# Bridge Menu Runtime Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The five SDK bridge menus (Tactical, Helm, Science, XO, Engineer) build at runtime via the root `LoadBridge.py` shim, the `Bridge.HelmMenuHandlers` pre-stub is lifted everywhere, and `TacticalControlWindow` gains the real menu-lookup API closing the `GetTacticalMenu` crash path.

**Architecture:** Per the spec ([2026-06-12-bridge-menu-activation-design.md](../specs/2026-06-12-bridge-menu-activation-design.md)): the root shim's `Load()` calls a now-real `CreateCharacterMenus()` mirroring SDK `LoadBridge.py:131-161` (five handlers, tactical-menu pointer, Tactical-hide epilogue, `SetupBridgeNone()`), each stage exception-wrapped (production degrades; CI stays strict). Mission-swap hygiene goes in `reset_sdk_globals`.

**Tech Stack:** Python shims (engine/appc conventions), pytest focused subsets ONLY (full suite OOMs the host — >100 GB RAM).

**Key verified facts (do not re-derive):**
- SDK sequence to mirror: `sdk/Build/scripts/LoadBridge.py:131-161` (`CreateCharacterMenus`) invoked from `Load()` at line 187. Epilogue loads `data/TGL/Bridge Menus.tgl`, calls `FindMenu`/`GetMenuParentPane` with the localized "Tactical" string, hides both, unloads, then `Tactical.Interface.TacticalControlWindow.SetupBridgeNone()`.
- Pre-stub sites: `tools/mission_harness.py:421-424` and `tests/conftest.py:439-442` install `_StubModule("Bridge.HelmMenuHandlers")` and assign `sys.modules["Bridge"].HelmMenuHandlers`. Real module imports cleanly (proven by `tests/integration/test_helm_menu_creation.py` and a live host experiment).
- `Appc.TacticalControlWindow_SetTacticalMenu` has no Python caller in the SDK — the C++ engine set it internally; our `CreateCharacterMenus` stands in.
- `reset_sdk_globals` is `engine/host_loop.py:1267`; it does NOT currently reset `TacticalControlWindow._instance` (stale-menu accumulation risk) nor the `st_widgets` module registry. Each step there is independently best-effort (try/except discipline).
- `TacticalControlWindow` (engine/appc/windows.py) has `_menus` (via `AddMenuToList`) and `_children` as `(child, x, y)` tuples; child panes are `_STStylizedWindow` instances whose `_children` list contains the menus. `STMenu` lives in engine/appc/characters.py; missing methods on it resolve to truthy `_Stub`s (TGObject base).
- Existing helm tests pop/restore the pre-stub and tolerate its absence (`saved is None` branch).
- Crash path to close: `sdk/Build/scripts/TacticalControlHandlers.py:183` — `GetTacticalMenu().IsCompletelyVisible()` then `STButton_Cast(pMenu.GetButtonW(...)).SetChosen(...)`.

**Branch:** create `feat/bridge-menu-activation` off main before Task 1.

---

### Task 1: TacticalControlWindow menu API + STMenu.IsCompletelyVisible

**Files:**
- Modify: `engine/appc/windows.py` (class `TacticalControlWindow`)
- Modify: `engine/appc/characters.py` (class `STMenu`)
- Test: `tests/unit/test_tactical_window_menus.py` (append)

- [ ] **Step 1: Write the failing tests (append to tests/unit/test_tactical_window_menus.py)**

