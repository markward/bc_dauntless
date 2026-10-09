"""Bridge editor fly camera (spec 2026-10-08-bridge-emitters §4). Conventions
match _BridgeCamera: bridge up +Z, forward at yaw 0 is +Y, +dx looks right,
+dy (screen down) looks down."""
import math

import pytest

from engine.bridge_editor import fly_camera as fc


def approx(v, w, tol=1e-6):
    return all(abs(a - b) < tol for a, b in zip(v, w))


def test_from_pose_round_trips_the_look_direction():
    cam = fc.FlyCamera.from_pose(eye=(10, 20, 50), target=(10, 10, 50))
    eye, target, up, fov = cam.pose()
    assert approx(eye, (10, 20, 50))
    assert approx(target, (10, 19, 50))          # unit step along -Y
    assert up == fc.UP
    assert fov == fc.FOV_Y_RAD


def test_from_pose_keeps_pitch():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 1))
    assert approx(cam.forward(), (0, math.sqrt(0.5), math.sqrt(0.5)))


def test_degenerate_pose_looks_forward():
    cam = fc.FlyCamera.from_pose(eye=(1, 2, 3), target=(1, 2, 3))
    assert approx(cam.forward(), (0, 1, 0))


def test_right_is_forward_cross_up():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    assert approx(cam.right(), (1, 0, 0))


def test_positive_dx_looks_right_and_positive_dy_looks_down():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(100, 0)
    assert cam.forward()[0] > 0
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(0, 100)
    assert cam.forward()[2] < 0


def test_pitch_clamps():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(0, -1e6)
    assert math.asin(cam.forward()[2]) == pytest.approx(fc.PITCH_LIMIT_RAD)


def test_move_forward_strafe_and_lift():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0)
    assert approx(cam.eye, (0, fc.BASE_SPEED, 0))
    cam.move(1.0, forward=0, strafe=1, lift=0)
    assert approx(cam.eye, (fc.BASE_SPEED, fc.BASE_SPEED, 0))
    cam.move(1.0, forward=0, strafe=0, lift=-1)            # Q = down
    assert approx(cam.eye, (fc.BASE_SPEED, fc.BASE_SPEED, -fc.BASE_SPEED))


def test_fast_and_slow_scale_speed():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0, fast=True)
    assert cam.eye[1] == pytest.approx(fc.BASE_SPEED * fc.FAST_MULT)
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0, slow=True)
    assert cam.eye[1] == pytest.approx(fc.BASE_SPEED * fc.SLOW_MULT)


def test_zero_dt_does_not_move():
    cam = fc.FlyCamera.from_pose(eye=(1, 2, 3), target=(1, 3, 3))
    cam.move(0.0, forward=1, strafe=1, lift=1, fast=True)
    assert approx(cam.eye, (1, 2, 3))
