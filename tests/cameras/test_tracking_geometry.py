"""Unit tests for _TrackingCamera — two-angle solver for the
tactical-mode target camera. See:
    docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md
"""
import math
import pytest


def test_tracking_camera_has_default_screen_y_constants():
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    assert tc.y_p == pytest.approx(-0.25)
    assert tc.y_t == pytest.approx(+0.25)


def test_tracking_camera_converts_screen_y_to_angle():
    """y → α via α = atan(y × tan(v_fov / 2)). For y = 0.25 and the
    default 60° v_fov, α ≈ atan(0.25 × tan(30°)) ≈ 8.213°."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.cameras           import EXTERIOR_FOV_Y_RAD

    tc = _TrackingCamera()
    alpha = tc._screen_y_to_angle(0.25)
    expected = math.atan(0.25 * math.tan(EXTERIOR_FOV_Y_RAD / 2))
    assert alpha == pytest.approx(expected, abs=1e-9)


def test_tracking_camera_screen_y_zero_gives_zero_angle():
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    assert tc._screen_y_to_angle(0.0) == pytest.approx(0.0)


def _ship(loc_xyz=(0.0, 0.0, 0.0), rot=None):
    from engine.appc.math import TGPoint3, TGMatrix3
    loc = TGPoint3(*loc_xyz)
    return loc, rot if rot is not None else TGMatrix3()


def _project_to_screen_y(point, eye, forward, up):
    """Forward and up are unit 3-tuples. Returns screen-Y fraction:
        y = ((P - E) · u) / ((P - E) · f) × cot(v_fov/2)
    For matching, divide by tan(v_fov/2) to land in [-1, +1]."""
    px, py, pz = point
    ex, ey, ez = eye
    dx, dy, dz = px - ex, py - ey, pz - ez
    fx, fy, fz = forward
    ux, uy, uz = up
    along_f = dx*fx + dy*fy + dz*fz
    along_u = dx*ux + dy*uy + dz*uz
    from engine.cameras import EXTERIOR_FOV_Y_RAD
    return (along_u / along_f) / math.tan(EXTERIOR_FOV_Y_RAD / 2)


def test_solver_places_player_at_minus_quarter_screen_y():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera()
    tc.d_chase = 10.0

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))  # identity rot → body-up = +z
    t_loc, _     = _ship((0.0, 20.0, 0.0))  # 20 GU along +y (ship-forward)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]
    fy = look_at[1] - eye[1]
    fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
    assert y_p == pytest.approx(-0.25, abs=1e-3)


def test_solver_places_target_at_plus_quarter_screen_y():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera()
    tc.d_chase = 10.0

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))
    t_loc, _     = _ship((0.0, 20.0, 0.0))

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_t = _project_to_screen_y((0.0, 20.0, 0.0), eye, forward, up)
    assert y_t == pytest.approx(+0.25, abs=1e-3)


def test_solver_framing_is_invariant_across_range():
    """Player & target screen-Y must be ≈ ±0.25 whether target is 5,
    50, or 500 GU away. This is the regression the rewrite exists to
    fix."""
    from engine.cameras.tracking import _TrackingCamera

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))
    for d in (5.0, 50.0, 500.0):
        tc = _TrackingCamera()
        tc.d_chase = 10.0
        t_loc, _ = _ship((0.0, d, 0.0))

        eye, look_at, up = tc.compute(
            player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

        fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        forward = (fx/flen, fy/flen, fz/flen)

        y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
        y_t = _project_to_screen_y((0.0,  d,  0.0), eye, forward, up)
        assert y_p == pytest.approx(-0.25, abs=1e-3), f"range {d}: y_p={y_p}"
        assert y_t == pytest.approx(+0.25, abs=1e-3), f"range {d}: y_t={y_t}"


class _FakeShip:
    """Minimal player/target stub: just the world transform getters."""
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
