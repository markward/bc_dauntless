# View/Locks Slice 1 — View Pull-Model + SPACE Event Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TopWindow's bridge/tactical flags the single source of truth for the rendered view, dispatch the SPACE toggle through TopWindow's SDK event chain so missions can swallow it, and give `GetRenderedSet()` BC's bridge semantics — without touching exterior lighting, warp, or the in-space cutscene camera.

**Architecture:** Pull model per `docs/superpowers/specs/2026-07-05-mission-view-camera-input-locks-design.md` §1. `_ViewModeController` in host_loop becomes a stateless facade reading `top_window.bridge_flag()` each frame; the default toggle handler is registered in `_TopWindow.__init__` so it is reborn with every singleton rebuild (no mission-load wiring). Engine-internal consumers of the rendered set migrate to a new raw accessor so the SDK-facing `GetRenderedSet()` can adopt bridge-wins semantics safely.

**Tech Stack:** Pure Python (no native/CMake changes in this slice). pytest via `uv run pytest`; full gate via `scripts/check_tests.sh`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-05-mission-view-camera-input-locks-design.md` (§1 View state, §7 lifecycle rule).
- Lifecycle rule: all new state lives on SDK objects rebuilt by `reset_sdk_globals()`; all default handlers registered in the owning object's `__init__`. No wiring at mission load, anywhere.
- Engine-internal code must NOT use `GetRenderedSet()` to find the space set — use `get_explicit_rendered_set()` (Task 3). `GetRenderedSet()` is the SDK-facing surface.
- Never orphan tests: every behavior change updates its tests in the same task. A failure is "pre-existing" only if `scripts/check_tests.sh` says so via `tests/known_failures.txt`.
- Branch in the main checkout, NOT a worktree (`sdk/` + `game/` are gitignored and only exist here).
- Python 3 engine code style: match surrounding code; lazy imports inside methods for cross-module `engine.appc` references (established pattern, avoids cycles).
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Pre-flight

- [ ] `git checkout -b feat/view-sync-pull-model` (from up-to-date `main`)
- [ ] `uv run pytest tests/unit/test_top_window.py tests/host/test_view_mode.py tests/unit/test_set.py -q` — all pass before starting. Expected: PASS (baseline).

---

### Task 1: TopWindow — real event chain + default toggle handler + bridge-visible default

**Files:**
- Modify: `engine/appc/top_window.py`
- Modify: `engine/appc/events.py` (add event-type constant)
- Modify: `App.py:849` (alias the constant instead of a duplicate literal)
- Test: `tests/unit/test_top_window.py`

**Interfaces:**
- Consumes: `TGEvent`, `TGEventHandlerObject` from `engine/appc/events.py` (existing LIFO chain: `AddPythonFuncHandlerForInstance(event_type: int, qualified_name: str)`, `ProcessEvent(event)`, `CallNextHandler(event)` — handlers are resolved from `sys.modules` by qualified name and called as `fn(dispatcher, event)`).
- Produces: `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL: int = 1055` in `engine.appc.events`; `_TopWindow.ProcessEvent(event)`, `_TopWindow.AddPythonFuncHandlerForInstance(event_type, qualified_name, *_extra)`, `_TopWindow.RemoveHandlerForInstance(event_type, qualified_name)` — real chain dispatch; module functions `bridge_flag() -> bool` and `dispatch_toggle_bridge_and_tactical() -> None` (Task 2 adds the latter); default `_bridge_visible=True`.

- [ ] **Step 1: Write the failing tests**

Replace the two `_handler_registrations` tests (currently at `tests/unit/test_top_window.py:469` and `:484` — they assert against the record-only list, which this task deletes) and the default-flag assertions (`:189` asserts `IsBridgeVisible() is False`; the reset test near `:444` asserts the fresh singleton is `False`) with the following. Also add the new chain tests. Module-level handler functions are required because the chain resolves handlers via `sys.modules[module].func`:

```python
# --- module scope in tests/unit/test_top_window.py ---
_chain_log = []

def _swallowing_handler(dispatcher, event):
    _chain_log.append("swallow")
    # returns WITHOUT CallNextHandler -> chain stops (E1M1 tutorial shape)

def _passthrough_handler(dispatcher, event):
    _chain_log.append("pass")
    dispatcher.CallNextHandler(event)


def test_default_view_is_bridge():
    from engine.appc.top_window import _TopWindow
    tw = _TopWindow()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


