"""RepairSubsystem queue/tick + ShipSubsystem repair surface."""
import App
from engine.appc.subsystems import ShipSubsystem


def _sub(name="Phasers", max_condition=1000.0, condition=None,
         complexity=None, disabled_pct=0.25):
    s = ShipSubsystem(name)
    s.SetMaxCondition(max_condition)
    s.SetDisabledPercentage(disabled_pct)
    if condition is not None:
        s.SetCondition(condition)
    if complexity is not None:
        s.SetRepairComplexity(complexity)
    return s


def test_repair_adds_condition_clamped_to_max():
    s = _sub(max_condition=1000.0, condition=400.0)
    s.Repair(100.0)
    assert s.GetCondition() == 500.0
    s.Repair(10000.0)
    assert s.GetCondition() == 1000.0


def test_repair_ignores_none_zero_negative():
    s = _sub(max_condition=1000.0, condition=400.0)
    s.Repair(None)
    s.Repair(0.0)
    s.Repair(-5.0)
    assert s.GetCondition() == 400.0


def test_repair_complexity_default_and_roundtrip():
    s = _sub()
    assert s.GetRepairComplexity() == 1.0
    s.SetRepairComplexity(3.0)
    assert s.GetRepairComplexity() == 3.0


def test_setup_properties_seeds_repair_complexity():
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import SensorProperty
    ship = ShipClass_Create("Galaxy")
    prop = SensorProperty("Sensor Array")
    prop.SetMaxCondition(8000.0)
    prop.SetRepairComplexity(4.0)          # data-bag setter, like hardpoints
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    assert ship.GetSensorSubsystem().GetRepairComplexity() == 4.0
