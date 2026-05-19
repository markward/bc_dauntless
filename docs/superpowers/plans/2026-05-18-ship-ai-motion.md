# Ship AI Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI-driven ships actually move under their script-recorded setpoints. After this slice, a `PlainAI("GoForward")` ship drifts forward on screen, and a `PlainAI("TurnToOrientation")` ship rotates to face its target.

**Architecture:** A new per-tick integrator (`engine/appc/ship_motion.py`) reads each ship's `_speed_setpoint` / `_target_angular_velocity_setpoint`, ramps `_current_speed` / `_current_angular_velocity` toward those targets at the ship's `MaxAccel` / `MaxAngularAccel` (with `_PlayerControl.FALLBACK_MAX_ACCEL = 1e9` fallback), and writes the result back to the ship's transform via `SetTranslateXYZ` / `SetMatrixRotation`. The integrator runs between `tick_all_ai` and the per-ship subsystem updates in `GameLoop.tick()`. Four new methods land on `ShipClass` for SDK script needs: `SetImpulse` (alias for `SetSpeed`), `GetPredictedPosition`, `GetRelativePositionInfo`, `TurnDirectionsToDirections`.

**Tech Stack:** Python 3, pytest, existing `engine/appc/` Phase-1 shims, `engine/appc/math.TGPoint3`/`TGMatrix3` (with `MakeRotation` / `MultMatrix` / `GetRow`), real SDK `AI/PlainAI/GoForward.py` + `TurnToOrientation.py` loaded via `_SDKFinder` in [tests/conftest.py](../../../tests/conftest.py). Builds on the just-merged Steps 1-3 plan ([2026-05-18-ship-ai-runtime-step1-3.md](2026-05-18-ship-ai-runtime-step1-3.md), commit `5071ce6`).

