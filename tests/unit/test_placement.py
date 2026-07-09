"""Unit tests for PlacementObject, Waypoint, Waypoint_Create, and PlaceObjectByName."""
import pytest
import App
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.placement import PlacementObject, Waypoint, Waypoint_Create, _waypoint_registry
from engine.appc.sets import SetClass


@pytest.fixture(autouse=True)
def clear_waypoint_registry():
    _waypoint_registry.clear()
    yield
    _waypoint_registry.clear()


# ── PlacementObject ───────────────────────────────────────────────────────────

def test_placement_object_is_object_class():
    p = PlacementObject()
    assert isinstance(p, ObjectClass)


def test_placement_static_flag():
    p = PlacementObject()
    assert not p.IsStatic()
    p.SetStatic(1)
    assert p.IsStatic()


def test_placement_nav_point_flag():
    p = PlacementObject()
    assert not p.IsNavPoint()
    p.SetNavPoint(1)
    assert p.IsNavPoint()


# ── Waypoint ──────────────────────────────────────────────────────────────────

def test_waypoint_is_placement_object():
    wp = Waypoint()
    assert isinstance(wp, PlacementObject)


def test_waypoint_speed_roundtrip():
    wp = Waypoint()
    wp.SetSpeed(25.0)
    assert wp.GetSpeed() == 25.0


def test_waypoint_next_prev_initially_none():
    wp = Waypoint()
    assert wp.GetNext() is None
    assert wp.GetPrev() is None


# ── Waypoint_Create ───────────────────────────────────────────────────────────

def test_waypoint_create_returns_waypoint():
    wp = Waypoint_Create("TestWP", "TestSet", None)
    assert isinstance(wp, Waypoint)


def test_waypoint_create_sets_name():
    wp = Waypoint_Create("MyWP", "ASet", None)
    assert wp.GetName() == "MyWP"


def test_waypoint_create_registers_globally():
    Waypoint_Create("RegisteredWP", "SomeSet", None)
    assert "RegisteredWP" in _waypoint_registry


def test_waypoint_create_stores_correct_instance():
    wp = Waypoint_Create("ExactWP", "SomeSet", None)
    assert _waypoint_registry["ExactWP"] is wp


# ── App.Waypoint_Create ───────────────────────────────────────────────────────

def test_app_waypoint_create_accessible():
    wp = App.Waypoint_Create("AppWP", "ASet", None)
    assert isinstance(wp, Waypoint)


# ── PlaceObjectByName ─────────────────────────────────────────────────────────

def test_place_object_by_name_copies_position():
    wp = Waypoint_Create("StartPos", "Set1", None)
    wp.SetTranslateXYZ(100.0, 200.0, 50.0)

    ship = ObjectClass()
    ship.PlaceObjectByName("StartPos")

    loc = ship.GetWorldLocation()
    assert loc.x == 100.0 and loc.y == 200.0 and loc.z == 50.0


def test_place_object_by_name_copies_rotation():
    from engine.appc.math import TGMatrix3
    wp = Waypoint_Create("RotWP", "Set1", None)
    fwd = TGPoint3(1.0, 0.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    wp.AlignToVectors(fwd, up)

    ship = ObjectClass()
    ship.PlaceObjectByName("RotWP")

    r = ship.GetWorldRotation()
    # Rotation should be orthonormal
    for i in range(3):
        assert abs(r.GetRow(i).Length() - 1.0) < 1e-6


def test_place_object_by_name_unknown_does_not_raise():
    ship = ObjectClass()
    ship.PlaceObjectByName("DoesNotExist")  # must not raise


def test_place_object_by_name_leaves_position_unchanged_if_unknown():
    ship = ObjectClass()
    ship.SetTranslateXYZ(7.0, 8.0, 9.0)
    ship.PlaceObjectByName("NoSuchWaypoint")
    loc = ship.GetWorldLocation()
    assert loc.x == 7.0 and loc.y == 8.0 and loc.z == 9.0


# ── SetClass containing_set wiring ───────────────────────────────────────────

def test_add_object_to_set_sets_containing_set():
    s = SetClass()
    s.SetName("MySet")
    obj = ObjectClass()
    s.AddObjectToSet(obj, "obj1")
    assert obj.GetContainingSet() is s


def test_waypoint_create_in_existing_set_wires_containing_set():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "Biranu1")
    wp = Waypoint_Create("Galaxy1Start", "Biranu1", None)
    assert wp.GetContainingSet() is s
    App.g_kSetManager.DeleteSet("Biranu1")


