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


# ── Task 5: auto-enqueue on damage ───────────────────────────────────────────

def _damaged_ship():
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import RepairSubsystemProperty
    ship = ShipClass_Create("AutoQ")
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(50.0)
    prop.SetNumRepairTeams(3)
    ship.GetRepairSubsystem().SetProperty(prop)
    ship.GetSensorSubsystem().SetMaxCondition(8000.0)
    return ship


def test_damage_auto_enqueues_subsystem():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)                      # damage
    assert ship.GetRepairSubsystem().IsBeingRepaired(sensors) == 1


def test_repair_increase_does_not_enqueue():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)
    ship.GetRepairSubsystem()._queue.clear()
    sensors.Repair(100.0)                             # increase only
    assert ship.GetRepairSubsystem()._queue == []


def test_destroying_hit_does_not_enqueue():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(0.0)                         # straight to destroyed
    assert ship.GetRepairSubsystem()._queue == []


def test_bay_enqueues_itself_when_damaged():
    ship = _damaged_ship()
    bay = ship.GetRepairSubsystem()
    bay.SetMaxCondition(8000.0)
    bay.SetCondition(4000.0)
    assert any(s is bay for s in bay._queue)


def test_orphan_subsystem_damage_is_safe():
    s = _sub(condition=500.0)     # no ship anywhere
    s.SetCondition(100.0)         # must not raise


# ── Task 6: Update(dt) — RE-verified tick, completion, cannot-complete ──────

def test_tick_formula_matches_re_worked_example():
    # Sovereign: 50 pts, healthy bay, 2 queued, 30fps tick (dt=0.033):
    # raw=1.65, perItem=0.825; phaser c=3.0 -> +0.275; tractor c=7.0 -> +0.118
    bay = _bay(points=50.0, teams=3)
    phaser  = _sub(name="Phasers", max_condition=1000.0, condition=500.0,
                   complexity=3.0)
    tractor = _sub(name="Tractor", max_condition=1000.0, condition=500.0,
                   complexity=7.0)
    bay.AddToRepairList(phaser)
    bay.AddToRepairList(tractor)
    bay.Update(0.033)
    assert abs(phaser.GetCondition()  - 500.275) < 1e-6
    assert abs(tractor.GetCondition() - (500.0 + 0.825 / 7.0)) < 1e-6


def test_bay_health_scales_output():
    bay = _bay(points=50.0, teams=3)
    bay.SetCondition(4000.0)                    # 50% bay health
    target = _sub(condition=500.0, complexity=1.0)
    bay.AddToRepairList(target)
    bay.Update(1.0)
    # raw = 50 * 0.5 * 1.0 = 25, one item -> +25
    assert abs(target.GetCondition() - 525.0) < 1e-6


def test_destroyed_bay_repairs_nothing():
    bay = _bay()
    target = _sub(condition=500.0)
    bay.AddToRepairList(target)
    bay.SetCondition(0.0)
    bay.Update(1.0)
    assert target.GetCondition() == 500.0


def test_team_cap_and_divisor_with_queue_longer_than_teams():
    bay = _bay(points=60.0, teams=2)
    subs = [_sub(name="s%d" % i, condition=100.0, complexity=1.0)
            for i in range(3)]
    for s in subs:
        bay.AddToRepairList(s)
    bay.Update(1.0)
    # raw=60, divisor=min(3,2)=2, perItem=30: first two get +30, third waits
    assert abs(subs[0].GetCondition() - 130.0) < 1e-6
    assert abs(subs[1].GetCondition() - 130.0) < 1e-6
    assert subs[2].GetCondition() == 100.0


def test_completion_removes_and_fires(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda e: fired.append(e))
    bay = _bay(points=50.0, teams=3)
    nearly = _sub(condition=999.9, complexity=1.0)
    bay.AddToRepairList(nearly)
    bay.Update(1.0)
    assert nearly.GetCondition() == 1000.0
    assert not any(s is nearly for s in bay._queue)
    assert App.ET_REPAIR_COMPLETED in [e.GetEventType() for e in fired]


def test_destroyed_while_queued_skipped_notified_once(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda e: fired.append(e))
    bay = _bay(points=50.0, teams=2)
    doomed = _sub(name="doomed", condition=500.0)
    other  = _sub(name="other",  condition=500.0, complexity=1.0)
    bay.AddToRepairList(doomed)
    bay.AddToRepairList(other)
    doomed._condition = 0.0                     # destroyed in place, bypass hooks
    bay.Update(1.0)
    bay.Update(1.0)
    cannot = [e for e in fired
              if e.GetEventType() == App.ET_REPAIR_CANNOT_BE_COMPLETED]
    assert len(cannot) == 1                     # once, not per tick
    assert cannot[0].GetSource() is doomed
    assert any(s is doomed for s in bay._queue)  # skipped, NOT removed
    # 'other' still got a full team's share on EACH tick (doomed consumes no
    # team and doesn't shrink the divisor): raw=50*1*1=50, divisor=min(2,2)=2
    # -> +25/tick, two ticks -> 500 + 25 + 25 = 550.
    assert abs(other.GetCondition() - 550.0) < 1e-6


def test_self_repair_bay_queued_on_itself():
    bay = _bay(points=50.0, teams=3)
    bay.SetCondition(4000.0)                    # auto-enqueue needs a ship; add manually
    bay.AddToRepairList(bay)
    before = bay.GetCondition()
    bay.Update(1.0)
    assert bay.GetCondition() > before


def _queued_bay(teams=2, n=4):
    bay = _bay(teams=teams)
    subs = [_sub(name="s%d" % i, condition=100.0) for i in range(n)]
    for s in subs:
        bay.AddToRepairList(s)
    return bay, subs


def test_toggle_demotes_active_to_tail():
    bay, subs = _queued_bay()
    bay.HandleIncreasePriority(subs[0])          # active (idx 0 < teams 2)
    assert bay._queue[-1] is subs[0]
    assert bay.IsBeingRepaired(subs[0]) == 0


def test_toggle_promotes_waiting_to_head():
    bay, subs = _queued_bay()
    bay.HandleIncreasePriority(subs[3])          # waiting
    assert bay._queue[0] is subs[3]
    assert bay.IsBeingRepaired(subs[3]) == 1


def test_toggle_unqueued_is_noop():
    bay, subs = _queued_bay()
    before = list(bay._queue)
    bay.HandleIncreasePriority(_sub(condition=1.0))
    assert bay._queue == before


def test_priority_event_routes_to_toggle():
    import App
    bay, subs = _queued_bay()
    evt = App.TGObjPtrEvent_Create()
    evt.SetEventType(App.ET_REPAIR_INCREASE_PRIORITY)
    evt.SetDestination(bay)
    evt.SetObjPtr(subs[3])
    App.g_kEventManager.AddEvent(evt)
    assert bay._queue[0] is subs[3]
