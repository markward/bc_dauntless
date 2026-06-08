"""Pure-function unit tests for render interpolation math."""

import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.interpolate import lerp_point, nlerp_rotation, lerp_transform


def _det(m: TGMatrix3) -> float:
    a = m._m
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def test_lerp_point_endpoints_and_midpoint():
    a = TGPoint3(0.0, 0.0, 0.0)
    b = TGPoint3(10.0, -4.0, 2.0)
    assert (lerp_point(a, b, 0.0).x, lerp_point(a, b, 0.0).y, lerp_point(a, b, 0.0).z) == (0.0, 0.0, 0.0)
    assert (lerp_point(a, b, 1.0).x, lerp_point(a, b, 1.0).y, lerp_point(a, b, 1.0).z) == (10.0, -4.0, 2.0)
    mid = lerp_point(a, b, 0.5)
    assert (mid.x, mid.y, mid.z) == (5.0, -2.0, 1.0)


def test_nlerp_rotation_alpha_zero_returns_prev():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.0)
    for i in range(3):
        for j in range(3):
            assert out._m[i][j] == prev._m[i][j]


def test_nlerp_rotation_alpha_one_matches_cur():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 1.0)
    for i in range(3):
        for j in range(3):
            assert abs(out._m[i][j] - cur._m[i][j]) < 1e-9


def test_nlerp_rotation_stays_orthonormal():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.5)
    for i in range(3):
        c = out.GetCol(i)
        assert abs(math.sqrt(c.x * c.x + c.y * c.y + c.z * c.z) - 1.0) < 1e-6
    assert abs(_det(out) - 1.0) < 1e-6


def test_nlerp_rotation_midpoint_is_between():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 0.5)
    r = out.GetCol(0)
    ang = math.degrees(math.atan2(r.z, r.x))  # MakeYRotation: col0 = (c,0,-s)
    assert -40.0 < ang < 0.0


def test_lerp_transform_blends_both():
    pl = TGPoint3(0.0, 0.0, 0.0)
    cl = TGPoint3(4.0, 0.0, 0.0)
    pr = TGMatrix3(); pr.MakeYRotation(0.0)
    cr = TGMatrix3(); cr.MakeYRotation(math.radians(30.0))
    loc, rot = lerp_transform(pl, pr, cl, cr, 0.5)
    assert (loc.x, loc.y, loc.z) == (2.0, 0.0, 0.0)
    assert abs(_det(rot) - 1.0) < 1e-6