# ── Waypoint_Cast / PlacementObject_Cast ──────────────────────────────────────

from engine.appc.placement import (
    Waypoint_Cast, PlacementObject_Cast,
    PlacementObject_GetObjectBySetName, PlacementObject_GetObject,
)


def test_waypoint_cast_returns_waypoint_for_waypoint():
    wp = Waypoint()
    assert Waypoint_Cast(wp) is wp


def test_waypoint_cast_returns_none_for_non_waypoint():
    assert Waypoint_Cast(ObjectClass()) is None
    assert Waypoint_Cast(None) is None


def test_placement_object_cast_returns_placement_for_placement():
    p = PlacementObject()
    assert PlacementObject_Cast(p) is p


def test_placement_object_cast_returns_none_for_non_placement():
    assert PlacementObject_Cast(ObjectClass()) is None


# ── PlacementObject_GetObjectBySetName ────────────────────────────────────────

def test_get_object_by_set_name_returns_placement_in_set():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "Biranu2")
    wp = Waypoint_Create("Cam1", "Biranu2", None)
    out = PlacementObject_GetObjectBySetName("Biranu2", "Cam1")
    assert out is wp
    App.g_kSetManager.DeleteSet("Biranu2")


def test_get_object_by_set_name_unknown_set_falls_back_to_global():
    """A few mission scripts run waypoint setup before the set is added
    to the SetManager — the global registry catches those lookups."""
    wp = Waypoint_Create("Orphan", "MissingSet", None)
    out = PlacementObject_GetObjectBySetName("MissingSet", "Orphan")
    assert out is wp


def test_get_object_by_set_name_unknown_name_returns_none():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "Biranu3")
    out = PlacementObject_GetObjectBySetName("Biranu3", "NotThere")
    assert out is None
    App.g_kSetManager.DeleteSet("Biranu3")


def test_placement_object_get_object_takes_set_and_name():
    """SDK signature: App.PlacementObject_GetObject(pSet, name).
    Used by MissionLib (nav point lookups), Camera, WarpSequence."""
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "Biranu4")
    wp = Waypoint_Create("NavA", "Biranu4", None)
    assert PlacementObject_GetObject(s, "NavA") is wp
    assert PlacementObject_GetObject(s, "Missing") is None
    App.g_kSetManager.DeleteSet("Biranu4")


def test_placement_object_get_object_with_none_set_falls_back_to_registry():
    wp = Waypoint_Create("RegistryWP", "NoSuchSet", None)
    assert PlacementObject_GetObject(None, "RegistryWP") is wp


# ── PlacementObject_Create factory ────────────────────────────────────────────

from engine.appc.placement import PlacementObject_Create


def test_placement_object_create_returns_placement_object():
    p = PlacementObject_Create("WarpIn1", "DeepSpace", None)
    assert isinstance(p, PlacementObject)
    assert p.GetName() == "WarpIn1"


def test_placement_object_create_registers_in_global_registry():
    """PlaceObjectByName uses the global _waypoint_registry — placement
    objects must register so the lookup succeeds."""
    p = PlacementObject_Create("RegisteredP", "AnySet", None)
    assert _waypoint_registry["RegisteredP"] is p


