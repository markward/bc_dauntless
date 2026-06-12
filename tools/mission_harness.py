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
import re
import signal
import sys
import types
import warnings
from collections import Counter
from pathlib import Path

_MISSION_TIMEOUT = 15  # seconds per mission before declaring a hang

# Ensure project root is on sys.path whether run as script or imported in tests
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SDK_SCRIPTS = _PROJECT_ROOT / "sdk" / "Build" / "scripts"

_PY2_OCTAL = re.compile(r'(?<![\w.])0([0-7]+)\b')
_PY2_RAISE = re.compile(r'^(\s*raise\s+\w[\w.]*)\s*,\s*(.*)', re.MULTILINE)
_PY2_PRINT_FILE = re.compile(r'^(\s*)print\s*>>\s*(\S+)\s*,\s*(.*?)\s*$', re.MULTILINE)
_PY2_PRINT_STMT = re.compile(r'^(\s*)print\s+(?!\()(.+?)\s*$', re.MULTILINE)
_PY2_PRINT_BARE = re.compile(r'^(\s*)print\s*$', re.MULTILINE)


def _fix_py2_syntax(source: str) -> str:
    source = source.replace('<>', '!=')
    source = re.sub(r'\.has_key\s*\(', '.__contains__(', source)
    source = _PY2_RAISE.sub(lambda m: m.group(1) + '(' + m.group(2).rstrip() + ')', source)
    source = _PY2_OCTAL.sub(
        lambda m: '0o' + m.group(1) if any(c != '0' for c in m.group(1)) else m.group(0),
        source,
    )
    source = _PY2_PRINT_FILE.sub(r'\1print(\3, file=\2)', source)
    source = _PY2_PRINT_STMT.sub(r'\1print(\2)', source)
    source = _PY2_PRINT_BARE.sub(r'\1print()', source)
    return source


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
    @staticmethod
    def _hoist_globals(stmts):
        extracted = []
        remaining = []
        for stmt in stmts:
            if isinstance(stmt, ast.Global):
                extracted.append(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                remaining.append(stmt)
            else:
                for attr in ('body', 'orelse', 'finalbody'):
                    child = getattr(stmt, attr, None)
                    if child:
                        g, c = _MoveGlobalsToTop._hoist_globals(child)
                        extracted.extend(g)
                        setattr(stmt, attr, c)
                if isinstance(stmt, ast.Try):
                    for handler in stmt.handlers:
                        g, c = _MoveGlobalsToTop._hoist_globals(handler.body)
                        extracted.extend(g)
                        handler.body = c
                remaining.append(stmt)
        return extracted, remaining

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        globals_stmts, other_stmts = self._hoist_globals(node.body)
        node.body = globals_stmts + other_stmts
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


class _FixPy2Sort(ast.NodeTransformer):
    """Rewrite x.sort(cmp_func) → x.sort(key=functools.cmp_to_key(cmp_func))."""

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "sort"
            and len(node.args) == 1
            and not node.keywords
        ):
            cmp_arg = node.args[0]
            cmp_to_key = ast.Call(
                func=ast.Attribute(
                    value=ast.Call(
                        func=ast.Name(id="__import__", ctx=ast.Load()),
                        args=[ast.Constant(value="functools")],
                        keywords=[],
                    ),
                    attr="cmp_to_key",
                    ctx=ast.Load(),
                ),
                args=[cmp_arg],
                keywords=[],
            )
            return ast.Call(
                func=node.func,
                args=[],
                keywords=[ast.keyword(arg="key", value=cmp_to_key)],
            )
        return node


