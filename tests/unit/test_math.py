"""Unit tests for TGPoint3 and TGMatrix3."""
import math
import pytest
import App
from engine.appc.math import (
    TGPoint3, TGMatrix3,
    TGPoint3_GetModelForward, TGPoint3_GetModelBackward,
    TGPoint3_GetModelUp, TGPoint3_GetModelDown,
    TGPoint3_GetModelRight, TGPoint3_GetModelLeft,
)


# ── TGPoint3 ───────────────────────────────────────────────────────────────────

def test_tgpoint3_default_zero():
    v = TGPoint3()
    assert v.x == 0.0 and v.y == 0.0 and v.z == 0.0


def test_tgpoint3_constructor_xyz():
    v = TGPoint3(1.0, 2.0, 3.0)
    assert v.x == 1.0 and v.y == 2.0 and v.z == 3.0


def test_tgpoint3_set_xyz():
    v = TGPoint3()
    v.SetXYZ(4.0, 5.0, 6.0)
    assert v.x == 4.0 and v.y == 5.0 and v.z == 6.0


def test_tgpoint3_set_components():
    v = TGPoint3()
    v.SetX(1.0); v.SetY(2.0); v.SetZ(3.0)
    assert v.GetX() == 1.0 and v.GetY() == 2.0 and v.GetZ() == 3.0


def test_tgpoint3_length():
    v = TGPoint3(3.0, 4.0, 0.0)
    assert abs(v.Length() - 5.0) < 1e-10


def test_tgpoint3_sqr_length():
    v = TGPoint3(1.0, 2.0, 2.0)
    assert abs(v.SqrLength() - 9.0) < 1e-10


def test_tgpoint3_dot():
    a = TGPoint3(1.0, 0.0, 0.0)
    b = TGPoint3(0.0, 1.0, 0.0)
    assert a.Dot(b) == 0.0


def test_tgpoint3_dot_parallel():
    a = TGPoint3(2.0, 3.0, 4.0)
    assert abs(a.Dot(a) - a.SqrLength()) < 1e-10


def test_tgpoint3_cross():
    x = TGPoint3(1.0, 0.0, 0.0)
    y = TGPoint3(0.0, 1.0, 0.0)
    z = x.Cross(y)
    assert abs(z.x) < 1e-10 and abs(z.y) < 1e-10 and abs(z.z - 1.0) < 1e-10


def test_tgpoint3_unitize():
    v = TGPoint3(3.0, 4.0, 0.0)
    v.Unitize()
    assert abs(v.Length() - 1.0) < 1e-10


def test_unitize_returns_pre_normalization_length():
    """SDK contract (NiPoint3.Unitize): returns the length before
    normalization as a float. SDK call sites rely on this:
        fDistance = vDiff.Unitize()  # vDiff is now unit-length; we know
                                     # how far it was."""
    v = TGPoint3(3.0, 4.0, 0.0)
    length = v.Unitize()
    assert length == pytest.approx(5.0)
    # And the vector is normalized in place.
    assert v.x == pytest.approx(0.6)
    assert v.y == pytest.approx(0.8)
    assert v.z == pytest.approx(0.0)


def test_unitize_zero_vector_returns_zero():
    """Edge case: unitizing a zero vector leaves it as zero and
    returns 0 (avoid divide-by-zero)."""
    v = TGPoint3(0.0, 0.0, 0.0)
    length = v.Unitize()
    assert length == 0.0
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_tgpoint3_unit_cross_is_normalized():
    a = TGPoint3(1.0, 0.0, 0.0)
    b = TGPoint3(0.0, 1.0, 0.0)
    c = a.UnitCross(b)
    assert abs(c.Length() - 1.0) < 1e-10


def test_tgpoint3_add():
    a = TGPoint3(1.0, 2.0, 3.0)
    b = TGPoint3(4.0, 5.0, 6.0)
    c = a + b
    assert c.x == 5.0 and c.y == 7.0 and c.z == 9.0


def test_tgpoint3_sub():
    a = TGPoint3(4.0, 5.0, 6.0)
    b = TGPoint3(1.0, 2.0, 3.0)
    c = a - b
    assert c.x == 3.0 and c.y == 3.0 and c.z == 3.0


