"""Unit tests for _CameraControl — arrow-key orbit + scroll-wheel zoom on
top of the ship-follow camera. The camera offset is stored in ship body
frame so it rotates with the ship.

Mirrors the test fakes from test_player_control.py."""
import math
import pytest


class _FakeKeys:
    KEY_UP    = 100
    KEY_DOWN  = 101
    KEY_LEFT  = 102
    KEY_RIGHT = 103
    KEY_C     = 104


class _FakeKeyReader:
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


def _make_ship_pose(x=0.0, y=0.0, z=0.0):
    from engine.appc.math import TGPoint3, TGMatrix3
    loc = TGPoint3(x, y, z)
    rot = TGMatrix3()
    return loc, rot


def test_default_state_matches_radius_framing():
    """Defaults frame a unit-radius ship at -CAM_BACK_RADII forward + CAM_UP_RADII up."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    from engine.host_loop import CAM_BACK_RADII, CAM_UP_RADII

    cc = _CameraControl()
    expected_dist  = math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2)
    expected_pitch = math.atan2(CAM_UP_RADII, CAM_BACK_RADII)

    assert cc.distance        == pytest.approx(expected_dist)
    assert cc.orbit_pitch_rad == pytest.approx(expected_pitch)
    assert cc.orbit_yaw_rad   == pytest.approx(0.0)


def test_right_arrow_increases_yaw():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_RIGHT)
    for _ in range(60):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_yaw_rad == pytest.approx(_CameraControl.TURN_RATE_RAD_PER_S, abs=1e-3)


def test_left_arrow_decreases_yaw():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT)
    for _ in range(60):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_yaw_rad == pytest.approx(-_CameraControl.TURN_RATE_RAD_PER_S, abs=1e-3)


def test_up_arrow_increases_pitch():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    start_pitch = cc.orbit_pitch_rad
    reader.held.add(reader.keys.KEY_UP)
    for _ in range(30):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    expected = start_pitch + _CameraControl.TURN_RATE_RAD_PER_S * 0.5
    assert cc.orbit_pitch_rad == pytest.approx(expected, abs=1e-3)


def test_down_arrow_decreases_pitch():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    start_pitch = cc.orbit_pitch_rad
    reader.held.add(reader.keys.KEY_DOWN)
    for _ in range(30):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    expected = start_pitch - _CameraControl.TURN_RATE_RAD_PER_S * 0.5
    assert cc.orbit_pitch_rad == pytest.approx(expected, abs=1e-3)


def test_pitch_clamps_at_upper_limit():
    """Hold UP indefinitely → orbit_pitch saturates at PITCH_LIMIT_RAD."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_UP)
    for _ in range(600):  # 10 simulated seconds
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_pitch_rad == pytest.approx(_CameraControl.PITCH_LIMIT_RAD)


def test_pitch_clamps_at_lower_limit():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_DOWN)
    for _ in range(600):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_pitch_rad == pytest.approx(-_CameraControl.PITCH_LIMIT_RAD)


def test_scroll_up_zooms_in():
    """Positive scroll_y reduces distance by 0.9^n per notch."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    initial = cc.distance
    cc.apply(dt=1.0/60, h=reader, scroll_y=3.0)
    expected = initial * (_CameraControl.ZOOM_FACTOR_PER_NOTCH ** 3.0)
    assert cc.distance == pytest.approx(expected)


def test_scroll_down_zooms_out():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    initial = cc.distance
    cc.apply(dt=1.0/60, h=reader, scroll_y=-2.0)
    expected = initial * (_CameraControl.ZOOM_FACTOR_PER_NOTCH ** -2.0)
    assert cc.distance == pytest.approx(expected)


def test_distance_clamps_at_min():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    cc.apply(dt=1.0/60, h=reader, scroll_y=1000.0)  # absurd zoom in
    assert cc.distance == pytest.approx(cc.distance_min)


def test_distance_clamps_at_max():
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    cc.apply(dt=1.0/60, h=reader, scroll_y=-1000.0)
    assert cc.distance == pytest.approx(cc.distance_max)


def test_compute_camera_at_defaults_at_origin_identity_rotation():
    """Default orbit + identity ship rotation places the eye at
    (0, -CAM_BACK_RADII*r, CAM_UP_RADII*r) relative to a unit-radius ship."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    from engine.host_loop import CAM_BACK_RADII, CAM_UP_RADII

    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    eye, target, up = cc.compute_camera(loc, rot)

    assert eye[0] == pytest.approx(0.0,             abs=1e-3)
    assert eye[1] == pytest.approx(-CAM_BACK_RADII, abs=1e-3)
    assert eye[2] == pytest.approx( CAM_UP_RADII,   abs=1e-3)
    assert target == pytest.approx((0.0, 0.0, 0.0))
    assert up     == pytest.approx((0.0, 0.0, 1.0))


