"""Unit tests for SetClass and SetManager."""
import pytest
import App
from engine.appc.sets import SetClass, SetManager, SetClass_Create
from engine.appc.ships import ShipClass_Create


def test_set_class_create_returns_set():
    s = SetClass_Create()
    assert isinstance(s, SetClass)


def test_set_class_name_roundtrip():
    s = SetClass_Create()
    s.SetName("Biranu1")
    assert s.GetName() == "Biranu1"


def test_set_class_add_and_get_object():
    s = SetClass_Create()
    ship = ShipClass_Create("Galaxy")
    result = s.AddObjectToSet(ship, "player")
    assert result is True
    assert s.GetObject("player") is ship


def test_set_class_add_sets_name_on_object():
    s = SetClass_Create()
    ship = ShipClass_Create("Galaxy")
    s.AddObjectToSet(ship, "USS Enterprise")
    assert ship.GetName() == "USS Enterprise"


def test_set_class_get_missing_returns_none():
    s = SetClass_Create()
    assert s.GetObject("no such ship") is None


def test_set_class_delete_object():
    s = SetClass_Create()
    ship = ShipClass_Create("Galaxy")
    s.AddObjectToSet(ship, "ship1")
    s.DeleteObjectFromSet("ship1")
    assert s.GetObject("ship1") is None


def test_set_manager_add_and_get():
    mgr = SetManager()
    s = SetClass_Create()
    mgr.AddSet(s, "TestSet")
    assert mgr.GetSet("TestSet") is s


def test_set_manager_add_sets_name():
    mgr = SetManager()
    s = SetClass_Create()
    mgr.AddSet(s, "Biranu1")
    assert s.GetName() == "Biranu1"


def test_set_manager_get_missing_returns_none():
    mgr = SetManager()
    assert mgr.GetSet("no such set") is None


def test_set_manager_delete_set():
    mgr = SetManager()
    s = SetClass_Create()
    mgr.AddSet(s, "TempSet")
    mgr.DeleteSet("TempSet")
    assert mgr.GetSet("TempSet") is None


def test_set_manager_delete_all_sets():
    mgr = SetManager()
    mgr.AddSet(SetClass_Create(), "A")
    mgr.AddSet(SetClass_Create(), "B")
    mgr.DeleteAllSets()
    assert mgr.GetNumSets() == 0


def test_app_g_kSetManager_accessible():
    assert App.g_kSetManager is not None


def test_app_set_class_create():
    s = App.SetClass_Create()
    assert isinstance(s, SetClass)


# ── SetClass cameras ──────────────────────────────────────────────────────────

def test_get_camera_returns_none_when_unset():
    """CutsceneCameraBegin's `if not pSet.GetCamera(name):` guard depends on
    a freshly-loaded set having no cameras yet."""
    s = SetClass()
    assert s.GetCamera("CutsceneCam") is None


def test_add_camera_then_get_round_trip():
    s = SetClass()
    cam = object()
    s.AddCameraToSet(cam, "CutsceneCam")
    assert s.GetCamera("CutsceneCam") is cam


def test_active_camera_round_trip():
    s = SetClass()
    cam = object()
    s.AddCameraToSet(cam, "MainCam")
    assert s.GetActiveCamera() is None
    s.SetActiveCamera("MainCam")
    assert s.GetActiveCamera() is cam


def test_remove_camera_clears_active_when_active():
    s = SetClass()
    cam = object()
    s.AddCameraToSet(cam, "MainCam")
    s.SetActiveCamera("MainCam")
    s.RemoveCameraFromSet("MainCam")
    assert s.GetCamera("MainCam") is None
    assert s.GetActiveCamera() is None


# ── SetManager rendered-set tracking ──────────────────────────────────────────

def test_make_rendered_set_round_trip():
    sm = App.g_kSetManager
    pSet = SetClass()
    sm.AddSet(pSet, "bridge")
    sm.MakeRenderedSet("bridge")
    assert sm.GetRenderedSet() is pSet


def test_get_rendered_set_returns_none_when_unset():
    from engine.appc.sets import SetManager
    fresh = SetManager()
    assert fresh.GetRenderedSet() is None
