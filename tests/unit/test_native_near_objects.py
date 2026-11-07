"""GetNearObjects reads candidate radii natively (phase 6 AI part 3, task 5).

The cached path (ProximityManager._near_objects) used to make one Python
`_size` -> GetRadius call per store-backed candidate per query, and another
per reported candidate for participation. The `prox_near` binding now reads a
stock candidate's radius in C++ (ObjectClass.GetRadius's guarded
`_radius * _scale`), and calls Python only for a candidate whose type or
instance does not resolve GetRadius to that body. The answer must be exactly
the Python cached path's (`_today` below, a verbatim copy of it): same
objects, same order, as a _ProximityIteration.

Review Focus 2: a type overriding GetRadius, or one whose GetRadius raises.
Review Focus 3: a radius or scale changed between queries with no generation
bump is seen.
"""
import random
import sys
from array import array

import pytest

_h = pytest.importorskip("_dauntless_host")

import App
from engine.appc import planet, projectiles, proximity_cache
from engine.appc.ai import ProximityCheck
from engine.appc.debris_chunk import DebrisChunk
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.planet import Planet_Create, Sun_Create, _ProximityIteration
from engine.appc.ships import ShipClass
from engine.appc.transform_store import NativeTransformStore, get_store
from engine.rocks.rock import RockClass


def _today(pm, point, radius):
    """ProximityManager._near_objects's cached path before task 5, verbatim
    but for `self` -> `pm` and module names qualified."""
    cand = pm._cached()
    assert cand is not None
    r = float(radius)
    px, py, pz = point.x, point.y, point.z
    objs = cand.objs
    keep = []
    if cand.packed:
        pos = cand.packed_pos
        radii = array("d", [planet._size(objs[i]) for i in pos])
        for k in get_store().near_indices_sized(cand.packed, radii,
                                                px, py, pz, r):
            i = pos[k]
            if planet._reports(cand, i):
                keep.append(i)
    if cand.unstored_pos:
        more = []
        for i in cand.unstored_pos:
            if not planet._reports(cand, i):
                continue
            obj = objs[i]
            loc = (obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation")
                   else None)
            if loc is None:
                continue
            if planet._within_reach(loc.x - px, loc.y - py, loc.z - pz, r,
                                    planet._size(obj)):
                more.append(i)
        if more:
            keep = sorted(keep + more) if keep else more
    return _ProximityIteration([objs[i] for i in keep])


# ── Doubles ──────────────────────────────────────────────────────────────────

class _OwnLocation(ObjectClass):
    """Answers GetWorldLocation itself: an unstored entry."""

    def __init__(self, xyz):
        super().__init__()
        self._own = TGPoint3(*xyz)

    def GetWorldLocation(self):
        return TGPoint3(self._own.x, self._own.y, self._own.z)


class _RadiusRaises(ObjectClass):
    def GetRadius(self):
        raise RuntimeError("no radius")


class _Overrides(ObjectClass):
    """An engine or mod type with its own GetRadius (Review Focus 2)."""

    calls = 0

    def GetRadius(self):
        type(self).calls += 1
        return 6.0


class _Bare:
    """A hand-registered manager entry with no location at all."""

    def GetRadius(self):
        return 1.0


def _grid(rng):
    return tuple(float(rng.randint(-20, 20)) for _ in range(3))


def _debris(rng):
    origin = ShipClass()
    return DebrisChunk(0, origin, 1, 1.0, rng.choice([0.0, 2.0]), 1.0, None,
                       TGPoint3(*_grid(rng)), None, None, None, 4242)


