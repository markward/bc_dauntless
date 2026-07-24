"""In-space cutscene camera modes must anchor on the render-interpolated pose
of their tracked object when a `pose_of` provider is supplied, so a camera
locked/chasing a 60 Hz-stepped ship tracks exactly what the renderer draws
(smooth-motion fix). When pose_of is None they read the live pose as before.
"""
import pytest

from engine.appc.math import TGPoint3, TGMatrix3


class _FakeTarget:
    def __init__(self, loc_xyz):
        self._loc = TGPoint3(*loc_xyz)
        self._rot = TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def _shift_provider(V):
    def pose_of(obj):
        loc = obj.GetWorldLocation()
        return (TGPoint3(loc.x + V[0], loc.y + V[1], loc.z + V[2]),
                obj.GetWorldRotation())
    return pose_of


def test_locked_mode_ideal_reads_target_through_pose_of():
    from engine.appc.camera_modes import CameraMode_Create
    m = CameraMode_Create("Locked")
    t = _FakeTarget((0.0, 0.0, 0.0))
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))

    eye0, _f0, _u0 = m.Update(dt=None)                      # live
    V = (100.0, -30.0, 7.0)
    eye1, _f1, _u1 = m.Update(dt=None, pose_of=_shift_provider(V))

    for a, b, v in zip(eye1, eye0, V):
        assert a == pytest.approx(b + v, abs=1e-6)


def test_chase_mode_ideal_reads_target_through_pose_of():
    from engine.appc.camera_modes import CameraMode_Create
    m = CameraMode_Create("Chase")
    t = _FakeTarget((5.0, 5.0, 5.0))
    m.SetAttrIDObject("Target", t)

    eye0, f0, _u0 = m.Update(dt=None)
    V = (40.0, 0.0, -12.0)
    eye1, f1, _u1 = m.Update(dt=None, pose_of=_shift_provider(V))

    # Eye offset built from target loc → shifts by V; look-at direction is
    # unchanged (both endpoints shifted equally).
    for a, b, v in zip(eye1, eye0, V):
        assert a == pytest.approx(b + v, abs=1e-6)
    for a, b in zip(f1, f0):
        assert a == pytest.approx(b, abs=1e-6)


def test_pose_of_none_is_unchanged_live_behavior():
    from engine.appc.camera_modes import CameraMode_Create
    m = CameraMode_Create("Chase")
    t = _FakeTarget((5.0, 5.0, 5.0))
    m.SetAttrIDObject("Target", t)
    assert m.Update(dt=None) == m.Update(dt=None, pose_of=None)
