# Warp Collision Suppression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ship in inter-system warp cannot collide with anything, from align-out until it has decelerated back to impulse on arrival.

**Architecture:** Drive BC's own `WarpEngineSubsystem` state machine (which our engine currently never sets, leaving it permanently at `WES_NOT_WARPING`), then derive collision suppression from it: a `ShipClass` whose warp state is not `WES_NOT_WARPING` is filtered out of collision resolution. The predicate is per-ship and script-observable, exactly as BC intends. The SDK's `SetCollisionsOn` flag is left untouched and composes with the suppression.

**Tech Stack:** Python 3 (`engine/appc/`), pytest. No C++ / native change — `engine/appc/collisions.py` is pure Python.

**Spec:** `docs/superpowers/specs/2026-07-13-warp-collision-suppression-design.md`

## Global Constraints

- **Never duck-type the warp-subsystem read.** `TGObject.__getattr__` returns a **truthy** `_Stub` for any unknown attribute, `_Stub()` calls return `_Stub`, and `_Stub.__ne__(0)` is `True` (`App.py:1955`). A `Planet` has no `GetWarpEngineSubsystem`, so a duck-typed predicate would make **every planet, moon and sun non-collidable**. Every warp-state read must be `isinstance(obj, ShipClass)`-guarded first.
- **Never use `getattr(obj, name, None)` to test for an unset instance attribute** on a `TGObject` subclass — it returns a truthy `_Stub`, not `None`. Use `obj.__dict__.get(name)`. See the comment at `engine/appc/collisions.py:43-50`.
- **Do not touch `_collisions_on`** (`engine/appc/objects.py:647`) or `CanCollide()`. Warp suppression is a separate, engine-owned overlay that composes with the SDK flag.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball. `scripts/run_tests.sh` is pytest-only and is not the gate.
- Run tests with `uv run pytest`.

---

### Task 1: Make `WarpEngineSubsystem.TransitionToState` real, with auto-completion

The SDK's NPC warp-in (`sdk/Build/scripts/Actions/EffectScriptActions.py:225-226`) does `SetWarpState(WES_WARPING)` then `TransitionToState(WES_DEWARP_INITIATED)`. `TransitionToState` is currently an unimplemented stub (silent no-op — stub heatmap rank 136), so an SDK-warped-in NPC would sit at a non-zero warp state **forever**. Once Task 4 lands, that would make the ship permanently non-collidable. The engine must run the dewarp to completion, as the C++ engine does.

**Files:**
- Modify: `engine/appc/subsystems.py:1225-1263` (class `WarpEngineSubsystem`)
- Test: `tests/unit/test_warp_engine_subsystem.py` (create)

**Interfaces:**
- Produces:
  - `WarpEngineSubsystem.DEWARP_STATES` — `frozenset({5, 6, 7})` (`WES_DEWARP_INITIATED`, `WES_DEWARP_BEGINNING`, `WES_DEWARP_ENDING`)
  - `WarpEngineSubsystem.TransitionToState(state: int) -> None`
  - `WarpEngineSubsystem.tick_transition(dt: float) -> None`
  - `WarpEngineSubsystem.IsWarping() -> bool`
  - `WarpEngineSubsystem.DEFAULT_DEWARP_SECONDS` — `2.0`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_warp_engine_subsystem.py`:

```python
"""WarpEngineSubsystem FSM: SetWarpState is the SDK setter; TransitionToState
is the engine-driven one that must run a dewarp to completion (the SDK's
EffectScriptActions.WarpEnterSet fires it and never clears the state itself)."""
import pytest
from engine.appc.subsystems import WarpEngineSubsystem


def _warp():
    return WarpEngineSubsystem("Warp Engines")


def test_fresh_subsystem_is_not_warping():
    w = _warp()
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.IsWarping() is False


def test_set_warp_state_marks_warping():
    w = _warp()
    w.SetWarpState(WarpEngineSubsystem.WES_WARPING)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_WARPING
    assert w.IsWarping() is True


def test_transition_to_dewarp_auto_completes_to_not_warping():
    # The SDK's WarpEnterSet path: SetWarpState(WARPING) then
    # TransitionToState(DEWARP_INITIATED) and nothing else. The engine must
    # land it back on NOT_WARPING, or the ship is stranded mid-warp forever.
    w = _warp()
    w.SetWarpEffectTime(3.0)
    w.SetWarpState(WarpEngineSubsystem.WES_WARPING)
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_INITIATED)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_DEWARP_INITIATED

    w.tick_transition(1.0)
    assert w.IsWarping() is True          # 2.0 s still to run

    w.tick_transition(2.5)                # past the 3.0 s effect time
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.IsWarping() is False


