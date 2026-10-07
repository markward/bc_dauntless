"""Sensor-model sub-project 3 end to end on the REAL E2M1 (same harness as
tests/integration/test_sensor_continuity_missions.py): a known Karoon stays on
the player's perceived list by name beyond sensor range, a nebula around the
PLAYER alone jams it off (the Karoon sits in clear space, so only the jam can
explain it), over-boost lists an unknown Karoon far away without identifying
it, the lock survives range and drops on jam, and a set change wipes memory.

Occlusion is switched off here: these tests prove memory and boost, and Beol4's
own asteroids could otherwise sit on the line and answer instead."""
import App
import MissionLib
import pytest

from engine import host_loop
from engine.appc import perception, sensor_occlusion
from engine.appc.sensor_detection import (can_detect, clear_undetectable_player_lock,
                                          effective_sensor_range)
from tests.integration.test_sdk_bridge_load import _fresh_world

E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


@pytest.fixture
def beol4_with_karoon():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    beol4 = App.g_kSetManager.GetSet("Beol4")
    if beol4.GetObject("Karoon") is None:
        mod.CreateBeolShips()
    karoon = App.ShipClass_GetObject(beol4, "Karoon")
    player = MissionLib.GetPlayer()
    player.GetContainingSet().RemoveObjectFromSet("player")
    beol4.AddObjectToSet(player, "player")
    sensor_occlusion.set_enabled(False)
    loc = karoon.GetWorldLocation()
    r = effective_sensor_range(player)
    assert r > 0.0
    player.SetTranslateXYZ(loc.x + 1.5 * r, loc.y, loc.z)   # Karoon is 1.5 ranges away
    return beol4, player, karoon


def _contact(player, ship):
    for c in perception.perceived_by(player):
        if c.ship is ship:
            return c
    return None


def test_known_karoon_stays_listed_by_name_beyond_range(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    c = _contact(player, karoon)
    assert c is None or c.perceivable is False         # unknown and out of range
    sensors.ForceObjectIdentified(karoon)
    c = _contact(player, karoon)
    assert c is not None and c.perceivable is True and c.identified is True


def test_a_nebula_around_the_player_alone_jams_memory(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    player.GetSensorSubsystem().ForceObjectIdentified(karoon)
    assert can_detect(player, karoon) is True
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "", "")
    p = player.GetWorldLocation()
    neb.AddNebulaSphere(p.x, p.y, p.z, 50.0)
    beol4.AddObjectToSet(neb, "JamNebula")
    assert can_detect(player, karoon) is False


def test_boost_lists_an_unknown_karoon_far_away(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    sensors._power_factor = 1.25
    c = _contact(player, karoon)
    assert c is not None and c.perceivable is True and c.identified is False
    assert sensors.IsObjectKnown(karoon) == 0


def test_lock_survives_range_and_drops_when_jammed(beol4_with_karoon):
    beol4, player, karoon = beol4_with_karoon
    player.GetSensorSubsystem().ForceObjectIdentified(karoon)
    player.SetTarget(karoon)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is karoon
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "", "")
    p = player.GetWorldLocation()
    neb.AddNebulaSphere(p.x, p.y, p.z, 50.0)
    beol4.AddObjectToSet(neb, "JamNebula")
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_set_change_wipes_memory_so_far_ships_stay_unlisted(beol4_with_karoon):
    from engine.appc import sensor_contacts
    beol4, player, karoon = beol4_with_karoon
    sensors = player.GetSensorSubsystem()
    sensors.ForceObjectIdentified(karoon)
    assert can_detect(player, karoon) is True
    vesuvi = App.g_kSetManager.GetSet("Vesuvi6")
    beol4.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    sensor_contacts.tick(player, 1.0)
    vesuvi.RemoveObjectFromSet("player")
    beol4.AddObjectToSet(player, "player")
    sensor_contacts.tick(player, 2.0)
    assert sensors.IsObjectKnown(karoon) == 0
    assert can_detect(player, karoon) is False
