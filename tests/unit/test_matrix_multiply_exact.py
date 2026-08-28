"""TGMatrix3.MultMatrix must be BIT-EXACT with the loop form it replaced.

The unrolled version is a performance change on the ship-motion hot path, and
this project's bar is behavioural exactness — so "close enough" is not the
test. Float addition is not associative, so an unrolled expression is only
identical if it preserves the accumulation order (k ascending) of the original
triple loop. The one divergence the analysis admits is a signed zero, which is
exactly the sort of thing that is easier to test than to be sure about.

Reference below is the ORIGINAL implementation, verbatim.
"""
import math
import random
import struct

from engine.appc.math import TGMatrix3, TGPoint3


def _reference_mult(lhs, rhs):
    """The pre-unroll implementation, character for character."""
    result = TGMatrix3()
    result.MakeZero()
    for i in range(3):
        for j in range(3):
            for k in range(3):
                result._m[i][j] += lhs._m[i][k] * rhs._m[k][j]
    return result


def _bits(x: float) -> bytes:
    """Raw IEEE-754 bits, so +0.0 and -0.0 compare UNEQUAL.

    `==` would call them equal and let a signed-zero divergence through, which
    is the single difference this test exists to catch.
    """
    return struct.pack("<d", x)


def _assert_identical(a, b, label):
    for i in range(3):
        for j in range(3):
            assert _bits(a._m[i][j]) == _bits(b._m[i][j]), (
                "%s: element [%d][%d] differs: %r vs %r"
                % (label, i, j, a._m[i][j], b._m[i][j]))


def _from_rows(rows):
    m = TGMatrix3()
    m._m = [list(r) for r in rows]
    return m


def test_identity_pair():
    a, b = TGMatrix3(), TGMatrix3()
    _assert_identical(a.MultMatrix(b), _reference_mult(a, b), "identity")


def test_zero_pair():
    """All-zero products are where a signed zero would surface."""
    a, b = TGMatrix3().MakeZero(), TGMatrix3().MakeZero()
    _assert_identical(a.MultMatrix(b), _reference_mult(a, b), "zero")


def test_negative_zero_elements():
    neg = _from_rows([[-0.0, -0.0, -0.0]] * 3)
    pos = _from_rows([[0.0, 0.0, 0.0]] * 3)
    for label, (x, y) in {
        "neg*neg": (neg, neg),
        "neg*pos": (neg, pos),
        "pos*neg": (pos, neg),
    }.items():
        _assert_identical(x.MultMatrix(y), _reference_mult(x, y), label)


def test_zero_angle_rotations():
    """_integrate_rotation composes an axis whose angular velocity is zero
    whenever a ship turns about only one or two axes — the common case."""
    axes = (TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 1.0, 0.0),
            TGPoint3(0.0, 0.0, 1.0))
    for axis in axes:
        a = TGMatrix3(); a.MakeRotation(0.0, axis)
        b = TGMatrix3(); b.MakeRotation(0.0, axis)
        _assert_identical(a.MultMatrix(b), _reference_mult(a, b),
                          "zero-angle %r" % ((axis.x, axis.y, axis.z),))


def test_real_rotation_compositions():
    """The exact shape _integrate_rotation builds: pitch . yaw . roll."""
    rng = random.Random(20260824)
    X = TGPoint3(1.0, 0.0, 0.0)
    Y = TGPoint3(0.0, 1.0, 0.0)
    Z = TGPoint3(0.0, 0.0, 1.0)
    for _ in range(200):
        p = TGMatrix3(); p.MakeRotation(rng.uniform(-math.pi, math.pi), X)
        y = TGMatrix3(); y.MakeRotation(rng.uniform(-math.pi, math.pi), Z)
        r = TGMatrix3(); r.MakeRotation(rng.uniform(-math.pi, math.pi), Y)
        _assert_identical(p.MultMatrix(y), _reference_mult(p, y), "pitch.yaw")
        step = p.MultMatrix(y)
        _assert_identical(step.MultMatrix(r), _reference_mult(step, r),
                          "(pitch.yaw).roll")


def test_random_dense_matrices():
    rng = random.Random(11)
    for _ in range(500):
        a = _from_rows([[rng.uniform(-1e6, 1e6) for _ in range(3)]
                        for _ in range(3)])
        b = _from_rows([[rng.uniform(-1e6, 1e6) for _ in range(3)]
                        for _ in range(3)])
        _assert_identical(a.MultMatrix(b), _reference_mult(a, b), "random")


def test_extreme_magnitudes():
    """Mixed huge/tiny terms are where a reordered sum would diverge most."""
    a = _from_rows([[1e300, 1e-300, -1e300],
                    [1e-300, 1e300, 1e-300],
                    [-1e300, 1e-300, 1e300]])
    b = _from_rows([[1e-300, 1e300, 1e-300],
                    [1e300, 1e-300, 1e300],
                    [1e-300, 1e300, 1e-300]])
    _assert_identical(a.MultMatrix(b), _reference_mult(a, b), "extremes")


def test_result_is_a_fresh_matrix():
    """MultMatrix must not alias either operand — callers chain it."""
    a, b = TGMatrix3(), TGMatrix3()
    out = a.MultMatrix(b)
    out._m[0][0] = 99.0
    assert a._m[0][0] == 1.0
    assert b._m[0][0] == 1.0
