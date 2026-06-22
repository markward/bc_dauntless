# Warp Stage 1 — Hard-Cut Warp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the player pick a destination in the CEF Set Course panel and warp there — the scene hard-cuts and the player loads into the chosen star system (no VFX, no camera work).

**Architecture:** A real `TGSequence` warp spine (`WarpSequence_Create`) whose actions load+realize the destination set, move the player into it, then terminate the source set and restore control. The CEF Warp button fires the authentic `ET_WARP_BUTTON_PRESSED` event on the SDK warp button — the SDK `WarpPressed` handler runs (camera stubs + input removal), and our own `execute_warp` handler, registered second, builds and plays the spine. The renderer is already per-set driven, so switching the rendered set changes the scene.

**Tech Stack:** Python 3 (engine + SDK shim), pytest, CEF (HTML/JS/CSS loaded from source — no rebuild), the existing `TGAction`/`TGSequence` action system.

## Global Constraints

- SDK is ground truth: never edit anything under `sdk/Build/scripts/`. Run SDK code against our shim; fix engine gaps, don't work around them.
- Fail loud: a destination set module that fails to import or `Initialize()` raises; do not swallow. Source-set teardown runs only AFTER the destination loads successfully.
- Terminate the source set on arrival (global sun/object aggregation forbids two live space sets).
- No new user-facing strings: the commit button label is **"Warp"**, read from `Bridge Menus.TGL` key `"Warp"`.
- Out of scope: warp VFX/flash, camera cutscenes/cinematic framing, pre-warp gameplay gates (beyond whatever SDK `WarpPressed` already does when the event fires), multiplayer, save/load of warp state, procedurally synthesizing sets.
- CEF assets load from `native/assets/ui-cef/` source — relaunch `./build/dauntless`, no rebuild. Python/JS/HTML/CSS only in this plan; no C++ changes (no `host_bindings.cc`, no shaders).
- Game units throughout; the player ship instance is reused (moved between sets), never destroyed/recreated.
- Run tests with `uv run pytest`.

**Key existing signatures (consumed across tasks):**
- `engine/appc/actions.py`: `TGAction` (override `_do_play(self)`; `Play()` auto-completes), `TGSequence` (`AddAction(action)`, `AppendAction(action)`, `Play()`), `TGScriptAction_Create(module, func, *args)`.
- `engine/appc/sets.py`: `g_kSetManager.GetSet(name)`, `.AddSet(pSet,name)`, `.DeleteSet(name)`, `.GetRenderedSet()`, `.MakeRenderedSet(name)`, `._sets` (dict name→set). `SetClass.AddObjectToSet(obj, id)`, `.RemoveObjectFromSet(name)`, `._objects` (dict id→obj), `.GetObject(id)`.
- `engine/appc/objects.py`: `obj.PlaceObjectByName(name)` (positions from the waypoint registry).
- `engine/core/game.py` / App: `App.Game_GetCurrentPlayer()`, `App.Game_SetCurrentPlayer(ship)`.
- `engine/appc/tg_ui/st_widgets.py`: `App.SortedRegionMenu_GetWarpButton()` → the `STWarpButton`; `STWarpButton.SetDestination(s)`, `.GetDestination()`, `.GetWarpTime()`.
- `engine/appc/events.py`: `TGEventHandlerObject.AddPythonFuncHandlerForInstance(eventType, "qualified.name")`, `.ProcessEvent(event)` (runs handlers in registration order). `App.g_kEventManager.AddEvent(event)` dispatches inline to `event.GetDestination().ProcessEvent(event)`. `App.TGEvent_Create()`, `event.SetEventType(int)`, `event.SetDestination(obj)`, `event.GetEventType()`.
- `engine/host_loop.py`: `_iter_set_objects(pSet)` (yields `pSet._objects.values()`), `_ship_world_matrix(ship, scale)`, `BC_MODEL_SCALE`, `_ship_nif_path(ship)`, `MissionSession` (`.ship_instances`, `.planet_instances`, `.planet_natural_scale`, `.ship_glow_controllers`, `.player`), renderer `r.create_instance(handle)`, `r.destroy_instance(iid)`, `r.load_model(path, search)`, `r.set_world_transform(iid, mat)`, `r.set_rim_eligible(iid, bool)`.

---

### Task 1: `ET_WARP_BUTTON_PRESSED` constant + `SortedRegionMenu` region retention

The baker and the warp trigger both need two missing primitives: a warp-button event type, and the region-module string that `SortedRegionMenu_CreateW(label, region)` currently discards.

**Files:**
- Modify: `engine/appc/events.py` (add the constant near the other `ET_*` at lines 7-8)
- Modify: `engine/appc/tg_ui/st_widgets.py` (`SortedRegionMenu`, `SortedRegionMenu_CreateW`)
- Modify: root `App.py` (export `ET_WARP_BUTTON_PRESSED`)
- Test: `tests/unit/test_st_widgets_region.py` (create)

