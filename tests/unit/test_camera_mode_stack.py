import App
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import LockedMode, ChaseMode, TargetMode
from engine.appc.math import TGPoint3


def _cam():
    return CameraObjectClass_Create(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")


def test_get_named_mode_builds_and_caches():
    c = _cam()
    m = c.GetNamedCameraMode("Locked")
    assert isinstance(m, LockedMode)
    assert c.GetNamedCameraMode("Locked") is m          # cached, same instance
    assert isinstance(c.GetNamedCameraMode("Chase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("ReverseChase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("Target"), TargetMode)


def test_get_named_mode_unknown_is_none():
    assert _cam().GetNamedCameraMode("Bogus") is None


def test_push_pop_current():
    c = _cam()
    assert c.GetCurrentCameraMode() is None
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
    assert c.GetCurrentCameraMode(0) is m               # NewMode calls with arg 0
    c.PopCameraMode()
    assert c.GetCurrentCameraMode() is None


def test_push_seeds_initial_pose_from_camera():
    c = _cam()                                           # position (1,2,3)
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert m._cur is not None
    assert m._cur[0] == (1.0, 2.0, 3.0)                  # seeded eye = camera pos


def test_camera_new_mode_pushes_live_mode():
    """End-to-end through the SDK's Camera.NewMode."""
    import Camera
    c = _cam()
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    ok = Camera.NewMode(c, "Chase", 0, 1, [("Target", ship)])
    assert ok == 1
    assert isinstance(c.GetCurrentCameraMode(), ChaseMode)
    assert c.GetCurrentCameraMode().GetAttrIDObject("Target") is ship
