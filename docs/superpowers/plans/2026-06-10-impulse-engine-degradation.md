# Impulse-Engine Degradation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make damage to a ship's individual impulse-engine pods proportionally degrade its flight limits, and make a ship with all pods offline drift on inertia until a pod is repaired.

**Architecture:** A shared `impulse_online_fraction(ies)` helper turns "online pods / total pods" into a fraction `f`. Two integrators — `engine/appc/ship_motion.py` (AI) and `engine/host_loop.py:_PlayerControl` (player) — scale all four kinematic limits by `f`, enforce a non-braking "keep-rule" cap, and at `f == 0` switch to inertial drift using a frozen world-space velocity snapshot. The old `_is_offline(master) → drag-to-stop` model is deleted.

**Tech Stack:** Python 3, pytest. Math via `engine/appc/math.py` (`TGPoint3`, `TGMatrix3`). No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-06-10-impulse-engine-degradation-design.md`](../specs/2026-06-10-impulse-engine-degradation-design.md)

---

## Background the engineer needs

- **Pods are children of the master.** `ship.GetImpulseEngineSubsystem()` returns the master `ImpulseEngineSubsystem`. Its targetable engine pods are `master.GetChildSubsystem(i)` for `i in range(master.GetNumChildSubsystems())`. A Galaxy has 3 pods. `ShipClass_Create("Galaxy")` materialises them (verified by `tests/unit/test_setup_properties_engine_pods.py`).
- **`_is_offline(sub)`** lives in `engine/appc/subsystems.py` and returns `True` iff `sub.IsDisabled()` or `sub.IsDestroyed()`. A subsystem is disabled when its condition drops below `MaxCondition * DisabledPercentage`. To disable a pod in a test: `pod.SetCondition(0.0)`. To re-enable: `pod.SetCondition(pod.GetMaxCondition())`.
- **Powered velocity follows facing.** Both integrators compute velocity as `forward * current_speed` recomputed each tick, so a powered ship always flies along its nose. **Drift must decouple this** — freeze the world-space velocity vector so a tumbling ship coasts straight.
- **Fallback ships.** Bare `ShipClass()` fixtures have no populated IES (`GetMaxSpeed() == 0`). They must keep today's "snap to target with `FALLBACK_MAX_ACCEL`" behaviour. `impulse_online_fraction` returns `1.0` for them, and the integrators branch to fallback when the IES has no real limits.
- **`TGPoint3` math.** `.Length()` returns magnitude; `.Unitize()` normalises in place; `.MultMatrixLeft(R)` does `v = R · v` in place. Plain attributes pickle via `__dict__` (ships define no `__getstate__`), so a `_drift_velocity` attribute persists across save/load for free — **no save/load task needed.**
- **Run focused tests only.** Per project memory, the full pytest suite OOMs the host. Always run specific files/tests as shown in each step.

## File Structure

- **`engine/appc/subsystems.py`** — add `impulse_online_fraction(ies)` beside `_is_offline` (~line 368).
- **`engine/appc/ship_motion.py`** — add shared helpers `_effective_motion`, `_cap_keep`, `_asymptote_step`; rewrite `_step_ship_motion`; delete `DISABLED_ENGINE_DRAG_FRACTION`, `_linear_step_magnitude`, `_max_accel`, `_max_angular_accel`.
- **`engine/host_loop.py`** — rewrite `_PlayerControl.apply` + `GetTargetSpeed`; add `_drift_velocity` to `__init__`; import shared helpers from `ship_motion`.
- **Tests** — new `tests/unit/test_impulse_online_fraction.py`, `tests/unit/test_impulse_degradation_motion.py`, `tests/host/test_player_impulse_degradation.py`; rewrite `tests/integration/test_engines_disabled_decays_velocity.py` and `tests/unit/test_engines_disabled_clamps_throttle.py`.

---

## Task 1: `impulse_online_fraction` helper

**Files:**
- Modify: `engine/appc/subsystems.py` (insert after `_is_offline`, ~line 379)
- Test: `tests/unit/test_impulse_online_fraction.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_impulse_online_fraction.py`:

```python
"""impulse_online_fraction: online-pod ratio that drives flight degradation."""
from engine.appc.subsystems import (
    impulse_online_fraction, ImpulseEngineSubsystem, ShipSubsystem,
)


def _pod(name, max_condition=100.0, disabled_pct=0.5):
    p = ShipSubsystem(name)
    p.SetMaxCondition(max_condition)
    p.SetDisabledPercentage(disabled_pct)
    p.SetCondition(max_condition)
    return p


def _master_with_pods(n):
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxCondition(100.0)
    ies.SetDisabledPercentage(0.5)
    ies.SetCondition(100.0)
    for i in range(n):
        ies.AddChildSubsystem(_pod("pod%d" % i))
    return ies


def test_none_ies_returns_full():
    assert impulse_online_fraction(None) == 1.0


def test_no_pods_returns_full():
    assert impulse_online_fraction(_master_with_pods(0)) == 1.0


def test_all_pods_online_returns_full():
    assert impulse_online_fraction(_master_with_pods(4)) == 1.0


def test_three_of_four_offline_returns_quarter():
    ies = _master_with_pods(4)
    for i in range(3):
        ies.GetChildSubsystem(i).SetCondition(0.0)
    assert impulse_online_fraction(ies) == 0.25