**Interfaces:**
- Produces: `App.ET_WARP_BUTTON_PRESSED` (int). `SortedRegionMenu(label, region=None)` with attribute `_region` and method `GetRegionModule() -> str|None`. `SortedRegionMenu_CreateW(label="", region=None, *extra)` stores `region`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_st_widgets_region.py
from engine.appc.tg_ui.st_widgets import SortedRegionMenu_CreateW


def test_region_module_retained():
    m = SortedRegionMenu_CreateW("Vesuvi Dust Cloud", "Systems.Vesuvi.Vesuvi4")
    assert m.GetRegionModule() == "Systems.Vesuvi.Vesuvi4"
    assert m._region == "Systems.Vesuvi.Vesuvi4"


def test_region_module_defaults_none():
    m = SortedRegionMenu_CreateW("Some System")
    assert m.GetRegionModule() is None


def test_warp_event_constant_exists():
    import App
    assert isinstance(App.ET_WARP_BUTTON_PRESSED, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_st_widgets_region.py -v`
Expected: FAIL (`GetRegionModule` missing / `_region` is None / no `ET_WARP_BUTTON_PRESSED`).

- [ ] **Step 3: Add the event constant**

In `engine/appc/events.py`, after the existing `ET_WEAPON_HIT` line, add:

```python
ET_WARP_BUTTON_PRESSED: int = 0x1200   # warp button activated (synthesized from CEF Set Course)
```

- [ ] **Step 4: Retain the region on `SortedRegionMenu`**

In `engine/appc/tg_ui/st_widgets.py`, replace the `SortedRegionMenu` class and its factory:

```python
class SortedRegionMenu(STMenu):
    """Set-course region list. Sorting/pause flags recorded, unused.

    `region` is the SDK region-module string (e.g. "Systems.Vesuvi.Vesuvi4")
    passed as the 2nd arg of SortedRegionMenu_CreateW — the warp destination
    module. Retained so the offline catalog baker can record it.
    """

    def __init__(self, label: str = "", region=None):
        super().__init__(label)
        self._pause_sorting = 0
        self._region = str(region) if region is not None else None

    def GetRegionModule(self):
        return self._region

    def ClearInfo(self, *args) -> None:
        # Region-info reset on set-course rebuild (Systems/Utils.py:70).
        pass
```

And the factory:

```python
def SortedRegionMenu_CreateW(label="", region=None, *_extra) -> SortedRegionMenu:
    return SortedRegionMenu(str(label), region)
```

- [ ] **Step 5: Export the constant from `App.py`**

In root `App.py`, find the `from engine.appc.events import (...)` block and add `ET_WARP_BUTTON_PRESSED` to it. If events aren't imported with a names list, add:

```python
from engine.appc.events import ET_WARP_BUTTON_PRESSED
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_st_widgets_region.py tests/unit/test_characters.py -v`
Expected: PASS (region test green; existing menu tests still green).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/events.py engine/appc/tg_ui/st_widgets.py App.py tests/unit/test_st_widgets_region.py
git commit -m "feat(warp): ET_WARP_BUTTON_PRESSED constant + SortedRegionMenu region retention"
```

---

### Task 2: Re-bake the Set Course catalog with destination modules

Each warp-point record and each system needs its set-module name so the panel can resolve a selection to a destination.

**Files:**
- Modify: `tools/bake_set_course_catalog.py`
- Modify: `engine/appc/sector_model.json` (regenerated artifact)
- Test: `tests/integration/test_bake_set_course_catalog.py` (extend), `tests/unit/test_sector_model.py` (extend)

**Interfaces:**
- Consumes: `SortedRegionMenu.GetRegionModule()` (Task 1).
- Produces: in `sector_model.json`, each system gains `"module"` (its region module, may be None) and each `warp_points[]` entry gains `"module"`. `sector_model.warp_points_for(sid)` entries carry `module`; new `sector_model.system_module(sid)` accessor.

- [ ] **Step 1: Write the failing test (baker emits module)**

```python
# tests/integration/test_bake_set_course_catalog.py  (add)
def test_catalog_carries_destination_modules():
    from tools.bake_set_course_catalog import build_catalog
    import tools.mission_harness as mh
    import sys
    if not any(type(f).__name__ == "_SDKFinder" for f in sys.meta_path):
        mh.setup_sdk()
    catalog = build_catalog()
    vesuvi = catalog["vesuvi"]
    mods = {w["module"] for w in vesuvi["warp_points"]}
    assert "Systems.Vesuvi.Vesuvi4" in mods
    # Riha is a single-region system: its self-entry carries the system module.
    assert catalog["riha"]["module"] == "Systems.Riha.Riha1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_bake_set_course_catalog.py::test_catalog_carries_destination_modules -v`
Expected: FAIL (`build_catalog` returns `{id: [..]}` of `{id,label}` with no `module`).

- [ ] **Step 3: Restructure `build_catalog` to capture modules**

In `tools/bake_set_course_catalog.py`, replace the catalog-assembly block (the `if sc is not None:` loop and the `return catalog`) so each system maps to `{"module": <system region>, "warp_points": [{"id","label","module"}, ...]}`:

```python
    catalog, unmatched = {}, []
    model_ids = {s["id"] for s in
                 __import__("engine.appc.sector_model", fromlist=["x"])
                 .load_sector_model().get("systems", [])}
    if sc is not None:
        for node in sc._children:
            sid = system_id_for_set(node.GetLabel())
            if sid not in model_ids:
                unmatched.append((node.GetLabel(), sid))
            wps = [{"id": _slug(c.GetLabel()), "label": c.GetLabel(),
                    "module": getattr(c, "GetRegionModule", lambda: None)()}
                   for c in getattr(node, "_children", [])]
            entry = catalog.setdefault(
                sid, {"module": None, "warp_points": []})
            entry["warp_points"].extend(wps)
            # System node's own region (used by single-region systems like Riha
            # whose self-row is the destination).
            node_mod = getattr(node, "GetRegionModule", lambda: None)()
            if node_mod is not None and entry["module"] is None:
                entry["module"] = node_mod
```

- [ ] **Step 4: Update `fold_into_model` for the new shape**

Replace `fold_into_model`:

```python
def fold_into_model(catalog, out_path=OUT):
    model = json.loads(Path(out_path).read_text())
    for s in model.get("systems", []):
        entry = catalog.get(s["id"])
        if entry is not None:
            s["warp_points"] = entry["warp_points"]
            s["module"] = entry["module"]
    Path(out_path).write_text(json.dumps(model, indent=2) + "\n")
    return model
```

- [ ] **Step 5: Add `system_module` accessor and carry `module` through reads**

In `engine/appc/sector_model.py`, add (near `warp_points_for`):

```python
def system_module(system_id):
    """Set-module name for a system's own set, or None if it has none."""
    for s in load_sector_model().get("systems", []):
        if s.get("id") == system_id:
            return s.get("module")
    return None
```

`warp_points_for` already returns the stored dicts verbatim, so the new `module` key rides along — no change needed there. Confirm by reading `warp_points_for` and leaving it untouched if it returns the raw list.

- [ ] **Step 6: Re-bake the catalog**

Run: `uv run python tools/bake_set_course_catalog.py`
Expected: prints the system/warp-point counts; `git diff --stat engine/appc/sector_model.json` shows the file changed (modules added).

- [ ] **Step 7: Add a sector_model read test**

```python
# tests/unit/test_sector_model.py  (add)
def test_warp_points_carry_module():
    from engine.appc import sector_model as sm
    wps = sm.warp_points_for("vesuvi")
    assert any(w.get("module") == "Systems.Vesuvi.Vesuvi4" for w in wps)

def test_system_module_for_riha():
    from engine.appc import sector_model as sm
    assert sm.system_module("riha") == "Systems.Riha.Riha1"
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/integration/test_bake_set_course_catalog.py tests/unit/test_sector_model.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tools/bake_set_course_catalog.py engine/appc/sector_model.py engine/appc/sector_model.json tests/integration/test_bake_set_course_catalog.py tests/unit/test_sector_model.py
git commit -m "feat(warp): bake destination set-modules into Set Course catalog"
```

---

### Task 3: Warp spine — `ChangeRenderedSetAction`, player placement, `WarpSequence_Create`

The reusable warp sequence. Renderer realize/teardown is reached through module-level hooks (Task 4 wires them); with hooks unset the actions still perform the headless set/placement logic, so this task is fully testable on its own.

**Files:**
- Create: `engine/appc/warp.py`
- Modify: root `App.py` (export `WarpSequence_Create`, `ChangeRenderedSetAction_Create`, `ChangeRenderedSetAction_CreateFromSet`)
- Test: `tests/unit/test_warp_spine.py` (create)

**Interfaces:**
- Consumes: `TGAction`, `TGSequence` (actions.py); `g_kSetManager`; `SetClass.Add/RemoveObjectToSet`, `_objects`; `PlaceObjectByName`.
- Produces:
  - `configure_warp_hooks(realize=None, teardown=None)` — host registers per-set realize/teardown callables `fn(pSet) -> None`.
  - `ChangeRenderedSetAction_Create(module) -> TGAction`, `ChangeRenderedSetAction_CreateFromSet(pSet) -> TGAction`.
  - `WarpSequence_Create(ship, dest_module, warp_time, placement) -> TGSequence` (also exposes `.GetShip()`, `.GetDestination()`, `.GetPlacementName()`).
  - `execute_warp(button, event=None) -> None` (Task 6 registers it as a handler).
  - `_set_name_from_module(module) -> str` helper.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_spine.py
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def _make_set(name, with_player_start=True):
    """Build a registered set with a 'Player Start' waypoint."""
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    if with_player_start:
        wp = App.Waypoint_Create("Player Start", name, None)
        wp.SetTranslateXYZ(10.0, 20.0, 30.0)
        wp.Update(0)
    return s


def setup_function(_):
    # fresh set manager + registry per test
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)


