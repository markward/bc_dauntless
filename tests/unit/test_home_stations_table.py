import json

import pytest

import App
from engine.appc import placement
from engine.systems import home_stations as hs
from tests.helpers import headless_mission as hm
from tests.helpers.fresh_world import _fresh_world

ROW = {"set": "S", "name": "N", "script": "FedStarbase", "point": "P",
       "point_module": "Systems.Starbase12.Starbase12"}


def _write(tmp_path, doc):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(doc))
    return p


def test_table_holds_the_thirteen_stations():
    rows = hs.table()
    assert len(rows) == 13
    assert len({(s.set_name, s.name) for s in rows}) == 13
    sb = hs.stations_for_set("Starbase12")
    assert [(s.name, s.script, s.point, s.point_module) for s in sb] == [
        ("Starbase 12", "FedStarbase", "Starbase12 Location",
         "Systems.Starbase12.Starbase12")]
    assert [s.name for s in hs.stations_for_set("DryDock")] == [
        "Dry Dock", "Dry Dock2", "Dry Dock3", "Station"]
    assert hs.stations_for_set("Belaruz1") == ()


@pytest.mark.parametrize("doc, word", [
    ({"format": 1, "stations": [dict(ROW, colour="red")]}, "colour"),
    ({"format": 1, "stations": [{k: v for k, v in ROW.items() if k != "point"}]}, "point"),
    ({"format": 1, "stations": [ROW, ROW]}, "duplicate"),
    ({"format": 2, "stations": [ROW]}, "format"),
    ({"format": 1, "stations": [ROW], "extra": 1}, "extra"),
])
def test_bad_tables_are_rejected(tmp_path, doc, word):
    with pytest.raises(ValueError, match=word):
        hs.load_table(_write(tmp_path, doc))


@pytest.fixture
def world():
    _fresh_world()


def _row(set_name, name):
    return next(s for s in hs.stations_for_set(set_name) if s.name == name)


def _close(a, b):
    return (abs(a.x - b.x) < 1e-4 and abs(a.y - b.y) < 1e-4
            and abs(a.z - b.z) < 1e-4)


def test_read_point_from_a_region_file(world):
    import Systems.Starbase12.Starbase12 as region
    region.Initialize()
    pset = App.g_kSetManager.GetSet("Starbase12")
    got = hs.read_point(_row("Starbase12", "Starbase 12"), pset)
    assert got is not None
    loc, _rot = got
    assert _close(loc, hm.placement_location("Starbase12", "Starbase12 Location"))


def test_read_point_from_a_mission_file_matches_the_sdk_and_leaves_no_trace(world):
    import Systems.DryDock.DryDock as region
    region.Initialize()
    pset = App.g_kSetManager.GetSet("DryDock")
    reg_before = dict(placement._waypoint_registry)
    sets_before = {n: dict(s._objects) for n, s in App.g_kSetManager._sets.items()}

    got = hs.read_point(_row("DryDock", "Dry Dock2"), pset)

    assert dict(placement._waypoint_registry) == reg_before
    assert {n: dict(s._objects)
            for n, s in App.g_kSetManager._sets.items()} == sets_before
    assert got is not None
    loc, rot = got

    scratch = App.SetClass_Create()
    App.g_kSetManager.AddSet(scratch, "OracleScratch")
    import Maelstrom.Episode1.E1M1.Dock_P as dock_p
    dock_p.LoadPlacements("OracleScratch")
    wp = scratch.GetObject("DryDock2")
    assert _close(loc, wp.GetWorldLocation())
    for i in range(3):
        assert _close(rot.GetCol(i), wp.GetWorldRotation().GetCol(i))


def test_read_point_missing_point_is_none(world):
    import Systems.Starbase12.Starbase12 as region
    region.Initialize()
    pset = App.g_kSetManager.GetSet("Starbase12")
    st = hs.Station("Starbase12", "X", "FedStarbase", "No Such Point",
                    "Systems.Starbase12.Starbase12")
    assert hs.read_point(st, pset) is None
