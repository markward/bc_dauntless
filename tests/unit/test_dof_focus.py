"""Focus control for depth of field.

The solver is deliberately pure Python with no GL dependency: every rule that
decides WHAT is in focus and how the lens gets there is testable headlessly.
"""
import math

import pytest

from engine.cameras import dof


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Obj:
    def __init__(self, x, y, z):
        self._p = _Pt(x, y, z)

    def GetWorldLocation(self):
        return self._p


class _Player:
    def __init__(self, target=None):
        self._t = target

    def GetTarget(self):
        return self._t


class _ModeWithSubject:
    def __init__(self, subject):
        self._s = subject

    def focus_subject(self):
        return self._s


# ── subject selection ────────────────────────────────────────────────────

def test_no_player_and_no_mode_means_no_subject():
    assert dof.focus_subject(None, None) is None


def test_falls_back_to_the_players_target():
    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), None) is tgt


def test_camera_mode_subject_beats_the_players_target():
    tgt, torp = _Obj(0, 0, 0), _Obj(1, 1, 1)
    assert dof.focus_subject(_Player(tgt), _ModeWithSubject(torp)) is torp


def test_camera_mode_with_no_subject_falls_through_to_the_target():
    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), _ModeWithSubject(None)) is tgt


def test_camera_mode_without_the_hook_is_tolerated():
    """Most camera modes will never grow a focus_subject(); their absence must
    fall through rather than raise."""
    class _Bare:
        pass

    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), _Bare()) is tgt


def test_no_target_means_no_subject():
    assert dof.focus_subject(_Player(None), None) is None


# ── distance ─────────────────────────────────────────────────────────────

def test_subject_distance_is_euclidean_in_game_units():
    d = dof.subject_distance_gu((0.0, 0.0, 0.0), _Obj(3.0, 4.0, 0.0))
    assert d == pytest.approx(5.0)


def test_subject_distance_of_nothing_is_none():
    assert dof.subject_distance_gu((0.0, 0.0, 0.0), None) is None


# ── the solver ───────────────────────────────────────────────────────────

def test_starts_disengaged():
    s = dof.FocusSolver()
    assert s.blend == 0.0
    assert s.focus_gu == 0.0


def test_first_acquisition_snaps_the_distance_but_ramps_the_blend():
    """A rack from nowhere would swing the lens wildly the moment a target is
    selected. The distance snaps; only the engage ramp is eased."""
    s = dof.FocusSolver()
    s.update(120.0, 1.0 / 60.0)
    assert s.focus_gu == pytest.approx(120.0)
    assert 0.0 < s.blend < 1.0


def test_blend_ramps_to_one_while_a_subject_is_held():
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    assert s.blend == pytest.approx(1.0, abs=1e-3)


def test_rack_eases_in_dioptres_not_distance():
    """A real focus pull moves the barrel in 1/distance. Easing linear
    distance would make a rack from 20 GU to 400 GU take visibly longer than
    the reverse; in dioptres the two are symmetric."""
    dt, tau = 0.05, dof.RACK_TAU_S

    out = dof.FocusSolver()
    out.update(20.0, dt)          # snap to 20
    out.update(400.0, dt)         # one eased step outward

    back = dof.FocusSolver()
    back.update(400.0, dt)        # snap to 400
    back.update(20.0, dt)         # one eased step inward

    a = 1.0 - math.exp(-dt / tau)
    expect_out  = 1.0 / (1.0 / 20.0 + (1.0 / 400.0 - 1.0 / 20.0) * a)
    expect_back = 1.0 / (1.0 / 400.0 + (1.0 / 20.0 - 1.0 / 400.0) * a)

    assert out.focus_gu == pytest.approx(expect_out, rel=1e-6)
    assert back.focus_gu == pytest.approx(expect_back, rel=1e-6)


def test_losing_the_subject_ramps_blend_down_not_snaps():
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    s.update(None, 1.0 / 60.0)
    assert 0.0 < s.blend < 1.0


def test_blend_reaches_exactly_zero_so_the_pass_can_be_skipped():
    """The host skips the pass on blend <= 0. An asymptote that never quite
    reaches zero would leave it running forever at an invisible strength."""
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    for _ in range(600):
        s.update(None, 1.0 / 60.0)
    assert s.blend == 0.0
    assert s.focus_gu == 0.0


def test_a_degenerate_distance_is_treated_as_no_subject():
    s = dof.FocusSolver()
    s.update(0.0, 1.0 / 60.0)
    assert s.blend == 0.0
    s.update(-5.0, 1.0 / 60.0)
    assert s.blend == 0.0


