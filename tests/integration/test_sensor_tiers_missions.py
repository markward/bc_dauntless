"""Missions that depend on the two tiers (sensor-tiers spec, Testing).

E2M2's `ShipInSensorRange` is a broadcast handler registered unconditionally
from `SetupEventHandlers(pMission)`, which `Initialize(pMission)` calls at
mission load (before the player ever reaches Serris 2) -- so it is live from
the moment `host_loop._init_mission` returns, with no extra mission-state
driving required.

E1M2's dwell-deferred identification is already covered by
`test_e1m2_scan_area.py::test_area_scan_advances_mission`; this file adds the
narrower "nothing is known before the dwell, everything is known after it"
check against a fresh contact, independent of the Scan Area button.

E8M1's `DetectingObject`/`DetectingKessok` registration
(`BelaruzEvents`, E8M1.py:2199) is reached only at the END of
`Belaruz1Arrive()`'s ~25-beat bridge cutscene, itself queued from an
`EnterSet` handler gated on the player's set becoming "Belaruz1" -- there is
no mission-state shortcut to it the way `test_campaign_warp_transitions.py`
drives a warp. Driving that whole cutscene through
`MissionLib.QueueActionToPlay` headlessly (dozens of `AT_SAY_LINE` character
actions) is far outside this task's scope, so per the brief this is left as
a live-check item (see the report) instead of a headless test.
"""
import App
import MissionLib
from engine import host_loop
from engine.appc import sensor_contacts
from tests.integration.test_sdk_bridge_load import _fresh_world


def _init(module):
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(module)
    return mod


def _ship_in_player_set(name, offset_gu):
    player = MissionLib.GetPlayer()
    loc = player.GetWorldLocation()
    import loadspacehelper
    ship = loadspacehelper.CreateShip("Galor", player.GetContainingSet(), name, None)
    ship.SetTranslateXYZ(loc.x + offset_gu, loc.y, loc.z)
    return player, ship


def test_e2m2_ships_on_sensors_comes_from_far_proximity_not_identify():
    mod = _init("Maelstrom.Episode2.E2M2.E2M2")
    name = mod.g_lShipNames[0]
    player, ship = _ship_in_player_set(name, 0.0)
    r = player.GetSensorSubsystem().GetSensorRange()
    ship.SetTranslateXYZ(player.GetWorldLocation().x + r * 0.75,
                         player.GetWorldLocation().y, player.GetWorldLocation().z)
    mod.g_bShipsOnSensors = 0
    sensor_contacts.tick(player, 1000.0)
    assert mod.g_bShipsOnSensors == 1
    assert player.GetSensorSubsystem().IsObjectKnown(ship) == 0


def test_contact_identified_only_after_dwell_in_mission():
    mod = _init("Maelstrom.Episode1.E1M2.E1M2")
    player, ship = _ship_in_player_set("Test Contact", 50.0)
    sensors = player.GetSensorSubsystem()
    sensor_contacts.tick(player, 1000.0)
    assert sensors.IsObjectKnown(ship) == 0
    sensor_contacts.tick(player, 1000.0 + sensors.GetIdentificationTime())
    assert sensors.IsObjectKnown(ship) == 1
