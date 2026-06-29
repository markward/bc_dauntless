"""Unit tests for _BridgeCamera — mouse-look first-person camera anchored
at the MissionLib-pinned DBridge captain's-chair pose. The camera lives
in bridge-local space (no ship-world coupling) while the viewscreen-as-
RTT path is off."""
import math
import pytest


def test_bridge_camera_starts_at_initial_yaw():
    """Initial yaw is INITIAL_YAW_RAD (π), so the default forward
    points -Y (into the bridge interior as authored)."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    assert bc.yaw_rad   == pytest.approx(_BridgeCamera.INITIAL_YAW_RAD)
    assert bc.pitch_rad == pytest.approx(0.0)


def test_mouse_delta_accumulates_yaw_and_pitch():
    """Right-mouse → look-right (negative yaw), up-mouse → look-up
    (positive pitch). Sign convention checked here so future changes
    can't silently flip it."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    initial_yaw = bc.yaw_rad
    bc.apply(mouse_dx=100.0, mouse_dy=-50.0)
    expected_yaw   = initial_yaw + (-100.0 * _BridgeCamera.MOUSE_SENSITIVITY)
    expected_pitch = -(-50.0)  * _BridgeCamera.MOUSE_SENSITIVITY  # -dy → +pitch
    assert bc.yaw_rad   == pytest.approx(expected_yaw)
    assert bc.pitch_rad == pytest.approx(expected_pitch)


def test_pitch_clamps_at_positive_limit():
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    # Drive pitch past PITCH_LIMIT_RAD with one big delta. Negative dy
    # in screen coords is mouse-up → positive pitch (look up).
    bc.apply(mouse_dx=0.0, mouse_dy=-10000.0)
    assert bc.pitch_rad == pytest.approx(_BridgeCamera.PITCH_LIMIT_RAD)


def test_pitch_clamps_at_negative_limit():
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    # Positive dy → look down → negative pitch.
    bc.apply(mouse_dx=0.0, mouse_dy=10000.0)
    assert bc.pitch_rad == pytest.approx(-_BridgeCamera.PITCH_LIMIT_RAD)


def test_yaw_wraps_freely_no_clamp():
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    initial_yaw = bc.yaw_rad
    # Drive yaw past 2π with one big delta.
    bc.apply(mouse_dx=100000.0, mouse_dy=0.0)
    expected = initial_yaw + (-100000.0 * _BridgeCamera.MOUSE_SENSITIVITY)
    assert bc.yaw_rad == pytest.approx(expected)


def test_camera_anchored_at_bridge_local_offset():
    """Initial yaw (π) makes the default forward -Y. Eye sits at the
    per-bridge captain's-chair offset from the SDK-camera-derived module
    global _BRIDGE_CAMERA_EYE. Up is unit length. Target differs from eye."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    eye, target, up, _fov = bc.compute_camera()
    ox, oy, oz = bc._eye_offset()
    assert eye[0] == pytest.approx(ox)
    assert eye[1] == pytest.approx(oy)
    assert eye[2] == pytest.approx(oz)
    # Default forward is +Y rotated π around +Z = -Y → target = eye + (0, -1, 0)
    assert target[0] == pytest.approx(ox, abs=1e-6)
    assert target[1] == pytest.approx(oy - 1.0, abs=1e-6)
    assert target[2] == pytest.approx(oz, abs=1e-6)
    up_len_sq = up[0]*up[0] + up[1]*up[1] + up[2]*up[2]
    assert up_len_sq == pytest.approx(1.0, abs=1e-6)


def test_yaw_rotates_forward_in_xy_plane():
    """At yaw = π/2 (90°), forward = +Y rotated 90° around +Z = -X.
    Confirms yaw axis is world-up (+Z) and rotation direction matches
    the sign convention, independent of the runtime initial yaw."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    bc.yaw_rad = math.radians(90.0)
    eye, target, _up, _fov = bc.compute_camera()
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    assert fx == pytest.approx(-1.0, abs=1e-6)
    assert fy == pytest.approx( 0.0, abs=1e-6)


