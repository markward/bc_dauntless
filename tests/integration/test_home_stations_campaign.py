"""Campaign missions reuse the home stations their regions already placed.

Each mission is loaded the way the dev picker loads it (headless_mission), so
the region hook places the stations as the mission's sets are built, and the
mission's own loadspacehelper.CreateShip for a station must return that object
instead of building a second one. A station still marked by home_stations is
the region hook's object, not one the mission built. No coordinate is typed
here: E8M2's point is read from the set the mission loaded.
"""
import App
from engine.systems import home_stations as hs
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401 (fixture)


def _named(pSet, name):
    return [o for o in pSet._objects.values() if o.GetName() == name]


def _the_marked_station(set_name, name):
    pSet = App.g_kSetManager.GetSet(set_name)
    assert pSet is not None, set_name
    found = _named(pSet, name)
    assert len(found) == 1, (set_name, name, len(found))
    assert hs.home_station_of(found[0]) is not None, (set_name, name)
    return found[0]


def test_e1m1_reuses_starbase_and_dry_docks(no_logged_failures):
    hs.reset()
    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    for set_name, name in (("Starbase12", "Starbase 12"),
                           ("DryDock", "Dry Dock"),
                           ("DryDock", "Dry Dock2"),
                           ("DryDock", "Dry Dock3"),
                           ("DryDock", "Station")):
        _the_marked_station(set_name, name)


def test_e7m3_reuses_the_resupply_station_on_arrival(no_logged_failures):
    hs.reset()
    _mission, _episode, _game, mod = hm.load("Maelstrom.Episode7.E7M3.E7M3")
    st = _the_marked_station("Ascella3", "Resupply Station")

    ascella3 = App.g_kSetManager.GetSet("Ascella3")
    player = App.Game_GetCurrentPlayer()
    assert player is not None
    old = player.GetContainingSet()
    assert old is not ascella3
    old.RemoveObjectFromSet("player")
    ascella3.AddObjectToSet(player, "player")
    hm.tick(1.0)

    assert mod.bAscella3Arrive
    assert ascella3.GetObject("Resupply Station") is st
    assert len(_named(ascella3, "Resupply Station")) == 1
    handlers = st._handlers.get(App.ET_SUBSYSTEM_COMPLETELY_DISABLED, [])
    assert any(h.endswith(".DisableSystemHandler") for h in handlers), handlers


def test_e8m2_moves_starbase_12_to_its_mission_point(no_logged_failures):
    hs.reset()
    hm.load("Maelstrom.Episode8.E8M2.E8M2")
    st = _the_marked_station("Starbase12", "Starbase 12")
    want = hm.placement_location("Starbase12", "Starbase Location")
    assert want is not None
    got = st.GetWorldLocation()
    assert (abs(got.x - want.x) < 1e-4 and abs(got.y - want.y) < 1e-4
            and abs(got.z - want.z) < 1e-4), ((got.x, got.y, got.z),
                                              (want.x, want.y, want.z))
