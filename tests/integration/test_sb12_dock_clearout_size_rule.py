"""SDK docking clear-out at Starbase 12 under BC's size rule for near queries.

`AI/Compound/DockWithStarbase.SetupDockPositions` asks the set's
ProximityManager for everything within 300 GU of the "Docking Entry" placement
and SetTranslate's each object (other than the docking ship and the starbase)
out to 300 GU or more. GetNearObjects now keeps an object when
`|location - point| <= r + max(GetRadius(), 0)` (surface reach, not centre).
The danger: a big body whose surface reaches the entry, New Holland, being
shoved. Its real geometry says it is not.

Geometry is the real E1M1 load (headless_mission): the Starbase12 set, the
station, New Holland, and the "Docking Entry" placement the SDK's own
`MakeWaypoints` builds from the fedstarbase hardpoint. Headless ships keep
radius 0 (no models load), so the tests seed radii themselves: the station gets
296.0 (its live radius, seeded from the model at realise), and the probe ships
get the radii each case needs.
"""
import math

import pytest

import App
import loadspacehelper

STATION_RADIUS_GU = 296.0
CLEAR_GU = 300.0


def _xyz(o):
    p = o.GetWorldLocation()
    return (p.x, p.y, p.z)


def _dist(a, b):
    return math.dist(a, b)


@pytest.fixture
def scene():
    from tests.helpers import headless_mission as hm
    import AI.Compound.DockWithStarbase as dock

    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    pSet = App.g_kSetManager.GetSet("Starbase12")
    station = App.ShipClass_GetObject(pSet, "Starbase 12")
    assert station is not None
    station.SetRadius(STATION_RADIUS_GU)
    dock.MakeWaypoints(station)
    entry = App.PlacementObject_GetObject(pSet, "Docking Entry")
    assert entry is not None
    holland = pSet.GetObject("New Holland")
    assert holland is not None

    docker = loadspacehelper.CreateShip("Galaxy", pSet, "Docker", "")
    assert not App.IsNull(docker)
    docker.SetRadius(2.0)

    e = _xyz(entry)
    s = _xyz(station)
    away = tuple(a - b for a, b in zip(e, s))
    n = math.sqrt(sum(c * c for c in away))
    away = tuple(c / n for c in away)

    def put_shuttle(name, distance, radius, direction=away):
        ship = loadspacehelper.CreateShip("Shuttle", pSet, name, "")
        assert not App.IsNull(ship)
        ship.SetRadius(radius)
        ship.SetTranslateXYZ(*(e[i] + direction[i] * distance for i in range(3)))
        ship.UpdateNodeOnly()
        return ship

    class S:
        pass
    sc = S()
    sc.set, sc.station, sc.entry, sc.holland, sc.docker = (
        pSet, station, entry, holland, docker)
    sc.e, sc.away, sc.put = e, away, put_shuttle
    sc.dock = dock
    return sc


def test_dock_clearout_leaves_new_holland_in_place(scene):
    before_nh, before_sb = _xyz(scene.holland), _xyz(scene.station)
    # not vacuous: the sweep runs with the station and planet both in the set
    assert scene.holland.GetRadius() > 0.0

    scene.dock.SetupDockPositions(scene.docker, "Starbase 12")

    assert _xyz(scene.holland) == before_nh
    assert _xyz(scene.station) == before_sb


def test_dock_clearout_moves_a_ship_near_the_entry(scene):
    ship = scene.put("Bystander", 100.0, 1.0)
    assert _dist(_xyz(ship), scene.e) == pytest.approx(100.0)

    scene.dock.SetupDockPositions(scene.docker, "Starbase 12")

    d = _dist(_xyz(ship), scene.e)
    assert d >= CLEAR_GU - 1e-6
    assert d == pytest.approx(CLEAR_GU, abs=1e-3)  # first empty ring, no extra 100


def test_dock_clearout_reaches_by_surface(scene):
    # Opposite sides of the entry so neither sits in the other's way.
    other = tuple(-c for c in scene.away)
    reached = scene.put("Reached", 350.0, 100.0)             # surface at 250
    missed = scene.put("Missed", 450.0, 100.0, other)        # surface at 350
    reached_before, missed_before = _xyz(reached), _xyz(missed)
    assert _dist(reached_before, scene.e) > CLEAR_GU          # centre is outside
    assert _dist(missed_before, scene.e) - 100.0 > CLEAR_GU

    scene.dock.SetupDockPositions(scene.docker, "Starbase 12")

    assert _xyz(reached) != reached_before
    assert _dist(_xyz(reached), scene.e) >= CLEAR_GU - 1e-6
    assert _xyz(missed) == missed_before
