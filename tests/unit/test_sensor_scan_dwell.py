"""Scans take BC's dwell: IdentifyObject is deferred, Scan Area spaces its
identifications one dwell apart (RE'd: ScanAllObjects spaces actions by
GetIdentificationTime). ForceObjectIdentified stays immediate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_contacts

_ids: list = []


def _on_id(dest, event):
    _ids.append(event.GetDestination())


def _world():
    from engine.core.game import Game, _set_current_game
    _ids.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_id")
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


def _ship(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def test_identify_object_is_deferred_by_the_dwell(monkeypatch):
    s, player, sensors = _world()
    far_away = _ship(s, "Far", 50000.0)       # beyond range: scans reach anyway
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 10.0)
    sensors.IdentifyObject(far_away)
    assert sensors.IsObjectKnown(far_away) == 0
    sensor_contacts.tick(player, 13.9)
    assert sensors.IsObjectKnown(far_away) == 0
    sensor_contacts.tick(player, 14.0)
    assert sensors.IsObjectKnown(far_away) == 1


def test_area_scan_spaces_identifications_one_dwell_apart(monkeypatch):
    s, player, sensors = _world()
    a = _ship(s, "A", 30000.0)
    b = _ship(s, "B", 40000.0)
    monkeypatch.setattr(sensor_contacts, "_now", lambda: 0.0)
    seq = sensors.ScanAllObjects()
    assert isinstance(seq, App.TGSequence)
    seq.Play()
    sensor_contacts.tick(player, 4.0)
    assert len(_ids) == 1
    sensor_contacts.tick(player, 8.0)
    assert set(_ids) == {a, b}


def test_force_identify_is_immediate():
    s, player, sensors = _world()
    a = _ship(s, "A", 30000.0)
    sensors.ForceObjectIdentified(a)
    assert sensors.IsObjectKnown(a) == 1
    assert _ids == [a]


def test_force_identify_while_pending_fires_once(monkeypatch):
    s, player, sensors = _world()
    a = _ship(s, "A", 500.0)
    sensor_contacts.tick(player, 0.0)         # passive dwell pending
    sensors.ForceObjectIdentified(a)
    sensor_contacts.tick(player, 4.0)
    assert _ids == [a]


def test_identify_object_on_a_non_player_ship_is_a_no_op(monkeypatch):
    s, player, sensors = _world()
    npc = _ship(s, "NPC", 100.0)
    npc_sensors = SensorSubsystem("Sensors")
    npc.SetSensorSubsystem(npc_sensors)
    target = _ship(s, "T", 200.0)
    npc_sensors.IdentifyObject(target)
    sensor_contacts.tick(player, 100.0)
    assert npc_sensors.IsObjectKnown(target) == 0
