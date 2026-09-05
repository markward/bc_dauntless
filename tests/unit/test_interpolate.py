"""Pure-function unit tests for render interpolation math."""

import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.interpolate import lerp_point, nlerp_rotation, lerp_transform


def _det(m: TGMatrix3) -> float:
    a = m.as_tuple()
    return (
        a[0] * (a[4] * a[8] - a[5] * a[7])
        - a[1] * (a[3] * a[8] - a[5] * a[6])
        + a[2] * (a[3] * a[7] - a[4] * a[6])
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
            assert out.GetEntry(i, j) == prev.GetEntry(i, j)


def test_nlerp_rotation_alpha_one_matches_cur():
    prev = TGMatrix3(); prev.MakeYRotation(0.0)
    cur = TGMatrix3(); cur.MakeYRotation(math.radians(40.0))
    out = nlerp_rotation(prev, cur, 1.0)
    for i in range(3):
        for j in range(3):
            assert abs(out.GetEntry(i, j) - cur.GetEntry(i, j)) < 1e-9


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


def _zero_mat() -> TGMatrix3:
    m = TGMatrix3()
    m.MakeZero()
    return m


def _is_orthonormal(m: TGMatrix3) -> bool:
    for i in range(3):
        c = m.GetCol(i)
        if abs(math.sqrt(c.x * c.x + c.y * c.y + c.z * c.z) - 1.0) > 1e-6:
            return False
    return abs(_det(m) - 1.0) < 1e-6


def test_nlerp_degenerate_zero_matrix_does_not_crash():
    # A freshly-spawned ship can carry a zero-column rotation; sampling it must
    # not ZeroDivisionError and must yield a proper orthonormal matrix.
    z = _zero_mat()
    out = nlerp_rotation(z, z, 0.0)
    assert _is_orthonormal(out)
    out2 = nlerp_rotation(z, z, 0.5)
    assert _is_orthonormal(out2)


def test_nlerp_degenerate_forward_falls_back_to_endpoint():
    ident = TGMatrix3()
    z = _zero_mat()
    # Blend a zero matrix toward identity — forward/up come from identity.
    out = nlerp_rotation(z, ident, 0.0)   # alpha 0 -> blended == zero (degenerate)
    assert _is_orthonormal(out)


def test_nlerp_zero_up_column_only():
    m = TGMatrix3()
    m.MakeIdentity()
    # Wipe the up column (col 2) to zero; forward (col 1) stays valid.
    m.SetCol(2, TGPoint3(0.0, 0.0, 0.0))
    out = nlerp_rotation(m, m, 0.0)
    assert _is_orthonormal(out)
