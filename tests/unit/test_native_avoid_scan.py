"""AvoidObstacles' obstacle scan, native for stock instances (phase 6 AI part
2, Task 2).

The SDK's AvoidObstacles.TestCourseOverride walks GetNearObjects and calls
NeedToAvoid on every object but the ship (AI/Preprocessors.py:1747-1762).
The host's ``combat_ai_avoid_scan`` replaces that loop for a stock instance:
the same objects, in the same order, by identity, as the SDK loop, with an
object whose class overrides an App method the scan reads evaluated by the
SDK's NeedToAvoid in Python (Review Focus 1).

Pinned here: the native list against the real SDK loop on random scenes, the
per-object Python fallback, a patched NeedToAvoid sending the whole call back
to the SDK, and lDontAvoidTypes read from the instance on every call."""
import random

import pytest

import App
import AI.Preprocessors as pp

from engine.appc import ai_native
from engine.appc import ai_optimized
from engine.appc.ai import ProximityCheck_Create
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet_Create, Sun_Create, _ProximityIteration
from engine.appc.projectiles import Torpedo
from engine.appc.ships import ShipClass
from engine.rocks.rock import RockClass

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(_h is None, reason="native host not built")


class _CodeAI:
    def __init__(self, ship):
        self._ship = ship

    def GetShip(self):
        return self._ship


def _inst(ship=None):
    """A real SDK AvoidObstacles, bound the way the engine binds it."""
    node = ai_optimized.optimized_version_of(pp.AvoidObstacles())
    node.pCodeAI = _CodeAI(ship)
    return node


def _sdk_loop(inst, ship, psr, it):
    """The SDK's loop (AI/Preprocessors.py:1748-1761), verbatim but for the
    manager: the handle's own cursor is what GetNextObject advances."""
    out = []
    obj = it.next_object()
    while obj != None:                               # noqa: E711 (SDK spelling)
        if obj.GetObjID() != ship.GetObjID():
            if pp.AvoidObstacles.NeedToAvoid(inst, ship, psr, obj):
                out.append(obj)
        obj = it.next_object()
    return out


def _ship(r=1.0):
    s = ShipClass()
    s.SetRadius(r)
    return s


def _place(obj, rng, spread):
    obj.SetTranslateXYZ(*(rng.choice((float(rng.randint(-spread, spread)),
                                      rng.uniform(-spread, spread)))
                          for _ in range(3)))


def _velocity(obj, rng):
    if rng.random() < 0.15:
        obj.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    else:
        obj.SetVelocity(TGPoint3(*(rng.uniform(-6.0, 6.0) for _ in range(3))))


def _pool():
    """One of every kind of object a near query can hand AvoidObstacles."""
    out = [_ship() for _ in range(18)]
    rock = _ship()
    rock.__class__ = RockClass
    out.append(rock)
    out.append(Planet_Create(6.0, ""))
    out.append(Sun_Create(9.0, 1.0, 0.0, "", ""))
    out.append(App.Debris())
    out.append(Torpedo())
    out.append(App.MetaNebula_Create(1.0, 1.0, 1.0, 0.5, 0.5, "", ""))
    out.append(ProximityCheck_Create())
    out.append(App.AsteroidField())
    return out


def _randomise(pool, rng):
    for obj in pool:
        _place(obj, rng, 12)
        if hasattr(type(obj), "SetVelocity"):
            _velocity(obj, rng)
        if isinstance(obj, ShipClass):
            obj.SetRadius(rng.choice((0.0, rng.uniform(0.0, 4.0), 2.0)))
        roll = rng.random()
        if roll < 0.1:
            obj.SetScale(rng.choice((0.0, -1.0, float("inf"))))
        elif roll < 0.4:
            obj.SetScale(rng.uniform(0.5, 3.0))
        else:
            obj.SetScale(1.0)


def test_native_scan_equals_the_sdk_loop_on_random_scenes():
    rng = random.Random(20261107)
    pool = _pool()
    ai_native.reset_stats()
    avoided = walked = predicted = 0
    for scene in range(200):
        _randomise(pool, rng)
        ship = pool[0]
        inst = _inst(ship)
        if scene % 5 == 0:
            inst.fPredictionTime = rng.uniform(1.0, 30.0)
        n = rng.randint(2, 40)
        objs = [rng.choice(pool) for _ in range(n)]
        if rng.random() < 0.5:
            objs.insert(rng.randrange(len(objs) + 1), ship)
        psr = ship.GetRadius() * inst.fPersonalSpace

        want = _sdk_loop(inst, ship, psr, _ProximityIteration(objs))
        it = _ProximityIteration(objs)
        got = _h.combat_ai_avoid_scan(inst, ship, psr, it)

        assert [id(o) for o in got] == [id(o) for o in want], scene
        assert it._cursor == len(it)                  # walked, as the SDK's
        avoided += len(want)
        walked += len(objs)
        sl = ship.GetWorldLocation()
        for o in want:
            d = o.GetWorldLocation()
            d.Subtract(sl)
            predicted += not d.Length() < psr + o.GetRadius()
    # Both answers occur often, and the hit-time branch decides a good share
    # of the avoids: the scenes exercise the formula, not one branch.
    assert walked * 0.1 < avoided < walked * 0.9, (avoided, walked)
    assert predicted > avoided * 0.2, (predicted, avoided)
    # Every kind in the pool is stock: nothing fell back to Python, so the
    # comparison above was native against the SDK, not the SDK twice.
    assert ai_native.stats()["avoid"]["reasons"].get("surface", 0) == 0


