"""Per-tick kinematic integrator for AI-controlled ships.

Reads each ship's `_speed_setpoint` / `_target_angular_velocity_setpoint`
and ramps `_current_speed` / `_current_angular_velocity` toward them under the
impulse subsystem's LIVE limits — `GetMaxSpeed` / `GetMaxAccel` /
`GetMaxAngularVelocity` / `GetMaxAngularAccel` already carry BC's
damage-and-power derating (`impulse_output_fraction`), so the integrator does
NOT scale them again. Clamping is via the non-braking `_cap_keep`; ships with
no populated ImpulseEngineSubsystem fall back to FALLBACK_MAX_ACCEL snap
semantics. When every pod is out (`impulse_online_fraction` == 0) the ship
drifts on inertia: the world-space velocity is snapshotted into
`_drift_velocity` and position integrates by that frozen vector while residual
angular momentum still tumbles the hull (velocity decoupled from facing, no
thrust, no decay).

The per-tick rotation delta is built as pitch/yaw/roll matrices and
post-multiplied into the world rotation (`_integrate_rotation`) — matches the
`_PlayerControl.apply` body-frame-delta convention.

Ships whose setpoints are still None skip the ramp above entirely, but are
NOT otherwise untouched: only the current player (driven by
`engine/host_loop.py:_PlayerControl` directly on the transform) is left
strictly alone. Every other setpoint-less ship -- a freshly-spawned prop with
zero velocity, or one the SDK moves only with a bare SetVelocity /
SetAngularVelocity and no AI (a launched probe, E1M2's falling station) --
drifts on that scripted velocity/angular velocity via `engine.appc.drift`,
the same step a rock uses (rocks.motion.step). When a helm AI is installed
on the player (Orbit Planet, All Stop, ...), the AI writes setpoints and the
player integrates through the ramp above like any other ship;
_PlayerControl.apply() yields for exactly that case (gated on
player.GetAI()) so the two integrators never fight over the transform.

Known gap, NOT covered by the drift branch above: a ship that already HAS
an AI installed (so its tree wrote a setpoint at some earlier point in the
mission, from ordinary combat maneuvering) takes the ramp path below even
after its script later fires a bare SetVelocity/SetAngularVelocity -- the
ramp path overwrites `_velocity` from its own commanded speed every tick,
so the scripted velocity is still silently ignored. E8M2's disabled Matan
(`DisableMatan`), E7M2's JonKa, E8M1's Galor and E2M1's Karoon are all this
case: each already has an AI (`SetAI`) installed before its script sends it
spinning off with a bare SetVelocity/SetAngularVelocity. See
`engine/appc/drift.py`'s module docstring.
"""
from dataclasses import dataclass

# Module scope, NOT a per-call `import`/`from ... import` inside the
# integrator: every name below is read once per ship per tick (App and
# drift included -- the setpoint-less branch hits both every tick for
# every drifting ship), and none of them import anything from this module
# (nor from ships), so there is no cycle to break. Same fix as the one
# applied to subsystems._is_offline, which was costing 115,279 importlib
# lookups over 150 ticks at 100 ships.
import App
import math

from engine.appc import drift, native_combat, tractor, warp_flight, warp_state
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.subsystems import impulse_fractions, impulse_output_fraction
from engine.core import frame_profiler as _prof
from engine.core.ids import implements

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

# Per-tick effective motion limits. has_linear / has_angular are False for
# fallback ships (no populated IES limits); the integrator then uses
# FALLBACK_MAX_ACCEL snap semantics for that axis group.
@dataclass(frozen=True)
class _EffectiveMotion:
    has_linear: bool
    max_speed: float
    max_accel: float
    has_angular: bool
    max_ang_vel: float
    max_ang_accel: float


