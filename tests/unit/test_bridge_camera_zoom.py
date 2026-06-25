"""_BridgeCamera zoom-into-officer state machine (step 5a). Pure unit — drives
set_zoom_target/compute_camera with module-global zoom params injected."""
import math
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera

_SAVED = {}


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_ZOOM_MIN", "_BRIDGE_ZOOM_MAX",
              "_BRIDGE_ZOOM_TIME"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_captain_view_when_no_target():
    bc = _BridgeCamera()
    eye, target, up, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)         # max_zoom == 1.0
    assert len((eye, target, up, fov)) == 4


def test_full_zoom_points_at_target_and_narrows_fov():
    bc = _BridgeCamera()
    # Drive the ease to completion (dt >> zoom_time clamps _zoom_t to 1.0).
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)
    eye, target, up, fov = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    fl = math.sqrt(sum(c * c for c in fwd))
    assert (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * 0.64)


def test_deselect_eases_back_to_captain_view():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)   # zoomed in
    bc.set_zoom_target(None, dt=10.0)               # eased fully back
    _, _, _, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_mouse_look_suspended_while_zooming():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)
    y0 = bc.yaw_rad
    bc.apply(100.0, 50.0)                            # ignored while zoomed
    assert bc.yaw_rad == y0


def test_zoom_from_behind_and_up_stays_roll_free():
    """Regression: zooming to a station from a facing-behind, pitched-up view
    must leave the camera level (no roll). The eased forward used to keep the
    pre-zoom up vector, tilting the horizon at the station."""
    bc = _BridgeCamera()
    bc.yaw_rad = math.pi          # facing behind
    bc.pitch_rad = 0.3            # looking slightly up
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)   # station off to the side
    eye, target, up, _ = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    # Roll-free ⇔ up has no component along the camera's right axis
    # (right = fwd × worldZ). Equivalently up lies in the fwd/worldZ plane.
    right = (fwd[1] * 1.0 - fwd[2] * 0.0,
             fwd[2] * 0.0 - fwd[0] * 1.0,
             fwd[0] * 0.0 - fwd[1] * 0.0)
    roll = sum(u * r for u, r in zip(up, right))
    assert roll == pytest.approx(0.0, abs=1e-6)


def test_zoom_t_clamps_to_unit_interval():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=100.0)
    assert bc._zoom_t == 1.0
    bc.set_zoom_target(None, dt=100.0)
    assert bc._zoom_t == 0.0
