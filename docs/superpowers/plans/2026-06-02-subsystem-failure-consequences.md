# Subsystem-Failure Gameplay Consequences — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire five capability gates — engines, weapons, sensors, shield-generator regen, and repair-release verification — into the existing damage pipeline so damaged subsystems actually stop their capabilities working.

**Architecture:** Single shared predicate `_is_offline(sub)` reads `IsDisabled()` / `IsDestroyed()` at use-time. Each gate calls it and returns early / clamps to zero. No cached state, no event bus, no write-side coordination — repair lifting condition auto-releases gates on the next tick.

**Tech Stack:** Python (engine layer), pytest, existing `App.py` shim, no native code changes.

**Spec:** [`docs/superpowers/specs/2026-06-02-subsystem-failure-consequences-design.md`](../specs/2026-06-02-subsystem-failure-consequences-design.md)

**Branch:** `feature/subsystem-failure-consequences` (already created with the spec commit).

---

## File map

**Modified:**
- `engine/appc/subsystems.py` — add `_is_offline` helper; gates in `WeaponSystem.StartFiring`, `PhaserSystem.StartFiring`, `PhaserSystem.retry_held_fire`, `ShieldSubsystem.Update`, `update_target_list_visibility`.
- `engine/appc/ship_motion.py` — add `DISABLED_ENGINE_DRAG_FRACTION` constant; gate in `_step_ship_motion`.
- `engine/host_loop.py` — gates in `_PlayerControl.GetTargetSpeed`, `_PlayerControl.apply`, and `_advance_combat`.
- `engine/ui/ship_display_panel.py` — `player_sensors_offline` helper; gates in `_affiliation_for` and `_resolve_ship_for_role`.

**New tests:**
- `tests/unit/test_is_offline_helper.py`
- `tests/unit/test_engines_disabled_clamps_throttle.py`
- `tests/unit/test_weapons_disabled_blocks_fire.py`
- `tests/unit/test_shield_generator_disabled_stops_regen.py`
- `tests/unit/test_sensors_disabled_blanks_target_ui.py`
- `tests/integration/test_engines_disabled_decays_velocity.py`

---

## Background — predicates already in place

The leaf `ShipSubsystem.IsDisabled()` returns 1 iff `condition <= disabled_percentage * max_condition`. `IsDestroyed()` returns 1 iff `condition == 0` (or `_destroyed` flag set). `WeaponSystem.IsDisabled()` (Project 2) aggregates: 1 iff `bool(children) and all(c.IsDisabled() for c in children)`.

Test setup pattern (from `tests/unit/test_weapon_system_aggregation.py`):

```python
child = PhaserBank("A")
child._max_condition = 100.0
child._condition = 100.0
child._disabled_percentage = 0.25
# To disable: child._condition = 10.0   (10 <= 0.25*100=25)
# To destroy: child._condition = 0.0
# To repair:  child._condition = 100.0
```

Player-control test pattern (from `tests/host/test_player_control_hardpoints.py`):

```python
class _Keys: KEY_W = 1; ...   # numeric stand-in for key constants
class _Reader:
    keys = _Keys()
    def __init__(self): self.held = set(); self.pressed_once = set()
    def key_state(self, key): return key in self.held
    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key); return True
        return False
```

---

### Task 1: Shared `_is_offline` helper

**Files:**
- Modify: `engine/appc/subsystems.py` (add module-level helper near other module-level helpers like `update_target_list_visibility` at line ~1898; module-level is fine — pick a location near `ShipSubsystem` or at the bottom alongside the visibility helper)
- Test: `tests/unit/test_is_offline_helper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_is_offline_helper.py`:

```python
"""`_is_offline(sub)` returns True iff the subsystem reports IsDisabled
OR IsDestroyed. Used by every Project 5 gate as the single source of
truth for "this capability is offline." Repair lifting condition flips
the gate back automatically because the predicate is read at use-time.
"""
from engine.appc.subsystems import _is_offline, ShipSubsystem


def _sub(condition, max_condition=100.0, disabled_percentage=0.5):
    s = ShipSubsystem("test")
    s._max_condition = float(max_condition)
    s._condition = float(condition)
    s._disabled_percentage = float(disabled_percentage)
    return s


def test_none_returns_false():
    assert _is_offline(None) is False


def test_healthy_returns_false():
    assert _is_offline(_sub(condition=100.0)) is False


def test_disabled_returns_true():
    # disabled_percentage 0.5 of max 100 -> threshold 50, condition 40 is disabled
    assert _is_offline(_sub(condition=40.0)) is True


def test_destroyed_returns_true():
    assert _is_offline(_sub(condition=0.0)) is True


def test_explicit_disabled_flag_returns_true():
    s = _sub(condition=100.0)
    s.SetDamaged(False)
    # SetDestroyed flips IsDestroyed -> _is_offline True via the destroy branch.
    s.SetDestroyed(True)
    assert _is_offline(s) is True


def test_repair_lifts_offline():
    s = _sub(condition=40.0)
    assert _is_offline(s) is True
    s.SetCondition(100.0)
    assert _is_offline(s) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_is_offline_helper.py -v`
Expected: FAIL with `ImportError: cannot import name '_is_offline'`.

- [ ] **Step 3: Add the helper to `engine/appc/subsystems.py`**

Add this function at module level, just above `class ShipSubsystem` (search for `class ShipSubsystem` to locate; place the helper immediately before it so every downstream call site sees it):

```python
def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed.

    Project 5 single source of truth for the five capability gates
    (engines, weapons, sensors, shield generator, repair-verify).
    Reads predicates at use-time so repair lifting condition releases
    the gate automatically on the next call.
    """
    if sub is None:
        return False
    return bool(sub.IsDisabled()) or bool(sub.IsDestroyed())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_is_offline_helper.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_is_offline_helper.py
git commit -m "feat(subsystems): _is_offline shared predicate helper

Single source of truth for Project 5 capability gates. Reads
IsDisabled/IsDestroyed at use-time so repair auto-releases gates."
```

---

### Task 2: Engines gate — AI integrator + `DISABLED_ENGINE_DRAG_FRACTION` constant

