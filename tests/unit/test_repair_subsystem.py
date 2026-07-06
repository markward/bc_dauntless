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


# ── Task 4: RepairSubsystem queue core ──────────────────────────────────────

from engine.appc.subsystems import RepairSubsystem


def _bay(points=50.0, teams=3):
    from engine.appc.properties import RepairSubsystemProperty
    bay = RepairSubsystem("Engineering")
    bay.SetMaxCondition(8000.0)
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(points)   # data-bag setters, as hardpoints do
    prop.SetNumRepairTeams(teams)
    bay.SetProperty(prop)
    return bay


def test_bay_is_on_by_default():
    assert RepairSubsystem("Engineering").IsOn() == 1


def test_property_readers_with_and_without_property():
    assert _bay(50.0, 3).GetMaxRepairPoints() == 50.0
    assert _bay(50.0, 3).GetNumRepairTeams() == 3
    bare = RepairSubsystem("Engineering")
    assert bare.GetMaxRepairPoints() == 0.0
    assert bare.GetNumRepairTeams() == 0


def test_add_accepts_damaged_rejects_dup_destroyed_undamaged():
    bay = _bay()
    damaged = _sub(condition=400.0)
    assert bay.AddToRepairList(damaged) == 1
    assert bay.AddToRepairList(damaged) == 0          # duplicate
    assert bay.AddToRepairList(_sub(condition=0.0)) == 0    # destroyed
    assert bay.AddToRepairList(_sub()) == 0           # undamaged (full)
    assert bay.AddToRepairList(None) == 0
    assert len(bay._queue) == 1


def test_add_fires_add_to_repair_list_event(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda evt: fired.append(evt))
    bay = _bay()
    damaged = _sub(condition=400.0)
    bay.AddToRepairList(damaged)
    assert [e.GetEventType() for e in fired] == [App.ET_ADD_TO_REPAIR_LIST]
    assert fired[0].GetSource() is damaged
    assert fired[0].GetObjPtr() is damaged
    assert fired[0].GetDestination() is bay


def test_is_being_repaired_is_first_num_teams_entries():
    bay = _bay(teams=2)
    subs = [_sub(name="s%d" % i, condition=100.0) for i in range(4)]
    for s in subs:
        bay.AddToRepairList(s)
    assert bay.IsBeingRepaired(subs[0]) == 1
    assert bay.IsBeingRepaired(subs[1]) == 1
    assert bay.IsBeingRepaired(subs[2]) == 0    # waiting
    assert bay.IsBeingRepaired(subs[3]) == 0
    assert bay.IsBeingRepaired(_sub(condition=1.0)) == 0  # not queued


def test_add_subsystem_is_the_sdk_alias():
    bay = _bay()
    damaged = _sub(condition=400.0)
    assert bay.AddSubsystem(damaged) == 1
    assert bay.IsBeingRepaired(damaged) == 1
