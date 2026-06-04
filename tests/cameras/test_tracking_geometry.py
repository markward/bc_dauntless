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