def test_placement_object_create_registers_in_named_set():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "BiranuP")
    p = PlacementObject_Create("PInBiranuP", "BiranuP", None)
    assert s.GetObject("PInBiranuP") is p
    App.g_kSetManager.DeleteSet("BiranuP")


def test_placement_object_create_handles_missing_set():
    """If the named set hasn't been added to the SetManager, the placement
    is still created and registered in the global registry — only the per-set
    addition is skipped (mirrors Waypoint_Create behaviour)."""
    p = PlacementObject_Create("OrphanP", "DefinitelyNoSuchSet", None)
    assert isinstance(p, PlacementObject)
    assert _waypoint_registry["OrphanP"] is p


def test_placement_object_create_then_place_object_by_name():
    """End-to-end: create placement, then use it as a PlaceObjectByName target."""
    from engine.appc.objects import ObjectClass
    from engine.appc.math import TGPoint3
    p = PlacementObject_Create("TargetWP", "AnySet2", None)
    p.SetTranslateXYZ(10.0, 20.0, 30.0)
    obj = ObjectClass()
    obj.PlaceObjectByName("TargetWP")
    loc = obj.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == (10.0, 20.0, 30.0)


def test_app_exposes_placement_object_create():
    assert App.PlacementObject_Create is PlacementObject_Create


# ── Waypoint.InsertAfterObj ───────────────────────────────────────────────────
#
# SDK convention (ground truth): self.InsertAfterObj(other) splices `other` in
# immediately AFTER `self` — i.e. self.GetNext() is other afterwards. See
# AI/Compound/DockWithStarbase.py:296-299 (pWaypointStart.InsertAfterObj(
# pWaypointEnd) followed by a guard that wants pWaypointStart.GetNext() ==
# pWaypointEnd) and the auto-generated *_Placements.py cutscene chains
# ("Attaching object <arg> after <self>").

def test_insert_after_obj_links_pair():
    a, b = Waypoint(), Waypoint()
    a.InsertAfterObj(b)
    assert a.GetNext() is b
    assert b.GetPrev() is a


def test_insert_after_obj_chains_three():
    a, b, c = Waypoint(), Waypoint(), Waypoint()
    a.InsertAfterObj(b)
    b.InsertAfterObj(c)
    assert a.GetNext() is b
    assert b.GetNext() is c
    assert c.GetPrev() is b
    assert b.GetPrev() is a


def test_insert_after_obj_into_middle_relinks_neighbours():
    a, c = Waypoint(), Waypoint()
    a.InsertAfterObj(c)        # a <-> c
    b = Waypoint()
    a.InsertAfterObj(b)        # a <-> b <-> c
    assert a.GetNext() is b
    assert b.GetPrev() is a
    assert b.GetNext() is c
    assert c.GetPrev() is b


def test_insert_after_obj_with_none_is_noop():
    """self.InsertAfterObj(None) does nothing at all to self — it must not
    detach self from any chain it's already part of (unlike the pre-fix
    implementation, which unconditionally detached self first)."""
    a, b, c = Waypoint(), Waypoint(), Waypoint()
    a.InsertAfterObj(b)        # a <-> b
    b.InsertAfterObj(c)        # a <-> b <-> c
    b.InsertAfterObj(None)
    assert a.GetNext() is b
    assert b.GetPrev() is a
    assert b.GetNext() is c
    assert c.GetPrev() is b


def test_insert_after_obj_detaches_other_from_prior_chain():
    a, b, c = Waypoint(), Waypoint(), Waypoint()
    a.InsertAfterObj(b)        # a <-> b
    b.InsertAfterObj(c)        # a <-> b <-> c
    # Re-splice c directly after a — should detach c from between a and b.
    a.InsertAfterObj(c)
    assert a.GetNext() is c    # c is now directly after a
    assert c.GetPrev() is a
    assert c.GetNext() is b
    assert b.GetPrev() is c
    assert b.GetNext() is None