def test_transition_uses_default_when_effect_time_unset():
    w = _warp()                            # GetWarpEffectTime() == 0.0
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_ENDING)
    w.tick_transition(WarpEngineSubsystem.DEFAULT_DEWARP_SECONDS - 0.1)
    assert w.IsWarping() is True
    w.tick_transition(0.2)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING


def test_transition_to_outbound_state_does_not_auto_complete():
    # Outbound warp states are held until the engine explicitly clears them —
    # only the DEWARP_* states have a completion deadline.
    w = _warp()
    w.TransitionToState(WarpEngineSubsystem.WES_WARPING)
    w.tick_transition(1000.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_WARPING


def test_tick_transition_is_a_noop_when_not_warping():
    w = _warp()
    w.tick_transition(5.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING


def test_set_warp_state_not_warping_cancels_a_pending_transition():
    w = _warp()
    w.TransitionToState(WarpEngineSubsystem.WES_DEWARP_INITIATED)
    w.SetWarpState(WarpEngineSubsystem.WES_NOT_WARPING)
    w.tick_transition(0.0)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    assert w.__dict__.get("_transition_remaining") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_warp_engine_subsystem.py -v`
Expected: FAIL — `AttributeError: 'WarpEngineSubsystem' object has no attribute 'IsWarping'` (and `DEFAULT_DEWARP_SECONDS`). Note `TransitionToState` will NOT raise: `TGObject.__getattr__` answers it with a silent no-op `_Stub` — which is precisely the bug being fixed.

- [ ] **Step 3: Implement**

In `engine/appc/subsystems.py`, inside `class WarpEngineSubsystem`, after the `WES_*` constants (currently ending at `WES_DEWARP_ENDING = 7`, line 1236), add:

```python
    # The inbound half of the FSM. Only these states carry a completion
    # deadline: the SDK fires TransitionToState(WES_DEWARP_*) and expects the
    # engine to run the dewarp out (Actions/EffectScriptActions.py:226) — with
    # no completion the ship is stranded mid-warp forever.
    DEWARP_STATES = frozenset((5, 6, 7))

    # Used when a script transitions to a dewarp state without ever setting a
    # warp effect time (GetWarpEffectTime() == 0.0).
    DEFAULT_DEWARP_SECONDS = 2.0
```

In `__init__`, after `self._warp_state = self.WES_NOT_WARPING` (line 1245), add:

```python
        # Seconds left on an engine-driven dewarp transition; None when no
        # transition is pending. See TransitionToState / tick_transition.
        self._transition_remaining = None
```

Replace `SetWarpState` (lines 1262-1263) and add the new methods:

```python
    def SetWarpState(self, state) -> None:
        """SDK setter — sets the state outright, with no transition. Clearing
        to WES_NOT_WARPING cancels any pending dewarp completion."""
        self._warp_state = int(state)
        if self._warp_state == self.WES_NOT_WARPING:
            self._transition_remaining = None

    def TransitionToState(self, state) -> None:
        """SDK `WarpEngineSubsystem_TransitionToState` (App.py:6747): enter a
        state that the ENGINE then runs to completion. The SDK's NPC warp-in
        (Actions/EffectScriptActions.py:225-226) sets WES_WARPING and then
        transitions to WES_DEWARP_INITIATED, and never touches the state
        again — so a dewarp transition must land back on WES_NOT_WARPING by
        itself, or the ship stays 'warping' for the rest of the mission."""
        self._warp_state = int(state)
        if self._warp_state in self.DEWARP_STATES:
            t = self.GetWarpEffectTime()
            self._transition_remaining = t if t > 0.0 else self.DEFAULT_DEWARP_SECONDS
        else:
            self._transition_remaining = None

    def tick_transition(self, dt: float) -> None:
        """Advance a pending dewarp transition; land on WES_NOT_WARPING when it
        expires. Driven by engine.appc.warp_state.tick_warp_states."""
        remaining = self._transition_remaining
        if remaining is None:
            return
        remaining -= float(dt)
        if remaining <= 0.0:
            self._warp_state = self.WES_NOT_WARPING
            self._transition_remaining = None
        else:
            self._transition_remaining = remaining

    def IsWarping(self) -> bool:
        """True for every state other than WES_NOT_WARPING — the same test BC's
        own scripts make (WarpSequence.py:638, HelmMenuHandlers.py:2465)."""
        return self._warp_state != self.WES_NOT_WARPING
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_engine_subsystem.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_warp_engine_subsystem.py
git commit -m "feat(warp): implement WarpEngineSubsystem.TransitionToState with dewarp completion

TransitionToState was an unimplemented stub (heatmap rank 136), so the SDK's
own NPC warp-in (EffectScriptActions.WarpEnterSet) set WES_WARPING, asked for
a DEWARP transition, and left the ship 'warping' for the rest of the mission.
The engine now runs a dewarp to completion over GetWarpEffectTime()."
```

---

### Task 2: `engine/appc/warp_state.py` — the ship-level warp-state facade

One module owns every warp-state read/write, so the `_Stub` guards live in exactly one place instead of being re-derived at each call site.

**Files:**
- Create: `engine/appc/warp_state.py`
- Test: `tests/unit/test_warp_state.py` (create)

**Interfaces:**
- Consumes: `WarpEngineSubsystem.IsWarping()`, `.tick_transition(dt)`, `.SetWarpState(state)` (Task 1)
- Produces:
  - `get_state(ship) -> int` — `WES_NOT_WARPING` when the ship has no warp subsystem
  - `set_state(ship, state) -> None` — no-op when the ship has no warp subsystem
  - `is_ship_warping(obj) -> bool` — **`isinstance(ShipClass)`-guarded**; False for anything else
  - `tick_warp_states(dt: float) -> None` — advances every ship's pending dewarp
  - `begin_flythrough(ship) -> None` / `end_flythrough() -> None` / `flythrough_ship()`
  - `sync_flythrough(warp_active: bool) -> None` — forces the flythrough ship back to `WES_NOT_WARPING` once the warp animator is done
  - `reset() -> None` — drops the flythrough registration (mission swap)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_warp_state.py`:

```python
"""Ship-level warp-state facade. The isinstance guard is load-bearing: a Planet
has no GetWarpEngineSubsystem, so TGObject.__getattr__ hands back a TRUTHY
_Stub whose GetWarpState() != WES_NOT_WARPING is True — a duck-typed predicate
would silently mark every planet in the game as 'warping'."""
import App
import pytest
from engine.appc import warp_state
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def _ship_with_warp(name="s"):
    s = ShipClass()
    s.SetName(name)
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    return s


def test_get_state_of_ship_without_warp_subsystem_is_not_warping():
    s = ShipClass()                       # no warp subsystem at all
    assert s.GetWarpEngineSubsystem() is None
    assert warp_state.get_state(s) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.is_ship_warping(s) is False


def test_set_state_on_ship_without_warp_subsystem_is_a_noop():
    s = ShipClass()
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)   # must not raise
    assert warp_state.is_ship_warping(s) is False


def test_is_ship_warping_tracks_the_subsystem():
    s = _ship_with_warp()
    assert warp_state.is_ship_warping(s) is False
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)
    assert warp_state.is_ship_warping(s) is True
    warp_state.set_state(s, WarpEngineSubsystem.WES_NOT_WARPING)
    assert warp_state.is_ship_warping(s) is False


def test_planet_is_never_warping():
    # THE STUB TRAP. Planet.GetWarpEngineSubsystem() is a truthy _Stub; a
    # duck-typed predicate would report the planet as warping and make every
    # planet, moon and sun in the game non-collidable.
    p = Planet_Create(170.0, "")
    assert warp_state.is_ship_warping(p) is False


def test_tick_warp_states_completes_a_dewarp_across_the_sets():
    from engine.appc.sets import SetClass_Create
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "S")
    s = _ship_with_warp("npc")
    pSet.AddObjectToSet(s, "npc")
    s.GetWarpEngineSubsystem().SetWarpEffectTime(1.0)
    s.GetWarpEngineSubsystem().TransitionToState(
        WarpEngineSubsystem.WES_DEWARP_INITIATED)

    warp_state.tick_warp_states(0.5)
    assert warp_state.is_ship_warping(s) is True

    warp_state.tick_warp_states(0.6)
    assert warp_state.is_ship_warping(s) is False


def test_sync_flythrough_clears_the_state_when_the_warp_animator_stops():
    s = _ship_with_warp()
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)

    warp_state.sync_flythrough(True)        # animator still running -> held
    assert warp_state.is_ship_warping(s) is True

    warp_state.sync_flythrough(False)       # animator done -> cleared
    assert warp_state.is_ship_warping(s) is False
    assert warp_state.flythrough_ship() is None


def test_sync_flythrough_without_a_registered_ship_is_a_noop():
    warp_state.sync_flythrough(False)       # must not raise
    assert warp_state.flythrough_ship() is None


def test_reset_drops_the_flythrough_registration():
    s = _ship_with_warp()
    warp_state.begin_flythrough(s)
    warp_state.reset()
    assert warp_state.flythrough_ship() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_warp_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.warp_state'`.

- [ ] **Step 3: Implement**

Create `engine/appc/warp_state.py`:

```python
"""Ship-level warp-state facade over WarpEngineSubsystem's WES_* machine.

BC's canonical "is this ship warping?" test is
`GetWarpEngineSubsystem().GetWarpState() != WES_NOT_WARPING` — the same test
its own scripts make (WarpSequence.py:638, HelmMenuHandlers.py:2465,
ConditionInRange.py:209). Every engine read/write of that state goes through
this module so the stub guards live in one place.

THE GUARD THAT MATTERS: is_ship_warping() is isinstance(ShipClass)-checked.
A Planet has no GetWarpEngineSubsystem, so TGObject.__getattr__ returns a
truthy _Stub, calling it returns a _Stub, and `_Stub != WES_NOT_WARPING` is
True (App.py:1955) — duck-typing here would mark every planet, moon and sun in
the game as warping, and (via collisions._collisions_enabled) make them all
non-collidable.

Spec: docs/superpowers/specs/2026-07-13-warp-collision-suppression-design.md
"""

from engine.appc.subsystems import WarpEngineSubsystem

# The ship the timed flythrough warp is currently flying (engine/appc/warp.py),
# or None. Only used to guarantee the flythrough's warp state cannot leak: the
# host loop syncs it to WES_NOT_WARPING once the warp animator goes inactive.
_flythrough_ship = None


def _warp_subsystem(ship):
    """The ship's WarpEngineSubsystem, or None. Ships can legitimately be built
    without one, and GetWarpEngineSubsystem() then returns a real None."""
    sub = ship.GetWarpEngineSubsystem()
    return sub if isinstance(sub, WarpEngineSubsystem) else None


def get_state(ship) -> int:
    """The ship's warp state; WES_NOT_WARPING when it has no warp subsystem."""
    sub = _warp_subsystem(ship)
    if sub is None:
        return WarpEngineSubsystem.WES_NOT_WARPING
    return sub.GetWarpState()


def set_state(ship, state) -> None:
    """Set the ship's warp state. No-op when it has no warp subsystem."""
    sub = _warp_subsystem(ship)
    if sub is not None:
        sub.SetWarpState(state)


def is_ship_warping(obj) -> bool:
    """True only for a ShipClass whose warp state is not WES_NOT_WARPING.

    isinstance-guarded on purpose — see the module docstring. Never rewrite
    this as a hasattr/getattr probe."""
    from engine.appc.ships import ShipClass
    if not isinstance(obj, ShipClass):
        return False
    sub = _warp_subsystem(obj)
    return False if sub is None else sub.IsWarping()


def tick_warp_states(dt: float) -> None:
    """Advance every ship's pending dewarp transition (see
    WarpEngineSubsystem.TransitionToState). Call once per frame BEFORE
    collisions.tick_collisions, so a dewarp that completes this frame is
    collidable this frame rather than next."""
    from engine.appc.ship_iter import iter_ships
    for ship in iter_ships():
        sub = _warp_subsystem(ship)
        if sub is not None:
            sub.tick_transition(dt)


def begin_flythrough(ship) -> None:
    """Register the ship the timed flythrough warp is flying."""
    global _flythrough_ship
    _flythrough_ship = ship


def flythrough_ship():
    return _flythrough_ship


def end_flythrough() -> None:
    """Clear the flythrough ship's warp state and drop the registration."""
    global _flythrough_ship
    ship = _flythrough_ship
    _flythrough_ship = None
    if ship is not None:
        set_state(ship, WarpEngineSubsystem.WES_NOT_WARPING)


def sync_flythrough(warp_active: bool) -> None:
    """Leak guard: once the warp animator is no longer active, the flythrough
    ship must not still read as warping — otherwise an aborted warp would leave
    it non-collidable forever."""
    if not warp_active and _flythrough_ship is not None:
        end_flythrough()


def reset() -> None:
    """Drop the flythrough registration without touching any ship (the ship is
    being destroyed — mission swap)."""
    global _flythrough_ship
    _flythrough_ship = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_state.py -v`
Expected: 8 passed.

- [ ] **Step 5: Register the module-global for test isolation**

`_flythrough_ship` is a module global and will leak between tests. Open `tests/conftest.py`, find the autouse `_reset_leakable_engine_globals` fixture, and add a `warp_state.reset()` call alongside the other engine-global resets, following the existing style in that fixture.

- [ ] **Step 6: Run the full unit suite to confirm no leakage**

Run: `uv run pytest tests/unit -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/warp_state.py tests/unit/test_warp_state.py tests/conftest.py
git commit -m "feat(warp): ship-level warp-state facade with the isinstance stub guard

is_ship_warping() is isinstance(ShipClass)-checked: a Planet's missing
GetWarpEngineSubsystem returns a truthy _Stub whose GetWarpState() compares
unequal to WES_NOT_WARPING, so a duck-typed predicate would report every
planet in the game as warping."
```

---

### Task 3: The flythrough warp drives the FSM

**Files:**
- Modify: `engine/appc/warp.py` — `_WarpVfxBeginAction._do_play` (193-218), `_WarpDepartAction._do_play` (374-410), `_ArriveFinalizeAction._do_play` (424-454), `_WarpVfxEndAction` (221-232), `WarpSequence_Create` (470-544)
- Test: `tests/unit/test_warp_state_sequence.py` (create)

**Interfaces:**
- Consumes: `warp_state.begin_flythrough/set_state/end_flythrough` (Task 2), `WarpEngineSubsystem.WES_*` (Task 1)
- Produces: the flythrough drives `WES_WARP_INITIATED` (align) → `WES_WARPING` (burst) → `WES_DEWARP_ENDING` (arrival) → `WES_NOT_WARPING` (end)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_warp_state_sequence.py`:

```python
"""The flythrough warp drives the ship's WarpEngineSubsystem FSM, so BC's own
GetWarpState() consumers (WarpSequence.py:638, HelmMenuHandlers.py:2465,
ConditionInRange.py:209) see a warping ship as warping."""
import sys
import types

import App
import pytest
from engine.appc import warp, warp_state
from engine.appc.sets import SetClass_Create
from engine.appc.subsystems import WarpEngineSubsystem

WES = WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def _player_in_set():
    src = SetClass_Create()
    App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create()
    player.SetName("player")
    player.SetWarpEngineSubsystem(WES("Warp Engines"))
    src.AddObjectToSet(player, "player")
    mod = types.ModuleType("FakeSys.D")
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), "D")
    sys.modules["FakeSys.D"] = mod
    return player