def test_change_rendered_set_loads_and_switches(monkeypatch):
    # A fake destination module that registers a set on Initialize().
    import types, sys
    mod = types.ModuleType("FakeSys.Dest")
    def Initialize():
        _make_set("Dest")
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dest"] = mod
    act = warp.ChangeRenderedSetAction_Create("FakeSys.Dest")
    act.Play()
    assert App.g_kSetManager.GetSet("Dest") is not None
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dest"


def test_warp_sequence_moves_player_and_terminates_source():
    import types, sys
    src = _make_set("Source")
    player = App.ShipClass_Create() if hasattr(App, "ShipClass_Create") else _Dummy()
    player.SetName("player")
    src.AddObjectToSet(player, "player")

    mod = types.ModuleType("FakeSys.Dest2")
    mod.Initialize = lambda: _make_set("Dest2")
    sys.modules["FakeSys.Dest2"] = mod

    seq = warp.WarpSequence_Create(player, "FakeSys.Dest2", 5.0, "Player Start")
    seq.Play()

    assert App.g_kSetManager.GetSet("Source") is None          # source terminated
    dest = App.g_kSetManager.GetSet("Dest2")
    assert dest.GetObject("player") is player                  # player moved in
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dest2"
    # placed at Player Start
    loc = player.GetWorldLocation()
    assert abs(loc.x - 10.0) < 1e-3