def test_compute_camera_offset_is_in_ship_body_frame():
    """Yaw the ship 90° around world Z. The camera-to-ship vector should
    rotate with the ship so the camera stays 'behind' the new heading."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    from engine.host_loop import CAM_BACK_RADII, CAM_UP_RADII

    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeZRotation(math.radians(90))
    eye, target, _ = cc.compute_camera(loc, rot)

    # Ship's body-Y after a +90° yaw points along R.GetCol(1) = (-1, 0, 0)
    # under column-vector convention (see CLAUDE.md). Body-Z is unchanged
    # (0, 0, 1). The camera sits at
    #   -CAM_BACK_RADII*body_Y + CAM_UP_RADII*body_Z.
    expected_eye_x =  CAM_BACK_RADII
    expected_eye_y =  0.0
    expected_eye_z =  CAM_UP_RADII
    assert eye[0] == pytest.approx(expected_eye_x, abs=1e-3)
    assert eye[1] == pytest.approx(expected_eye_y, abs=1e-3)
    assert eye[2] == pytest.approx(expected_eye_z, abs=1e-3)


def test_compute_camera_up_is_ship_up():
    """Roll the ship; camera up should track ship-up (banking visible)."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeYRotation(math.radians(30))   # roll
    _, _, up = cc.compute_camera(loc, rot)
    # Ship-up after Y rotation: col 2 of R (column-vector convention; see CLAUDE.md).
    expected = rot.GetCol(2)
    assert up[0] == pytest.approx(expected.x)
    assert up[1] == pytest.approx(expected.y)
    assert up[2] == pytest.approx(expected.z)


# ── Spring/lag smoothing ─────────────────────────────────────────────────────


def _roll_90_rot():
    """Ship rotated 90° around body Y (roll). Col 2 (body-up) = (1, 0, 0)
    under column-vector convention (see CLAUDE.md)."""
    from engine.appc.math import TGMatrix3
    r = TGMatrix3()
    r.MakeYRotation(math.radians(90))
    return r


def test_spring_first_call_with_dt_seeds_to_live_rotation():
    """First compute_camera with dt should produce the same up vector as the
    no-spring path, because there is no prior smoothed state to lag against."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeYRotation(math.radians(30))
    eye_dt,  _, up_dt  = cc.compute_camera(loc, rot, dt=1.0/60)
    cc2 = _CameraControl()
    eye_no, _, up_no = cc2.compute_camera(loc, rot)
    assert up_dt  == pytest.approx(up_no,  abs=1e-9)
    assert eye_dt == pytest.approx(eye_no, abs=1e-9)


def test_spring_lags_after_sudden_ship_rotation_jump():
    """Seed smoothing at identity, then snap the ship to a 90° roll. After
    one short tick the camera up should still be near world-up, not the new
    ship-up."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, ident = _make_ship_pose(0.0, 0.0, 0.0)
    # Seed: many ticks at identity so smoothed_rot ≈ identity.
    for _ in range(60):
        cc.compute_camera(loc, ident, dt=1.0/60)
    rolled = _roll_90_rot()
    _, _, up = cc.compute_camera(loc, rolled, dt=1.0/60)
    # Live ship-up is (-1, 0, 0). After ~16ms with τ=0.25s, blend α ≈ 0.064.
    # Up should still be very close to world +Z, not anywhere near body +X.
    assert up[2] > 0.99
    assert abs(up[0]) < 0.10


def test_spring_converges_to_live_after_long_settle():
    """Hold the rotation steady for ≫ τ; smoothed rotation should reach the
    live rotation within float tolerance."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, ident = _make_ship_pose(0.0, 0.0, 0.0)
    cc.compute_camera(loc, ident, dt=1.0/60)   # seed at identity
    rolled = _roll_90_rot()
    # 6 seconds → ≥ 12 × τ regardless of τ ≤ 0.5s → residual ≲ e^-12.
    for _ in range(int(6.0 * 60)):
        cc.compute_camera(loc, rolled, dt=1.0/60)
    _, _, up = cc.compute_camera(loc, rolled, dt=1.0/60)
    expected = rolled.GetCol(2)
    assert up[0] == pytest.approx(expected.x, abs=1e-4)
    assert up[1] == pytest.approx(expected.y, abs=1e-4)
    assert up[2] == pytest.approx(expected.z, abs=1e-4)


def test_spring_snap_clears_smoothing():
    """After snap(), the next compute_camera with dt should align to live
    immediately rather than blending from the prior smoothed state."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, ident = _make_ship_pose(0.0, 0.0, 0.0)
    for _ in range(60):
        cc.compute_camera(loc, ident, dt=1.0/60)
    cc.snap()
    rolled = _roll_90_rot()
    _, _, up = cc.compute_camera(loc, rolled, dt=1.0/60)
    expected = rolled.GetCol(2)
    assert up[0] == pytest.approx(expected.x, abs=1e-9)
    assert up[1] == pytest.approx(expected.y, abs=1e-9)
    assert up[2] == pytest.approx(expected.z, abs=1e-9)