def _effective_motion(ship, ies=None, imp_f=None) -> "_EffectiveMotion":
    """Resolve a ship's LIVE impulse limits.

    The four getters already carry BC's derating (damaged pods x power slider,
    see subsystems.impulse_output_fraction), so there is nothing to scale here.
    Whether a ship HAS real limits is decided on the AUTHORED values: a ship
    whose engines are shot out still has a populated Galaxy hardpoint and must
    keep flying under (zeroed) real limits, not fall through to the
    FALLBACK_MAX_ACCEL snap semantics meant for ships with no engines at all.
    """
    if ies is None:
        # Callers on the per-ship path already hold the subsystem and the
        # derating fraction; re-fetching both here is a second pod walk for an
        # answer they just computed.
        getter = getattr(ship, "GetImpulseEngineSubsystem", None)
        ies = getter() if getter is not None else None
    if ies is None:
        return _EffectiveMotion(False, 0.0, 0.0, False, 0.0, 0.0)
    has_lin = ies.GetAuthoredMaxSpeed() > 0.0
    has_ang = ies.GetAuthoredMaxAngularVelocity() > 0.0

    # The four derived getters are each `authored * impulse_output_fraction(self)`
    # with the SAME argument, so calling all four recomputed that fraction four
    # times per ship per tick -- and it is not cheap: it walks every child pod
    # querying IsDisabled / GetConditionPercentage / GetMaxCondition. cProfile
    # put it at 55% of the entire ship-motion cost (1.149 s of 2.083 s over 600
    # ticks at 17 ships), called 3.76x per ship per tick.
    #
    # Computing it once and multiplying the authored values is BIT-EXACT: same
    # operands, same single multiply, same order. Nothing between the four
    # calls could have changed it -- they were consecutive reads of one
    # subsystem's state.
    f = impulse_output_fraction(ies) if imp_f is None else imp_f
    return _EffectiveMotion(
        has_linear=has_lin,
        max_speed=ies.GetAuthoredMaxSpeed() * f if has_lin else 0.0,
        max_accel=ies.GetAuthoredMaxAccel() * f if has_lin else 0.0,
        has_angular=has_ang,
        max_ang_vel=ies.GetAuthoredMaxAngularVelocity() * f if has_ang else 0.0,
        max_ang_accel=ies.GetAuthoredMaxAngularAccel() * f if has_ang else 0.0,
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


def law_step_vector(cur, target, accel: float, dt: float):
    """One step of BC's motion law on a 3-vector: move ``cur`` toward
    ``target`` by min(accel, |gap| / tau) * dt along the gap. accel >=
    FALLBACK_MAX_ACCEL means no authored limit: snap. Tuples in, tuple out."""
    ex, ey, ez = target[0] - cur[0], target[1] - cur[1], target[2] - cur[2]
    e = math.sqrt(ex * ex + ey * ey + ez * ez)
    step = accel * dt if accel >= FALLBACK_MAX_ACCEL else min(accel, e / BC_IMPULSE_TAU) * dt
    if e <= step or e == 0.0:
        return (target[0], target[1], target[2])
    k = step / e
    return (cur[0] + ex * k, cur[1] + ey * k, cur[2] + ez * k)


def step_vector_velocity(ship, forward, current_speed: float, target_speed: float,
                         accel: float, dt: float, snap: bool = False):
    """BC's impulse law applied to the velocity VECTOR, not just its length.

    dv/dt = (target - v) / tau, its magnitude capped at the acceleration, with
    target = forward x target_speed. The same law as the scalar ramp along a
    straight line (so straight-line acceleration is unchanged), but in a turn
    the course lags the nose and the speed bleeds -- measured on stbc.exe
    (stbc-oracle reference, Movement): turning at half impulse the slide
    settles at atan(w x tau) = 15.6-15.9 deg; at full impulse the cap binds,
    so the speed settles at MaxAccel / w = 1.5 / 0.28 = 5.36 (85%) with the
    course 32 deg off the nose.

    The vector lives on the ship, ``_motion_vel = (vx, vy, vz, speed)``
    (mirrored for kernel M), so the AI integrator and the player's helm
    share it across hand-offs. Returns (vx, vy, vz, speed): speed is the
    vector's length, negative when it points behind the nose, or exactly
    ``target_speed`` once the vector lands on its target.

    The re-seed contract: the vector is trusted only while
    ``current_speed`` is bit-identical to ``_motion_vel[3]``, the speed this
    function last returned; any writer that sets ``_current_speed`` directly
    (warp exit, drift re-seed, tests) makes them differ and the vector is
    re-seeded along the nose; a writer that must keep the vector (none
    today) must write both. Code that moves the ship without the law and
    without writing ``_current_speed`` (a warp flight's end, a set-to-set
    arrival, the helm's warp burst and dash) drops the vector instead,
    ``ship._motion_vel = None`` (docs/reference/engine/motion-law.md).

    It also records the ship's acceleration, the law's own output
    (Mark 2026-11-06): ``_acceleration = (v - v0) / dt``, where v0 is the
    vector it stepped FROM (after any re-seed), so a direct velocity write
    gives no spike; ``(0, 0, 0)`` when ``dt <= 0``. The player's helm runs
    this outside the motion stage, so the manually flown player reports
    its helm's acceleration too.

    ``snap``: a ship with no authored linear limits takes the whole gap in
    one step (``accel * dt``, accel = FALLBACK_MAX_ACCEL), as the scalar
    ramp did; a ship whose live accel is 0 still closes at gap / tau."""
    mv = ship.__dict__.get("_motion_vel")
    if mv is None or current_speed != mv[3]:
        vel = (forward.x * current_speed, forward.y * current_speed, forward.z * current_speed)
    else:
        vel = (mv[0], mv[1], mv[2])
    sx, sy, sz = vel
    tx, ty, tz = forward.x * target_speed, forward.y * target_speed, forward.z * target_speed
    ex, ey, ez = tx - vel[0], ty - vel[1], tz - vel[2]
    e = math.sqrt(ex * ex + ey * ey + ez * ez)
    step = accel * dt if snap else min(accel, e / BC_IMPULSE_TAU) * dt
    if e <= step or e == 0.0:
        vel = (tx, ty, tz)
        speed = target_speed
    else:
        k = step / e
        vel = (vel[0] + ex * k, vel[1] + ey * k, vel[2] + ez * k)
        speed = math.sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2])
        if vel[0] * forward.x + vel[1] * forward.y + vel[2] * forward.z < 0.0:
            speed = -speed
    ship._motion_vel = (vel[0], vel[1], vel[2], speed)
    if dt <= 0.0:
        ship._acceleration = (0.0, 0.0, 0.0)
    else:
        ship._acceleration = ((vel[0] - sx) / dt, (vel[1] - sy) / dt, (vel[2] - sz) / dt)
    return vel[0], vel[1], vel[2], speed