**Files:**
- Modify: `engine/appc/ship_motion.py` — add constant; gate `_step_ship_motion` so disabled IES clamps both linear and angular targets and uses drag-fraction-scaled ramp steps.
- Test: `tests/unit/test_engines_disabled_clamps_throttle.py` (will be extended in Tasks 3-4)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_engines_disabled_clamps_throttle.py`:

```python
"""Engines disabled / destroyed → ship_motion._step_ship_motion clamps
linear and angular targets to zero and applies a drag-fraction-scaled
ramp so current velocities decay slowly. Repair lifts the gate at use-
time (no cached flag)."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import (
    _step_ship_motion, DISABLED_ENGINE_DRAG_FRACTION,
)


def _galaxy_like_ship():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies._disabled_percentage = 0.5
    return ship


def _set_forward_setpoint(ship, speed):
    ship._speed_setpoint = (
        speed, TGPoint3(0.0, 1.0, 0.0),
        PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )


def _set_angular_setpoint(ship, x, y, z):
    ship._target_angular_velocity_setpoint = TGPoint3(x, y, z)


def test_drag_fraction_is_one_tenth():
    """Locked tuning constant from the spec (§2)."""
    assert DISABLED_ENGINE_DRAG_FRACTION == 0.1


def test_healthy_ies_ramps_to_setpoint_at_max_accel():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # After ~1 s at MaxAccel 1.5: current_speed = 1.5.
    assert abs(ship._current_speed - 1.5) < 1e-3


def test_disabled_ies_clamps_target_and_decays_at_drag_fraction():
    """Disable IES with high current_speed; target clamps to 0, decay is
    MaxAccel * drag_fraction per second (not full MaxAccel)."""
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ship._current_speed = 6.3
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # below 0.5 * 100 = 50 -> disabled
    assert ies.IsDisabled() == 1

    for _ in range(60):  # 1 second
        _step_ship_motion(ship, 1.0 / 60)
    # Drag-fraction decel: 1.5 * 0.1 = 0.15 m/s^2; after 1s: 6.3 - 0.15 = 6.15.
    expected = 6.3 - 1.5 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_speed - expected) < 1e-3


def test_destroyed_ies_behaves_identically_to_disabled():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ship._current_speed = 6.3
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(0.0)  # destroyed
    assert ies.IsDestroyed() == 1

    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    expected = 6.3 - 1.5 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_speed - expected) < 1e-3


def test_disabled_ies_clamps_angular_target_and_decays():
    """Angular setpoint also clamps to zero; ramp uses drag fraction."""
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 0.0)
    _set_angular_setpoint(ship, 0.0, 0.0, 0.28)  # yawing at MaxAngularVelocity
    ship._current_angular_velocity.z = 0.28
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # MaxAngularAccel 0.12 * drag_fraction 0.1 = 0.012 rad/s^2; 1s: 0.28-0.012=0.268.
    expected = 0.28 - 0.12 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_angular_velocity.z - expected) < 1e-3


def test_repair_restores_full_ramp_rate():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # disabled
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    speed_disabled = ship._current_speed

    ies.SetCondition(100.0)  # repaired
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # 1 s of healthy ramp at MaxAccel 1.5: gain ~1.5 (capped at MaxSpeed 6.3).
    assert ship._current_speed > speed_disabled + 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py -v`
Expected: `test_drag_fraction_is_one_tenth` FAILS with `ImportError` for `DISABLED_ENGINE_DRAG_FRACTION`; other tests also fail because the gate doesn't exist.

- [ ] **Step 3: Add the constant + gate to `engine/appc/ship_motion.py`**

At the top of `engine/appc/ship_motion.py`, after the existing `FALLBACK_MAX_ACCEL = 1.0e9` constant, add:

```python
# When the impulse engine subsystem is disabled or destroyed,
# _step_ship_motion clamps target speed and angular targets to zero
# and scales the ramp step by this fraction so velocity decays
# gracefully instead of instantly. 0.1 = ~10× the normal stop time.
# Spec: docs/superpowers/specs/2026-06-02-subsystem-failure-consequences-design.md §2.
DISABLED_ENGINE_DRAG_FRACTION = 0.1
```

Modify `_step_ship_motion` — locate the function body (starts at line 65). The current code reads the setpoint, computes `target_speed`, ramps via `step = _max_accel(ship) * dt`, then handles angular similarly. Add the offline check just after the setpoint resolution and before the ramps:

Find this section (current code at lines 91-94):

```python
    # ── Ramp current speed toward target ─────────────────────────────
    step = _max_accel(ship) * dt
    ship._current_speed = _ramp_toward(ship._current_speed, target_speed, step)
```

Replace with:

```python
    # ── Engines-disabled gate: clamp target + scale ramp by drag fraction.
    # Reads predicate at use-time so repair lifting condition releases
    # the gate on the next call. Spec §4.1.
    from engine.appc.subsystems import _is_offline
    engines_offline = _is_offline(ship.GetImpulseEngineSubsystem())
    if engines_offline:
        target_speed = 0.0

    # ── Ramp current speed toward target ─────────────────────────────
    step = _max_accel(ship) * dt
    if engines_offline:
        step *= DISABLED_ENGINE_DRAG_FRACTION
    ship._current_speed = _ramp_toward(ship._current_speed, target_speed, step)
```

Then find the angular block (current code around lines 114-125):

```python
    # ── Resolve target angular velocity ──────────────────────────────
    if av is None:
        target_av_x = target_av_y = target_av_z = 0.0
    else:
        target_av_x, target_av_y, target_av_z = av.x, av.y, av.z

    # ── Ramp each axis of _current_angular_velocity toward target ────
    ang_step = _max_angular_accel(ship) * dt
```

Modify to:

```python
    # ── Resolve target angular velocity ──────────────────────────────
    if av is None:
        target_av_x = target_av_y = target_av_z = 0.0
    else:
        target_av_x, target_av_y, target_av_z = av.x, av.y, av.z

    # Engines-disabled gate also kills angular thrust (SDK puts
    # MaxAngularVelocity / MaxAngularAccel directly on ImpulseEngines;
    # no separate RCS subsystem). Spec §4.1.
    if engines_offline:
        target_av_x = target_av_y = target_av_z = 0.0

    # ── Ramp each axis of _current_angular_velocity toward target ────
    ang_step = _max_angular_accel(ship) * dt
    if engines_offline:
        ang_step *= DISABLED_ENGINE_DRAG_FRACTION
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Run the existing ship_motion regression tests**

Run: `uv run pytest tests/unit/test_ship_motion.py tests/host/test_player_control_hardpoints.py -v`
Expected: all PASS — no regression in healthy-ship integrator behaviour. (If `tests/unit/test_ship_motion.py` doesn't exist, skip it; only the player-control hardpoint tests are guaranteed.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ship_motion.py tests/unit/test_engines_disabled_clamps_throttle.py
git commit -m "feat(ship_motion): disabled-engines gate clamps linear+angular targets

Add DISABLED_ENGINE_DRAG_FRACTION=0.1 constant. _step_ship_motion checks
IES IsDisabled/IsDestroyed at use-time; when offline clamps targets to
zero and scales ramp step by drag fraction. Repair lifts gate
automatically. Spec §4.1."
```

---

### Task 3: Engines gate — player linear throttle (`_PlayerControl.GetTargetSpeed`)

**Files:**
- Modify: `engine/host_loop.py` — `_PlayerControl.GetTargetSpeed` (around line 683)
- Test: extend `tests/unit/test_engines_disabled_clamps_throttle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_engines_disabled_clamps_throttle.py`:

```python
# ── Player-side gate (host_loop._PlayerControl) ───────────────────────────────

from engine.host_loop import _PlayerControl


class _Keys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4; KEY_Q = 5; KEY_E = 6
    KEY_R = 7; KEY_I = 8
    KEY_0 = 10; KEY_1 = 11; KEY_2 = 12; KEY_3 = 13; KEY_4 = 14
    KEY_5 = 15; KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19
    KEY_LEFT_SHIFT = 20; KEY_LEFT_CONTROL = 21; KEY_LEFT_SUPER = 22


class _Reader:
    keys = _Keys()
    def __init__(self):
        self.held = set(); self.pressed_once = set()
    def key_state(self, key): return key in self.held
    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key); return True
        return False


def test_player_throttle_clamped_when_ies_disabled():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # disabled
    assert pc.GetTargetSpeed(ship) == 0.0


def test_player_throttle_clamped_when_ies_destroyed():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(0.0)
    assert pc.GetTargetSpeed(ship) == 0.0


def test_player_throttle_restored_after_repair():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    assert pc.GetTargetSpeed(ship) == 0.0
    ies.SetCondition(100.0)
    assert abs(pc.GetTargetSpeed(ship) - 6.3) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py::test_player_throttle_clamped_when_ies_disabled tests/unit/test_engines_disabled_clamps_throttle.py::test_player_throttle_clamped_when_ies_destroyed tests/unit/test_engines_disabled_clamps_throttle.py::test_player_throttle_restored_after_repair -v`
Expected: All three FAIL with `assert 6.3 == 0.0` (or similar) — the gate isn't there yet.

- [ ] **Step 3: Add the gate to `_PlayerControl.GetTargetSpeed` in `engine/host_loop.py`**

Find the function (currently at line 683). The full body begins:

```python
    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into a target speed using the ship's
        ImpulseEngineProperty.MaxSpeed when present, or the legacy
        per-level placeholder otherwise.

        Forward speed is multiplied by WARP_BOOST_FACTOR when the
        in-system warp toggle is on (Ctrl+I); reverse is unaffected.
        """
        ies = self._get_ies(player)
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
```

Insert the gate immediately after `ies = self._get_ies(player)`:

```python
    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into a target speed using the ship's
        ImpulseEngineProperty.MaxSpeed when present, or the legacy
        per-level placeholder otherwise.

        Forward speed is multiplied by WARP_BOOST_FACTOR when the
        in-system warp toggle is on (Ctrl+I); reverse is unaffected.

        Disabled-engines gate (Project 5 §4.1): when the IES reports
        IsDisabled or IsDestroyed, target is unconditionally 0 — the
        ship coasts under the ship_motion drag fraction.
        """
        from engine.appc.subsystems import _is_offline
        ies = self._get_ies(player)
        if _is_offline(ies):
            return 0.0
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py -v`
Expected: all tests PASS (including the original 6 + 3 new player tests).

- [ ] **Step 5: Run the player-control regression tests**

Run: `uv run pytest tests/host/test_player_control_hardpoints.py -v`
Expected: all PASS — healthy IES throttle math unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_engines_disabled_clamps_throttle.py
git commit -m "feat(host_loop): disabled-engines gate clamps player linear throttle

_PlayerControl.GetTargetSpeed returns 0 when IES IsDisabled/IsDestroyed.
Repair auto-releases the gate. Spec §4.1."
```

---

### Task 4: Engines gate — player angular targets (`_PlayerControl.apply`)

**Files:**
- Modify: `engine/host_loop.py` — `_PlayerControl.apply` angular ramp section (around lines 792-840)
- Test: extend `tests/unit/test_engines_disabled_clamps_throttle.py`

- [ ] **Step 1: Read the existing `_PlayerControl.apply` angular section**

Read `engine/host_loop.py` lines 740-870 to confirm the structure. The function takes `(self, player, dt, h)`, computes pitch/yaw/roll targets from held keys, then ramps current rates toward target. The gate goes after key resolution, before the ramp.

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_engines_disabled_clamps_throttle.py`:

```python
def test_player_angular_clamped_when_ies_disabled():
    """Holding D (yaw right) with disabled engines: angular target
    forced to 0 and current rate decays at drag fraction × MaxAngularAccel.
    """
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    pc._current_yaw_rate = 0.28  # already yawing at full rate
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)

    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)  # request yaw right (which sets a nonzero target)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    # MaxAngularAccel 0.12 * 0.1 drag = 0.012 rad/s² decay; after 1 s: 0.28 - 0.012 ≈ 0.268.
    expected = 0.28 - 0.12 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(pc._current_yaw_rate - expected) < 1e-3


def test_player_angular_recovers_after_repair():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    pc._current_yaw_rate = 0.28
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    reader = _Reader()
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_disabled = pc._current_yaw_rate

    ies.SetCondition(100.0)  # repaired
    for _ in range(60):  # no keys held -> target is 0, full-rate decay back to 0
        pc.apply(ship, dt=1.0/60, h=reader)
    assert pc._current_yaw_rate < rate_disabled - 0.05
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py::test_player_angular_clamped_when_ies_disabled tests/unit/test_engines_disabled_clamps_throttle.py::test_player_angular_recovers_after_repair -v`
Expected: FAIL — angular ramping uses full MaxAngularAccel, decays too fast.

- [ ] **Step 4: Add the angular gate to `_PlayerControl.apply` in `engine/host_loop.py`**

Read the section around lines 793-840 to find the structure. After the `ang_rate = self._angular_rate(player)` / `ang_step = self._angular_accel(player) * dt` lines and the per-key target assembly (`pitch_target = ...`, `yaw_target = ...`, `roll_target = ...`), and before the three `_ramp_toward` calls that update `self._current_pitch_rate / _current_yaw_rate / _current_roll_rate`, insert the gate.

The current code looks like:

```python
        ang_rate    = self._angular_rate(player)
        ang_step    = self._angular_accel(player) * dt
        pitch_target = 0.0
        yaw_target   = 0.0
        roll_target  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target -= ang_rate
        # ... other key bindings
```

Modify the `ang_step` line and add the post-key-resolution clamp. Find the line:

```python
        ang_step    = self._angular_accel(player) * dt
```

Replace with:

```python
        # Disabled-engines gate also kills angular thrust. Spec §4.1.
        from engine.appc.subsystems import _is_offline
        from engine.appc.ship_motion import DISABLED_ENGINE_DRAG_FRACTION
        engines_offline = _is_offline(self._get_ies(player))
        ang_step    = self._angular_accel(player) * dt
        if engines_offline:
            ang_step *= DISABLED_ENGINE_DRAG_FRACTION
```

Then find the three lines that look like (use the codebase's exact form — search for the pattern `pitch_target -= ang_rate` and `roll_target += ang_rate` to locate; after all six key checks have set pitch_target/yaw_target/roll_target), and immediately after the last key check, add:

```python
        if engines_offline:
            pitch_target = 0.0
            yaw_target = 0.0
            roll_target = 0.0
```

Also clamp the linear ramp step in the same function. Find:

```python
        # 2. Linear speed ramp toward target at MaxAccel rate.
        self._current_speed = self._ramp_toward(
            self._current_speed,
            self.GetTargetSpeed(player),
            self._max_accel(player) * dt,
        )
```

Replace with:

```python
        # 2. Linear speed ramp toward target at MaxAccel rate.
        #    Disabled engines: scale ramp by drag fraction so velocity
        #    decays gradually rather than at full MaxAccel. Spec §4.1.
        linear_step = self._max_accel(player) * dt
        if engines_offline:
            linear_step *= DISABLED_ENGINE_DRAG_FRACTION
        self._current_speed = self._ramp_toward(
            self._current_speed,
            self.GetTargetSpeed(player),
            linear_step,
        )
```

Note: `engines_offline` is computed lower in the function (in the angular block) but used here (linear block). Move the `engines_offline =` lines + the imports up to just before "# 2. Linear speed ramp" so the variable is available for both blocks. Final layout for the relevant section:

```python
        # Disabled-engines gate: read once, applied to both linear and
        # angular ramps. Spec §4.1.
        from engine.appc.subsystems import _is_offline
        from engine.appc.ship_motion import DISABLED_ENGINE_DRAG_FRACTION
        engines_offline = _is_offline(self._get_ies(player))

        # 2. Linear speed ramp toward target at MaxAccel rate.
        linear_step = self._max_accel(player) * dt
        if engines_offline:
            linear_step *= DISABLED_ENGINE_DRAG_FRACTION
        self._current_speed = self._ramp_toward(
            self._current_speed,
            self.GetTargetSpeed(player),
            linear_step,
        )

        # 3. Angular rates: held keys set a per-axis target rate; current rate
        #    ramps toward target at MaxAngularAccel.
        # ... (existing comment block kept verbatim)
        ang_rate    = self._angular_rate(player)
        ang_step    = self._angular_accel(player) * dt
        if engines_offline:
            ang_step *= DISABLED_ENGINE_DRAG_FRACTION
        pitch_target = 0.0
        yaw_target   = 0.0
        roll_target  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target -= ang_rate
        # ... (all six existing key checks unchanged)

        if engines_offline:
            pitch_target = 0.0
            yaw_target = 0.0
            roll_target = 0.0
        # ... (existing _ramp_toward calls follow)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_engines_disabled_clamps_throttle.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 6: Run the player-control regression suite**

Run: `uv run pytest tests/host/test_player_control_hardpoints.py tests/host/test_player_control.py -v`
Expected: all PASS — healthy IES rotation math unchanged.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_engines_disabled_clamps_throttle.py
git commit -m "feat(host_loop): disabled-engines gate clamps player angular thrust

_PlayerControl.apply clamps pitch/yaw/roll targets to 0 and scales ramp
step by DISABLED_ENGINE_DRAG_FRACTION when IES offline. Linear ramp
also drag-scaled. Spec §4.1."
```

---

### Task 5: Engines integration test — end-to-end decay & recovery

**Files:**
- Test: `tests/integration/test_engines_disabled_decays_velocity.py`

This is a pure-test task; no production code changes.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_engines_disabled_decays_velocity.py`:

```python
"""Engines-disabled gate end-to-end: ship at full impulse, damage IES to
disable, observe velocity decay, repair, observe recovery. Exercises the
shared _is_offline predicate through ship_motion._step_ship_motion."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import (
    _step_ship_motion, DISABLED_ENGINE_DRAG_FRACTION,
)