def test_flythrough_begin_marks_the_ship_warp_initiated():
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None, stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))
    player = _player_in_set()
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    # Only the align-start action has fired (the rest are time-delayed).
    assert warp_state.get_state(player) == WES.WES_WARP_INITIATED
    assert warp_state.is_ship_warping(player) is True
    assert warp_state.flythrough_ship() is player


def test_depart_action_marks_the_ship_warping():
    player = _player_in_set()
    warp._WarpDepartAction(None, player)._do_play()
    assert warp_state.get_state(player) == WES.WES_WARPING


def test_arrive_action_marks_the_ship_dewarp_ending():
    # Arrival begins the exit-decel glide: still warping (still non-collidable)
    # until the animator finishes and _WarpVfxEndAction clears it.
    player = _player_in_set()
    warp._ArriveFinalizeAction(None, player)._do_play()
    assert warp_state.get_state(player) == WES.WES_DEWARP_ENDING
    assert warp_state.is_ship_warping(player) is True


def test_vfx_end_action_clears_the_warp_state():
    player = _player_in_set()
    warp_state.begin_flythrough(player)
    warp_state.set_state(player, WES.WES_DEWARP_ENDING)
    warp._WarpVfxEndAction()._do_play()
    assert warp_state.get_state(player) == WES.WES_NOT_WARPING
    assert warp_state.flythrough_ship() is None


