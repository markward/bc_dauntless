# M1Basic.Initialize() Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get `Custom.Tutorial.Episode.M1Basic.M1Basic.Initialize()` — the SDK's own "minimum a mission needs to be functional" tutorial — to run against our Python shim without raising.

**Architecture:** Three compatibility gaps separate us from this milestone: (1) `Game` is missing `GetPlayer`/`SetPlayer`, (2) several stub modules are plain `types.ModuleType` whose attributes raise `AttributeError` when called, and (3) Python 1.5's `__import__("a.b.c")` returned the *leaf* module while Python 3 returns the *root* — SDK scripts throughout `MissionLib` and `Systems.Utils` rely on the old behaviour. We fix these incrementally via TDD, then add the integration test.

**Tech Stack:** Python 3, pytest, `ast` (AST transformers already in `tests/conftest.py`), `importlib.import_module`.

---

## File map

| Status | Path | What changes |
|--------|------|--------------|
| Modify | `engine/core/game.py` | Add `_player`, `GetPlayer()`, `SetPlayer()` to `Game` |
| Modify | `tests/conftest.py` | Add `_StubModule`, `_FixDottedImport`, update stub list |
| Create | `tests/unit/test_stub_modules.py` | Unit tests for callable stubs |
| Modify | `tests/unit/test_game.py` | Two new tests for player getter/setter |
| Create | `tests/integration/test_m1basic_initialize.py` | End-to-end integration test |

---

### Task 1: Add `GetPlayer` / `SetPlayer` to `Game`