def test_disabled_engines_decay_velocity_then_repair_recovers():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies._disabled_percentage = 0.5

    ship._speed_setpoint = (
        6.3, TGPoint3(0.0, 1.0, 0.0),
        PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )

    # ── 1. Healthy: ramp to full impulse over a few seconds.
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3

    # ── 2. Disable IES; verify gate engaged.
    ies.SetCondition(10.0)
    assert ies.IsDisabled() == 1

    # ── 3. Tick 1 second; current_speed decays at drag-fraction rate.
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    decay = 6.3 - ship._current_speed
    expected_decay = 1.5 * DISABLED_ENGINE_DRAG_FRACTION  # 0.15 m/s
    assert abs(decay - expected_decay) < 1e-3, \
        f"expected ~{expected_decay} decay, got {decay}"

    # ── 4. Repair; verify gate releases.
    ies.SetCondition(100.0)
    assert ies.IsDisabled() == 0
    speed_at_repair = ship._current_speed

    # ── 5. Tick 1 second; ramp resumes at MaxAccel rate.
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    recovery = ship._current_speed - speed_at_repair
    # Healthy MaxAccel 1.5 vs drag-rate 0.15 — must be at least 10× faster.
    assert recovery > expected_decay * 5, \
        f"expected fast recovery, got {recovery} m/s gain"
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_engines_disabled_decays_velocity.py -v`
Expected: PASS — exercises the full damage→decay→repair→recovery cycle.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_engines_disabled_decays_velocity.py
git commit -m "test(integration): engines-disabled end-to-end decay + recovery

Builds a Galaxy ship, ramps to full impulse, disables IES via SetCondition,
verifies drag-fraction decay, repairs, verifies full-rate recovery."
```

