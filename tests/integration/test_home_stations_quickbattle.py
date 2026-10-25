"""Quick Battle keeps owned objects (home stations and the like) in their set.

BC's ChangeRegion moves every ship in the player's set into the new battle
region; a placed home station would follow the player. The region-change tests
set `QB.g_sSelectedRegion` directly, standing in for BC's Change Combat Region
menu (the setup panel leaves it "" so the battle happens where the player is).
No coordinate is typed here: the station's saved location is read off the
station itself before the battle starts.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers.headless_mission import no_logged_failures  # noqa: E402,F401
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, world)


def _into_region(system, region):
    """Build `region` through BC's own module and move the player into it."""
    import App
    from tests.helpers.mapped_regions import load_region
    pSet = load_region(system, region)
    player = App.Game_GetCurrentGame().GetPlayer()
    name = player.GetName()
    old = player.GetContainingSet()
    if old is not None:
        old.RemoveObjectFromSet(name)
    pSet.AddObjectToSet(player, name)
    player.PlaceObjectByName("Player Start")
    player.UpdateNodeOnly()
    return pSet


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _loc(obj):
    w = obj.GetWorldLocation()
    return (w.x, w.y, w.z)


def _start_region_change(hl, panel, QB, region):
    QB.g_sSelectedRegion = region
    _do(panel, "add:Warbird")
    _go(hl, panel)


def test_a_battle_at_starbase_12_includes_the_station(world):
    hl, _c, panel, QB = world
    from engine.systems import home_stations as hs
    _into_region("TauCeti", "Starbase12")
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.g_pSet.GetName() == "Starbase12"
    station = QB.g_pSet.GetObject("Starbase 12")
    assert station is not None
    assert hs.home_station_of(station) is not None


def test_a_region_change_leaves_the_station_home(world):
    hl, _c, panel, QB = world
    import App
    pSet = _into_region("TauCeti", "Starbase12")
    station = pSet.GetObject("Starbase 12")
    saved = _loc(station)
    _start_region_change(hl, panel, QB, "Belaruz1")
    assert _player().GetContainingSet().GetName() == "Belaruz1"
    home = App.g_kSetManager.GetSet("Starbase12")
    assert home.GetObject("Starbase 12") is station
    assert station.GetContainingSet() is home
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert App.g_kSetManager.GetSet("Belaruz1").GetObject("Starbase 12") is None


def test_a_dupe_region_change_keeps_the_station_in_its_set(
        world, no_logged_failures):  # noqa: F811
    hl, _c, panel, QB = world
    import App
    old = _into_region("TauCeti", "Starbase12")
    station = old.GetObject("Starbase 12")
    saved = _loc(station)
    _start_region_change(hl, panel, QB, "Belaruz4")
    assert _player().GetContainingSet().GetName() == "Belaruz4"
    assert station.GetContainingSet() is old
    assert old.GetObject("Starbase 12") is station
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert App.g_kSetManager.GetSet("Belaruz4").GetObject("Starbase 12") is None


class _TestPatrolOwner:
    name = "test_patrol"

    def rebuild(self, old, record):
        return None

    def after_rebuild(self, new, record) -> None:
        pass


def test_any_owned_object_stays_home(world):
    hl, _c, panel, QB = world
    import App
    import loadspacehelper
    from engine.systems import owners
    owners.register(_TestPatrolOwner())
    try:
        pSet = _into_region("TauCeti", "Starbase12")
        patrol = loadspacehelper.CreateShip("Galor", pSet, "Patrol 1", "")
        owners.tag(patrol, "test_patrol", "Patrol 1")
        _start_region_change(hl, panel, QB, "Belaruz1")
        assert _player().GetContainingSet().GetName() == "Belaruz1"
        assert App.g_kSetManager.GetSet("Starbase12").GetObject("Patrol 1") is patrol
        assert App.g_kSetManager.GetSet("Belaruz1").GetObject("Patrol 1") is None
    finally:
        owners._owners.pop("test_patrol", None)