def _no_thrust(ship) -> None:
    """A row the motion law did not fly (immobile, a warp flight that
    owned the tick, a warp-in arrival, a setpoint-less drifter, engines-out
    inertial drift): no commanded acceleration, for
    PhysicsObjectClass.GetAccelerationTG. Not the setpoint-less manually
    flown player: its helm (host_loop._PlayerControl) owns it."""
    ship._acceleration = (0.0, 0.0, 0.0)


def tick_all_ship_motion(dt: float) -> None:
    """Iterate every live ship and advance its motion by `dt` seconds.

    Rocks are excluded from the motion rows — a rock's motion is never
    AI-driven (rock-class spec §1) — but the tractor step's roster includes
    them.

    While native_motion.enabled() (DAUNTLESS_NATIVE_MOTION, on unless =0;
    the mirror live; the motion surface stock) kernel M flies the stage
    instead (native_motion.step_all), bit-exact with the loop below, which
    stays the reference.

    Then the tractor force (tick_tractors), then the publish.
    """
    with _prof.scope("motion.check"):
        native = native_motion.enabled()
    if native:
        native_motion.step_all(dt)
    else:
        from engine.appc.ship_iter import iter_non_rock_ships
        for ship in iter_non_rock_ships():
            _step_ship_motion(ship, dt)
    # After every row, before the publish: the tractor force is the stage's
    # other pose writer (Mark 2026-11-04), so the published poses hold it.
    tick_tractors(dt)
    # Last, in both switch states: the tick's poses, for later phases.
    with _prof.scope("motion.publish"):
        native_motion.publish_stage()


def tick_tractors(dt: float) -> None:
    """The tractor force step for one tick (``tractor.advance_tractors``:
    the native step, tractor_force.h), over the whole ``iter_ships()``
    roster, rocks included -- the roster the host's combat step passed when
    the force ran there (``cb.tractors``, after K2). It runs here, in the
    motion stage, so motion is the only ship-pose writer (Mark 2026-11-04):
    a beam the K1 tractor walk grips in a tick's combat step first pulls in
    the next tick's motion stage, and a headless GameLoop moves tractored
    ships too. In the host that is the NEXT FRAME: a frame runs all its
    GameLoop ticks before its combat steps (perf-cadences-and-latency.md).
    No-op for ships without a firing tractor."""
    from engine.appc.ship_iter import iter_ships
    with _prof.scope("motion.tractors"):
        tractor.advance_tractors(list(iter_ships()), dt)