def test_an_object_overriding_getradius_takes_the_python_path():
    """Review Focus 1: a class overriding an App method the scan reads is
    evaluated by the SDK NeedToAvoid, per object, and counted."""
    class BigShip(ShipClass):
        def GetRadius(self):
            return 10.0

    ship = _ship(1.0)
    inst = _inst(ship)
    big = BigShip()
    big.SetRadius(0.5)                 # the native read would see 0.5
    big.SetTranslateXYZ(8.0, 0.0, 0.0)
    plain = _ship(0.5)
    plain.SetTranslateXYZ(8.0, 0.0, 0.0)
    psr = ship.GetRadius() * inst.fPersonalSpace     # 2.5

    ai_native.reset_stats()
    got = _h.combat_ai_avoid_scan(inst, ship, psr,
                                  _ProximityIteration([big, plain]))
    # 8 < 2.5 + 10 (the override) but not < 2.5 + 0.5; both at rest.
    assert got == [big]
    assert got == _sdk_loop(inst, ship, psr, _ProximityIteration([big, plain]))
    assert ai_native.stats()["avoid"]["reasons"].get("surface", 0) == 1


def _scene_in_a_set():
    pset = App.SetClass_Create()
    pset.SetName("AvoidScan")
    ship = _ship(1.0)
    pset.AddObjectToSet(ship, "Me")
    others = []
    for i, x in enumerate((3.0, 40.0, 6.0)):
        o = _ship(1.0)
        o.SetTranslateXYZ(x, 0.0, 0.0)
        pset.AddObjectToSet(o, "Other%d" % i)
        others.append(o)
    return ship, others


def test_a_patched_needtoavoid_runs_the_sdk_loop(monkeypatch):
    ship, others = _scene_in_a_set()
    inst = _inst(ship)

    calls = []
    original = pp.AvoidObstacles.NeedToAvoid

    def recording(self, pShip, fPersonalSpaceRadius, pObject):
        calls.append(pObject)
        return original(self, pShip, fPersonalSpaceRadius, pObject)

    ai_native.reset_stats()
    inst.TestCourseOverride()
    assert calls == []                           # stock: the scan ran native
    assert ai_native.stats()["avoid"]["native"] == 1

    monkeypatch.setattr(pp.AvoidObstacles, "NeedToAvoid", recording)
    ai_native.reset_stats()
    inst.TestCourseOverride()
    s = ai_native.stats()["avoid"]
    assert s["native"] == 0
    assert s["reasons"] == {"not_stock": 1}
    assert {id(o) for o in calls} == {id(o) for o in others}


def test_lDontAvoidTypes_changed_on_the_instance_is_honoured():
    ship = _ship(1.0)
    inst = _inst(ship)
    torp = Torpedo()
    torp.SetTranslateXYZ(2.0, 0.0, 0.0)          # inside personal space
    planet = Planet_Create(1.0, "")
    planet.SetTranslateXYZ(0.0, 2.0, 0.0)        # inside too
    psr = ship.GetRadius() * inst.fPersonalSpace
    objs = [torp, planet]

    def both():
        want = _sdk_loop(inst, ship, psr, _ProximityIteration(objs))
        got = _h.combat_ai_avoid_scan(inst, ship, psr, _ProximityIteration(objs))
        assert got == want
        return got

    assert both() == [planet]                    # stock list skips torpedoes
    inst.lDontAvoidTypes = [App.CT_PLANET]
    assert both() == [torp]
    inst.lDontAvoidTypes.append(App.CT_TORPEDO)  # mutated in place
    assert both() == []
    inst.lDontAvoidTypes = ()
    assert both() == [torp, planet]


def _course(result):
    """(direction, speed) as exact floats, for comparing two answers."""
    direction, speed = result
    if direction is None:
        return (None, speed)
    return ((direction.x.hex(), direction.y.hex(), direction.z.hex()),
            float(speed).hex())


def test_native_test_course_override_equals_the_sdk_method():
    """The whole engine TestCourseOverride (the SDK body around the native
    loop, then the SDK's AvoidObjects) against the SDK method itself, from the
    same unit-vector RNG state, on crowded scenes where avoidance fires. The
    A/B fights never put an obstacle on a collision course, so this is where
    a non-empty avoid list is compared end to end."""
    from engine.appc import math as appc_math
    rng = random.Random(1107)
    pset = App.SetClass_Create()
    pset.SetName("AvoidCrowd")
    ship = _ship(2.0)
    pset.AddObjectToSet(ship, "Me")
    others = []
    for i in range(16):
        o = _ship(1.0)
        pset.AddObjectToSet(o, "Other%d" % i)
        others.append(o)
    planet = Planet_Create(5.0, "")
    pset.AddObjectToSet(planet, "Rock")
    others.append(planet)

    ai_native.reset_stats()
    fired = 0
    trials = 60
    for _ in range(trials):
        ship.SetTranslateXYZ(0.0, 0.0, 0.0)
        _velocity(ship, rng)
        for o in others:
            _place(o, rng, 25)
            if isinstance(o, ShipClass):
                _velocity(o, rng)
                o.SetRadius(rng.uniform(0.5, 3.0))
        inst = _inst(ship)
        state = appc_math._unit_vector_rng.getstate()
        want = pp.AvoidObstacles.TestCourseOverride(inst)
        after = appc_math._unit_vector_rng.getstate()
        appc_math._unit_vector_rng.setstate(state)
        got = inst.TestCourseOverride()
        assert _course(got) == _course(want)
        assert appc_math._unit_vector_rng.getstate() == after
        fired += want[0] is not None
    assert fired > trials // 4, fired
    s = ai_native.stats()["avoid"]
    assert s["native"] == trials and s["python"] == 0, s