def test_all_pods_offline_returns_zero():
    ies = _master_with_pods(3)
    for i in range(3):
        ies.GetChildSubsystem(i).SetCondition(0.0)
    assert impulse_online_fraction(ies) == 0.0


def test_master_offline_forces_zero_even_with_online_pods():
    ies = _master_with_pods(4)        # all pods healthy
    ies.SetCondition(0.0)             # but master itself disabled
    assert impulse_online_fraction(ies) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_impulse_online_fraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'impulse_online_fraction'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/subsystems.py`, immediately after the `_is_offline` function (ends ~line 379), add:

```python
def impulse_online_fraction(ies) -> float:
    """Fraction in [0, 1] of a ship's impulse engine pods that are online.

    `ies` is the master ImpulseEngineSubsystem (or None). A pod is offline
    iff _is_offline(pod) (disabled OR destroyed). Returns:
      - 1.0 when ies is None or has no child pods (fallback ships);
      - 0.0 when the master itself is offline;
      - online_pods / total_pods otherwise.
    """
    if ies is None:
        return 1.0
    if _is_offline(ies):
        return 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        return 1.0
    online = sum(
        1 for i in range(n) if not _is_offline(ies.GetChildSubsystem(i))
    )
    return online / float(n)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_impulse_online_fraction.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_impulse_online_fraction.py
git commit -m "feat(impulse): add impulse_online_fraction pod-ratio helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Shared motion helpers (`_effective_motion`, `_cap_keep`, `_asymptote_step`)

These pure helpers are used by both integrators. `_effective_motion` returns `f`-scaled limits plus per-axis "has real limits" flags so fallback ships keep snap semantics. `_cap_keep` implements the non-braking cap. `_asymptote_step` is the BC rate-limited ramp step.

**Files:**
- Modify: `engine/appc/ship_motion.py` (add helpers near top, after the constants block ~line 46)
- Test: `tests/unit/test_impulse_degradation_motion.py` (helper tests only this task)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_impulse_degradation_motion.py`:

```python
"""Effective-limit + keep-rule helpers for impulse degradation."""
from engine.appc.ship_motion import (
    _effective_motion, _cap_keep, _asymptote_step,
)
from engine.appc.ships import ShipClass_Create


def _galaxy():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    return ship


def test_effective_motion_scales_all_four_limits():
    ship = _galaxy()
    em = _effective_motion(ship, 0.5)
    assert em.has_linear is True
    assert abs(em.max_speed - 3.15) < 1e-9
    assert abs(em.max_accel - 0.75) < 1e-9
    assert em.has_angular is True
    assert abs(em.max_ang_vel - 0.14) < 1e-9
    assert abs(em.max_ang_accel - 0.06) < 1e-9


def test_effective_motion_full_fraction_is_base():
    ship = _galaxy()
    em = _effective_motion(ship, 1.0)
    assert abs(em.max_speed - 6.3) < 1e-9
    assert abs(em.max_accel - 1.5) < 1e-9


def test_effective_motion_fallback_ship_has_no_real_limits():
    # bare ship: IES exists but MaxSpeed/MaxAngularVelocity are 0
    from engine.appc.ships import ShipClass
    ship = ShipClass("bare")
    em = _effective_motion(ship, 1.0)
    assert em.has_linear is False
    assert em.has_angular is False


def test_cap_keep_caps_acceleration_below_cap():
    # current under cap → commanded clamped to cap
    assert _cap_keep(10.0, 1.0, 3.0) == 3.0


def test_cap_keep_does_not_brake_above_cap():
    # already above cap → keep current, never dragged down by the cap
    assert _cap_keep(10.0, 5.0, 3.0) == 5.0


def test_cap_keep_allows_commanded_slowdown_above_cap():
    # pilot eases off below current (but still above cap) → allowed
    assert _cap_keep(4.0, 5.0, 3.0) == 4.0


def test_cap_keep_preserves_reverse_sign():
    assert _cap_keep(-10.0, 0.0, 3.0) == -3.0


def test_asymptote_step_rate_limited():
    # large gap → limited by accel
    assert abs(_asymptote_step(1.5, 100.0, 1.0 / 60) - 1.5 / 60) < 1e-9


def test_asymptote_step_closes_small_gap():
    # small gap (|gap|/tau < accel) → limited by gap/tau (tau == 1.0)
    assert abs(_asymptote_step(1.5, 0.3, 1.0 / 60) - 0.3 / 60) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_impulse_degradation_motion.py -v`
Expected: FAIL — `ImportError: cannot import name '_effective_motion'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/ship_motion.py`, after the body-frame axis constants (`_Z_AXIS`, ~line 46) add:

```python
from collections import namedtuple

# Per-tick effective motion limits at engine-fraction f. has_linear /
# has_angular are False for fallback ships (no populated IES limits); the
# integrator then uses FALLBACK_MAX_ACCEL snap semantics for that axis group.
_EffectiveMotion = namedtuple(
    "_EffectiveMotion",
    "has_linear max_speed max_accel has_angular max_ang_vel max_ang_accel",
)