```python
def _pane_with_menu(label):
    from engine.appc.windows import STStylizedWindow_CreateW
    from engine.appc.characters import STTopLevelMenu
    pane = STStylizedWindow_CreateW("StylizedWindow", "NoMinimize", label, 0.0, 0.0)
    menu = STTopLevelMenu(label)
    pane.AddChild(menu, 0.0, 0.0, 0)
    return pane, menu


def test_find_menu_by_label_and_missing_returns_none():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tcw.AddMenuToList(helm)
    assert tcw.FindMenu("Helm") is helm
    assert tcw.FindMenu("Nope") is None


def test_find_menu_coerces_tgstring_like_labels():
    from engine.appc.localization import _TGString
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tcw.AddMenuToList(helm)
    assert tcw.FindMenu(_TGString("Helm")) is helm


def test_get_menu_parent_pane():
    tcw = TacticalControlWindow.GetInstance()
    pane, menu = _pane_with_menu("Tactical")
    tcw.AddChild(pane, 0.0, 0.0)
    tcw.AddMenuToList(menu)
    assert tcw.GetMenuParentPane("Tactical") is pane
    assert tcw.GetMenuParentPane("Nope") is None


def test_tactical_menu_pointer_roundtrip():
    tcw = TacticalControlWindow.GetInstance()
    assert tcw.GetTacticalMenu() is None
    menu = STTopLevelMenu("Tactical")
    tcw.SetTacticalMenu(menu)
    assert tcw.GetTacticalMenu() is menu


def test_stmenu_is_completely_visible_mirrors_visibility():
    m = STTopLevelMenu("Helm")
    assert m.IsCompletelyVisible() == 1
    m.SetNotVisible()
    assert m.IsCompletelyVisible() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_tactical_window_menus.py -v`
Expected: the 5 new tests FAIL (`FindMenu` resolves to a `_Stub`, identity/`is None` asserts fail); existing 3 pass.

- [ ] **Step 3: Implement in engine/appc/windows.py**

In `TacticalControlWindow.__init__`, add `self._tactical_menu = None` after `self._menus`. After `GetMenuList`, add:

```python
    def FindMenu(self, label):
        """Menu lookup by label. SDK: 66 call sites, all null-guarded with
        `if pMenu:` — None for a missing label is the faithful contract."""
        key = str(label)
        for menu in self._menus:
            if menu.GetLabel() == key:
                return menu
        return None

    def GetMenuParentPane(self, label):
        """The AddChild-recorded pane whose subtree holds the labelled menu.
        SDK: LoadBridge.py:155, guarded `if pPane != None:`."""
        menu = self.FindMenu(label)
        if menu is None:
            return None
        for (child, _x, _y) in self._children:
            if menu in getattr(child, "_children", []):
                return child
        return None

    def SetTacticalMenu(self, menu) -> None:
        # Engine-internal in original BC (Appc binding has no Python
        # caller); our LoadBridge.CreateCharacterMenus stands in.
        self._tactical_menu = menu

    def GetTacticalMenu(self):
        return self._tactical_menu
```

- [ ] **Step 4: Implement in engine/appc/characters.py**

In `STMenu`, after `IsVisible`, add:

```python
    def IsCompletelyVisible(self) -> int:
        # Headless has no partial scroll clipping — visibility is the
        # faithful answer (TacticalControlHandlers.py:183 chains this off
        # GetTacticalMenu before toggling the manual-aim button).
        return self.IsVisible()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_tactical_window_menus.py tests/unit/test_crew_menu_panel.py -v`
Expected: all PASS.

NOTE: if `_TGString("Helm")`'s `str()` does not produce `"Helm"` (check `engine/appc/localization.py` `_TGString.__str__`), fix `FindMenu` by comparing against `label.GetCString()` when present — do NOT modify `_TGString`.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/windows.py engine/appc/characters.py tests/unit/test_tactical_window_menus.py
git commit -m "feat(bridge-menus): TacticalControlWindow FindMenu/parent-pane/tactical-menu API"
```

---

### Task 2: Activate CreateCharacterMenus in the LoadBridge shim + lift pre-stubs

**Files:**
- Modify: `LoadBridge.py` (project root)
- Modify: `tests/conftest.py:439-442` (remove pre-stub block)
- Modify: `tools/mission_harness.py:421-424` (remove pre-stub block)
- Test: `tests/integration/test_bridge_menu_activation.py` (new)
- Possibly modify (triage only): `engine/appc/` shims, `App.py` constants

- [ ] **Step 1: Write the strict integration test**

```python
"""Bridge menu activation — LoadBridge.Load() builds ALL FIVE menus via the
real SDK Bridge/*MenuHandlers. Strict: no degraded pass. Spec:
docs/superpowers/specs/2026-06-12-bridge-menu-activation-design.md
"""
import json
import sys

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.ui.crew_menu_panel import CrewMenuPanel

