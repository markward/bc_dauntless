"""ProximityManager caches its candidate list (native proximity phase 1, Task 5).

Each AvoidObstacles query used to rebuild a ~337-entry candidate list in
Python and filter it. The manager now keeps one per membership generation
(engine/appc/proximity_cache.py), rebuilt only when membership changes, and
does the radius test as one native ``near_indices_sized`` call (BC's size
rule, Task 7). The answer must be exactly the reference's:
tests/helpers/proximity_oracle.py is a copy of the queries before the cache
(its near query carrying the size rule), and the differentials compare by
identity and order.

Review Focus (plan docs/superpowers/plans/2026-11-03-native-proximity-phase1.md):
1 same-tick removal, 2 sized torpedo, 3 radius read at query time,
4 member also in the manager, 5 no stale handle.
"""
import random
import sys

import pytest

import App
from engine.appc import native_combat
from engine.appc import projectiles
from engine.appc import proximity_cache
from engine.appc.ai import ProximityCheck
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.planet import ProximityManager
from engine.appc.projectiles import Torpedo
from engine.appc.transform_store import StaleHandleError, get_store
from tests.helpers import proximity_oracle as oracle


class _OwnLocation(ObjectClass):
    """Answers GetWorldLocation itself: never read from the store."""

    def __init__(self, xyz):
        super().__init__()
        self._own = TGPoint3(*xyz)

    def GetWorldLocation(self):
        return TGPoint3(self._own.x, self._own.y, self._own.z)

    def SetTranslateXYZ(self, x, y, z):
        self._own = TGPoint3(x, y, z)


class _RadiusRaises(ObjectClass):
    def GetRadius(self):
        raise RuntimeError("no radius")


class _Bare:
    """A hand-registered manager entry with no location at all."""

    def GetRadius(self):
        return 1.0


def _ship(pSet, name, xyz=(0.0, 0.0, 0.0)):
    s = App.ShipClass_Create()
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _planet(pSet, name, radius, xyz=(0.0, 0.0, 0.0)):
    p = App.Planet_Create(radius, "")
    pSet.AddObjectToSet(p, name)
    p.SetTranslateXYZ(*xyz)
    return p


def _check(xyz=(0.0, 0.0, 0.0)):
    c = ProximityCheck(event_type=999)
    c.SetRadius(50.0)
    c.SetTranslateXYZ(*xyz)
    return c


def _origin():
    return TGPoint3(0.0, 0.0, 0.0)


def _near(pm, point=None, radius=1000.0):
    return list(pm.GetNearObjects(point or _origin(), radius))


def _ids(objs):
    return [id(o) for o in objs]


def _assert_near_matches(pm, point, radius):
    got = list(pm.GetNearObjects(point, radius))
    want = list(oracle.near_objects(pm, point, radius))
    assert _ids(got) == _ids(want), (point.x, point.y, point.z, radius)


def _assert_line_matches(pm, start, end, radius):
    got = list(pm.GetLineIntersectObjects(start, end, radius))
    want = list(oracle.line_objects(pm, start, end, radius))
    assert _ids(got) == _ids(want)


# ── Random scenes ───────────────────────────────────────────────────────────

def _grid(rng):
    return tuple(float(rng.randint(-20, 20)) for _ in range(3))