`MissionLib.CreatePlayerShip` immediately calls `pGame.GetPlayer()` (line 554 of the SDK's `MissionLib.py`). `Game` currently has no such method, so it raises `AttributeError`.

**Files:**
- Modify: `engine/core/game.py`
- Modify: `tests/unit/test_game.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_game.py`:

```python
def test_game_get_player_initially_none():
    from engine.core.game import Game
    g = Game()
    assert g.GetPlayer() is None


def test_game_set_and_get_player():
    from engine.core.game import Game
    g = Game()
    sentinel = object()
    g.SetPlayer(sentinel)
    assert g.GetPlayer() is sentinel
```

- [ ] **Step 2: Verify the tests fail**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_game.py::test_game_get_player_initially_none tests/unit/test_game.py::test_game_set_and_get_player -v
```

Expected: FAIL — `AttributeError: 'Game' object has no attribute 'GetPlayer'`

- [ ] **Step 3: Add `_player`, `GetPlayer`, `SetPlayer` to `Game`**

The current `Game` class in `engine/core/game.py`:

```python
class Game(TGObject):
    def __init__(self):
        super().__init__()
        self._current_episode = None

    def GetCurrentEpisode(self):
        return self._current_episode

    def SetCurrentEpisode(self, episode):
        self._current_episode = episode
```

Replace it with:

```python
class Game(TGObject):
    def __init__(self):
        super().__init__()
        self._current_episode = None
        self._player = None

    def GetCurrentEpisode(self):
        return self._current_episode

    def SetCurrentEpisode(self, episode):
        self._current_episode = episode

    def GetPlayer(self):
        return self._player

    def SetPlayer(self, player):
        self._player = player
```

- [ ] **Step 4: Verify tests pass**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_game.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/core/game.py tests/unit/test_game.py
git commit -m "feat(game): add GetPlayer/SetPlayer to Game"
```

---

### Task 2: Add callable stub modules

`loadspacehelper`, `LoadBridge`, and `Bridge.HelmMenuHandlers` are all either missing entirely or stubbed as plain `types.ModuleType`. Any attribute access on a plain `types.ModuleType` raises `AttributeError`. We need:

- `loadspacehelper.CreateShip(...)` → returns `None` (so `if pPlayer:` is falsy and the creation branch is skipped cleanly)
- `loadspacehelper.PreloadShip(...)` → returns `None`
- `loadspacehelper.AdjustShipForDifficulty(...)` → returns `None` (called inside the `if pPlayer` branch — won't be reached, but good to have)
- `LoadBridge.Load(...)` → returns `None`
- `Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0` → attribute set must not raise (a plain `types.ModuleType` actually handles `setattr` fine, but we need `Bridge.HelmMenuHandlers` to be pre-populated so the SDK finder never loads the real file, which has deep dependencies)

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/unit/test_stub_modules.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_stub_modules.py`:

```python
def test_loadspacehelper_create_ship_callable():
    import loadspacehelper
    result = loadspacehelper.CreateShip("Galaxy", None, "player", "Start")
    assert result is None


def test_loadspacehelper_preload_ship_callable():
    import loadspacehelper
    result = loadspacehelper.PreloadShip("Galaxy", 1)
    assert result is None


def test_load_bridge_load_callable():
    import LoadBridge
    result = LoadBridge.Load("GalaxyBridge")
    assert result is None


def test_bridge_helm_menu_handlers_attr_set():
    import Bridge.HelmMenuHandlers
    Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0
```

- [ ] **Step 2: Verify the tests fail**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_stub_modules.py -v
```

Expected: FAIL — `AttributeError: module 'loadspacehelper' has no attribute 'CreateShip'` for the first two, `ModuleNotFoundError: No module named 'LoadBridge'` for the third.

- [ ] **Step 3: Add `_StubModule` and update conftest**

In `tests/conftest.py`, add `_StubModule` after the existing imports (after `import warnings`):

```python
class _StubModule(types.ModuleType):
    """Module where any attribute access returns a no-op callable returning None.

    Used for SDK-side modules whose implementations are pure UI/bridge and
    irrelevant to Phase 1 headless logic.
    """
    def __getattr__(self, name):
        return lambda *args, **kwargs: None
```

Then replace the `pytest_configure` stub block (lines 80–94 in the current file):

```python
    # Callable stubs: modules whose attributes must be callable (return None).
    # loadspacehelper.CreateShip etc. are called by MissionLib but the return
    # value is None, so all ship-creation branches are safely skipped.
    _callable_stubs = [
        "loadspacehelper",
        "LoadBridge",
        "Bridge.HelmMenuHandlers",
    ]
    for name in _callable_stubs:
        if name not in sys.modules:
            sys.modules[name] = _StubModule(name)

    # Plain stubs: modules that are imported but never called in Phase 1.
    _plain_stubs = [
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
    for name in _plain_stubs:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
```

- [ ] **Step 4: Verify tests pass**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_stub_modules.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full suite to check for regressions**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: all previously passing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/unit/test_stub_modules.py
git commit -m "feat(conftest): add _StubModule for callable SDK stubs (loadspacehelper, LoadBridge, HelmMenuHandlers)"
```

---

### Task 3: Fix Python 1.5 `__import__` semantics

**Background.** In Python 1.5, `__import__("a.b.c")` returned the *leaf* module `c`. In Python 2.0 this changed to return the *root* module `a`. SDK scripts were written for Python 1.5 and rely on the old behaviour in two critical places:

1. `MissionLib.SetupSpaceSet(pcSetName)` (line 1435–1438 of `MissionLib.py`):
   ```python
   pModule = __import__(pcSetName)   # expects leaf — gets root in Py3
   pModule.Initialize()              # AttributeError on root module
   return pModule.GetSet()
   ```

2. `Systems.Utils.CreateSystemMenuInternal` (lines 78–80 of `Utils.py`):
   ```python
   pSystemModule = __import__(sRegion)  # same issue
   sSystem = pSystemModule.GetSetName()
   ```

Fix: add an AST transformer to `_SDKLoader` that rewrites bare `__import__(x)` (one positional arg, no keywords) to `importlib.import_module(x)`, which returns the leaf module in both Python 2 and 3.

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add `_FixDottedImport` transformer to `conftest.py`**

Add the class immediately after `_MoveGlobalsToTop` (before `_SDKLoader`):

```python
class _FixDottedImport(ast.NodeTransformer):
    """Rewrite bare __import__(x) → importlib.import_module(x).

    Python 1.5 returned the leaf module for a dotted __import__; Python 3
    returns the root. SDK scripts depend on the 1.5 behaviour for dotted
    paths like "Systems.Biranu.Biranu1".

    Only the single-argument no-keyword form is rewritten; __import__ calls
    with fromlist/level arguments use Python 3 semantics and are left alone.
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
```

- [ ] **Step 2: Apply the transformer in `_SDKLoader.exec_module`**

The current `exec_module` body in `_SDKLoader` ends with:

```python
        tree = _MoveGlobalsToTop().visit(tree)
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        exec(code, module.__dict__)
```

Change it to:

```python
        tree = _MoveGlobalsToTop().visit(tree)
        tree = _FixDottedImport().visit(tree)
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        exec(code, module.__dict__)
```

- [ ] **Step 3: Run the full suite to verify no regressions**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: all previously passing tests still PASS. (The transformer adds `import importlib as _sdk_importlib` to every SDK script, which is harmless for scripts that don't use `__import__`.)

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "feat(conftest): fix Python 1.5 __import__ leaf-module semantics via AST rewrite"
```

---

### Task 4: M1Basic integration test

Write the test first; it exercises the full call chain:

```
M1Basic.PreLoadAssets(mission)
  └── loadspacehelper.PreloadShip("Galaxy", 1)          # _StubModule → None

M1Basic.Initialize(mission)
  ├── LoadBridge.Load("GalaxyBridge")                    # _StubModule → None
  ├── CreateRegions()
  │   ├── Systems.Biranu.Biranu.CreateMenus()
  │   │   └── Systems.Utils.CreateSystemMenu(...)
  │   │       └── __import__(sRegion) → importlib.import_module → Biranu1/Biranu2
  │   │           └── pSystemModule.GetSetName()        # "Biranu1" / "Biranu2"
  │   └── MissionLib.SetupSpaceSet("Systems.Biranu.Biranu1")
  │       └── __import__(pcSetName) → importlib.import_module → Biranu1
  │           ├── Biranu1.Initialize()                  # all App calls → _Stub
  │           └── Biranu1.GetSet() → App.g_kSetManager.GetSet(...) → _Stub
  └── CreateStartingObjects(mission)
      └── MissionLib.CreatePlayerShip("Galaxy", _Stub, "player", "Player Start")
          ├── App.Game_GetCurrentGame() → real Game
          ├── import Bridge.HelmMenuHandlers             # pre-stubbed
          ├── Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0
          ├── pGame.GetPlayer() → None (Task 1)
          ├── importlib.import_module("ships.Galaxy")    # SDK ship file, loads fine
          └── loadspacehelper.CreateShip(...) → None    # skips pPlayer != None branch
```

**Files:**
- Create: `tests/integration/test_m1basic_initialize.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_m1basic_initialize.py`:

```python
"""
Integration test: Tutorial M1Basic.Initialize() runs against our Python shim.

Custom.Tutorial.Episode.M1Basic.M1Basic is the SDK's own "minimum a mission
needs to be functional" tutorial. All rendering/UI calls return _Stub;
game-logic calls use our real implementations.

Full path exercised:
  M1Basic.Initialize
    -> LoadBridge.Load (stub)
    -> MissionLib.SetupSpaceSet("Systems.Biranu.Biranu1")
         -> importlib.import_module (fixed __import__)
         -> Biranu1.Initialize() (all App calls -> _Stub)
    -> MissionLib.CreatePlayerShip
         -> Game.GetPlayer() -> None
         -> loadspacehelper.CreateShip -> None (skips player-creation branch)
"""
import sys
import pytest
import App
from engine.core.game import Game, Episode, Mission, _set_current_game

_M1BASIC_PREFIXES = (
    "Custom.Tutorial",
    "Systems.Biranu",
    "ships",
    "Multiplayer",
)


@pytest.fixture(autouse=True)
def game_context():
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield game, episode, mission
    _set_current_game(None)
    # Evict SDK modules loaded during the test so each test starts clean.
    for key in [k for k in sys.modules if k.startswith(_M1BASIC_PREFIXES)]:
        del sys.modules[key]


def test_m1basic_preload_assets_does_not_raise(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M1Basic.M1Basic as M1Basic
    M1Basic.PreLoadAssets(mission)


def test_m1basic_initialize_does_not_raise(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M1Basic.M1Basic as M1Basic
    M1Basic.PreLoadAssets(mission)
    M1Basic.Initialize(mission)
```

- [ ] **Step 2: Run the integration test — expect PASS**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/integration/test_m1basic_initialize.py -v
```

Expected: both tests PASS.

If either fails, read the traceback carefully. The most likely remaining issue is an SDK module importing something not yet stubbed — add it to the `_callable_stubs` or `_plain_stubs` list in conftest and re-run.

- [ ] **Step 3: Run the full suite**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: all tests PASS (30 existing + 2 new integration + 3 new stub unit tests + 2 new game unit tests).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_m1basic_initialize.py
git commit -m "test(integration): M1Basic.Initialize() runs against shim"
```