def test_spring_keeps_basis_orthonormal_under_continual_rotation():
    """Continually update with a non-trivial rotation; the smoothed basis
    used for the camera must remain orthonormal (no drift / non-unit)."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    from engine.appc.math import TGMatrix3
    cc = _CameraControl()
    cc.orbit_yaw_rad = math.radians(45)        # so eye depends on all three rows
    loc, _ = _make_ship_pose(0.0, 0.0, 0.0)
    angle = 0.0
    for _ in range(600):
        r = TGMatrix3()
        r.MakeZRotation(angle)
        angle += math.radians(1.0)             # slow continuous yaw
        cc.compute_camera(loc, r, dt=1.0/60)
    rot_used = cc._smoothed_rot                # internal smoothed basis
    rows = [rot_used.GetRow(i) for i in range(3)]
    for v in rows:
        assert math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z) == pytest.approx(1.0, abs=1e-6)
    def dot(a, b): return a.x*b.x + a.y*b.y + a.z*b.z
    assert dot(rows[0], rows[1]) == pytest.approx(0.0, abs=1e-6)
    assert dot(rows[1], rows[2]) == pytest.approx(0.0, abs=1e-6)
    assert dot(rows[0], rows[2]) == pytest.approx(0.0, abs=1e-6)


def test_compute_camera_dt_none_does_not_mutate_smoothed_state():
    """Legacy call (no dt) must remain a pure projection — no smoothing
    state should accumulate, so existing single-shot tests stay valid."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeZRotation(math.radians(30))
    cc.compute_camera(loc, rot)
    assert cc._smoothed_rot is None


def test_orbit_yaw_90_puts_camera_on_ship_right():
    """orbit_yaw=+90° at default pitch: camera should sit to the ship's right
    (body +X) and slightly above. Identity ship rotation."""
    from engine.cameras.chase import _ChaseCamera as _CameraControl
    from engine.host_loop import CAM_BACK_RADII, CAM_UP_RADII
    cc = _CameraControl()
    cc.orbit_yaw_rad = math.radians(90)
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    eye, _, _ = cc.compute_camera(loc, rot)

    expected_x =  CAM_BACK_RADII                       # cos(default_pitch)*dist along +X
    expected_y =  0.0
    expected_z =  CAM_UP_RADII
    assert eye[0] == pytest.approx(expected_x, abs=1e-3)
    assert eye[1] == pytest.approx(expected_y, abs=1e-3)
    assert eye[2] == pytest.approx(expected_z, abs=1e-3)


def test_reverse_active_defaults_to_false():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    assert cc.reverse_active is False


def test_enter_exit_reverse_toggles_flag():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    assert cc.reverse_active is False
    cc.enter_reverse()
    assert cc.reverse_active is True
    cc.exit_reverse()
    assert cc.reverse_active is False
    # Idempotent.
    cc.enter_reverse()
    cc.enter_reverse()
    assert cc.reverse_active is True
    cc.exit_reverse()
    cc.exit_reverse()
    assert cc.reverse_active is False


def test_reverse_active_flips_eye_to_ship_front():
    """With identity ship and default orbit (yaw=0, pitch≈atan2(0.25, 1.5)):
    behind-ship eye is at (0, -CAM_BACK_RADII, CAM_UP_RADII). Reverse flips
    sign of x and y components; z component preserved (sign flip is in the
    (ox, oy) body-frame plane only)."""
    from engine.cameras.chase  import _ChaseCamera
    from engine.cameras        import CAM_BACK_RADII, CAM_UP_RADII
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc = _ChaseCamera()
    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()

    eye_normal, _, _ = cc.compute_camera(loc, rot)
    cc.enter_reverse()
    eye_reverse, _, _ = cc.compute_camera(loc, rot)

    # x and y flip sign; z is unchanged.
    assert eye_reverse[0] == pytest.approx(-eye_normal[0], abs=1e-9)
    assert eye_reverse[1] == pytest.approx(-eye_normal[1], abs=1e-9)
    assert eye_reverse[2] == pytest.approx( eye_normal[2], abs=1e-9)


def test_reverse_inactive_eye_unchanged_from_baseline():
    """Regression: setting and then unsetting reverse_active leaves eye
    identical to a fresh camera."""
    from engine.cameras.chase import _ChaseCamera
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc1 = _ChaseCamera()
    cc2 = _ChaseCamera()
    cc2.enter_reverse()
    cc2.exit_reverse()

    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()
    eye1, _, _ = cc1.compute_camera(loc, rot)
    eye2, _, _ = cc2.compute_camera(loc, rot)
    assert eye1 == pytest.approx(eye2, abs=1e-12)


def test_reverse_composes_with_orbit_yaw():
    """yaw_effective = orbit_yaw_rad + π. With orbit_yaw_rad = π/4 + π = 5π/4,
    cos/sin produce the same result as a single +π/4 yaw with reverse on."""
    import math
    from engine.cameras.chase import _ChaseCamera
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc_combined = _ChaseCamera()
    cc_combined.orbit_yaw_rad = math.pi / 4
    cc_combined.enter_reverse()

    cc_yaw_only = _ChaseCamera()
    cc_yaw_only.orbit_yaw_rad = math.pi / 4 + math.pi

    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()
    eye_c, _, _ = cc_combined.compute_camera(loc, rot)
    eye_y, _, _ = cc_yaw_only.compute_camera(loc, rot)

    assert eye_c == pytest.approx(eye_y, abs=1e-12)
