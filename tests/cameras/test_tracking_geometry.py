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
    tc.d_chase_tracking = 10.0

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
    tc.d_chase_tracking = 10.0

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
        tc.d_chase_tracking = 10.0
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


def test_solver_up_vector_lies_in_ship_target_body_up_plane():
    """The returned up vector must lie in the plane spanned by
    (T − S) and the ship body-up axis — equivalently, up must be a
    linear combination of e1 and e3."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    _, _, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # e1 is +y world, e3 is +z world for identity rotation. up should
    # have no x component.
    assert up[0] == pytest.approx(0.0, abs=1e-9)


def test_solver_camera_basis_is_orthonormal():
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    dot_fu = forward[0]*up[0] + forward[1]*up[1] + forward[2]*up[2]
    ulen   = math.sqrt(up[0]**2 + up[1]**2 + up[2]**2)
    assert dot_fu == pytest.approx(0.0, abs=1e-9)
    assert flen   == pytest.approx(1.0, abs=1e-9)
    assert ulen   == pytest.approx(1.0, abs=1e-9)


def test_solver_player_roll_inherited_into_camera_up():
    """Roll the ship 30° around its forward axis (body-Y). The camera
    up should rotate with it — it is e3 = body-up Gram-Schmidt projected
    against forward, so it inherits the roll and stays in the solver
    plane."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0)
    s_rot = TGMatrix3(); s_rot.MakeYRotation(math.radians(30))  # roll 30° about body-Y
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Derive what the correct up must be: e3 (body-up perp to e1) projected
    # perpendicular to forward. Compute it independently here.
    # MakeYRotation(30): body-up = Col(2) = (sin30, 0, cos30).
    # e1 = (0, 1, 0); e3 = body-up (already perp to e1).
    e1 = (0.0, 1.0, 0.0)
    e3 = (math.sin(math.radians(30)), 0.0, math.cos(math.radians(30)))
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)
    dot_e3_f = e3[0]*forward[0] + e3[1]*forward[1] + e3[2]*forward[2]
    ux = e3[0] - dot_e3_f*forward[0]
    uy = e3[1] - dot_e3_f*forward[1]
    uz = e3[2] - dot_e3_f*forward[2]
    ulen = math.sqrt(ux*ux + uy*uy + uz*uz)
    expected_up = (ux/ulen, uy/ulen, uz/ulen)

    # The up vector must lie in the (e1, e3) plane, inherit the roll, and
    # be perpendicular to forward.
    assert up[0] == pytest.approx(expected_up[0], abs=1e-6)
    assert up[1] == pytest.approx(expected_up[1], abs=1e-6)
    assert up[2] == pytest.approx(expected_up[2], abs=1e-6)

    # Also confirm no x-component in the plan-orthogonal direction
    # (up must lie in the e1-e3 plane, i.e. have no e2 = e1×e3 component).
    e2 = (e1[1]*e3[2] - e1[2]*e3[1], e1[2]*e3[0] - e1[0]*e3[2], e1[0]*e3[1] - e1[1]*e3[0])
    dot_up_e2 = up[0]*e2[0] + up[1]*e2[1] + up[2]*e2[2]
    assert dot_up_e2 == pytest.approx(0.0, abs=1e-6)


def test_solver_close_target_falls_back_gracefully():
    """When d_chase ≥ D cot β, the back-of-player intersection
    doesn't exist. Solver must pull the eye onto the locus arc behind
    the player rather than emit NaN."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    # D = 5 GU, d_chase = 10: threshold for fallback is D/tan(β) ≈ 17.
    # This case takes the happy path; the dedicated fallback-coverage
    # test below uses d_chase = 100 to actually exercise the fallback.
    t_loc = TGPoint3(0.0, 5.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Finite output:
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
    # Eye behind player (negative y in this setup since e1 = +y):
    assert eye[1] < 0.0
    # Player still framed at y_p ≈ −0.25:
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)
    y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
    assert y_p == pytest.approx(-0.25, abs=1e-3)


def test_solver_close_target_fallback_code_path():
    """Explicitly exercise the fallback branch: d_chase=100, D=5.
    d_chase=100 >> D cot β ≈ 17, so the fallback must be taken.
    Eye lands at the leftmost point of the locus arc (D/2 − r, h)."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 100.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 5.0, 0.0)  # D = 5, d_chase = 100 >> D cot β ≈ 17

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Finite output:
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
    # Eye must be behind player (eye[1] < 0 since e1 = +y):
    assert eye[1] < 0.0
    # Player still framed at y_p ≈ −0.25:
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)
    y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
    assert y_p == pytest.approx(-0.25, abs=1e-3)