FIVE = ["Tactical", "Helm", "Science", "XO", "Engineer"]


def _fresh_world():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    LoadBridge._reset_menus_created()
    App.g_kSetManager._sets.clear()
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    # The five handlers' import chains must see the REAL modules.
    for name in list(sys.modules):
        if name.startswith("Bridge.") and "StubModule" in type(sys.modules[name]).__name__:
            sys.modules.pop(name)
    return game


def test_load_builds_all_five_menus():
    _fresh_world()
    try:
        LoadBridge.Load("GalaxyBridge")
        tcw = TacticalControlWindow.GetInstance()
        menus = tcw.GetMenuList()
        assert len(menus) == 5, [m.GetLabel() for m in menus]
        # Tactical pointer set and its pane hidden by the epilogue.
        tac = tcw.GetTacticalMenu()
        assert tac is not None
        assert tac in menus
        pane = tcw.GetMenuParentPane(tac.GetLabel())
        assert pane is not None
        assert pane._visible is False
        # Helm built its warp registry.
        assert st_widgets.SortedRegionMenu_GetWarpButton() is not None
        # CrewMenuPanel renders the full forest as well-formed JSON.
        panel = CrewMenuPanel()
        payload = panel.render_payload()
        data = json.loads(payload[len("setCrewMenus("):-2])
        assert len(data["menus"]) == 5
    finally:
        _set_current_game(None)


def test_double_load_builds_menus_once():
    _fresh_world()
    try:
        LoadBridge.Load("GalaxyBridge")
        n = len(TacticalControlWindow.GetInstance().GetMenuList())
        LoadBridge.Load("GalaxyBridge")
        assert len(TacticalControlWindow.GetInstance().GetMenuList()) == n
    finally:
        _set_current_game(None)
```

If `Episode.SetCurrentMission` / `Game.SetCurrentEpisode` have different
names in `engine/core/game.py`, mirror the scaffolding used by
`tests/integration/test_crew_menu_round_trip.py` instead — that file already
solved it.

- [ ] **Step 2: Run to verify the right failure**

Run: `uv run pytest tests/integration/test_bridge_menu_activation.py -v -x`
Expected: FAIL — `LoadBridge` has no `_reset_menus_created` (AttributeError), then after stubbing that out mentally: menus list empty because `CreateCharacterMenus` is a `pass` stub.

- [ ] **Step 3: Implement in root `LoadBridge.py`**

Replace the `CreateCharacterMenus` stub with (and add the module flag + logger import at module top: `import logging` / `_logger = logging.getLogger(__name__)`):

```python
_menus_created = False


def _reset_menus_created():
    """Mission-swap hook (reset_sdk_globals) and test reset."""
    global _menus_created
    _menus_created = False