---

### Task 6: Weapons gate — `WeaponSystem.StartFiring` + `PhaserSystem.StartFiring`

**Files:**
- Modify: `engine/appc/subsystems.py` — gates in `WeaponSystem.StartFiring` (line 899) and `PhaserSystem.StartFiring` (line 1107)
- Test: `tests/unit/test_weapons_disabled_blocks_fire.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_weapons_disabled_blocks_fire.py`:

```python
"""Disabled weapon system → StartFiring is a no-op. Parent-aggregator
predicate from Project 2: all children disabled => parent disabled.
A half-crippled system (one healthy bank) still fires the healthy bank
via the existing per-emitter retry."""
from engine.appc.subsystems import (
    PhaserSystem, PhaserBank, WeaponSystem,
    TorpedoSystem, TorpedoTube, PulseWeaponSystem, PulseWeapon,
)


def _bank(name, max_charge=5.0, charge=5.0, min_firing=3.0,
          max_damage=1.0, max_damage_distance=1000.0,
          max_condition=100.0, condition=100.0,
          disabled_percentage=0.25):
    b = PhaserBank(name)
    b._max_charge = max_charge
    b._charge_level = charge
    b._min_firing_charge = min_firing
    b._max_damage = max_damage
    b._max_damage_distance = max_damage_distance
    b._max_condition = max_condition
    b._condition = condition
    b._disabled_percentage = disabled_percentage
    return b


def _target(world_x=0.0, world_y=100.0, world_z=0.0):
    """Minimal target stub straight ahead of the ship (model-Y forward).

    Positioned on +Y so PhaserBank's default emitter direction (model-Y
    via the property pipeline, or the open-arc fallback when GetDirection
    is absent) doesn't reject the aim during arc-gate checks."""
    class _T:
        def GetWorldLocation(self):
            from engine.appc.math import TGPoint3
            return TGPoint3(world_x, world_y, world_z)
        def IsDead(self): return False
    return _T()


def _firing_phaser_system():
    """A PhaserSystem turned on with four child banks; parent ship set."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    for i in range(4):
        sys_.AddChildSubsystem(_bank(f"Bank{i}"))
    ship.SetPhaserSystem(sys_)
    return ship, sys_


def test_phaser_system_all_children_disabled_blocks_startfiring():
    ship, sys_ = _firing_phaser_system()
    target = _target()
    # Disable every child.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0  # 10 <= 0.25 * 100 = 25
    assert sys_.IsDisabled() == 1

    sys_.StartFiring(target=target)
    # No bank should have transitioned to firing.
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
    assert sys_._currently_firing == []


def test_phaser_system_one_healthy_child_still_fires():
    """Aggregator semantics: at least one healthy child => parent NOT
    disabled, so StartFiring works and the healthy bank fires."""
    ship, sys_ = _firing_phaser_system()
    target = _target()
    for i in range(3):
        sys_.GetWeapon(i)._condition = 10.0  # disabled
    # Bank3 stays at condition 100
    assert sys_.IsDisabled() == 0  # parent still enabled
    sys_.StartFiring(target=target)
    # SingleFire defaults to 0 on PhaserSystem unless set; check that
    # at least one bank flipped to firing.
    firing_idxs = [i for i in range(4) if sys_.GetWeapon(i).IsFiring() == 1]
    assert len(firing_idxs) >= 1


def test_phaser_system_repair_restores_firing():
    ship, sys_ = _firing_phaser_system()
    target = _target()
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    sys_.StartFiring(target=target)
    assert sys_._currently_firing == []

    # Repair one child; parent re-enabled.
    sys_.GetWeapon(0)._condition = 100.0
    assert sys_.IsDisabled() == 0
    sys_.StartFiring(target=target)
    assert len(sys_._currently_firing) >= 1


def test_weapon_system_base_startfiring_gates_on_offline():
    """Cover the base WeaponSystem.StartFiring used by TorpedoSystem,
    PulseWeaponSystem, TractorBeamSystem. PhaserSystem overrides the
    method, so we exercise a non-phaser parent here."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    sys_ = PulseWeaponSystem("Pulse")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    # Build one disabled pulse-weapon child.
    child = PulseWeapon("PW0")
    child._max_condition = 100.0
    child._condition = 10.0
    child._disabled_percentage = 0.25
    sys_.AddChildSubsystem(child)
    ship.SetPulseWeaponSystem(sys_) if hasattr(ship, "SetPulseWeaponSystem") else setattr(ship, "_pulse_weapon_system", sys_)

    assert sys_.IsDisabled() == 1
    # StartFiring should be a no-op.
    sys_.StartFiring()
    assert sys_._currently_firing == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py -v`
