"""E6M5: the Khitomer's four shuttles land on Tezle 1 and the mission counts
exactly four (sensor-probes Task 4 fix round 1).

The Planet.AttachObject fix made E6M5's "Tezle 1" ProximityCheck live for the
first time. Its handler ShuttleReachesPlanet (E6M5.py:2243) does
`g_iNumberShuttlesLanded += 1; SetDeleteMe(1)`, acts only on `== 4`, and never
removes the shuttle from the check. Our checks are level-triggered and a
delete-me object leaves its set only in the host's per-frame deletion pass, so
without the delete-me skip in ProximityCheck one shuttle counted several times
and the `== 4` branch could be stepped over. Headless there is no deletion
pass at all, so every landed shuttle stays inside the radius for the rest of
the test -- the strongest form of that window.

Setup: the Khitomer is moved into Tezle1 (set-reassignment idiom), 60 GU off
the planet's surface, and the mission's own KhitLaunchingShuttles() runs (its
E6M5_AI_Khit calls it on arrival). Shuttles spawn through the SDK's real
ShipScriptActions.LaunchObject and fly E6M5_AI_ShuttleLanding.
"""
import App

from tests.helpers import headless_mission

E6M5 = "Maelstrom.Episode6.E6M5.E6M5"
SHUTTLES = ("Shuttle 1", "Shuttle 2", "Shuttle 3", "Shuttle 4")


def test_four_shuttles_land_and_count_exactly_four():
    mission, episode, game, mod = headless_mission.load(E6M5)
    tezle1 = App.g_kSetManager.GetSet("Tezle1")
    khit = App.ShipClass_GetObject(None, "Khitomer")
    assert khit is not None
    khit.ClearAI()
    khit.GetContainingSet().RemoveObjectFromSet("Khitomer")
    tezle1.AddObjectToSet(khit, "Khitomer")
    planet = tezle1.GetObject("Tezle 1")
    c = planet.GetWorldLocation()
    khit.SetTranslateXYZ(c.x, c.y + planet.GetRadius() + 60.0, c.z)

    mod.KhitLaunchingShuttles()
    # Measured: the fourth lands ~25 s after launch at the AI's 5 GU/s.
    headless_mission.tick_until(lambda: mod.g_iNumberShuttlesLanded >= 4,
                                bound_s=60.0)
    for name in SHUTTLES:
        shuttle = App.ShipClass_GetObject(tezle1, name)
        assert shuttle is not None and shuttle.IsDeleteMe() == 1
    # Every shuttle is still in the set, inside the radius, delete-me pending:
    # further evaluations must not count any of them again.
    headless_mission.tick(10.0)
    assert mod.g_iNumberShuttlesLanded == 4
