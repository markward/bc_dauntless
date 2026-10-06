"""SensorSubsystem bands + IsObjectVisible, per BC's RE'd algorithm
(sensor-subsystem.md: IsObjectNear = half range, IsObjectFar = full range,
pure distance; IsObjectVisible = BC's set gate, then the one rule
sensor_detection.can_detect -- sub-project 3)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem, CloakingSubsystem
from engine.appc.sets import SetClass
from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)


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


def test_fully_cloaked_follows_the_cloak_contest():
    """IsObjectVisible gives the list's answer: a fully cloaked ship inside
    the cloak bubble is visible (BC: never -- our stage-4 contest), outside it
    is not, and neither memory nor over-boost reveals it."""
    from engine.appc.sensor_detection import (CLOAK_DETECTION_BASE_GU,
                                              CLOAK_RANGE_FACTOR)
    s, player, sensors = _player_in_set(2000.0)
    bubble = CLOAK_DETECTION_BASE_GU + 2000.0 * CLOAK_RANGE_FACTOR
    inside = _ship_at(s, "inside", bubble * 0.5)
    outside = _ship_at(s, "outside", bubble * 3.0)
    for ship in (inside, outside):
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        ship.GetCloakingSubsystem().InstantCloak()
        sensors.AddKnownObject(ship)
    assert sensors.IsObjectVisible(inside) == 1
    assert sensors.IsObjectVisible(outside) == 0
    sensors._power_factor = 1.25
    assert sensors.IsObjectVisible(outside) == 0


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


def test_is_object_visible_matches_can_detect(monkeypatch):
    from engine.appc import contact_index
    from engine.appc.sensor_detection import can_detect
    s, player, sensors = _player_in_set(2000.0)
    ships = [_ship_at(s, "n%d" % i, x)
             for i, x in enumerate((10.0, 1500.0, 2500.0, 50000.0))]
    sensors.AddKnownObject(ships[2])

    class _Neb:
        def IsObjectInNebula(self, obj):
            return 1 if obj is ships[3] else 0

    for power in (1.0, 1.25):
        sensors._power_factor = power
        for jam in (False, True):
            monkeypatch.setattr(contact_index, "nebulae_in",
                                (lambda pSet: (_Neb(),)) if jam else (lambda pSet: ()))
            for ship in ships:
                assert sensors.IsObjectVisible(ship) == (1 if can_detect(player, ship) else 0), (
                    power, jam, ship.GetName())


def test_is_object_visible_keeps_bcs_set_gate():
    # can_detect's range branch has no set check (cross-set torpedoes); the
    # SDK surface must still refuse another set's object at close range.
    s, player, sensors = _player_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    other.AddObjectToSet(ship, "elsewhere")
    assert sensors.IsObjectVisible(ship) == 0


def test_is_object_visible_gets_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, player, sensors = _player_in_set(2000.0)
    near = _ship_at(s, "near", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensors.IsObjectVisible(near) == 0
