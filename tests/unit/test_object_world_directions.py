"""World-direction helpers on ObjectClass (column-vector convention)."""

from engine.appc.objects import ObjectClass
from engine.appc.math import TGMatrix3, TGPoint3


def _yaw90():
    # Forward (col1) points +X, up (col2) stays +Z, right (col0) -> -Y... build
    # an explicit orthonormal matrix to check column extraction unambiguously.
    m = TGMatrix3()
    m.SetCol(0, TGPoint3(0.0, -1.0, 0.0))   # right
    m.SetCol(1, TGPoint3(1.0, 0.0, 0.0))    # forward
    m.SetCol(2, TGPoint3(0.0, 0.0, 1.0))    # up
    return m


def test_world_direction_helpers_return_real_vectors_not_stubs():
    o = ObjectClass()
    o.SetMatrixRotation(_yaw90())
    fwd = o.GetWorldForwardTG()
    assert (fwd.x, fwd.y, fwd.z) == (1.0, 0.0, 0.0)
    back = o.GetWorldBackwardTG()
    assert (back.x, back.y, back.z) == (-1.0, 0.0, 0.0)
    up = o.GetWorldUpTG()
    assert (up.x, up.y, up.z) == (0.0, 0.0, 1.0)
    down = o.GetWorldDownTG()
    assert (down.x, down.y, down.z) == (0.0, 0.0, -1.0)
    right = o.GetWorldRightTG()
    assert (right.x, right.y, right.z) == (0.0, -1.0, 0.0)
    left = o.GetWorldLeftTG()
    assert (left.x, left.y, left.z) == (0.0, 1.0, 0.0)


def test_default_identity_directions_are_unit():
    o = ObjectClass()  # identity rotation
    fwd = o.GetWorldForwardTG()
    assert (fwd.x, fwd.y, fwd.z) == (0.0, 1.0, 0.0)
    up = o.GetWorldUpTG()
    assert (up.x, up.y, up.z) == (0.0, 0.0, 1.0)