def test_reset_restores_bridge_default():
    import engine.appc.top_window as top_window
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    top_window.reset_for_tests()
    assert top_window.TopWindow_GetTopWindow().IsBridgeVisible() is True


def test_toggle_event_default_handler_flips_view():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is True
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_mission_handler_swallows_toggle():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, __name__ + "._swallowing_handler")
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == ["swallow"]
    assert tw.IsBridgeVisible() is True      # default never ran — view held


def test_mission_handler_passthrough_reaches_default():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, __name__ + "._passthrough_handler")
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == ["pass"]
    assert tw.IsBridgeVisible() is False     # default ran via CallNextHandler


def test_remove_handler_for_instance():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    name = __name__ + "._swallowing_handler"
    tw.AddPythonFuncHandlerForInstance(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, name)
    tw.RemoveHandlerForInstance(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, name)
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == []                  # removed handler never fired
    assert tw.IsBridgeVisible() is False     # default still ran


def test_reset_rebuilds_default_handler():
    # The lifecycle rule: the default lives in __init__, so a singleton
    # rebuild (mission swap) must re-arm it with no external wiring.
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    top_window.reset_for_tests()             # twice — idempotent
    tw = top_window.TopWindow_GetTopWindow()
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert tw.IsBridgeVisible() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -q`
Expected: the new tests FAIL (`IsBridgeVisible() is True` assertion fails on default; `ImportError: cannot import name 'ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL'`; `ProcessEvent` raises `AttributeError`). The two old `_handler_registrations` tests you replaced are gone.

- [ ] **Step 3: Implement**

In `engine/appc/events.py`, next to the other module-level event-type constants (grep `ET_` at module scope; add near them):

```python
# SPACE-bar bridge/tactical toggle. Value must stay in sync with the SDK's
# event id; App.py re-exports this name (missions reference it as
# App.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL when registering
# TacticalToggleHandler — E1M1.py:858, E1M2.py:1155).
ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 1055
```

In `App.py`: delete the literal at line 849 (`ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 1055`) and add `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL` to the existing `from engine.appc.events import (...)` block at the top of the file.

In `engine/appc/top_window.py`:

1. Add to the module imports (top of file — events.py does not import top_window, so this is cycle-safe):

```python
from engine.appc.events import TGEventHandlerObject, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
```

2. In `_TopWindow.__init__`, flip the view defaults and replace the record-only registration list with a real dispatcher (delete `self._handler_registrations = ...`):

```python
        self._bridge_visible: bool = True
        self._tactical_visible: bool = False
        ...
        # Instance event chain (composition, not inheritance: _TopWindow
        # stays a plain class so missing methods raise AttributeError
        # instead of vending _Stubs — see the focus/z-order comment below).
        # The default toggle handler is registered HERE so every singleton
        # rebuild (mission swap via reset_for_tests) re-arms it with no
        # external wiring — spec §7 lifecycle rule.
        self._events = TGEventHandlerObject()
        self._events.AddPythonFuncHandlerForInstance(
            ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
            "engine.appc.top_window._default_toggle_handler",
        )
```

3. Replace the `AddPythonFuncHandlerForInstance` method (and its "record but don't dispatch" comment) with real delegation, and add the two missing chain methods:

```python
    # ── Event handler chain ────────────────────────────────────
    # SDK code registers per-instance handlers (E1M1/E1M2
    # TacticalToggleHandler) and swallows events by returning without
    # CallNextHandler; the chain is LIFO (see TGEventHandlerObject).
    def AddPythonFuncHandlerForInstance(
        self, event_type, qualified_name, *_extra
    ) -> None:
        self._events.AddPythonFuncHandlerForInstance(
            int(event_type), str(qualified_name))

    def RemoveHandlerForInstance(self, event_type, qualified_name) -> None:
        self._events.RemoveHandlerForInstance(
            int(event_type), str(qualified_name))

    def ProcessEvent(self, event) -> None:
        self._events.ProcessEvent(event)
```

4. Add the module-level default handler and flag reader (next to `keyboard_input_enabled`):

```python
def _default_toggle_handler(_dispatcher, _event) -> None:
    """Bottom-of-chain default for ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL.
    Runs synchronously inside CallNextHandler — E1M1's TacticalToggleHandler
    reads IsBridgeVisible() immediately after CallNextHandler and expects
    the flip to have already happened (E1M1.py:1194-1198)."""
    _the_top_window.ToggleBridgeAndTactical()


