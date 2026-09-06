"""The PlaceByDirection lift must follow the camera's ACTUAL aim, not just the
mouse yaw.

BC's GalaxyBridgeCaptain mode is a *place by direction* mode: the captain's eye
rises and eases toward the viewscreen as the view turns off bridge-forward, so
the aft science/engineering stations are seen over the raised platform and the
arch. Our port fed that placement from `yaw_rad` — the mouse-look accumulator —
alone, while an officer engagement (crew menu / AT_WATCH_ME, and every E1M1 crew
intro) turns the camera through the maincamera zoom look-at instead. The eye
therefore stayed seated for the whole automatic turn and the shot looked into
the platform.

These cover the seated captain path only; a cutscene `_anim_pose` and a held
stand-up `_held_pose` own the eye outright and must stay untouched.
"""
import math
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera
from engine.appc.bridge_set import ZoomCameraObjectClass

# SDK GalaxyBridgeCaptain (CameraModes.py:353-372): BasePosition from
# Bridge.GalaxyBridge.GetBaseCameraPosition(), Movement (0, -15, +15) — "-Y is
# forward, +Z is up" — over [StartMoveAngle 1.25, EndMoveAngle 2.5] radians.
_PBD_EYE = (0.683736, 86.978439, 50.0)
_PBD_MOVE = ((0.0, -15.0, 15.0), 1.25, 2.5)
_ZOOM_TIME = 0.375

# An aft station (science/engineering side of the DBridge): well behind the
# captain's chair in +Y and below eye level. Bearing off bridge-forward from the
# base eye is ~159°, past EndMoveAngle, so a manual turn to face it would apply
# the FULL movement.
_AFT_STATION = (25.0, 150.0, 40.0)

_SAVED = {}
_GLOBALS = ("_BRIDGE_CAMERA_EYE", "_BRIDGE_CAMERA_MOVE", "_BRIDGE_CAMERA_MOVE_SCALE",
            "_BRIDGE_ZOOM_MIN", "_BRIDGE_ZOOM_MAX", "_BRIDGE_ZOOM_TIME",
            "_BRIDGE_ZOOM_CAM")


def setup_function(_):
    for k in _GLOBALS:
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = _PBD_EYE
    hl._BRIDGE_CAMERA_MOVE = _PBD_MOVE
    hl._BRIDGE_CAMERA_MOVE_SCALE = 1.0
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = _ZOOM_TIME
    cam = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    cam.SetMinZoom(0.64); cam.SetMaxZoom(1.0); cam.SetZoomTime(_ZOOM_TIME)
    hl._BRIDGE_ZOOM_CAM = cam


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def _full_zoom_to(point):
    """A camera facing the viewscreen, fully engaged on `point` — the pose every
    E1M1 crew intro produces (mouse-look is frozen, so yaw never moves)."""
    bc = _BridgeCamera()
    assert bc.yaw_rad == pytest.approx(_BridgeCamera.INITIAL_YAW_RAD)
    hl._BRIDGE_ZOOM_CAM.engage(0.64, point)
    hl._BRIDGE_ZOOM_CAM.advance(10.0)
    return bc


def test_zoom_to_an_aft_station_lifts_the_eye_like_a_manual_turn():
    """Engaging an aft officer without touching the mouse must apply the same
    full PlaceByDirection movement a manual turn to that bearing applies: up +15
    and forward -15. Before the fix the eye stayed at the seated BasePosition."""
    bc = _full_zoom_to(_AFT_STATION)
    eye, _target, _up, _fov = bc.compute_camera()
    assert eye[0] == pytest.approx(_PBD_EYE[0])
    assert eye[1] == pytest.approx(_PBD_EYE[1] - 15.0)
    assert eye[2] == pytest.approx(_PBD_EYE[2] + 15.0)


def test_lifted_zoom_still_aims_at_the_officer():
    """The lift moves the eye 15 units up and 15 forward, so the aim has to be
    re-derived from the lifted eye or the officer drifts off-centre by that
    much."""
    bc = _full_zoom_to(_AFT_STATION)
    eye, target, _up, _fov = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    want = (_AFT_STATION[0] - eye[0], _AFT_STATION[1] - eye[1], _AFT_STATION[2] - eye[2])
    wl = math.sqrt(sum(c * c for c in want))
    assert fwd == pytest.approx(tuple(c / wl for c in want), abs=1e-6)


def test_lift_eases_in_with_the_zoom_never_popping():
    """The lift rides the eased aim, so it grows monotonically over the zoom
    instead of snapping on at the start or the end. It stays zero early — the
    movement band only opens at StartMoveAngle (71.6°), well into a 157° swing."""
    bc = _full_zoom_to(_AFT_STATION)
    hl._BRIDGE_ZOOM_CAM.disengage()
    hl._BRIDGE_ZOOM_CAM.advance(10.0)          # back to the seated captain view
    hl._BRIDGE_ZOOM_CAM.engage(0.64, _AFT_STATION)

    lifts = []
    for _ in range(4):
        hl._BRIDGE_ZOOM_CAM.advance(_ZOOM_TIME * 0.25)
        lifts.append(bc.compute_camera()[0][2] - _PBD_EYE[2])

    assert lifts[0] == pytest.approx(0.0)
    assert lifts == sorted(lifts)
    assert lifts[-1] == pytest.approx(15.0)


def test_viewscreen_forward_zoom_keeps_the_seated_eye():
    """A hail zoom (look_at None) eases the aim back to bridge-forward, which is
    angle 0 — no lift. Guards against lifting on every zoom."""
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, None)
    hl._BRIDGE_ZOOM_CAM.advance(10.0)
    eye, _target, _up, _fov = bc.compute_camera()
    assert eye == pytest.approx(_PBD_EYE)


def test_held_stand_pose_eye_is_not_relifted_by_a_zoom():
    """A completed stand-up clip owns the eye outright (it is already an
    elevated pose); an AT_WATCH_ME engagement retargets the aim but must not
    re-place the eye through the seated movement."""
    bc = _BridgeCamera()
    bc.set_anim_pose((5.0, 60.0, 62.0), (5.0, 59.0, 62.0), (0.0, 0.0, 1.0))
    bc.hold_anim_pose()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, _AFT_STATION)
    hl._BRIDGE_ZOOM_CAM.advance(10.0)
    eye, _target, _up, _fov = bc.compute_camera()
    assert eye == pytest.approx((5.0, 60.0, 62.0))


def test_placement_is_continuous_across_the_zoom_boundary():
    """At zoom progress 0 the eased aim IS the mouse-look forward, so placing by
    aim must land on exactly the same eye as placing by yaw. Without that the
    eye would jump the instant a zoom starts or finishes."""
    bc = _BridgeCamera()
    bc.yaw_rad = math.pi - 1.9          # inside the movement band
    bc.pitch_rad = -0.4                 # pitch must not change the bearing
    by_yaw = bc._eye_offset()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, _AFT_STATION)
    hl._BRIDGE_ZOOM_CAM.advance(_ZOOM_TIME * 1e-6)   # a hair past 0
    eye, _target, _up, _fov = bc.compute_camera()
    assert eye == pytest.approx(by_yaw, abs=1e-4)
    assert eye[2] > _PBD_EYE[2]         # and it is a real lift, not the base