def test_hard_cut_path_never_marks_the_ship_warping():
    # Flythrough OFF: an instant set swap, no warp-speed flight, so the ship
    # must never read as warping.
    warp.configure_warp_vfx(enabled=lambda: False)
    player = _player_in_set()
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    assert warp_state.get_state(player) == WES.WES_NOT_WARPING
    assert warp_state.flythrough_ship() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_warp_state_sequence.py -v`
Expected: FAIL — `test_flythrough_begin_marks_the_ship_warp_initiated` asserts `WES_WARP_INITIATED` but gets `WES_NOT_WARPING` (0), because nothing drives the FSM yet.

- [ ] **Step 3: Implement**

In `engine/appc/warp.py`:

**(a)** In `_WarpVfxBeginAction._do_play` (line 193), immediately after the `MissionLib.RemoveControl()` try/except block and before the `if _vfx_start is not None:` block, add:

```python
        # Enter BC's warp FSM. This is the state BC's own scripts read
        # (WarpSequence.py:638, HelmMenuHandlers.py:2465), and it is what makes
        # the ship non-collidable for the flight (collisions._collisions_enabled).
        try:
            from engine.appc import warp_state
            from engine.appc.subsystems import WarpEngineSubsystem
            warp_state.begin_flythrough(self._ship)
            warp_state.set_state(self._ship, WarpEngineSubsystem.WES_WARP_INITIATED)
        except Exception:
            pass
