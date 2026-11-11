"""The game never reads the BC SDK (spec 2026-11-11-no-sdk-runtime, decision 1).

The SDK is a development requirement only: the dev chain lives in
tools/dev_sdk.py, and the SDK's Custom/Tutorial sample is a TEST fixture
(decision 8). These guards PARSE rather than grep, so a docstring that
mentions an SDK file never trips them, and a real import can never hide.

What they cover: nothing the game ships (engine/, the project-root shims,
the runtime tools scripts/package.py copies) imports the dev SDK accessor
or registers a fixture tree, engine.paths has no SDK surface left to call,
and the packager does not ship the dev accessor.
"""
import ast
import importlib.util
from pathlib import Path

from engine import paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SDK_SURFACE = ("sdk_root", "sdk_scripts", "sdk_scripts_in", "sdk_data",
                "validate_sdk_root", "SDK_MARKERS")


def _package():
    spec = importlib.util.spec_from_file_location(
        "dauntless_package_script_no_sdk", PROJECT_ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shipped_sources():
    """Every Python file a packaged game runs: engine/, the root shims and
    the runtime tools scripts/package.py copies into the install."""
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path
    yield from sorted(PROJECT_ROOT.glob("*.py"))
    for name in _package()._RUNTIME_TOOLS:
        yield PROJECT_ROOT / "tools" / name


def _game_sources():
    """Everything outside tests/: the shipped sources plus tools/ and
    scripts/ (a developer tool must not register a fixture either)."""
    seen = set()
    for path in _shipped_sources():
        seen.add(path)
        yield path
    for sub in ("tools", "scripts"):
        for path in sorted((PROJECT_ROOT / sub).rglob("*.py")):
            if "__pycache__" in path.parts or path in seen:
                continue
            yield path


def _parse(path):
    """The module's AST, or None for a Python 1.5 probe (tools/probes/),
    which modern ast cannot read; test_path_indirection bounds that zone."""
    try:
        return ast.parse(path.read_text(errors="replace"), filename=str(path))
    except SyntaxError:
        return None


def _imports_dev_sdk(tree) -> list:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "tools.dev_sdk" for a in node.names):
                hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "tools.dev_sdk":
                hits.append(node.lineno)
            elif node.module == "tools" and any(
                    a.name == "dev_sdk" for a in node.names):
                hits.append(node.lineno)
    return hits


def test_engine_never_imports_dev_sdk():
    offenders = []
    for path in _shipped_sources():
        tree = _parse(path)
        assert tree is not None, f"{path} must be modern Python"
        offenders += [f"{path.relative_to(PROJECT_ROOT)}:{line}"
                      for line in _imports_dev_sdk(tree)]
    assert offenders == [], (
        "the game must never reach the BC SDK; tools/dev_sdk.py is the "
        "developer chain only:\n" + "\n".join(offenders))


def test_engine_never_registers_fixture_trees():
    offenders = []
    for path in _game_sources():
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else None)
            if name == "add_fixture_tree":
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], (
        "stock_scripts.add_fixture_tree is TEST-ONLY (decision 8):\n"
        + "\n".join(offenders))


def test_paths_has_no_sdk_surface():
    left = [name for name in _SDK_SURFACE if hasattr(paths, name)]
    assert left == [], f"engine.paths still exposes SDK surface: {left}"
    assert "sdk" not in paths.ENV_VARS  # paths-guard: kind label
    assert "sdk" not in paths.CLI_FLAGS  # paths-guard: kind label


def test_package_does_not_ship_dev_sdk():
    assert "dev_sdk.py" not in _package()._RUNTIME_TOOLS
