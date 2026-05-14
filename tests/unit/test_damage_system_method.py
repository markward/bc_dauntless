"""DamageableObject.DamageSystem(subsystem, amount) decrements
subsystem condition. Hull-zero triggers SetDying(True).
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem


def _ship_with_hull(max_cond=1000.0):
    ship = ShipClass_Create("Test")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(max_cond)
    ship._hull = hull
    return ship, hull


def test_damage_system_decrements_condition():
    ship, hull = _ship_with_hull(max_cond=1000.0)
    ship.DamageSystem(hull, 300.0)
    assert hull.GetCondition() == 700.0


def test_damage_system_floors_at_zero():
    ship, hull = _ship_with_hull(max_cond=100.0)
    ship.DamageSystem(hull, 500.0)
    assert hull.GetCondition() == 0.0


def test_damage_system_no_op_on_none():
    ship, _ = _ship_with_hull()
    ship.DamageSystem(None, 100.0)  # must not raise


def test_damage_system_hull_zero_triggers_dying():
    ship, hull = _ship_with_hull(max_cond=50.0)
    assert ship.IsDying() == 0
    ship.DamageSystem(hull, 50.0)
    assert hull.GetCondition() == 0.0
    assert ship.IsDying() == 1


def test_damage_system_non_hull_zero_does_not_trigger_dying():
    """A subsystem at zero condition that isn't the hull does NOT
    flip the ship to dying — that's a hull-only effect."""
    from engine.appc.subsystems import SensorSubsystem
    ship, hull = _ship_with_hull(max_cond=1000.0)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(100.0)
    ship.DamageSystem(sensor, 100.0)
    assert sensor.GetCondition() == 0.0
    assert ship.IsDying() == 0
