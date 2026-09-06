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


def test_zero_dt_does_not_divide_by_zero():
    s = dof.FocusSolver()
    s.update(120.0, 0.0)
    assert s.focus_gu == pytest.approx(120.0)