class _Dummy:
    _name = ""
    def SetName(self, n): self._name = n
    def GetName(self): return self._name
    def PlaceObjectByName(self, n):
        import App
        App.g_kWaypointRegistry  # noqa - placeholder if needed
    def GetWorldLocation(self):
        import App
        return App.TGPoint3()
```

> Note for implementer: prefer the real `App.ShipClass_Create()` if present so `PlaceObjectByName`/`GetWorldLocation` are genuine; drop `_Dummy` if a real ship is constructible headlessly. Keep the assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_spine.py -v`
Expected: FAIL (`engine.appc.warp` does not exist).

- [ ] **Step 3: Implement `engine/appc/warp.py`**

```python
"""Warp Stage 1 — the hard-cut warp spine.

WarpSequence_Create builds a TGSequence that (1) loads + switches to the
destination set, (2) moves the player into it at the placement, (3) terminates
the source set and restores player control. Renderer realize/teardown is reached
via module-level hooks the host registers; unset hooks make those steps no-ops
(headless set/placement logic still runs). See
docs/superpowers/specs/2026-06-22-warp-stage1-hard-cut-design.md.
"""
from engine.appc.actions import TGAction, TGSequence

# Host-registered render hooks: fn(pSet) -> None. None => skip (headless).
_realize_hook = None
_teardown_hook = None
# Optional current-player fallback when App.Game_GetCurrentPlayer() is None.
_player_hook = None


def configure_warp_hooks(realize=None, teardown=None, current_player=None):
    global _realize_hook, _teardown_hook, _player_hook
    _realize_hook = realize
    _teardown_hook = teardown
    _player_hook = current_player


def _set_name_from_module(module):
    """'Systems.Vesuvi.Vesuvi4' -> 'Vesuvi4' (mirrors WarpSequence.py)."""
    s = str(module)
    return s[s.rfind(".") + 1:] if "." in s else s


class ChangeRenderedSetAction(TGAction):
    """Load (if needed) and switch the rendered set. Faithful to BC's
    ChangeRenderedSetAction_Create(module) / _CreateFromSet(set)."""

    def __init__(self, module=None, pSet=None):
        super().__init__()
        self._module = module
        self._set = pSet

    def _do_play(self):
        import App
        pSet = self._set
        if pSet is None:
            name = _set_name_from_module(self._module)
            pSet = App.g_kSetManager.GetSet(name)
            if pSet is None:
                # Lazy-load: import the region module and Initialize() it.
                # Fail loud — a bad module raises here.
                import importlib
                mod = importlib.import_module(self._module)
                mod.Initialize()
                pSet = App.g_kSetManager.GetSet(name)
                if pSet is None:
                    raise RuntimeError(
                        "warp: module %r Initialize() did not register set %r"
                        % (self._module, name))
        App.g_kSetManager.MakeRenderedSet(pSet.GetName())
        if _realize_hook is not None:
            _realize_hook(pSet)


def ChangeRenderedSetAction_Create(module):
    return ChangeRenderedSetAction(module=module)


def ChangeRenderedSetAction_CreateFromSet(pSet):
    return ChangeRenderedSetAction(pSet=pSet)


class _PlacePlayerAction(TGAction):
    """Move the player ship from its source set into the destination set and
    position it at the named placement."""

    def __init__(self, ship, dest_name, placement):
        super().__init__()
        self._ship = ship
        self._dest_name = dest_name
        self._placement = placement

    def _do_play(self):
        import App
        ship = self._ship
        # Remove from whatever set currently holds it.
        for s in list(App.g_kSetManager._sets.values()):
            if s.GetObject(ship.GetName()) is ship:
                s.RemoveObjectFromSet(ship.GetName())
        dest = App.g_kSetManager.GetSet(self._dest_name)
        dest.AddObjectToSet(ship, ship.GetName())
        ship.PlaceObjectByName(self._placement)


class _ArriveFinalizeAction(TGAction):
    """Terminate the source set (render teardown + DeleteSet) and return
    player control."""

    def __init__(self, source_set):
        super().__init__()
        self._source = source_set

    def _do_play(self):
        import App
        src = self._source
        if src is not None:
            name = src.GetName()
            # Only terminate if it isn't the destination (defensive).
            if App.g_kSetManager.GetRenderedSet() is not src:
                if _teardown_hook is not None:
                    _teardown_hook(src)
                App.g_kSetManager.DeleteSet(name)
        # Undo SDK WarpPressed's RemoveControl (no-op if MissionLib absent).
        try:
            import MissionLib
            MissionLib.ReturnControl()
        except Exception:
            pass


class WarpSequence(TGSequence):
    def __init__(self, ship, dest_module, warp_time, placement):
        super().__init__()
        self._ship = ship
        self._dest_module = dest_module
        self._warp_time = float(warp_time)
        self._placement = placement

    def GetShip(self):          return self._ship
    def GetDestination(self):   return self._dest_module
    def GetPlacementName(self):  return self._placement


def WarpSequence_Create(ship, dest_module, warp_time=0.0, placement="Player Start"):
    import App
    seq = WarpSequence(ship, dest_module, warp_time, placement)
    dest_name = _set_name_from_module(dest_module)
    # Capture the source set NOW (before the player is moved).
    source = None
    for s in App.g_kSetManager._sets.values():
        if s.GetObject(ship.GetName()) is ship:
            source = s
            break
    seq.AddAction(ChangeRenderedSetAction_Create(dest_module))
    seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
    seq.AppendAction(_ArriveFinalizeAction(source))
    return seq


def execute_warp(button, event=None):
    """ET_WARP_BUTTON_PRESSED handler (registered second, after SDK WarpPressed)
    — builds and plays the warp spine for the button's destination."""
    import App
    dest = button.GetDestination()
    if not dest:
        return
    player = App.Game_GetCurrentPlayer()
    if player is None and _player_hook is not None:
        player = _player_hook()
    if player is None:
        return
    WarpSequence_Create(player, dest, button.GetWarpTime(), "Player Start").Play()
```

