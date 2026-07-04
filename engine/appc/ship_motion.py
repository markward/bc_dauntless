"""Per-tick kinematic integrator for AI-controlled ships.

Reads each ship's `_speed_setpoint` / `_target_angular_velocity_setpoint`
and ramps `_current_speed` / `_current_angular_velocity` toward them under
limits scaled by the ship's online impulse-pod fraction f (see
`impulse_online_fraction`). At f in (0, 1] flight runs under f-scaled
MaxSpeed / MaxAccel / MaxAngularVelocity / MaxAngularAccel with a
non-braking `_cap_keep` clamp; ships with no populated ImpulseEngineSubsystem
fall back to FALLBACK_MAX_ACCEL snap semantics. At f == 0 the ship drifts on
inertia: the world-space velocity is snapshotted into `_drift_velocity` and
position integrates by that frozen vector while residual angular momentum
still tumbles the hull (velocity decoupled from facing, no thrust, no decay).

The per-tick rotation delta is built as pitch/yaw/roll matrices and
post-multiplied into the world rotation (`_integrate_rotation`) — matches the
`_PlayerControl.apply` body-frame-delta convention.

Ships whose setpoints are still None are skipped entirely — the player ship
under manual control (driven by `engine/host_loop.py:_PlayerControl` directly
on the transform) and freshly-spawned props never enter the integrator. When a
helm AI is installed on the player (Orbit Planet, All Stop, ...), the AI
writes setpoints and the player integrates here like any other ship;
_PlayerControl.apply() yields for exactly that case (gated on player.GetAI())
so the two integrators never fight over the transform.
"""
from dataclasses import dataclass

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass

# Match _PlayerControl.FALLBACK_MAX_ACCEL in engine/host_loop.py:613.
# Used when a ship has no ImpulseEngineSubsystem with non-zero MaxSpeed
# (i.e. test ships built with ShipClass() directly, before SetupProperties).
FALLBACK_MAX_ACCEL = 1.0e9

# Reverse-engineered from original BC ground-truth measurements
# (Galaxy + Shuttle at impulse 9 from rest, 2026-06-03): the impulse
# ramp is dv/dt = min(MaxAccel, (target − v) / τ) with τ = 1 s,
# ship-independent. Below the crossover gap (= MaxAccel·τ) the step is
# the SDK MaxAccel; above, the closure rate dominates and the velocity
# gap to target decays exponentially with τ.
BC_IMPULSE_TAU = 1.0

# Body-frame axes — matches _PlayerControl convention.
_X_AXIS = TGPoint3(1.0, 0.0, 0.0)
_Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
_Z_AXIS = TGPoint3(0.0, 0.0, 1.0)

# Per-tick effective motion limits at engine-fraction f. has_linear /
# has_angular are False for fallback ships (no populated IES limits); the
# integrator then uses FALLBACK_MAX_ACCEL snap semantics for that axis group.
@dataclass(frozen=True)
class _EffectiveMotion:
    has_linear: bool
    max_speed: float
    max_accel: float
    has_angular: bool
    max_ang_vel: float
    max_ang_accel: float


def _effective_motion(ship, f: float) -> "_EffectiveMotion":
    """Resolve a ship's impulse limits scaled by online-fraction f."""
    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    raw_speed = ies.GetMaxSpeed() if ies is not None else 0.0
    raw_ang_vel = ies.GetMaxAngularVelocity() if ies is not None else 0.0
    has_lin = raw_speed > 0.0
    has_ang = raw_ang_vel > 0.0
    accel = ies.GetMaxAccel() if has_lin else 0.0
    ang_accel = ies.GetMaxAngularAccel() if has_ang else 0.0
    return _EffectiveMotion(
        has_linear=has_lin,
        max_speed=f * raw_speed if has_lin else 0.0,
        max_accel=f * accel if (has_lin and accel > 0.0) else 0.0,
        has_angular=has_ang,
        max_ang_vel=f * raw_ang_vel if has_ang else 0.0,
        max_ang_accel=f * ang_accel if (has_ang and ang_accel > 0.0) else 0.0,
    )