def _effective_motion(ship, f: float) -> "_EffectiveMotion":
    """Resolve a ship's impulse limits scaled by online-fraction f."""
    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    has_lin = ies is not None and ies.GetMaxSpeed() > 0.0
    has_ang = ies is not None and ies.GetMaxAngularVelocity() > 0.0
    max_speed = f * ies.GetMaxSpeed() if has_lin else 0.0
    accel = ies.GetMaxAccel() if has_lin else 0.0
    max_accel = f * accel if (has_lin and accel > 0.0) else 0.0
    max_ang_vel = f * ies.GetMaxAngularVelocity() if has_ang else 0.0
    ang_accel = ies.GetMaxAngularAccel() if has_ang else 0.0
    max_ang_accel = f * ang_accel if (has_ang and ang_accel > 0.0) else 0.0
    return _EffectiveMotion(
        has_lin, max_speed, max_accel, has_ang, max_ang_vel, max_ang_accel,
    )


def _cap_keep(commanded: float, current: float, cap: float) -> float:
    """Limit |commanded| to max(cap, |current|), preserving commanded's sign.

    Caps future acceleration without force-braking a value already above the
    cap (spec §3 'caps limit future acceleration; they do not force-brake').
    """
    limit = cap if cap > abs(current) else abs(current)
    if commanded > limit:
        return limit
    if commanded < -limit:
        return -limit
    return commanded


def _asymptote_step(accel: float, gap: float, dt: float) -> float:
    """BC rate-limited asymptote step: min(accel, |gap|/tau) · dt."""
    return min(accel, abs(gap) / BC_IMPULSE_TAU) * dt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_impulse_degradation_motion.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_motion.py tests/unit/test_impulse_degradation_motion.py
git commit -m "feat(impulse): add effective-limit, keep-rule, and ramp-step helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Rewrite the AI integrator (`_step_ship_motion`)

Replace the old `engines_offline` drag block with: proportional scaling for `0 < f <= 1`, and inertial drift for `f == 0`. Drift snapshots the world velocity vector on entry and re-seeds `_current_speed` on exit.

**Files:**
- Modify: `engine/appc/ship_motion.py` — rewrite `_step_ship_motion` (lines 98-191); delete `_linear_step_magnitude` (72-87), `_max_accel` (64-69), `_max_angular_accel` (90-95). **Keep** `DISABLED_ENGINE_DRAG_FRACTION` defined for now (host_loop still imports it; removed in Task 5).
- Test: `tests/unit/test_impulse_degradation_motion.py` (append AI-integrator tests)

- [ ] **Step 1: Write the failing tests (append)**

Append to `tests/unit/test_impulse_degradation_motion.py`:

```python
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ship_motion import _step_ship_motion


def _disable_pods(ship, count):
    ies = ship.GetImpulseEngineSubsystem()
    for i in range(count):
        ies.GetChildSubsystem(i).SetCondition(0.0)


def _fwd_setpoint(ship, speed):
    ship._speed_setpoint = (
        speed, TGPoint3(0.0, 1.0, 0.0), PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )


def test_partial_loss_caps_top_speed_proportionally():
    # Galaxy has 3 pods. Disable 1 → f = 2/3 → top speed ~= 6.3 * 2/3.
    ship = _galaxy()
    _disable_pods(ship, 1)
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 20):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3 * (2.0 / 3.0)) < 1e-2


def test_partial_loss_does_not_brake_ship_already_above_cap():
    # Reach full speed healthy, then lose a pod. Keep-rule: speed is held,
    # not dragged down to the new lower cap.
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3
    _disable_pods(ship, 1)          # cap drops to 4.2, ship is at 6.3
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3  # unchanged, not braked


def test_total_loss_drifts_at_constant_velocity():
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    speed_before = ship._current_speed
    pos_a = ship.GetTranslate()
    _disable_pods(ship, 3)          # all pods offline → drift
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    # velocity magnitude unchanged across 10 s of drift (no decay)
    v = ship.GetVelocityTG()
    assert abs(v.Length() - speed_before) < 1e-6
    pos_b = ship.GetTranslate()
    travelled = ((pos_b.x - pos_a.x) ** 2 + (pos_b.y - pos_a.y) ** 2
                 + (pos_b.z - pos_a.z) ** 2) ** 0.5
    assert travelled > 0.0


def test_drift_velocity_decoupled_from_facing_while_tumbling():
    # Ship drifting along +Y, with residual yaw. Path must stay straight in
    # world space even though the nose rotates.
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    ship._target_angular_velocity_setpoint = TGPoint3(0.0, 0.0, 0.2)  # yaw
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    _disable_pods(ship, 3)          # drift with residual yaw
    p0 = ship.GetTranslate()
    _step_ship_motion(ship, 1.0 / 60)
    p1 = ship.GetTranslate()
    # one drift tick later, do many more; direction of travel must not curve.
    dir0 = (p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
    for _ in range(60 * 3):
        _step_ship_motion(ship, 1.0 / 60)
    p2 = ship.GetTranslate()
    pN = ship.GetTranslate()  # noqa: F841 (clarity)
    # Late step direction:
    _step_ship_motion(ship, 1.0 / 60)
    p3 = ship.GetTranslate()
    dirN = (p3.x - p2.x, p3.y - p2.y, p3.z - p2.z)
    # normalise + dot ~ 1.0 (parallel) despite the ship having yawed
    import math
    def _unit(d):
        m = math.sqrt(sum(c * c for c in d))
        return tuple(c / m for c in d)
    u0, uN = _unit(dir0), _unit(dirN)
    dot = sum(a * b for a, b in zip(u0, uN))
    assert dot > 0.999


def test_repair_one_pod_resumes_powered_flight():
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    _disable_pods(ship, 3)
    for _ in range(60 * 2):
        _step_ship_motion(ship, 1.0 / 60)
    assert getattr(ship, "_drift_velocity", None) is not None
    # repair pod 0
    ies = ship.GetImpulseEngineSubsystem()
    pod = ies.GetChildSubsystem(0)
    pod.SetCondition(pod.GetMaxCondition())
    _step_ship_motion(ship, 1.0 / 60)
    assert ship._drift_velocity is None
    assert ship._current_speed > 0.0   # re-seeded from drift speed
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_impulse_degradation_motion.py -v -k "partial_loss or total_loss or drift or repair_one"`
Expected: FAIL — old `_step_ship_motion` drags to a stop / has no `_drift_velocity`.

