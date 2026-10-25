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


def _rot(obj):
    return obj.GetWorldRotation().as_tuple()


def _proximity_holds(pSet, obj):
    """`obj` is in the set's proximity index: the set-member read-through or a
    registered (AddObject/UpdateObject) entry."""
    return any(o is obj for o in pSet.GetProximityManager()._candidates())


def _crowd_every_spot_once(monkeypatch):
    """Make BC's ChangeRegion find each ship's first spot occupied, so its
    ChooseNewLocation loop really moves every ship (our IsLocationEmptyTG is a
    stub that always answers 1). `seen` holds the points so an id is never
    reused for a new one."""
    from engine.appc.sets import SetClass
    seen = []

    def IsLocationEmptyTG(self, point, radius, flag=1):
        if any(p is point for p in seen):
            return 1
        seen.append(point)
        return 0

    monkeypatch.setattr(SetClass, "IsLocationEmptyTG", IsLocationEmptyTG)


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


def test_a_region_change_leaves_the_station_home(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    pSet = _into_region("TauCeti", "Starbase12")
    station = pSet.GetObject("Starbase 12")
    saved, saved_rot = _loc(station), _rot(station)
    _crowd_every_spot_once(monkeypatch)
    _start_region_change(hl, panel, QB, "Belaruz1")
    assert _player().GetContainingSet().GetName() == "Belaruz1"
    home = App.g_kSetManager.GetSet("Starbase12")
    battle = App.g_kSetManager.GetSet("Belaruz1")
    assert home.GetObject("Starbase 12") is station
    assert station.GetContainingSet() is home
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert _rot(station) == pytest.approx(saved_rot, abs=1e-6)
    assert battle.GetObject("Starbase 12") is None
    # BC's loop UpdateObject'ed the station into the battle set's proximity
    # manager; it must not linger there, and its home set's must know it.
    assert not _proximity_holds(battle, station)
    assert station not in battle.GetProximityManager()._objects
    assert _proximity_holds(home, station)


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


def test_a_failing_region_change_still_returns_the_station(world, monkeypatch):
    """The original moves and turns the station into the battle set, then
    raises: the station still goes home at its pose, and the exception still
    reaches the caller."""
    _hl, _c, _panel, QB = world
    import App
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.quickbattle import sim_restore
    from tests.helpers.mapped_regions import load_region
    home = _into_region("TauCeti", "Starbase12")
    station = home.GetObject("Starbase 12")
    saved, saved_rot = _loc(station), _rot(station)
    turned = TGMatrix3().MakeZRotation(1.0)
    assert turned.as_tuple() != pytest.approx(saved_rot, abs=1e-3)
    battle = load_region("Belaruz", "Belaruz1")

    def failing_change_region():
        home.RemoveObjectFromSet("Starbase 12")
        battle.AddObjectToSet(station, "Starbase 12")
        station.SetTranslate(TGPoint3(saved[0] + 50.0, saved[1], saved[2]))
        station.SetMatrixRotation(turned)
        station.UpdateNodeOnly()
        battle.GetProximityManager().UpdateObject(station)
        raise RuntimeError("region module blew up")

    monkeypatch.setattr(QB, "ChangeRegion", failing_change_region)
    assert sim_restore.install(QB) is True
    with pytest.raises(RuntimeError, match="region module blew up"):
        QB.ChangeRegion()
    assert station.GetContainingSet() is home
    assert home.GetObject("Starbase 12") is station
    assert battle.GetObject("Starbase 12") is None
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert _rot(station) == pytest.approx(saved_rot, abs=1e-6)
    assert station not in battle.GetProximityManager()._objects
    assert App.g_kSetManager.GetSet("Starbase12") is home


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
