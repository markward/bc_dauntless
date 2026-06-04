"""Unit tests for _CameraDirector — mode dispatch shim that owns the
mode flag and forwards compute() to the appropriate camera class.

At Task 3 the director only handles CHASE mode. TRACKING dispatch and
mode transitions arrive in Task 10."""
import math
import pytest


def _make_ship_pose():
    from engine.appc.math import TGPoint3, TGMatrix3
    return TGPoint3(0.0, 0.0, 0.0), TGMatrix3()


class _FakePlayer:
    def __init__(self):
        self._loc, self._rot = _make_ship_pose()

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return None  # no target → stays in Chase


def test_director_starts_in_chase_mode():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    assert d.mode is CameraMode.CHASE


def test_director_compute_matches_chase_camera_when_in_chase():
    from engine.cameras.director import _CameraDirector
    from engine.cameras.chase    import _ChaseCamera

    d  = _CameraDirector()
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    d.chase.set_ship_radius(1.0)

    player = _FakePlayer()
    eye_d, look_d, up_d = d.compute(player=player, dt=1.0/60)
    eye_c, look_c, up_c = cc.compute_camera(
        player.GetWorldLocation(), player.GetWorldRotation(), dt=1.0/60,
    )

    for got, want in zip(eye_d, eye_c):  assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(look_d, look_c): assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(up_d, up_c):    assert got == pytest.approx(want, abs=1e-6)
