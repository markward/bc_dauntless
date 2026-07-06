"""Threshold-crossing events on ShipSubsystem condition changes."""
import App
from engine.appc.subsystems import ShipSubsystem


def _capture(monkeypatch):
    fired = []
    orig = App.g_kEventManager.AddEvent
    def spy(evt):
        fired.append(evt)
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return fired


def _types(fired):
    return [e.GetEventType() for e in fired]


def _sub(max_condition=1000.0, disabled_pct=0.25):
    s = ShipSubsystem("Sensors")
    s.SetMaxCondition(max_condition)
    s.SetDisabledPercentage(disabled_pct)
    return s


def test_crossing_into_disabled_fires_once(monkeypatch):
    s = _sub()
    fired = _capture(monkeypatch)
    s.SetCondition(200.0)          # 20% <= 25% -> disabled
    assert _types(fired) == [App.ET_SUBSYSTEM_DISABLED]
    s.SetCondition(150.0)          # still disabled -> no re-fire
    assert _types(fired) == [App.ET_SUBSYSTEM_DISABLED]


def test_destroyed_fires_and_beats_disabled(monkeypatch):
    s = _sub()
    fired = _capture(monkeypatch)
    s.SetCondition(0.0)            # straight to destroyed
    assert _types(fired) == [App.ET_SUBSYSTEM_DESTROYED]


def test_repair_back_above_threshold_fires_operational(monkeypatch):
    s = _sub()
    s.SetCondition(100.0)          # disabled
    fired = _capture(monkeypatch)
    s.Repair(400.0)                # 50% -> operational
    assert App.ET_SUBSYSTEM_OPERATIONAL in _types(fired)


def test_destroyed_to_disabled_is_silent(monkeypatch):
    s = _sub()
    s.SetCondition(0.0)
    fired = _capture(monkeypatch)
    s.Repair(100.0)                # 10% — above 0, still <= 25%
    assert _types(fired) == []     # no event for destroyed->disabled


def test_event_shape_source_sub_dest_ship(monkeypatch):
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Shape")
    sensors = ship.GetSensorSubsystem()
    sensors.SetMaxCondition(1000.0)
    fired = _capture(monkeypatch)
    sensors.SetCondition(0.0)
    destroyed = [e for e in fired
                 if e.GetEventType() == App.ET_SUBSYSTEM_DESTROYED]
    assert len(destroyed) == 1
    assert destroyed[0].GetSource() is sensors
    assert destroyed[0].GetDestination() is ship


def test_child_subsystem_resolves_ship_via_parent_chain(monkeypatch):
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Chain")
    parent = ship.GetSensorSubsystem()
    child = ShipSubsystem("Sensor Dish")
    child.SetMaxCondition(500.0)
    parent.AddChildSubsystem(child)
    fired = _capture(monkeypatch)
    child.SetCondition(0.0)
    destroyed = [e for e in fired
                 if e.GetEventType() == App.ET_SUBSYSTEM_DESTROYED]
    assert destroyed and destroyed[0].GetDestination() is ship