class _FixPy2DictIterMutation(ast.NodeTransformer):
    """Wrap ``for X in someDict.keys():`` (and ``.values()`` / ``.items()``)
    in ``list(...)``.

    Python 1.5 and 2.x returned a list from these methods, so SDK code that
    ``del``-s entries mid-loop worked. Python 3 returns a view and raises
    ``RuntimeError: dictionary changed size during iteration``. Wrapping
    the call in ``list(...)`` makes the SDK pattern compatible without
    forking SDK files. Observed bite site: AI/Preprocessors.py:871
    (FireScript.ChooseTargetSubsystem prunes stale subsystem ratings).
    """

    _DICT_METHODS = ("keys", "values", "items")

    def visit_For(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr in self._DICT_METHODS
            and not node.iter.args
            and not node.iter.keywords
        ):
            node.iter = ast.Call(
                func=ast.Name(id="list", ctx=ast.Load()),
                args=[node.iter],
                keywords=[],
            )
        return node


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
            _n = '_sdk_import_name'
            return ast.Call(
                func=ast.Lambda(
                    args=ast.arguments(
                        posonlyargs=[], args=[ast.arg(arg=_n)],
                        vararg=None, kwonlyargs=[], kw_defaults=[],
                        kwarg=None, defaults=[]
                    ),
                    body=ast.IfExp(
                        test=ast.Call(
                            func=ast.Name(id='isinstance', ctx=ast.Load()),
                            args=[ast.Name(id=_n, ctx=ast.Load()), ast.Name(id='str', ctx=ast.Load())],
                            keywords=[]
                        ),
                        body=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="_sdk_importlib", ctx=ast.Load()),
                                attr="import_module", ctx=ast.Load(),
                            ),
                            args=[ast.Name(id=_n, ctx=ast.Load())],
                            keywords=[],
                        ),
                        orelse=ast.Name(id=_n, ctx=ast.Load()),
                    )
                ),
                args=node.args,
                keywords=[],
            )
        return node


class _Stub:
    """Recursive stub for unimplemented engine objects."""
    def __getattr__(self, name): return _Stub()
    def __call__(self, *args, **kwargs): return _Stub()
    def __bool__(self): return True
    def __hash__(self): return id(self)
    def __getitem__(self, key): return _Stub()
    def __setitem__(self, key, value): pass
    def __delitem__(self, key): pass
    def __iter__(self): return iter([])
    def __len__(self): return 0
    def __int__(self): return 0
    def __float__(self): return 0.0
    def __index__(self): return 0
    def __add__(self, o): return o if isinstance(o, str) else 0
    def __radd__(self, o): return o if isinstance(o, str) else 0
    def __sub__(self, o): return 0
    def __rsub__(self, o): return 0
    def __mul__(self, o): return 0
    def __rmul__(self, o): return 0
    def __truediv__(self, o): return 0.0
    def __rtruediv__(self, o): return 0.0
    def __floordiv__(self, o): return 0
    def __rfloordiv__(self, o): return 0
    def __mod__(self, o): return "" if isinstance(o, (str, tuple)) else 0
    def __rmod__(self, o): return "" if isinstance(o, (str, tuple)) else 0
    def __neg__(self): return 0
    def __pos__(self): return 0
    def __abs__(self): return 0
    def __or__(self, o): return 0
    def __ror__(self, o): return 0
    def __and__(self, o): return 0
    def __rand__(self, o): return 0
    def __xor__(self, o): return 0
    def __rxor__(self, o): return 0
    def __lshift__(self, o): return 0
    def __rshift__(self, o): return 0
    def __invert__(self): return 0
    def __lt__(self, o): return False
    def __le__(self, o): return False
    def __gt__(self, o): return False
    def __ge__(self, o): return False
    def __eq__(self, o): return isinstance(o, type(self))
    def __ne__(self, o): return not isinstance(o, type(self))


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        return _Stub()


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, existing_module):
        self._module = existing_module
    def create_module(self, spec):
        return self._module
    def exec_module(self, module):
        pass


