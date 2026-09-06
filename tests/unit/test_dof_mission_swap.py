"""The depth-of-field lens must not survive a mission swap.

`_focus_solver` is constructed once at module scope and lives for the whole
process. `_drain_pending_swap` explicitly resets fourteen other module-level
states -- and nulls the cached camera eye, with a comment reasoning about
exactly this hazard -- but the lens was not among them.

Concretely: swap with a target held and blend == 1.0. If the new mission
selects a target on load (common in episode openers) `_inv_focus` is still
> 0, so FocusSolver.update() takes the EASE branch rather than the snap
branch, and the new mission's opening frames render at full blend focused at
the previous mission's distance.
"""
import pytest

from engine.cameras.dof import FocusSolver
from engine import host_loop


def _swap(controller_module=host_loop):
    """Drive the REAL _drain_pending_swap, not a re-run of its body, so
    deleting the reset line from the production block fails these tests."""
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    return h


@pytest.fixture(autouse=True)
def _fresh_solver(monkeypatch):
    """Own the module-level solver outright; never leak a racked lens."""
    monkeypatch.setattr(host_loop, "_focus_solver", FocusSolver())


def _rack_fully(solver, distance_gu=120.0):
    for _ in range(240):
        solver.update(distance_gu, 1.0 / 60.0)


# ── the reset itself ─────────────────────────────────────────────────────

def test_mission_swap_releases_a_fully_racked_lens():
    solver = host_loop._focus_solver
    _rack_fully(solver)
    assert solver.blend == pytest.approx(1.0, abs=1e-3)
    assert solver.focus_gu == pytest.approx(120.0)

    _swap()

    assert solver.blend == 0.0
    assert solver.focus_gu == 0.0


def test_the_next_mission_snaps_to_its_own_distance_not_the_previous_one():
    """The bug's actual symptom: without the reset the first acquisition in the
    new mission eases from the old dioptre instead of snapping, so frame one is
    focused hundreds of GU away from what it is looking at."""
    solver = host_loop._focus_solver
    _rack_fully(solver, 120.0)

    _swap()

    solver.update(900.0, 1.0 / 60.0)          # new mission's opener
    assert solver.focus_gu == pytest.approx(900.0)


# ── what must NOT be reset ───────────────────────────────────────────────

def test_mission_swap_preserves_the_nudged_lens_strengths():
    """Those are per-session dev tuning the user just dialled in live, not
    mission state. Wiping them mid-session would silently undo a calibration
    round -- the exact opposite of what the live-tuning keys are for."""
    solver = host_loop._focus_solver
    solver.nudge_strength(0.5)
    solver.nudge_max_radius_frac(0.004)
    solver.nudge_far_ceiling(0.15)
    tuned = (solver.near_strength, solver.far_strength,
             solver.max_radius_frac, solver.far_ceiling)

    _swap()

    assert (solver.near_strength, solver.far_strength,
            solver.max_radius_frac, solver.far_ceiling) == tuned


def test_reset_focus_is_not_a_fresh_solver():
    """Guard against 'fixing' this by reassigning _focus_solver = FocusSolver(),
    which would drop the tuning AND orphan the dev keys' lazily-resolved
    reference."""
    s = FocusSolver()
    s.nudge_far_ceiling(0.2)
    tuned = s.far_ceiling
    s.update(120.0, 1.0 / 60.0)
    s.reset_focus()
    assert s.far_ceiling == tuned
    assert s.blend == 0.0