- [ ] **Step 4: Export from `App.py`**

In root `App.py`, add:

```python
from engine.appc.warp import (
    WarpSequence_Create,
    ChangeRenderedSetAction_Create,
    ChangeRenderedSetAction_CreateFromSet,
)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_warp_spine.py -v`
Expected: PASS. If a real `ShipClass` is used, confirm `PlaceObjectByName` resolves "Player Start" (the waypoint registry is keyed by name+set — ensure the waypoint was created for the dest set name).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/warp.py App.py tests/unit/test_warp_spine.py
git commit -m "feat(warp): WarpSequence spine (ChangeRenderedSetAction, placement, terminate)"
```

---

### Task 4: Mid-mission set realize / teardown render hooks

Build/destroy render instances for one set's objects mid-mission, and wire them into the warp spine via `configure_warp_hooks`.

**Files:**
- Modify: `engine/host_loop.py` (add `realize_set` / `teardown_set`; call `configure_warp_hooks` at host setup)
- Test: `tests/unit/test_realize_set.py` (create)

**Interfaces:**
- Consumes: `MissionSession`, `_iter_set_objects`, `_ship_world_matrix`, `BC_MODEL_SCALE`, `_ship_nif_path`, renderer `create_instance`/`destroy_instance`/`load_model`/`set_world_transform`/`set_rim_eligible`; `warp.configure_warp_hooks` (Task 3).
- Produces: `realize_set(session, pSet, renderer, *, verbose=False) -> None` (idempotent: skips objects already in `session.ship_instances`/`planet_instances`), `teardown_set(session, pSet, renderer) -> None` (destroys instances for that set's objects and drops them from session maps; never touches objects not in the set).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_realize_set.py
import App
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()
    def load_model(self, path, search): return 100
    def model_aabb(self, h): return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    def create_instance(self, h):
        iid = self._next; self._next += 1; self.live.add(iid); return iid
    def destroy_instance(self, iid): self.live.discard(iid)
    def set_world_transform(self, iid, m): pass
    def set_rim_eligible(self, iid, b): pass


def test_realize_then_teardown(monkeypatch):
    from engine import host_loop as hl
    # Force a NIF path so the ship is realizable without real assets.
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    s = SetClass_Create(); App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create(); ship.SetName("rock")
    s.AddObjectToSet(ship, "rock")

    hl.realize_set(sess, s, r)
    assert ship in sess.ship_instances and len(r.live) == 1
    # idempotent
    hl.realize_set(sess, s, r)
    assert len(r.live) == 1

    hl.teardown_set(sess, s, r)
    assert ship not in sess.ship_instances and len(r.live) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_realize_set.py -v`
Expected: FAIL (`realize_set` / `teardown_set` not defined).

- [ ] **Step 3: Implement `realize_set` / `teardown_set`**

In `engine/host_loop.py`, add module-level functions (place them near `_iter_planets`, ~line 1764). Model the body on the ship loop in `_MissionLoader.load` (lines ~2195-2230), filtered to one set and made idempotent:

