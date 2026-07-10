from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import ZoomTargetMode


def _cam():
    return CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")


def test_viewscreen_zoom_target_is_zoomtarget_mode():
    cam = _cam()
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")
    assert isinstance(mode, ZoomTargetMode)
    # identity-stable (same mode instance on re-fetch)
    assert cam.GetNamedCameraMode("ViewscreenZoomTarget") is mode
    assert mode._owner_camera is cam


def test_vs_active_defaults_false_not_stub():
    cam = _cam()
    # Real attribute — must be exactly False, NOT a truthy _LoudStub lambda.
    assert cam._vs_active is False


def test_addmodehierarchy_engagement_seam():
    cam = _cam()
    assert cam._vs_active is False
    cam.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")
    assert cam._vs_active is True


def test_addmodehierarchy_other_pairs_are_noops():
    cam = _cam()
    cam.AddModeHierarchy("ViewscreenZoomTarget", "ViewscreenForward")
    assert cam._vs_active is False
    cam.AddModeHierarchy("InvalidSpace", "Target")
    assert cam._vs_active is False