def bridge_flag() -> bool:
    """Per-frame view selector consulted by host_loop's
    _ViewModeController. Function, not constant: read at frame time."""
    return _the_top_window._bridge_visible
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -q`
Expected: PASS (all, including the pre-existing tests — `ForceBridgeVisible`/`ForceTacticalVisible`/`Toggle` behavior is unchanged, only defaults moved).

- [ ] **Step 5: Check for stray consumers of the deleted list and old default**

Run: `grep -rn "_handler_registrations" engine/ tests/ App.py`
Expected: no matches. If any appear, migrate them to chain-behavior assertions in this task.

Run: `uv run pytest tests/unit -q`
Expected: PASS except possibly tests asserting the old tactical-first default outside test_top_window.py — fix any such assertion in this task (same-change rule).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/top_window.py engine/appc/events.py App.py tests/unit/test_top_window.py
git commit -m "feat(view): TopWindow event chain + constructor-armed default toggle, bridge-visible default

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: SPACE dispatch helper on top_window

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

**Interfaces:**
- Consumes: Task 1's chain (`ProcessEvent`, default handler).
- Produces: `engine.appc.top_window.dispatch_toggle_bridge_and_tactical() -> None` — the single entry point host_loop calls on a SPACE edge (Task 5).

- [ ] **Step 1: Write the failing test**

```python
def test_dispatch_toggle_helper_round_trip():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is True
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is False
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is True


def test_dispatch_toggle_helper_respects_mission_swallow():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._swallowing_handler")
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is True      # held on bridge
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_top_window.py -k dispatch_toggle -q`
Expected: FAIL — `AttributeError: module 'engine.appc.top_window' has no attribute 'dispatch_toggle_bridge_and_tactical'`.

- [ ] **Step 3: Implement**

In `engine/appc/top_window.py`, extend the events import and add the helper next to `bridge_flag`:

```python
from engine.appc.events import (
    TGEvent,
    TGEventHandlerObject,
    ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
)
```

```python
def dispatch_toggle_bridge_and_tactical() -> None:
    """Host entry point for the SPACE key: routes the toggle through the
    TopWindow instance-handler chain so missions can swallow it
    (E1M1/E1M2 TacticalToggleHandler hold the player on the bridge
    during tutorials by returning without CallNextHandler)."""
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    _the_top_window.ProcessEvent(ev)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_top_window.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(view): dispatch_toggle_bridge_and_tactical routes SPACE through the SDK chain

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: SetManager — raw accessor + bridge-wins GetRenderedSet

**Files:**
- Modify: `engine/appc/sets.py:479-496` (`GetRenderedSet`, new `get_explicit_rendered_set`)
- Test: `tests/unit/test_set.py`

**Interfaces:**
- Consumes: `engine.appc.top_window.bridge_flag()` (Task 1).
- Produces: `SetManager.get_explicit_rendered_set() -> SetClass | None` (raw `MakeRenderedSet` name lookup — the engine-internal surface Task 4 migrates callers to); `SetManager.GetRenderedSet()` returns the set registered as `"bridge"` whenever `bridge_flag()` is true and that set exists, else falls back to the raw lookup.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_set.py` (match its existing import style):

```python
def _fresh_manager_with_bridge():
    import App
    from engine.appc.sets import SetManager, SetClass
    mgr = SetManager()
    bridge = SetClass()
    space = SetClass()
    mgr.AddSet(bridge, "bridge")
    mgr.AddSet(space, "Vesuvi6")
    return mgr, bridge, space


def test_rendered_set_is_bridge_while_bridge_visible():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()                      # bridge visible (default)
    mgr, bridge, space = _fresh_manager_with_bridge()
    mgr.MakeRenderedSet("Vesuvi6")
    # SDK-facing: on the bridge, the bridge IS the rendered set
    # (MissionLib.EndCutscene's restore conditional, MissionLib.py:790).
    assert mgr.GetRenderedSet() is bridge
    # Engine-internal: the explicit MakeRenderedSet target is unaffected.
    assert mgr.get_explicit_rendered_set() is space


def test_rendered_set_follows_explicit_when_tactical():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    mgr, bridge, space = _fresh_manager_with_bridge()
    mgr.MakeRenderedSet("Vesuvi6")
    assert mgr.GetRenderedSet() is space
    assert mgr.get_explicit_rendered_set() is space


