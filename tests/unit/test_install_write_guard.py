"""Static guard: nothing in engine/ or a root shim writes to the install folder.

Per-user data lives under the platform user dirs (engine.paths). A function
that writes AND derives a path from the project root / __file__ / the cwd is how
a packaged build ends up writing into a read-only install, so this is structural.

Scope is engine/ and the project-root *.py shims only. `_sources()` also yields
tools/ and tests/conftest.py, which legitimately write into the repo.

_ALLOWED_REPO_WRITERS is per FUNCTION ("module:function"), dev authoring into
the repo; allowlisted functions are skipped by BOTH rules, and the rest of an
allowlisted module is still checked. Anything else flagged is a real
install-folder write to fix, not to allowlist.

KNOWN LIMIT (Ruling 12): the scan is per module. A non-writing helper module
that builds a project-derived path which a writer in ANOTHER module consumes is
not seen; a cross-module scan would be too noisy. Task 12's dynamic guard (runs
the writers against a read-only install) is the net for that case. Also unseen:
paths assembled from several modules or from computed names.
"""
import ast

import pytest

from tests.unit.test_path_indirection import PROJECT_ROOT, _parse_or_skip, _sources

# "module:function" -> reason. Per-function so an allowlisted module's future
# functions are still checked. Allowlisted functions are skipped by BOTH rules.
_ALLOWED_REPO_WRITERS: dict = {
    "engine/systems/map.py:map_dir":
        "system-map authoring: save() writes the checked-in maps beside "
        "__file__; no engine caller of save()",
    "engine/appc/override_routing.py:HardpointOverridesFileTarget":
        "V1 hardpoint authoring: _PATH is beside __file__, reaches write() via "
        "self.path; refuses when packaged",
    "engine/ui/ship_icons.py:icon_path_for_species":
        "dev-checkout-only inspection PNG (guarded by dev_mode.is_enabled() "
        "and not paths.is_packaged())",
    "engine/ui/weapon_icons.py:export_reference_pngs":
        "tool-only: writes curated references into the repo; no runtime caller "
        "(trace_atlas, the SVG generator, writes to paths.cache_dir())",
}

_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "unlink", "touch"}
_OS_WRITES = {"makedirs", "replace", "rename", "remove", "mkdir", "unlink", "rmdir"}
_SHUTIL_WRITES = {"move", "rmtree"}
_OPEN_MODULES = {"io", "codecs"}
_PROJECT_NAMES = {"PROJECT_ROOT", "_PROJECT_ROOT", "__file__"}
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _scoped_sources():
    for path in _sources():
        if not path.exists():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if rel.parts[0] == "engine" or (len(rel.parts) == 1 and rel.suffix == ".py"):
            yield path, rel.as_posix()


def _mode_writes(call, mode_index):
    """open()-style call: a write if the mode has w/a/x/+ OR is not a literal
    (a variable must not hide a writer). No mode argument means read."""
    mode = None
    if len(call.args) > mode_index:
        mode = call.args[mode_index]
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(c in mode.value for c in "wax+")
    return True


def _is_write_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name) and f.id == "open":
        return _mode_writes(node, 1)
    if isinstance(f, ast.Attribute):
        if f.attr == "open":
            if isinstance(f.value, ast.Name) and f.value.id in _OPEN_MODULES:
                return _mode_writes(node, 1)
            if not isinstance(f.value, ast.Name) or f.value.id not in (
                    "os", "webbrowser", "tarfile", "zipfile", "gzip"):
                return _mode_writes(node, 0)  # Path(...).open(mode)
            return False
        if f.attr in _WRITE_METHODS:
            return True
        if isinstance(f.value, ast.Name):
            if f.value.id == "os" and f.attr in _OS_WRITES:
                return True
            if f.value.id == "shutil" and (f.attr.startswith("copy")
                                           or f.attr in _SHUTIL_WRITES):
                return True
    return False


def _is_relative_literal(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value != "" and not node.value.startswith(("/", "~")))


