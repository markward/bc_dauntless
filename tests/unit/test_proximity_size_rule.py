"""ProximityManager.GetNearObjects uses BC's size rule (ruling 4, native
proximity phase 1, Task 7).

BC keeps an object when its SURFACE is within the query radius:
`|position - centre| - bounding radius <= radius`
(docs/reference/engine/native-motion/open-questions-by-reading.md Q3). Ours
kept it only when its CENTRE was, so AI avoidance, the Helm collision alert
and the docking clear-out saw a 296 GU starbase only once they were inside
it. The radius is GetRadius(), BC's scaled world bound, read live on every
query; one that raises counts as 0; the boundary is inclusive.

Every rule is checked on the three ways a query is answered: the cached
store-backed walk, an entry that answers GetWorldLocation itself, and the
uncached Python walk a sized torpedo forces.
"""
import pytest

import App
from engine.appc import projectiles
from engine.appc import proximity_cache
from engine.appc import proximity_table
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.projectiles import Torpedo
from engine.appc.ships import ShipClass


class _OwnLocation(ShipClass):
    """A ship that answers GetWorldLocation itself: never read from the
    store (a physics object, so it participates at any radius)."""

    def __init__(self):
        super().__init__()
        self._own = TGPoint3(0.0, 0.0, 0.0)

    def GetWorldLocation(self):
        return TGPoint3(self._own.x, self._own.y, self._own.z)

    def SetTranslateXYZ(self, x, y, z):
        self._own = TGPoint3(x, y, z)


class _RadiusRaises(ObjectClass):
    def GetRadius(self):
        raise RuntimeError("no radius")


class _OwnLocationRadiusRaises(_OwnLocation):
    def GetRadius(self):
        raise RuntimeError("no radius")


PATHS = ["cached", "unstored", "uncached"]


class _Scene:
    def __init__(self, path):
        self.path = path
        self.pSet = App.SetClass_Create()
        self.pm = self.pSet.GetProximityManager()
        self.n = 0
        if path == "uncached":
            # A torpedo with a radius sends the query down the uncached walk.
            t = Torpedo()
            self.pSet.AddObjectToSet(t, "T")
            t.SetTranslateXYZ(1e6, 0.0, 0.0)
            t.SetRadius(0.5)
            assert self.pm._cached() is None

    def put(self, x, radius=0.0, scale=None):
        """A ship at (x, 0, 0); on the "unstored" path one that answers its
        own location."""
        o = _OwnLocation() if self.path == "unstored" else App.ShipClass_Create()
        self.n += 1
        self.pSet.AddObjectToSet(o, "o%d" % self.n)
        o.SetTranslateXYZ(x, 0.0, 0.0)
        o.SetRadius(radius)
        if scale is not None:
            o.SetScale(scale)
        assert proximity_table.location_is_stored(o) == (self.path != "unstored")
        return o

    def near(self, radius, point=(0.0, 0.0, 0.0)):
        return list(self.pm.GetNearObjects(TGPoint3(*point), radius))


@pytest.fixture(params=PATHS)
def scene(request):
    yield _Scene(request.param)
    projectiles._active.clear()


def test_station_surface_in_range_is_returned(scene):
    station = scene.put(350.0, radius=296.0)
    assert scene.near(60.0) == [station]
    assert scene.near(50.0) == []


def test_boundary_is_inclusive(scene):
    station = scene.put(350.0, radius=296.0)
    assert scene.near(54.0) == [station]        # 350 - 296 == 54 exactly
    assert scene.near(53.999) == []


def test_scaled_rock_reach_uses_scaled_radius(scene):
    rock = scene.put(35.0, radius=10.0, scale=3.0)
    assert rock.GetRadius() == 30.0
    assert scene.near(10.0) == [rock]           # reach 40
    assert scene.near(4.0) == []                # reach 34; base 10 would be 14


def test_radius_change_between_queries_is_seen(scene):
    o = scene.put(100.0, radius=0.0)
    other = scene.put(-5.0)
    assert scene.near(50.0) == [other]
    gen = proximity_cache.generation()
    o.SetRadius(60.0)
    assert scene.near(50.0) == [o, other]
    o.SetRadius(20.0)
    assert scene.near(50.0) == [other]
    o.SetScale(3.0)                             # 60 again, through the scale
    assert scene.near(50.0) == [o, other]
    assert proximity_cache.generation() == gen  # no membership change


def test_zero_radius_objects_keep_the_centre_rule(scene):
    a = scene.put(100.0, radius=0.0)
    assert scene.near(100.0) == [a]
    assert scene.near(99.999) == []


def test_negative_radius_counts_as_zero(scene):
    a = scene.put(100.0, radius=-50.0)
    assert scene.near(100.0) == [a]
    assert scene.near(99.999) == []


def test_radius_that_raises_counts_as_zero(scene):
    cls = _OwnLocationRadiusRaises if scene.path == "unstored" else _RadiusRaises
    o = cls()
    o.SetTranslateXYZ(10.0, 0.0, 0.0)
    scene.pm.AddObject(o)
    assert scene.near(10.0) == [o]
    assert scene.near(9.999) == []


def test_type_argument_is_accepted_and_ignored(scene):
    station = scene.put(350.0, radius=296.0)
    for eType in (None, 0, 1):
        assert list(scene.pm.GetNearObjects(
            TGPoint3(0.0, 0.0, 0.0), 54.0, eType)) == [station]
        assert list(scene.pm.GetNearObjects(
            TGPoint3(0.0, 0.0, 0.0), 53.0, eType)) == []


def teardown_function(_):
    projectiles._active.clear()