def test_a_subject_beyond_the_far_plane_is_treated_as_no_subject():
    """focus_gu > far mushes the WHOLE frame. dd = 1 - focus/z is negative for
    every visible pixel, so everything is near field and everything nearer than
    focus/2 clamps to the hard -1 -- maximum blur, with the far ceiling unable
    to help because nothing is far field. The lens must release to deep focus
    rather than rack past infinity."""
    s = dof.FocusSolver()
    s.update(dof.MAX_FOCUS_GU + 1.0, 1.0 / 60.0)
    assert s.blend == 0.0
    assert s.focus_gu == 0.0


def test_the_far_bound_is_reachable_from_a_real_sensor_fallback_range():
    """Not a theoretical edge: sensor_detection.FALLBACK_RANGE_GU is 30000 GU,
    six times the exterior camera's far plane, and a lock is only dropped when
    can_detect fails."""
    from engine.appc import sensor_detection
    assert sensor_detection.FALLBACK_RANGE_GU > dof.MAX_FOCUS_GU
    s = dof.FocusSolver()
    s.update(sensor_detection.FALLBACK_RANGE_GU, 1.0 / 60.0)
    assert s.blend == 0.0


def test_a_held_subject_racking_past_the_far_plane_releases_the_lens():
    """A target that warps out to beyond the far plane must ramp the blend down
    like any other loss, not hold a saturated frame."""
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    assert s.blend == pytest.approx(1.0, abs=1e-3)
    for _ in range(600):
        s.update(9000.0, 1.0 / 60.0)
    assert s.blend == 0.0


def test_the_far_bound_matches_the_exterior_cameras_far_plane():
    """MAX_FOCUS_GU is not a free parameter -- it IS the camera's far plane
    (host_loop's r.set_camera(..., far=5000.0)). If that changes, this must."""
    assert dof.MAX_FOCUS_GU == 5000.0


def test_solver_seeds_its_lens_values_from_the_module_defaults():
    s = dof.FocusSolver()
    assert s.near_strength == dof.NEAR_STRENGTH
    assert s.far_strength == dof.FAR_STRENGTH
    assert s.far_ceiling == dof.FAR_CEILING
    assert s.max_radius_frac == dof.MAX_RADIUS_FRAC


def test_nudge_moves_both_strengths_and_never_writes_back_to_the_module():
    s = dof.FocusSolver()
    before = dof.NEAR_STRENGTH
    near, far = s.nudge_strength(0.1)
    assert near == pytest.approx(before + 0.1)
    assert far == pytest.approx(dof.FAR_STRENGTH + 0.1)
    assert dof.NEAR_STRENGTH == before, "nudge must be per-session, not global"


def test_nudge_clamps_at_both_ends():
    s = dof.FocusSolver()
    for _ in range(100):
        s.nudge_strength(1.0)
    assert s.near_strength == dof.STRENGTH_MAX
    for _ in range(100):
        s.nudge_strength(-1.0)
    assert s.near_strength == dof.STRENGTH_MIN


def test_paused_frame_does_not_advance_engagement():
    """A paused frame (dt=0) freezes the engagement ramp, not snaps to full.
    With dt=0 there is no time for the exponential ease to move, so blend
    stays exactly where it was."""
    s = dof.FocusSolver()
    # Ramp blend partway with normal dt
    for _ in range(10):
        s.update(120.0, 1.0 / 60.0)
    blend_partway = s.blend
    assert 0.0 < blend_partway < 1.0
    # Paused frame does not advance blend
    s.update(120.0, 0.0)
    assert s.blend == pytest.approx(blend_partway)


def test_paused_frame_does_not_advance_the_rack():
    """A paused frame (dt=0) freezes the focus distance, not jumps to the new target.
    After acquiring one distance, changing target with dt=0 should leave focus_gu
    unchanged because no time has passed."""
    s = dof.FocusSolver()
    # Acquire and partially ramp to first distance
    s.update(120.0, 1.0 / 60.0)
    s.update(120.0, 1.0 / 60.0)
    focus_partway = s.focus_gu
    assert focus_partway == pytest.approx(120.0)
    # Paused frame with different target does not advance rack
    s.update(400.0, 0.0)
    assert s.focus_gu == pytest.approx(focus_partway)


def test_first_acquisition_snaps_at_zero_dt():
    """First acquisition snaps the distance even with dt=0, because the snap
    is a deliberate bypass of the easing function, not dependent on it."""
    s = dof.FocusSolver()
    s.update(120.0, 0.0)
    assert s.focus_gu == pytest.approx(120.0)
