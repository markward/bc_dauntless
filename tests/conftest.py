import ast
import importlib.abc
import importlib.machinery
import os
import re
import sys
import types
import warnings
from pathlib import Path

# Default audio to the null backend during tests so no device is opened.
os.environ.setdefault("OPEN_STBC_AUDIO", "0")

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"

# Make the C++-built _open_stbc_host extension importable. CMake outputs it
# under build/python/ relative to the project root.
_BUILD_PYTHON = PROJECT_ROOT / "build" / "python"
if _BUILD_PYTHON.is_dir() and str(_BUILD_PYTHON) not in sys.path:
    sys.path.insert(0, str(_BUILD_PYTHON))

_PY2_OCTAL = re.compile(r'(?<![\w.])0([0-7]+)\b')
_PY2_RAISE = re.compile(r'^(\s*raise\s+\w[\w.]*)\s*,\s*(.*)', re.MULTILINE)
_PY2_PRINT_FILE = re.compile(r'^(\s*)print\s*>>\s*(\S+)\s*,\s*(.*?)\s*$', re.MULTILINE)
_PY2_PRINT_STMT = re.compile(r'^(\s*)print\s+(?!\()(.+?)\s*$', re.MULTILINE)
_PY2_PRINT_BARE = re.compile(r'^(\s*)print\s*$', re.MULTILINE)


def _fix_py2_syntax(source: str) -> str:
    """Rewrite Python 2-only syntax that ast.parse rejects."""
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


class _MoveGlobalsToTop(ast.NodeTransformer):
    """Move global declarations to the top of each function body.

    SDK scripts were written for Python 1.5/2.x, which allowed using a name
    before its global declaration anywhere in the function (even inside if/for/try
    blocks). Python 3 treats this as a SyntaxError at compile time.
    """

    @staticmethod
    def _hoist_globals(stmts):
        """Extract Global nodes from stmts and all nested blocks, except nested functions/classes."""
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
    """Rewrite x.sort(cmp_func) → x.sort(key=functools.cmp_to_key(cmp_func)).

    Python 2 list.sort accepted a positional comparison function; Python 3
    removed that parameter.  All SDK occurrences follow the Python 2 pattern.
    """

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


class _FixDottedImport(ast.NodeTransformer):
    """Rewrite bare __import__(x) → importlib.import_module(x).

    Python 1.5 returned the leaf module for a dotted __import__; Python 3
    returns the root. SDK scripts depend on the 1.5 behaviour for paths like
    "Systems.Biranu.Biranu1" in MissionLib.SetupSpaceSet and Systems.Utils.

    Only the single-argument no-keyword form is rewritten; __import__ calls
    with fromlist/level arguments are left unchanged.
    """
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
            # Generate: (lambda _x: _sdk_importlib.import_module(_x) if isinstance(_x, str) else _x)(arg)
            # Guards against stubs being passed as module names.
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
    """Module where any attribute access returns a chainable stub.

    Used for SDK-side modules whose implementations are pure UI/bridge and
    irrelevant to Phase 1 headless logic.
    """
    def __getattr__(self, name):
        return _Stub()


class _AliasLoader(importlib.abc.Loader):
    """Loader that reuses an already-loaded module (for bare-name → qualified-name aliasing)."""
    def __init__(self, existing_module):
        self._module = existing_module
    def create_module(self, spec):
        return self._module
    def exec_module(self, module):
        pass


class _SDKLoader(importlib.abc.Loader):
    """Load an SDK script with Python 2 compatibility fixes applied."""

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
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        module.__dict__.setdefault('apply', lambda f, a=(), kw={}: f(*a, **kw))
        # SDK loadspacehelper.py:91 calls `reload(mod)` after ClearLocalTemplates()
        # to re-register hardpoint templates by re-running the module top-level.
        # A no-op stub silently leaves templates cleared.
        module.__dict__.setdefault('reload', importlib.reload)
        module.__dict__.setdefault('BORG', 0x00000200)  # QuickBattle.py omits this; BORG_CUBE = 0x200
        exec(code, module.__dict__)
        # Python 1.5 compat: also register under the qualified dotted name so that
        # package.Submodule attribute lookups resolve correctly.
        if self.also_register_as and self.also_register_as not in sys.modules:
            sys.modules[self.also_register_as] = module
            parent, _, attr = self.also_register_as.rpartition('.')
            if parent and parent in sys.modules:
                try:
                    setattr(sys.modules[parent], attr, module)
                except (AttributeError, TypeError):
                    pass