def test_rendered_set_bridge_flag_without_bridge_set_falls_back():
    # Headless harnesses have no "bridge" set registered; the flag must
    # not make GetRenderedSet return None-forever.
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()                      # bridge visible
    from engine.appc.sets import SetManager, SetClass
    mgr = SetManager()
    space = SetClass()
    mgr.AddSet(space, "Vesuvi6")
    mgr.MakeRenderedSet("Vesuvi6")
    assert mgr.GetRenderedSet() is space
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_set.py -q`
Expected: new tests FAIL (`AttributeError: 'SetManager' object has no attribute 'get_explicit_rendered_set'`; bridge-wins assertion fails).

- [ ] **Step 3: Implement**

In `engine/appc/sets.py`, replace `GetRenderedSet` (line 479) and add the raw accessor beside it (keep `ClearRenderedSet`/`MakeRenderedSet` untouched):

```python
    def GetRenderedSet(self) -> "SetClass | None":
        # BC semantics (SDK-facing): while the bridge is visible the bridge
        # IS the rendered set — MissionLib.EndCutscene compares
        # str(GetSet("bridge")) against str(GetRenderedSet()) to decide
        # whether to restore bridge or tactical view (MissionLib.py:790),
        # and E1M1 relies on the same comparison. Engine-internal code that
        # needs the explicit MakeRenderedSet target (exterior lighting,
        # in-space cutscene camera, warp guards) must use
        # get_explicit_rendered_set() instead.
        from engine.appc.top_window import bridge_flag
        if bridge_flag():
            bridge = self._sets.get("bridge")
            if bridge is not None:
                return bridge
        return self.get_explicit_rendered_set()

    def get_explicit_rendered_set(self) -> "SetClass | None":
        """Raw MakeRenderedSet-name lookup, ignoring the bridge-visible
        flag. Engine-internal surface — not part of the SDK App API."""
        if self._rendered_set_name is None:
            return None
        return self._sets.get(self._rendered_set_name)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_set.py tests/unit/test_top_window.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_set.py
git commit -m "feat(sets): GetRenderedSet reports the bridge while bridge-visible; raw accessor for engine internals

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Migrate engine-internal rendered-set consumers to the raw accessor

**Files:**
- Modify: `engine/host_loop.py:2815` (`_resolve_active_set`), `engine/host_loop.py:3812` (`_active_cutscene_camera`)
- Modify: `engine/appc/warp.py:439` and `engine/appc/warp.py:447` (warp-transit guards)
- Test: `tests/unit/test_set.py` (regression guard), existing lighting/warp/cutscene-camera tests stay green

**Interfaces:**
- Consumes: `SetManager.get_explicit_rendered_set()` (Task 3).
- Produces: nothing new — behavior preservation. Exterior lighting, the in-space cutscene camera, and warp guards must be byte-identical in behavior whether or not the bridge is visible.

- [ ] **Step 1: Write the failing regression test**

The sharp edge this task exists for: with bridge-wins `GetRenderedSet()` (Task 3) and the player on the bridge, `_resolve_active_set` would light the exterior scene from the bridge set, and warp's `GetRenderedSet() is not transit` guard would misfire during warp-from-bridge. Add to `tests/unit/test_set.py`:

```python
def test_resolve_active_set_ignores_bridge_visibility():
    # Exterior lighting must key off the explicit rendered set even while
    # the player is on the bridge (bridge sets have their own lights; the
    # exterior scene must not inherit them).
    import App
    import engine.appc.top_window as top_window
    from engine.appc.sets import SetClass
    from engine.host_loop import _resolve_active_set

    top_window.reset_for_tests()                      # bridge visible
    App.g_kSetManager._sets.clear()
    App.g_kSetManager._rendered_set_name = None

    bridge = SetClass()
    bridge._lights = [object()]                       # bridge has lights
    space = SetClass()
    space._lights = [object()]
    App.g_kSetManager.AddSet(bridge, "bridge")
    App.g_kSetManager.AddSet(space, "Vesuvi6")
    App.g_kSetManager.MakeRenderedSet("Vesuvi6")

    assert _resolve_active_set(None) is space
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_set.py::test_resolve_active_set_ignores_bridge_visibility -q`
Expected: FAIL — `_resolve_active_set` returns the bridge set (it still calls `GetRenderedSet()`).

