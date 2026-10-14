# tests/unit/test_bridge_camera_mode_pose.py
"""_BridgeCamera's mode-pose slot: a bridge PlacementWatch shot.
Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md §3.2"""
import engine.host_loop as hl
from engine.host_loop import _BridgeCamera

SHOT = ((-35.0, -142.0, 45.0), (-25.0, -60.0, 60.0), (0.0, 0.0, 1.0))


def test_mode_pose_overrides_captain_view():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    eye, target, up, fov = cam.compute_camera()
    assert (eye, target, up) == SHOT
    assert fov == _BridgeCamera.FOV_Y_RAD * hl._BRIDGE_ZOOM_MAX


def test_clear_mode_pose_restores_captain_view():
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose(*SHOT)
    cam.clear_mode_pose()
    assert cam.compute_camera() == base


def test_mode_pose_freezes_mouse_look():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    before = (cam.yaw_rad, cam.pitch_rad)
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) == before


def test_anim_pose_outranks_mode_pose():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    clip = ((1.0, 2.0, 3.0), (1.0, 3.0, 3.0), (0.0, 0.0, 1.0))
    cam.set_anim_pose(*clip)
    eye, target, up, _ = cam.compute_camera()
    assert (eye, target, up) == clip


def test_hold_anim_pose_does_not_latch_mode_pose():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    cam.hold_anim_pose()               # no clip active: latches None
    cam.clear_mode_pose()
    assert cam._held_pose is None


def test_reset_cutscene_pose_clears_mode_pose():
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose(*SHOT)
    cam.reset_cutscene_pose()          # mission swap
    assert cam.compute_camera() == base
