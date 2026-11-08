"""Guard: no function-local imports on the per-frame / per-tick hot paths.

A function-local ``from X import Y`` costs ~128 ns per call; on these paths
that was ~1.5 M calls per 900 frames. Hoist to module level (as MODULE
imports, so tests that monkeypatch a name on its home module still work), or
keep it local when it is a real import cycle and mark the line with
``# hot-import: <reason>``.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = "# hot-import:"

HOT_MODULES = [
    "engine/systems/frames.py",
    "engine/appc/sensor_media.py",
    "engine/systems/profile.py",
    "engine/rocks/far_tier.py",
    "engine/audio/attached_sources.py",
    "engine/appc/perception.py",
]
HOT_FUNCTIONS = {
    "engine/host_loop.py": ["_pump_contacts", "_sync_instance_transforms", "tick_audio"],
}


def _offenders(source, rel, only=None):
    tree = ast.parse(source)
    lines = source.splitlines()
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if only is not None and fn.name not in only:
            continue
        for node in ast.walk(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if MARKER not in lines[node.lineno - 1]:
                    found.append(f"{rel}:{node.lineno}")
    return sorted(set(found))


def test_hot_modules_exist():
    for rel in list(HOT_MODULES) + list(HOT_FUNCTIONS):
        assert (ROOT / rel).is_file(), rel
    for rel, names in HOT_FUNCTIONS.items():
        tree = ast.parse((ROOT / rel).read_text())
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert set(names) <= defined, (rel, set(names) - defined)


def test_the_guard_sees_a_planted_offender():
    src = "def f():\n    from x import y\n    return y\n"
    assert _offenders(src, "planted.py") == ["planted.py:2"]
    ok = "def f():\n    from x import y  # hot-import: cycle\n    return y\n"
    assert _offenders(ok, "planted.py") == []


def test_no_function_local_imports_on_hot_paths():
    offenders = []
    for rel in HOT_MODULES:
        offenders += _offenders((ROOT / rel).read_text(), rel)
    for rel, names in HOT_FUNCTIONS.items():
        offenders += _offenders((ROOT / rel).read_text(), rel, set(names))
    assert not offenders, (
        "function-local import on a hot path (hoist it, or mark a real cycle "
        "with '# hot-import: <reason>'):\n" + "\n".join(offenders)
    )