def CreateCharacterMenus(*args, **kwargs):
    """Build the five bridge menus via the real SDK handlers.

    Mirrors sdk/Build/scripts/LoadBridge.py:131-161. Each stage is
    exception-wrapped: a broken menu must not kill mission load
    (logging.exception keeps the traceback); the integration tests assert
    all five built, so gaps stay loud in CI.
    """
    global _menus_created
    if _menus_created:
        return
    _menus_created = True
    import App

    handler_modules = [
        "Bridge.TacticalMenuHandlers",
        "Bridge.HelmMenuHandlers",
        "Bridge.ScienceMenuHandlers",
        "Bridge.XOMenuHandlers",
        "Bridge.EngineerMenuHandlers",
    ]
    import importlib
    for mod_name in handler_modules:
        try:
            importlib.import_module(mod_name).CreateMenus()
        except Exception:
            _logger.exception("CreateMenus failed for %s", mod_name)

    tcw = App.TacticalControlWindow_GetTacticalControlWindow()

    # Epilogue — mirrors SDK LoadBridge.py:152-161: point the window at the
    # Tactical menu (engine-internal in original BC) and pre-hide it.
    try:
        pDatabase = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        sTactical = pDatabase.GetString("Tactical")
        pMenu = tcw.FindMenu(sTactical)
        tcw.SetTacticalMenu(pMenu)
        pPane = tcw.GetMenuParentPane(sTactical)
        if pPane is not None:
            pPane.SetNotVisible()
        if pMenu is not None:
            pMenu.SetNotVisible()
        App.g_kLocalizationManager.Unload(pDatabase)
    except Exception:
        _logger.exception("bridge-menu epilogue (Tactical hide) failed")

    try:
        import Tactical.Interface.TacticalControlWindow as _TCW_script
        _TCW_script.SetupBridgeNone()
    except Exception:
        _logger.exception("SetupBridgeNone failed")
```

And at the end of `Load()`, just before `return pSet`, add:

```python
    # Stock BC builds the five bridge menus as part of Load —
    # sdk/Build/scripts/LoadBridge.py:187.
    CreateCharacterMenus()
```

Note `Load()` early-returns when the bridge set already exists — the
`CreateCharacterMenus()` call must also run on that branch. Restructure to:

```python
    existing = App.g_kSetManager.GetSet("bridge")
    if existing:
        CreateCharacterMenus()
        return existing
```

- [ ] **Step 4: Lift the pre-stubs**

In `tests/conftest.py`, delete the block (keep the `Bridge` package shim above it):

```python
    if "Bridge.HelmMenuHandlers" not in sys.modules:
        _helm = _StubModule("Bridge.HelmMenuHandlers")
        sys.modules["Bridge.HelmMenuHandlers"] = _helm
        sys.modules["Bridge"].HelmMenuHandlers = _helm  # type: ignore[attr-defined]