```python
def _iter_ships_in_set(pSet):
    from engine.appc.ships import ShipClass
    for obj in _iter_set_objects(pSet):
        if isinstance(obj, ShipClass):
            yield obj


def _iter_planets_in_set(pSet):
    from engine.appc.planet import Planet, Sun
    for obj in _iter_set_objects(pSet):
        if isinstance(obj, Planet) and not isinstance(obj, Sun):
            yield obj


def realize_set(session, pSet, renderer, *, verbose=False):
    """Build render instances for one set's ships/planets mid-mission.
    Idempotent: objects already instanced are skipped (e.g. the player)."""
    r_ = renderer
    for ship in _iter_ships_in_set(pSet):
        if ship in session.ship_instances:
            continue
        nif_path = _ship_nif_path(ship, verbose=verbose)
        if nif_path is None:
            continue
        try:
            handle = r_.load_model(nif_path, _shared_texture_search())
        except Exception as e:
            dev_mode.log_swallowed("realize_set load_model", e)
            continue
        iid = r_.create_instance(handle)
        r_.set_world_transform(iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
        session.ship_instances[ship] = iid
        r_.set_rim_eligible(iid, True)
    for planet in _iter_planets_in_set(pSet):
        if planet in session.planet_instances:
            continue
        nif_path = _planet_nif_path(planet, verbose=verbose)
        if nif_path is None:
            continue
        try:
            handle = r_.load_model(nif_path, _shared_texture_search())
        except Exception as e:
            dev_mode.log_swallowed("realize_set planet load_model", e)
            continue
        center, half = r_.model_aabb(handle)
        natural = _planet_natural_scale(planet, center, half)
        iid = r_.create_instance(handle)
        r_.set_world_transform(iid, _astro_world_matrix(planet, natural))
        session.planet_instances[planet] = iid
        session.planet_natural_scale[planet] = natural


def teardown_set(session, pSet, renderer):
    """Destroy render instances for this set's objects and forget them."""
    for ship in list(_iter_ships_in_set(pSet)):
        iid = session.ship_instances.pop(ship, None)
        if iid is not None:
            renderer.destroy_instance(iid)
            session.ship_glow_controllers.pop(iid, None)
    for planet in list(_iter_planets_in_set(pSet)):
        iid = session.planet_instances.pop(planet, None)
        if iid is not None:
            renderer.destroy_instance(iid)
            session.planet_natural_scale.pop(planet, None)
```

> Implementer notes: reuse the EXACT texture-search and `_planet_natural_scale`/`_astro_world_matrix` logic the load loops use (lines ~2191-2286). If a helper like `_shared_texture_search()` doesn't already exist, inline the same `shared_search` list the loader builds (host_loop.py:2191-2194). Match the loader's behavior; do not invent new scaling.

- [ ] **Step 4: Wire the hooks at host setup**

In `engine/host_loop.py`, where the controller/session/renderer are available at startup (near where the panel registry is built, ~line 3290), register the warp hooks bound to the live session+renderer:

```python
from engine.appc import warp as _warp
def _warp_realize(pSet):
    if controller.session is not None:
        realize_set(controller.session, pSet, controller.renderer)
def _warp_teardown(pSet):
    if controller.session is not None:
        teardown_set(controller.session, pSet, controller.renderer)
_warp.configure_warp_hooks(
    realize=_warp_realize, teardown=_warp_teardown,
    current_player=lambda: controller.session.player if controller.session else None)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_realize_set.py -v`
Expected: PASS.

- [ ] **Step 6: Run the mission-load regression**

Run: `uv run pytest tests/ -k "mission or host_loop or realize" -q`
Expected: PASS (no regression in existing load path).

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_realize_set.py
git commit -m "feat(warp): mid-mission realize_set/teardown_set render hooks"
```

---

### Task 5: CEF Warp button + panel `on_warp` wiring

Add the Warp button to the Set Course panel, resolve the selection to a set module, and hand it to a host-injected callback.

**Files:**
- Modify: `engine/ui/setting_course_panel.py`
- Modify: `native/assets/ui-cef/js/setting_course_panel.js`
- Modify: `native/assets/ui-cef/index.html` (`#setting-course-panel` footer)
- Modify: `native/assets/ui-cef/css/configuration_panel.css` (Warp button style, reuse `cp-*`)
- Test: `tests/unit/test_setting_course_panel.py` (extend)

**Interfaces:**
- Consumes: `sector_model.warp_points_for(sid)` entries now carry `module` (Task 2); `sector_model.system_module(sid)` (Task 2).
- Produces: `SettingCoursePanel(on_warp=None)`; payload gains `"can_warp": bool` and `"warp_label": str`; new event `warp` resolves `self._selected_warp` → module and calls `self._on_warp(module)` then `close()`. A warp row/system-self row exposes `"module"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_setting_course_panel.py  (add)
def test_warp_button_fires_on_warp_with_module():
    fired = {}
    p = SettingCoursePanel(on_warp=lambda m: fired.setdefault("m", m))
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    # pick the first warp point
    data = _payload(p.render_payload())
    wp_id = data["warp_points"][0]["id"]
    assert p.dispatch_event("select-warp:" + wp_id) is True
    data = _payload(p.render_payload())
    assert data["can_warp"] is True
    assert p.dispatch_event("warp") is True
    assert fired["m"] == "Systems.Vesuvi.Vesuvi4"  # first vesuvi warp point module
    assert p.is_open() is False  # panel closed on warp


def test_warp_noop_without_selection():
    p = SettingCoursePanel(on_warp=lambda m: (_ for _ in ()).throw(AssertionError("should not fire")))
    p.open(course_menu=_live_menu())
    assert p.dispatch_event("warp") is False
```

