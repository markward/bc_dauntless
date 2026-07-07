"""Threshold-crossing events on ShipSubsystem condition changes."""
import App
from engine.appc.subsystems import ShipSubsystem, PhaserSystem, PhaserBank


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


def _phaser_parent_with_banks(n=2):
    """PhaserSystem parent with `n` alive PhaserBank children, plus the
    parent's own raw condition pool healthy. No SetCondition/SetMaxCondition
    calls here (direct attribute writes only), so building the fixture never
    fires any threshold events on its own."""
    parent = PhaserSystem("Phasers")
    parent._max_condition = 100.0
    parent._condition = 100.0
    banks = []
    for i in range(n):
        b = PhaserBank(f"Bank{i}")
        b._max_condition = 100.0
        b._condition = 100.0
        parent.AddChildSubsystem(b)
        banks.append(b)
    return parent, banks


def test_weapon_parent_alive_children_zero_raw_condition_no_destroyed_event(monkeypatch):
    """A weapon parent's raw _condition pool hitting zero must NOT fire
    ET_SUBSYSTEM_DESTROYED while its child emitter banks are still alive —
    the aggregate IsDestroyed() (all children destroyed) is what matters for
    weapon parents, not the unused raw condition field. Splash damage in
    combat.py's _iter_subsystems yields the parent AND its children, so the
    parent's raw pool can be driven to zero independently of the banks."""
    parent, banks = _phaser_parent_with_banks()
    fired = _capture(monkeypatch)
    parent.SetCondition(0.0)          # raw pool zeroed; children still alive
    assert parent.IsDestroyed() == 0  # aggregate: children alive => not destroyed
    assert App.ET_SUBSYSTEM_DESTROYED not in _types(fired)


def test_weapon_parent_destroyed_fires_only_when_all_children_destroyed(monkeypatch):
    """Once every child bank is destroyed, the aggregate IsDestroyed() flips
    True; the parent must fire ET_SUBSYSTEM_DESTROYED exactly once when its
    own threshold machinery next re-evaluates (SetCondition on the parent —
    the same call combat.py's splash loop makes every hit)."""
    parent, banks = _phaser_parent_with_banks()
    for b in banks:
        b._condition = 0.0            # direct write: no event from the child
    assert parent.IsDestroyed() == 1   # aggregate flips once all children are gone
    fired = _capture(monkeypatch)
    # Parent only re-evaluates its own threshold state on ITS OWN
    # SetCondition/SetMaxCondition call — it does not observe child mutations
    # automatically. Drive it exactly like combat.py's splash loop does.
    parent.SetCondition(parent.GetCondition())
    assert _types(fired) == [App.ET_SUBSYSTEM_DESTROYED]


def test_plain_subsystem_still_destroys_on_zero_condition_regression(monkeypatch):
    """Regression guard: a non-weapon leaf subsystem (no children, no
    IsDestroyed override) still fires ET_SUBSYSTEM_DESTROYED on condition 0,
    unaffected by the switch to IsDestroyed()-based threshold checking."""
    s = _sub()
    fired = _capture(monkeypatch)
    s.SetCondition(0.0)
    assert _types(fired) == [App.ET_SUBSYSTEM_DESTROYED]


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
