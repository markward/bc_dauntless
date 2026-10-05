"""SensorSubsystem bands + IsObjectVisible, per BC's RE'd algorithm
(sensor-subsystem.md: IsObjectNear = half range, IsObjectFar = full range,
pure distance; IsObjectVisible's ordered gates, probes omitted)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem, CloakingSubsystem
from engine.appc.sets import SetClass


def _player_in_set(base_range=2000.0):
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    return s, player, sensors


def _ship_at(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


def test_get_sensor_range_is_the_one_rule():
    from engine.appc.sensor_detection import effective_sensor_range
    s, player, sensors = _player_in_set(2000.0)
    assert sensors.GetSensorRange() == effective_sensor_range(player) == 2000.0


def test_near_is_half_range_far_is_full_range():
    s, player, sensors = _player_in_set(2000.0)
    near = _ship_at(s, "near", 999.0)
    mid = _ship_at(s, "mid", 1500.0)
    out = _ship_at(s, "out", 2001.0)
    assert (sensors.IsObjectNear(near), sensors.IsObjectFar(near)) == (1, 1)
    assert (sensors.IsObjectNear(mid), sensors.IsObjectFar(mid)) == (0, 1)
    assert (sensors.IsObjectNear(out), sensors.IsObjectFar(out)) == (0, 0)


def test_bands_follow_the_near_fraction_dial():
    from engine.appc import sensor_dials
    s, player, sensors = _player_in_set(2000.0)
    mid = _ship_at(s, "mid", 1500.0)
    sensor_dials._dials["near_fraction"] = 0.8
    assert sensors.IsObjectNear(mid) == 1


def test_other_set_is_neither_near_nor_far():
    s, player, sensors = _player_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    assert sensors.IsObjectNear(ship) == 0 and sensors.IsObjectFar(ship) == 0


def test_visible_in_range_invisible_beyond_unless_known():
    s, player, sensors = _player_in_set(2000.0)
    inside = _ship_at(s, "in", 1500.0)
    beyond = _ship_at(s, "beyond", 5000.0)
    assert sensors.IsObjectVisible(inside) == 1
    assert sensors.IsObjectVisible(beyond) == 0
    sensors.AddKnownObject(beyond)          # BC sensor memory
    assert sensors.IsObjectVisible(beyond) == 1


def test_fully_cloaked_is_never_visible():
    s, player, sensors = _player_in_set(2000.0)
    ship = _ship_at(s, "cloaked", 10.0)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    ship.GetCloakingSubsystem().InstantCloak()
    sensors.AddKnownObject(ship)
    assert sensors.IsObjectVisible(ship) == 0


def test_over_boost_sees_the_whole_set():
    s, player, sensors = _player_in_set(2000.0)
    beyond = _ship_at(s, "beyond", 50000.0)
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(beyond) == 1


def test_offline_sensors_see_nothing():
    s, player, sensors = _player_in_set(2000.0)
    inside = _ship_at(s, "in", 10.0)
    sensors.AddKnownObject(inside)
    sensors._power_factor = 0.0
    assert sensors.GetSensorRange() == 0.0
    assert sensors.IsObjectVisible(inside) == 0


def test_nebula_jam_cancels_memory_and_boost(monkeypatch):
    from engine.appc import contact_index
    s, player, sensors = _player_in_set(2000.0)
    beyond = _ship_at(s, "beyond", 50000.0)
    sensors.AddKnownObject(beyond)

    class _Neb:
        def IsObjectInNebula(self, obj):
            return 1 if obj is beyond else 0

    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: (_Neb(),))
    assert sensors.IsObjectVisible(beyond) == 0      # memory blocked
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(beyond) == 0      # boost blocked
    near = _ship_at(s, "near", 100.0)
    assert sensors.IsObjectVisible(near) == 1        # range test still applies
