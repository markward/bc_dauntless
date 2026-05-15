"""Unit tests for _BridgeCamera — mouse-look first-person camera anchored
at the MissionLib-pinned DBridge captain's-chair pose. The camera lives
in bridge-local space (no ship-world coupling) while the viewscreen-as-
RTT path is off."""
import math
import pytest


def test_bridge_camera_starts_at_zero_yaw_pitch():
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    assert bc.yaw_rad   == pytest.approx(0.0)
    assert bc.pitch_rad == pytest.approx(0.0)


def test_mouse_delta_accumulates_yaw_and_pitch():
    """Right-mouse → look-right (negative yaw), up-mouse → look-up
    (positive pitch). Sign convention checked here so future changes
    can't silently flip it."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    bc.apply(mouse_dx=100.0, mouse_dy=-50.0)
    expected_yaw   = -100.0 * _BridgeCamera.MOUSE_SENSITIVITY
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
    # Drive yaw past 2π with one big delta.
    bc.apply(mouse_dx=100000.0, mouse_dy=0.0)
    expected = -100000.0 * _BridgeCamera.MOUSE_SENSITIVITY
    assert bc.yaw_rad == pytest.approx(expected)


def test_camera_anchored_at_bridge_local_offset():
    """At zero yaw/pitch, eye sits at BRIDGE_LOCAL_OFFSET in bridge-
    local space. Default forward is +Y (into bridge interior). Up is a
    unit vector. Target differs from eye so the view direction is
    well-defined."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    eye, target, up = bc.compute_camera()
    ox, oy, oz = _BridgeCamera.BRIDGE_LOCAL_OFFSET
    assert eye[0] == pytest.approx(ox)
    assert eye[1] == pytest.approx(oy)
    assert eye[2] == pytest.approx(oz)
    # Default forward is +Y → target = eye + (0, 1, 0)
    assert target[0] == pytest.approx(ox)
    assert target[1] == pytest.approx(oy + 1.0)
    assert target[2] == pytest.approx(oz)
    up_len_sq = up[0]*up[0] + up[1]*up[1] + up[2]*up[2]
    assert up_len_sq == pytest.approx(1.0, abs=1e-6)


def test_yaw_rotates_forward_in_xy_plane():
    """Positive yaw (look LEFT from default +Y) turns the forward
    vector toward -X under right-handed Z-up convention. Confirms the
    yaw axis is the world up (+Z) and the rotation direction matches
    the sign convention."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    bc.yaw_rad = math.radians(90.0)
    eye, target, _ = bc.compute_camera()
    # Forward was +Y; after +90° around +Z it's -X.
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