class _Scene:
    """A set + its manager holding one of everything a near query meets."""

    def __init__(self, rng):
        self.rng = rng
        self.pSet = App.SetClass_Create()
        self.pm = self.pSet.GetProximityManager()
        self.objs = []
        self.names = {}
        self.counter = 0
        for _ in range(rng.randint(4, 14)):
            self.mutate()

    def _name(self):
        self.counter += 1
        return "o%d" % self.counter

    def _new(self):
        rng = self.rng
        kind = rng.randrange(11)
        xyz = _grid(rng)
        if kind <= 1:
            o = App.ShipClass_Create()
            o.SetRadius(rng.choice([0.0, 1.0, 2.5]))
        elif kind == 2:
            o = Planet_Create(rng.choice([0.0, 3.0, 40.0]), "")
        elif kind == 3:
            o = Sun_Create(rng.choice([0.0, 9.0]), 1.0, 0.0, "", "")
        elif kind == 4:
            o = ShipClass()
            o.SetRadius(rng.choice([0.0, 4.0]))
            o.__class__ = RockClass
        elif kind == 5:
            o = App.Debris()
            o.SetRadius(rng.choice([0.0, 1.5]))
        elif kind == 6:
            o = ProximityCheck(event_type=999)
            o.SetRadius(50.0)
        elif kind == 7:
            o = _OwnLocation(xyz)
            o.SetRadius(rng.choice([0.0, 1.5]))
        elif kind == 8:
            o = _Overrides()
        elif kind == 9:
            o = _RadiusRaises()
        else:
            o = ObjectClass()
            o.SetRadius(rng.choice([0.0, 2.0]))
            if rng.random() < 0.3:          # an instance shadowing GetRadius
                o.GetRadius = lambda v=rng.choice([-1.0, 0.0, 3.0]): v
        if not isinstance(o, _OwnLocation):
            o.SetTranslateXYZ(*xyz)
        self.objs.append(o)
        return o

    def mutate(self):
        rng = self.rng
        pSet, pm = self.pSet, self.pm
        op = rng.randrange(12)
        if op <= 3:                                      # add to the set
            o = self._new()
            name = self._name()
            pSet.AddObjectToSet(o, name)
            self.names[name] = o
        elif op == 4:                                    # manager-only entry
            o = rng.choice([self._new, lambda: _Bare(),
                            lambda: _debris(rng)])()
            if not isinstance(o, ObjectClass):
                self.objs.append(o)
            pm.AddObject(o)
        elif op == 5 and self.objs:                      # member also AddObject'd
            pm.AddObject(rng.choice(self.objs))
        elif op == 6 and pm._objects:                    # manager removal
            pm.RemoveObject(rng.choice(pm._objects))
        elif op == 7 and self.names:                     # set removal
            name = rng.choice(sorted(self.names))
            self.names.pop(name)
            pSet.RemoveObjectFromSet(name)
        elif op == 8 and self.names:                     # second name
            o = self.names[rng.choice(sorted(self.names))]
            name = self._name()
            pSet.AddObjectToSet(o, name)
            self.names[name] = o
        elif op == 9 and self.objs:                      # radius, no bump
            o = rng.choice(self.objs)
            if isinstance(o, ObjectClass) and not isinstance(o, ProximityCheck):
                if rng.random() < 0.2:
                    o.__dict__["_radius"] = rng.choice([3, -2])   # an int
                else:
                    o.SetRadius(rng.choice([0.0, 0.0, 2.5, -1.0]))
        elif op == 10 and self.objs:                     # move
            o = rng.choice(self.objs)
            if hasattr(o, "SetTranslateXYZ") and not isinstance(o, _OwnLocation):
                o.SetTranslateXYZ(*_grid(rng))
        elif op == 11 and self.objs:                     # scale, no bump
            o = rng.choice(self.objs)
            if isinstance(o, ObjectClass) and not isinstance(o, ProximityCheck):
                o.SetScale(rng.choice([1.0, 0.5, 3.0, 0.0, -2.0,
                                       float("inf"), float("nan")]))

    def query(self):
        rng = self.rng
        located = [o for o in self.objs if hasattr(o, "GetWorldLocation")]
        if located and rng.random() < 0.5:
            o = rng.choice(located)
            loc = o.GetWorldLocation()
            r = float(rng.randint(0, 15))
            p = [loc.x, loc.y, loc.z]
            p[rng.randrange(3)] -= r
            size = planet._size(o)
            if 0.0 < size <= r and rng.random() < 0.5:
                return TGPoint3(*p), r - size          # surface on the boundary
            return TGPoint3(*p), r
        return TGPoint3(*_grid(rng)), rng.choice([0.0, 1.0, 5.0, 12.5, 30.0, 1e4])