def test_solver_body_up_parallel_to_ship_target_does_not_crash():
    """When body-up is parallel to (T − S), the projection that
    builds e3 degenerates. Solver must return finite output."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase_tracking = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()  # body-up = +z
    # Target directly above ship in body frame:
    t_loc = TGPoint3(0.0, 0.0, 20.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)


class _FakeShip:
    """Minimal player/target stub: world transform getters + bounding radius."""
    def __init__(self, loc, rot, radius=1.0):
        self._loc, self._rot, self._radius = loc, rot, radius
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetRadius(self):        return self._radius


class _Scaled(_FakeShip):
    def __init__(self, loc, rot, radius=1.0, scale=1.0):
        super().__init__(loc, rot, radius)
        self._scale = scale
    def GetScale(self): return self._scale


def _sphere_fit(tc, radius):
    from engine.cameras.zoom_fit import TargetExtent, fit_distance
    ext = TargetExtent((0.0, 0.0, 0.0), None, None, radius)
    return fit_distance(ext, (0, 1, 0), (0, 0, 1), tc.v_fov_rad, tc.aspect)


def _zoom_cam(scale=None):
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.zoom_target_active = True
    if scale is not None:
        tc.zoom_target_scale = scale
    return tc


def test_zoom_target_fits_a_scaled_rock_from_far():
    """GetRadius 5 x GetScale 3 = a 15 GU drawn sphere; the eye stands at
    the sphere fit distance from T on the S->T axis, outside the sphere."""
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam()
    rock = _Scaled(TGPoint3(0.0, 400.0, 0.0), TGMatrix3(), radius=5.0, scale=3.0)
    eye, look_at, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()), target=rock,
        dt=None)
    d = _sphere_fit(tc, 15.0)
    assert d > 15.0
    assert eye[0] == pytest.approx(0.0, abs=1e-9)
    assert eye[1] == pytest.approx(400.0 - d, abs=1e-6)
    assert eye[2] == pytest.approx(0.0, abs=1e-9)
    assert look_at[1] > eye[1]


def test_zoom_target_looks_at_the_box_centre_not_the_aim_point():
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam()
    tgt = _FakeShip(TGPoint3(0.0, 200.0, 0.0), TGMatrix3(), radius=10.0)
    tgt._shield_hull_box = ((0.0, 0.0, 5.0), (4.0, 12.0, 3.0))   # centre 5 GU above
    eye, look_at, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()), target=tgt,
        dt=None, aim_point=TGPoint3(3.0, 200.0, 0.0))
    f = tuple(look_at[i] - eye[i] for i in range(3))
    n = math.sqrt(sum(c * c for c in f))
    centre = (0.0, 200.0, 5.0)
    to_c = tuple(centre[i] - eye[i] for i in range(3))
    m = math.sqrt(sum(c * c for c in to_c))
    assert tuple(c / n for c in f) == pytest.approx(
        tuple(c / m for c in to_c), abs=1e-9)
    # and the eye is on the S -> centre axis
    assert eye[0] == pytest.approx(0.0, abs=1e-9)
    assert eye[2] / eye[1] == pytest.approx(5.0 / 200.0, abs=1e-9)


def test_zoom_target_never_behind_the_player():
    """Player 30 GU from a r=15 target, r_player 4: the fit is far larger
    than 26, so the cap holds the eye at player_dist - r_player."""
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam()
    eye, _, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3(), radius=4.0),
        target=_FakeShip(TGPoint3(0.0, 30.0, 0.0), TGMatrix3(), radius=15.0),
        dt=None)
    assert math.dist(eye, (0.0, 30.0, 0.0)) == pytest.approx(26.0, abs=1e-9)
    assert 0.0 < eye[1] < 30.0


def test_zoom_target_ignores_fov_scale():
    from engine.appc.math import TGPoint3, TGMatrix3
    def run(fs):
        tc = _zoom_cam()
        tc.fov_scale = fs
        return tc.compute(
            player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()),
            target=_FakeShip(TGPoint3(0.0, 300.0, 0.0), TGMatrix3(), radius=8.0),
            dt=None)[0]
    assert run(2.0) == pytest.approx(run(1.0), abs=1e-12)


def test_zoom_target_uses_the_cameras_aspect():
    from engine.appc.math import TGPoint3, TGMatrix3
    def run(aspect):
        tc = _zoom_cam()
        tc.aspect = aspect
        eye = tc.compute(
            player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()),
            target=_FakeShip(TGPoint3(0.0, 300.0, 0.0), TGMatrix3(), radius=8.0),
            dt=None)[0]
        return 300.0 - eye[1]
    assert _zoom_cam().aspect == pytest.approx(16.0 / 9.0)
    assert run(0.5) > run(16.0 / 9.0)


def test_zoom_target_distance_filter_runs_before_the_cap():
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam()
    seen = []
    def flt(t, d):
        seen.append(d)
        return d * 10.0
    eye, _, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3(), radius=4.0),
        target=_FakeShip(TGPoint3(0.0, 30.0, 0.0), TGMatrix3(), radius=15.0),
        dt=None, distance_filter=flt)
    assert seen and seen[0] > 0.0
    assert math.dist(eye, (0.0, 30.0, 0.0)) == pytest.approx(26.0, abs=1e-9)


def test_zoom_target_distance_filter_receives_fit_times_scale():
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam(scale=2.0)
    seen = []
    tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()),
        target=_FakeShip(TGPoint3(0.0, 500.0, 0.0), TGMatrix3(), radius=8.0),
        dt=None, distance_filter=lambda t, d: seen.append(d) or d)
    assert seen[0] == pytest.approx(2.0 * _sphere_fit(tc, 8.0), abs=1e-9)


def test_zoom_target_player_at_the_target_centre_is_finite():
    from engine.appc.math import TGPoint3, TGMatrix3
    tc = _zoom_cam()
    eye, look_at, up = tc.compute(
        player=_FakeShip(TGPoint3(5.0, 5.0, 5.0), TGMatrix3()),
        target=_FakeShip(TGPoint3(5.0, 5.0, 5.0), TGMatrix3(), radius=10.0),
        dt=None)
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)


def test_zoom_target_hugging_a_hull_clears_the_near_plane():
    """A tight cap would park the eye on the hull; the surface rule adds
    SCENE_NEAR_GU so the near clip does not slice it."""
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.cameras import SCENE_NEAR_GU
    tc = _zoom_cam()
    # Target r=10 sphere, player 100 GU away but huge fit scale pushes the
    # fit; use a tiny-radius player so the cap allows eye at surface + near.
    tc.zoom_target_scale = 1.0
    tgt = _FakeShip(TGPoint3(0.0, 100.0, 0.0), TGMatrix3(), radius=10.0)
    # Force a hugging fit via the filter.
    eye, _, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3(), radius=1.0),
        target=tgt, dt=None, distance_filter=lambda t, d: 0.1)
    assert math.dist(eye, (0.0, 100.0, 0.0)) == pytest.approx(
        10.0 + SCENE_NEAR_GU, abs=1e-9)


def test_zoom_target_target_projects_to_screen_centre():
    """With eye on the target→player ray and look-at = target, target
    must land at screen-Y = 0."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_t = _project_to_screen_y((0.0, 20.0, 0.0), eye, forward, up)
    assert y_t == pytest.approx(0.0, abs=1e-9)


