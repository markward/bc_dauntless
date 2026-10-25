"""A mission's own loadspacehelper.CreateShip for a home station returns the
station the region hook already placed, instead of building a second one.

The set comes from BC's own region module (load_region), so the station under
test is the one the region hook placed. No coordinate is typed here: the
mission point is built from the station's own location.
"""
import pytest

import App
from engine.appc import ship_death
from engine.appc.math import TGPoint3
from engine.systems import home_stations as hs
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region


@pytest.fixture
def sb12():
    _fresh_world()
    hs.reset()
    pSet = load_region("TauCeti", "Starbase12")
    station = App.ShipClass_GetObject(pSet, "Starbase 12")
    assert station is not None
    assert hs.home_station_of(station) is not None
    yield pSet, station
    hs.reset()


def _offset_from(obj, dx):
    loc = obj.GetWorldLocation()
    return loc.x + dx, loc.y, loc.z


def _close(a, b):
    return (abs(a.x - b.x) < 1e-4 and abs(a.y - b.y) < 1e-4
            and abs(a.z - b.z) < 1e-4)


def test_create_ship_returns_the_home_station_and_places_it(sb12):
    import loadspacehelper
    pSet, station = sb12
    wp = App.Waypoint_Create("Elsewhere", "Starbase12", None)
    wp.SetTranslateXYZ(*_offset_from(station, 50.0))
    want = TGPoint3(*_offset_from(station, 50.0))
    got = loadspacehelper.CreateShip("FedStarbase", pSet, "Starbase 12",
                                     "Elsewhere", 1)
    assert got is station
    assert _close(station.GetWorldLocation(), wp.GetWorldLocation())
    assert _close(station.GetWorldLocation(), want)
    assert sum(1 for n in pSet._objects if n == "Starbase 12") == 1


@pytest.mark.parametrize("script, name",
                         [("Galaxy", "Starbase 12"), ("FedStarbase", "Other")])
def test_anything_else_takes_bcs_path(sb12, script, name):
    import loadspacehelper
    pSet, station = sb12
    got = loadspacehelper.CreateShip(script, pSet, name, "")
    assert got is not station


def test_a_dying_station_is_not_reused(sb12):
    pSet, station = sb12
    assert hs.reusable("FedStarbase", pSet, "Starbase 12") is station
    ship_death.begin(station)
    assert hs.reusable("FedStarbase", pSet, "Starbase 12") is None


def test_the_hook_is_installed_by_the_sdk_loader(sb12):
    import loadspacehelper
    assert hasattr(loadspacehelper.CreateShip, "_dauntless_home_station_orig")


def test_both_sdk_loaders_route_loadspacehelper():
    """The runtime loader (tools/mission_harness.py) and its test twin
    (tests/conftest.py) must gate identically: the tests only run the twin,
    so without this the runtime loader could drop the hook unseen."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    gate = '_qual == "loadspacehelper"'
    for rel in ("tools/mission_harness.py", "tests/conftest.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert gate in text, f"{rel} does not route loadspacehelper"


def test_installing_the_hook_twice_wraps_once(sb12):
    import loadspacehelper
    wrapper = loadspacehelper.CreateShip
    assert hs.install_create_ship_hook(loadspacehelper) is False
    assert loadspacehelper.CreateShip is wrapper