def test_tgpoint3_mul_scalar():
    v = TGPoint3(1.0, 2.0, 3.0)
    w = v * 2.0
    assert w.x == 2.0 and w.y == 4.0 and w.z == 6.0


def test_tgpoint3_rmul_scalar():
    v = TGPoint3(1.0, 2.0, 3.0)
    w = 3.0 * v
    assert w.x == 3.0 and w.y == 6.0 and w.z == 9.0


def test_tgpoint3_neg():
    v = TGPoint3(1.0, -2.0, 3.0)
    w = -v
    assert w.x == -1.0 and w.y == 2.0 and w.z == -3.0


def test_tgpoint3_equality():
    assert TGPoint3(1.0, 2.0, 3.0) == TGPoint3(1.0, 2.0, 3.0)
    assert TGPoint3(1.0, 2.0, 3.0) != TGPoint3(1.0, 2.0, 4.0)


# ── TGMatrix3 ──────────────────────────────────────────────────────────────────

def test_tgmatrix3_default_identity():
    m = TGMatrix3()
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            assert m.GetEntry(i, j) == expected


def test_tgmatrix3_make_zero():
    m = TGMatrix3()
    m.MakeZero()
    for i in range(3):
        for j in range(3):
            assert m.GetEntry(i, j) == 0.0


def test_tgmatrix3_get_set_row():
    m = TGMatrix3()
    m.SetRow(0, TGPoint3(1.0, 2.0, 3.0))
    r = m.GetRow(0)
    assert r.x == 1.0 and r.y == 2.0 and r.z == 3.0


def test_tgmatrix3_get_set_col():
    m = TGMatrix3()
    m.SetCol(1, TGPoint3(7.0, 8.0, 9.0))
    c = m.GetCol(1)
    assert c.x == 7.0 and c.y == 8.0 and c.z == 9.0


def test_tgmatrix3_get_set_entry():
    m = TGMatrix3()
    m.SetEntry(1, 2, 5.0)
    assert m.GetEntry(1, 2) == 5.0


def test_tgmatrix3_transpose_inverts_itself():
    m = TGMatrix3()
    m.MakeZRotation(0.7)
    assert m.Transpose().Transpose() == m


def test_tgmatrix3_identity_mult():
    m = TGMatrix3()
    m.MakeZRotation(1.0)
    identity = TGMatrix3()
    result = identity.MultMatrix(m)
    assert result == m


def test_tgmatrix3_mult_transpose_is_identity_for_rotation():
    m = TGMatrix3()
    m.MakeYRotation(0.5)
    product = m.MultMatrix(m.Transpose())
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            assert abs(product.GetEntry(i, j) - expected) < 1e-10


def test_tgmatrix3_make_x_rotation():
    m = TGMatrix3()
    m.MakeXRotation(math.pi / 2)
    # rotating Y axis by 90° around X should give Z axis
    y = TGPoint3(0.0, 1.0, 0.0)
    result = m.MultPoint(y)
    assert abs(result.x) < 1e-10
    assert abs(result.y) < 1e-10
    assert abs(result.z - 1.0) < 1e-10


def test_tgmatrix3_make_z_rotation():
    m = TGMatrix3()
    m.MakeZRotation(math.pi / 2)
    # rotating X axis by 90° around Z should give Y axis
    x = TGPoint3(1.0, 0.0, 0.0)
    result = m.MultPoint(x)
    assert abs(result.x) < 1e-10
    assert abs(result.y - 1.0) < 1e-10
    assert abs(result.z) < 1e-10


def test_tgmatrix3_make_rotation_axis_angle():
    axis = TGPoint3(0.0, 0.0, 1.0)
    m = TGMatrix3()
    m.MakeRotation(math.pi / 2, axis)
    x = TGPoint3(1.0, 0.0, 0.0)
    result = m.MultPoint(x)
    assert abs(result.x) < 1e-10
    assert abs(result.y - 1.0) < 1e-10


def test_tgmatrix3_mult_point():
    m = TGMatrix3()  # identity
    v = TGPoint3(1.0, 2.0, 3.0)
    assert m.MultPoint(v) == v


