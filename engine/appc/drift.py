"""Shared drift-and-spin kinematic step for objects with no AI setpoints.

This is the only integration a bare `SetVelocity` / `SetAngularVelocity`
ever gets: the shim's `PhysicsObjectClass.SetVelocity` just STORES the
value (`engine/appc/objects.py`), so without a per-tick step reading it
back out, an object moved only by the SDK's own script code (never by a
helm AI) never actually moves.

Two SDK call sites besides rocks hit exactly this gap:
  * E1M2's Haven station, sent toward the planet with `pStation.SetVelocity`
    after being hit (no AI, no setpoints).
  * E8M2's disabled Matan, sent spinning into the sun with
    `SetVelocity` + `SetAngularVelocity(..., DIRECTION_MODEL_SPACE)`.
  * `ShipScriptActions.PushObject` (e.g. a launched sensor probe), which
    only ever calls `SetVelocity`.

Spin honours the space it was set in: DIRECTION_MODEL_SPACE is a
body-frame axis (post-multiply, R.D), world space a world axis
(pre-multiply, D.R) -- see `engine/appc/ship_motion.py`'s rotation
convention note.

`engine.rocks.motion.step` is this exact step (a rock has no AI and no
engines, so it was always drift-only); it now calls through here so
there is one implementation. `engine.appc.ship_motion._step_ship_motion`
falls back to this for any OTHER setpoint-less, non-player ship.
"""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.core.ids import implements


def step(obj, dt: float) -> None:
    # Only a PhysicsObjectClass (ships, rocks) actually carries `_velocity` /
    # `_angular_velocity` (set in PhysicsObjectClass.__init__) -- a defensive
    # direct call on something else (e.g. a Waypoint, via
    # ship_motion._step_ship_motion's own defensive-call test) must no-op,
    # not raise.
    if not isinstance(obj, PhysicsObjectClass):
        return
    # implements(), NOT a bare call: IsImmobile is a ShipClass method, and
    # TGObject.__getattr__ hands back a truthy _Stub for it on any other
    # object, so a bare obj.IsImmobile() call stubs/misreads a non-ship that
    # reaches here -- same gotcha ship_motion._step_ship_motion already
    # guards against for its own immobility check.
    if implements(obj, "IsImmobile") and obj.IsImmobile():
        return
    v = obj._velocity
    if v.x or v.y or v.z:
        p = obj.GetTranslate()
        obj.SetTranslateXYZ(p.x + v.x * dt, p.y + v.y * dt, p.z + v.z * dt)
    w = obj._angular_velocity
    if w.x or w.y or w.z:
        rate = (w.x * w.x + w.y * w.y + w.z * w.z) ** 0.5
        axis = TGPoint3(w.x / rate, w.y / rate, w.z / rate)
        D = TGMatrix3()
        D.MakeRotation(rate * dt, axis)
        R = obj.GetWorldRotation()
        if getattr(obj, "_angular_space", PhysicsObjectClass.DIRECTION_WORLD_SPACE) \
                == PhysicsObjectClass.DIRECTION_MODEL_SPACE:
            R = R.MultMatrix(D)
        else:
            R = D.MultMatrix(R)
        obj.SetMatrixRotation(R)
