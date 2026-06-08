"""The chase rotation spring must be frame-rate independent: equal
elapsed wall time => equal smoothed basis, regardless of frame count.
This is the invariant that makes feeding wall-clock dt (not a fixed
TICK_DT) to the camera correct. Regression guard for host_loop's
_compute_camera dt."""

import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.cameras.chase import _ChaseCamera


def _yaw(angle_deg):
    m = TGMatrix3(); m.MakeYRotation(math.radians(angle_deg)); return m


def _loc():
    return TGPoint3(0.0, 0.0, 0.0)


def _converge(n_frames, total_time, target):
    cam = _ChaseCamera()
    dt = total_time / n_frames
    start = _yaw(0.0)
    cam.compute_camera(_loc(), start, dt=dt)  # seed
    for _ in range(n_frames):
        cam.compute_camera(_loc(), target, dt=dt)
    return cam._smoothed_rot.GetCol(1)  # forward column


def test_chase_spring_same_elapsed_time_converges_equally():
    target = _yaw(45.0)
    coarse = _converge(10, 1.0, target)    # 10 fps for 1s
    fine = _converge(240, 1.0, target)     # 240 fps for 1s
    assert abs(coarse.x - fine.x) < 1e-3
    assert abs(coarse.y - fine.y) < 1e-3
    assert abs(coarse.z - fine.z) < 1e-3