**Spec:** [docs/superpowers/specs/2026-05-18-ship-ai-motion-design.md](../specs/2026-05-18-ship-ai-motion-design.md) — read this first; the file map, non-goals, and risks lists are authoritative.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/appc/ship_motion.py` (new) | `tick_all_ship_motion(dt)` + per-ship `_step_ship_motion` integrator. Reads setpoints, ramps current state, writes transform. ~130 LOC. |
| [`engine/appc/ships.py`](../../../engine/appc/ships.py) (modify) | Add `_current_speed`/`_current_angular_velocity` fields. Add `SetImpulse`, `GetPredictedPosition`, `GetRelativePositionInfo`, `TurnDirectionsToDirections` methods. Defensively copy direction vec in `SetSpeed`. |
| [`engine/core/loop.py`](../../../engine/core/loop.py) (modify) | One added call in `tick()`: `tick_all_ship_motion(TICK_DELTA)` between `tick_all_ai` and the shield-subsystem loop. |
| `tests/unit/test_ship_motion.py` (new) | ~13 tests for the integrator (zero-setpoint stay, linear ramp, frame conversion, angular ramp, soft stop, IES fallback, forward follows rotation, math helpers, SetImpulse aliasing, SetSpeed defensive copy). |
| `tests/unit/test_turn_directions.py` (new) | ~6 tests for the `TurnDirectionsToDirections` solver. |
| `tests/unit/test_loop.py` (modify) | One added test pinning order-of-ops: `tick_all_ai` runs before `tick_all_ship_motion`. |
| `tests/integration/test_ai_goforward_smoke.py` (new) | 3 end-to-end tests: GoForward drifts +Y; X/Z stay zero; AI stays `US_ACTIVE`. |
| `tests/integration/test_ai_turn_to_orientation_smoke.py` (new) | 3 end-to-end tests: ship rotates to face target; `bDoneOnLineup=1` returns `US_DONE`; target on -X rotates the other way (no shortest-path bug). |
| [`tests/integration/test_ai_stay_smoke.py`](../../../tests/integration/test_ai_stay_smoke.py) (modify) | One appended assertion: after the integrator runs, `ship.GetTranslate()` matches initial position exactly. |
| `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/AIMotion.py` (new) | Mission fixture for visible verification. Discovered automatically by `engine/missions/discovery.py` (any leaf dir under `Custom/Tutorial/Episode/` containing `def Initialize(` becomes a picker entry). |
| `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/__init__.py` (new) | Empty marker (mirrors `M1Basic/__init__.py`). |
| [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md) (modify) | Strike completed items (Step 4 partial: linear+angular setpoints, `TurnDirectionsToDirections`, `GetPredictedPosition`, `GetRelativePositionInfo`; Step 5.2 GoForward; Step 5.3 TurnToOrientation). |

---

## Task 1: Integrator scaffold + Stay regression

Lay down the no-op integrator skeleton and the per-ship `_current_*` fields. Verify it doesn't break the existing `Stay` smoke test (which sets zero setpoints — the integrator must be a no-op).

**Files:**
- Create: `engine/appc/ship_motion.py`
- Modify: [`engine/appc/ships.py`](../../../engine/appc/ships.py) — add `_current_speed` and `_current_angular_velocity` fields in `__init__`
- Modify: [`engine/core/loop.py`](../../../engine/core/loop.py) — call `tick_all_ship_motion` from `tick()`
- Modify: [`tests/integration/test_ai_stay_smoke.py`](../../../tests/integration/test_ai_stay_smoke.py) — assert position unchanged

- [ ] **Step 1.1: Write the failing position-unchanged assertion in the Stay smoke test**

In [`tests/integration/test_ai_stay_smoke.py`](../../../tests/integration/test_ai_stay_smoke.py), append:

```python
def test_stay_ship_does_not_move():
    """After the integrator runs, a Stay ship's transform is byte-identical
    to its starting transform — Stay's zero setpoints must survive the
    integrator round-trip with no drift."""
    ship, pai = _setup_ship_with_stay()
    ship.SetTranslateXYZ(100.0, 200.0, 300.0)
    start_pos = ship.GetTranslate()
    start_rot = ship.GetWorldRotation()

    loop = GameLoop()
    loop.advance(TICK_RATE * 11)  # 11 seconds — multiple Update cycles

    end_pos = ship.GetTranslate()
    assert (end_pos.x, end_pos.y, end_pos.z) == (100.0, 200.0, 300.0)
    end_rot = ship.GetWorldRotation()
    # Identity rotation is preserved bit-exact since the integrator must
    # be a no-op when setpoints are zero.
    for i in range(3):
        for j in range(3):
            assert end_rot.GetEntry(i, j) == start_rot.GetEntry(i, j), (
                f"rotation drifted at ({i},{j}): "
                f"{start_rot.GetEntry(i, j)} -> {end_rot.GetEntry(i, j)}"
            )
```

- [ ] **Step 1.2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_ai_stay_smoke.py::test_stay_ship_does_not_move -v`

Expected: FAIL with `AttributeError: module 'engine.appc.ship_motion' has no attribute 'tick_all_ship_motion'` (or `ImportError` — whichever surfaces first when the GameLoop change in Step 1.5 hits).

(If you run this before Step 1.5, the test passes trivially because the GameLoop hasn't been changed yet. That's fine — the real failing-test signal lands in Step 1.6.)

- [ ] **Step 1.3: Add `_current_*` fields to `ShipClass.__init__`**

In [`engine/appc/ships.py`](../../../engine/appc/ships.py), inside `ShipClass.__init__` (after `self._alert_level = ShipClass.GREEN_ALERT` on line 60), add:

```python
        # Integrator-owned motion state — AI scripts write setpoints
        # (_speed_setpoint, _target_angular_velocity_setpoint) and the
        # ship_motion.tick_all_ship_motion integrator ramps these
        # _current_* values toward those targets each tick, then writes
        # the result back to the ship's transform. Zero initial state
        # means a freshly-spawned ship is at rest until an AI tells it
        # otherwise — matches Stay semantics exactly.
        from engine.appc.math import TGPoint3
        self._current_speed: float = 0.0
        self._current_angular_velocity = TGPoint3(0.0, 0.0, 0.0)
```

- [ ] **Step 1.4: Create the integrator scaffold**

Create `engine/appc/ship_motion.py`:

```python
"""Per-tick kinematic integrator for AI-controlled ships.

Reads each ship's _speed_setpoint and _target_angular_velocity_setpoint
(written by AI scripts via ShipClass.SetSpeed / SetImpulse /
SetTargetAngularVelocityDirect), ramps _current_speed and
_current_angular_velocity toward those targets at the ship's
MaxAccel / MaxAngularAccel, and integrates the result into the ship's
world transform.

Mirrors _PlayerControl.apply() in engine/host_loop.py (lines 594-769) —
same row-vector matrix convention, same Y-forward Z-up frame, same
linear ramp helper, same IES-fallback (FALLBACK_MAX_ACCEL = 1e9) for
ships without a populated impulse engine subsystem.

Ships whose setpoints have never been written (both _speed_setpoint
and _target_angular_velocity_setpoint are None) are skipped entirely —
the player ship drives its transform via _PlayerControl directly, not
via setpoints, so this integrator must leave it alone.
"""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass

# Match _PlayerControl.FALLBACK_MAX_ACCEL in engine/host_loop.py:613.
# Used when a ship has no ImpulseEngineSubsystem with non-zero MaxSpeed
# (i.e. test ships built with ShipClass() directly, before SetupProperties).
FALLBACK_MAX_ACCEL = 1.0e9

# Body-frame axes — matches _PlayerControl convention.
_X_AXIS = TGPoint3(1.0, 0.0, 0.0)
_Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
_Z_AXIS = TGPoint3(0.0, 0.0, 1.0)


def tick_all_ship_motion(dt: float) -> None:
    """Iterate every live ship and advance its motion by `dt` seconds."""
    from engine.appc.ship_iter import iter_ships
    for ship in iter_ships():
        _step_ship_motion(ship, dt)


def _ramp_toward(current: float, target: float, step: float) -> float:
    """Linear ramp: move `current` toward `target` by at most `step`."""
    delta = target - current
    if abs(delta) <= step:
        return target
    return current + (step if delta > 0 else -step)


def _max_accel(ship) -> float:
    ies = ship.GetImpulseEngineSubsystem()
    if ies is not None and ies.GetMaxSpeed() > 0.0:
        a = ies.GetMaxAccel()
        return a if a > 0.0 else FALLBACK_MAX_ACCEL
    return FALLBACK_MAX_ACCEL


def _max_angular_accel(ship) -> float:
    ies = ship.GetImpulseEngineSubsystem()
    if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
        a = ies.GetMaxAngularAccel()
        return a if a > 0.0 else FALLBACK_MAX_ACCEL
    return FALLBACK_MAX_ACCEL


def _step_ship_motion(ship, dt: float) -> None:
    """Advance one ship's transform by one tick.

    Skips entirely if no setpoint has ever been written — preserves the
    player ship (which drives its transform via _PlayerControl, not
    setpoints) and freshly-spawned non-AI props.
    """
    sp = getattr(ship, "_speed_setpoint", None)
    av = getattr(ship, "_target_angular_velocity_setpoint", None)
    if sp is None and av is None:
        return
    # Placeholder for Tasks 2 + 3: zero-setpoint case must be a no-op.
    # If both setpoints have been written but evaluate to zero, the
    # current-state ramp toward zero is also zero, so nothing happens.
    # Tasks 2/3 will replace this body with the real linear + angular
    # integration. For now, return so the Stay-position-unchanged test
    # passes.
    return
```

- [ ] **Step 1.5: Wire `tick_all_ship_motion` into `GameLoop.tick()`**

In [`engine/core/loop.py`](../../../engine/core/loop.py), replace `tick()`:

```python
    def tick(self) -> None:
        App.g_kTimerManager.tick(TICK_DELTA)
        App.g_kRealtimeTimerManager.tick(TICK_DELTA)

        from engine.appc.time_slice import g_kAIManager
        from engine.appc.ai_driver import tick_all_ai
        from engine.appc.ship_motion import tick_all_ship_motion
        game_time = App.g_kTimerManager.get_time()
        real_time = App.g_kRealtimeTimerManager.get_time()
        g_kAIManager.tick(game_time=game_time, real_time=real_time)
        tick_all_ai(game_time=game_time)
        tick_all_ship_motion(TICK_DELTA)

        for ship in iter_ships():
            ss = ship.GetShieldSubsystem()
            if ss is not None:
                ss.Update(TICK_DELTA)
```

Lazy import (`from engine.appc.ship_motion import ...` inside `tick`) matches the existing pattern for `g_kAIManager` and `tick_all_ai` — keeps `engine/core/loop.py` import-cycle-safe.

- [ ] **Step 1.6: Run the Stay smoke test plus existing Stay tests**

Run: `uv run pytest tests/integration/test_ai_stay_smoke.py -v`

Expected: 4 PASS — the three original Stay tests plus the new position-unchanged test.

- [ ] **Step 1.7: Run the full existing suite to confirm no regressions**

Run: `uv run pytest tests/unit tests/integration -x -q`

Expected: green. The integrator is a no-op so far; nothing else can have changed.

- [ ] **Step 1.8: Commit**

```bash
git add engine/appc/ship_motion.py engine/appc/ships.py engine/core/loop.py tests/integration/test_ai_stay_smoke.py
git commit -m "feat(motion): scaffold ship_motion integrator (no-op) + Stay regression"
```

---

## Task 2: Linear motion (ramp + position integration) + `SetImpulse` alias + defensive copy

Implement the linear motion path: ramp `_current_speed` toward the target speed, project the direction vec into world space, advance position along `forward * _current_speed * dt`. Also: `SetImpulse` aliases `SetSpeed` (used by `GoForward.Update`), and `SetSpeed` defensively copies the direction vec (per Risk #2 in the spec).

**Files:**
- Modify: [`engine/appc/ships.py`](../../../engine/appc/ships.py) — `SetImpulse`, defensive copy in `SetSpeed`
- Modify: `engine/appc/ship_motion.py` — implement linear integration
- Test: `tests/unit/test_ship_motion.py` (new)

- [ ] **Step 2.1: Write the failing linear-motion tests**

Create `tests/unit/test_ship_motion.py`:

```python
"""Unit tests for engine.appc.ship_motion.tick_all_ship_motion.

Each test constructs a ship in its own SetClass so iter_ships() picks
it up, then calls tick_all_ship_motion(dt) directly. Conftest's
reset_app_state fixture clears g_kSetManager between tests.
"""
import math

import pytest

import App
from engine.appc.math import (
    TGPoint3, TGMatrix3,
    TGPoint3_GetModelForward, TGPoint3_GetModelUp,
)
from engine.appc.ship_motion import tick_all_ship_motion
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def fresh_set_manager():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _place(ship, name="t"):
    """Drop a ship into a fresh SetClass so iter_ships sees it."""
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    pSet.AddObjectToSet(ship, name + "_obj")
    App.g_kSetManager._sets[name] = pSet


def test_no_setpoints_is_noop():
    """Ship with no setpoints written must be left strictly alone."""
    ship = ShipClass()
    _place(ship)
    ship.SetTranslateXYZ(10.0, 20.0, 30.0)
    tick_all_ship_motion(1.0)
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (10.0, 20.0, 30.0)


def test_set_impulse_aliases_set_speed():
    """SetImpulse(s, dir, frame) records the same _speed_setpoint as
    SetSpeed — GoForward.Update calls SetImpulse, not SetSpeed."""
    ship = ShipClass()
    fwd = TGPoint3_GetModelForward()
    ship.SetImpulse(42.0, fwd, App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == 42.0
    assert sp[2] == App.PhysicsObjectClass.DIRECTION_MODEL_SPACE


def test_set_speed_defensively_copies_direction():
    """If a caller mutates the direction vec after SetSpeed returns,
    the recorded setpoint must NOT change. Prevents the Risk #2
    aliasing bug from the design spec."""
    ship = ShipClass()
    fwd = TGPoint3(0.0, 1.0, 0.0)
    ship.SetSpeed(10.0, fwd, App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    fwd.SetXYZ(99.0, 99.0, 99.0)
    sp = ship.GetSpeedSetpoint()
    recorded_dir = sp[1]
    assert (recorded_dir.x, recorded_dir.y, recorded_dir.z) == (0.0, 1.0, 0.0)


def test_linear_ramp_snaps_with_fallback_accel():
    """Test ship has no IES populated; FALLBACK_MAX_ACCEL=1e9 makes
    the ramp snap to target on the first tick. After one tick with
    SetImpulse(50, fwd, MODEL_SPACE), _current_speed should equal
    50.0 and the position should advance by ~50 * dt along +Y."""
    ship = ShipClass()
    _place(ship)
    ship.SetImpulse(50.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    # Zero out the angular setpoint explicitly so the integrator picks
    # up motion (avoids the no-setpoint early-out path).
    v0 = TGPoint3(0.0, 0.0, 0.0)
    ship.SetTargetAngularVelocityDirect(v0)

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    assert ship._current_speed == pytest.approx(50.0)
    p = ship.GetTranslate()
    assert p.y == pytest.approx(50.0 * dt)
    assert p.x == pytest.approx(0.0)
    assert p.z == pytest.approx(0.0)


def test_linear_speed_zero_setpoint_stops_ship():
    """A ship moving at _current_speed > 0 ramps to zero when speed
    setpoint is zero. Fallback accel snaps in one tick."""
    ship = ShipClass()
    _place(ship)
    ship._current_speed = 100.0
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_speed == pytest.approx(0.0)


def test_direction_model_space_follows_rotation():
    """When direction frame is MODEL_SPACE, the velocity vector is
    rotated by the ship's world rotation each tick. Yaw the ship 90°
    around +Z so its model-forward (+Y) now points along world +X;
    moving forward should advance along +X, not +Y."""
    ship = ShipClass()
    _place(ship)
    # Yaw 90° around Z: model +Y -> world +X.
    R = TGMatrix3()
    R.MakeZRotation(-math.pi / 2.0)  # row-vector convention: +Z rotation
                                     # tilts forward toward +X (see
                                     # host_loop.py:721 sign comment).
    ship.SetMatrixRotation(R)

    ship.SetImpulse(10.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    p = ship.GetTranslate()
    # Forward is now world +X (within the rotation convention's sign).
    assert abs(p.x) == pytest.approx(10.0 * dt, abs=1e-9)
    assert p.y == pytest.approx(0.0, abs=1e-9)
    assert p.z == pytest.approx(0.0, abs=1e-9)


def test_direction_world_space_ignores_rotation():
    """When direction frame is WORLD_SPACE, the direction vec is used
    as-is, independent of ship rotation."""
    ship = ShipClass()
    _place(ship)
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)  # arbitrary rotation
    ship.SetMatrixRotation(R)

    world_dir = TGPoint3(0.0, 1.0, 0.0)  # world +Y
    ship.SetSpeed(20.0, world_dir,
                  App.PhysicsObjectClass.DIRECTION_WORLD_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    p = ship.GetTranslate()
    assert p.y == pytest.approx(20.0 * dt)
    assert p.x == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 2.2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ship_motion.py -v`

Expected: 7 FAILs.
- `test_set_impulse_aliases_set_speed`: `AttributeError: 'ShipClass' object has no attribute 'SetImpulse'`
- `test_set_speed_defensively_copies_direction`: assertion fails — direction stored by reference.
- All four motion tests: position remains `(0, 0, 0)` because integrator body is `return`.
- `test_no_setpoints_is_noop`: PASSES already (early-out path is in place). That's fine — it's a regression test.

- [ ] **Step 2.3: Add `SetImpulse` and defensive copy in `SetSpeed`**

In [`engine/appc/ships.py`](../../../engine/appc/ships.py), replace the existing `SetSpeed` and add `SetImpulse` (currently `SetSpeed` is at line 75):

```python
    def SetSpeed(self, speed, direction, frame) -> None:
        # Defensively copy the direction vec — many SDK call sites pass
        # App.TGPoint3_GetModelForward() (a fresh constant per call,
        # safe) but others reuse a stack-local TGPoint3 and mutate it
        # after the call. Copying here makes SetSpeed's contract
        # independent of caller hygiene. Mirrors the existing copy in
        # SetTargetAngularVelocityDirect.
        from engine.appc.math import TGPoint3
        self._speed_setpoint = (
            float(speed),
            TGPoint3(direction.x, direction.y, direction.z),
            int(frame),
        )

    def SetImpulse(self, speed, direction, frame) -> None:
        """SDK alias used by AI.PlainAI.GoForward.Update (sdk/.../GoForward.py:47).

        Records into the same _speed_setpoint tuple as SetSpeed —
        downstream the integrator can't tell which entry point the AI
        used."""
        self.SetSpeed(speed, direction, frame)
```

- [ ] **Step 2.4: Implement the linear integration in `_step_ship_motion`**

Replace the placeholder body in `engine/appc/ship_motion.py`'s `_step_ship_motion`:

```python
def _step_ship_motion(ship, dt: float) -> None:
    """Advance one ship's transform by one tick.

    Skips entirely if no setpoint has ever been written — preserves the
    player ship (which drives its transform via _PlayerControl, not
    setpoints) and freshly-spawned non-AI props.
    """
    sp = getattr(ship, "_speed_setpoint", None)
    av = getattr(ship, "_target_angular_velocity_setpoint", None)
    if sp is None and av is None:
        return

    # ── Resolve target speed + world-space direction ─────────────────
    if sp is None:
        target_speed = 0.0
        world_dir = TGPoint3(0.0, 1.0, 0.0)  # arbitrary; magnitude is 0
    else:
        target_speed_signed, direction, frame = sp
        if frame == PhysicsObjectClass.DIRECTION_MODEL_SPACE:
            world_dir = TGPoint3(direction.x, direction.y, direction.z)
            world_dir.MultMatrixLeft(ship.GetWorldRotation())
        else:
            world_dir = TGPoint3(direction.x, direction.y, direction.z)
        world_dir.Unitize()
        target_speed = target_speed_signed

    # ── Ramp current speed toward target ─────────────────────────────
    step = _max_accel(ship) * dt
    ship._current_speed = _ramp_toward(ship._current_speed, target_speed, step)

    # ── Integrate position ───────────────────────────────────────────
    if ship._current_speed != 0.0:
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(
            p.x + world_dir.x * ship._current_speed * dt,
            p.y + world_dir.y * ship._current_speed * dt,
            p.z + world_dir.z * ship._current_speed * dt,
        )

    # ── Angular integration — Task 3 fills this in ───────────────────
    # (placeholder: no-op so test_no_setpoints_is_noop + the linear
    # tests still pass; angular tests land in Task 3)
```

- [ ] **Step 2.5: Run to verify the linear tests pass**

Run: `uv run pytest tests/unit/test_ship_motion.py -v`

Expected: all 7 PASS.

If `test_direction_model_space_follows_rotation` fails on the sign of `p.x` (e.g. `p.x ≈ -10*dt` instead of `+10*dt`), the rotation sign convention is the opposite of what I asserted — flip the `MakeZRotation` argument in the test to match what `_PlayerControl` actually produces. Read [host_loop.py:719-723](../../../engine/host_loop.py) for the canonical sign comment.

- [ ] **Step 2.6: Re-run the Stay smoke test**

Run: `uv run pytest tests/integration/test_ai_stay_smoke.py -v`

Expected: 4 PASS. Stay's zero setpoint means `target_speed = 0`, `_current_speed = 0`, no position advance — round-trip preserved.

- [ ] **Step 2.7: Commit**

```bash
git add engine/appc/ships.py engine/appc/ship_motion.py tests/unit/test_ship_motion.py
git commit -m "feat(motion): linear ramp + position integration + SetImpulse alias"
```

---

## Task 3: Angular motion (rotation integration)

Implement angular ramping and rotation integration. Each axis of `_current_angular_velocity` ramps independently toward the corresponding component of the target. Per-tick rotation is built as pitch/yaw/roll rotations from `_current_angular_velocity * dt`, then pre-multiplied into the existing world rotation (matches `_PlayerControl` body-frame-delta convention).

**Files:**
- Modify: `engine/appc/ship_motion.py` — replace the angular-placeholder block
- Modify: `tests/unit/test_ship_motion.py` — add angular tests

- [ ] **Step 3.1: Write the failing angular tests**

Append to `tests/unit/test_ship_motion.py`:

```python
def test_angular_ramp_snaps_with_fallback_accel():
    """Test ship has no IES populated; the angular ramp snaps to
    target in one tick under FALLBACK_MAX_ACCEL."""
    ship = ShipClass()
    _place(ship)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    target_av = TGPoint3(0.0, 0.0, 1.0)  # yaw at 1 rad/s
    ship.SetTargetAngularVelocityDirect(target_av)

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.0)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(1.0)


def test_angular_zero_setpoint_stops_rotation():
    """A ship rotating at _current_angular_velocity != 0 ramps to
    zero when the target is zero."""
    ship = ShipClass()
    _place(ship)
    ship._current_angular_velocity = TGPoint3(0.5, 0.5, 0.5)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.0)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(0.0)


def test_angular_rotation_advances_world_rotation():
    """After one tick at yaw=1 rad/s for dt=1/60, the ship's world
    rotation has advanced by ~1/60 rad around Z (model-up axis).
    Easiest check: model-forward (+Y) now has a small +X (or -X)
    component, no longer pure +Y."""
    ship = ShipClass()
    _place(ship)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 1.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    R = ship.GetWorldRotation()
    fwd_world = R.GetRow(1)  # model-Y mapped into world
    # After yaw of ~dt rad, |x| ≈ sin(dt), |y| ≈ cos(dt).
    assert abs(fwd_world.x) == pytest.approx(math.sin(dt), abs=1e-6)
    assert fwd_world.y == pytest.approx(math.cos(dt), abs=1e-6)
    assert fwd_world.z == pytest.approx(0.0, abs=1e-9)


def test_angular_per_axis_ramp_is_independent():
    """When the target has nonzero pitch but zero yaw, only pitch
    rate ramps up — yaw and roll stay at zero."""
    ship = ShipClass()
    _place(ship)
    ship._current_angular_velocity = TGPoint3(0.0, 0.0, 0.0)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.7, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.7)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(0.0)


def test_motion_integrator_runs_after_ai_setpoints():
    """Sanity: when the integrator runs, GetSpeedSetpoint must already
    reflect the AI's intent — order-of-ops is locked by the GameLoop
    test in Task 6. This duplicates that contract at the integrator
    boundary so a bug in either side fails locally."""
    ship = ShipClass()
    _place(ship)
    ship.SetImpulse(7.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_speed == pytest.approx(7.0)
```

- [ ] **Step 3.2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ship_motion.py -v -k "angular"`

Expected: 4 FAILs.
- `test_angular_ramp_snaps_with_fallback_accel`: `_current_angular_velocity.z == 0.0`, not 1.0 — the angular ramp isn't implemented.
- `test_angular_zero_setpoint_stops_rotation`: `_current_angular_velocity` unchanged at (0.5, 0.5, 0.5).
- `test_angular_rotation_advances_world_rotation`: rotation matrix unchanged from identity.
- `test_angular_per_axis_ramp_is_independent`: ramp not implemented.

- [ ] **Step 3.3: Implement the angular block in `_step_ship_motion`**

In `engine/appc/ship_motion.py`, replace the angular placeholder comment at the end of `_step_ship_motion` with:

```python
    # ── Resolve target angular velocity ──────────────────────────────
    if av is None:
        target_av_x = target_av_y = target_av_z = 0.0
    else:
        target_av_x, target_av_y, target_av_z = av.x, av.y, av.z

    # ── Ramp each axis of _current_angular_velocity toward target ────
    ang_step = _max_angular_accel(ship) * dt
    cav = ship._current_angular_velocity
    cav.x = _ramp_toward(cav.x, target_av_x, ang_step)
    cav.y = _ramp_toward(cav.y, target_av_y, ang_step)
    cav.z = _ramp_toward(cav.z, target_av_z, ang_step)

    # ── Integrate rotation ───────────────────────────────────────────
    # Same convention as _PlayerControl.apply step 4 (host_loop.py:741):
    # row-vector matrices, body-frame delta pre-multiplies. Pitch (X) →
    # yaw (Z) → roll (Y) Euler order. Body axes map: X=right, Y=forward,
    # Z=up; cav components are per-axis rates around those body axes.
    if cav.x or cav.y or cav.z:
        R = ship.GetWorldRotation()
        R_pitch = TGMatrix3(); R_pitch.MakeRotation(cav.x * dt, _X_AXIS)
        R_yaw   = TGMatrix3(); R_yaw.MakeRotation(cav.z * dt, _Z_AXIS)
        R_roll  = TGMatrix3(); R_roll.MakeRotation(cav.y * dt, _Y_AXIS)
        delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
        R = delta.MultMatrix(R)
        ship.SetMatrixRotation(R)
```

- [ ] **Step 3.4: Run to verify the angular tests pass**

Run: `uv run pytest tests/unit/test_ship_motion.py -v`

Expected: all tests PASS (12 total: 7 from Task 2 + 5 new).

If `test_angular_rotation_advances_world_rotation` fails on the sign of `fwd_world.x`, the rotation convention is flipped from my assertion — change the assertion to `fwd_world.x == pytest.approx(-math.sin(dt), abs=1e-6)`. Confirm against `_PlayerControl` (yaw uses `MakeRotation(yaw_rate * dt, Z_AXIS)`, same axis order, so the sign should match).

- [ ] **Step 3.5: Re-run Stay smoke test**

Run: `uv run pytest tests/integration/test_ai_stay_smoke.py -v`

Expected: 4 PASS. Stay still produces zero setpoints → zero ramp → no rotation delta.

- [ ] **Step 3.6: Commit**

```bash
git add engine/appc/ship_motion.py tests/unit/test_ship_motion.py
git commit -m "feat(motion): angular ramp + rotation integration"
```

---

## Task 4: Trivial math helpers — `GetPredictedPosition` + `GetRelativePositionInfo`

Pure-math methods used by `TurnToOrientation` (Task 8) and future Intercept work. No state mutation, no dependency on the integrator.

**Files:**
- Modify: [`engine/appc/ships.py`](../../../engine/appc/ships.py)
- Test: add to `tests/unit/test_ship_motion.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/unit/test_ship_motion.py`:

```python
def test_get_predicted_position_returns_p_v_t_half_a_t_squared():
    """GetPredictedPosition(p, v, a, t) = p + v*t + 0.5*a*t²"""
    ship = ShipClass()
    p = TGPoint3(10.0, 20.0, 30.0)
    v = TGPoint3(1.0, 2.0, 3.0)
    a = TGPoint3(0.4, 0.0, -0.2)
    t = 5.0
    result = ship.GetPredictedPosition(p, v, a, t)
    # p + v*t = (15, 30, 45); 0.5*a*t² = (5, 0, -2.5) → (20, 30, 42.5)
    assert result.x == pytest.approx(20.0)
    assert result.y == pytest.approx(30.0)
    assert result.z == pytest.approx(42.5)


def test_get_relative_position_info_basic():
    """Ship at origin, target at (0, 100, 0): diff=(0,100,0),
    distance=100, unit=(0,1,0), angle_off_forward=0 (aligned with +Y
    model-forward in identity rotation)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = TGPoint3(0.0, 100.0, 0.0)
    diff, dist, unit, angle = ship.GetRelativePositionInfo(target)
    assert (diff.x, diff.y, diff.z) == (0.0, 100.0, 0.0)
    assert dist == pytest.approx(100.0)
    assert (unit.x, unit.y, unit.z) == pytest.approx((0.0, 1.0, 0.0))
    assert angle == pytest.approx(0.0, abs=1e-9)


def test_get_relative_position_info_angle_off_forward():
    """Target perpendicular to model-forward → 90° angle."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = TGPoint3(100.0, 0.0, 0.0)  # world +X; identity rotation,
                                        # model-forward is world +Y
    _, _, _, angle = ship.GetRelativePositionInfo(target)
    assert angle == pytest.approx(math.pi / 2.0, abs=1e-9)


def test_get_relative_position_info_zero_distance():
    """Target at ship's location: distance == 0, unit_dir is (0,0,0),
    angle is 0 (defined by convention — avoid divide-by-zero)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(5.0, 5.0, 5.0)
    target = TGPoint3(5.0, 5.0, 5.0)
    diff, dist, unit, angle = ship.GetRelativePositionInfo(target)
    assert dist == pytest.approx(0.0)
    assert (unit.x, unit.y, unit.z) == (0.0, 0.0, 0.0)
    assert angle == pytest.approx(0.0)
```

- [ ] **Step 4.2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ship_motion.py -v -k "predicted or relative"`

Expected: 4 FAILs with `AttributeError: 'ShipClass' object has no attribute 'GetPredictedPosition'` / `GetRelativePositionInfo`.

- [ ] **Step 4.3: Implement the helpers**

In [`engine/appc/ships.py`](../../../engine/appc/ships.py), add after `GetTargetAngularVelocitySetpoint` (the existing block ends near line 87):

```python
    def GetPredictedPosition(self, p, v, a, t):
        """Kinematic forecast: p + v*t + 0.5*a*t².

        Pure math — no ship state read or written. SDK signature
        documented in sdk/.../App.py (PhysicsObjectClass).
        """
        from engine.appc.math import TGPoint3
        t2_half = 0.5 * t * t
        return TGPoint3(
            p.x + v.x * t + a.x * t2_half,
            p.y + v.y * t + a.y * t2_half,
            p.z + v.z * t + a.z * t2_half,
        )

    def GetRelativePositionInfo(self, target_vec):
        """Geometry of a world-space point relative to this ship.

        Returns (diff_vec, distance, unit_dir, angle_off_forward_rad)
        where diff_vec = target - ship_world_location,
        distance = |diff_vec|, unit_dir = diff_vec / distance
        (zero vec if distance ≈ 0), angle_off_forward is the angle
        between unit_dir and ship's world-forward (model-Y mapped
        through GetWorldRotation()).

        Used heavily by AI.PlainAI.TurnToOrientation and Intercept.
        """
        import math as _math
        from engine.appc.math import TGPoint3
        loc = self.GetWorldLocation()
        diff = TGPoint3(
            target_vec.x - loc.x,
            target_vec.y - loc.y,
            target_vec.z - loc.z,
        )
        distance = diff.Length()
        if distance < 1e-9:
            return diff, 0.0, TGPoint3(0.0, 0.0, 0.0), 0.0
        unit = TGPoint3(diff.x / distance, diff.y / distance, diff.z / distance)
        forward = self.GetWorldRotation().GetRow(1)
        # Clamp dot to [-1, 1] to guard against FP drift outside acos
        # domain.
        cos_a = unit.x * forward.x + unit.y * forward.y + unit.z * forward.z
        if cos_a > 1.0: cos_a = 1.0
        elif cos_a < -1.0: cos_a = -1.0
        angle = _math.acos(cos_a)
        return diff, distance, unit, angle
```

- [ ] **Step 4.4: Run to verify the tests pass**

Run: `uv run pytest tests/unit/test_ship_motion.py -v -k "predicted or relative"`

Expected: 4 PASS.

- [ ] **Step 4.5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_ship_motion.py
git commit -m "feat(ships): GetPredictedPosition + GetRelativePositionInfo math helpers"
```

---

## Task 5: `TurnDirectionsToDirections` solver

Builds the angular-velocity setpoint needed to rotate `primary_from` onto `primary_to` (and optionally `secondary_from` onto `secondary_to` around the primary axis). Called by `TurnToOrientation.Update` each tick.

**Files:**
- Modify: [`engine/appc/ships.py`](../../../engine/appc/ships.py)
- Test: `tests/unit/test_turn_directions.py` (new)

- [ ] **Step 5.1: Write the failing tests**

Create `tests/unit/test_turn_directions.py`:

```python
"""Unit tests for ShipClass.TurnDirectionsToDirections.

The method computes an angular velocity that rotates primary_from
toward primary_to and (optionally) secondary_from toward secondary_to
around the primary axis, then writes the result via
SetTargetAngularVelocityDirect."""
import math

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


def _make_ship():
    return ShipClass()


def test_aligned_inputs_zero_angular_velocity():
    """When primary_from already equals primary_to, the solver should
    drive angular velocity to zero."""
    ship = _make_ship()
    v = TGPoint3(0.0, 1.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(v, v, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)


def test_ninety_degree_turn_angular_velocity_around_expected_axis():
    """primary_from=+Y, primary_to=+X: rotation is 90° around -Z.
    Without IES clamp, the solver returns the gap-derived angular vel
    aligned with the cross product +Y × +X = -Z."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(1.0, 0.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    # Magnitude should be > 0 along Z (negative) and ~0 elsewhere.
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z < 0.0
    assert abs(av.z) == pytest.approx(math.pi / 2.0, rel=1e-6)


def test_one_eighty_degree_picks_perpendicular_axis():
    """primary_from=+Y, primary_to=-Y: cross product is zero, but
    the solver must still produce a non-zero angular velocity to
    flip the orientation. Falls back to an arbitrary perpendicular
    axis (cross with world up = +Z gives +X)."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, -1.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    mag = (av.x * av.x + av.y * av.y + av.z * av.z) ** 0.5
    assert mag > 1.0  # well above zero — flipping a full 180°


def test_secondary_constraint_adds_roll():
    """primary already aligned (+Y onto +Y) but secondary needs
    rotation around the primary axis: +Z secondary, +X target →
    angular velocity around primary axis +Y is non-zero."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, 1.0, 0.0)
    sf = TGPoint3(0.0, 0.0, 1.0)  # current "up" is +Z
    st = TGPoint3(1.0, 0.0, 0.0)  # desired "up" is +X (roll 90° around Y)
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    # Roll lives on the primary axis (+Y). |y| should dominate.
    assert abs(av.y) > 0.5
    assert abs(av.x) < 1e-6
    assert abs(av.z) < 1e-6


def test_clamp_to_max_angular_velocity():
    """If the ship has an ImpulseEngineSubsystem with a small
    MaxAngularVelocity, the per-axis magnitude must be clamped to
    that value."""
    ship = _make_ship()
    ies = ship.GetImpulseEngineSubsystem()
    # Populate so the clamp branch fires.
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(1.0)
    ies.SetMaxSpeed(100.0)  # non-zero so _max_accel branch is taken
    ies.SetMaxAccel(10.0)

    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(1.0, 0.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    assert abs(av.x) <= 0.5 + 1e-9
    assert abs(av.y) <= 0.5 + 1e-9
    assert abs(av.z) <= 0.5 + 1e-9


def test_secondary_both_zero_is_noop_for_secondary():
    """When secondary_from or secondary_to is the zero vector, the
    secondary constraint is skipped entirely (mirrors the SDK guard
    in TurnToOrientation.Update where vSecondaryWorld defaults to
    (0,0,0) when no secondary direction is configured)."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, 1.0, 0.0)  # already aligned
    sf = TGPoint3(0.0, 0.0, 0.0)  # zero — skip secondary
    st = TGPoint3(1.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    # No primary correction, no secondary applied — all zero.
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 5.2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_turn_directions.py -v`

Expected: 6 FAILs — `AttributeError: 'ShipClass' object has no attribute 'TurnDirectionsToDirections'`.

- [ ] **Step 5.3: Implement `TurnDirectionsToDirections`**

In [`engine/appc/ships.py`](../../../engine/appc/ships.py), add after `GetRelativePositionInfo`:

```python
    def TurnDirectionsToDirections(self, primary_from, primary_to,
                                   secondary_from, secondary_to) -> float:
        """Compute the angular velocity needed to rotate primary_from
        onto primary_to (and secondary_from onto secondary_to around
        the primary axis), call SetTargetAngularVelocityDirect, return
        an estimate of seconds until alignment completes.

        Called by AI.PlainAI.TurnToOrientation.Update (sdk/.../
        TurnToOrientation.py:88-105) each tick (0.5 s cadence).

        Algorithm:
          1. Primary alignment: axis = pf × pt; angle = acos(pf · pt).
             Degenerate case (vectors collinear, angle ≈ π): pick an
             arbitrary perpendicular axis (cross with world up; if
             still collinear, cross with world right).
          2. Secondary constraint (skipped when secondary_from or
             secondary_to has magnitude 0): compute signed roll angle
             between projections of sf and st onto the plane
             perpendicular to primary_to. Add roll * primary_to to
             the angular velocity.
          3. Clamp per-axis magnitude to GetMaxAngularVelocity()
             (FALLBACK_MAX_ACCEL when the IES isn't populated).
          4. SetTargetAngularVelocityDirect(angular_velocity).
          5. Return total_angle / max_angular_velocity (loose
             estimate; TurnToOrientation uses it only when
             bDoneOnLineup=1, and that's gated separately).
        """
        import math as _math
        from engine.appc.math import TGPoint3

        # Normalised copies — avoid mutating caller vecs.
        pf = TGPoint3(primary_from.x, primary_from.y, primary_from.z); pf.Unitize()
        pt = TGPoint3(primary_to.x, primary_to.y, primary_to.z); pt.Unitize()

        # 1. Primary alignment.
        cos_a = pf.Dot(pt)
        if cos_a > 1.0: cos_a = 1.0
        elif cos_a < -1.0: cos_a = -1.0
        primary_angle = _math.acos(cos_a)

        axis = pf.Cross(pt)
        axis_len = axis.Length()
        if axis_len < 1e-9:
            # Collinear: either aligned (angle 0, return zero AV) or
            # opposite (angle π, need a perpendicular axis).
            if primary_angle < 1e-6:
                axis = TGPoint3(0.0, 0.0, 0.0)
            else:
                # Pick an arbitrary perpendicular.
                world_up = TGPoint3(0.0, 0.0, 1.0)
                candidate = pf.Cross(world_up)
                if candidate.Length() < 1e-6:
                    world_right = TGPoint3(1.0, 0.0, 0.0)
                    candidate = pf.Cross(world_right)
                candidate.Unitize()
                axis = candidate
        else:
            axis.Scale(1.0 / axis_len)  # unit primary rotation axis

        # Angular velocity contribution from primary: magnitude = angle.
        av_x = axis.x * primary_angle
        av_y = axis.y * primary_angle
        av_z = axis.z * primary_angle

        # 2. Secondary constraint.
        sf_len = (secondary_from.x ** 2 + secondary_from.y ** 2 + secondary_from.z ** 2) ** 0.5
        st_len = (secondary_to.x ** 2 + secondary_to.y ** 2 + secondary_to.z ** 2) ** 0.5
        roll_angle = 0.0
        if sf_len > 1e-9 and st_len > 1e-9:
            # Project sf and st onto the plane perpendicular to pt.
            sf = TGPoint3(secondary_from.x, secondary_from.y, secondary_from.z)
            st = TGPoint3(secondary_to.x, secondary_to.y, secondary_to.z)
            sf_proj = TGPoint3(
                sf.x - pt.x * sf.Dot(pt),
                sf.y - pt.y * sf.Dot(pt),
                sf.z - pt.z * sf.Dot(pt),
            )
            st_proj = TGPoint3(
                st.x - pt.x * st.Dot(pt),
                st.y - pt.y * st.Dot(pt),
                st.z - pt.z * st.Dot(pt),
            )
            sf_proj.Unitize(); st_proj.Unitize()
            cos_roll = sf_proj.Dot(st_proj)
            if cos_roll > 1.0: cos_roll = 1.0
            elif cos_roll < -1.0: cos_roll = -1.0
            roll_angle = _math.acos(cos_roll)
            # Sign: positive if (sf_proj × st_proj) is along +pt.
            sign_axis = sf_proj.Cross(st_proj)
            if sign_axis.Dot(pt) < 0.0:
                roll_angle = -roll_angle
            av_x += pt.x * roll_angle
            av_y += pt.y * roll_angle
            av_z += pt.z * roll_angle

        # 3. Clamp per-axis to MaxAngularVelocity. Uses the same
        # IES-populated guard as ship_motion._max_angular_accel.
        ies = self.GetImpulseEngineSubsystem()
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            max_av = ies.GetMaxAngularVelocity()
        else:
            max_av = 1.0e9  # ship_motion.FALLBACK_MAX_ACCEL parallel
        def _clamp(v, m):
            if v > m: return m
            if v < -m: return -m
            return v
        av_x = _clamp(av_x, max_av)
        av_y = _clamp(av_y, max_av)
        av_z = _clamp(av_z, max_av)

        # 4. Write the setpoint.
        result = TGPoint3(av_x, av_y, av_z)
        self.SetTargetAngularVelocityDirect(result)

        # 5. ETA estimate.
        total_angle = abs(primary_angle) + abs(roll_angle)
        if max_av > 1e-9:
            return float(total_angle / max_av)
        return 0.0
```

- [ ] **Step 5.4: Run to verify the tests pass**

Run: `uv run pytest tests/unit/test_turn_directions.py -v`

Expected: 6 PASS.

If `test_ninety_degree_turn_angular_velocity_around_expected_axis` fails on the sign of `av.z`, the cross product sign is the opposite — confirm with `+Y × +X = -Z` by hand: `(0,1,0) × (1,0,0) = (1·0 - 0·0, 0·1 - 0·0, 0·0 - 1·1) = (0, 0, -1)`. So `av.z < 0` is correct. If the test still fails, the issue is in the implementation, not the convention.

- [ ] **Step 5.5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_turn_directions.py
git commit -m "feat(ships): TurnDirectionsToDirections solver"
```

---

## Task 6: Order-of-ops test in `test_loop.py`

Pin the within-tick contract: timer ticks → `g_kAIManager.tick` → `tick_all_ai` → `tick_all_ship_motion` → shield updates. The spec calls this the "three asserts pin the within-tick contract" test.

**Files:**
- Modify: [`tests/unit/test_loop.py`](../../../tests/unit/test_loop.py)

- [ ] **Step 6.1: Write the failing test**

Append to [`tests/unit/test_loop.py`](../../../tests/unit/test_loop.py):

```python
def test_gameloop_runs_ai_before_motion_integrator():
    """Within one tick: AI scripts write setpoints, THEN the motion
    integrator reads them. If the order is reversed, the setpoint
    from this tick wouldn't move the ship until next tick.

    Three asserts:
      1. AI script Update fires (proves tick_all_ai ran).
      2. _speed_setpoint is non-None when the integrator reads it
         (proves AI ran first).
      3. _current_speed advanced from 0 -> target on this very tick
         (proves the integrator ran after AI, not before).
    """
    import App
    from engine.appc.ai import PlainAI
    from engine.appc.math import TGPoint3, TGPoint3_GetModelForward
    from engine.appc.ships import ShipClass

    setpoint_seen_during_update = []

    class _Leaf:
        def __init__(self):
            self.calls = 0
        def GetNextUpdateTime(self): return 1.0
        def Update(self):
            self.calls += 1
            # When this fires, the integrator has NOT yet run for
            # this tick — _current_speed should still be its prior
            # value (0 on first tick).
            setpoint_seen_during_update.append(ship._current_speed)
            ship.SetImpulse(50.0, TGPoint3_GetModelForward(),
                            App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
            ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))
            return 0  # US_ACTIVE

    ship = ShipClass()
    pai = PlainAI(ship, "T")
    pai._script_instance = _Leaf()
    ship.SetAI(pai)

    pSet = App.SetClass_Create()
    pSet.SetName("orderoftest")
    pSet.AddObjectToSet(ship, "testship")
    App.g_kSetManager._sets["orderoftest"] = pSet
    try:
        loop = GameLoop()
        loop.tick()

        # Assert 1: AI fired.
        assert pai.GetScriptInstance().calls == 1

        # Assert 2: At the moment AI ran, _current_speed was still 0
        # (integrator hadn't touched it yet on this tick).
        assert setpoint_seen_during_update == [0.0]

        # Assert 3: After tick() returned, the integrator HAS run and
        # ramped _current_speed up — FALLBACK_MAX_ACCEL snaps to 50.0
        # in one tick.
        assert ship._current_speed == 50.0
    finally:
        App.g_kSetManager._sets.pop("orderoftest", None)
```

- [ ] **Step 6.2: Run to verify it passes**

Run: `uv run pytest tests/unit/test_loop.py::test_gameloop_runs_ai_before_motion_integrator -v`

Expected: PASS — the order is already correct in `GameLoop.tick` (Task 1 wired `tick_all_ship_motion` after `tick_all_ai`).

If the test fails on the third assert (`_current_speed == 0`), the integrator isn't being called. Re-check the lazy import in [`engine/core/loop.py`](../../../engine/core/loop.py) added in Step 1.5.

- [ ] **Step 6.3: Run the full loop test file**

Run: `uv run pytest tests/unit/test_loop.py -v`

Expected: all pre-existing tests + the new one PASS.

- [ ] **Step 6.4: Commit**

```bash
git add tests/unit/test_loop.py
git commit -m "test(loop): pin AI-then-motion order-of-ops within a tick"
```

---

## Task 7: End-to-end GoForward smoke test

Real `AI.PlainAI.GoForward` loaded via `_SDKFinder`, attached to a ship, run for 6 simulated seconds in the GameLoop. Expectations: ship has drifted along +Y by ~300 units (50 units/s × 6 s, within ramp tolerance), X/Z stay zero, AI is `US_ACTIVE`.

**Files:**
- Test: `tests/integration/test_ai_goforward_smoke.py` (new)

- [ ] **Step 7.1: Write the integration test**

Create `tests/integration/test_ai_goforward_smoke.py`:

```python
"""End-to-end smoke: GoForward AI drifts a ship along +Y.

Proves the full chain: SDK script loading (Task 1 of prior slice),
AI driver (Task 3 of prior slice), motion integrator (Tasks 1-3
of this slice), SetImpulse alias (Task 2), GameLoop wiring."""
import pytest

import App
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass


def _setup_ship_with_goforward(impulse: float = 50.0):
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("goforward_smoke")
    App.g_kSetManager._sets["goforward_smoke"] = pSet
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "testship")

    pai = PlainAI_Create(ship, "TestGoForward")
    pai.SetScriptModule("GoForward")
    # GoForward requires a SetImpulse parameter — set it on the script
    # instance directly (SDK pattern: BaseAI.SetRequiredParams configures
    # the surface; mission scripts call SetImpulse(N) before activation).
    inst = pai.GetScriptInstance()
    inst.SetImpulse(impulse)
    ship.SetAI(pai)
    return ship, pai


def test_goforward_drifts_along_plus_y():
    """6 seconds at 50 units/s → ~300 units along ship-forward (+Y).
    Tolerance is loose because FALLBACK_MAX_ACCEL snaps on the first
    tick, so the ship effectively drifts at full speed for ~6 s. The
    first ~1/60 s tick before the AI's first Update is the only
    "ramp" loss: < 1 unit."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 6)
    p = ship.GetTranslate()
    assert p.y == pytest.approx(300.0, abs=2.0)
    assert p.x == pytest.approx(0.0, abs=1e-6)
    assert p.z == pytest.approx(0.0, abs=1e-6)


def test_goforward_stays_active():
    """GoForward returns US_ACTIVE forever (mirrors Stay)."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 6)
    assert pai.IsActive() == 1


def test_goforward_speed_setpoint_persists():
    """After GoForward's Update fires, _speed_setpoint records 50.0
    along model-forward in MODEL_SPACE frame — the setpoint survives
    across many ticks because the AI is on a 5-second cadence."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 2)  # two seconds — well before the next
                                 # 5-second AI tick
    sp = ship.GetSpeedSetpoint()
    assert sp is not None
    assert sp[0] == 50.0
    assert sp[2] == App.PhysicsObjectClass.DIRECTION_MODEL_SPACE


```

- [ ] **Step 7.2: Run the test**

Run: `uv run pytest tests/integration/test_ai_goforward_smoke.py -v`

Expected: 3 PASS.

If `test_goforward_drifts_along_plus_y` fails because `p.y` is far off 300, possible causes:
- AI didn't fire (check `pai.GetScriptInstance().Update` count in a debug print).
- Direction-frame conversion picked the wrong axis (compare with the corresponding unit test in `test_ship_motion.py`).
- `_SDKFinder` didn't import `AI.PlainAI.GoForward` — verify with `import AI.PlainAI.GoForward; print(AI.PlainAI.GoForward.GoForward)` at a Python REPL with the test conftest active.

- [ ] **Step 7.3: Commit**

```bash
git add tests/integration/test_ai_goforward_smoke.py
git commit -m "test(ai): end-to-end smoke for PlainAI('GoForward') drift"
```

---

## Task 8: End-to-end TurnToOrientation smoke test

Real `AI.PlainAI.TurnToOrientation` loaded via `_SDKFinder`, attached to a ship at origin, target placed at world `(1000, 0, 0)`. Expectations: after N seconds, the ship's model-forward (`GetRow(1)` of world rotation) has non-trivial +X component (`> 0.9` once aligned). `bDoneOnLineup=1` variant → `US_DONE` after alignment. Target on -X → rotates the other way.

**Files:**
- Test: `tests/integration/test_ai_turn_to_orientation_smoke.py` (new)

- [ ] **Step 8.1: Write the integration test**

Create `tests/integration/test_ai_turn_to_orientation_smoke.py`:

```python
"""End-to-end smoke: TurnToOrientation rotates a ship to face a target.

Proves TurnDirectionsToDirections (Task 5), angular integration
(Task 3), GetRelativePositionInfo (Task 4), real SDK script load
(prior slice)."""
import pytest

import App
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass


def _setup_ship_with_turn_to(target_pos, *, done_on_lineup=0,
                              target_name="target"):
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("turn_smoke")
    App.g_kSetManager._sets["turn_smoke"] = pSet

    # Target ship — TurnToOrientation looks it up by name from the
    # containing set (sdk/.../TurnToOrientation.py:122-128).
    target = ShipClass()
    target.SetTranslateXYZ(*target_pos)
    pSet.AddObjectToSet(target, target_name)

    # Subject ship at origin, identity rotation.
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(ship, "subject")

    pai = PlainAI_Create(ship, "TestTurn")
    pai.SetScriptModule("TurnToOrientation")
    inst = pai.GetScriptInstance()
    # Required param — SDK SetExternalFunctions registers "SetTarget"
    # as an alias for SetObjectName, both reach the same field.
    inst.SetObjectName(target_name)
    inst.SetPrimaryDirection()  # default: TGPoint3_GetModelForward()
    inst.SetDoneOnLineup(done_on_lineup)
    ship.SetAI(pai)
    return ship, pai, target


def test_turn_to_orientation_rotates_toward_target_on_plus_x():
    """Target at world (1000, 0, 0). After several seconds, the
    ship's model-forward (GetRow(1)) should have a strong +X
    component (well above 0.9 = the SDK's fDoneDot constant)."""
    ship, pai, target = _setup_ship_with_turn_to((1000.0, 0.0, 0.0))
    loop = GameLoop()
    # The SDK's TurnToOrientation runs every 0.5s; the integrator
    # applies the angular velocity every tick. Give it enough time
    # to traverse 90° at FALLBACK MaxAngularVelocity (which is
    # effectively instant) — even a few seconds is overkill but
    # documents the ceiling.
    loop.advance(TICK_RATE * 10)

    fwd = ship.GetWorldRotation().GetRow(1)
    # Strong +X component means the ship is facing the target.
    assert fwd.x > 0.9, f"ship did not turn toward +X target; fwd={fwd}"


def test_turn_to_orientation_rotates_toward_target_on_minus_x():
    """Target at (-1000, 0, 0). After alignment, fwd.x should be
    near -1.0 — proving the solver picks the shorter rotation
    direction, not the wrong way around."""
    ship, pai, target = _setup_ship_with_turn_to((-1000.0, 0.0, 0.0))
    loop = GameLoop()
    loop.advance(TICK_RATE * 10)

    fwd = ship.GetWorldRotation().GetRow(1)
    assert fwd.x < -0.9, f"ship did not turn toward -X target; fwd={fwd}"


def test_turn_to_orientation_done_on_lineup_completes():
    """With bDoneOnLineup=1, once the ship is within fDoneDot of
    aligned, the AI returns US_DONE and stops being active."""
    ship, pai, target = _setup_ship_with_turn_to(
        (1000.0, 0.0, 0.0), done_on_lineup=1)
    loop = GameLoop()
    # Run long enough that at least one Update fires after alignment.
    # TurnToOrientation cadence is 0.5s; run for 5s = 10 Update
    # cycles. Under FALLBACK_MAX_ACCEL the ship snaps to facing in
    # the first tick after the first Update.
    loop.advance(TICK_RATE * 5)
    assert pai.IsActive() == 0, "TurnToOrientation should complete with bDoneOnLineup=1"
```

- [ ] **Step 8.2: Run the test**

Run: `uv run pytest tests/integration/test_ai_turn_to_orientation_smoke.py -v`

Expected: 3 PASS.

Common failure modes and fixes:
- `fwd.x` is near 0 (no rotation): the angular velocity from `TurnDirectionsToDirections` isn't being integrated. Check that the integrator's angular path (Task 3) is firing — add a one-liner `print(ship._current_angular_velocity)` inside `_step_ship_motion` to diagnose.
- `fwd.x` is exactly 1.0 but tests run extremely fast: that's fine — `FALLBACK_MAX_ACCEL` snaps everything to target in the first tick. The assertions are deliberately loose to allow for both ramp-limited and snap-to-target behaviour.
- `done_on_lineup` test fails because `pai.IsActive()` stays at 1: the SDK's `TurnToOrientation.Update` returns `US_DONE` only when `bLinedUp` is true AND `bDoneOnLineup` is set. Inspect `inst.bDoneOnLineup` and confirm `SetDoneOnLineup(1)` actually wrote `1` (BaseAI's `SetupDefaultParams` may be overriding).

- [ ] **Step 8.3: Commit**

```bash
git add tests/integration/test_ai_turn_to_orientation_smoke.py
git commit -m "test(ai): end-to-end smoke for PlainAI('TurnToOrientation')"
```

---

## Task 9: Visible mission fixture + deferred-doc update

Place an `AIMotion` mission under `Custom/Tutorial/Episode/AIMotion/` so the mission picker discovers it. The mission spawns the player ship and one AI hostile +1000 units along ship-forward, attaches `PlainAI("GoForward")` to the hostile with a modest `SetImpulse(20)`. Visual acceptance: launch `./build/dauntless`, pick "AIMotion" from the mission picker, see the hostile drift slowly forward.

Also strike completed items from the deferred AI runtime doc.

**Files:**
- Create: `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/AIMotion.py`
- Create: `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/__init__.py`
- Modify: [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md)

- [ ] **Step 9.1: Verify the mission picker discovers Tutorial leaf dirs**

Run: `uv run python -c "from engine.missions.discovery import discover; r = discover('sdk/Build/scripts'); print([m.dir_name for f in r.families for ep in f.episodes for m in ep.missions])"`

Expected: a list including `M1Basic`, `M2Objects`, `M3Gameflow`, `M4Complex`. The walk only flags dirs whose primary `.py` file contains a top-level `def Initialize(`. Note this — any new mission file must define `Initialize(pMission)` to appear.

- [ ] **Step 9.2: Create the empty package marker**

Create `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/__init__.py` as an empty file.

- [ ] **Step 9.3: Create the mission script**

Create `sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion/AIMotion.py`:

```python
###############################################################################
#  AIMotion.py
#
#  Visible smoke for the Ship AI Motion slice (2026-05-18). Spawns the
#  player ship at origin facing +Y and one hostile +1000 units along
#  ship-forward, then attaches PlainAI("GoForward") with SetImpulse(20)
#  to the hostile. The hostile drifts slowly forward, providing a
#  visible end-to-end check that:
#    1. AI scripts load (real GoForward.py).
#    2. The AI driver fires Update each 5s.
#    3. SetImpulse + the motion integrator move the ship.
#  Run with ./build/dauntless and pick AIMotion from the mission menu.
###############################################################################
import App
import loadspacehelper
import MissionLib


def PreLoadAssets(pMission):
    # Pre-create one Galaxy for both player and hostile so the model
    # is in the cache before the mission's Initialize runs.
    loadspacehelper.PreloadShip("Galaxy", 2)


def Initialize(pMission):
    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    # Reuse the Biranu 1 region — the same one M1Basic uses. Lets us
    # rely on the existing region's backdrop/sun without inventing
    # new scenery for a smoke mission.
    import Systems.Biranu.Biranu
    Systems.Biranu.Biranu.CreateMenus()
    MissionLib.SetupSpaceSet("Systems.Biranu.Biranu1")

    pSet = App.g_kSetManager.GetSet("Biranu1")
    if pSet is None:
        return

    # Player ship at origin, facing +Y (model default). Use the same
    # CreateShip/SetPlayerShip flow as M1Basic.py so the existing
    # host_loop binding picks up the player normally. Defensive
    # try/except around the fleet/mission glue: Phase-1 shims may
    # not implement every callee, but the mission must still load
    # so the hostile-drift smoke works.
    pPlayer = loadspacehelper.CreateShip("Enterprise", pSet, "Galaxy")
    if pPlayer is not None:
        pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
        try:
            App.g_kFleetManager.AddShipToFleet(pPlayer, "Federation")
        except Exception:
            pass
        try:
            pMission.SetPlayerShip(pPlayer)
        except Exception:
            pass

    # Hostile 1000 units along +Y (model-forward). This is the visible
    # subject — attach a real PlainAI("GoForward") with a slow impulse
    # so the hostile drifts visibly without leaving the scene fast.
    pHostile = loadspacehelper.CreateShip("Hostile", pSet, "Galaxy")
    if pHostile is not None:
        pHostile.SetTranslateXYZ(0.0, 1000.0, 0.0)
        pAI = App.PlainAI_Create(pHostile, "GoForwardSmoke")
        pAI.SetScriptModule("GoForward")
        pAI.GetScriptInstance().SetImpulse(20.0)
        pHostile.SetAI(pAI)
```

The two `try/except` blocks above cover the case where Phase-1 shims for `g_kFleetManager.AddShipToFleet` or `Mission.SetPlayerShip` are no-ops or missing. The hostile + its AI is the load-bearing part of the smoke test; everything else is supportive scenery.

- [ ] **Step 9.4: Confirm discovery picks up `AIMotion`**

Run: `uv run python -c "from engine.missions.discovery import discover; r = discover('sdk/Build/scripts'); print(sorted({m.dir_name for f in r.families for ep in f.episodes for m in ep.missions}))"`

Expected: list now includes `'AIMotion'` alongside `M1Basic`, etc.

- [ ] **Step 9.5: Build and launch the renderer**

Run:
```bash
cmake --build build -j
./build/dauntless
```

Expected: dauntless launches; the mission picker shows an "AIMotion" entry under Tutorial. Selecting it spawns the player + a Galaxy hostile 1000 units ahead. Over 10-30 seconds, the hostile drifts further away (or, with the camera oriented behind the player, slowly toward the horizon).

If `cmake --build` reports shader-edit-reconfigure errors, fall back to `cmake -B build -S . && cmake --build build -j` (the project memory at [memory/project_shader_edits_need_reconfigure.md](../../../memory/project_shader_edits_need_reconfigure.md) documents this gotcha).

This step is the user-visible acceptance criterion. The headless tests prove the math; this step proves the integration into the engine binary.

- [ ] **Step 9.6: Strike completed items from the deferred AI-runtime doc**

In [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md), update Step 5 (the "smoke trail, one leaf at a time" section) by striking through items 2 and 3:

```markdown
### Step 5 — End-to-end smoke trail, one leaf at a time

1. **`PlainAI.Stay`** ([`Stay.py`](../../../sdk/Build/scripts/AI/PlainAI/Stay.py)) — ✅ done in [Steps 1-3 plan](../plans/2026-05-18-ship-ai-runtime-step1-3.md).
2. **`PlainAI.GoForward`** — ✅ done in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md). `SetImpulse` aliased to `SetSpeed`; linear ramp + position integration land in `engine/appc/ship_motion.py`.
3. **`PlainAI.TurnToOrientation`** — ✅ done in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md). `TurnDirectionsToDirections` solver in `engine/appc/ships.py`; angular ramp + rotation integration in `engine/appc/ship_motion.py`.
4. **`PlainAI.Intercept`** ([`Intercept.py`](../../../sdk/Build/scripts/AI/PlainAI/Intercept.py)) — still open; needs `TurnTowardLocation`, `InSystemWarp`/`StopInSystemWarp`, obstacle-avoidance.
5. **`PlainAI.FollowObject` + `CircleObject`** — still open; `GetRelativePositionInfo` is now available (landed in the motion slice).
6. **`AI.Compound.BasicAttack`** — still open.
```

And in Step 4 (the motion API section), add a `(done)` annotation to the four primitives this slice closed:

```markdown
### Step 4 — Ship motion APIs on `ShipClass`

Bind to PyBullet rigid bodies (Phase 1 harness) and the C++ engine later:

- `TurnTowardLocation(vec)` — still open. PD-style solver: compute axis-angle from current forward to target direction, set target angular velocity. Largely the same math as `TurnDirectionsToDirections` (done) — should be a thin wrapper.
- `SetTargetAngularVelocityDirect(vec)` — ✅ done in Steps 1-3 plan; defensive copy in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md).
- `SetSpeed(speed, direction, frame)` — ✅ done; defensive copy added in motion slice. `SetImpulse` alias added.
- `GetPredictedPosition(p, v, a, t)` — ✅ done in motion slice.
- `GetRelativePositionInfo(vec)` — ✅ done in motion slice.
- `InSystemWarp(target, distance)` — still open. Start with "teleport to within `distance` of target, decel"; refine when chase camera + sub-light warp visuals land.
- `StopInSystemWarp()` — still open. `Intercept.LostFocus` calls it ([`Intercept.py:73`](../../../sdk/Build/scripts/AI/PlainAI/Intercept.py)).
- `GetImpulseEngineSubsystem().GetMaxSpeed()` / `GetMaxAccel()` — ✅ already exist on the subsystem; the motion integrator + `TurnDirectionsToDirections` solver use them.
```

- [ ] **Step 9.7: Run the full test suite one final time**

Run: `uv run pytest tests/unit tests/integration -q`

Expected: green across the board (or only pre-existing failures unrelated to this slice).

- [ ] **Step 9.8: Commit**

```bash
git add sdk/Build/scripts/Custom/Tutorial/Episode/AIMotion docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "feat(mission): AIMotion smoke mission + close motion items in deferred AI runtime"
```

---

## Out of scope (deferred to the next slice)

- `TurnTowardLocation`, `InSystemWarp`, `StopInSystemWarp`, obstacle avoidance — Intercept slice.
- PyBullet rigid-body integration — the integrator stays kinematic; physics motion lives behind a separate later slice.
- `PriorityListAI` status propagation from child to parent (current driver runs one child per tick; full status promotion lands when `Compound.BasicAttack` needs it).
- `OptimizedFireScript` / `OptimizedSelectTarget` preprocessor wiring — combat slice.
- `ConditionScript` evaluation — still data-only.
- Save/load of motion state (`_current_speed`, `_current_angular_velocity`).
- PD damping for angular convergence — natural soft stop (gap-shrinking velocity) is enough for the smoke test; revisit when `Intercept` lands.

These remain in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md) and pick up where this plan leaves off.
