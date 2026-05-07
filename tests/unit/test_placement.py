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