class _Scene:
    """A set + its manager, mutated at random between queries."""

    def __init__(self, rng):
        self.rng = rng
        self.pSet = App.SetClass_Create() if rng.random() < 0.9 else None
        self.pm = (self.pSet.GetProximityManager() if self.pSet is not None
                   else ProximityManager(None))
        self.objs = []          # every object ever made, kept alive here
        self.names = {}         # set name -> object, as we added it
        self.counter = 0
        for _ in range(rng.randint(0, 8)):
            self.mutate()

    def _name(self):
        self.counter += 1
        return "o%d" % self.counter

    def _new(self):
        rng = self.rng
        kind = rng.randrange(7)
        xyz = _grid(rng)
        if kind <= 1:
            o = App.ShipClass_Create()
        elif kind == 2:
            o = App.Planet_Create(rng.choice([0.0, 0.0, 3.0, 40.0]), "")
        elif kind == 3:
            o = ObjectClass()
            o.SetRadius(rng.choice([0.0, 2.0]))
        elif kind == 4:
            o = _OwnLocation(xyz)
            o.SetRadius(rng.choice([0.0, 1.5]))
        elif kind == 5:
            o = _check(xyz)
        else:
            o = Torpedo()
        if not isinstance(o, _OwnLocation):
            o.SetTranslateXYZ(*xyz)
        self.objs.append(o)
        return o

    def mutate(self):
        rng = self.rng
        pSet, pm = self.pSet, self.pm
        op = rng.randrange(13)
        if op <= 2 and pSet is not None:                 # add to the set
            o = self._new()
            name = self._name()
            pSet.AddObjectToSet(o, name)
            self.names[name] = o
        elif op == 3:                                    # manager ghost
            o = rng.choice([self._new, lambda: _Bare(),
                            lambda: _RadiusRaises()])()
            if isinstance(o, (_Bare, _RadiusRaises)):
                self.objs.append(o)
            pm.AddObject(o)
        elif op == 4 and self.objs:                      # member also AddObject'd
            pm.AddObject(rng.choice(self.objs))
        elif op == 5 and pm._objects:                    # manager removal
            pm.RemoveObject(rng.choice(pm._objects))
        elif op == 6 and self.names and pSet is not None:    # set removal
            name = rng.choice(sorted(self.names))
            o = self.names.pop(name)
            if rng.random() < 0.5:
                pSet.RemoveObjectFromSet(name)
            else:
                pSet.DeleteObjectFromSet(name)
            if rng.random() < 0.5:
                pm.AddObject(o)                          # left behind in the manager
        elif op == 7 and self.names and pSet is not None:    # same object, second name
            o = self.names[rng.choice(sorted(self.names))]
            name = self._name()
            pSet.AddObjectToSet(o, name)
            self.names[name] = o
        elif op == 8 and self.objs:                      # rename, no membership change
            o = rng.choice(self.objs)
            if hasattr(o, "SetName"):
                o.SetName("renamed %d" % rng.randrange(1000))
        elif op == 9 and self.objs:                      # radius change, no bump
            o = rng.choice(self.objs)
            if not isinstance(o, (_Bare, _RadiusRaises)):
                o.SetRadius(rng.choice([0.0, 0.0, 2.5]))
        elif op == 10 and self.objs:                     # move
            o = rng.choice(self.objs)
            if not isinstance(o, (_Bare, _RadiusRaises)):
                o.SetTranslateXYZ(*_grid(rng))
        elif op == 11 and self.names and pSet is not None:   # replace a name
            name = rng.choice(sorted(self.names))
            o = self._new()
            pSet.AddObjectToSet(o, name)
            self.names[name] = o
        elif op == 12 and self.objs:                     # scale change, no bump
            o = rng.choice(self.objs)
            if not isinstance(o, (_Bare, _RadiusRaises)):
                o.SetScale(rng.choice([1.0, 0.5, 3.0, 0.0, -2.0]))

    def query_point_and_radius(self):
        rng = self.rng
        located = [o for o in self.objs if hasattr(o, "GetWorldLocation")]
        if located and rng.random() < 0.4:
            # Exactly on the boundary: an integer offset along one axis from
            # an object's (integer) position.
            o = rng.choice(located)
            loc = o.GetWorldLocation()
            r = float(rng.randint(0, 15))
            axis = rng.randrange(3)
            p = [loc.x, loc.y, loc.z]
            p[axis] -= r
            # Half the time, the radius that puts its SURFACE on the
            # boundary (BC's size rule, ruling 4).
            try:
                size = float(o.GetRadius())
            except Exception:
                size = 0.0
            if 0.0 < size <= r and rng.random() < 0.5:
                return TGPoint3(*p), r - size
            return TGPoint3(*p), r
        return TGPoint3(*_grid(rng)), rng.choice([0.0, 1.0, 5.0, 12.5, 30.0, 1e4])


def _run_scenes(check_one, seed=20261103, scenes=200, steps=12):
    rng = random.Random(seed)
    for _ in range(scenes):
        scene = _Scene(rng)
        for _ in range(steps):
            check_one(scene)
            for _ in range(rng.randint(0, 2)):
                scene.mutate()
    projectiles._active.clear()


def test_cached_near_query_equals_oracle_on_random_scenes():
    def one(scene):
        for _ in range(3):
            _assert_near_matches(scene.pm, *scene.query_point_and_radius())
    _run_scenes(one)


def test_cached_line_query_equals_oracle_on_random_scenes():
    def one(scene):
        for _ in range(3):
            rng = scene.rng
            start, _ = scene.query_point_and_radius()
            end = start if rng.random() < 0.15 else TGPoint3(*_grid(rng))
            _assert_line_matches(scene.pm, start, end,
                                 rng.choice([0.0, 0.5, 4.0]))
    _run_scenes(one, seed=20261104)


# ── Review Focus ────────────────────────────────────────────────────────────

def test_query_after_remove_in_same_tick_excludes_the_object():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    _ship(pSet, "B")
    c = _ship(pSet, "C")
    pm = pSet.GetProximityManager()
    assert len(_near(pm)) == 3              # the cache is built
    pSet.RemoveObjectFromSet("B")
    assert _near(pm) == [a, c]
    pSet.DeleteObjectFromSet("C")
    assert _near(pm) == [a]


