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


def test_default_state_matches_legacy_offset():
    """Defaults reproduce the pre-orbit (-forward*600 + up*200) framing."""
    from engine.host_loop import _CameraControl
    from engine.scale import SHIP_SCALE

    cc = _CameraControl()
    expected_dist  = math.sqrt(600.0**2 + 200.0**2) * SHIP_SCALE
    expected_pitch = math.atan2(200.0, 600.0)

    assert cc.distance        == pytest.approx(expected_dist)
    assert cc.orbit_pitch_rad == pytest.approx(expected_pitch)
    assert cc.orbit_yaw_rad   == pytest.approx(0.0)


def test_right_arrow_increases_yaw():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_RIGHT)
    for _ in range(60):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_yaw_rad == pytest.approx(_CameraControl.TURN_RATE_RAD_PER_S, abs=1e-3)


def test_left_arrow_decreases_yaw():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT)
    for _ in range(60):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_yaw_rad == pytest.approx(-_CameraControl.TURN_RATE_RAD_PER_S, abs=1e-3)


def test_up_arrow_increases_pitch():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    start_pitch = cc.orbit_pitch_rad
    reader.held.add(reader.keys.KEY_UP)
    for _ in range(30):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    expected = start_pitch + _CameraControl.TURN_RATE_RAD_PER_S * 0.5
    assert cc.orbit_pitch_rad == pytest.approx(expected, abs=1e-3)


def test_down_arrow_decreases_pitch():
    from engine.host_loop import _CameraControl
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
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_UP)
    for _ in range(600):  # 10 simulated seconds
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_pitch_rad == pytest.approx(_CameraControl.PITCH_LIMIT_RAD)


def test_pitch_clamps_at_lower_limit():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_DOWN)
    for _ in range(600):
        cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    assert cc.orbit_pitch_rad == pytest.approx(-_CameraControl.PITCH_LIMIT_RAD)


def test_scroll_up_zooms_in():
    """Positive scroll_y reduces distance by 0.9^n per notch."""
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    initial = cc.distance
    cc.apply(dt=1.0/60, h=reader, scroll_y=3.0)
    expected = initial * (_CameraControl.ZOOM_FACTOR_PER_NOTCH ** 3.0)
    assert cc.distance == pytest.approx(expected)


def test_scroll_down_zooms_out():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    initial = cc.distance
    cc.apply(dt=1.0/60, h=reader, scroll_y=-2.0)
    expected = initial * (_CameraControl.ZOOM_FACTOR_PER_NOTCH ** -2.0)
    assert cc.distance == pytest.approx(expected)


def test_distance_clamps_at_min():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    cc.apply(dt=1.0/60, h=reader, scroll_y=1000.0)  # absurd zoom in
    assert cc.distance == pytest.approx(_CameraControl.DISTANCE_MIN)


def test_distance_clamps_at_max():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    reader = _FakeKeyReader()
    cc.apply(dt=1.0/60, h=reader, scroll_y=-1000.0)
    assert cc.distance == pytest.approx(_CameraControl.DISTANCE_MAX)


def test_C_resets_to_defaults():
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    cc.orbit_yaw_rad   = 1.2
    cc.orbit_pitch_rad = -0.4
    cc.distance        = 12345.0
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_C)
    cc.apply(dt=1.0/60, h=reader, scroll_y=0.0)
    fresh = _CameraControl()
    assert cc.orbit_yaw_rad   == pytest.approx(fresh.orbit_yaw_rad)
    assert cc.orbit_pitch_rad == pytest.approx(fresh.orbit_pitch_rad)
    assert cc.distance        == pytest.approx(fresh.distance)


def test_compute_camera_at_defaults_at_origin_identity_rotation():
    """Default orbit + identity ship rotation reproduces the legacy
    (0, -600*SHIP_SCALE, 200*SHIP_SCALE) eye position relative to ship."""
    from engine.host_loop import _CameraControl
    from engine.scale import SHIP_SCALE

    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    eye, target, up = cc.compute_camera(loc, rot)

    assert eye[0] == pytest.approx(0.0,                    abs=1e-3)
    assert eye[1] == pytest.approx(-600.0 * SHIP_SCALE,    abs=1e-3)
    assert eye[2] == pytest.approx( 200.0 * SHIP_SCALE,    abs=1e-3)
    assert target == pytest.approx((0.0, 0.0, 0.0))
    assert up     == pytest.approx((0.0, 0.0, 1.0))