```

**(b)** In `_WarpDepartAction._do_play` (line 374), immediately after `ship = self._ship` (line 378), add:

```python
        # Burst: the ship is now at warp.
        try:
            from engine.appc import warp_state
            from engine.appc.subsystems import WarpEngineSubsystem
            warp_state.set_state(ship, WarpEngineSubsystem.WES_WARPING)
        except Exception:
            pass
```

**(c)** In `_ArriveFinalizeAction._do_play` (line 424), immediately after `src = self._source` (line 426), add:

```python
        # Arrival: the exit-decel glide starts now, so the ship is dewarping —
        # still non-collidable until the animator finishes and _WarpVfxEndAction
        # clears the state. On the hard-cut path there is no flythrough ship
        # registered, so this correctly stays a no-op.
        try:
            from engine.appc import warp_state
            from engine.appc.subsystems import WarpEngineSubsystem
            if self._ship is not None and warp_state.flythrough_ship() is self._ship:
                warp_state.set_state(self._ship, WarpEngineSubsystem.WES_DEWARP_ENDING)
        except Exception:
            pass
```

**(d)** Replace `_WarpVfxEndAction._do_play` (lines 227-232) with:

```python
    def _do_play(self):
        if _vfx_stop is not None:
            try:
                _vfx_stop()
            except Exception:
                pass
        # Leave the warp FSM: the decel tail is done, the ship is back at
        # impulse, and it becomes collidable again.
        try:
            from engine.appc import warp_state
            warp_state.end_flythrough()
        except Exception:
            pass