def _ids(objs):
    return [id(o) for o in objs]


def _origin():
    return TGPoint3(0.0, 0.0, 0.0)


@pytest.fixture(autouse=True)
def _native_store():
    assert type(get_store()) is NativeTransformStore
    yield
    projectiles._active.clear()


# ── Tests ────────────────────────────────────────────────────────────────────

def test_native_near_equals_today_on_random_scenes():
    assert hasattr(_h, "prox_near"), "the native near query is not built"
    rng = random.Random(20261107)
    queries = 0
    while queries < 300:
        scene = _Scene(rng)
        for _ in range(10):
            point, radius = scene.query()
            got = scene.pm.GetNearObjects(point, radius)
            want = _today(scene.pm, point, radius)
            assert type(got) is _ProximityIteration
            assert got._cursor == 0
            assert _ids(got) == _ids(want), (point.x, point.y, point.z, radius)
            queries += 1
            for _ in range(rng.randint(0, 2)):
                scene.mutate()


def test_a_type_overriding_getradius_uses_its_override():
    pSet = App.SetClass_Create()
    a = App.ShipClass_Create()
    pSet.AddObjectToSet(a, "A")
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    o = _Overrides()                     # radius 0 underneath, 6 by override
    pSet.AddObjectToSet(o, "O")
    o.SetTranslateXYZ(10.0, 0.0, 0.0)
    pm = pSet.GetProximityManager()
    _Overrides.calls = 0
    assert list(pm.GetNearObjects(_origin(), 5.0)) == [a, o]
    assert _Overrides.calls == 2         # _size, then participation
    _Overrides.calls = 0
    assert list(pm.GetNearObjects(_origin(), 3.0)) == [a]
    assert _Overrides.calls == 1         # _size only: never near
    # A class patch is seen by the next query.
    try:
        ObjectClass.GetRadius, saved = (lambda self: 20.0), ObjectClass.GetRadius
        a.SetTranslateXYZ(25.0, 0.0, 0.0)
        assert list(pm.GetNearObjects(_origin(), 5.0)) == [a, o]
    finally:
        ObjectClass.GetRadius = saved
    # And an instance-dict shadow, once the stock read is remembered again.
    assert list(pm.GetNearObjects(_origin(), 3.5)) == []
    a.GetRadius = lambda: 21.5
    assert list(pm.GetNearObjects(_origin(), 3.5)) == [a]


def test_a_raising_getradius_counts_as_zero():
    pSet = App.SetClass_Create()
    a = App.ShipClass_Create()
    pSet.AddObjectToSet(a, "A")
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    bad = _RadiusRaises()
    pSet.AddObjectToSet(bad, "Bad")
    bad.SetTranslateXYZ(1.0, 0.0, 0.0)
    pm = pSet.GetProximityManager()
    pm.AddObject(bad)                    # its twin does not participate
    assert list(pm.GetNearObjects(_origin(), 2.0)) == [a, bad]
    assert list(pm.GetNearObjects(_origin(), 0.5)) == [a]


def test_radius_change_without_a_generation_bump_is_seen():
    pSet = App.SetClass_Create()
    a = App.ShipClass_Create()
    pSet.AddObjectToSet(a, "A")
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    p = Planet_Create(0.0, "")
    pSet.AddObjectToSet(p, "P")
    p.SetTranslateXYZ(20.0, 0.0, 0.0)
    pm = pSet.GetProximityManager()
    assert list(pm.GetNearObjects(_origin(), 5.0)) == [a]
    gen = proximity_cache.generation()
    p.SetRadius(10.0)
    assert list(pm.GetNearObjects(_origin(), 5.0)) == [a]  # participates, too far
    assert list(pm.GetNearObjects(_origin(), 10.0)) == [a, p]
    p.SetScale(0.5)
    assert list(pm.GetNearObjects(_origin(), 10.0)) == [a]
    p.SetScale(2.0)
    assert list(pm.GetNearObjects(_origin(), 0.0)) == [a, p]
    p.SetRadius(0.0)
    assert list(pm.GetNearObjects(_origin(), 10.0)) == [a]
    assert proximity_cache.generation() == gen