Expected: at least `test_phaser_system_all_children_disabled_blocks_startfiring` and `test_weapon_system_base_startfiring_gates_on_offline` FAIL — the gates don't exist yet.

- [ ] **Step 3: Add the gate to `WeaponSystem.StartFiring` (subsystems.py line 899)**

Locate `class WeaponSystem(PoweredSubsystem):` and its `def StartFiring`. The current code (line 899) starts:

```python
    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn():
            return
        n = self.GetNumWeapons()
```

Insert the offline gate immediately after `IsOn()` check:

```python
    def StartFiring(self, target=None, offset=None) -> None:
        if not self.IsOn():
            return
        # Disabled-weapons gate: when every child reports disabled (Project 2
        # aggregation), the parent IsDisabled is 1 — block fire. Spec §4.2.
        if _is_offline(self):
            return
        n = self.GetNumWeapons()
```

- [ ] **Step 4: Add the gate to `PhaserSystem.StartFiring` (subsystems.py around line 1107)**

Locate `class PhaserSystem(WeaponSystem):` `def StartFiring`. Current code (around line 1107):

```python
    def StartFiring(self, target=None, offset=None) -> None:
        """Dispatch — fires the next eligible PhaserBank.
        ...
        """
        if not self.IsOn() or target is None:
            return
        ship = self.GetParentShip()
```

Insert the offline gate immediately after the `IsOn() or target is None` check:

```python
    def StartFiring(self, target=None, offset=None) -> None:
        """Dispatch — fires the next eligible PhaserBank.
        ...
        """
        if not self.IsOn() or target is None:
            return
        # Disabled-weapons gate: parent aggregates child IsDisabled (Project 2).
        # When all banks are disabled the parent flips disabled and we bail.
        # Spec §4.2.
        if _is_offline(self):
            return
        ship = self.GetParentShip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Run the existing weapon-system regression tests**

Run: `uv run pytest tests/unit/test_weapon_system_aggregation.py tests/unit/test_arc_gate.py -v`
Expected: all PASS — aggregator semantics and per-emitter arc gating unchanged.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_weapons_disabled_blocks_fire.py
git commit -m "feat(subsystems): disabled-weapons gate blocks StartFiring

WeaponSystem.StartFiring + PhaserSystem.StartFiring early-return when
_is_offline(self) — i.e. parent aggregator reports all children
disabled. Half-crippled systems still fire healthy banks via existing
per-emitter loop. Spec §4.2."
```

---

### Task 7: Weapons gate — `PhaserSystem.retry_held_fire` mid-burst stop

**Files:**
- Modify: `engine/appc/subsystems.py` — `PhaserSystem.retry_held_fire` (around line 1125)
- Test: extend `tests/unit/test_weapons_disabled_blocks_fire.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_weapons_disabled_blocks_fire.py`:

```python
def test_retry_held_fire_stops_on_offline_mid_burst():
    """LBUTTON held, system fires, then all children flip disabled
    mid-burst: retry_held_fire calls StopFiring (clears _fire_held)."""
    ship, sys_ = _firing_phaser_system()
    target = _target()
    sys_.StartFiring(target=target)
    assert sys_._fire_held is True

    # All children flip disabled mid-burst.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    assert sys_.IsDisabled() == 1

    sys_.retry_held_fire()
    # Held state cleared, no banks firing.
    assert sys_._fire_held is False
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py::test_retry_held_fire_stops_on_offline_mid_burst -v`
Expected: FAIL — retry doesn't gate on offline.

- [ ] **Step 3: Add the gate to `retry_held_fire`**

Locate `PhaserSystem.retry_held_fire` (subsystems.py line 1125). Current code starts:

```python
    def retry_held_fire(self) -> None:
        """Re-attempt firing while LBUTTON is held.  ...
        """
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
```

Insert the offline gate immediately after `IsOn()`:

```python
    def retry_held_fire(self) -> None:
        """Re-attempt firing while LBUTTON is held.  ...
        """
        if not self._fire_held or self._held_target is None:
            return
        if not self.IsOn():
            return
        # Disabled-weapons gate: system flipped disabled mid-burst —
        # stop firing cleanly (clears _fire_held + walks _currently_firing
        # to call bank.StopFiring on each). Spec §4.2.
        if _is_offline(self):
            self.StopFiring()
            return
        ship = self.GetParentShip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_weapons_disabled_blocks_fire.py
git commit -m "feat(subsystems): retry_held_fire stops cleanly on mid-burst disable

PhaserSystem.retry_held_fire bails via StopFiring when parent flips
_is_offline mid-burst. Spec §4.2."
```

---

### Task 8: Weapons gate — `_advance_combat` mid-tick stop

**Files:**
- Modify: `engine/host_loop.py` — `_advance_combat` per-system block (lines 259-262)
- Test: extend `tests/unit/test_weapons_disabled_blocks_fire.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_weapons_disabled_blocks_fire.py`:

```python
def test_advance_combat_stops_disabled_system_mid_tick():
    """_advance_combat called against a ship whose PhaserSystem flipped
    disabled mid-frame — must call StopFiring on any active banks and
    skip the damage loop. No apply_hit invocations."""
    from engine.host_loop import _advance_combat
    from engine.appc.combat import apply_hit
    import engine.appc.combat as combat_mod

    ship, sys_ = _firing_phaser_system()
    # Target ship: needs a hull subsystem for apply_hit to be invocable
    # without errors. The gate must prevent any call entirely.
    from engine.appc.ships import ShipClass_Create
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)  # straight ahead (model-Y forward)
    sys_.StartFiring(target=target)
    # At least one bank firing.
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))

    # Disable mid-burst.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    assert sys_.IsDisabled() == 1

    # Spy on apply_hit so we can prove it's not called.
    calls = []
    original = combat_mod.apply_hit
    combat_mod.apply_hit = lambda *a, **kw: calls.append((a, kw))
    try:
        _advance_combat([ship, target], dt=1.0/60, host=None,
                        ship_instances=None)
    finally:
        combat_mod.apply_hit = original

    assert calls == []
    # All banks stopped.
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py::test_advance_combat_stops_disabled_system_mid_tick -v`
Expected: FAIL — `_advance_combat` walks banks without checking parent offline.