```

Note: `_ArriveFinalizeAction` is used on BOTH paths, which is why (c) is gated on `flythrough_ship() is self._ship` — the hard-cut path never registers one, so it stays at `WES_NOT_WARPING`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_state_sequence.py tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_spine.py -v`
Expected: all pass (the two existing warp files must stay green).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp.py tests/unit/test_warp_state_sequence.py
git commit -m "feat(warp): flythrough drives the WarpEngineSubsystem FSM

WES_WARP_INITIATED at align, WES_WARPING at burst, WES_DEWARP_ENDING on
arrival, WES_NOT_WARPING when the decel tail ends. Our engine never called
SetWarpState, so BC's four GetWarpState consumers were dead."
```

---

### Task 4: Collision suppression

**Files:**
- Modify: `engine/appc/collisions.py:53-59` (`_collisions_enabled`)
- Test: `tests/unit/test_collisions.py` (append)

**Interfaces:**
- Consumes: `warp_state.is_ship_warping(obj)` (Task 2)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collisions.py`:

```python
def _warping_ship(x, mass, vx, radius=1.0, state=None):
    from engine.appc.subsystems import WarpEngineSubsystem
    s = _ship(x, mass, vx, radius)
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    if state is not None:
        s.GetWarpEngineSubsystem().SetWarpState(state)
    return s


def test_warping_ship_is_not_collidable():
    from engine.appc.collisions import _collisions_enabled
    from engine.appc.subsystems import WarpEngineSubsystem
    s = _warping_ship(0.0, 1000.0, 0.0, state=WarpEngineSubsystem.WES_WARPING)
    assert _collisions_enabled(s) is False


def test_ship_out_of_warp_is_collidable_again():
    from engine.appc.collisions import _collisions_enabled
    from engine.appc.subsystems import WarpEngineSubsystem
    s = _warping_ship(0.0, 1000.0, 0.0, state=WarpEngineSubsystem.WES_WARPING)
    s.GetWarpEngineSubsystem().SetWarpState(WarpEngineSubsystem.WES_NOT_WARPING)
    assert _collisions_enabled(s) is True


def test_warp_suppression_does_not_stomp_the_sdk_collision_flag():
    # CanCollide() is the ONLY collision getter any SDK script can read. Warp
    # suppression is an engine overlay and must leave it alone.
    from engine.appc.subsystems import WarpEngineSubsystem
    s = _warping_ship(0.0, 1000.0, 0.0, state=WarpEngineSubsystem.WES_WARPING)
    assert s.CanCollide() == 1


def test_sdk_collisions_off_composes_with_warp_rather_than_being_overridden():
    from engine.appc.collisions import _collisions_enabled
    from engine.appc.subsystems import WarpEngineSubsystem
    s = _warping_ship(0.0, 1000.0, 0.0, state=WarpEngineSubsystem.WES_WARPING)
    s.SetCollisionsOn(0)
    s.GetWarpEngineSubsystem().SetWarpState(WarpEngineSubsystem.WES_NOT_WARPING)
    assert _collisions_enabled(s) is False   # the mission's flag still holds


def test_planet_stays_collidable_the_stub_trap():
    # A Planet has no GetWarpEngineSubsystem: TGObject.__getattr__ returns a
    # TRUTHY _Stub, and _Stub != WES_NOT_WARPING is True. A duck-typed warp
    # predicate would make every planet in the game non-collidable.
    from engine.appc.collisions import _collisions_enabled
    p = Planet_Create(170.0, "")
    assert _collisions_enabled(p) is True


def test_warping_ship_is_excluded_from_pair_resolution():
    # Head-on overlap that WOULD collide: a warping ship generates no contact,
    # while the same pair out of warp does.
    from engine.appc.collisions import _collisions_enabled, resolve_collisions
    from engine.appc.subsystems import WarpEngineSubsystem
    a = _warping_ship(0.0, 1000.0, 10.0, radius=5.0,
                      state=WarpEngineSubsystem.WES_WARPING)
    b = _ship(4.0, 1000.0, -10.0, radius=5.0)
    live = [o for o in (a, b) if _collisions_enabled(o)]
    assert live == [b]
    assert resolve_collisions(live) == []

    a.GetWarpEngineSubsystem().SetWarpState(WarpEngineSubsystem.WES_NOT_WARPING)
    assert resolve_collisions([a, b]) != []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_collisions.py -v -k "warp or planet_stays"`