def test_zoom_target_framing_invariant_across_range():
    """Across target ranges 6, 50, 500 GU with the target stays centred and the eye is exactly the sphere fit away."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    for d in (6.0, 50.0, 500.0):
        tc = _TrackingCamera()
        tc.set_ship_radius(1.0)
        tc.zoom_target_active = True

        s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
        t_loc = TGPoint3(0.0, d, 0.0)

        eye, look_at, up = tc.compute(
            player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

        dx = t_loc.x - eye[0]; dy = t_loc.y - eye[1]; dz = t_loc.z - eye[2]
        assert math.sqrt(dx*dx + dy*dy + dz*dz) == pytest.approx(_sphere_fit(tc, 1.0), abs=1e-6), \
            f"range {d}: eye→target = {math.sqrt(dx*dx + dy*dy + dz*dz)}"

        # Target screen-Y ≈ 0.
        fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        forward = (fx/flen, fy/flen, fz/flen)
        y_t = _project_to_screen_y((0.0, d, 0.0), eye, forward, up)
        assert y_t == pytest.approx(0.0, abs=1e-6), f"range {d}: y_t={y_t}"


def test_zoom_target_inherits_player_roll_into_up():
    """Ship rolled 30° around body-Y; ZoomTarget up follows ship body-up
    perpendicularised against forward."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0)
    s_rot = TGMatrix3(); s_rot.MakeYRotation(math.radians(30))
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    _, _, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Body-up after Y-roll 30° = (sin 30°, 0, cos 30°). e1 = (0,1,0).
    # body-up already perpendicular to e1, so e3 = body-up exactly.
    # Forward = e1 = (0,1,0), so up perpendicularised against forward = e3.
    assert up[0] == pytest.approx(math.sin(math.radians(30)), abs=1e-6)
    assert up[1] == pytest.approx(0.0,                          abs=1e-6)
    assert up[2] == pytest.approx(math.cos(math.radians(30)), abs=1e-6)


