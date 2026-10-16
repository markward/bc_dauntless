"""Static guard: nothing in engine/ or a root shim writes to the install folder.

Per-user data lives under the platform user dirs (engine.user_dirs). A function
that writes AND derives a path from the project root / __file__ / the cwd is how
a packaged build ends up writing into a read-only install, so this is structural.

Scope is engine/ and the project-root *.py shims only. `_sources()` also yields
tools/ and tests/conftest.py, which legitimately write into the repo.

Modules in _ALLOWED_REPO_WRITERS are dev authoring into the repo; anything else
this guard flags is a real install-folder write to fix, not to allowlist.
"""
import ast

import pytest

from tests.unit.test_path_indirection import PROJECT_ROOT, _parse_or_skip, _sources

_ALLOWED_REPO_WRITERS = {
    "engine/appc/override_routing.py":
        "V1 hardpoint authoring; _PATH is beside __file__",
    "engine/appc/decals_writer.py":
        "V3 dev authoring into the repo",
    "engine/bridge_editor/lighting_writer.py":
        "V4 dev authoring into the repo",
    "engine/ui/ship_icons.py":
        "dev-mode-only inspection PNG (Task 7)",
    "engine/systems/map.py":
        "system-map authoring: save() writes the checked-in maps beside __file__ "
        "(map_dir()); no runtime caller",
    "engine/ui/weapon_icons.py":
        "tool-only export_reference_pngs writes curated references into the repo",
}

_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "unlink"}
_OS_WRITES = {"makedirs", "replace", "rename", "remove"}
_SHUTIL_WRITES = {"move"}
_PROJECT_NAMES = {"PROJECT_ROOT", "_PROJECT_ROOT", "__file__"}
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _scoped_sources():
    for path in _sources():
        if not path.exists():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if rel.parts[0] == "engine" or (len(rel.parts) == 1 and rel.suffix == ".py"):
            yield path, rel.as_posix()


def _is_write_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name) and f.id == "open":
        mode = None
        if len(node.args) > 1:
            mode = node.args[1]
        for kw in node.keywords:
            if kw.arg == "mode":
                mode = kw.value
        return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                and any(c in mode.value for c in "wax+"))
    if isinstance(f, ast.Attribute):
        if f.attr in _WRITE_METHODS:
            return True
        if isinstance(f.value, ast.Name):
            if f.value.id == "os" and f.attr in _OS_WRITES:
                return True
            if f.value.id == "shutil" and (f.attr.startswith("copy")
                                           or f.attr in _SHUTIL_WRITES):
                return True
    return False


def _is_project_ref(node):
    if isinstance(node, ast.Name) and node.id in _PROJECT_NAMES:
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        f = node.func
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


def test_no_function_writes_to_a_project_derived_path():
    """Two shapes, both fail:
    - one function both writes and references the project root / cwd;
    - a path helper (e.g. `_save_dir`) references it in a module that writes
      elsewhere -- the writer reaches the install folder through the helper,
      which a same-function check alone cannot see."""
    offenders = []
    for path, rel in _scoped_sources():
        if rel in _ALLOWED_REPO_WRITERS:
            continue
        tree = _parsed(path)
        if tree is None or not any(_is_write_call(n) for n in ast.walk(tree)):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, _FUNCS):
                continue
            if any(_is_project_ref(n) for n in _own_nodes(fn)):
                offenders.append(f"{rel}:{fn.lineno}: {fn.name}")
    assert offenders == [], (
        "these functions reference the project root / __file__ / cwd in a "
        "module that writes files (write under engine.user_dirs instead):\n"
        + "\n".join(offenders))


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


def test_no_module_level_project_path_constant_in_a_writing_module():
    """A project-derived module constant is only a hazard when a function that
    writes can read it; a read-only constant (curated assets) or an unused one
    is not an install-folder write."""
    offenders = []
    for path, rel in _scoped_sources():
        if rel in _ALLOWED_REPO_WRITERS:
            continue
        tree = _parsed(path)
        if tree is None:
            continue
        tainted = _tainted_constants(tree)
        if not tainted:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, _FUNCS):
                continue
            nodes = list(_own_nodes(fn))
            if not any(_is_write_call(n) for n in nodes):
                continue
            for n in nodes:
                if isinstance(n, ast.Name) and n.id in tainted:
                    offenders.append(
                        f"{rel}:{tainted[n.id]}: {n.id} read by writer {fn.name}")
                    break
    assert offenders == [], (
        "module-level project-derived path constants read by a function that "
        "writes files:\n" + "\n".join(offenders))


def test_allowlist_has_no_stale_entries():
    stale = []
    for rel in _ALLOWED_REPO_WRITERS:
        path = PROJECT_ROOT / rel
        if not path.exists():
            stale.append(f"{rel}: missing")
            continue
        tree = _parsed(path)
        if tree is None or not any(_is_write_call(n) for n in ast.walk(tree)):
            stale.append(f"{rel}: no write call")
    assert stale == [], "stale allowlist entries:\n" + "\n".join(stale)
