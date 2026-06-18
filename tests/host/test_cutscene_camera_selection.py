# tests/host/test_cutscene_camera_selection.py
import App
from engine.host_loop import _active_cutscene_camera
from engine.appc.bridge_set import BridgeSet_Create, CameraObjectClass_Create
from engine.appc.math import TGPoint3


def _space_set_with_cutscene_cam(name, target):
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")
    mode.SetAttrIDObject("Target", target)
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet(name)
    return s, cam, mode


def test_active_cutscene_camera_found_when_rendered_set_has_live_mode():
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(10.0, 0.0, 0.0))
    s, cam, mode = _space_set_with_cutscene_cam("cc_sel_set", ship)
    got = _active_cutscene_camera(ship)
    assert got is not None
    assert got[0] is cam and got[1] is mode
    App.g_kSetManager.DeleteSet("cc_sel_set")


def test_none_when_no_mode_pushed():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_none_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    App.g_kSetManager.MakeRenderedSet("cc_none_set")
    assert _active_cutscene_camera(App.ShipClass_Create("Galaxy")) is None
    App.g_kSetManager.DeleteSet("cc_none_set")


def test_none_when_rendered_set_unset():
    App.g_kSetManager.MakeRenderedSet("__nonexistent__")
    assert _active_cutscene_camera(None) is None


def test_none_when_mode_target_dead():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_dead_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")            # no Target set => invalid
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet("cc_dead_set")
    assert _active_cutscene_camera(None) is None
    App.g_kSetManager.DeleteSet("cc_dead_set")