def test_zoom_target_target_without_a_radius_surface_is_framed_at_unit_radius():
    """A target with no GetRadius (a waypoint stub) reads as r=1.0 so the
    eye still stands off by the unit-sphere fit rather than dividing by
    nothing."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    class _NoRadius:
        def __init__(self, loc): self._loc = loc
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return TGMatrix3()

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.zoom_target_active = True

    eye, _, _ = tc.compute(
        player=_FakeShip(TGPoint3(0.0, 0.0, 0.0), TGMatrix3()),
        target=_NoRadius(TGPoint3(0.0, 20.0, 0.0)), dt=None)
    assert eye[1] == pytest.approx(20.0 - _sphere_fit(tc, 1.0), abs=1e-6)


# ── pose_of provider: camera reads interpolated poses (smooth-motion fix) ─────


class _PoseShip:
    """Minimal ship exposing live world pose + a target link."""
    def __init__(self, loc_xyz, target=None):
        from engine.appc.math import TGPoint3, TGMatrix3
        self._loc = TGPoint3(*loc_xyz)
        self._rot = TGMatrix3()
        self._target = target
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return self._target


def test_tracking_compute_reads_player_and_target_through_pose_of():
    """When a pose_of provider is supplied, the solver must anchor on the
    poses it returns (interpolated render poses), not the live object poses.

    Verified via translation covariance: offsetting BOTH the player and the
    target by the same vector V translates the whole camera rig by V, so
    eye and look_at shift by exactly V while up is unchanged.
    """
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)

    player = _PoseShip((0.0, 0.0, 0.0))
    target = _PoseShip((0.0, 20.0, 0.0))

    eye0, look0, up0 = tc.compute(player=player, target=target, dt=None)

    V = (100.0, -30.0, 7.0)

    def pose_of(obj):
        loc = obj.GetWorldLocation()
        return (TGPoint3(loc.x + V[0], loc.y + V[1], loc.z + V[2]),
                TGMatrix3())

    eye1, look1, up1 = tc.compute(player=player, target=target, dt=None,
                                  pose_of=pose_of)

    for a, b, v in zip(eye1, eye0, V):
        assert a == pytest.approx(b + v, abs=1e-6)
    for a, b, v in zip(look1, look0, V):
        assert a == pytest.approx(b + v, abs=1e-6)
    for a, b in zip(up1, up0):
        assert a == pytest.approx(b, abs=1e-6)