```

and update the comment above it that says HelmMenuHandlers is pre-stubbed.
In `tools/mission_harness.py`, delete the identical block (lines ~421-424).

- [ ] **Step 5: Triage run**

Run: `uv run pytest tests/integration/test_bridge_menu_activation.py -v -x`

The four newly-exercised handlers (Tactical/Science/XO/Engineer) and the
`SetupBridgeNone` chain will surface gaps. Allowed fixes ONLY (the parent
plan's discipline):

1. Missing method on a shim class → state-sink in that class, one-line SDK
   file:line citation, style of its siblings.
2. Missing `App` constant → App.py 1060+ block (next free int < 1200) + name
   appended to `BRIDGE_ET_NAMES` in `tests/unit/test_bridge_event_constants.py`.
3. Missing widget factory/cast → `engine/appc/tg_ui/` per existing patterns +
   App.py export + `REAL_SYMBOLS` in `tests/unit/test_tg_ui_app_exports.py`.
4. NEVER touch `sdk/` files. NEVER weaken the five-menu assertion. If a
   handler's failure can't be fixed via 1-3, leave its try/except logging the
   gap and report DONE_WITH_CONCERNS naming the handler — do not fake the
   menu.

Iterate run → fix one failure class → re-run until green.

- [ ] **Step 6: Regression set**

Run: `uv run pytest tests/integration/test_bridge_menu_activation.py tests/integration/test_helm_menu_creation.py tests/integration/test_crew_menu_round_trip.py tests/unit/test_crew_menu_panel.py tests/unit/test_tg_ui_app_exports.py tests/host/test_host_loop_unit.py -v`
Expected: ALL pass (helm tests tolerate the absent pre-stub via their
`saved is None` restore branch; M1_Basic now exercises menu construction
in-subprocess).

- [ ] **Step 7: Commit**

```bash
git add -A LoadBridge.py tests/ tools/mission_harness.py App.py engine/
git commit -m "feat(bridge-menus): activate all five SDK bridge menus via LoadBridge shim"
```

---

### Task 3: Mission-swap hygiene in reset_sdk_globals

**Files:**
- Modify: `engine/host_loop.py:1267` (`reset_sdk_globals`)
- Test: `tests/unit/test_reset_sdk_globals_menus.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""reset_sdk_globals clears bridge-menu state so a mission swap rebuilds
menus fresh (no stale-menu accumulation, no leaked warp-button registry)."""
import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.tg_ui import st_widgets
from engine.host_loop import reset_sdk_globals


def test_reset_clears_menu_state():
    # Dirty every piece of state the reset must clear.
    LoadBridge._menus_created = True
    tcw = TacticalControlWindow.GetInstance()
    from engine.appc.characters import STTopLevelMenu
    tcw.AddMenuToList(STTopLevelMenu("Helm"))
    st_widgets.SortedRegionMenu_SetWarpButton(object())

    reset_sdk_globals()

    assert LoadBridge._menus_created is False
    assert TacticalControlWindow._instance is None
    assert st_widgets.SortedRegionMenu_GetWarpButton() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_reset_sdk_globals_menus.py -v`
Expected: FAIL on all three asserts.

- [ ] **Step 3: Implement**

In `reset_sdk_globals` (engine/host_loop.py), after the
`App._reset_target_menu_singleton()` line, add:

```python
    # Bridge-menu state: drop the TacticalControlWindow singleton (its menu
    # list belongs to the outgoing mission), clear the st_widgets module
    # registry (warp button etc.), and re-arm LoadBridge so the next
    # Load() rebuilds the five menus. Each step best-effort, matching the
    # rest of this function.
    try:
        from engine.appc.windows import TacticalControlWindow
        TacticalControlWindow._instance = None
        from engine.appc.tg_ui import st_widgets
        st_widgets._reset_module_state()
        import LoadBridge
        LoadBridge._reset_menus_created()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_reset_sdk_globals_menus.py tests/host/test_host_loop_unit.py tests/unit/test_loop.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_reset_sdk_globals_menus.py
git commit -m "feat(bridge-menus): mission-swap reset clears menu state"
```

---

### Task 4: Feature-wide regression sweep

- [ ] **Step 1: Run the full focused set**

Run: `uv run pytest tests/integration/test_bridge_menu_activation.py tests/integration/test_helm_menu_creation.py tests/integration/test_crew_menu_round_trip.py tests/unit/test_tactical_window_menus.py tests/unit/test_crew_menu_panel.py tests/unit/test_tg_ui_st_widgets.py tests/unit/test_tg_ui_app_exports.py tests/unit/test_bridge_event_constants.py tests/unit/test_reset_sdk_globals_menus.py tests/unit/test_time_slice.py tests/unit/test_loop.py tests/host/test_host_loop_unit.py -q`
Expected: ALL pass. Fix regressions before proceeding (same triage rules).

- [ ] **Step 2: Commit anything outstanding, no-op if clean**

---

### Task 5: Visual verification + wrap-up

- [ ] **Step 1: Build and run**

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Expected: once a mission loads its bridge, all five menus appear in the
crew-menu bar (no experiment patch needed — this is now the production path).
Capture the log lines and a screenshot PROMPTLY.

⚠️ HARD RULE (memory: no-desktop-interaction-during-verification): NEVER post
synthetic mouse/keyboard events; the machine is in active use. Evidence =
host log + one prompt screenshot. If the window closes mid-check, rely on the
log + integration tests. Delete any capture that catches non-dauntless
windows immediately.

- [ ] **Step 2: Use superpowers:finishing-a-development-branch**