def test_sized_torpedo_set_takes_python_path_and_matches_oracle(monkeypatch):
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    t = Torpedo()
    pSet.AddObjectToSet(t, "T")
    t.SetTranslateXYZ(0.0, 0.0, 0.0)
    b = _ship(pSet, "B")
    pm = pSet.GetProximityManager()
    cls = type(get_store())
    calls = []          # per near_indices_sized call: was it the cache's?
    real = cls.near_indices_sized

    def spy(self, packed, *a):
        calls.append(pm._cand is not None and packed is pm._cand.packed)
        return real(self, packed, *a)

    monkeypatch.setattr(cls, "near_indices_sized", spy)
    t.SetRadius(0.5)
    try:
        got = _near(pm)
        assert got == [a, t, b]
        assert _ids(got) == _ids(oracle.near_objects(pm, _origin(), 1000.0))
        assert calls == [False]             # today's Python path, uncached
        t.SetRadius(0.0)
        assert _near(pm) == [a, b]
        assert calls == [False, True]       # back on the cache
    finally:
        projectiles._active.clear()


def test_planet_radius_change_between_queries_is_seen():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    p = _planet(pSet, "P", 0.0)
    pm = pSet.GetProximityManager()
    assert _near(pm) == [a]
    gen = proximity_cache.generation()
    p.SetRadius(10.0)
    assert proximity_cache.generation() == gen      # no membership change
    assert _near(pm) == [a, p]
    assert list(pm.GetLineIntersectObjects(
        TGPoint3(-5, 0, 0), TGPoint3(5, 0, 0), 0.0)) == [a, p]
    p.SetRadius(0.0)
    assert _near(pm) == [a]


def test_member_also_in_manager_reported_once_at_the_right_slot():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    s = _ship(pSet, "S")
    p = _planet(pSet, "P", 0.0)
    b = _ship(pSet, "B")
    pm = pSet.GetProximityManager()
    ghost = ObjectClass()
    pm.AddObject(p)
    pm.AddObject(ghost)
    pm.AddObject(s)
    # S participates: once, at its set slot. P does not: at its manager slot.
    assert _near(pm) == [a, s, b, p, ghost]
    p.SetRadius(5.0)
    assert _near(pm) == [a, s, p, b, ghost]


def test_cached_query_never_raises_stale_handle():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    b = _ship(pSet, "B")
    pm = pSet.GetProximityManager()
    assert _near(pm) == [a, b]              # the cache lists B's handle
    old = pm._cand
    pSet.DeleteObjectFromSet("B")
    # Free B's transform slot now, as its collection would (engine.core.ids
    # holds it, so gc.collect() never does), then recycle slots.
    b._xform_finalizer()
    native_combat.drain(boundary=True)
    fresh = [ObjectClass() for _ in range(8)]
    # The old list is now stale: reusing it past its generation would raise.
    with pytest.raises(StaleHandleError):
        get_store().near_indices(old.packed, 0.0, 0.0, 0.0, 1e6)
    assert _near(pm) == [a]
    assert fresh


def test_cache_is_rebuilt_only_on_generation_change(monkeypatch):
    pSet = App.SetClass_Create()
    for i in range(5):
        _ship(pSet, "S%d" % i, (float(i), 0.0, 0.0))
    _planet(pSet, "P", 3.0)
    pm = pSet.GetProximityManager()
    pm.AddObject(_check())
    builds = []
    real = ProximityManager._build_cand
    monkeypatch.setattr(ProximityManager, "_build_cand",
                        lambda self, *a: builds.append(1) or real(self, *a))
    for _ in range(100):
        pm.GetNearObjects(_origin(), 10.0)
        pm.GetLineIntersectObjects(_origin(), TGPoint3(1, 0, 0), 1.0)
    assert len(builds) == 1
    _ship(pSet, "Late")
    pm.GetNearObjects(_origin(), 10.0)
    assert len(builds) == 2


def test_cached_query_does_no_per_query_import():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    pm = pSet.GetProximityManager()
    assert _near(pm) == [a]
    saved = {m: sys.modules[m] for m in
             ("engine.appc.ai", "engine.appc.sets", "engine.appc.projectiles")}
    try:
        for m in saved:
            sys.modules[m] = None           # any import of these now raises
        assert _near(pm) == [a]
        assert list(pm.GetLineIntersectObjects(
            TGPoint3(-1, 0, 0), TGPoint3(1, 0, 0), 0.0)) == [a]
    finally:
        sys.modules.update(saved)


def teardown_function(_):
    projectiles._active.clear()
