"""_BridgeCamera held-pose persistence: a completed bridge camera animation
holds its final pose while the seated captain mode (GalaxyBridgeCaptain,
a PlaceByDirectionMode) is popped off the live maincamera's mode stack, and
reverts to the baked seated eye the moment that mode is re-pushed.

See docs/superpowers/specs/2026-07-25-bridge-camera-stand-persistence-design.md.
"""
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera
from engine.appc.bridge_set import ZoomCameraObjectClass
from engine.appc.camera_modes import PlaceByDirectionMode

_SAVED = {}

_STAND = ((1.0, 2.0, 3.0), (1.0, 2.0, 4.0), (0.0, 0.0, 1.0))


def _make_cam():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    c.SetMinZoom(0.64); c.SetMaxZoom(1.0); c.SetZoomTime(0.375)
    return c


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_CAMERA_MOVE", "_BRIDGE_ZOOM_MIN",
              "_BRIDGE_ZOOM_MAX", "_BRIDGE_ZOOM_TIME", "_BRIDGE_ZOOM_CAM"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)   # baked seated eye = origin in this fixture
    hl._BRIDGE_CAMERA_MOVE = None
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375
    hl._BRIDGE_ZOOM_CAM = _make_cam()         # empty mode stack => seated mode absent


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_hold_anim_pose_latches_final_and_clears_transient():
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    assert bc._anim_pose is None
    assert bc._held_pose == _STAND


def test_held_pose_used_when_seated_mode_absent():
    # Seated captain mode is NOT on the (empty) stack: the standing pose governs.
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    eye, target, up, fov = bc.compute_camera()
    assert eye == (1.0, 2.0, 3.0)
    assert target == (1.0, 2.0, 4.0)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * hl._BRIDGE_ZOOM_MAX)


def test_held_pose_eye_anchored_but_look_tracks_watch_target():
    # AT_WATCH_ME during a held (standing) pose must still TURN the camera: the
    # eye stays anchored at the held position while the look direction eases
    # toward the watched target via the maincamera zoom look-at. Regression: the
    # held pose used to short-circuit compute_camera and freeze the whole
    # transform, so the standing camera could not follow Picard/Saffi.
    bc = _BridgeCamera()
    bc.set_anim_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))  # stand: eye at origin, look +Y
    bc.hold_anim_pose()
    # Watch a character off to +X (engages the maincamera zoom look-at).
    hl._BRIDGE_ZOOM_CAM.engage(1.0, (10.0, 0.0, 0.0))
    hl._BRIDGE_ZOOM_CAM.advance(10.0)                       # ease to completion
    eye, target, _up, _fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)                           # eye still anchored at the standing position
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    assert fwd[0] > 0.9                                     # look now aimed toward the watched +X target


def test_held_pose_holds_forward_when_nothing_watched():
    # With no zoom engaged the held pose keeps its resting forward (unchanged).
    bc = _BridgeCamera()
    bc.set_anim_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    bc.hold_anim_pose()
    eye, target, _up, _fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    assert fwd == pytest.approx((0.0, 1.0, 0.0))            # still looking +Y


def test_held_pose_discarded_when_seated_mode_present():
    # ResetBridgeCamera re-pushes GalaxyBridgeCaptain: revert to the seated eye.
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    hl._BRIDGE_ZOOM_CAM.PushCameraMode(PlaceByDirectionMode("PlaceByDirection"))
    eye, _target, _up, fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)          # baked seated eye, NOT the held (1,2,3)
    assert bc._held_pose is None           # stale latch dropped
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_no_held_pose_uses_seated_eye():
    # Regression guard: normal seated view is untouched.
    bc = _BridgeCamera()
    eye, _target, _up, fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_reset_cutscene_pose_clears_both():
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()          # _held_pose now set, _anim_pose None
    bc.set_anim_pose(*_STAND)    # _anim_pose set again
    bc.reset_cutscene_pose()
    assert bc._anim_pose is None
    assert bc._held_pose is None
    # after reset, with no held pose, compute_camera returns the baked seated eye
    eye, _t, _u, _f = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)


def test_apply_frozen_while_held_and_seated_mode_absent():
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()                 # held; empty stack => seated mode absent
    before = (bc.yaw_rad, bc.pitch_rad)
    bc.apply(100.0, 100.0)
    assert (bc.yaw_rad, bc.pitch_rad) == before


def test_apply_resumes_once_seated_mode_present():
    from engine.appc.camera_modes import PlaceByDirectionMode
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    hl._BRIDGE_ZOOM_CAM.PushCameraMode(PlaceByDirectionMode("PlaceByDirection"))
    before_yaw = bc.yaw_rad
    bc.apply(100.0, 0.0)
    assert bc.yaw_rad != before_yaw     # seated mode present => mouse-look active


def test_anim_pose_takes_precedence_over_held():
    bc = _BridgeCamera()
    bc._held_pose = ((9.0, 9.0, 9.0), (9.0, 9.0, 10.0), (0.0, 0.0, 1.0))
    bc.set_anim_pose(*_STAND)           # active override present
    eye, target, _up, _fov = bc.compute_camera()
    assert eye == (1.0, 2.0, 3.0)       # _STAND eye, not the held (9,9,9)
    assert target == (1.0, 2.0, 4.0)