Expected: FAIL — `test_warping_ship_is_not_collidable` asserts `False` but `_collisions_enabled` returns `True` (it only reads `_collisions_on`).

- [ ] **Step 3: Implement**

In `engine/appc/collisions.py`, replace `_collisions_enabled` (lines 53-59) with:

```python
def _collisions_enabled(obj):
    """Whether this object takes part in collision resolution.

    Two independent gates, which COMPOSE (neither overrides the other):

    1. The SDK's per-object DamageableObject.SetCollisionsOn flag; default True.
       Same obj.__dict__ pattern as _overlay_vec: the flag is only ever set as
       an instance attribute, and getattr would hit TGObject.__getattr__'s
       truthy _Stub on objects that never had it set (e.g. Planet).

    2. Engine warp suppression: a ship in warp is non-collidable. Our flythrough
       flies the ship through populated sets at 100x max speed, where a contact
       is instantly lethal (_ke_damage is quadratic in closing speed) and the
       sphere broadphase can tunnel clean through a hull. BC never had this
       problem — it teleports the warping ship into an isolated warp set — so
       suppression restores BC's outcome, not a new behaviour.
       warp_state.is_ship_warping is isinstance(ShipClass)-guarded: do not
       inline it as a getattr probe, or every planet becomes non-collidable.
    """
    if not obj.__dict__.get("_collisions_on", True):
        return False
    from engine.appc.warp_state import is_ship_warping
    return not is_ship_warping(obj)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_collisions.py -v`
Expected: all pass, including the 6 new tests.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collisions.py
git commit -m "feat(collisions): a ship in warp does not collide

Derived from the SDK warp FSM, so it is per-ship and script-observable. The
SDK's SetCollisionsOn flag is untouched and composes with it. Planets stay
collidable: the predicate is isinstance-guarded against the truthy _Stub."
```

---

### Task 5: Host-loop wiring + leak guards

**Files:**
- Modify: `engine/host_loop.py:6294-6297` (before `collisions.tick_collisions`), `engine/host_loop.py:3647-3655` (mission-swap teardown)
- Test: `tests/host/test_warp_state_host_wiring.py` (create)

**Interfaces:**
- Consumes: `warp_state.tick_warp_states(dt)`, `warp_state.sync_flythrough(active)`, `warp_state.reset()` (Task 2)

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_warp_state_host_wiring.py`:

```python
"""Host wiring for warp state: the per-frame sync must run BEFORE collisions
(a dewarp that completes this frame is collidable this frame), and a mission
swap must not strand a mid-warp ship as permanently non-collidable."""
import inspect

import App
import pytest
from engine.appc import warp_state
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def test_warp_state_is_ticked_before_collisions_in_the_host_loop():
    import engine.host_loop as hl
    src = inspect.getsource(hl)
    i_sync = src.index("warp_state.tick_warp_states")
    i_coll = src.index("collisions.tick_collisions")
    assert i_sync < i_coll, (
        "warp state must be advanced before collision resolution, or a ship "
        "that leaves warp this frame stays non-collidable for one extra frame")
    assert "warp_state.sync_flythrough" in src


def test_mission_swap_clears_a_mid_warp_ship():
    # The swap destroys the ship, so reset() drops the registration without
    # touching it — a later frame must not find a stale flythrough ship.
    s = ShipClass()
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)

    import engine.host_loop as hl
    assert "warp_state.reset()" in inspect.getsource(hl)

    warp_state.reset()
    assert warp_state.flythrough_ship() is None
    # A fresh ship in the new mission is collidable.
    from engine.appc.collisions import _collisions_enabled
    fresh = ShipClass()
    fresh.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    assert _collisions_enabled(fresh) is True


def test_sync_flythrough_releases_the_ship_when_the_animator_stops():
    from engine.appc.collisions import _collisions_enabled
    s = ShipClass()
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_DEWARP_ENDING)
    assert _collisions_enabled(s) is False

    warp_state.sync_flythrough(False)       # what the host loop calls each frame
    assert _collisions_enabled(s) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_warp_state_host_wiring.py -v`
Expected: FAIL — `ValueError: substring not found` on `src.index("warp_state.tick_warp_states")`.

- [ ] **Step 3: Implement**

**(a)** In `engine/host_loop.py`, immediately BEFORE the `collisions.tick_collisions(` call at line 6294 (and inside the same block, at the same indentation as that call), insert:

```python
                # Advance BC's warp FSM before collisions: a ship in warp is
                # non-collidable (collisions._collisions_enabled), so a dewarp
                # that completes this frame must be collidable THIS frame, not
                # next. sync_flythrough is the leak guard — once the warp
                # animator is inactive the flythrough ship cannot still read as
                # warping, however the sequence ended.
                from engine.appc import warp_state as _warp_state
                from engine import warp_vfx as _wv_state
                _warp_state.tick_warp_states(_player_dt)
                _warp_state.sync_flythrough(_wv_state.get().is_active())
```

**(b)** In the mission-swap teardown, after the `_wv.get().stop()` try/except block (lines 3647-3651) and before the `_warp_clear_turn()` block, insert:

```python
        try:
            from engine.appc import warp_state as _warp_state
            _warp_state.reset()
        except Exception:
            pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/host/test_warp_state_host_wiring.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the FULL gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. The only permitted failures are the 7 headless-GL `FrameTest`s already listed in `tests/known_failures.txt`. **Any other failure is a regression from this branch — fix it, do not baseline it.**

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_warp_state_host_wiring.py
git commit -m "feat(warp): host-loop warp-state tick + leak guards

tick_warp_states runs before tick_collisions so a ship leaving warp is
collidable the same frame; sync_flythrough and the mission-swap reset ensure
no abort path can strand a ship non-collidable."
```

---

### Task 6: Mark the resolved stubs and verify in the running game

**Files:**
- Modify: `docs/stub_heatmap.md` (the `markedResolvedOn` cells for the `WarpEngineSubsystem` rows)

- [ ] **Step 1: Mark `TransitionToState` resolved**

In `docs/stub_heatmap.md`, in the roadmap table, set `markedResolvedOn` to `2026-07-13` on the row `| 136 | WarpEngineSubsystem | TransitionToState |`. Leave `SetPlacement`, `GetWarpExitLocation` and `GetWarpExitRotation` open — this plan does not implement them.

- [ ] **Step 2: Verify in the running game**

Build and run:

```bash
cmake --build build -j && ./build/dauntless --developer
```

In-game: load a mission with traffic in the source system, put a ship or station directly ahead of the player, and engage warp from the Helm "Warp" button. Confirm:
1. the ship flies *through* anything in its path during the align-out ramp instead of exploding on it;
2. on arrival in the destination system the high-speed glide-in does not collide;
3. once the ship has coasted to a stop, ramming a nearby ship at impulse **still collides normally** (suppression released).

Do not claim this task complete on tests alone — the failure this fixes is a live one, and (3) is the check that the release actually fires.

- [ ] **Step 3: Commit**

```bash
git add docs/stub_heatmap.md
git commit -m "docs(stubs): mark WarpEngineSubsystem.TransitionToState resolved"
```

---

## Deferred (filed in the spec, NOT in this plan)

- `InSystemWarp` (AI hyper-cruise + Ctrl+I boost) also runs at 100× max speed and stays collidable.
- `ship_motion.py:168,185` — `getattr(ship, "_drift_velocity", None)` returns a truthy `_Stub`, corrupting `_current_speed` for one frame on every NPC ship (heatmap ranks 51-52).
- `collision_avoidance.py:125` — calls the unimplemented `Planet.GetVelocity` (heatmap ranks 7-10).