def _is_relative_write(node):
    """A write whose target is a relative string literal, i.e. the cwd."""
    if not _is_write_call(node):
        return False
    f = node.func
    if isinstance(f, ast.Name):  # open("x", "w")
        return bool(node.args) and _is_relative_literal(node.args[0])
    if isinstance(f.value, ast.Call):  # Path("x").write_text(...)
        inner = f.value
        name = (inner.func.id if isinstance(inner.func, ast.Name)
                else getattr(inner.func, "attr", ""))
        return (name in ("Path", "PurePath") and bool(inner.args)
                and _is_relative_literal(inner.args[0]))
    if isinstance(f.value, ast.Name):  # io.open / os.makedirs / shutil.copy
        return bool(node.args) and _is_relative_literal(node.args[0])
    return False


def _is_project_ref(node):
    if isinstance(node, ast.Name) and node.id in _PROJECT_NAMES:
        return True
    if isinstance(node, ast.Attribute) and node.attr in _PROJECT_NAMES:
        return True
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "getcwd":
            return True
        if isinstance(f, ast.Attribute):
            if (f.attr == "cwd" and isinstance(f.value, ast.Name)
                    and f.value.id == "Path"):
                return True
            if (f.attr == "getcwd" and isinstance(f.value, ast.Name)
                    and f.value.id == "os"):
                return True
            if (f.attr == "abspath" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                return True
    return False


def _own_nodes(func):
    """Nodes of `func` excluding the bodies of nested functions."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _FUNCS):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _parsed(path):
    return _parse_or_skip(path, [])


def _function_offenses(tree, rel, allowed):
    """Rule 1 findings for one module: 'rel:line: name (why)'."""
    out = []
    module_writes = any(_is_write_call(n) for n in ast.walk(tree))
    for fn in ast.walk(tree):
        if not isinstance(fn, _FUNCS) or f"{rel}:{fn.name}" in allowed:
            continue
        nodes = list(_own_nodes(fn))
        if any(_is_relative_write(n) for n in nodes):
            out.append(f"{rel}:{fn.lineno}: {fn.name} (cwd-relative write)")
        elif module_writes and any(_is_project_ref(n) for n in nodes):
            out.append(f"{rel}:{fn.lineno}: {fn.name} (project/cwd path in a writing module)")
    return out


def _tainted_constants(tree):
    """Module-level names derived from the project root, transitively."""
    tainted = {}
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
            continue
        derived = any(
            _is_project_ref(n) or (isinstance(n, ast.Name) and n.id in tainted)
            for n in ast.walk(stmt.value))
        if not derived:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for t in targets:
            if isinstance(t, ast.Name):
                tainted[t.id] = stmt.lineno
    return tainted


def _constant_offenses(tree, rel, allowed):
    """Functions reading a tainted constant while writing, plus classes whose
    methods together write and read a tainted constant / project ref (taint
    crossing methods through an attribute: `self.path = path`)."""
    out = []
    tainted = _tainted_constants(tree)
    for fn in ast.walk(tree):
        if not isinstance(fn, _FUNCS) or f"{rel}:{fn.name}" in allowed:
            continue
        nodes = list(_own_nodes(fn))
        if not any(_is_write_call(n) for n in nodes):
            continue
        for n in nodes:
            if isinstance(n, ast.Name) and n.id in tainted:
                out.append(f"{rel}:{fn.lineno}: {fn.name} (writer reads {n.id})")
                break
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or f"{rel}:{cls.name}" in allowed:
            continue
        nodes = [n for m in cls.body if isinstance(m, _FUNCS)
                 for n in _own_nodes(m)]
        if not any(_is_write_call(n) for n in nodes):
            continue
        if any(_is_project_ref(n)
               or (isinstance(n, ast.Name) and n.id in tainted) for n in nodes):
            out.append(f"{rel}:{cls.lineno}: {cls.name} (class writes and "
                       "reads a project-derived path)")
    return out


def test_no_function_writes_to_a_project_derived_path():
    offenders = []
    for path, rel in _scoped_sources():
        tree = _parsed(path)
        if tree is not None:
            offenders += _function_offenses(tree, rel, _ALLOWED_REPO_WRITERS)
    assert offenders == [], (
        "install-folder / cwd writes (write under engine.paths user dirs instead):\n"
        + "\n".join(offenders))


def test_no_module_level_project_path_constant_in_a_writing_module():
    """A project-derived module constant is only a hazard when a function that
    writes can read it; a read-only constant (curated assets) or an unused one
    is not an install-folder write."""
    offenders = []
    for path, rel in _scoped_sources():
        tree = _parsed(path)
        if tree is not None:
            offenders += _constant_offenses(tree, rel, _ALLOWED_REPO_WRITERS)
    assert offenders == [], (
        "module-level project-derived path constants read by a function that "
        "writes files:\n" + "\n".join(offenders))


def test_allowlist_has_no_stale_entries():
    """Each entry must name an existing function/class that the rules WOULD
    flag without it, so an entry that no longer protects anything is caught."""
    stale = []
    for key in _ALLOWED_REPO_WRITERS:
        rel, _, name = key.partition(":")
        path = PROJECT_ROOT / rel
        if not path.exists():
            stale.append(f"{key}: module missing")
            continue
        tree = _parsed(path)
        flagged = set()
        if tree is not None:
            for h in (_function_offenses(tree, rel, set())
                      + _constant_offenses(tree, rel, set())):
                flagged.add(h.split()[1])
        if name not in flagged:
            stale.append(f"{key}: would not be flagged without its entry")
    assert stale == [], "stale allowlist entries:\n" + "\n".join(stale)


# --- synthetic snippets: every detection must fire ---------------------------

def _offenses(src, allowed=()):
    tree = ast.parse(src)
    return (_function_offenses(tree, "m.py", set(allowed))
            + _constant_offenses(tree, "m.py", set(allowed)))


@pytest.mark.parametrize("body", [
    "paths.PROJECT_ROOT",
    "engine.paths.PROJECT_ROOT",
    "getcwd()",
    "os.getcwd()",
    "Path.cwd()",
])
def test_project_ref_shapes_fire(body):
    src = f"def f():\n    p = {body}\n    open(p, 'w')\n"
    assert _offenses(src), body


@pytest.mark.parametrize("stmt", [
    "open('log.txt', 'w')",
    "Path('saves').mkdir()",
    "Path('x').write_text('y')",
    "os.makedirs('saves')",
    "io.open('log.txt', 'a')",
])
def test_relative_literal_writes_fire(stmt):
    assert _offenses(f"def f():\n    {stmt}\n"), stmt


@pytest.mark.parametrize("stmt", [
    "p.open('w')",
    "io.open(p, 'w')",
    "codecs.open(p, 'w')",
    "p.touch()",
    "shutil.rmtree(p)",
    "os.mkdir(p)",
    "os.unlink(p)",
    "os.rmdir(p)",
    "open(p, mode)",
])
def test_write_verbs_are_writes(stmt):
    tree = ast.parse(stmt)
    assert any(_is_write_call(n) for n in ast.walk(tree)), stmt


@pytest.mark.parametrize("stmt", ["open(p)", "open(p, 'r')", "p.open('rb')",
                                  "os.path.join(a, b)"])
def test_reads_are_not_writes(stmt):
    assert not any(_is_write_call(n) for n in ast.walk(ast.parse(stmt)))


def test_per_function_allowlist_skips_only_that_function():
    src = ("def ok():\n    open('a', 'w')\n"
           "def bad():\n    open('b', 'w')\n")
    assert len(_offenses(src)) == 2
    hits = _offenses(src, allowed={"m.py:ok"})
    assert len(hits) == 1 and "bad" in hits[0]


# --- class-scoped taint (taint crossing methods through an attribute) --------

_ATTR_SHAPE = (
    "import os\n"
    "_PATH = os.path.join(os.path.dirname(__file__), 'x.py')\n"
    "class Target:\n"
    "    def __init__(self, path=_PATH):\n"
    "        self.path = path\n"
    "    def write(self, text):\n"
    "        with open(self.path, 'w') as fh:\n"
    "            fh.write(text)\n"
)


def test_taint_through_default_arg_and_self_attribute_fires():
    hits = _offenses(_ATTR_SHAPE)
    assert any(h.split()[1] == "Target" for h in hits), hits


def test_class_allowlist_entry_silences_it():
    assert _offenses(_ATTR_SHAPE, allowed={"m.py:Target"}) == []


def test_override_routing_class_is_allowlisted_and_would_be_flagged():
    key = "engine/appc/override_routing.py:HardpointOverridesFileTarget"
    assert key in _ALLOWED_REPO_WRITERS
    tree = _parsed(PROJECT_ROOT / "engine/appc/override_routing.py")
    unguarded = _function_offenses(tree, "engine/appc/override_routing.py", set())
    unguarded += _constant_offenses(tree, "engine/appc/override_routing.py", set())
    assert any(h.split()[1] == "HardpointOverridesFileTarget" for h in unguarded)
