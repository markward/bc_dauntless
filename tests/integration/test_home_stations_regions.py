"""Home stations are placed whenever their region's set is built.

Every set is built through BC's own region module
(tests/helpers/mapped_regions.load_region), so the region hook runs exactly as
it does in play. No coordinate is typed here: each station's expected position
is read independently from the SDK -- the set's own waypoint for a region
point, or a scratch-set LoadPlacements of the mission file for a mission point.
"""
import dataclasses
import importlib
import math

import pytest

import App
from engine.appc import placement, ship_death
from engine.appc.math import TGPoint3
from engine.systems import home_stations as hs
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region

REGIONS = [
    ("TauCeti", "Starbase12"),
    ("TauCeti", "DryDock"),
    ("Chambana", "Chambana1"),
    ("Cebalrai", "Cebalrai2"),
    ("Ascella", "Ascella3"),
    ("Alioth", "Alioth6"),
    ("Prendel", "Prendel3"),
    ("Biranu", "Biranu2"),
    ("Savoy", "Savoy1"),
    ("Albirea", "Albirea3"),
]
_IDS = [r for _s, r in REGIONS]


@pytest.fixture(autouse=True)
def world():
    _fresh_world()
    hs.reset()
    yield
    hs.reset()


def _oracle_location(row, pSet):
    """The point's world location, read straight from the SDK file."""
    if row.point_module == pSet.GetRegionModule():
        return pSet.GetObject(row.point).GetWorldLocation()
    saved = dict(placement._waypoint_registry)
    scratch = App.SetClass_Create()
    App.g_kSetManager.AddSet(scratch, "OracleScratch")
    try:
        importlib.import_module(row.point_module).LoadPlacements("OracleScratch")
        loc = scratch.GetObject(row.point).GetWorldLocation()
        return TGPoint3(loc.x, loc.y, loc.z)
    finally:
        App.g_kSetManager.DeleteSet("OracleScratch")
        placement._waypoint_registry.clear()
        placement._waypoint_registry.update(saved)


def _close(a, b):
    return (abs(a.x - b.x) < 1e-4 and abs(a.y - b.y) < 1e-4
            and abs(a.z - b.z) < 1e-4)


def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _row(set_name, name):
    return next(s for s in hs.stations_for_set(set_name) if s.name == name)


def _named(pSet, name):
    return [o for o in pSet._objects.values() if o.GetName() == name]


def _destroy(ship):
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)


@pytest.mark.parametrize("system, region", REGIONS, ids=_IDS)
def test_every_station_is_placed_with_its_script_at_its_point(system, region):
    import MissionLib
    pSet = load_region(system, region)
    rows = hs.stations_for_set(region)
    assert rows, f"no table rows for {region}"
    mission = MissionLib.GetMission()
    groups = (mission.GetFriendlyGroup(), mission.GetEnemyGroup(),
              mission.GetNeutralGroup())
    for row in rows:
        obj = App.ShipClass_GetObject(pSet, row.name)
        assert obj is not None, f"{region}/{row.name} not placed"
        assert obj.GetScript() == "ships." + row.script
        assert hs.home_station_of(obj) == row
        want = _oracle_location(row, pSet)
        got = obj.GetWorldLocation()
        assert _close(got, want), (row.name, (got.x, got.y, got.z),
                                   (want.x, want.y, want.z))
        for group in groups:
            assert not group.IsNameInGroup(row.name), (
                f"{row.name} joined a mission group")


@pytest.mark.parametrize("system, region", REGIONS, ids=_IDS)
def test_no_station_sits_inside_a_planet(system, region):
    pSet = load_region(system, region)
    planets = pSet.GetClassObjectList(App.CT_PLANET)
    for row in hs.stations_for_set(region):
        st = App.ShipClass_GetObject(pSet, row.name)
        assert st is not None
        for planet in planets:
            gap = _dist(planet.GetWorldLocation(), st.GetWorldLocation())
            assert gap > planet.GetRadius() + st.GetRadius(), (
                f"{row.name} sits inside {planet.GetName()}")


def test_rebuilding_a_region_gives_one_station():
    first_set = load_region("TauCeti", "Starbase12")
    first = App.ShipClass_GetObject(first_set, "Starbase 12")
    assert first is not None
    load_region("TauCeti", "Starbase12")
    live = App.g_kSetManager.GetSet("Starbase12")
    assert len(_named(live, "Starbase 12")) == 1
    assert first.GetContainingSet() is not live


def test_a_destroyed_station_is_not_placed_again_until_reset():
    row = _row("Starbase12", "Starbase 12")
    pSet = load_region("TauCeti", "Starbase12")
    st = App.ShipClass_GetObject(pSet, "Starbase 12")
    assert hs.is_standing(row) is True
    _destroy(st)
    assert hs.is_standing(row) is False

    pSet = load_region("TauCeti", "Starbase12")
    assert _named(pSet, "Starbase 12") == []

    hs.reset()
    pSet = load_region("TauCeti", "Starbase12")
    assert len(_named(pSet, "Starbase 12")) == 1


def test_two_outposts_are_independent():
    cebalrai = load_region("Cebalrai", "Cebalrai2")
    _destroy(App.ShipClass_GetObject(cebalrai, "Outpost"))
    assert hs.is_standing(_row("Cebalrai2", "Outpost")) is False
    assert hs.is_standing(_row("Prendel3", "Outpost")) is True

    prendel = load_region("Prendel", "Prendel3")
    st = App.ShipClass_GetObject(prendel, "Outpost")
    assert st is not None
    assert hs.home_station_of(st) == _row("Prendel3", "Outpost")


def test_a_bad_point_module_skips_only_that_station(monkeypatch, capfd):
    real = hs.table()
    bad = tuple(
        dataclasses.replace(s, point_module="Maelstrom.NoSuchModule_P")
        if (s.set_name, s.name) == ("DryDock", "Dry Dock2") else s
        for s in real)
    monkeypatch.setattr(hs, "table", lambda: bad)
    capfd.readouterr()

    pSet = load_region("TauCeti", "DryDock")

    for name in ("Dry Dock", "Dry Dock3", "Station"):
        assert App.ShipClass_GetObject(pSet, name) is not None, name
    assert App.ShipClass_GetObject(pSet, "Dry Dock2") is None
    out = capfd.readouterr()
    lines = [ln for ln in (out.out + out.err).splitlines()
             if ln.startswith("[home-stations]")]
    assert len(lines) == 1, lines
    assert "Dry Dock2" in lines[0]


def test_a_mission_change_forgets_destroyed_stations():
    from engine import host_loop
    row = _row("Starbase12", "Starbase 12")
    pSet = load_region("TauCeti", "Starbase12")
    _destroy(App.ShipClass_GetObject(pSet, "Starbase 12"))
    assert hs.is_standing(row) is False
    host_loop._reset_system_loader_state()
    assert hs.is_standing(row) is True
