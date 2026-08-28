"""ProximityManager must actually be iterable, and must see the set's objects.

THE GAP THIS PINS. Eight shipped SDK call sites walk objects with the same
three-call contract:

    pIter   = pProxManager.<producer>(...)
    pObject = pProxManager.GetNextObject(pIter)
    while pObject != None:
        ...
        pObject = pProxManager.GetNextObject(pIter)
    pProxManager.EndObjectIteration(pIter)

There are TWO producers, and this file only fixes one of them:

    GetNearObjects -- fixed here, these four now walk real objects:
        AI/Preprocessors.py:1749         AvoidObstacles.TestCourseOverride
        AI/Compound/DockWithStarbase.py:71
        Bridge/HelmMenuHandlers.py:2493  helm collision-alert voice lines
        MissionLib.py:5035               GrabWarpEncompassingObstacles

    GetLineIntersectObjects -- STILL a hardcoded `return ()` (planet.py), so
    these four remain dead even with GetNextObject working:
        AI/Preprocessors.py:373          FireScript target occlusion
                                         (fails OPEN: bTargetVisible = 1)
        AI/PlainAI/Intercept.py:269
        Conditions/ConditionInLineOfSight.py:128
        MissionLib.py:4930               GrabWarpObstacles

⚠️ Do not read "the proximity walk works now" as "all eight work now". The
second placeholder is a separate, still-open gap.

Two independent breaks made every one of them a silent no-op:

1. ``GetNextObject`` was a hardcoded ``return None`` -- a Phase-1 placeholder,
   so the ``while`` above exited BEFORE its first iteration, every time.
2. The manager only knew about objects hand-registered through ``AddObject``
   (probes, proximity checks). Nothing puts the set's SHIPS in it, so even a
   working iterator would have walked an empty list. Measured on a live
   QuickBattle scene: 5 ships in the world, ``GetNumObjects() == 0``.

Neither shows up in docs/stub_heatmap.md, and cannot: both are real methods
returning a real value. There is no attribute miss for the telemetry to record.

Live cost: ``AvoidObstacles.TestCourseOverride`` always returned ``(None, None)``
-- "nothing to avoid" -- so AI collision avoidance never ran for any ship in the
game. See tests/integration/test_pursuers_avoid_each_other.py.
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.planet import ProximityManager
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship_at(name, x, y, z):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslateXYZ(x, y, z)
    return s


def _drain(pm, iterator):
    """Walk the iterator exactly the way every SDK call site does."""
    out = []
    obj = pm.GetNextObject(iterator)
    while obj is not None:
        out.append(obj)
        obj = pm.GetNextObject(iterator)
    pm.EndObjectIteration(iterator)
    return out


# ── the iteration contract ──────────────────────────────────────────────────

def test_get_next_object_walks_the_result_then_terminates():
    pm = ProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    b = _ship_at("B", 20.0, 0.0, 0.0)
    pm.AddObject(a)
    pm.AddObject(b)

    walked = _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))

    assert set(id(o) for o in walked) == {id(a), id(b)}


def test_an_empty_result_terminates_immediately():
    pm = ProximityManager()
    assert _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)) == []


def test_two_iterators_do_not_share_a_cursor():
    """FireScript's occlusion walk and AvoidObstacles' scan both run inside one
    tick. A cursor stored on the manager rather than the handle would let one
    consume the other's objects."""
    pm = ProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    b = _ship_at("B", 20.0, 0.0, 0.0)
    pm.AddObject(a)
    pm.AddObject(b)

    first = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    second = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    pm.GetNextObject(first)                       # consume one from `first`

    assert len(_drain(pm, second)) == 2


def test_end_object_iteration_tolerates_anything():
    """SDK code calls it on paths where the iterator may never have been made
    (ConditionInLineOfSight bails early)."""
    pm = ProximityManager()
    pm.EndObjectIteration(None)
    pm.EndObjectIteration(pm.GetNearObjects(TGPoint3(0, 0, 0), 1.0))


def test_get_near_objects_result_is_still_a_sequence():
    """tests/unit/test_proximity_manager_distance.py consumes the return value
    directly with `in` / `== ()` / len. The iterator handle must not break that."""
    pm = ProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    pm.AddObject(a)

    result = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)

    assert a in result
    assert len(result) == 1
    assert list(result) == [a]
    assert pm.GetNearObjects(TGPoint3(0, 0, 0), 1.0) == ()


# ── the manager must see the SET, not only hand-registered extras ───────────

def test_the_manager_reports_objects_that_are_in_its_set():
    """BC's ProximityManager is the set's spatial index -- every object in the
    set is in it. Ours only had what AddObject was called with, which for ships
    is nothing."""
    pSet = SetClass()
    pm = pSet.GetProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    pSet.AddObjectToSet(a, "A")

    walked = _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))

    assert [id(o) for o in walked] == [id(a)]


