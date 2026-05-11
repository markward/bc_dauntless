"""Unit tests for _BridgeCamera — mouse-look first-person camera anchored
at the MissionLib-pinned DBridge captain's-chair pose. Mirrors the fake-
ship pattern from tests/host/test_camera_control.py."""
import math
import pytest


def _identity_ship_at_origin():
    from engine.appc.math import TGPoint3, TGMatrix3
    return TGPoint3(0.0, 0.0, 0.0), TGMatrix3()


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


def test_camera_anchor_at_ship_origin_with_identity_ship():
    """At zero yaw/pitch, identity ship rotation, ship at origin: eye
    sits at BRIDGE_LOCAL_OFFSET in world coords (no ship rotation
    applied), and target points along the rotated base forward."""
    from engine.host_loop import _BridgeCamera
    bc = _BridgeCamera()
    ship_loc, ship_rot = _identity_ship_at_origin()
    eye, target, up = bc.compute_camera(ship_loc, ship_rot)
    ox, oy, oz = _BridgeCamera.BRIDGE_LOCAL_OFFSET
    assert eye[0] == pytest.approx(ox)
    assert eye[1] == pytest.approx(oy)
    assert eye[2] == pytest.approx(oz)
    # Target is eye + base forward × small distance; we don't pin the
    # exact direction here (that depends on the BRIDGE_BASE_PITCH_RAD
    # convention which iterates visually). What we DO pin: target is
    # not equal to eye (so the view direction is well-defined), and the
    # up vector is unit length.
    assert (eye[0], eye[1], eye[2]) != (target[0], target[1], target[2])
    up_len_sq = up[0]*up[0] + up[1]*up[1] + up[2]*up[2]
    assert up_len_sq == pytest.approx(1.0, abs=1e-6)


def test_camera_couples_to_ship_rotation():
    """Rotating the ship 90° around its Z axis (yaw RIGHT) carries the
    bridge with it. Body-Y (forward) now points world+X, so the bridge
    offset (ox, oy, oz) lands in world space at (oy, -ox, oz) — under
    BC's row-vector convention where row1 is body-forward in world."""
    from engine.host_loop import _BridgeCamera
    from engine.appc.math import TGPoint3, TGMatrix3

    bc = _BridgeCamera()
    ship_loc = TGPoint3(0.0, 0.0, 0.0)

    # Identity ship: eye at BRIDGE_LOCAL_OFFSET in world coords.
    eye_id, _, _ = bc.compute_camera(ship_loc, TGMatrix3())
    ox, oy, oz = _BridgeCamera.BRIDGE_LOCAL_OFFSET
    assert eye_id == pytest.approx((ox, oy, oz), abs=1e-4)

    # Yaw the ship +90° about world-Z (per host_loop.py docstring:
    # "+Z rotation tilts forward toward +X = yaw RIGHT").
    Z_AXIS = TGPoint3(0.0, 0.0, 1.0)
    rot90 = TGMatrix3(); rot90.MakeRotation(math.radians(90.0), Z_AXIS)
    eye_rot, _, _ = bc.compute_camera(ship_loc, rot90)

    # MakeRotation(90°, Z) rows: row0=(0,-1,0), row1=(1,0,0), row2=(0,0,1).
    # _to_world(v) = v.x*row0 + v.y*row1 + v.z*row2 (body→world via the
    # row-vector convention used elsewhere in host_loop.py). With offset
    # (0, 50, 47) → world (50, 0, 47). General form: (oy, -ox, oz).
    assert eye_rot[0] == pytest.approx( oy, abs=1e-4)
    assert eye_rot[1] == pytest.approx(-ox, abs=1e-4)
    assert eye_rot[2] == pytest.approx( oz, abs=1e-4)
    # Critical: rotated eye DIFFERS from identity-rotation eye.
    assert eye_rot != eye_id