- [ ] **Step 3: Add the gate to `_advance_combat` in `engine/host_loop.py`**

Locate `_advance_combat` (line 217). The phaser-tick block (lines 259-262):

```python
    for ship in ships_list:
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
            continue
        # While LBUTTON is held, re-fire banks that recharged above the
```

Add the offline gate immediately after `if sys_ is None: continue`:

```python
    for ship in ships_list:
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
            continue
        # Disabled-weapons gate: parent aggregates child IsDisabled. When
        # the system flips disabled mid-tick (incoming hit during the
        # previous frame's damage routing), stop any active banks and
        # skip the damage loop for this ship. Spec §4.2.
        from engine.appc.subsystems import _is_offline
        if _is_offline(sys_):
            sys_.StopFiring()
            continue
        # While LBUTTON is held, re-fire banks that recharged above the
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_weapons_disabled_blocks_fire.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Run the broader combat regression**

Run: `uv run pytest tests/unit/test_apply_hit_routing.py tests/integration/test_close_range_combat_motion.py -v`
Expected: PASS — healthy-ship combat path unaffected.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_weapons_disabled_blocks_fire.py
git commit -m "feat(host_loop): _advance_combat stops disabled phaser system mid-tick

When a ship's PhaserSystem flips _is_offline between ticks, the combat
loop calls StopFiring on the parent and skips the per-bank damage loop.
In-flight torpedoes still propagate (launch-and-forget). Spec §4.2."
```

---

### Task 9: Shield generator gate — `ShieldSubsystem.Update` skip-when-offline

**Files:**
- Modify: `engine/appc/subsystems.py` — `ShieldSubsystem.Update` (line 1706)
- Test: `tests/unit/test_shield_generator_disabled_stops_regen.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_shield_generator_disabled_stops_regen.py`:

```python
"""Disabled shield generator → Update(dt) skips per-face regen entirely
without mutating _charge_per_second. Repair restores regen at original
rates. ApplyDamage still drains the face (drain is regen-independent)."""
from engine.appc.subsystems import ShieldSubsystem


def _generator(condition=100.0, max_condition=100.0, disabled_percentage=0.75):
    """A six-face shield generator with all faces at max."""
    s = ShieldSubsystem("ShieldGen")
    s._max_condition = max_condition
    s._condition = condition
    s._disabled_percentage = disabled_percentage
    for f in range(s.NUM_SHIELDS):
        s.SetMaxShields(f, 1000.0)
        s.SetShieldChargePerSecond(f, 50.0)
    # Drain front face so regen has somewhere to go.
    s.SetCurrentShields(s.FRONT_SHIELDS, 500.0)
    return s


def test_healthy_generator_regens():
    s = _generator()
    s.Update(dt=1.0)
    # 500 + 50*1 = 550, clamped to 1000 max
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 550.0


def test_disabled_generator_skips_regen():
    s = _generator()
    s.SetCondition(10.0)  # 10 <= 0.75 * 100 = 75 -> disabled
    assert s.IsDisabled() == 1
    s.Update(dt=1.0)
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 500.0


def test_destroyed_generator_skips_regen():
    s = _generator()
    s.SetCondition(0.0)
    assert s.IsDestroyed() == 1
    s.Update(dt=1.0)
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 500.0


def test_disabled_generator_preserves_charge_per_second():
    """Gate is read-time: the stored regen rates are not mutated.
    Repair restores regen at the original values."""
    s = _generator()
    s.SetCondition(10.0)
    s.Update(dt=1.0)
    assert s.GetShieldChargePerSecond(s.FRONT_SHIELDS) == 50.0
    # Repair.
    s.SetCondition(100.0)
    assert s.IsDisabled() == 0
    s.Update(dt=1.0)
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 550.0


def test_disabled_generator_still_takes_damage():
    """ApplyDamage is independent of Update — drain still works."""
    s = _generator()
    s.SetCondition(10.0)
    overflow = s.ApplyDamage(s.FRONT_SHIELDS, 200.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 300.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_shield_generator_disabled_stops_regen.py -v`
Expected: `test_disabled_generator_skips_regen`, `test_destroyed_generator_skips_regen`, `test_disabled_generator_preserves_charge_per_second` FAIL — Update regens regardless of offline state.

- [ ] **Step 3: Add the gate to `ShieldSubsystem.Update`**

Locate `ShieldSubsystem.Update` (subsystems.py line 1706). Current code:

```python
    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.
        """
        dt = float(dt)
        for f in range(self.NUM_SHIELDS):
            mx = self._max_shields[f]
            if mx == 0.0:
                continue
            new = self._current_shields[f] + self._charge_per_second[f] * dt
            if new > mx:
                new = mx
            self._current_shields[f] = new
```

Modify to add the offline early-return at function entry:

```python
    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.

        Disabled-generator gate (Project 5 §4.4): when _is_offline(self),
        skip the whole loop. _charge_per_second values are NOT mutated;
        repair restores regen at the original rates on the next call.
        """
        if _is_offline(self):
            return
        dt = float(dt)
        for f in range(self.NUM_SHIELDS):
            mx = self._max_shields[f]
            if mx == 0.0:
                continue
            new = self._current_shields[f] + self._charge_per_second[f] * dt
            if new > mx:
                new = mx
            self._current_shields[f] = new
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_shield_generator_disabled_stops_regen.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Run the existing shield regression tests**

Run: `uv run pytest tests/unit -k "shield" -v`
Expected: all PASS — healthy regen unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_shield_generator_disabled_stops_regen.py
git commit -m "feat(subsystems): disabled shield generator skips Update regen

ShieldSubsystem.Update early-returns when _is_offline(self). Damage via
ApplyDamage remains independent. Stored _charge_per_second values are
not mutated; repair restores original rates. Spec §4.4."
```

---

### Task 10: Sensors gate — `player_sensors_offline` helper + UI gates in `ship_display_panel.py`

**Files:**
- Modify: `engine/ui/ship_display_panel.py` — add `player_sensors_offline()`; modify `_affiliation_for` (line 321) and `_resolve_ship_for_role` (line 301)
- Test: `tests/unit/test_sensors_disabled_blanks_target_ui.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sensors_disabled_blanks_target_ui.py`:

```python
"""Player sensors disabled → UI blanks target rows / forces UNKNOWN
affiliation / drops the target-role panel. Player-role panel is
unaffected; you always know who you are."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.core.game import (
    Game, Episode, Mission, _set_current_game,
)
from engine.ui.ship_display_panel import (
    ROLE_PLAYER, ROLE_TARGET,
    _resolve_ship_for_role, _affiliation_for, player_sensors_offline,
)


def _setup(enemy_in_group=True):
    App._reset_target_menu_singleton()
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)

    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors._disabled_percentage = 0.5
    player.SetSensorSubsystem(sensors)
    game.SetPlayer(player)
    _set_current_game(game)

    enemy = ShipClass_Create("BirdOfPrey")
    enemy.SetName("Enemy")
    if enemy_in_group:
        mission.GetEnemyGroup().AddName("Enemy")
    player.SetTarget(enemy)
    return game, player, enemy, sensors, mission


def teardown_function(_):
    _set_current_game(None)


def test_helper_returns_false_when_sensors_healthy():
    _setup()
    assert player_sensors_offline() is False


def test_helper_returns_true_when_sensors_disabled():
    _, _, _, sensors, _ = _setup()
    sensors.SetCondition(10.0)  # below 0.5 * 100 = 50
    assert player_sensors_offline() is True


def test_helper_returns_true_when_sensors_destroyed():
    _, _, _, sensors, _ = _setup()
    sensors.SetCondition(0.0)
    assert player_sensors_offline() is True


def test_resolve_target_returns_none_when_sensors_offline():
    _, player, enemy, sensors, _ = _setup()
    # Healthy: target resolves.
    assert _resolve_ship_for_role(ROLE_TARGET) is enemy
    sensors.SetCondition(10.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is None
    # Player role still works.
    assert _resolve_ship_for_role(ROLE_PLAYER) is player


def test_resolve_target_restored_after_repair():
    _, _, enemy, sensors, _ = _setup()
    sensors.SetCondition(10.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is None
    sensors.SetCondition(100.0)
    assert _resolve_ship_for_role(ROLE_TARGET) is enemy


def test_affiliation_returns_unknown_when_sensors_offline():
    _, player, enemy, sensors, _ = _setup(enemy_in_group=True)
    # Healthy: classifies as ENEMY.
    assert _affiliation_for(enemy, player) == "ENEMY"
    sensors.SetCondition(10.0)
    assert _affiliation_for(enemy, player) == "UNKNOWN"


def test_player_self_affiliation_unaffected_by_sensors_offline():
    """ship is player short-circuits before the sensor gate."""
    _, player, _, sensors, _ = _setup()
    sensors.SetCondition(10.0)
    assert _affiliation_for(player, player) == "FRIENDLY"


def test_affiliation_restored_after_repair():
    _, player, enemy, sensors, _ = _setup(enemy_in_group=True)
    sensors.SetCondition(10.0)
    assert _affiliation_for(enemy, player) == "UNKNOWN"
    sensors.SetCondition(100.0)
    assert _affiliation_for(enemy, player) == "ENEMY"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py -v`
Expected: FAIL — `player_sensors_offline` doesn't exist; affiliation and target-resolve don't gate.

- [ ] **Step 3: Add the helper + UI gates to `engine/ui/ship_display_panel.py`**

Add the helper function at module scope (place it just below the existing module-level helpers like `_current_episode`, somewhere around line 295):

```python
def player_sensors_offline() -> bool:
    """True iff the player's own SensorSubsystem reports IsDisabled or
    IsDestroyed. Used to gate target-list visibility, IFF colouring, and
    target-panel resolution. Spec §4.3."""
    from engine.appc.subsystems import _is_offline
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game else None
    if player is None:
        return False
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    return _is_offline(sensors)
```

Modify `_resolve_ship_for_role` (line 301). Current code:

```python
def _resolve_ship_for_role(role: str):
    """Returns the ship the panel renders for, or None for the no-target
    empty state.

    The SDK gates target display behind SensorSubsystem.IsObjectKnown()
    ...
    """
    player = _get_player()
    if player is None:
        return None
    if role == ROLE_PLAYER:
        return player
    target = player.GetTarget() if hasattr(player, "GetTarget") else None
    return target
```

Insert the offline gate just before the `target = ...` line:

```python
def _resolve_ship_for_role(role: str):
    """Returns the ship the panel renders for, or None for the no-target
    empty state.

    The SDK gates target display behind SensorSubsystem.IsObjectKnown()
    ...

    Project 5 sensor gate (§4.3): when the player's sensors are offline,
    target-role resolves to None (panel goes to empty state). Player
    role is unaffected — you always know who you are.
    """
    player = _get_player()
    if player is None:
        return None
    if role == ROLE_PLAYER:
        return player
    if player_sensors_offline():
        return None
    target = player.GetTarget() if hasattr(player, "GetTarget") else None
    return target
```

Modify `_affiliation_for` (line 321). Current code:

```python
def _affiliation_for(ship, player) -> str:
    """Map ship affiliation to the snapshot string used by the CSS layer."""
    try:
        if player is None or ship is None:
            return "NONE"
        if ship is player:
            return "FRIENDLY"
        episode = _current_episode()
        mission = episode.GetCurrentMission() if episode else None
        ...
```

Insert the offline gate right after the `ship is player` short-circuit (so player-self stays FRIENDLY):

```python
def _affiliation_for(ship, player) -> str:
    """Map ship affiliation to the snapshot string used by the CSS layer.

    Project 5 sensor gate (§4.3): when the player's own sensors are
    offline, every non-player ship maps to UNKNOWN. Player-self
    short-circuits FRIENDLY above this check so you can always see who
    you are.
    """
    try:
        if player is None or ship is None:
            return "NONE"
        if ship is player:
            return "FRIENDLY"
        if player_sensors_offline():
            return "UNKNOWN"
        episode = _current_episode()
        mission = episode.GetCurrentMission() if episode else None
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Run the existing ship_display_panel regression**

Run: `uv run pytest tests/ -k "ship_display" -v`
Expected: all PASS — healthy-sensor affiliation and target-resolution unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/unit/test_sensors_disabled_blanks_target_ui.py
git commit -m "feat(ship_display_panel): player-sensors-offline gate

Adds player_sensors_offline() helper. _affiliation_for forces UNKNOWN
for non-player ships when player sensors offline (player-self stays
FRIENDLY via short-circuit). _resolve_ship_for_role returns None for
target role when offline (player role unaffected). Spec §4.3."
```

---

### Task 11: Sensors gate — `update_target_list_visibility` hides every row when player offline

**Files:**
- Modify: `engine/appc/subsystems.py` — `update_target_list_visibility` (line 1898)
- Test: extend `tests/unit/test_sensors_disabled_blanks_target_ui.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sensors_disabled_blanks_target_ui.py`:

```python
def test_update_visibility_hides_all_rows_when_sensors_offline():
    """When player sensors offline, every row in the target menu goes
    invisible — radar and target-list views read this via row.IsVisible()."""
    from engine.appc.subsystems import update_target_list_visibility

    _, player, enemy, sensors, _ = _setup()
    target_menu = App.STTargetMenu_CreateW("Targets")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)  # well within 30000 range
    target_menu.RebuildShipMenu(enemy)
    update_target_list_visibility(target_menu, [enemy], player,
                                  range_units=30000.0)
    assert target_menu.GetObjectEntry(enemy).IsVisible() == 1

    # Disable sensors; next update flips visibility to 0.
    sensors.SetCondition(10.0)
    update_target_list_visibility(target_menu, [enemy], player,
                                  range_units=30000.0)
    assert target_menu.GetObjectEntry(enemy).IsVisible() == 0


def test_update_visibility_restores_after_sensor_repair():
    from engine.appc.subsystems import update_target_list_visibility

    _, player, enemy, sensors, _ = _setup()
    target_menu = App.STTargetMenu_CreateW("Targets")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)
    target_menu.RebuildShipMenu(enemy)

    sensors.SetCondition(10.0)
    update_target_list_visibility(target_menu, [enemy], player,
                                  range_units=30000.0)
    assert target_menu.GetObjectEntry(enemy).IsVisible() == 0

    sensors.SetCondition(100.0)
    update_target_list_visibility(target_menu, [enemy], player,
                                  range_units=30000.0)
    assert target_menu.GetObjectEntry(enemy).IsVisible() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py::test_update_visibility_hides_all_rows_when_sensors_offline tests/unit/test_sensors_disabled_blanks_target_ui.py::test_update_visibility_restores_after_sensor_repair -v`