def _cap_keep(commanded: float, current: float, cap: float) -> float:
    """Limit |commanded| to max(cap, |current|), preserving commanded's sign.

    Caps future acceleration without force-braking a value already above the
    cap (spec 2026-06-10-impulse-engine-degradation-design.md §3 'caps limit
    future acceleration; they do not force-brake').
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


def _step_ship_motion(ship, dt: float) -> None:
    """Advance one ship's transform by one tick.

    Skips entirely when no setpoint has ever been written so the manually
    flown player ship (driven via `_PlayerControl`, which yields to this
    integrator whenever a helm AI is installed) and freshly-spawned non-AI
    props are left alone. Otherwise: at engine-fraction f in (0, 1] flies under f-scaled
    limits with a non-braking cap; at f == 0 drifts on inertia (frozen
    world-space velocity + residual angular momentum). Spec
    docs/superpowers/specs/2026-06-10-impulse-engine-degradation-design.md.
    """
    # An active in-system-warp transit overrides normal setpoint motion:
    # the ship cruises straight at the warp drop point until arrival.
    if getattr(ship, "_insystem_warp_transit", None) is not None:
        _step_in_system_warp(ship, dt)
        return

    sp = getattr(ship, "_speed_setpoint", None)
    av = getattr(ship, "_target_angular_velocity_setpoint", None)
    if sp is None and av is None:
        return

    # -- Commanded speed + world-space direction --
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

    # -- Total loss -> inertial drift --
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

    # -- Powered flight: clear any drift snapshot, re-seed speed --
    drift = getattr(ship, "_drift_velocity", None)
    if drift is not None:
        ship._current_speed = drift.Length()
        ship._drift_velocity = None

    em = _effective_motion(ship, f)

    # -- Linear ramp toward (capped) target --
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

    # -- Angular ramp toward (capped) target --
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


def _step_in_system_warp(ship, dt: float) -> None:
    """Advance one tick of an in-system-warp transit (see
    ShipClass.InSystemWarp). Straight-line cruise toward
    (target − unit_dir · drop_distance) at IN_SYSTEM_WARP_SPEED_FACTOR ×
    the ship's impulse MaxSpeed. On arrival the transit clears and
    `_warp_consumed` latches so the AI body resumes normal motion; the
    published velocity drops back to the ship's pre-warp `_current_speed`
    along the approach line (the warp is "instant transit", not a change
    of impulse state). Rotation is frozen during the cruise — the facing
    gate ensured the nose is already on the warp vector."""
    from engine.appc.ships import ShipClass
    target, drop = ship._insystem_warp_transit
    target_loc = (
        target.GetWorldLocation()
        if hasattr(target, "GetWorldLocation") else None
    )
    if target_loc is None:
        ship._insystem_warp_transit = None
        ship._warp_consumed = True
        return
    p = ship.GetTranslate()
    dx = target_loc.x - p.x
    dy = target_loc.y - p.y
    dz = target_loc.z - p.z
    d = (dx * dx + dy * dy + dz * dz) ** 0.5
    if d <= max(float(drop), 1e-9):
        ship._insystem_warp_transit = None
        ship._warp_consumed = True
        return
    ux, uy, uz = dx / d, dy / d, dz / d

    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    base = ies.GetMaxSpeed() if ies is not None else 0.0
    if base <= 0.0:
        base = ShipClass.IN_SYSTEM_WARP_FALLBACK_BASE
    warp_speed = ShipClass.IN_SYSTEM_WARP_SPEED_FACTOR * base

    remaining = d - float(drop)
    step = warp_speed * dt
    if step >= remaining:
        # Arrival: place exactly on the drop edge, end the transit.
        ship.SetTranslateXYZ(
            target_loc.x - ux * float(drop),
            target_loc.y - uy * float(drop),
            target_loc.z - uz * float(drop),
        )
        ship._insystem_warp_transit = None
        ship._warp_consumed = True
        s = ship._current_speed
        ship.SetVelocity(TGPoint3(ux * s, uy * s, uz * s))
    else:
        ship.SetTranslateXYZ(p.x + ux * step, p.y + uy * step, p.z + uz * step)
        ship.SetVelocity(TGPoint3(ux * warp_speed, uy * warp_speed, uz * warp_speed))


def _integrate_rotation(ship, dt: float) -> None:
    """Apply ship._current_angular_velocity to the world rotation for one
    tick. Column-vector matrices, body-frame delta POST-multiplies (R . D);
    pitch (X) -> yaw (Z) -> roll (Y) Euler order. See CLAUDE.md -> 'Rotation
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
