import pytest


def _make_pose(x, y, z, radius=0.0):
    """Minimal stand-in for a ship or planet object with the pose API."""
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Pose:
        def __init__(self):
            self._loc = TGPoint3(x, y, z)
            self._rot = TGMatrix3()  # identity by default
            self._radius = radius

        def GetWorldLocation(self):
            return self._loc

        def GetWorldRotation(self):
            return self._rot

        def GetRadius(self):
            return self._radius

    return _Pose()


def test_ship_world_matrix_scales_mesh_not_position():
    """Identity rotation: upper-left 3x3 scaled by SHIP_SCALE, translation unchanged."""
    from engine import host_loop
    from engine.scale import SHIP_SCALE

    pose = _make_pose(100.0, 200.0, 300.0)
    m = host_loop._ship_world_matrix(pose)

    assert len(m) == 16
    # Upper-left 3x3: identity * SHIP_SCALE
    assert m[0]  == pytest.approx(SHIP_SCALE)   # row0 col0
    assert m[5]  == pytest.approx(SHIP_SCALE)   # row1 col1
    assert m[10] == pytest.approx(SHIP_SCALE)   # row2 col2
    # Off-diagonal rotation elements -> 0
    assert m[1]  == pytest.approx(0.0)
    assert m[4]  == pytest.approx(0.0)
    # Translation column: unchanged world position
    assert m[3]  == pytest.approx(100.0)
    assert m[7]  == pytest.approx(200.0)
    assert m[11] == pytest.approx(300.0)
    # Homogeneous row
    assert m[12] == pytest.approx(0.0)
    assert m[13] == pytest.approx(0.0)
    assert m[14] == pytest.approx(0.0)
    assert m[15] == pytest.approx(1.0)