- [ ] **Step 3: Implement the migration**

Four one-line changes, replacing `GetRenderedSet()` with `get_explicit_rendered_set()`:

- `engine/host_loop.py:2815` in `_resolve_active_set`:
  ```python
    rendered = App.g_kSetManager.get_explicit_rendered_set()
  ```
  Also update the docstring line above it (`1. g_kSetManager.GetRenderedSet() — set explicitly via`) to name `get_explicit_rendered_set()`.
- `engine/host_loop.py:3812` in `_active_cutscene_camera`:
  ```python
    rendered = _App.g_kSetManager.get_explicit_rendered_set()
  ```
- `engine/appc/warp.py:439`:
  ```python
        if App.g_kSetManager.get_explicit_rendered_set() is not src:
  ```
- `engine/appc/warp.py:447`:
  ```python
        if transit is not None and App.g_kSetManager.get_explicit_rendered_set() is not transit:
  ```

Then verify no other engine-internal caller remains:

Run: `grep -rn "GetRenderedSet()" engine/ App.py`
Expected: only `engine/appc/sets.py` (the definition and its internal fallback). Any other hit in `engine/` is an internal consumer this task must migrate the same way (SDK scripts under `sdk/` are untouched, they get the SDK-facing behavior on purpose).

- [ ] **Step 4: Run to verify pass + no collateral**

Run: `uv run pytest tests/unit/test_set.py -q && uv run pytest tests/unit -q -k "light or warp or cutscene"`
Expected: PASS — the new regression test and every existing lighting/warp/cutscene-camera test.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/appc/warp.py tests/unit/test_set.py
git commit -m "fix(sets): lighting, cutscene camera, warp guards read the explicit rendered set

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: _ViewModeController becomes a facade over TopWindow

