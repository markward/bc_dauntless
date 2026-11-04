"""The native render interpolation math is a twin of the Python oracle (phase 3c).

`dauntless::lerp_pose` must match `engine.core.interpolate.lerp_transform` and
`dauntless::HandoverBlend` must match `engine.core.handover_smoother`'s
`HandoverSmoother` element for element (|native - python| <= 1e-12), on random
poses and on every degenerate input `tests/unit/test_interpolate.py` pins.
"""
import math
import random

import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.core.handover_smoother import HandoverSmoother  # noqa: E402
from engine.core.interpolate import lerp_transform  # noqa: E402

_TOL = 1e-12


def _random_rotation(rng: random.Random) -> TGMatrix3:
    axis = TGPoint3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    n = math.sqrt(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z)
    axis = TGPoint3(axis.x / n, axis.y / n, axis.z / n)
    return TGMatrix3().MakeRotation(rng.uniform(-math.pi, math.pi), axis)


def _random_point(rng: random.Random) -> TGPoint3:
    return TGPoint3(rng.uniform(-1000, 1000), rng.uniform(-1000, 1000),
                    rng.uniform(-1000, 1000))


def _xyz(p: TGPoint3):
    return [p.x, p.y, p.z]


def _assert_twin(native, loc: TGPoint3, rot: TGMatrix3):
    n_pos, n_rot = native
    for got, want in zip(list(n_pos) + list(n_rot), _xyz(loc) + list(rot.as_tuple())):
        assert abs(got - want) <= _TOL, (list(n_pos), list(n_rot),
                                          _xyz(loc), rot.as_tuple())


def _check_lerp(pl, pr, cl, cr, alpha):
    loc, rot = lerp_transform(pl, pr, cl, cr, alpha)
    native = _h._test_only_interp_lerp(
        _xyz(pl), list(pr.as_tuple()), _xyz(cl), list(cr.as_tuple()), alpha)
    _assert_twin(native, loc, rot)


def _zero_mat() -> TGMatrix3:
    return TGMatrix3().MakeZero()


def test_twin_matches_interpolate_on_random_poses():
    rng = random.Random(20261104)
    for _ in range(2000):
        _check_lerp(_random_point(rng), _random_rotation(rng),
                    _random_point(rng), _random_rotation(rng),
                    rng.uniform(0.0, 1.0))


def test_twin_matches_every_degenerate_case():
    origin = TGPoint3(0.0, 0.0, 0.0)
    z = _zero_mat()
    ident = TGMatrix3()
    zero_up = TGMatrix3()
    zero_up.SetCol(2, TGPoint3(0.0, 0.0, 0.0))
    # test_interpolate.py: zero matrix at alpha 0 and 0.5, zero -> identity at
    # alpha 0 (endpoint fallback), and a zeroed up column only.
    _check_lerp(origin, z, origin, z, 0.0)
    _check_lerp(origin, z, origin, z, 0.5)
    _check_lerp(origin, z, origin, ident, 0.0)
    _check_lerp(origin, zero_up, origin, zero_up, 0.0)


@pytest.mark.parametrize("elapsed", (0.0, 0.09, 0.18, 0.36, 0.5))
def test_handover_twin_matches_the_python_smoother(elapsed):
    rng = random.Random(20261104)
    for _ in range(200):
        fl, fr = _random_point(rng), _random_rotation(rng)
        tl, tr = _random_point(rng), _random_rotation(rng)
        s = HandoverSmoother()
        s.begin(fl, fr)
        s.advance(elapsed)
        loc, rot = s.blend(tl, tr)
        native = _h._test_only_handover_blend(
            _xyz(fl), list(fr.as_tuple()), _xyz(tl), list(tr.as_tuple()),
            elapsed)
        _assert_twin(native, loc, rot)
