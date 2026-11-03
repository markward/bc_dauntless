"""ShipSubsystem.SetConditionPercentage (SDK App.py:5665) -- campaign bug 2,
decided 2026-11-02 (docs/reference/engine/campaign-bug-decisions-2026-11-02.md
on main): condition = fraction x GetMaxCondition(), through the same path as
any other condition change, so a script-set condition posts the same events
as weapon damage. It used to fall through to the truthy TGObject _Stub and
do nothing (docs/stub_heatmap.md)."""
import App
import pytest

from engine.appc import effect_queue
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, PhaserBank, PhaserSystem,
                                    RepairSubsystem, ShipSubsystem)


@pytest.fixture(autouse=True)
def _clean():
    effect_queue.reset()
    yield
    effect_queue.reset()


def _capture(monkeypatch):
    fired = []
    orig = App.g_kEventManager.AddEvent

    def spy(evt):
        fired.append(evt)
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return fired


def _shape(fired):
    return [(e.GetEventType(), e.GetSource(), e.GetDestination())
            for e in fired]


def _sub(name="Sensors", max_condition=1000.0, disabled_pct=0.25):
    s = ShipSubsystem(name)
    s.SetMaxCondition(max_condition)
    s.SetDisabledPercentage(disabled_pct)
    return s


def _ship_with(sub):
    ship = ShipClass_Create("Galor")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(5000.0)
    ship.SetHull(hull)
    ship.SetSensorSubsystem(sub)
    return ship


def test_sets_the_fraction_of_max_condition():
    s = _sub()
    s.SetConditionPercentage(0.4)
    assert s.GetCondition() == 400.0
    assert s.GetConditionPercentage() == 0.4


def test_uses_the_property_max_so_the_percentage_reads_back():
    """GetMaxCondition is the property's (E1M2 edits it after load); E3M5's
    clamp compares GetConditionPercentage() with the value it set."""
    class _Prop:
        def GetMaxCondition(self):
            return 300.0
    s = _sub()
    s._property = _Prop()
    s.SetConditionPercentage(0.15)
    assert s.GetCondition() == pytest.approx(45.0)
    assert s.GetConditionPercentage() == pytest.approx(0.15)


def test_posts_the_same_events_as_damage(monkeypatch):
    by_damage = _sub()
    ship_a = _ship_with(by_damage)
    fired = _capture(monkeypatch)
    ship_a.DamageSystem(by_damage, 1000.0)
    effect_queue.boundary()             # the tick boundary
    damage_events = [(t, d is ship_a) for t, s, d in _shape(fired)
                     if s is by_damage]

    by_script = _sub()
    ship_b = _ship_with(by_script)
    fired.clear()
    by_script.SetConditionPercentage(0.0)
    effect_queue.boundary()             # the tick boundary
    script_events = [(t, d is ship_b) for t, s, d in _shape(fired)
                     if s is by_script]
    assert script_events == damage_events
    assert (App.ET_SUBSYSTEM_DESTROYED, True) in script_events


def test_disabling_fraction_posts_disabled(monkeypatch):
    s = _sub()
    ship = _ship_with(s)
    fired = _capture(monkeypatch)
    s.SetConditionPercentage(0.2)
    effect_queue.boundary()             # the tick boundary
    assert (App.ET_SUBSYSTEM_DISABLED, s, ship) in _shape(fired)


def test_raising_back_above_disabled_posts_operational(monkeypatch):
    s = _sub()
    _ship_with(s)
    s.SetConditionPercentage(0.2)
    effect_queue.boundary()             # the tick boundary
    fired = _capture(monkeypatch)
    s.SetConditionPercentage(0.9)
    effect_queue.boundary()             # the tick boundary
    assert [e.GetEventType() for e in fired if e.GetSource() is s] == \
        [App.ET_SUBSYSTEM_OPERATIONAL]


def test_enqueues_the_repair_like_damage():
    s = _sub()
    ship = _ship_with(s)
    bay = RepairSubsystem("Repair")
    bay.SetMaxCondition(100.0)
    ship.SetRepairSubsystem(bay)
    s.SetConditionPercentage(0.5)
    effect_queue.boundary()             # the tick boundary
    assert bay.IsBeingRepaired(s) or s in bay._queue


def test_works_on_a_child_weapon():
    system = PhaserSystem("Phasers")
    system.SetMaxCondition(1000.0)
    bank = PhaserBank("Phaser 1")
    bank.SetMaxCondition(800.0)
    system.AddChildSubsystem(bank)
    bank.SetConditionPercentage(0.25)
    assert bank.GetCondition() == 200.0


def test_missionlib_walks_the_children():
    """MissionLib.SetConditionPercentage (MissionLib.py:2293-2301) sets each
    child, not the parent that has children."""
    import MissionLib
    system = PhaserSystem("Phasers")
    system.SetMaxCondition(1000.0)
    banks = []
    for i in range(3):
        bank = PhaserBank("Phaser %d" % i)
        bank.SetMaxCondition(800.0)
        system.AddChildSubsystem(bank)
        banks.append(bank)
    MissionLib.SetConditionPercentage(system, 0.5)
    assert [b.GetCondition() for b in banks] == [400.0, 400.0, 400.0]
    assert system.GetCondition() == 1000.0


def test_missionlib_sets_a_leaf_subsystem_itself():
    import MissionLib
    s = _sub()
    MissionLib.SetConditionPercentage(s, 0.3)
    assert s.GetCondition() == pytest.approx(300.0)
