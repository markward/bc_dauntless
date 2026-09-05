"""The migration's guards. A missed site fails SILENTLY -- a texture that
does not load, a mission that does not list -- so these are structural.

Both Python guards parse rather than grep. A grep for `sdk/` flags every
docstring in engine/ that cites sdk/Build/scripts/... -- there are dozens --
and it MISSES engine/dev_keybindings.py's nine-line constant, where no single
line holds both the root and the segment. A guard that cries wolf gets
deleted, and one that misses the hardest case is worse than none.

What the scan reaches, and what it does not. `ast.walk` sees every string
constant in a module, not just assignment targets, so an assigned string
(`X = "game/..."`), a bare string that is not a docstring, and a string
buried in a dict or list literal are all caught the same way -- and so is
an f-string SEGMENT that itself begins "game/", because each literal piece
of an f-string is its own constant node. What it cannot see is a spelling
assembled at runtime: an f-string substitution that only completes the
prefix once formatted (`f"ga{x}me/data"`) or two constants joined by `+`
(`"ga" + "me"`) never appear as a single string constant to walk, so
neither is caught. That is an inherent limit of scanning string constants,
not a bug in this guard, and it is not worth chasing -- nobody spells a BC
root that way by accident, and anybody doing it on purpose to dodge the
guard has bigger problems. The `# paths-guard:` escape is matched per
LINE, by substring: a line carrying the comment silences every offending
constant that line contains, not just the one the reason was written
about, so keep escaped lines to one offender each if the distinction ever
matters. The C++ guard's comment handling is narrower still -- it skips
`//` line comments only; a `/* ... */` block comment containing `"game/`
would be flagged as a real offender. None exists in the tree today, so
this has not needed the `# paths-guard:` escape yet, but a future block
comment quoting a game/ path for documentation purposes would need one.

Guard 3 (test_no_engine_module_captures_a_path_at_import) has a narrower
reach than the string-constant guards above: it walks `tree.body`, i.e.
MODULE-LEVEL statements only, and only `ast.Assign`/`ast.AnnAssign` among
those. A call to `paths.game_asset(...)` (or any watched accessor) captured
in a class-body attribute, a function's default argument value, a decorator
argument, or inside a module-level `if`/`for`/`try` block all evaluate at
import time exactly like a bare module-level assignment does, and none of
those shapes is an `ast.Assign`/`ast.AnnAssign` directly under `tree.body`,
so all four evade this guard. Checked: zero current violations of any of
these shapes exist in engine/ today. Widening the guard to catch them is
future work, not done here.
"""
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The one module allowed to know how BC content is laid out.
_AUTHORITY = PROJECT_ROOT / "engine" / "paths.py"

# An opt-out for a string that DESCRIBES the layout rather than building a
# path -- e.g. the Ghidra export manifest's portable "source_binary" label,
# or a test fixture that deliberately builds a fake install tree. Matched as
# a PREFIX, not a fixed string, so the reason after the colon can vary --
# it's a comment, not a file allowlist, so the exemption sits next to the
# reason it applies.
_ESCAPE = "# paths-guard:"

_BAD_EXACT = {"game", "sdk"}
_BAD_PREFIX = ("game/", "sdk/", "game\\", "sdk\\")

# tools/probes/ holds Python 1.5 sources -- they are injected into the
# ORIGINAL stbc.exe, which embeds Python 1.5 (see CLAUDE.md), so modern
# `ast` cannot read them and never will. Skipping them silently would let a
# BC path hide there; the zone is bounded and checked below.
UNPARSEABLE_ZONE = PROJECT_ROOT / "tools" / "probes"


def _sources():
    """engine/ and tools/ entirely, plus conftest and the project-root SDK
    shims -- but not tests/ at large: a test fixture that builds a fake
    install tree is the one legitimate reason to spell the layout.

    The root shims (App.py, LoadBridge.py, LoadDamageHitSounds.py, ...) are
    scanned because both SDK finders resolve them BEFORE the SDK, so one
    hardcoding a BC root would silently win over the real thing.
    """
    for sub in ("engine", "tools"):
        for path in (PROJECT_ROOT / sub).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path
    yield from sorted(PROJECT_ROOT.glob("*.py"))
    yield PROJECT_ROOT / "tests" / "conftest.py"