- [ ] **Step 3: Rewrite `_step_ship_motion`**

In `engine/appc/ship_motion.py`, delete `_max_accel` (64-69), `_linear_step_magnitude` (72-87), `_max_angular_accel` (90-95), and replace `_step_ship_motion` (98-191) with:

```python
def _step_ship_motion(ship, dt: float) -> None:
    """Advance one ship's transform by one tick.

    Skips entirely when no setpoint has ever been written so the player ship
    (driven via `_PlayerControl`) and freshly-spawned non-AI props are left
    alone. Otherwise: at engine-fraction f in (0, 1] flies under f-scaled
    limits with a non-braking cap; at f == 0 drifts on inertia (frozen
    world-space velocity + residual angular momentum). Spec
    2026-06-10-impulse-engine-degradation-design.md.
    """
    sp = getattr(ship, "_speed_setpoint", None)
    av = getattr(ship, "_target_angular_velocity_setpoint", None)
    if sp is None and av is None:
        return

    # ── Commanded speed + world-space direction ──────────────────────
    if sp is None:
        commanded_speed = 0.0
        world_dir = TGPoint3(0.0, 1.0, 0.0)
    else:
        commanded_speed, direction, frame = sp
        if frame == PhysicsObjectClass.DIRECTION_MODEL_SPACE:
            world_dir = TGPoint3(direction.x, direction.y, direction.z)
            world_dir.MultMatrixLeft(ship.GetWorldRotation())
        else:
            world_dir = TGPoint3(direction.x, direction.y, direction.z)
        world_dir.Unitize()

    from engine.appc.subsystems import impulse_online_fraction
    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    f = impulse_online_fraction(ies)

    # ── Total loss → inertial drift ──────────────────────────────────
    if f <= 0.0:
        drift = getattr(ship, "_drift_velocity", None)
        if drift is None:
            drift = TGPoint3(
                world_dir.x * ship._current_speed,
                world_dir.y * ship._current_speed,
                world_dir.z * ship._current_speed,
            )
            ship._drift_velocity = drift
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(
            p.x + drift.x * dt, p.y + drift.y * dt, p.z + drift.z * dt,
        )
        ship.SetVelocity(TGPoint3(drift.x, drift.y, drift.z))
        _integrate_rotation(ship, dt)   # residual angular momentum, held
        return

    # ── Powered flight: clear any drift snapshot, re-seed speed ──────
    drift = getattr(ship, "_drift_velocity", None)
    if drift is not None:
        ship._current_speed = drift.Length()
        ship._drift_velocity = None

    em = _effective_motion(ship, f)

    # ── Linear ramp toward (capped) target ───────────────────────────
    if em.has_linear:
        target_speed = _cap_keep(commanded_speed, ship._current_speed, em.max_speed)
        accel = em.max_accel if em.max_accel > 0.0 else FALLBACK_MAX_ACCEL
        step = _asymptote_step(accel, target_speed - ship._current_speed, dt)
    else:
        target_speed = commanded_speed
        step = FALLBACK_MAX_ACCEL * dt
    ship._current_speed = _ramp_toward(ship._current_speed, target_speed, step)

    if ship._current_speed != 0.0:
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(
            p.x + world_dir.x * ship._current_speed * dt,
            p.y + world_dir.y * ship._current_speed * dt,
            p.z + world_dir.z * ship._current_speed * dt,
        )
    ship.SetVelocity(TGPoint3(
        world_dir.x * ship._current_speed,
        world_dir.y * ship._current_speed,
        world_dir.z * ship._current_speed,
    ))

    # ── Angular ramp toward (capped) target ──────────────────────────
    if av is None:
        tx = ty = tz = 0.0
    else:
        tx, ty, tz = av.x, av.y, av.z
    cav = ship._current_angular_velocity
    if em.has_angular:
        tx = _cap_keep(tx, cav.x, em.max_ang_vel)
        ty = _cap_keep(ty, cav.y, em.max_ang_vel)
        tz = _cap_keep(tz, cav.z, em.max_ang_vel)
        aa = em.max_ang_accel if em.max_ang_accel > 0.0 else FALLBACK_MAX_ACCEL
        ang_step = aa * dt
    else:
        ang_step = FALLBACK_MAX_ACCEL * dt
    cav.x = _ramp_toward(cav.x, tx, ang_step)
    cav.y = _ramp_toward(cav.y, ty, ang_step)
    cav.z = _ramp_toward(cav.z, tz, ang_step)

    _integrate_rotation(ship, dt)


def _integrate_rotation(ship, dt: float) -> None:
    """Apply ship._current_angular_velocity to the world rotation for one
    tick. Column-vector matrices, body-frame delta POST-multiplies (R · D);
    pitch (X) → yaw (Z) → roll (Y) Euler order. See CLAUDE.md ↦ 'Rotation
    matrix convention'."""
    cav = ship._current_angular_velocity
    if cav.x or cav.y or cav.z:
        R = ship.GetWorldRotation()
        R_pitch = TGMatrix3(); R_pitch.MakeRotation(cav.x * dt, _X_AXIS)
        R_yaw   = TGMatrix3(); R_yaw.MakeRotation(cav.z * dt, _Z_AXIS)
        R_roll  = TGMatrix3(); R_roll.MakeRotation(cav.y * dt, _Y_AXIS)
        delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
        R = R.MultMatrix(delta)
        ship.SetMatrixRotation(R)
```