class _SDKLoader(importlib.abc.Loader):
    def __init__(self, path: str, also_register_as: str = None):
        self.path = path
        self.also_register_as = also_register_as

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        source = source.expandtabs(4)
        source = _fix_py2_syntax(source)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=self.path)
            tree = _MoveGlobalsToTop().visit(tree)
            tree = _FixDottedImport().visit(tree)
            tree = _FixPy2Sort().visit(tree)
            tree = _FixPy2DictIterMutation().visit(tree)
            ast.fix_missing_locations(tree)
            code = compile(tree, self.path, "exec")
        module.__dict__.setdefault('apply', lambda f, a=(), kw={}: f(*a, **kw))
        # SDK loadspacehelper.py:91 calls `reload(mod)` after ClearLocalTemplates()
        # to re-register hardpoint templates by re-running the module top-level.
        # A no-op stub silently leaves templates cleared.
        module.__dict__.setdefault('reload', importlib.reload)
        module.__dict__.setdefault('BORG', 0x00000200)  # QuickBattle.py omits this; BORG_CUBE = 0x200
        exec(code, module.__dict__)
        if self.also_register_as and self.also_register_as not in sys.modules:
            sys.modules[self.also_register_as] = module
            parent, _, attr = self.also_register_as.rpartition('.')
            if parent and parent in sys.modules:
                try:
                    setattr(sys.modules[parent], attr, module)
                except (AttributeError, TypeError):
                    pass


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
        # Submodule via explicit path: parent package has __path__ pointing into
        # an SDK directory (e.g. Characters → Bridge/Characters).
        if path:
            child = fullname.rpartition(".")[2]
            for _search_dir in path:
                _p = Path(_search_dir)
                if str(SDK_SCRIPTS) not in str(_p):
                    continue
                _cand = _p / (child + ".py")
                if _cand.exists():
                    _rel_parts = _cand.relative_to(SDK_SCRIPTS).with_suffix("").parts
                    _qual = ".".join(_rel_parts)
                    if _qual != fullname and _qual in sys.modules:
                        loader = _AliasLoader(sys.modules[_qual])
                    else:
                        loader = _SDKLoader(str(_cand), also_register_as=(_qual if _qual != fullname else None))
                    return importlib.machinery.ModuleSpec(fullname, loader, origin=str(_cand))
                _pkg = _p / child / "__init__.py"
                if _pkg.exists():
                    _rel_parts = (_p / child).relative_to(SDK_SCRIPTS).parts
                    _qual = ".".join(_rel_parts)
                    if _qual != fullname and _qual in sys.modules:
                        loader = _AliasLoader(sys.modules[_qual])
                    else:
                        loader = _SDKLoader(str(_pkg), also_register_as=(_qual if _qual != fullname else None))
                    spec = importlib.machinery.ModuleSpec(fullname, loader, origin=str(_pkg))
                    spec.submodule_search_locations = [str(_p / child)]
                    return spec
        # Python 1.5 implicit relative import fallback: BC engine added each SDK
        # package directory to sys.path, so bare `import X` inside Bridge/ found
        # Bridge/X.py.  Search SDK subdirectories for a unique match.
        if "." not in fullname:
            matches = sorted(SDK_SCRIPTS.rglob(f"{fullname}.py"))
            caller_dir = None
            frame = sys._getframe(1)
            while frame is not None:
                co_file = frame.f_code.co_filename
                if str(SDK_SCRIPTS) in co_file:
                    caller_dir = Path(co_file).parent
                    break
                frame = frame.f_back
            if caller_dir:
                matches.sort(key=lambda p: (p.parent != caller_dir, str(p)))
            for candidate in matches:
                rel_parts = candidate.relative_to(SDK_SCRIPTS).with_suffix("").parts
                qualified = ".".join(rel_parts)
                if qualified in sys.modules:
                    loader = _AliasLoader(sys.modules[qualified])
                else:
                    loader = _SDKLoader(str(candidate), also_register_as=qualified)
                return importlib.machinery.ModuleSpec(fullname, loader, origin=str(candidate))
        return None


_BASELINE_MODULES: set[str] = set()


