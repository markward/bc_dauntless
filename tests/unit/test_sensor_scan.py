"""Active area scan + single-target scan on SensorSubsystem.

The Science bridge menu's "Scan Area" button was a silent no-op: the SDK's
``ScienceMenuHandlers.Scan`` / ``E1M2.ScanComplete`` call
``pSensors.ScanAllObjects().Play()`` (E1M2 unguarded), and "Scan Object" calls
``pSensors.IdentifyObject(target)`` — both fell through to a truthy ``_Stub`` and
did nothing.

``ScanAllObjects`` now returns a real TGSequence whose played action arms a
scan identification for EVERY unknown contact in the ship's set (ignoring
range — an active scan reveals the whole area), spaced one identification
time apart. ``IdentifyObject`` arms one contact the same way. Both land through
``engine.appc.sensor_contacts`` and the shared commit point (``_identify_one``),
so they never double-fire against the passive dwell. Both are deferred by BC's
identification dwell (default 4.0 s) — tests tick the contact manager forward
to settle them.
"""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc.planet import Planet_Create
from engine.appc import sensor_contacts, sensor_dials
from engine.core.game import Game, _set_current_game

_identified: list = []


def _dwell() -> float:
    return sensor_dials.get("identification_time_s")


def _on_identified(dest, event):
    _identified.append(event.GetDestination())


def _subscribe():
    _identified.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SENSORS_SHIP_IDENTIFIED, None, __name__ + "._on_identified")


def _player_in_set(base_range=2000.0, at=(0.0, 0.0, 0.0)):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    player.SetTranslateXYZ(*at)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    # The contact manager is player-only (same idiom as
    # tests/unit/test_sensor_contacts.py::_world).
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


# --------------------------------------------------------------------------
# Sensor power state
# --------------------------------------------------------------------------

def test_sensors_are_on_by_default():
    """A functioning sensor array is ON during normal operation (unlike weapons,
    which power on only at RED alert). SDK gates like E1M2.ScanHandler check
    pSensors.IsOn(); if sensors defaulted off they'd fall through to the generic
    'Scan Area' acknowledgement."""
    assert SensorSubsystem("Sensors").IsOn() == 1


# --------------------------------------------------------------------------
# ScanAllObjects
# --------------------------------------------------------------------------

def test_scan_all_objects_returns_playable_sequence():
    _subscribe()
    s, player, sensors = _player_in_set()
    seq = sensors.ScanAllObjects()
    # Must be a real, truthy TGSequence the SDK can Play() (never a _Stub/None:
    # E1M2.ScanComplete plays the result with no None guard).
    assert seq is not None
    assert hasattr(seq, "Play")
    seq.Play()   # must not raise


def test_scan_identifies_all_in_set_ignoring_range():
    """Active scan reveals the whole area — including an out-of-range contact
    the passive sweep would skip — once each contact's dwell has elapsed.
    ScanAllObjects spaces the three contacts' identifications one dwell apart,
    so settling the last one needs n * dwell game-time to pass."""
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)

    near = ShipClass_Create("BirdOfPrey")
    near.SetTranslateXYZ(1000.0, 0.0, 0.0)       # inside 2000 GU
    s.AddObjectToSet(near, "Near")
    far = ShipClass_Create("BirdOfPrey")
    far.SetTranslateXYZ(50000.0, 0.0, 0.0)       # far outside sensor range
    s.AddObjectToSet(far, "Far")
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetTranslateXYZ(80000.0, 0.0, 0.0)     # planet, also out of range
    s.AddObjectToSet(haven, "Haven")

    sensors.ScanAllObjects().Play()
    sensor_contacts.tick(player, 3 * _dwell())

    assert sensors.IsObjectKnown(near) == 1
    assert sensors.IsObjectKnown(far) == 1       # bypasses the range gate
    assert sensors.IsObjectKnown(haven) == 1
    assert near in _identified and far in _identified and haven in _identified
    # Each contact fires exactly once.
    assert _identified.count(near) == 1
    assert _identified.count(far) == 1
    assert _identified.count(haven) == 1


def test_scan_excludes_player_and_non_contacts():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    from engine.appc.objects import ObjectClass
    marker = ObjectClass()      # placement marker / light / grid — not a contact
    marker.SetTranslateXYZ(100.0, 0.0, 0.0)
    s.AddObjectToSet(marker, "Player Start")

    sensors.ScanAllObjects().Play()
    sensor_contacts.tick(player, _dwell())

    assert sensors.IsObjectKnown(player) == 0
    assert sensors.IsObjectKnown(marker) == 0
    assert _identified == []


def test_scan_does_not_refire_for_known_contacts():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)
    s.AddObjectToSet(target, "Bird")

    sensors.ScanAllObjects().Play()
    sensor_contacts.tick(player, _dwell())
    sensors.ScanAllObjects().Play()   # second scan: contact already known
    sensor_contacts.tick(player, 2 * _dwell())

    assert _identified.count(target) == 1


def test_scan_with_no_ship_returns_empty_sequence():
    """A bare sensor subsystem (no attached ship) still returns a real, playable
    sequence — the unguarded SDK .Play() must be safe."""
    _subscribe()
    sensors = SensorSubsystem("Sensors")   # never attached to a ship
    seq = sensors.ScanAllObjects()
    assert seq is not None
    assert hasattr(seq, "Play")
    seq.Play()          # must not raise
    assert _identified == []


# --------------------------------------------------------------------------
# IdentifyObject (single-target "Scan Object" path)
# --------------------------------------------------------------------------

def test_identify_object_marks_one_known_and_broadcasts_once():
    _subscribe()
    s, player, sensors = _player_in_set(base_range=2000.0)
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)
    s.AddObjectToSet(target, "Bird")
    other = ShipClass_Create("BirdOfPrey")
    other.SetTranslateXYZ(1200.0, 0.0, 0.0)
    s.AddObjectToSet(other, "Other")

    sensors.IdentifyObject(target)
    sensor_contacts.tick(player, _dwell())

    assert sensors.IsObjectKnown(target) == 1
    assert sensors.IsObjectKnown(other) == 0     # only the named target
    assert _identified.count(target) == 1

    # De-dupe: a second identify is a no-op.
    sensors.IdentifyObject(target)
    sensor_contacts.tick(player, 2 * _dwell())
    assert _identified.count(target) == 1


def test_identify_object_none_is_safe():
    _subscribe()
    s, player, sensors = _player_in_set()
    sensors.IdentifyObject(None)   # must not raise
    assert _identified == []