Note: `_integrate_rotation` is the old inline rotation block (lines 184-191) extracted so the drift path can reuse it. Update the module docstring's reference to `_max_accel`/`FALLBACK_MAX_ACCEL` only if it now reads wrong — leave `FALLBACK_MAX_ACCEL` and `BC_IMPULSE_TAU` constants in place.

- [ ] **Step 4: Run the new tests + the existing motion suite**

Run: `uv run pytest tests/unit/test_impulse_degradation_motion.py tests/unit/test_ship_motion.py tests/unit/test_turn_directions.py -v`
Expected: PASS for all new tests and the existing motion/turn tests (fallback snap semantics preserved). The old `tests/integration/test_engines_disabled_decays_velocity.py` and `tests/unit/test_engines_disabled_clamps_throttle.py` will still FAIL — they are rewritten in Task 5.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_motion.py tests/unit/test_impulse_degradation_motion.py
git commit -m "feat(impulse): proportional degradation + inertial drift in AI integrator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Rewrite the player integrator (`_PlayerControl`)

Mirror Task 3 for the keyboard-driven player ship. Add `_drift_velocity` state; remove the `_is_offline → 0.0` early-out in `GetTargetSpeed`; scale limits by `f`; drift at `f == 0`.

**Files:**
- Modify: `engine/host_loop.py` — `_PlayerControl.__init__` (add `_drift_velocity`), `GetTargetSpeed` (711-735), `apply` (777-907). Keep `_max_accel`/`_angular_rate`/`_angular_accel` methods but they are no longer used by `apply` — delete them to avoid dead code (verify no other caller via grep in Step 3).
- Test: `tests/host/test_player_impulse_degradation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_player_impulse_degradation.py`:

```python
"""Player-ship impulse degradation + drift through _PlayerControl.apply."""
from engine.host_loop import _PlayerControl
from engine.appc.ships import ShipClass_Create


class _FakeKeys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4; KEY_Q = 5; KEY_E = 6
    KEY_R = 7; KEY_0 = 8
    KEY_1 = 11; KEY_2 = 12; KEY_3 = 13; KEY_4 = 14; KEY_5 = 15
    KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19


class _FakeHost:
    """Minimal host: no keys held, no edges, unless primed."""
    def __init__(self):
        self.keys = _FakeKeys()
        self._pressed = set()
        self._state = set()
    def key_pressed(self, code): return code in self._pressed
    def key_state(self, code): return code in self._state
    def press(self, code): self._pressed.add(code)
    def clear_edges(self): self._pressed.clear()


def _galaxy_player():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    return ship


def _disable_pods(ship, count):
    ies = ship.GetImpulseEngineSubsystem()
    for i in range(count):
        ies.GetChildSubsystem(i).SetCondition(0.0)


def test_partial_loss_caps_player_top_speed():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)            # full impulse
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    _disable_pods(ship, 1)           # f = 2/3
    for _ in range(60 * 20):
        ctrl.apply(ship, 1.0 / 60, h)
    assert abs(ctrl._current_speed - 6.3 * (2.0 / 3.0)) < 1e-2


def test_total_loss_player_drifts_constant_speed():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    for _ in range(60 * 10):
        ctrl.apply(ship, 1.0 / 60, h)
    speed_before = ctrl._current_speed
    p0 = ship.GetTranslate()
    _disable_pods(ship, 3)           # drift
    for _ in range(60 * 5):
        ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is not None
    p1 = ship.GetTranslate()
    travelled = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2
                 + (p1.z - p0.z) ** 2) ** 0.5
    # 5 s of drift at ~speed_before GU/s
    assert abs(travelled - speed_before * 5.0) < speed_before * 0.05


def test_repair_resumes_player_powered_flight():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    for _ in range(60 * 10):
        ctrl.apply(ship, 1.0 / 60, h)
    _disable_pods(ship, 3)
    for _ in range(60 * 2):
        ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is not None
    ies = ship.GetImpulseEngineSubsystem()
    pod = ies.GetChildSubsystem(0)
    pod.SetCondition(pod.GetMaxCondition())
    ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is None
    assert ctrl._current_speed > 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/host/test_player_impulse_degradation.py -v`
Expected: FAIL — `AttributeError: _PlayerControl object has no attribute '_drift_velocity'` / old drag behaviour.

- [ ] **Step 3: Rewrite the player integrator**

