"""Unit tests for _TrackingCamera position + rotation springs."""
import math
import pytest


class _FakeShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def _identity_setup():
    from engine.appc.math import TGPoint3, TGMatrix3
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)
    return _FakeShip(s_loc, s_rot), _FakeShip(t_loc, s_rot)


def test_first_call_with_dt_seeds_springs_to_solver_output():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera(); tc.d_chase = 10.0
    player, target = _identity_setup()

    eye_seeded, _, up_seeded = tc.compute(player=player, target=target, dt=1.0/60)
    # With springs seeded on first call, output equals the solver
    # output exactly — no lag.
    eye_solver, _, up_solver = tc.compute(player=player, target=target, dt=None)
    for got, want in zip(eye_seeded, eye_solver):
        assert got == pytest.approx(want, abs=1e-9)
    for got, want in zip(up_seeded, up_solver):
        assert got == pytest.approx(want, abs=1e-9)


def test_position_spring_lags_after_target_jump_then_converges():
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0

    # Seed at one target position.
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc_a = TGPoint3(0.0, 20.0, 0.0)
    t_loc_b = TGPoint3(0.0, 200.0, 0.0)   # far jump

    player   = _FakeShip(s_loc, s_rot)
    target_a = _FakeShip(t_loc_a, s_rot)
    target_b = _FakeShip(t_loc_b, s_rot)

    # Seed.
    tc.compute(player=player, target=target_a, dt=1.0/60)
    # Jump the target. One frame after the jump, eye should still be
    # close to its old position (within 90% of pre-jump value, since
    # one frame at τ=0.25 gives α ≈ 1 − exp(−1/15) ≈ 0.0645).
    eye_pre, _, _ = tc.compute(player=player, target=target_a, dt=None)
    eye_one_frame, _, _ = tc.compute(player=player, target=target_b, dt=1.0/60)
    # Solver output for target_b directly:
    fresh = _TrackingCamera(); fresh.d_chase = 10.0
    eye_solver_b, _, _ = fresh.compute(player=player, target=target_b, dt=None)

    # Lag check: smoothed eye much closer to pre-jump than to solver_b.
    def _dist(a, b): return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
    assert _dist(eye_one_frame, eye_pre)      < 0.2 * _dist(eye_pre, eye_solver_b)

    # Convergence: after ~70 frames at dt=1/60 with τ=0.25, spring is
    # within 1% of target.  (exp(-70/15) ≈ 0.009, i.e. < 1%.)
    for _ in range(70):
        tc.compute(player=player, target=target_b, dt=1.0/60)
    eye_settled, _, _ = tc.compute(player=player, target=target_b, dt=1.0/60)
    err = _dist(eye_settled, eye_solver_b)
    initial_err = _dist(eye_pre, eye_solver_b)
    assert err < 0.01 * initial_err


def test_snap_clears_spring_state():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera(); tc.d_chase = 10.0
    player, target = _identity_setup()
    for _ in range(5):
        tc.compute(player=player, target=target, dt=1.0/60)
    tc.snap()
    assert tc._smoothed_eye   is None
    assert tc._smoothed_basis is None


def test_set_ship_radius_updates_d_chase():
    from engine.cameras.tracking import _TrackingCamera
    from engine.cameras           import CAM_BACK_RADII, CAM_UP_RADII
    tc = _TrackingCamera()
    tc.set_ship_radius(2.0)
    expected = math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * 2.0
    assert tc.d_chase == pytest.approx(expected)