class _SDKFinder(importlib.abc.MetaPathFinder):
    """Find modules in sdk/Build/scripts/ and load them via _SDKLoader."""

    def find_spec(self, fullname, path, target=None):
        rel = fullname.replace(".", "/")
        # Project root modules/packages take priority
        if (PROJECT_ROOT / (rel + ".py")).exists():
            return None
        if (PROJECT_ROOT / rel).is_dir() and (PROJECT_ROOT / rel / "__init__.py").exists():
            return None
        # Regular SDK module
        candidate = SDK_SCRIPTS / (rel + ".py")
        if candidate.exists():
            loader = _SDKLoader(str(candidate))
            return importlib.machinery.ModuleSpec(
                fullname, loader, origin=str(candidate)
            )
        # SDK package (directory with __init__.py)
        pkg_init = SDK_SCRIPTS / rel / "__init__.py"
        if pkg_init.exists():
            loader = _SDKLoader(str(pkg_init))
            spec = importlib.machinery.ModuleSpec(
                fullname, loader, origin=str(pkg_init)
            )
            spec.submodule_search_locations = [str(pkg_init.parent)]
            return spec
        # Submodule via explicit path: parent package has __path__ pointing into
        # an SDK directory (e.g. Characters → Bridge/Characters).  Use our loader
        # so Python 2 compatibility fixes are applied to the submodule too.
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
            # Python 1.5 compat: prefer the file in the same directory as the
            # calling SDK module (covers both load-time and call-time imports).
            # Walk the call stack to find the innermost SDK frame.
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
                    # Reuse the already-initialized module so module-level state
                    # (e.g. MissionShared.g_pDatabase) is shared, not reset.
                    loader = _AliasLoader(sys.modules[qualified])
                else:
                    # Load fresh and also register under the qualified dotted name
                    # so that package.Submodule attribute lookups work.
                    loader = _SDKLoader(str(candidate), also_register_as=qualified)
                return importlib.machinery.ModuleSpec(fullname, loader, origin=str(candidate))
        return None


def pytest_configure(config):
    # Our App.py must shadow sdk/Build/scripts/App.py
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    # Install SDK finder before the default finders so SDK scripts get our
    # compatibility loader instead of the standard one.
    if not any(isinstance(f, _SDKFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _SDKFinder())

    # LoadBridge is a real Phase 1 shim (LoadBridge.py at project root) that
    # registers an empty "bridge" SetClass.  Remove any stale stub entry so the
    # real module is picked up on first import.
    sys.modules.pop("LoadBridge", None)

    # Bridge: real SDK package at sdk/Build/scripts/Bridge/.  Setting __path__
    # lets Python (and _SDKFinder) find Bridge.* submodules.  HelmMenuHandlers
    # is pre-stubbed as callable because MissionLib writes to its attributes.
    if "Bridge" not in sys.modules:
        _bridge = types.ModuleType("Bridge")
        _bridge.__path__ = [str(SDK_SCRIPTS / "Bridge")]  # type: ignore[attr-defined]
        sys.modules["Bridge"] = _bridge
    if "Bridge.HelmMenuHandlers" not in sys.modules:
        _helm = _StubModule("Bridge.HelmMenuHandlers")
        sys.modules["Bridge.HelmMenuHandlers"] = _helm
        sys.modules["Bridge"].HelmMenuHandlers = _helm  # type: ignore[attr-defined]

    # Actions: real SDK package at sdk/Build/scripts/Actions/.  Setting __path__
    # lets Python (and _SDKFinder) find Actions.* submodules.
    if "Actions" not in sys.modules:
        _actions = types.ModuleType("Actions")
        _actions.__path__ = [str(SDK_SCRIPTS / "Actions")]  # type: ignore[attr-defined]
        sys.modules["Actions"] = _actions

    # Plain stubs: modules that are imported but whose attributes are not
    # accessed in Phase 1 code paths, or are pure UI/bridge handlers.
    # Use _StubModule so that any attribute access returns a chainable stub
    # rather than raising AttributeError.
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
        _mp_pkg.__path__ = [str(SDK_SCRIPTS / "Multiplayer")]  # type: ignore[attr-defined]
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

    # Characters: alias package for Bridge.Characters.  SDK scripts in Bridge/
    # use bare `import Characters.X` relying on Python 1.5 implicit relative
    # imports; our finder handles submodule lookups via the __path__ below.
    if "Characters" not in sys.modules:
        _chars = types.ModuleType("Characters")
        _chars.__path__ = [str(SDK_SCRIPTS / "Bridge" / "Characters")]  # type: ignore[attr-defined]
        sys.modules["Characters"] = _chars

    # Episode-level scripts: pre-load so their globals are initialized to
    # FALSE (0) for missions that read carry-over state from earlier episodes.
    import importlib as _il
    if "Maelstrom.Episode6.Episode6" not in sys.modules:
        try:
            _ep6 = _il.import_module("Maelstrom.Episode6.Episode6")
            _ep6.g_bDevoreDestroyed = 0
            _ep6.g_bSFDestroyed = 0
            _ep6.g_bVentureDestroyed = 0
        except Exception:
            pass
    if "Maelstrom.Episode7.Episode7" not in sys.modules:
        try:
            _il.import_module("Maelstrom.Episode7.Episode7")
        except Exception:
            pass