First confirm the now-unused methods have no external callers:

Run: `grep -rn "_max_accel\|_angular_rate\|_angular_accel" engine/ tests/ | grep -i player`
Expected: only definitions/uses inside `_PlayerControl`. (Tests like `test_player_control_hardpoints.py` may assert on rates via `apply` behaviour, not these methods directly — if any test calls them directly, keep the method.)

In `engine/host_loop.py`:

(a) Add `_drift_velocity` to `__init__` (after line 702 `self._warp_boost = False`):

```python
        self._drift_velocity = None   # TGPoint3 while drifting (f==0), else None
```

(b) Replace `GetTargetSpeed` (711-735) — drop the `_is_offline → 0.0` early-out (drift is handled in `apply` now; the cap is enforced by the keep-rule, not by zeroing the target):

```python
    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into the throttle-commanded target speed
        against the ship's BASE MaxSpeed (unscaled). Degradation caps are
        applied by the keep-rule clamp in apply(), so a ship above its
        reduced cap is not braked. Forward speed is multiplied by
        WARP_BOOST_FACTOR when the in-system warp toggle is on (Ctrl+I);
        reverse is unaffected.
        """
        ies = self._get_ies(player)
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
        boost = self.WARP_BOOST_FACTOR if self._warp_boost else 1.0
        if max_speed > 0.0:
            if self.impulse_level >= 0:
                return (self.impulse_level / 9.0) * max_speed * boost
            return -self.REVERSE_FRACTION * max_speed
        if self.impulse_level >= 0:
            return self.impulse_level * self.IMPULSE_UNIT * boost
        return self.impulse_level * self.IMPULSE_UNIT
```

(c) Delete the `_max_accel`, `_angular_rate`, `_angular_accel` methods (740-762) **unless** Step 3's grep found a direct caller; if so, leave them.

(d) Replace `apply` (777-907). Keep the throttle/key-reading section (lines 783-818) verbatim, then replace everything from the disabled-engines comment (820) through the end of position integration (907) with:

```python
        # ── Engine effectiveness for this tick (spec 2026-06-10) ─────────
        from engine.appc.subsystems import impulse_online_fraction
        from engine.appc.ship_motion import (
            _effective_motion, _cap_keep, _asymptote_step,
        )
        from engine.appc.math import TGMatrix3, TGPoint3
        X_AXIS = TGPoint3(1.0, 0.0, 0.0)
        Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
        Z_AXIS = TGPoint3(0.0, 0.0, 1.0)

        ies = self._get_ies(player)
        f = impulse_online_fraction(ies)

        # ── Total loss → inertial drift ─────────────────────────────────
        if f <= 0.0:
            R = player.GetWorldRotation()
            if self._drift_velocity is None:
                fwd = R.GetCol(1)
                self._drift_velocity = TGPoint3(
                    fwd.x * self._current_speed,
                    fwd.y * self._current_speed,
                    fwd.z * self._current_speed,
                )
            # residual rotation: held rates, no thrust, no decay
            pr, yr, rr = (self._current_pitch_rate, self._current_yaw_rate,
                          self._current_roll_rate)
            if pr or yr or rr:
                R_pitch = TGMatrix3(); R_pitch.MakeRotation(pr * dt, X_AXIS)
                R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yr * dt, Z_AXIS)
                R_roll  = TGMatrix3(); R_roll.MakeRotation(rr * dt, Y_AXIS)
                delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
                player.SetMatrixRotation(R.MultMatrix(delta))
            d = self._drift_velocity
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + d.x * dt, p.y + d.y * dt, p.z + d.z * dt)
            return

        # ── Powered flight: clear drift, re-seed speed ──────────────────
        if self._drift_velocity is not None:
            self._current_speed = self._drift_velocity.Length()
            self._drift_velocity = None

        em = _effective_motion(player, f)

        # Linear ramp toward (capped) target.
        commanded = self.GetTargetSpeed(player)
        if em.has_linear:
            target_speed = _cap_keep(commanded, self._current_speed, em.max_speed)
            accel = em.max_accel if em.max_accel > 0.0 else self.FALLBACK_MAX_ACCEL
            linear_step = _asymptote_step(accel, target_speed - self._current_speed, dt)
        else:
            target_speed = commanded
            linear_step = self.FALLBACK_MAX_ACCEL * dt
        self._current_speed = self._ramp_toward(
            self._current_speed, target_speed, linear_step,
        )

        # Angular: held keys → per-axis target rate, capped + ramped.
        # W=nose DOWN S=nose UP A=yaw LEFT D=yaw RIGHT Q=roll LEFT E=roll RIGHT
        if em.has_angular:
            ang_rate = em.max_ang_vel
            aa = em.max_ang_accel if em.max_ang_accel > 0.0 else self.FALLBACK_MAX_ACCEL
            ang_step = aa * dt
        else:
            ang_rate = self.TURN_RATE_RAD_PER_S
            ang_step = self.FALLBACK_MAX_ACCEL * dt
        pitch_target = 0.0; yaw_target = 0.0; roll_target = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target -= ang_rate
        if h.key_state(h.keys.KEY_S): pitch_target += ang_rate
        if h.key_state(h.keys.KEY_A): yaw_target   -= ang_rate
        if h.key_state(h.keys.KEY_D): yaw_target   += ang_rate
        if h.key_state(h.keys.KEY_Q): roll_target  += ang_rate
        if h.key_state(h.keys.KEY_E): roll_target  -= ang_rate
        if em.has_angular:
            pitch_target = _cap_keep(pitch_target, self._current_pitch_rate, em.max_ang_vel)
            yaw_target   = _cap_keep(yaw_target,   self._current_yaw_rate,   em.max_ang_vel)
            roll_target  = _cap_keep(roll_target,  self._current_roll_rate,  em.max_ang_vel)
        self._current_pitch_rate = self._ramp_toward(self._current_pitch_rate, pitch_target, ang_step)
        self._current_yaw_rate   = self._ramp_toward(self._current_yaw_rate,   yaw_target,   ang_step)
        self._current_roll_rate  = self._ramp_toward(self._current_roll_rate,  roll_target,  ang_step)
        pitch_rate = self._current_pitch_rate
        yaw_rate   = self._current_yaw_rate
        roll_rate  = self._current_roll_rate

        # Rotation integration (R · D body-frame delta; see CLAUDE.md).
        R = player.GetWorldRotation()
        if pitch_rate or yaw_rate or roll_rate:
            R_pitch = TGMatrix3(); R_pitch.MakeRotation(pitch_rate * dt, X_AXIS)
            R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yaw_rate   * dt, Z_AXIS)
            R_roll  = TGMatrix3(); R_roll.MakeRotation(roll_rate  * dt, Y_AXIS)
            delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
            R = R.MultMatrix(delta)
            player.SetMatrixRotation(R)

        # Position integration (powered: velocity follows facing).
        if self._current_speed != 0.0:
            forward = R.GetCol(1)
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * self._current_speed * dt,
                p.y + forward.y * self._current_speed * dt,
                p.z + forward.z * self._current_speed * dt,
            )
```

