"""_BridgeCamera zoom geometry, driven via the ZoomCameraObjectClass the host
harvests into hl._BRIDGE_ZOOM_CAM (MenuEventHandler port)."""
import math
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera
from engine.appc.bridge_set import ZoomCameraObjectClass

_SAVED = {}


def _make_cam():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    c.SetMinZoom(0.64); c.SetMaxZoom(1.0); c.SetZoomTime(0.375)
    return c


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_CAMERA_MOVE", "_BRIDGE_ZOOM_MIN",
              "_BRIDGE_ZOOM_MAX", "_BRIDGE_ZOOM_TIME", "_BRIDGE_ZOOM_CAM"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)
    hl._BRIDGE_CAMERA_MOVE = None
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375
    hl._BRIDGE_ZOOM_CAM = _make_cam()


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_captain_view_when_no_target():
    bc = _BridgeCamera()
    eye, target, up, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)
    assert len((eye, target, up, fov)) == 4


def test_full_zoom_points_at_target_and_narrows_fov():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0))
    hl._BRIDGE_ZOOM_CAM.advance(10.0)          # ease to completion
    eye, target, up, fov = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    fl = math.sqrt(sum(c * c for c in fwd))
    assert (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * 0.64)


def test_deselect_eases_back_to_captain_view():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    hl._BRIDGE_ZOOM_CAM.disengage(); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    _, _, _, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_mouse_look_suspended_while_zooming():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    y0 = bc.yaw_rad
    bc.apply(100.0, 50.0)
    assert bc.yaw_rad == y0


def test_zoom_from_behind_and_up_stays_roll_free():
    bc = _BridgeCamera()
    bc.yaw_rad = math.pi
    bc.pitch_rad = 0.3
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    eye, target, up, _ = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    right = (fwd[1] * 1.0 - fwd[2] * 0.0,
             fwd[2] * 0.0 - fwd[0] * 1.0,
             fwd[0] * 0.0 - fwd[1] * 0.0)
    roll = sum(u * r for u, r in zip(up, right))
    assert roll == pytest.approx(0.0, abs=1e-6)