def test_tgmatrix3_set_nine_entries():
    m = TGMatrix3()
    m.Set(1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert m.GetEntry(0, 0) == 1.0
    assert m.GetEntry(1, 1) == 5.0
    assert m.GetEntry(2, 2) == 9.0


# ── App-level exposure ─────────────────────────────────────────────────────────

def test_app_tgpoint3_accessible():
    v = App.TGPoint3(1.0, 2.0, 3.0)
    assert isinstance(v, TGPoint3)


def test_app_tgmatrix3_accessible():
    m = App.TGMatrix3()
    assert isinstance(m, TGMatrix3)


def test_app_model_direction_vectors():
    fwd = App.TGPoint3_GetModelForward()
    assert isinstance(fwd, TGPoint3)
    assert abs(fwd.Length() - 1.0) < 1e-10


def test_app_model_directions_are_unit_and_distinct():
    dirs = [
        App.TGPoint3_GetModelForward(),
        App.TGPoint3_GetModelBackward(),
        App.TGPoint3_GetModelUp(),
        App.TGPoint3_GetModelDown(),
        App.TGPoint3_GetModelRight(),
        App.TGPoint3_GetModelLeft(),
    ]
    for d in dirs:
        assert abs(d.Length() - 1.0) < 1e-10
    # Opposite pairs sum to zero
    assert (dirs[0] + dirs[1]) == TGPoint3(0.0, 0.0, 0.0)
    assert (dirs[2] + dirs[3]) == TGPoint3(0.0, 0.0, 0.0)
    assert (dirs[4] + dirs[5]) == TGPoint3(0.0, 0.0, 0.0)


# ── TGPoint3.MultMatrixLeft ────────────────────────────────────────────────────

def test_tgpoint3_mult_matrix_left_in_place():
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    # Identity → no change
    p.MultMatrixLeft(R)
    assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)


def test_tgpoint3_mult_matrix_left_matches_mult_point():
    """vec.MultMatrixLeft(R) must equal R.MultPoint(vec)."""
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    # Build a non-identity rotation: 90° about z so x→y, y→-x
    R.SetRow(0, TGPoint3(0.0, -1.0, 0.0))
    R.SetRow(1, TGPoint3(1.0,  0.0, 0.0))
    R.SetRow(2, TGPoint3(0.0,  0.0, 1.0))

    expected = R.MultPoint(p)
    p.MultMatrixLeft(R)
    assert abs(p.x - expected.x) < 1e-9
    assert abs(p.y - expected.y) < 1e-9
    assert abs(p.z - expected.z) < 1e-9


def test_tgpoint3_mult_matrix_left_returns_self_for_chaining_optional():
    """Either returns self or returns None; both are fine. Document choice."""
    p = TGPoint3(1.0, 2.0, 3.0)
    R = TGMatrix3()
    result = p.MultMatrixLeft(R)
    assert result is None or result is p


# ── TGPoint3.Subtract ──────────────────────────────────────────────────────────
# In-place vector subtract. Mirrors the existing TGPoint3.Add contract. Used by
# SDK scripts like AI/PlainAI/Intercept.py which compute relative vectors via
# `vec.Subtract(other)` 13+ times.

def test_tgpoint3_subtract_is_in_place():
    v = TGPoint3(10.0, 20.0, 30.0)
    result = v.Subtract(TGPoint3(1.0, 2.0, 3.0))
    assert result is None  # in-place, returns None
    assert (v.x, v.y, v.z) == (9.0, 18.0, 27.0)


def test_tgpoint3_subtract_negative_components():
    v = TGPoint3(0.0, 0.0, 0.0)
    v.Subtract(TGPoint3(-5.0, -5.0, -5.0))
    assert (v.x, v.y, v.z) == (5.0, 5.0, 5.0)


def test_tgpoint3_subtract_zero_is_identity():
    v = TGPoint3(7.0, 8.0, 9.0)
    v.Subtract(TGPoint3(0.0, 0.0, 0.0))
    assert (v.x, v.y, v.z) == (7.0, 8.0, 9.0)


def test_tgpoint3_subtract_self_zeroes():
    v = TGPoint3(3.0, 4.0, 5.0)
    other = TGPoint3(3.0, 4.0, 5.0)
    v.Subtract(other)
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)
