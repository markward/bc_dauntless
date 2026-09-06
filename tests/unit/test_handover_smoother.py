"""HandoverSmoother: eases the player's drawn pose across a helm handover.

The player is rendered from two pose pipelines with a one-tick phase offset —
live (manual flight, integrated per render frame) and lerp(prev, cur, alpha)
(AI/scripted, integrated on the 60 Hz tick). Switching between them jumps by
up to one tick of motion. The smoother freezes the pose that was on screen and
blends from it to the true pose, so the transition is continuous.
"""
import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.handover_smoother import HandoverSmoother, SMOOTH_DURATION_S


def _pt(x, y, z):
    return TGPoint3(float(x), float(y), float(z))


def _identity():
    return TGMatrix3()


def _z_rot(angle):
    return TGMatrix3().MakeZRotation(angle)


def test_starts_inactive():
    s = HandoverSmoother()
    assert not s.active


def test_begin_makes_it_active():
    s = HandoverSmoother()
    s.begin(_pt(1, 2, 3), _identity())
    assert s.active


def test_first_blend_returns_the_frozen_pose_exactly():
    """At t=0 the drawn pose must equal what was already on screen — that is
    what removes the discontinuity. Any deviation here IS the snap."""
    s = HandoverSmoother()
    frozen_loc = _pt(10.0, 20.0, 30.0)
    s.begin(frozen_loc, _identity())
    loc, _rot = s.blend(_pt(99.0, 99.0, 99.0), _identity())
    assert (loc.x, loc.y, loc.z) == (10.0, 20.0, 30.0)


def test_blend_reaches_the_target_exactly_at_the_end():
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.advance(SMOOTH_DURATION_S)
    loc, _rot = s.blend(_pt(4.0, 8.0, 12.0), _identity())
    assert (loc.x, loc.y, loc.z) == (4.0, 8.0, 12.0)


def test_becomes_inactive_once_the_window_elapses():
    s = HandoverSmoother()
    s.begin(_pt(0, 0, 0), _identity())
    s.advance(SMOOTH_DURATION_S)
    assert not s.active


def test_overshooting_the_window_does_not_go_past_the_target():
    """A long frame (alt-tab, a hitch) must not extrapolate beyond the target."""
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.advance(SMOOTH_DURATION_S * 10.0)
    assert not s.active
    loc, _rot = s.blend(_pt(4.0, 0.0, 0.0), _identity())
    assert loc.x == 4.0


def test_blend_is_a_no_op_when_inactive():
    """An inactive smoother must return the live pose untouched, so the common
    path costs nothing and cannot perturb normal flight."""
    s = HandoverSmoother()
    target_loc = _pt(7.0, -3.0, 0.5)
    target_rot = _z_rot(0.4)
    loc, rot = s.blend(target_loc, target_rot)
    assert (loc.x, loc.y, loc.z) == (7.0, -3.0, 0.5)
    assert rot.as_tuple() == target_rot.as_tuple()


def test_midpoint_lies_between_frozen_and_target():
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.advance(SMOOTH_DURATION_S * 0.5)
    loc, _rot = s.blend(_pt(10.0, 0.0, 0.0), _identity())
    assert 0.0 < loc.x < 10.0


def test_progress_is_monotonic_toward_the_target():
    """The eased pose must never move backwards — a non-monotonic curve would
    read as a stutter, which is the thing we are removing."""
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    target = _pt(10.0, 0.0, 0.0)
    prev_x = -1.0
    for _ in range(12):
        loc, _rot = s.blend(target)  # target rot omitted -> identity default
        assert loc.x >= prev_x
        prev_x = loc.x
        s.advance(SMOOTH_DURATION_S / 10.0)


def test_uses_smoothstep_easing():
    """Matches LetterboxAnimator's t*t*(3-2t) — the house easing curve."""
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.advance(SMOOTH_DURATION_S * 0.25)
    loc, _rot = s.blend(_pt(1.0, 0.0, 0.0), _identity())
    t = 0.25
    assert math.isclose(loc.x, t * t * (3.0 - 2.0 * t), rel_tol=1e-9)


def test_rotation_is_blended_too():
    """The handover offset is a pose offset, not just a position offset: a
    turning ship snaps in heading as well."""
    s = HandoverSmoother()
    s.begin(_pt(0, 0, 0), _identity())
    target_rot = _z_rot(0.6)
    _loc, rot = s.blend(_pt(0, 0, 0), target_rot)
    assert rot.as_tuple() != target_rot.as_tuple()
    assert rot.as_tuple() == _identity().as_tuple()


def test_begin_while_active_restarts_from_the_new_pose():
    """Two handovers inside one window (a fast toggle) must re-freeze rather
    than blend from a stale pose."""
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.advance(SMOOTH_DURATION_S * 0.5)
    s.begin(_pt(5.0, 0.0, 0.0), _identity())
    loc, _rot = s.blend(_pt(9.0, 0.0, 0.0), _identity())
    assert loc.x == 5.0


def test_cancel_stops_smoothing_immediately():
    """A mission swap / scene discontinuity must drop the frozen pose rather
    than blend the player in from wherever it used to be."""
    s = HandoverSmoother()
    s.begin(_pt(0.0, 0.0, 0.0), _identity())
    s.cancel()
    assert not s.active
    loc, _rot = s.blend(_pt(4.0, 0.0, 0.0), _identity())
    assert loc.x == 4.0
