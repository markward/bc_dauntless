"""The whole-body convergence gate in _test_course_override.

The gate tests an obstacle's bounding sphere before expanding it into hull
pieces. It exists because proximity does not discriminate in a battle
(AVOID_MINIMUM_RADIUS_GU is 225 GU ~ 40 km, coarse next to the distances that
matter) while convergence does. Measured over 40,320 pair-samples at 64 ships:
47.7% pass the proximity query, 1.48% are actually on a collision course — a
~32x tighter predicate.

⚠️ Those figures are the CORRECTED ones. This docstring first said 100% / 0%,
measured on a scene where every ship had `GetRadius() == 0` (the headless
harness has no realize step, so `SetRadius` never ran) — which zeroes
`personal_space`, trips `_test_course_override`'s `ob_r <= 0.0` reject, and
asks the swept test whether dimensionless points collide. See
docs/engine/avoidance-duplication.md.

It is a SAFETY system, so the property under test is soundness, not speed: the
gate may only drop obstacles the per-piece scan would have ignored anyway.
"""
import pytest

from engine.appc import collision_avoidance as ca
from engine.appc import hull_bounds as hb
from engine.appc.math import TGPoint3


class _Ship:
    """Minimal stand-in with the surface bound_radius and the gate touch."""

    def __init__(self, pieces=None, radius=1.0, scale=1.0):
        self._radius = radius
        self._scale = scale
        if pieces is not None:
            self.__dict__[hb._ATTR] = pieces

    def GetRadius(self):
        return self._radius

    def GetScale(self):
        return self._scale


# ── bound_radius: the value the gate's soundness rests on ────────────────────

def test_bound_radius_is_zero_without_pieces():
    assert hb.bound_radius(_Ship()) == 0.0


def test_bound_radius_encloses_every_piece():
    pieces = [((0.0, 0.0, 0.0), 1.0),
              ((10.0, 0.0, 0.0), 2.0),      # reaches 12
              ((0.0, -3.0, 4.0), 0.5)]      # reaches 5.5
    r = hb.bound_radius(_Ship(pieces))
    assert r == pytest.approx(12.0)
    for (cx, cy, cz), pr in pieces:
        assert (cx * cx + cy * cy + cz * cz) ** 0.5 + pr <= r + 1e-9


def test_bound_radius_tracks_live_scale():
    pieces = [((3.0, 4.0, 0.0), 1.0)]        # reaches 6
    assert hb.bound_radius(_Ship(pieces, scale=1.0)) == pytest.approx(6.0)
    assert hb.bound_radius(_Ship(pieces, scale=2.5)) == pytest.approx(15.0)


def test_bound_radius_memo_does_not_freeze_scale():
    """Memoised UNSCALED, so a rescale between calls must still be honoured."""
    ship = _Ship([((0.0, 0.0, 5.0), 1.0)], scale=1.0)
    assert hb.bound_radius(ship) == pytest.approx(6.0)
    ship._scale = 3.0
    assert hb.bound_radius(ship) == pytest.approx(18.0)


def test_bound_radius_exceeds_an_undersized_authored_radius():
    """The reason the gate cannot just use GetRadius().

    host_loop only derives the radius from the model AABB when the SDK left it
    at 0, so a hardpoint script's authored value can be smaller than the
    geometry — and a protruding piece outside it would be gated away.
    """
    ship = _Ship([((0.0, 40.0, 0.0), 2.0)], radius=5.0)
    assert ship.GetRadius() < hb.bound_radius(ship)


# ── the gate predicate itself ────────────────────────────────────────────────

def test_overlapping_bodies_are_never_gated_out():
    """_need_to_avoid's already-inside-personal-space clause returns True
    regardless of velocity. A body you are already touching must survive the
    gate even at zero closing speed — that is how you steer out of it."""
    at_rest = TGPoint3(0.0, 0.0, 0.0)
    assert ca._need_to_avoid(TGPoint3(0.0, 0.0, 0.0), at_rest, 10.0,
                             TGPoint3(3.0, 0.0, 0.0), at_rest, 1.0) is True


def test_a_head_on_pair_survives_the_gate():
    assert ca._need_to_avoid(TGPoint3(0.0, 0.0, 0.0), TGPoint3(10.0, 0.0, 0.0),
                             5.0,
                             TGPoint3(100.0, 0.0, 0.0), TGPoint3(-10.0, 0.0, 0.0),
                             5.0) is True


def test_a_distant_parallel_pair_is_gated_out():
    assert ca._need_to_avoid(TGPoint3(0.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 10.0),
                             5.0,
                             TGPoint3(1000.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 10.0),
                             5.0) is False


def test_a_bigger_radius_can_only_make_the_gate_more_permissive():
    """Monotonicity is what makes 'use the larger of the two radii' sound: a
    gate radius that is too LARGE costs work, one that is too small drops a
    real obstacle."""
    pa, va, ps = TGPoint3(0.0, 0.0, 0.0), TGPoint3(5.0, 0.0, 0.0), 2.0
    pb, vb = TGPoint3(60.0, 12.0, 0.0), TGPoint3(0.0, 0.0, 0.0)
    small = ca._need_to_avoid(pa, va, ps, pb, vb, 1.0)
    large = ca._need_to_avoid(pa, va, ps, pb, vb, 40.0)
    assert not (small and not large), "a larger radius rejected what a smaller accepted"