def _ramp_toward(current: float, target: float, step: float) -> float:
    """Linear ramp: move `current` toward `target` by at most `step`."""
    delta = target - current
    if abs(delta) <= step:
        return target
    return current + (step if delta > 0 else -step)


def _step_ship_motion(ship, dt: float) -> None:
    """Advance one ship's transform by one tick.

    When no setpoint has ever been written, the manually flown player ship
    (driven via `_PlayerControl`, which yields to this integrator whenever a
    helm AI is installed) is left strictly alone; every other setpoint-less
    ship drifts on its scripted velocity/angular velocity via
    `engine.appc.drift` (see module docstring). Otherwise: flies under the
    impulse subsystem's live (already damage- and power-derated) limits with
    a non-braking cap; with every pod out it drifts on inertia (frozen
    world-space velocity + residual angular momentum). Spec
    docs/superpowers/specs/2026-06-10-impulse-engine-degradation-design.md.
    """
    # An immobile ship (SetStatic / SetStationary) is a fixed anchor: never
    # integrate a translation or rotation, whatever setpoint the Stay AI (or
    # anything else) wrote. Placed first so even a degenerate warp/setpoint
    # state can't move a station.
    #
    # implements(), NOT getattr(...) is not None: IsImmobile is a ShipClass
    # method, and TGObject.__getattr__ hands back a truthy _Stub for it on any
    # other object — so the old gate returned for EVERY non-ship, i.e. it gave
    # the right answer for the wrong reason. tick_all_ship_motion feeds this
    # from iter_ships(), which is already ShipClass-filtered, so no non-ship
    # reaches it via that path; the gate still has to be honest for direct
    # callers (and for the day someone makes _Stub falsy).
    if implements(ship, "IsImmobile") and ship.IsImmobile():
        _no_thrust(ship)
        return

    # An active in-system warp flight overrides normal setpoint motion:
    # engine/appc/warp_flight.py flies it (routed, facing its path) -- except
    # while an AI flight holds for its articulated parts, when the ship flies
    # its impulse orders below (warp_flight.step returns False).
    if getattr(ship, "_insystem_warp_transit", None) is not None:
        if warp_flight.step(ship, dt):
            _no_thrust(ship)
            return
    _step_after_warp(ship, dt)