def test_compute_camera_takes_no_ship_args():
    """Guard against the previous ship-coupled signature being
    re-introduced. compute_camera must work with zero positional args."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    # Would raise TypeError if compute_camera still required ship args.
    bc.compute_camera()


def test_eye_offset_reads_module_global(monkeypatch):
    """Step 5a: the captain eye comes from the SDK-camera-derived module
    global (the GalaxyBridgeCaptain mode's BasePosition), not a hardcoded
    per-bridge table."""
    import engine.host_loop as hl
    from engine.host_loop import _BridgeCamera
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_EYE", (1.0, 2.0, 3.0))
    assert _BridgeCamera()._eye_offset() == (1.0, 2.0, 3.0)


# ── PlaceByDirection gradual lift as the view turns off-forward ───────────────
# SDK GalaxyBridgeCaptain: eye = base + Movement(0,-15,+15) * frac, frac
# smoothstepping over [StartMoveAngle=1.25, EndMoveAngle=2.5] rad by how far the
# view has turned off bridge-forward, scaled by the feel knob.
_PBD_EYE = (0.683736, 86.978439, 50.0)
_PBD_MOVE = ((0.0, -15.0, 15.0), 1.25, 2.5)


def _lift_camera(monkeypatch, scale=1.0):
    import engine.host_loop as hl
    from engine.host_loop import _BridgeCamera
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_EYE", _PBD_EYE)
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_MOVE", _PBD_MOVE)
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_MOVE_SCALE", scale)
    return _BridgeCamera()


def test_no_lift_facing_forward(monkeypatch):
    """Facing the viewscreen (yaw = π) is angle 0 → no lift; the eye is the
    BasePosition (z=50)."""
    bc = _lift_camera(monkeypatch)
    bc.yaw_rad = math.pi
    assert bc._eye_offset() == pytest.approx(_PBD_EYE)


def test_full_lift_facing_rear(monkeypatch):
    """Facing the rear (yaw = 0) is angle π > EndMoveAngle → full Movement:
    eye = base + (0,-15,+15)."""
    bc = _lift_camera(monkeypatch)
    bc.yaw_rad = 0.0
    eye = bc._eye_offset()
    assert eye[0] == pytest.approx(0.683736)
    assert eye[1] == pytest.approx(86.978439 - 15.0)
    assert eye[2] == pytest.approx(50.0 + 15.0)


def test_partial_lift_smoothsteps(monkeypatch):
    """Inside the band the lift eases via the 0.5-0.5cos smoothstep — at the
    band midpoint it is exactly half."""
    bc = _lift_camera(monkeypatch)
    mid = 0.5 * (1.25 + 2.5)
    bc.yaw_rad = math.pi - mid          # horiz = |(π-mid) % 2π - π| = mid
    eye = bc._eye_offset()
    assert eye[2] == pytest.approx(50.0 + 15.0 * 0.5)
    assert eye[1] == pytest.approx(86.978439 - 15.0 * 0.5)


def test_lift_scales_with_feel_knob(monkeypatch):
    """The lift magnitude scales linearly with _BRIDGE_CAMERA_MOVE_SCALE. The
    knob is a module global, so measure each scale before changing it."""
    import engine.host_loop as hl
    bc = _lift_camera(monkeypatch, scale=0.5)
    bc.yaw_rad = 0.0
    half_lift = bc._eye_offset()[2] - 50.0
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_MOVE_SCALE", 1.0)
    full_lift = bc._eye_offset()[2] - 50.0
    assert full_lift == pytest.approx(2.0 * half_lift)
    assert half_lift == pytest.approx(15.0 * 0.5)


def test_no_lift_without_movement(monkeypatch):
    """_BRIDGE_CAMERA_MOVE None (e.g. Sovereign) → static base at any yaw."""
    import engine.host_loop as hl
    from engine.host_loop import _BridgeCamera
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_EYE", _PBD_EYE)
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_MOVE", None)
    bc = _BridgeCamera()
    bc.yaw_rad = 0.0
    assert bc._eye_offset() == pytest.approx(_PBD_EYE)