def test_compute_camera_offset_is_in_ship_body_frame():
    """Yaw the ship 90° around world Z. The camera-to-ship vector should
    rotate with the ship so the camera stays 'behind' the new heading."""
    from engine.host_loop import _CameraControl
    from engine.scale import SHIP_SCALE
    from engine.appc.math import TGMatrix3

    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeZRotation(math.radians(90))
    eye, target, _ = cc.compute_camera(loc, rot)

    # Ship's body-Y after a +90° yaw points along R.GetRow(1) = (1, 0, 0).
    # The camera should sit at -600*body_Y + 200*body_Z from the ship.
    expected_eye_x = -600.0 * SHIP_SCALE
    expected_eye_y =    0.0
    expected_eye_z =  200.0 * SHIP_SCALE
    assert eye[0] == pytest.approx(expected_eye_x, abs=1e-3)
    assert eye[1] == pytest.approx(expected_eye_y, abs=1e-3)
    assert eye[2] == pytest.approx(expected_eye_z, abs=1e-3)


def test_compute_camera_up_is_ship_up():
    """Roll the ship; camera up should track ship-up (banking visible)."""
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeYRotation(math.radians(30))   # roll
    _, _, up = cc.compute_camera(loc, rot)
    # Ship-up after Y rotation: row 2 of R.
    expected = rot.GetRow(2)
    assert up[0] == pytest.approx(expected.x)
    assert up[1] == pytest.approx(expected.y)
    assert up[2] == pytest.approx(expected.z)


# ── Spring/lag smoothing ─────────────────────────────────────────────────────


def _roll_90_rot():
    """Ship rotated 90° around body Y (roll). Row 2 (body-up) = (-1, 0, 0)."""
    from engine.appc.math import TGMatrix3
    r = TGMatrix3()
    r.MakeYRotation(math.radians(90))
    return r


def test_spring_first_call_with_dt_seeds_to_live_rotation():
    """First compute_camera with dt should produce the same up vector as the
    no-spring path, because there is no prior smoothed state to lag against."""
    from engine.host_loop import _CameraControl
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
    from engine.host_loop import _CameraControl
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
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    loc, ident = _make_ship_pose(0.0, 0.0, 0.0)
    cc.compute_camera(loc, ident, dt=1.0/60)   # seed at identity
    rolled = _roll_90_rot()
    # 6 seconds → ≥ 12 × τ regardless of τ ≤ 0.5s → residual ≲ e^-12.
    for _ in range(int(6.0 * 60)):
        cc.compute_camera(loc, rolled, dt=1.0/60)
    _, _, up = cc.compute_camera(loc, rolled, dt=1.0/60)
    expected = rolled.GetRow(2)
    assert up[0] == pytest.approx(expected.x, abs=1e-4)
    assert up[1] == pytest.approx(expected.y, abs=1e-4)
    assert up[2] == pytest.approx(expected.z, abs=1e-4)


def test_spring_snap_clears_smoothing():
    """After snap(), the next compute_camera with dt should align to live
    immediately rather than blending from the prior smoothed state."""
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    loc, ident = _make_ship_pose(0.0, 0.0, 0.0)
    for _ in range(60):
        cc.compute_camera(loc, ident, dt=1.0/60)
    cc.snap()
    rolled = _roll_90_rot()
    _, _, up = cc.compute_camera(loc, rolled, dt=1.0/60)
    expected = rolled.GetRow(2)
    assert up[0] == pytest.approx(expected.x, abs=1e-9)
    assert up[1] == pytest.approx(expected.y, abs=1e-9)
    assert up[2] == pytest.approx(expected.z, abs=1e-9)


def test_spring_keeps_basis_orthonormal_under_continual_rotation():
    """Continually update with a non-trivial rotation; the smoothed basis
    used for the camera must remain orthonormal (no drift / non-unit)."""
    from engine.host_loop import _CameraControl
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
    from engine.host_loop import _CameraControl
    cc = _CameraControl()
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    rot.MakeZRotation(math.radians(30))
    cc.compute_camera(loc, rot)
    assert cc._smoothed_rot is None


def test_orbit_yaw_90_puts_camera_on_ship_right():
    """orbit_yaw=+90° at default pitch ≈ 18.4°: camera should sit to the
    ship's right (body +X) and slightly above. Identity ship rotation."""
    from engine.host_loop import _CameraControl
    from engine.scale import SHIP_SCALE
    cc = _CameraControl()
    cc.orbit_yaw_rad = math.radians(90)
    loc, rot = _make_ship_pose(0.0, 0.0, 0.0)
    eye, _, _ = cc.compute_camera(loc, rot)

    expected_x =  600.0 * SHIP_SCALE   # cos(default_pitch)*dist along +X
    expected_y =  0.0
    expected_z =  200.0 * SHIP_SCALE
    assert eye[0] == pytest.approx(expected_x, abs=1e-3)
    assert eye[1] == pytest.approx(expected_y, abs=1e-3)
    assert eye[2] == pytest.approx(expected_z, abs=1e-3)
