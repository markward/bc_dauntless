"""E6M3: the Khitomer's shuttles reach Savoy Station's bay check, the mission
counts each once, ShuttlesLanded runs, and its timer creates the transports
(sensor-probes final review, fix 2).

E6M3.CreateProximityCheck (E6M3.py:644-665) builds the station check with
SetTranslate(bay position) + ProximityManager.AddObject and never calls
AttachObject. ProximityCheck.Evaluate used to return early with no anchor, so
StationProximity never fired, ShuttlesLanded never ran and the transports
never arrived. An anchorless check now centres on its own position.

Setup: the Khitomer is moved into Savoy1 (set-reassignment idiom) at its
launch waypoint KhitLaunch2, and the mission's own KhitomerLaunchesShuttles()
runs (its E6M3_AI_Khit_Launch calls it on arrival). Shuttles spawn through
the SDK's real ShipScriptActions.LaunchObject, get HandleShuttle's AI and
check-list entry, and fly E6M3_AI_Shuttle (FollowWaypoints ShuttleWay1 ->
ShuttleWay2, which ends inside the 10 GU bay sphere). Measured headless: the
second shuttle lands ~23 s after the call (closest approaches 2.4-2.7 GU).

CreateTransports waits until more than two Cardassians are destroyed
(`g_iNumberCardsDestroyed <= 2` re-arms a 20 s timer). That battle is not
what this test is about, so the count is set directly once the shuttles have
landed; everything from ShuttlesLanded's timer onward is the mission's own.
"""
import App

from tests.helpers import headless_mission

E6M3 = "Maelstrom.Episode6.E6M3.E6M3"
SHUTTLES = ("Shuttle 1", "Shuttle 2", "Shuttle 3")


def test_shuttles_land_at_the_station_and_the_transports_arrive():
    mission, episode, game, mod = headless_mission.load(E6M3)
    savoy1 = App.g_kSetManager.GetSet("Savoy1")
    khit = App.ShipClass_GetObject(None, "Khitomer")
    assert khit is not None
    khit.ClearAI()
    khit.GetContainingSet().RemoveObjectFromSet("Khitomer")
    savoy1.AddObjectToSet(khit, "Khitomer")
    wp = savoy1.GetObject("KhitLaunch2").GetWorldLocation()
    khit.SetTranslateXYZ(wp.x, wp.y, wp.z)

    mod.KhitomerLaunchesShuttles(None)
    headless_mission.tick_until(lambda: mod.g_iShuttleAtStationCounter >= 2,
                                bound_s=300.0)
    # ShuttlesLanded fires on exactly == 2; the third lands later and every
    # shuttle is counted once (the delete-me skip), never twice.
    headless_mission.tick_until(lambda: mod.g_iShuttleAtStationCounter >= 3,
                                bound_s=60.0)
    headless_mission.tick(10.0)
    assert mod.g_iShuttleAtStationCounter == 3
    for name in SHUTTLES:
        shuttle = App.ShipClass_GetObject(savoy1, name)
        assert shuttle is not None and shuttle.IsDeleteMe() == 1

    # ShuttlesLanded's 4 s CreateTransports timer has fired and re-armed
    # (the Cardassian gate); open the gate and let the 20 s recheck create
    # the transports.
    assert App.ShipClass_GetObject(savoy1, "Transport 1") is None
    mod.g_iNumberCardsDestroyed = 3
    headless_mission.tick_until(
        lambda: App.ShipClass_GetObject(savoy1, "Transport 1") is not None,
        bound_s=25.0)
    assert App.ShipClass_GetObject(savoy1, "Transport 2") is not None