**Files:**
- Modify: `engine/host_loop.py:1638-1670` (`_ViewModeController`)
- Test: `tests/host/test_view_mode.py`, `tests/unit/test_bridge_camera_anim.py` (existing consumers), `tests/conftest.py` (only if Step 5 shows top_window isn't reset by the autouse fixture)

**Interfaces:**
- Consumes: `top_window.bridge_flag()`, `top_window.dispatch_toggle_bridge_and_tactical()`, `TopWindow_GetTopWindow().ForceBridgeVisible()/ToggleBridgeAndTactical()`.
- Produces: same public surface as today — `is_bridge`, `is_exterior` (properties), `toggle()`, `set_bridge()`, `apply(h)` — so `_apply_view_mode_side_effects`, `_apply_input`, `_compute_camera`, `bridge_cutscene`, and the `run()` body need **zero changes**. The `_last_synced_is_bridge` attribute writes at `host_loop.py:1736/1814/1860` keep working (plain instance attribute).

- [ ] **Step 1: Update/extend the tests first**

`tests/host/test_view_mode.py` constructs `_ViewModeController()` and asserts toggle behavior on private `_mode` semantics. Rework its state assertions to go through the public properties, add `top_window.reset_for_tests()` at the top of each test (the controller is now a view over the singleton), and add the two new behaviors:

```python
def test_space_edge_dispatches_through_top_window_chain():
    """SPACE must route through the SDK event chain (missions swallow it),
    not flip state directly."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    _chain_log.clear()
    top_window.TopWindow_GetTopWindow().AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._swallowing_handler")
    vm = _ViewModeController()
    assert vm.is_bridge

    class _H:
        class keys: KEY_SPACE = 32
        def key_pressed(self, code): return code == self.keys.KEY_SPACE
    vm.apply(_H())
    assert _chain_log == ["swallow"]
    assert vm.is_bridge                      # held on bridge by the mission


def test_controller_reads_top_window_truth():
    """ForceBridgeVisible from SDK code must be visible to the host with
    no listener wiring — the pull model's core promise."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    vm = _ViewModeController()
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    assert vm.is_exterior
    top_window.TopWindow_GetTopWindow().ForceBridgeVisible()
    assert vm.is_bridge
```

(with module-level `_chain_log` / `_swallowing_handler` helpers as in Task 1, defined in this test module).

Keep every existing test in the file, adapted only where it reached into `vm._mode` or assumed construction-time state isolation; each keeps its current behavioral intent (toggle flips, apply edge-triggers, `_apply_input` suppresses ship input on bridge, etc.).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/host/test_view_mode.py -q`
Expected: new tests FAIL (`_ViewModeController` has no chain dispatch; `is_bridge` doesn't track TopWindow).

- [ ] **Step 3: Implement the facade**

Replace the `_ViewModeController` class body (`engine/host_loop.py:1638-1670`) with:

```python
class _ViewModeController:
    """Bridge/exterior view modality — a stateless facade over the SDK
    TopWindow flags (engine/appc/top_window.py), which are the single
    source of truth (pull model; spec
    docs/superpowers/specs/2026-07-05-mission-view-camera-input-locks-design.md §1).

    SPACE dispatches ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL through
    TopWindow's instance-handler chain so missions can swallow the toggle
    (E1M1/E1M2 TacticalToggleHandler); the bottom-of-chain default
    performs the flag flip synchronously during dispatch. SDK calls like
    ForceBridgeVisible are plain flag writes the next frame's read picks
    up — no listeners, nothing to re-wire on mission swap.
    """

    @property
    def is_bridge(self) -> bool:
        from engine.appc.top_window import bridge_flag
        return bridge_flag()

    @property
    def is_exterior(self) -> bool:
        return not self.is_bridge

    def toggle(self) -> None:
        from engine.appc.top_window import TopWindow_GetTopWindow
        TopWindow_GetTopWindow().ToggleBridgeAndTactical()

    def set_bridge(self) -> None:
        """Force bridge view (used to start a bridge cutscene)."""
        from engine.appc.top_window import TopWindow_GetTopWindow
        TopWindow_GetTopWindow().ForceBridgeVisible()

    def apply(self, h) -> None:
        """Poll space-pressed; on edge, route through the SDK chain."""
        if h.key_pressed(h.keys.KEY_SPACE):
            from engine.appc.top_window import (
                dispatch_toggle_bridge_and_tactical,
            )
            dispatch_toggle_bridge_and_tactical()
```

(The `EXTERIOR`/`BRIDGE` class constants and `__init__` are deleted; `_last_synced_is_bridge` is set externally by the side-effect functions and needs no declaration.)

- [ ] **Step 4: Run the affected suites**

Run: `uv run pytest tests/host/test_view_mode.py tests/unit/test_bridge_camera_anim.py tests/unit/test_bridge_cutscene.py tests/unit/test_top_window.py -q`
Expected: PASS.

- [ ] **Step 5: Verify cross-test isolation**

The controller now reads singleton state, so leaked view flags between tests would be order-dependent breakage. Check `tests/conftest.py`'s autouse `_reset_leakable_engine_globals` fixture: if it does not already call `engine.appc.top_window.reset_for_tests()`, add it there (one line, alongside the other reset calls). Then:

Run: `uv run pytest tests/host tests/unit -q`
Expected: PASS (full python unit+host suites, any order).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_view_mode.py tests/unit/test_bridge_camera_anim.py tests/conftest.py
git commit -m "feat(view): _ViewModeController pulls TopWindow truth; SPACE routes through the SDK chain

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: E1M1-shaped integration test — synchronous default + EndCutscene restore seam

**Files:**
- Create: `tests/host/test_space_toggle_mission_semantics.py`

**Interfaces:**
- Consumes: everything above. No production code changes — this task locks in the two SDK contracts the missions depend on.

- [ ] **Step 1: Write the tests (they should pass immediately if Tasks 1–5 are correct — this is a contract-freeze task, RED only if something above is wrong)**

```python
"""Mission-shaped contracts for the SPACE toggle + cutscene view restore.

Mirrors E1M1.py:1187-1204 (TacticalToggleHandler) and
MissionLib.py:788-802 (EndCutscene's restore conditional) without
importing the SDK: the shapes are copied verbatim so a regression here
means those mission code paths break live.
"""

_tutorial_active = [False]
_seen_after_callnext = []


def _mission_tactical_toggle_handler(dispatcher, event):
    # E1M1.py:1187: swallow during tutorial (return, no CallNextHandler)
    if _tutorial_active[0]:
        return
    # E1M1.py:1194: pass on, THEN read the flag — the default must have
    # run synchronously inside CallNextHandler.
    dispatcher.CallNextHandler(event)
    import engine.appc.top_window as top_window
    _seen_after_callnext.append(
        top_window.TopWindow_GetTopWindow().IsBridgeVisible())


def _install(top_window):
    top_window.TopWindow_GetTopWindow().AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._mission_tactical_toggle_handler")


def test_tutorial_swallow_holds_bridge_view():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _tutorial_active[0] = True
    _install(top_window)
    top_window.dispatch_toggle_bridge_and_tactical()
    assert top_window.TopWindow_GetTopWindow().IsBridgeVisible() is True


def test_callnexthandler_sees_flipped_flag_synchronously():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _tutorial_active[0] = False
    _seen_after_callnext.clear()
    _install(top_window)
    top_window.dispatch_toggle_bridge_and_tactical()     # bridge -> tactical
    assert _seen_after_callnext == [False]
    top_window.dispatch_toggle_bridge_and_tactical()     # tactical -> bridge
    assert _seen_after_callnext == [False, True]


def test_end_cutscene_restore_conditional_shape():
    """MissionLib.py:790: if str(bridge_set) != str(rendered_set) force
    tactical, else force bridge. Both branches, driven only by view state."""
    import App
    import engine.appc.top_window as top_window
    from engine.appc.sets import SetClass

    top_window.reset_for_tests()                          # bridge visible
    App.g_kSetManager._sets.clear()
    App.g_kSetManager._rendered_set_name = None
    bridge, space = SetClass(), SetClass()
    App.g_kSetManager.AddSet(bridge, "bridge")
    App.g_kSetManager.AddSet(space, "Vesuvi6")
    App.g_kSetManager.MakeRenderedSet("Vesuvi6")

    pBridgeSet = App.g_kSetManager.GetSet("bridge")

    # Player on the bridge when the cutscene ends -> bridge branch
    # (the user-observed "always returns to bridge" for E1M1/E1M2).
    assert str(pBridgeSet) == str(App.g_kSetManager.GetRenderedSet())

    # Player toggled to tactical before the cutscene ends -> tactical branch.
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    assert str(pBridgeSet) != str(App.g_kSetManager.GetRenderedSet())
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/host/test_space_toggle_mission_semantics.py -v`
Expected: PASS (3/3). If any fail, fix the responsible earlier task — do not adjust these contracts.

- [ ] **Step 3: Commit**

```bash
git add tests/host/test_space_toggle_mission_semantics.py
git commit -m "test(view): freeze E1M1/MissionLib SPACE-toggle and cutscene-restore contracts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Full gate + live-verify handoff

**Files:**
- None new (gate + docs check only).

- [ ] **Step 1: Run the full machine-checked gate (both suites — never pytest-only)**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression introduced by this branch — fix it before proceeding (the ledger is currently expected to be empty).

- [ ] **Step 2: Sanity-run the real binary boot path**

Run: `cmake --build build -j && ./build/dauntless --help 2>&1 | head -5` (build should be a no-op — this slice is pure Python — but proves no stale-binary surprise).
Expected: builds clean; binary prints usage/boots.

- [ ] **Step 3: Hand off for live verification (user-run; do NOT interact with the desktop)**

Present this checklist to the user verbatim:

1. Launch `./build/dauntless`, enter QuickBattle or E1M1: game starts in **bridge view**.
2. Press SPACE repeatedly: toggles bridge ↔ exterior both ways, every press.
3. Start E1M1, reach the tutorial beat after the briefing: pressing SPACE does **nothing** (mission holds you on the bridge); after the tutorial releases, SPACE works again.
4. E1M1 crew-intro sequence: the DryDock exterior shots render (in-space cutscene camera unaffected), and the sequence returns you to the **bridge**.
5. Warp from the bridge view (Set Course → engage): warp transit renders normally and you stay on the bridge throughout.
6. Exterior scene lighting/backdrops look unchanged in both views (no bridge-light bleed into space).

**STOP after this task.** Slice 2 (input policy + gates) gets its own plan only after the user confirms all six live checks. If any check fails, apply superpowers:systematic-debugging against this slice only.

---

## Explicitly deferred (later slices — do not implement here)

- Input policy / keyboard+mouse gates, camera freeze (Slice 2)
- Root-window skip-key synthesis (Slice 2)
- Letterbox/fade/reticle/TCW/subtitle overlay — `StartCutscene` arg handling stays flag-only in this slice (Slice 3)
- `LookForward`, `GetOpenMenu` (Slice 4)
- `ET_CHARACTER_MENU` / `ET_SET_ALERT_LEVEL` dispatch (Slice 5)