> Implementer: the asserted module must match whatever the re-baked catalog lists as vesuvi's first warp point. Read `sector_model.warp_points_for("vesuvi")[0]["module"]` and use that value in the assertion.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: FAIL (`on_warp` kwarg unknown / no `warp` event / no `can_warp`).

- [ ] **Step 3: Add `on_warp`, module resolution, `can_warp` to the panel**

In `engine/ui/setting_course_panel.py`:

- Constructor: `def __init__(self, on_warp=None):` → after `super().__init__()` set `self._on_warp = on_warp`.
- Add a resolver:

```python
    def _selected_module(self):
        """Set module for the current warp selection, or None."""
        if self._selected_system is None or self._selected_warp is None:
            return None
        sid = self._selected_system
        for wp in sm.warp_points_for(sid):
            if wp["id"] == self._selected_warp:
                return wp.get("module")
        # empty-system self-row: id == system id
        if self._selected_warp == sid:
            return sm.system_module(sid)
        return None
```

- In `render_payload`, add to the payload dict:

```python
            "can_warp": self._selected_module() is not None,
            "warp_label": _warp_button_label(),
```

  where `_warp_button_label()` reads the TGL once (module-level, lru-cached):

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _warp_button_label():
    try:
        from engine.appc.localization import TGLocalizationManager
        db = TGLocalizationManager().Load("data/TGL/Bridge Menus.TGL")
        if db is not None and db.HasString("Warp"):
            return str(db.GetString("Warp"))
    except Exception:
        pass
    return "Warp"
```

- In `dispatch_event`, add the `warp` branch (before the final `return False`):

```python
        if action == "warp":
            module = self._selected_module()
            if module is None:
                return False
            if self._on_warp is not None:
                self._on_warp(module)
            self.close()
            return True
```

- [ ] **Step 4: Add the Warp button to the CEF panel**

In `native/assets/ui-cef/index.html`, inside `#setting-course-panel` after the two-column body, add a footer:

```html
<div class="cp-footer">
  <button id="setting-course-warp" class="cp-done-button" disabled
          onclick="dauntlessEvent('setting-course/warp')">Warp</button>
  <button class="cp-done-button"
          onclick="dauntlessEvent('setting-course/cancel')">Cancel</button>
</div>
```

In `native/assets/ui-cef/js/setting_course_panel.js`, in `setSettingCoursePanel(state)` after rendering the columns, set the button label + enabled state:

```javascript
    var warpBtn = document.getElementById('setting-course-warp');
    if (warpBtn) {
        warpBtn.textContent = state.warp_label || 'Warp';
        warpBtn.disabled = (state.can_warp !== true);
    }
```

In `native/assets/ui-cef/css/configuration_panel.css`, add (the `.cp-done-button` style already exists; add a disabled rule):

```css
.cp-done-button:disabled { opacity: 0.4; cursor: default; }
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: PASS (all existing panel tests + the two new ones).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/setting_course_panel.py native/assets/ui-cef/js/setting_course_panel.js native/assets/ui-cef/index.html native/assets/ui-cef/css/configuration_panel.css tests/unit/test_setting_course_panel.py
git commit -m "feat(warp): Set Course Warp button + on_warp module resolution"
```

---

### Task 6: Fire the authentic event + register `execute_warp` (end-to-end)

Wire the panel's `on_warp` to fire `ET_WARP_BUTTON_PRESSED` on the SDK warp button, register `execute_warp` as the second handler, and verify the full path warps the player (with SDK `WarpPressed` running first). Fix any Appc-surface gap `WarpPressed` surfaces (fail loud → minimal implementation).

**Files:**
- Modify: `engine/host_loop.py` (build `on_warp`; inject into `SettingCoursePanel`; register `execute_warp` after bridge init)
- Test: `tests/integration/test_warp_end_to_end.py` (create)

**Interfaces:**
- Consumes: `warp.execute_warp` (Task 3), `App.SortedRegionMenu_GetWarpButton()`, `App.ET_WARP_BUTTON_PRESSED` (Task 1), `App.g_kEventManager.AddEvent`, `App.TGEvent_Create`, `configure_warp_hooks` (Task 4), `SettingCoursePanel(on_warp=...)` (Task 5).
- Produces: a host `on_warp(module)` that sets the warp button destination and fires the event; `execute_warp` registered on the warp button.

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/integration/test_warp_end_to_end.py
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def _waypoint(name, set_name, x):
    wp = App.Waypoint_Create(name, set_name, None)
    wp.SetTranslateXYZ(x, 0.0, 0.0); wp.Update(0)