- [ ] **Step 4: Run the player tests + existing player-control suite**

Run: `uv run pytest tests/host/test_player_impulse_degradation.py tests/host/test_player_control_hardpoints.py tests/unit/test_player.py -v`
Expected: PASS. If `test_player_control_hardpoints.py` asserts angular onset behaviour, confirm it still holds (full-fraction `em` equals base limits, so healthy-ship behaviour is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_player_impulse_degradation.py
git commit -m "feat(impulse): proportional degradation + drift in player integrator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Remove the old drag model and rewrite its tests

Delete `DISABLED_ENGINE_DRAG_FRACTION` (now unused) and rewrite the two tests that asserted the old drag-to-stop behaviour.

**Files:**
- Modify: `engine/appc/ship_motion.py` — delete `DISABLED_ENGINE_DRAG_FRACTION` (line 41 + its comment block 36-41).
- Rewrite: `tests/integration/test_engines_disabled_decays_velocity.py` → drift semantics.
- Rewrite: `tests/unit/test_engines_disabled_clamps_throttle.py` → degradation + drift semantics.

- [ ] **Step 1: Confirm the constant is unused, then delete it**

Run: `grep -rn "DISABLED_ENGINE_DRAG_FRACTION" engine/`
Expected: only the definition in `ship_motion.py` (host_loop no longer imports it after Task 4). Delete lines 36-41 (the comment + `DISABLED_ENGINE_DRAG_FRACTION = 0.1`).

- [ ] **Step 2: Rewrite the integration test**

Replace the entire contents of `tests/integration/test_engines_disabled_decays_velocity.py` with (and rename intent — keep the filename to preserve history, or `git mv` to `test_engines_disabled_drifts.py`; this plan keeps the filename):

```python
"""All impulse pods offline → inertial drift (no decay), repair → powered.
Exercises impulse_online_fraction through ship_motion._step_ship_motion."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import _step_ship_motion


def _disable_all_pods(ies):
    for i in range(ies.GetNumChildSubsystems()):
        pod = ies.GetChildSubsystem(i)
        pod.SetCondition(0.0)


def test_all_pods_offline_drift_then_repair_recovers():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    assert ies.GetNumChildSubsystems() == 3   # Galaxy: Port/Star/Center Impulse

    ship._speed_setpoint = (
        6.3, TGPoint3(0.0, 1.0, 0.0), PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )

    # 1. Healthy: ramp to full impulse.
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3

    # 2. Disable all pods → drift.
    _disable_all_pods(ies)
    v_before = ship.GetVelocityTG().Length()

    # 3. Drift 2 s: velocity magnitude unchanged (no decay).
    for _ in range(60 * 2):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship.GetVelocityTG().Length() - v_before) < 1e-6
    assert ship._drift_velocity is not None

    # 4. Repair one pod → gate releases, powered flight resumes.
    ies.GetChildSubsystem(0).SetCondition(
        ies.GetChildSubsystem(0).GetMaxCondition())
    _step_ship_motion(ship, 1.0 / 60)
    assert ship._drift_velocity is None
    assert ship._current_speed > 0.0
```

- [ ] **Step 3: Rewrite the unit clamp test**

Open `tests/unit/test_engines_disabled_clamps_throttle.py`. It currently imports `DISABLED_ENGINE_DRAG_FRACTION` and asserts decay rates. Replace its contents with degradation + drift assertions:

```python
"""Throttle/degradation behaviour as impulse pods go offline."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import _step_ship_motion


def _galaxy():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3); ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28); ies.SetMaxAngularAccel(0.12)
    return ship, ies


def _fwd(ship, speed):
    ship._speed_setpoint = (
        speed, TGPoint3(0.0, 1.0, 0.0), PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )


def test_one_pod_offline_caps_speed_at_two_thirds():
    ship, ies = _galaxy()
    ies.GetChildSubsystem(0).SetCondition(0.0)   # 1 of 3 offline → f = 2/3
    _fwd(ship, 6.3)
    for _ in range(60 * 20):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3 * (2.0 / 3.0)) < 1e-2


def test_two_pods_offline_caps_speed_at_one_third():
    ship, ies = _galaxy()
    ies.GetChildSubsystem(0).SetCondition(0.0)
    ies.GetChildSubsystem(1).SetCondition(0.0)   # 2 of 3 offline → f = 1/3
    _fwd(ship, 6.3)
    for _ in range(60 * 20):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3 * (1.0 / 3.0)) < 1e-2


def test_all_pods_offline_drifts_not_stops():
    ship, ies = _galaxy()
    _fwd(ship, 6.3)
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    for i in range(ies.GetNumChildSubsystems()):
        ies.GetChildSubsystem(i).SetCondition(0.0)
    v = ship.GetVelocityTG().Length()
    for _ in range(60 * 3):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship.GetVelocityTG().Length() - v) < 1e-6   # drift, no stop
```

- [ ] **Step 4: Run the rewritten tests + the full impulse-feature set**

Run:
```bash
uv run pytest \
  tests/unit/test_impulse_online_fraction.py \
  tests/unit/test_impulse_degradation_motion.py \
  tests/unit/test_engines_disabled_clamps_throttle.py \
  tests/integration/test_engines_disabled_decays_velocity.py \
  tests/host/test_player_impulse_degradation.py \
  tests/unit/test_ship_motion.py \
  tests/host/test_player_control_hardpoints.py \
  -v
```
Expected: PASS across all.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_motion.py \
  tests/integration/test_engines_disabled_decays_velocity.py \
  tests/unit/test_engines_disabled_clamps_throttle.py
git commit -m "refactor(impulse): drop drag-to-stop model; tests assert drift + degradation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Regression sweep of motion-adjacent suites

Run the broader (but still focused) set of suites that touch ship motion, the player, AI driving, and subsystem state, to catch any coupling the rewrite disturbed. **Do not run the full suite** (it OOMs the host).

- [ ] **Step 1: Run the regression set**

Run:
```bash
uv run pytest \
  tests/unit/test_ship_motion.py \
  tests/unit/test_turn_directions.py \
  tests/unit/test_set_impulse_fraction.py \
  tests/unit/test_setup_properties_engine_pods.py \
  tests/unit/test_subsystems.py \
  tests/unit/test_player.py \
  tests/host/test_player_control_hardpoints.py \
  tests/integration/test_e1m1_ship_identity.py \
  -v
```
Expected: PASS. Investigate any failure against the spec before proceeding — a genuine behaviour change in healthy (f==1) flight is a bug (full-fraction must be byte-identical to pre-change behaviour).

- [ ] **Step 2: Verify no stragglers reference removed symbols**

Run: `grep -rn "DISABLED_ENGINE_DRAG_FRACTION\|_linear_step_magnitude" engine/ tests/`
Expected: no matches. If any remain, fix them (delete/replace) and re-run the relevant suite.

- [ ] **Step 3: Commit any regression fixes**

```bash
git add -A
git commit -m "test(impulse): regression sweep fixes for engine-degradation rewrite

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(If Step 1 and Step 2 were clean with nothing to commit, skip this step.)

---

## Self-Review notes

- **Spec §1 partial loss** → Tasks 3/4 scaling + Task 5 `test_one/two_pods_offline`. ✓
- **Spec §1 total loss / drift** → Tasks 3/4 drift branch + Task 5 drift tests. ✓
- **Spec §3 all four limits scale** → `_effective_motion` (Task 2) + tests. ✓
- **Spec §3 keep-rule (no force-brake)** → `_cap_keep` (Task 2) + `test_partial_loss_does_not_brake...` (Task 3). ✓
- **Spec §3 master offline → f=0** → `impulse_online_fraction` (Task 1) + `test_master_offline...`. ✓
- **Spec §3 no pods → f=1** → Task 1 + `_effective_motion` fallback path. ✓
- **Spec §3 drift exit re-seed** → Tasks 3/4 re-seed from `_drift_velocity.Length()` + repair tests. ✓
- **Spec §4.4 removed code** → Task 5 deletes `DISABLED_ENGINE_DRAG_FRACTION`; Task 3 deletes `_linear_step_magnitude`/`_max_accel`/`_max_angular_accel`; Task 4 deletes player `_max_accel`/`_angular_rate`/`_angular_accel`. ✓
- **Spec §5 save/load** → no task needed; `_drift_velocity` is a plain attr and pickles via `__dict__` (documented in Background). ✓
- **Type consistency** → `_EffectiveMotion` field names (`has_linear`, `max_speed`, `max_accel`, `has_angular`, `max_ang_vel`, `max_ang_accel`) used identically in Tasks 2/3/4. `_cap_keep(commanded, current, cap)` and `_asymptote_step(accel, gap, dt)` signatures consistent across call sites. ✓
