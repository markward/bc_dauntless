"""All impulse pods offline → inertial drift (no decay), repair → powered.
Exercises impulse_online_fraction through ship_motion._step_ship_motion.

(Filename retained from the prior drag-to-stop model for git history; the
behaviour under test is now drift, not decay.)"""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.subsystems import ShipSubsystem


def _galaxy_with_pods():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    # ShipClass_Create does not materialise hardpoint engine pods in a
    # headless test, so add the Galaxy's three impulse pods explicitly.
    for i in range(3):
        ies.AddChildSubsystem(ShipSubsystem("pod%d" % i))
    return ship, ies


def _disable_all_pods(ies):
    for i in range(ies.GetNumChildSubsystems()):
        ies.GetChildSubsystem(i).SetCondition(0.0)


def test_all_pods_offline_drift_then_repair_recovers():
    ship, ies = _galaxy_with_pods()
    assert ies.GetNumChildSubsystems() == 3

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
    pod0 = ies.GetChildSubsystem(0)
    pod0.SetCondition(pod0.GetMaxCondition())
    _step_ship_motion(ship, 1.0 / 60)
    assert ship._drift_velocity is None
    assert ship._current_speed > 0.0
