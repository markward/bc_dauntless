"""ShipClass.TurnTowardOrientation must steer the ship's forward/up onto the
commanded vectors — the 2-arg form AI.PlainAI.FollowWaypoints.TurnToward calls
(sdk/.../FollowWaypoints.py:276). It delegates to the tested
TurnDirectionsToDirections controller; FollowWaypoints could not turn before
this (PhysicsObjectClass.TurnTowardOrientation was a no-op)."""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.appc.ship_motion import _step_ship_motion

_DT = 1.0 / 60.0


def _galaxy_ship():
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _fwd_dot(ship, target_fwd):
    fwd = ship.GetWorldRotation().GetCol(1)
    d = TGPoint3(target_fwd.x, target_fwd.y, target_fwd.z); d.Unitize()
    return fwd.x * d.x + fwd.y * d.y + fwd.z * d.z


def test_turn_toward_orientation_converges_off_axis():
    """From an arbitrary attitude, commanding a fixed target forward/up each
    tick must land the nose on target and hold it (no hunting)."""
    ship = _galaxy_ship()
    Rx = TGMatrix3(); Rx.MakeRotation(1.1, TGPoint3(1.0, 0.0, 0.0))
    Rz = TGMatrix3(); Rz.MakeRotation(2.3, TGPoint3(0.0, 0.0, 1.0))
    ship.SetMatrixRotation(Rx.MultMatrix(Rz))

    target_fwd = TGPoint3(0.6, 0.8, 0.0); target_fwd.Unitize()
    target_up = TGPoint3(0.0, 0.0, 1.0)

    history = []
    for _ in range(int(20.0 * 60)):
        ship.TurnTowardOrientation(target_fwd, target_up)
        _step_ship_motion(ship, _DT)
        history.append(_fwd_dot(ship, target_fwd))

    assert history[-1] > 0.999, f"never converged: {history[-1]:.3f}"
    assert min(history[-300:]) > 0.995, "hunting after alignment"


def test_turn_toward_orientation_writes_body_setpoint():
    """One call must write a non-None body-frame angular-velocity setpoint
    (proves delegation actually reached the controller, not the no-op stub)."""
    ship = _galaxy_ship()
    target_fwd = TGPoint3(1.0, 0.0, 0.0)   # 90° off the +Y nose
    target_up = TGPoint3(0.0, 0.0, 1.0)
    ship.TurnTowardOrientation(target_fwd, target_up)
    sp = ship.GetTargetAngularVelocitySetpoint()
    assert sp is not None
    assert (sp.x * sp.x + sp.y * sp.y + sp.z * sp.z) > 0.0