def test_no_python_getradius_call_for_stock_candidates():
    pSet = App.SetClass_Create()
    stock = []
    for i in range(6):
        s = App.ShipClass_Create()
        pSet.AddObjectToSet(s, "S%d" % i)
        s.SetTranslateXYZ(float(i), 0.0, 0.0)
        s.SetRadius(1.0)
        stock.append(s)
    p = Planet_Create(3.0, "")
    pSet.AddObjectToSet(p, "P")
    p.SetTranslateXYZ(-2.0, 0.0, 0.0)
    stock.append(p)
    o = _Overrides()
    pSet.AddObjectToSet(o, "O")
    o.SetTranslateXYZ(2.0, 2.0, 0.0)
    pm = pSet.GetProximityManager()
    pm.AddObject(stock[0])
    pm.GetNearObjects(_origin(), 1.0)    # build the cache, warm the memos

    stock_code = ObjectClass.GetRadius.__code__
    size_code = planet._size.__code__
    seen = {"stock": 0, "size": 0}

    def prof(frame, event, _arg):
        if event == "call":
            if frame.f_code is stock_code:
                seen["stock"] += 1
            elif frame.f_code is size_code:
                seen["size"] += 1

    _Overrides.calls = 0
    sys.setprofile(prof)
    try:
        got = pm.GetNearObjects(_origin(), 100.0)
    finally:
        sys.setprofile(None)
    assert list(got) == stock[:] + [o]
    assert seen["stock"] == 0
    assert seen["size"] == 1             # the override's, only
    assert _Overrides.calls == 2


def test_a_stale_handle_raises_what_the_store_raises():
    from engine.appc.transform_store import StaleHandleError
    o = ObjectClass()
    index, generation = o._xform
    cand = planet._Cand()
    cand.objs, cand.is_set, cand.physics, cand.dup_of = [o], [True], [False], [-1]
    cand.packed = array("I", [index, generation + 1])
    cand.packed_pos, cand.unstored_pos = [0], []
    radii = array("d", [0.0])
    for px in (0.0, None):                  # a stale handle; float() refusing
        with pytest.raises(StaleHandleError) as want:
            get_store().near_indices_sized(cand.packed, radii, px, 0.0, 0.0, 1.0)
        with pytest.raises(StaleHandleError) as got:
            _h.prox_near(cand, px, 0.0, 0.0, 1.0)
        assert type(got.value) is type(want.value)
        assert str(got.value) == str(want.value)
        assert type(got.value.__cause__) is type(want.value.__cause__)
        assert str(got.value.__cause__) == str(want.value.__cause__)


def test_stale_error_context_survives_an_enclosing_except():
    """Raised from inside an outer `except`, the stale error keeps the store
    exception as __context__ (as `raise ... from exc` sets it), not the outer
    one the interpreter was handling."""
    from engine.appc.transform_store import StaleHandleError
    o = ObjectClass()
    index, generation = o._xform
    cand = planet._Cand()
    cand.objs, cand.is_set, cand.physics, cand.dup_of = [o], [True], [False], [-1]
    cand.packed = array("I", [index, generation + 1])
    cand.packed_pos, cand.unstored_pos = [0], []
    radii = array("d", [0.0])

    def caught(call):
        try:
            raise KeyError("outer")
        except KeyError:
            try:
                call()
            except StaleHandleError as e:
                return e

    want = caught(lambda: get_store().near_indices_sized(
        cand.packed, radii, 0.0, 0.0, 0.0, 1.0))
    got = caught(lambda: _h.prox_near(cand, 0.0, 0.0, 0.0, 1.0))
    assert want is not None and got is not None
    assert type(want.__context__) is not KeyError
    assert type(got.__context__) is type(want.__context__)
    assert str(got.__context__) == str(want.__context__)
    assert got.__cause__ is got.__context__
    assert got.__suppress_context__ is want.__suppress_context__
