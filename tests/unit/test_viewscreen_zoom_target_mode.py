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


def test_vs_last_player_target_defaults_none_not_stub():
    cam = _cam()
    # Real attribute — must be exactly None, NOT a truthy _LoudStub lambda.
    assert cam._vs_last_player_target is None


def test_addmodehierarchy_is_a_pure_noop():
    cam = _cam()
    # BC installs the InvalidViewscreen -> ViewscreenZoomTarget -> ViewscreenForward
    # chain at camera creation; we model first-valid-wins in the resolver instead,
    # so this stays a no-op and must not create hidden state.
    assert cam.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget") is None
    assert cam.AddModeHierarchy("InvalidSpace", "Target") is None
    # NOTE: _LoudStub.__getattr__ hands back a truthy lambda for ANY missing
    # attribute name, so hasattr() can never prove a removed engagement flag
    # is absent from `cam` — that guarantee (nothing reads or writes it any
    # more) is enforced by the repo-wide cleanup grep run at the end of the
    # R1+R2 rework, not by an assertion in this test.