def _step_after_warp(ship, dt: float) -> None:
    """The rest of `_step_ship_motion`, past its in-system warp check: what a
    row runs once warp_flight.step returned False (native_motion's driver
    calls it for that row when the kernel hands it back), and what every
    other mobile row runs."""
    # A warp-in arrival is flown by its warp engine's dewarp drive
    # (WarpEngineSubsystem.step_dewarp_drive): it holds its heading and
    # slides onto its placement whatever setpoint its AI writes meanwhile.
    if warp_state.is_arriving(ship):
        _no_thrust(ship)
        return

    sp = getattr(ship, "_speed_setpoint", None)
    av = getattr(ship, "_target_angular_velocity_setpoint", None)
    if sp is None and av is None:
        # No helm/AI setpoint has ever been written. The manually-flown
        # player is excluded -- it has no setpoints either under manual
        # control, but host_loop._PlayerControl drives and moves it
        # directly, so integrating here too would double-move it. Every
        # OTHER setpoint-less ship (a freshly-spawned prop, or one only
        # ever touched by the SDK's bare SetVelocity/SetAngularVelocity --
        # a launched probe, E1M2's falling station) drifts on whatever
        # velocity/angular velocity was scripted onto it, same as a rock
        # (engine.appc.drift, shared with engine.rocks.motion). A ship that
        # HAS an AI never reaches this branch once its tree has written a
        # setpoint -- see the module docstring's "known gap" paragraph.
        if ship is not App.Game_GetCurrentPlayer():
            drift.step(ship, dt)
            _no_thrust(ship)
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

    getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    ies = getter() if getter is not None else None
    f, _imp_out_f = impulse_fractions(ies)

    # -- Total loss -> inertial drift --
    # Named drift_vec, NOT drift: this function also calls the
    # engine.appc.drift MODULE (imported at module scope above) in the
    # setpoint-less branch earlier, and a local `drift =` assignment
    # anywhere in the function makes Python treat every `drift` in it as
    # local, shadowing that import (UnboundLocalError on the earlier use).
    if f <= 0.0:
        drift_vec = getattr(ship, "_drift_velocity", None)
        if drift_vec is None:
            drift_vec = TGPoint3(
                world_dir.x * ship._current_speed,
                world_dir.y * ship._current_speed,
                world_dir.z * ship._current_speed,
            )
            ship._drift_velocity = drift_vec
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(
            p.x + drift_vec.x * dt, p.y + drift_vec.y * dt, p.z + drift_vec.z * dt,
        )
        ship.SetVelocity(TGPoint3(drift_vec.x, drift_vec.y, drift_vec.z))
        _integrate_rotation(ship, dt)   # residual angular momentum, held
        _no_thrust(ship)
        return

    # -- Powered flight: clear any drift snapshot, re-seed speed --
    drift_vec = getattr(ship, "_drift_velocity", None)
    if drift_vec is not None:
        ship._current_speed = drift_vec.Length()
        ship._drift_velocity = None

    em = _effective_motion(ship, ies=ies, imp_f=_imp_out_f)

    # -- Linear: BC's law on the velocity vector (course lags the nose) --
    if em.has_linear:
        target_speed = _cap_keep(commanded_speed, ship._current_speed, em.max_speed)
        accel = em.max_accel if em.max_accel > 0.0 else FALLBACK_MAX_ACCEL
    else:
        target_speed = commanded_speed
        accel = FALLBACK_MAX_ACCEL
    vx, vy, vz, ship._current_speed = step_vector_velocity(
        ship, world_dir, ship._current_speed, target_speed, accel, dt,
        snap=not em.has_linear)

    if vx or vy or vz:
        p = ship.GetTranslate()
        ship.SetTranslateXYZ(p.x + vx * dt, p.y + vy * dt, p.z + vz * dt)
    ship.SetVelocity(TGPoint3(vx, vy, vz))

    # -- Angular ramp toward (capped) target --
    # A stored turn goal (TurnToward* / TurnDirectionsToDirections) re-plans
    # every tick while it still owns the setpoint, as the original's does; its
    # rate is not capped at MaxAngularVelocity (ShipClass._steer_turn_goal).
    goal = ship.__dict__.get("_turn_goal")
    steering = goal is not None and av is not None and goal[1] is av
    if steering:
        ship._steer_turn_goal(dt, em.max_ang_accel if em.has_angular else 0.0)
        av = ship._target_angular_velocity_setpoint
    frac = ship.__dict__.get("_target_angular_velocity_fraction")
    if frac is not None and em.has_angular:
        tx, ty, tz = (frac.x * em.max_ang_vel, frac.y * em.max_ang_vel, frac.z * em.max_ang_vel)
    elif av is None:
        tx = ty = tz = 0.0
    else:
        tx, ty, tz = av.x, av.y, av.z
    cav = ship._current_angular_velocity
    if em.has_angular:
        if not steering:
            tx = _cap_keep(tx, cav.x, em.max_ang_vel)
            ty = _cap_keep(ty, cav.y, em.max_ang_vel)
            tz = _cap_keep(tz, cav.z, em.max_ang_vel)
        aa = em.max_ang_accel if em.max_ang_accel > 0.0 else FALLBACK_MAX_ACCEL
        # BC eases into and out of a turn with the impulse law on the angular
        # velocity VECTOR: capped at MaxAngularAccel, then the gap decays with
        # tau = 1 s (measured: 50 / 90 / 99% of the rate at 1.15 / 2.75 /
        # 5.05 s, stop mirrored, every axis and power level; a diagonal turn's
        # TOTAL rate follows the same curve, 0.707 of it per axis --
        # stbc-oracle motion2 / motion_check / motion3).
        cav.x, cav.y, cav.z = law_step_vector((cav.x, cav.y, cav.z), (tx, ty, tz), aa, dt)
    else:
        ang_step = FALLBACK_MAX_ACCEL * dt
        cav.x = _ramp_toward(cav.x, tx, ang_step)
        cav.y = _ramp_toward(cav.y, ty, ang_step)
        cav.z = _ramp_toward(cav.z, tz, ang_step)
    # In place, so the descriptor never saw it: the mirror is a copy.
    native_combat.push_field(ship, "_current_angular_velocity")

    _integrate_rotation(ship, dt)


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


# At the bottom, not with the imports above: native_motion snapshots this
# module's functions at its own import (the stock surface kernel M stands
# in for), so they must exist by then whichever module is imported first.
from engine.appc import native_motion  # noqa: E402