def test_event_fire_warps_player(monkeypatch):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)

    # source set + player
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)

    # destination module
    import types, sys
    mod = types.ModuleType("FakeSys.Dst")
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Dst")
        _waypoint("Player Start", "Dst", 42.0)
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dst"] = mod

    # a warp button registered like the SDK does
    btn = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(btn)
    btn.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                        "engine.appc.warp.execute_warp")

    # host on_warp: set destination + fire event
    btn.SetDestination("FakeSys.Dst")
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_WARP_BUTTON_PRESSED)
    ev.SetDestination(btn)
    App.g_kEventManager.AddEvent(ev)

    assert App.g_kSetManager.GetSet("Src") is None
    dst = App.g_kSetManager.GetSet("Dst")
    assert dst.GetObject("player") is player
    assert abs(player.GetWorldLocation().x - 42.0) < 1e-3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_warp_end_to_end.py -v`
Expected: FAIL (no handler registered yet → event is a no-op, source survives).

- [ ] **Step 3: Build `on_warp` and register `execute_warp` in host_loop**

In `engine/host_loop.py`:

- Define `on_warp` near the panel setup (~line 3290):

```python
    def on_warp(module):
        import App
        btn = App.SortedRegionMenu_GetWarpButton()
        if btn is None:
            return
        btn.SetDestination(module)
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_WARP_BUTTON_PRESSED)
        ev.SetDestination(btn)
        App.g_kEventManager.AddEvent(ev)
```

- Inject it: change `setting_course_panel = SettingCoursePanel()` to
  `setting_course_panel = SettingCoursePanel(on_warp=on_warp)`.

- After bridge init / mission load registers the warp button (after the SDK
  `CreateMenus` path runs — i.e. in `post_load_hook` or right after a mission
  loads), register our executor exactly once per warp button:

```python
    def _register_warp_executor():
        import App
        btn = App.SortedRegionMenu_GetWarpButton()
        if btn is not None and not getattr(btn, "_dauntless_warp_wired", False):
            btn.AddPythonFuncHandlerForInstance(
                App.ET_WARP_BUTTON_PRESSED, "engine.appc.warp.execute_warp")
            btn._dauntless_warp_wired = True
```

  Call `_register_warp_executor()` from the existing `post_load_hook` (the hook
  invoked after `loader.load`, host_loop.py:2169) so it runs after every mission
  load once the SDK has created + registered the warp button.

- [ ] **Step 4: Run the end-to-end test**

Run: `uv run pytest tests/integration/test_warp_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 5: Verify SDK `WarpPressed` coexists (regression)**

Run: `uv run pytest tests/ -k "warp or helm or set_course or setting_course" -q`
Expected: PASS. If firing the event in a fuller mission context raises inside SDK `WarpPressed` (e.g. a missing `TopWindow_GetTopWindow().AllowKeyboardInput`, or a `CameraScriptActions` Appc call), implement the minimal missing shim method so `WarpPressed` runs without error — do not guard around it. Document each gap filled in the commit message.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/integration/test_warp_end_to_end.py
git commit -m "feat(warp): fire ET_WARP_BUTTON_PRESSED + register execute_warp end-to-end"
```

---

## Final verification

- [ ] Run the focused suite:
  `uv run pytest tests/ -k "warp or setting_course or sector_model or realize or st_widgets" -q` → all PASS.
- [ ] Run the watchdog-capped full suite: `bash scripts/run_tests.sh` → green.
- [ ] **Human gate (Mark):** relaunch `./build/dauntless`, load a mission, open Helm → Set Course, pick a populated destination (e.g. Vesuvi Dust Cloud) and click **Warp** → scene hard-cuts into the system, player flyable, control restored. Repeat for a single-region system (Riha). Confirm an unselected-warp state leaves the Warp button disabled.

## Self-review notes

- **Spec coverage:** trigger via authentic event (Task 6, per the revised decision), minimal `WarpSequence_Create` (Task 3), `ChangeRenderedSetAction` (Task 3), source terminate-on-arrival (Task 3 `_ArriveFinalizeAction`), per-set render realize/teardown (Task 4), catalog `module` re-bake (Task 2), CEF Warp button from TGL (Task 5), fail-loud load (Task 3, `importlib`/`raise`), destination resolution incl. empty-system self-rows (Tasks 2+5), control restore via `MissionLib.ReturnControl` (Task 3). Covered.
- **Revised decision (vs. spec):** Stage 1 fires the authentic `ET_WARP_BUTTON_PRESSED` (Mark's call during planning), so SDK `WarpPressed` runs; `execute_warp` is registered as a second sibling handler because our `CallNextHandler` is a headless no-op. The warp itself is decoupled into `execute_warp`/the spine, so it works regardless of `WarpPressed`'s side effects; `WarpPressed` must not raise (Task 6 Step 5 fixes any surfaced gap).
- **No-placeholder check:** all code blocks are concrete; the two "match the baked value" notes (Task 3 `_Dummy`, Task 5 module assertion) instruct reading a real value, not inventing one.
