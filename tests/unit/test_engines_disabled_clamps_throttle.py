"""Throttle/degradation behaviour as impulse pods go offline."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.subsystems import ShipSubsystem


def _galaxy():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3); ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28); ies.SetMaxAngularAccel(0.12)
    for i in range(3):
        ies.AddChildSubsystem(ShipSubsystem("pod%d" % i))
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
