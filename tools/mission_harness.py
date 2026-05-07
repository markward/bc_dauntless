"""
Mission Initialize harness for open_stbc.

Discovers all SDK mission scripts and attempts Initialize(pMission) on each,
reporting a ranked summary of failures.

Usage:
    uv run python tools/mission_harness.py
"""
import ast
import importlib
import importlib.abc
import importlib.machinery
import sys
import types
import warnings
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path whether run as script or imported in tests
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SDK_SCRIPTS = _PROJECT_ROOT / "sdk" / "Build" / "scripts"


def discover_missions() -> list[str]:
    """Return sorted list of dotted module names for all SDK mission scripts.

    A mission script is any .py file (not __init__.py) that contains the
    string 'def Initialize(pMission)'.  Episode-level scripts use
    'def Initialize(pEpisode)' and are therefore excluded automatically.
    """
    missions = []
    for py_file in sorted(SDK_SCRIPTS.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "def Initialize(pMission)" not in text:
            continue
        rel = py_file.relative_to(SDK_SCRIPTS)
        module_name = ".".join(rel.with_suffix("").parts)
        missions.append(module_name)
    return missions


# ── SDK compatibility machinery ───────────────────────────────────────────────
# Mirrors tests/conftest.py.  Kept separate so the harness has no pytest dep.

class _MoveGlobalsToTop(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        globals_stmts = [s for s in node.body if isinstance(s, ast.Global)]
        other_stmts = [s for s in node.body if not isinstance(s, ast.Global)]
        node.body = globals_stmts + other_stmts
        return node
    visit_AsyncFunctionDef = visit_FunctionDef


class _FixDottedImport(ast.NodeTransformer):
    def visit_Module(self, node):
        self.generic_visit(node)
        node.body.insert(0, ast.Import(
            names=[ast.alias(name="importlib", asname="_sdk_importlib")]
        ))
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and len(node.args) == 1
            and not node.keywords
        ):
            return ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="_sdk_importlib", ctx=ast.Load()),
                    attr="import_module",
                    ctx=ast.Load(),
                ),
                args=node.args,
                keywords=[],
            )
        return node


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _SDKLoader(importlib.abc.Loader):
    def __init__(self, path: str):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        source = source.expandtabs(4)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=self.path)
        tree = _MoveGlobalsToTop().visit(tree)
        tree = _FixDottedImport().visit(tree)
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        exec(code, module.__dict__)


class _SDKFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        rel = fullname.replace(".", "/")
        if (_PROJECT_ROOT / (rel + ".py")).exists():
            return None
        if (_PROJECT_ROOT / rel).is_dir() and (_PROJECT_ROOT / rel / "__init__.py").exists():
            return None
        candidate = SDK_SCRIPTS / (rel + ".py")
        if candidate.exists():
            loader = _SDKLoader(str(candidate))
            return importlib.machinery.ModuleSpec(fullname, loader, origin=str(candidate))
        pkg_init = SDK_SCRIPTS / rel / "__init__.py"
        if pkg_init.exists():
            loader = _SDKLoader(str(pkg_init))
            spec = importlib.machinery.ModuleSpec(fullname, loader, origin=str(pkg_init))
            spec.submodule_search_locations = [str(pkg_init.parent)]
            return spec
        return None


_BASELINE_MODULES: set[str] = set()


def setup_sdk() -> None:
    """Install SDK finder and stub modules. Call once before run_mission()."""
    global _BASELINE_MODULES

    if not any(isinstance(f, _SDKFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _SDKFinder())

    _callable_stubs = ["loadspacehelper", "LoadBridge"]
    for name in _callable_stubs:
        if name not in sys.modules:
            sys.modules[name] = _StubModule(name)

    if "Bridge" not in sys.modules:
        sys.modules["Bridge"] = types.ModuleType("Bridge")
    if "Bridge.HelmMenuHandlers" not in sys.modules:
        _helm = _StubModule("Bridge.HelmMenuHandlers")
        sys.modules["Bridge.HelmMenuHandlers"] = _helm
        sys.modules["Bridge"].HelmMenuHandlers = _helm  # type: ignore[attr-defined]

    _plain_stubs = [
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions",
        "Actions.MissionScriptActions",
    ]
    for name in _plain_stubs:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    _BASELINE_MODULES = set(sys.modules.keys())


def run_mission(module_name: str) -> tuple[str, Exception | None]:
    """Import module_name and call Initialize(pMission).

    Returns ("pass", None) on success or ("fail", exc) on any exception.
    Cleans up all sys.modules entries added during the run so each mission
    starts from the same baseline state.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    try:
        mod = importlib.import_module(module_name)
        mod.Initialize(mission)
        return ("pass", None)
    except Exception as exc:
        return ("fail", exc)
    finally:
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _BASELINE_MODULES]:
            del sys.modules[key]


def main() -> None:
    setup_sdk()
    missions = discover_missions()

    print("open_stbc mission harness")
    print("=" * 50)
    print(f"Found {len(missions)} missions\n")
    print("Running Initialize()...\n")

    results: dict[str, tuple[str, Exception | None]] = {}
    for name in missions:
        status, exc = run_mission(name)
        results[name] = (status, exc)
        marker = "PASS" if status == "pass" else "FAIL"
        if exc:
            err_line = str(exc).splitlines()[0][:90]
            print(f"  {marker}  {name}")
            print(f"         {type(exc).__name__}: {err_line}")
        else:
            print(f"  {marker}  {name}")

    passed = sum(1 for s, _ in results.values() if s == "pass")
    failed = len(results) - passed
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed of {len(results)} total")

    if failed:
        errors: Counter[str] = Counter()
        for status, exc in results.values():
            if exc is not None:
                key = f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}"
                errors[key] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")


if __name__ == "__main__":
    main()
