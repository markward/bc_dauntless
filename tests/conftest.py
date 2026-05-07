import ast
import importlib.abc
import importlib.machinery
import sys
import types
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"


class _MoveGlobalsToTop(ast.NodeTransformer):
    """Move global declarations to the top of each function body.

    SDK scripts were written for Python 1.5/2.x, which allowed using a name
    before its global declaration in the same function. Python 3 treats this
    as a SyntaxError at compile time.
    """
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        globals_stmts = [s for s in node.body if isinstance(s, ast.Global)]
        other_stmts = [s for s in node.body if not isinstance(s, ast.Global)]
        node.body = globals_stmts + other_stmts
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


class _SDKLoader(importlib.abc.Loader):
    """Load an SDK script with Python 2 compatibility fixes applied."""

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
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        exec(code, module.__dict__)


class _SDKFinder(importlib.abc.MetaPathFinder):
    """Find modules in sdk/Build/scripts/ and load them via _SDKLoader."""

    def find_spec(self, fullname, path, target=None):
        # Project root modules take priority — let normal finders handle them
        project_module = PROJECT_ROOT / (fullname.replace(".", "/") + ".py")
        if project_module.exists():
            return None
        candidate = SDK_SCRIPTS / (fullname.replace(".", "/") + ".py")
        if candidate.exists():
            loader = _SDKLoader(str(candidate))
            return importlib.machinery.ModuleSpec(
                fullname, loader, origin=str(candidate)
            )
        return None


def pytest_configure(config):
    # Our App.py must shadow sdk/Build/scripts/App.py
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    # Install SDK finder before the default finders so SDK scripts get our
    # compatibility loader instead of the standard one.
    if not any(isinstance(f, _SDKFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _SDKFinder())

    # Stub out SDK modules that MissionLib imports but we don't implement yet
    _stub_modules = [
        "loadspacehelper",
        "Bridge",
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions",
        "Actions.MissionScriptActions",
    ]
    for name in _stub_modules:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