def test_set_objects_still_respect_the_radius():
    pSet = SetClass()
    pm = pSet.GetProximityManager()
    near = _ship_at("near", 10.0, 0.0, 0.0)
    far = _ship_at("far", 500.0, 0.0, 0.0)
    pSet.AddObjectToSet(near, "near")
    pSet.AddObjectToSet(far, "far")

    walked = _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))

    assert [id(o) for o in walked] == [id(near)]


def test_an_object_registered_twice_is_reported_once():
    """E6M4 calls AddObject(pProbe) on an object that is also in the set. The
    SDK loops skip only `pObject.GetObjID() != pShip.GetObjID()`, so a duplicate
    would be scored as two separate obstacles at the same point."""
    pSet = SetClass()
    pm = pSet.GetProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    pSet.AddObjectToSet(a, "A")
    pm.AddObject(a)

    walked = _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))

    assert len(walked) == 1


def test_an_object_removed_from_the_set_stops_being_reported():
    """A destroyed ship must not go on being avoided -- the manager cannot hold
    its own strong list of set members or it will hand back the dead."""
    pSet = SetClass()
    pm = pSet.GetProximityManager()
    a = _ship_at("A", 10.0, 0.0, 0.0)
    pSet.AddObjectToSet(a, "A")
    assert len(pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)) == 1

    pSet.RemoveObjectFromSet("A")

    assert _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)) == []


# ── what counts as a proximity participant ──────────────────────────────────
#
# A set holds authoring and rendering bookkeeping alongside real objects. The
# QuickBattle region ships with a `Waypoint` ("Player Start"), two
# `LightPlacement`s and a `GridClass` -- all at the origin, all radius 0. None
# of them occupies space, and handing them to the SDK's proximity walks does
# real damage:
#
#   * AvoidObstacles steered around them -- measured, ships dodging
#     "LightPlacement(Ambient Light)" 166 times in 300 ticks.
#   * DockWithStarbase divided by zero. Its walk subtracts the object's
#     position from the docking entry's and unitizes; for an object sitting ON
#     the entry that vector is zero, and `fMoveDistance / vDiff.Length()`
#     raises. The SDK guards that case at line 94 -- and Python 2's cross-type
#     comparison meant the guard never fired, so BC cannot have been returning
#     zero-distance objects here either.
#
# The rule keeps physics objects unconditionally: a ship in a headless run
# reports radius 0 until the renderer's realize step sets it, and excluding
# those would make avoidance silently do nothing in exactly the environment the
# tests run in. Non-physics objects have to actually occupy space, which keeps
# planets and suns (real radii) and drops the markers.

def test_placement_markers_are_not_proximity_participants():
    from engine.appc.placement import PlacementObject

    pSet = SetClass()
    pm = pSet.GetProximityManager()
    marker = PlacementObject()
    marker.SetName("Docking Entry")
    marker.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(marker, "Docking Entry")

    assert _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)) == []


def test_a_zero_radius_non_physics_object_is_not_a_participant():
    """`GridClass` is a plain ObjectClass with radius 0 -- the set's reference
    grid, not an obstacle."""
    from engine.appc.objects import ObjectClass

    pSet = SetClass()
    pm = pSet.GetProximityManager()
    grid = ObjectClass()
    grid.SetName("grid")
    grid.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(grid, "grid")

    assert _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)) == []


def test_a_physics_object_participates_even_with_no_radius_yet():
    """Headless has no realize step, so GetRadius() reads 0 on a real ship.
    Dropping those would make every proximity walk vacuous under test."""
    pSet = SetClass()
    pm = pSet.GetProximityManager()
    ship = _ship_at("A", 10.0, 0.0, 0.0)
    ship.SetRadius(0.0)
    pSet.AddObjectToSet(ship, "A")

    assert [id(o) for o in _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))] \
        == [id(ship)]


def test_a_non_physics_object_that_occupies_space_participates():
    """A planet is an ObjectClass, not a PhysicsObjectClass, and AvoidObstacles
    is written to expect exactly that (it null-checks PhysicsObjectClass_Cast
    and treats the miss as zero velocity)."""
    from engine.appc.objects import ObjectClass

    pSet = SetClass()
    pm = pSet.GetProximityManager()
    planet = ObjectClass()
    planet.SetName("planet")
    planet.SetTranslateXYZ(20.0, 0.0, 0.0)
    planet.SetRadius(50.0)
    pSet.AddObjectToSet(planet, "planet")

    assert [id(o) for o in _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0))] \
        == [id(planet)]
