"""Per-tick kinematic integrator scaffold for AI-controlled ships.

This is the no-op scaffold (Task 1). Tasks 2 (linear motion) and 3
(angular motion) fill in the integrator body. The public surface
(`tick_all_ship_motion`) and the helpers (`_ramp_toward`, `_max_accel`,
`_max_angular_accel`) are in place so the per-tick wiring in
`engine/core/loop.py` is exercised end-to-end, and the
no-setpoint guard at the top of `_step_ship_motion` keeps the player
ship (driven by `engine/host_loop.py:_PlayerControl`) untouched.
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

    Skips entirely when no setpoint has ever been written so the
    player ship (driven via `_PlayerControl`, not setpoints) and
    freshly-spawned non-AI props are left alone.
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
