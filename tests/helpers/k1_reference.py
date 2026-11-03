"""Frozen reference rules for the K1 kernel's geometry twins (fire control
native only, Task 6): the Python of weapon_subsystems as it stood at
9c3db5ec6, before fire control's Python copy was deleted (M3). The kernel
(native/src/combat/src/weapon_geometry.cc) is now the engine's one copy;
these are recorded expectations for tests/unit/test_native_weapon_geometry.py
only -- nothing in the engine may import this module.
"""
import math as _math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.weapon_subsystems import (_PULSE_DEFAULT_LIFETIME,
                                           _PULSE_RANGE_GATE_SECONDS,
                                           _TORPEDO_CONE_HALF_ANGLE)


def _emitter_forward_world(emitter, ship, *, skew=False) -> TGPoint3:
    """The emitter's local forward (tube Direction / cannon OrientationForward)
    rotated to world.  ``skew`` adds BC's +0.033 x Right fan in the LOCAL
    frame first (audited §2.4.1; torpedo skew salvo only)."""
    got = emitter.GetDirection() if hasattr(emitter, "GetDirection") else None
    local = (TGPoint3(got.x, got.y, got.z) if isinstance(got, TGPoint3)
             else TGPoint3(0.0, 1.0, 0.0))
    if skew and getattr(emitter, "IsSkewFire", None) and emitter.IsSkewFire():
        right = emitter.GetRight() if hasattr(emitter, "GetRight") else None
        if isinstance(right, TGPoint3):
            local = TGPoint3(local.x + 0.033 * right.x,
                             local.y + 0.033 * right.y,
                             local.z + 0.033 * right.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            local.MultMatrixLeft(rot)
    return local


def _solve_pulse_launch_direction(cannon, ship, target, mod):
    """BC's targeted pulse launch (PulseWeapon vtable slot +0x7C): a
    world-space unit launch direction that LEADS the target, or None when
    the shot must be refused.  Read from the retail binary 2026-09-14
    (clean-room answer); prose, not transcription:

      aim    = target centre + local aim offset, rotated & scaled (0x005852A0
               -- the same resolver the torpedo tube's fire gate uses)
      muzzle = cannon mount position in world
      v_eff  = launchSpeed + (shipVel - targetVel) . unit(aim - muzzle)
      t      = |aim - muzzle| / v_eff
      pred   = aim + targetVel*t + 0.5*targetAccel*t^2   (lead helper 0x005A0B50)
               - shipVel*t     (the bolt inherits shipVel; cancel that drift)
      dir    = unit(pred - muzzle)

    Refusals, in BC's order: v_eff <= 0 (target outruns the bolt), t <= 0,
    t > the module's GetLifetime() (default 8 s), predicted range beyond
    30 * v_eff.  The arc test is the caller's, on the returned direction.

    launchSpeed is the module's GetLaunchSpeed() -- BC keeps a separate
    per-weapon copy for the solver (PulseWeapon+0xCC) that script is
    expected to keep equal to the module value; the SDK AI reads it via
    PulseWeapon.GetLaunchSpeed() for its own lead, so one source is the
    faithful reading.
    """
    aim = _resolve_torpedo_aim_point(cannon, target)
    if aim is None:
        return None
    muzzle = cannon._emitter_world_position()
    to_aim = aim - muzzle
    dist = to_aim.Length()
    if dist < 1e-6:
        return None
    u = TGPoint3(to_aim.x / dist, to_aim.y / dist, to_aim.z / dist)

    def _vec(obj, name):
        v = getattr(obj, name)() if (obj is not None and hasattr(obj, name)) else None
        return v if isinstance(v, TGPoint3) else TGPoint3(0.0, 0.0, 0.0)

    ship_vel = _vec(ship, "GetVelocityTG")
    tgt_vel = _vec(target, "GetVelocityTG")
    tgt_acc = _vec(target, "GetAccelerationTG")

    launch_speed = float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 0.0
    v_eff = launch_speed + (ship_vel - tgt_vel).Dot(u)
    if v_eff <= 0.0:
        return None
    t = dist / v_eff
    if t <= 0.0:
        return None
    lifetime = (float(mod.GetLifetime()) if hasattr(mod, "GetLifetime")
                else _PULSE_DEFAULT_LIFETIME)
    if t > lifetime:
        return None
    pred = TGPoint3(
        aim.x + tgt_vel.x * t + 0.5 * tgt_acc.x * t * t - ship_vel.x * t,
        aim.y + tgt_vel.y * t + 0.5 * tgt_acc.y * t * t - ship_vel.y * t,
        aim.z + tgt_vel.z * t + 0.5 * tgt_acc.z * t * t - ship_vel.z * t,
    )
    launch = pred - muzzle
    n = launch.Length()
    if n < 1e-6 or n > _PULSE_RANGE_GATE_SECONDS * v_eff:
        return None
    return TGPoint3(launch.x / n, launch.y / n, launch.z / n)


def _resolve_torpedo_aim_point(tube, target):
    """0x005852A0: target world pos + tube aim offset scaled by target world
    scale and rotated by target world rotation. None => unresolvable (the
    caller posts ET_WEAPON_FIRE_FAILED). No speed/velocity/intercept enters."""
    if target is None or not hasattr(target, "GetWorldLocation"):
        return None
    if hasattr(target, "IsDead") and target.IsDead():
        return None
    offset = getattr(tube, "_target_offset", None)
    if not isinstance(offset, TGPoint3):
        pos = target.GetWorldLocation()
        return TGPoint3(pos.x, pos.y, pos.z)
    from engine.appc.subsystems import target_offset_world
    return target_offset_world(target, offset)


def _in_torpedo_cone(tube, ship, aim_point) -> bool:
    """0x0057DA90->0x0057DC10: square +/-30 degree cone about the tube
    direction, yaw and pitch checked INDEPENDENTLY via atan2; forward must
    be > 0.  No occlusion test -- firing through an asteroid is legal
    (audited)."""
    mount = tube._emitter_world_position()
    to_aim = aim_point - mount
    if to_aim.Length() < 1e-6:
        return False
    d = tube.GetDirection() if hasattr(tube, "GetDirection") else None
    r = tube.GetRight() if hasattr(tube, "GetRight") else None
    if not isinstance(d, TGPoint3):
        d = TGPoint3(0.0, 1.0, 0.0)
    if not isinstance(r, TGPoint3):
        r = TGPoint3(1.0, 0.0, 0.0)
    u = TGPoint3(d.y * r.z - d.z * r.y,      # up = dir x right (local)
                 d.z * r.x - d.x * r.z,
                 d.x * r.y - d.y * r.x)
    rot = ship.GetWorldRotation() if (ship is not None
              and hasattr(ship, "GetWorldRotation")) else None
    basis = []
    for v in (d, r, u):
        w = TGPoint3(v.x, v.y, v.z)
        if isinstance(rot, TGMatrix3):
            w.MultMatrixLeft(rot)
        basis.append(w)
    fwd = basis[0].Dot(to_aim)
    if fwd <= 0.0:
        return False
    yaw = _math.atan2(abs(basis[1].Dot(to_aim)), fwd)
    pitch = _math.atan2(abs(basis[2].Dot(to_aim)), fwd)
    return yaw <= _TORPEDO_CONE_HALF_ANGLE and pitch <= _TORPEDO_CONE_HALF_ANGLE
