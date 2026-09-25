"""ArticulatedPartProperty's pose surface (spec 2026-09-25 §3, §6)."""
import pytest

from engine.appc import articulated_part as ap
from engine.appc import part_pose as pp


def test_a_fresh_part_is_static_and_unbreakable():
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.anchor is None
    assert p.transition_seconds == 2.0
    assert p.break_fraction is None
    assert p.authored_states() == ()
    for s in ap.STATES:
        assert pp.is_identity(p.pose_for(s))
        assert p.pose6_for(s) is None


def test_state_pose_round_trips():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetAnchor(-0.16, 0.0, 0.05)
    p.SetStatePose("warp", 0.1, 0.0, 0.2, 0.0, 30.0, 0.0)
    assert p.anchor == (-0.16, 0.0, 0.05)
    assert p.pose6_for("warp") == pytest.approx((0.1, 0.0, 0.2, 0.0, 30.0, 0.0))
    assert p.authored_states() == ("warp",)


def test_an_unknown_state_is_rejected():
    p = ap.ArticulatedPartProperty_Create("left wing")
    with pytest.raises(ValueError):
        p.SetStatePose("REd", 0, 0, 0, 0, 0, 0)


def test_transition_seconds_and_break_fraction():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetTransitionSeconds(3.5)
    p.SetBreakFraction(0.25)
    assert p.transition_seconds == 3.5
    assert p.break_fraction == 0.25
    assert p.detach_fraction == 0.25, "the old reader aliases the new value"


def test_legacy_detach_fraction_sets_break_fraction():
    p = ap.ArticulatedPartProperty_Create("head")
    p.SetDetachFraction(0.3)
    assert p.break_fraction == 0.3


def test_legacy_hinge_converts_to_anchor_and_poses():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetPivot(-0.16, 0.0, 0.05)
    p.SetAxis(0.0, 1.0, 0.0)
    p.SetStateAngle("cruise", 45.0)
    p.SetStateAngle("red", 0.0)
    assert p.anchor == (-0.16, 0.0, 0.05)
    x = (-1.0, 0.45, -0.67)
    want = pp.apply(pp.hinge_pose((-0.16, 0.0, 0.05), (0.0, 1.0, 0.0), 45.0), x)
    assert pp.apply(p.pose_for("cruise"), x) == pytest.approx(want)
    assert pp.is_identity(p.pose_for("red"))
    assert set(p.authored_states()) == {"cruise", "red"}


def test_legacy_hinge_without_a_pivot_anchors_at_the_origin():
    """Spec §10: matches today's default pivot."""
    p = ap.ArticulatedPartProperty_Create("fin")
    p.SetStateAngle("cruise", 10.0)
    assert p.anchor == (0.0, 0.0, 0.0)


def test_an_explicit_pose_wins_over_a_legacy_angle():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("warp", 45.0)
    p.SetStatePose("warp", 0, 0, 0, 0, 0, 0)
    assert pp.is_identity(p.pose_for("warp"))
