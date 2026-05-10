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


# ── SetClass.GetFirstObject / GetNextObject iteration ────────────────────────

def test_get_first_object_returns_none_when_empty():
    s = SetClass()
    assert s.GetFirstObject() is None


def test_get_first_object_returns_first_inserted():
    from engine.appc.objects import ObjectClass
    s = SetClass()
    a, b = ObjectClass(), ObjectClass()
    s.AddObjectToSet(a, "alpha")
    s.AddObjectToSet(b, "beta")
    assert s.GetFirstObject() is a


def test_get_next_object_walks_in_insertion_order():
    from engine.appc.objects import ObjectClass
    s = SetClass()
    a, b, c = ObjectClass(), ObjectClass(), ObjectClass()
    s.AddObjectToSet(a, "alpha")
    s.AddObjectToSet(b, "beta")
    s.AddObjectToSet(c, "gamma")
    assert s.GetNextObject(a.GetObjID()) is b
    assert s.GetNextObject(b.GetObjID()) is c


def test_get_next_object_wraps_to_first():
    """SDK iteration loop relies on wrap-around to detect end-of-iteration."""
    from engine.appc.objects import ObjectClass
    s = SetClass()
    a, b = ObjectClass(), ObjectClass()
    s.AddObjectToSet(a, "alpha")
    s.AddObjectToSet(b, "beta")
    assert s.GetNextObject(b.GetObjID()) is a


def test_get_next_object_returns_none_for_unknown_id():
    s = SetClass()
    assert s.GetNextObject(999999) is None


def test_set_lights_initially_empty():
    pSet = App.SetClass_Create()
    assert pSet._lights == []
    assert pSet._lights_by_name == {}
    assert pSet.GetLight("missing") is None


def test_set_create_ambient_light_4_arg():
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    light = pSet.CreateAmbientLight(1.0, 1.0, 1.0, 0.7, "ambientlight1")
    assert isinstance(light, Light)
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (1.0, 1.0, 1.0)
    assert light._dimmer == 0.7
    assert pSet._lights == [light]
    assert pSet.GetLight("ambientlight1") is light


def test_set_create_directional_light_8_arg():
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    light = pSet.CreateDirectionalLight(1, 1, 1, 1, 1, 0, 0, "light1")
    assert light._kind == Light.KIND_DIRECTIONAL
    assert light._color == (1.0, 1.0, 1.0)
    assert light._dimmer == 1.0
    assert light._direction_world == (1.0, 0.0, 0.0)
    assert pSet.GetLight("light1") is light


def test_set_backdrops_initially_empty():
    pSet = App.SetClass_Create()
    assert pSet._backdrops == []


def test_add_backdrop_to_set_appends_in_order():
    pSet = App.SetClass_Create()
    star = App.StarSphere_Create()
    cloud1 = App.BackdropSphere_Create()
    cloud2 = App.BackdropSphere_Create()
    pSet.AddBackdropToSet(star, "stars")
    pSet.AddBackdropToSet(cloud1, "nebula1")
    pSet.AddBackdropToSet(cloud2, "nebula2")
    assert pSet._backdrops == [star, cloud1, cloud2]


def test_add_backdrop_assigns_name_to_object():
    pSet = App.SetClass_Create()
    star = App.StarSphere_Create()
    pSet.AddBackdropToSet(star, "Backdrop stars")
    assert star.GetName() == "Backdrop stars"


def test_set_unrelated_renderer_methods_still_stub():
    """Regression: catch-all _RendererStub still handles non-light methods."""
    pSet = App.SetClass_Create()
    # SetBackgroundModel is not implemented — should silently chain via stub.
    result = pSet.SetBackgroundModel("data/Models/Sets/X.nif", 0, 0, 0)
    # Result is a chainable stub; the test only checks that the call did
    # not raise AttributeError.
    assert result is not None