def setup_sdk() -> None:
    """Install SDK finder and stub modules. Call once before run_mission()."""
    global _BASELINE_MODULES

    # Pre-import stdlib modules that BC's SDK shadows. The SDK finder we're
    # about to install sits at sys.meta_path[0] and `sdk/Build/scripts/` has a
    # Python-1.5-era `string.py` (uses backtick-repr syntax) that masks
    # stdlib's `string`. Without this, anything that triggers
    # `import logging` -> `from string import Template` after setup_sdk()
    # tries to load the SDK's `string.py` and crashes with SyntaxError.
    # Under pytest the issue is hidden because pytest itself imports logging
    # (-> string) at startup, so the modules are already cached. The host
    # binary doesn't have that luxury — call this before the finder.
    import string  # noqa: F401

    if not any(isinstance(f, _SDKFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _SDKFinder())

    # LoadBridge is a real Phase 1 shim at the project root.
    sys.modules.pop("LoadBridge", None)

    if "Bridge" not in sys.modules:
        _bridge = types.ModuleType("Bridge")
        _bridge.__path__ = [str(SDK_SCRIPTS / "Bridge")]  # type: ignore[attr-defined]
        sys.modules["Bridge"] = _bridge

    if "Actions" not in sys.modules:
        _actions = types.ModuleType("Actions")
        _actions.__path__ = [str(SDK_SCRIPTS / "Actions")]  # type: ignore[attr-defined]
        sys.modules["Actions"] = _actions

    _plain_stubs = [
        "imp",  # removed in Python 3.12; loadspacehelper imports but never uses it
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions.MissionScriptActions",
    ]
    for _stub_name in _plain_stubs:
        if _stub_name not in sys.modules:
            _stub = _StubModule(_stub_name)
            sys.modules[_stub_name] = _stub
            _parent, _, _child = _stub_name.rpartition(".")
            if _parent and _parent in sys.modules:
                try:
                    setattr(sys.modules[_parent], _child, _stub)
                except (AttributeError, TypeError):
                    pass

    # Multiplayer: pre-create the package so child stubs land as attributes.
    if "Multiplayer" not in sys.modules:
        _mp_pkg = types.ModuleType("Multiplayer")
        _mp_pkg.__path__ = [str(SDK_SCRIPTS / "Multiplayer")]
        sys.modules["Multiplayer"] = _mp_pkg

    _multiplayer_ui_stubs = [
        "Multiplayer.MultiplayerMenus",
        "Multiplayer.MissionMenusShared",
    ]
    for _mp_name in _multiplayer_ui_stubs:
        _stub = _StubModule(_mp_name)
        sys.modules[_mp_name] = _stub
        _parent, _, _child = _mp_name.rpartition(".")
        if _parent in sys.modules:
            try:
                setattr(sys.modules[_parent], _child, _stub)
            except (AttributeError, TypeError):
                pass

    # Characters: alias package for Bridge.Characters (Python 1.5 implicit relative imports).
    if "Characters" not in sys.modules:
        _chars = types.ModuleType("Characters")
        _chars.__path__ = [str(SDK_SCRIPTS / "Bridge" / "Characters")]  # type: ignore[attr-defined]
        sys.modules["Characters"] = _chars

    # Episode-level scripts: pre-load so mission scripts reading carry-over
    # state get FALSE (0) defaults rather than None.
    if "Maelstrom.Episode6.Episode6" not in sys.modules:
        try:
            _ep6 = importlib.import_module("Maelstrom.Episode6.Episode6")
            _ep6.g_bDevoreDestroyed = 0
            _ep6.g_bSFDestroyed = 0
            _ep6.g_bVentureDestroyed = 0
        except Exception:
            pass
    if "Maelstrom.Episode7.Episode7" not in sys.modules:
        try:
            importlib.import_module("Maelstrom.Episode7.Episode7")
        except Exception:
            pass

    _BASELINE_MODULES = set(sys.modules.keys())

    # Install the LaunchObject emission hook so any TGScriptAction that
    # routes through Actions.ShipScriptActions.LaunchObject lands in the
    # engine wrapper (which records via App._emission_recorder instead
    # of spawning real ships). Idempotent — safe to call repeatedly.
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()


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

    # Reset per-mission global state so each run starts clean.
    import App
    from engine.appc.placement import _waypoint_registry
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kSetManager._sets.clear()
    _waypoint_registry.clear()
    App._next_event_type_id = 200  # reset dynamic event IDs

    def _alarm_handler(signum, frame):
        raise TimeoutError(f"timed out after {_MISSION_TIMEOUT}s")

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(_MISSION_TIMEOUT)
    try:
        mod = importlib.import_module(module_name)
        mod.Initialize(mission)
        return ("pass", None)
    except Exception as exc:
        return ("fail", exc)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _BASELINE_MODULES]:
            del sys.modules[key]


def _error_key(exc: Exception) -> str:
    """Normalize an exception into a grouping key for the summary counter."""
    msg = (str(exc).splitlines() or [""])[0]
    if isinstance(exc, SyntaxError):
        msg = re.sub(r"name '[^']+' ", "name <X> ", msg)
        msg = re.sub(r" \([^)]+\.py, line \d+\)", "", msg)
    return f"{type(exc).__name__}: {msg[:80]}"


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
            err_line = (str(exc).splitlines() or [""])[0][:90]
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
                errors[_error_key(exc)] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")


if __name__ == "__main__":
    main()