def _parse_or_skip(path, unparseable):
    """tools/probes/ holds Python 1.5 sources -- they are injected into the
    ORIGINAL stbc.exe, which embeds Python 1.5, so modern ast cannot read them
    and never will. Skipping them silently would let a BC path hide there;
    recording them lets the test below assert the skip stays bounded."""
    try:
        return ast.parse(path.read_text(errors="replace"), filename=str(path))
    except SyntaxError:
        unparseable.append(path)
        return None


def _docstring_ids(tree):
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def _spells_a_root(value: str) -> bool:
    return value in _BAD_EXACT or value.startswith(_BAD_PREFIX)


def test_no_python_source_spells_a_bc_root():
    offenders = []
    for path in _sources():
        if path == _AUTHORITY or not path.exists():
            continue
        text = path.read_text(errors="replace")
        lines = text.splitlines()
        # Unparseable sources (the Python 1.5 probes) are a real finding on
        # their own -- test_the_only_unparseable_sources_are_the_python_1_5_
        # probes below asserts the skip stays bounded to that zone. This test
        # only cares about the strings it CAN read, so the discard list here
        # is scratch, not tracked.
        tree = _parse_or_skip(path, [])
        if tree is None:
            continue
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            if id(node) in docs or not _spells_a_root(node.value):
                continue
            line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if _ESCAPE in line:
                continue
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                f"{node.value[:60]!r}")
    assert offenders == [], (
        "these spell a BC root instead of asking engine.paths "
        f"(add '{_ESCAPE} <reason>' if the string is a label, not a path):\n"
        + "\n".join(offenders))


def test_the_only_unparseable_sources_are_the_python_1_5_probes():
    """A guard that silently skips what it cannot parse is not a guard. The
    skip is legitimate only inside tools/probes/; anywhere else an unparseable
    file is a real syntax error this suite should surface."""
    unparseable = []
    for path in _sources():
        if path.exists():
            _parse_or_skip(path, unparseable)
    stray = [str(p.relative_to(PROJECT_ROOT)) for p in unparseable
             if UNPARSEABLE_ZONE not in p.parents]
    assert stray == [], (
        "these files could not be parsed and are NOT Python 1.5 probes, so the "
        "path guard silently skipped them:\n" + "\n".join(stray))


def test_no_engine_module_captures_a_path_at_import():
    """The trap that would make a first-run picker impossible.

    A module-level `X = paths.game_asset(...)` is evaluated at import, so it
    still points at the old install after the player chooses a folder. There
    were eight of these; engine/dev_keybindings.py's spanned nine lines.
    """
    watched = {"game_root", "sdk_root", "sdk_scripts", "sdk_data", "game_asset"}
    offenders = []
    for path in (PROJECT_ROOT / "engine").rglob("*.py"):
        if "__pycache__" in path.parts or path == _AUTHORITY:
            continue
        tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
        for node in tree.body:                       # module level ONLY
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name in watched:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                        f"module-level {name}()")
    assert offenders == [], (
        "paths must resolve at USE, never at import -- these are captured "
        "when the module loads and would be stale after the first-run "
        "picker:\n" + "\n".join(offenders))


def test_no_cpp_source_spells_a_game_prefix():
    allow = {PROJECT_ROOT / "native" / "src" / "renderer" / "asset_path.cc",
             PROJECT_ROOT / "native" / "src" / "renderer" / "include"
             / "renderer" / "asset_path.h"}
    offenders = []
    for cpp_root in (PROJECT_ROOT / "native" / "src",
                      PROJECT_ROOT / "native" / "tools"):
        for pattern in ("*.cc", "*.h", "*.mm"):
            for path in cpp_root.rglob(pattern):
                if path in allow:
                    continue
                for n, line in enumerate(
                        path.read_text(errors="replace").splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("//") or _ESCAPE in line:
                        continue
                    if '"game/' in line:
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{n}: {stripped}")
    assert offenders == [], (
        'these carry a literal "game/" prefix instead of routing through '
        "renderer::resolve_asset_path:\n" + "\n".join(offenders))