Expected: FAIL — `update_target_list_visibility` doesn't gate on player sensors.

- [ ] **Step 3: Add the gate to `update_target_list_visibility`**

Locate the function in `engine/appc/subsystems.py` (line 1898). Current code:

```python
def update_target_list_visibility(target_menu, ships, player, range_units: float = 30000.0) -> None:
    """Flip STSubsystemMenu.SetVisible/SetNotVisible on each row based
    on the ship's distance from the player.
    ...
    """
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
    for ship in ships:
        row = target_menu.GetObjectEntry(ship)
        if row is None or not isinstance(row, STSubsystemMenu):
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - px, sy - py, sz - pz
        if dx * dx + dy * dy + dz * dz <= range_sq:
            row.SetVisible()
        else:
            row.SetNotVisible()
```

Insert the offline gate. The cleanest place is at function entry — check if the *player's* sensors are offline (i.e. `_is_offline(player.GetSensorSubsystem())`); if so, set every matching row invisible and return:

```python
def update_target_list_visibility(target_menu, ships, player, range_units: float = 30000.0) -> None:
    """Flip STSubsystemMenu.SetVisible/SetNotVisible on each row based
    on the ship's distance from the player.
    ...

    Project 5 sensor gate (§4.3): when the player's own SensorSubsystem
    reports _is_offline, every row in the menu goes invisible regardless
    of range. The radar panel and target-list view both filter on
    row.IsVisible(), so contacts disappear automatically.
    """
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    # Player-sensors-offline gate: blank every row, then return.
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if _is_offline(sensors):
        for ship in ships:
            row = target_menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            row.SetNotVisible()
        return
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
    for ship in ships:
        row = target_menu.GetObjectEntry(ship)
        if row is None or not isinstance(row, STSubsystemMenu):
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - px, sy - py, sz - pz
        if dx * dx + dy * dy + dz * dz <= range_sq:
            row.SetVisible()
        else:
            row.SetNotVisible()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Run the existing sensor-visibility regression**

Run: `uv run pytest tests/unit/test_sensor_visibility.py -v`
Expected: all PASS — healthy-sensor range-gated visibility unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_sensors_disabled_blanks_target_ui.py
git commit -m "feat(subsystems): update_target_list_visibility blanks all rows when player sensors offline

When _is_offline(player.GetSensorSubsystem()), every row in the target
menu is flipped invisible regardless of range. Radar and target-list
views read row.IsVisible() and automatically blank contacts. Spec §4.3."
```

---

### Task 12: Visual smoke verification

**Files:** none — this is a manual verification step recorded in the spec.

- [ ] **Step 1: Build and launch**

Run: `cmake -B build -S . && cmake --build build -j && ./build/dauntless`
Expected: build succeeds; game launches into the default mission.

- [ ] **Step 2: Verify the enemy-engines gate visually**

In-game:
1. Target an enemy ship (left-side panel shows the enemy).
2. Fire phasers until the enemy's **Engines** row on the target ShipDisplay panel goes red.
3. Observe: enemy ship's velocity visibly decays — its position changes slow toward zero over ~10 seconds.

Record observation in the spec's §5.3 if behaviour differs from expectation.

- [ ] **Step 3: Verify the enemy-weapons gate visually**

Continue firing on the same enemy:
1. Damage continues; **Weapons** row eventually goes red.
2. Observe: enemy stops firing back. No incoming phaser beams from this ship in the next ~5 seconds.

- [ ] **Step 4: Verify the player-sensors gate visually**

Take incoming hits yourself until:
1. Your own **Sensors** row goes red on your ShipDisplay panel.
2. Observe: target list (right side / sensor panel) blanks. Radar contacts disappear. The target-role ShipDisplay panel goes to its empty state. Your own player-role panel keeps showing your name/affiliation.

- [ ] **Step 5: Verify the player-shield-generator gate visually**

Continue taking hits until:
1. Your **Shield Generator** row goes red.
2. Observe: any depleted face stays at the depleted level — it does not regen between hits.

- [ ] **Step 6: Verify repair flow (optional / deferred)**

Repair lifting is currently testable only via unit tests (direct `SetCondition` mutation). The production `RepairSubsystem` is still `pass`. If a debug REPL or hotkey is available, force-lift one subsystem's condition and observe the gate releasing; otherwise this step is documented as deferred per the spec's open questions.

- [ ] **Step 7: Record observations in the spec**

If any observed behaviour diverges from expectation, append a "Visual smoke findings" subsection to `docs/superpowers/specs/2026-06-02-subsystem-failure-consequences-design.md` documenting the divergence.

- [ ] **Step 8: Commit visual-smoke completion (no code change required)**

If changes were necessary (only if smoke uncovered bugs), commit them per the relevant earlier task's pattern. Otherwise no commit is needed for this task.

---

## Final regression sweep

After all tasks complete:

- [ ] **Run a focused regression covering every gate's domain**

Run:

```
uv run pytest \
  tests/unit/test_is_offline_helper.py \
  tests/unit/test_engines_disabled_clamps_throttle.py \
  tests/unit/test_weapons_disabled_blocks_fire.py \
  tests/unit/test_shield_generator_disabled_stops_regen.py \
  tests/unit/test_sensors_disabled_blanks_target_ui.py \
  tests/integration/test_engines_disabled_decays_velocity.py \
  tests/unit/test_weapon_system_aggregation.py \
  tests/unit/test_sensor_visibility.py \
  tests/unit/test_apply_hit_routing.py \
  tests/host/test_player_control_hardpoints.py \
  -v
```

Expected: all PASS.

- [ ] **Do NOT run the full suite** (`uv run pytest`) — per `CLAUDE.md` memory, it OOMs the host.

---

## Done state

When every checkbox above is checked:

- Five capability gates respect `IsDisabled()` / `IsDestroyed()` predicates of their target subsystems.
- Gates auto-release when condition is lifted via direct mutation, repair scripting, or (eventually) a real `RepairSubsystem`.
- New tests cover gate-applied and gate-released states for each capability, plus the integration end-to-end engines flow.
- Visual smoke documented: engines, weapons, sensors, and shield-generator gates verified in the default mission.
- Spec open question recorded: `RepairSubsystem` is still `pass`; follow-up Project 6 proposed for real repair flow.

This closes Project 5 of the combat damage pipeline roadmap. The original symptom ("fire a phaser, nothing visibly happens") is fully resolved end-to-end.
