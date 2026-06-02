"""Per-tick kinematic integrator for AI-controlled ships.

Reads each ship's `_speed_setpoint` (written via SetSpeed / SetImpulse)
and ramps `_current_speed` toward the target speed at the ship's
MaxAccel (with FALLBACK_MAX_ACCEL for ships without a populated
ImpulseEngineSubsystem). Position advances along the world-space
direction each tick.

Reads each ship's `_target_angular_velocity_setpoint` and ramps
`_current_angular_velocity` per axis toward it at the ship's
MaxAngularAccel (same fallback rule). The per-tick rotation delta
is built as pitch/yaw/roll matrices and pre-multiplied into the
existing world rotation — matches the `_PlayerControl.apply`
body-frame-delta convention.

Ships whose setpoints are still None are skipped entirely so the
player ship (driven by `engine/host_loop.py:_PlayerControl` directly
on the transform) is left alone.
"""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass

# Match _PlayerControl.FALLBACK_MAX_ACCEL in engine/host_loop.py:613.
# Used when a ship has no ImpulseEngineSubsystem with non-zero MaxSpeed
# (i.e. test ships built with ShipClass() directly, before SetupProperties).
FALLBACK_MAX_ACCEL = 1.0e9

# When the impulse engine subsystem is disabled or destroyed,
# _step_ship_motion clamps target speed and angular targets to zero
# and scales the ramp step by this fraction so velocity decays
# gracefully instead of instantly. 0.1 = ~10× the normal stop time.
# Spec: docs/superpowers/specs/2026-06-02-subsystem-failure-consequences-design.md §2.
DISABLED_ENGINE_DRAG_FRACTION = 0.1

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

    # ── Integrate position ───────────────────────────────────────────
    if ship._current_speed != 0.0:
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(
            p.x + world_dir.x * ship._current_speed * dt,
            p.y + world_dir.y * ship._current_speed * dt,
            p.z + world_dir.z * ship._current_speed * dt,
        )

    # Publish velocity so SDK consumers (Intercept's brake-aware control,
    # Defensive, etc.) reading GetVelocityTG().Length() see real numbers.
    # Zero speed publishes zero velocity — caller-visible state must
    # match the integrator's actual progress this tick.
    ship.SetVelocity(TGPoint3(
        world_dir.x * ship._current_speed,
        world_dir.y * ship._current_speed,
        world_dir.z * ship._current_speed,
    ))

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
    cav = ship._current_angular_velocity
    cav.x = _ramp_toward(cav.x, target_av_x, ang_step)
    cav.y = _ramp_toward(cav.y, target_av_y, ang_step)
    cav.z = _ramp_toward(cav.z, target_av_z, ang_step)

    # ── Integrate rotation ───────────────────────────────────────────
    # Same convention as _PlayerControl.apply step 4: column-vector
    # matrices, body-frame delta POST-multiplies (R · D); see
    # CLAUDE.md ↦ "Rotation matrix convention". Pitch (X) → yaw (Z) →
    # roll (Y) Euler order. Body axes map: X=right, Y=forward, Z=up;
    # cav components are per-axis rates around those body axes.
    if cav.x or cav.y or cav.z:
        R = ship.GetWorldRotation()
        R_pitch = TGMatrix3(); R_pitch.MakeRotation(cav.x * dt, _X_AXIS)
        R_yaw   = TGMatrix3(); R_yaw.MakeRotation(cav.z * dt, _Z_AXIS)
        R_roll  = TGMatrix3(); R_roll.MakeRotation(cav.y * dt, _Y_AXIS)
        delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
        R = R.MultMatrix(delta)
        ship.SetMatrixRotation(R)
