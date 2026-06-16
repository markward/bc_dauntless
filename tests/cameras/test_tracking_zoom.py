"""Unit tests for _TrackingCamera sticky zoom + ZoomTarget toggles.
See docs/superpowers/specs/2026-06-04-tracking-zoom-and-zoom-target-design.md §4."""
import math
import pytest


def _seeded_camera(radius=1.0):
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    tc.set_ship_radius(radius)
    return tc


def test_zoom_in_in_tracking_decreases_d_chase_tracking():
    tc = _seeded_camera()
    seed = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    tc.zoom_in()
    assert tc.d_chase_tracking == pytest.approx(seed * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.d_chase_zoom == pytest.approx(seed_zoom)  # unchanged


def test_zoom_in_in_zoom_target_decreases_d_chase_zoom():
    tc = _seeded_camera()
    # Pre-zoom-out so d_chase_zoom > zoom_min and the press is effective.
    tc.zoom_target_active = True
    tc.d_chase_zoom = tc.zoom_min * 2.0
    seed_tracking = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    tc.zoom_in()
    assert tc.d_chase_zoom == pytest.approx(seed_zoom * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)  # unchanged


def test_zoom_in_clamps_at_zoom_min():
    """zoom_in must never push d_chase_zoom below zoom_min: once at the
    floor, a further = press is a no-op (matches BC behaviour).

    Note: set_ship_radius now seeds d_chase_zoom 5 zoom-out clicks above
    zoom_min (ZOOM_DEFAULT_RADII), so this test drives it to the floor
    explicitly before exercising the clamp."""
    tc = _seeded_camera()
    tc.zoom_target_active = True
    tc.d_chase_zoom = tc.zoom_min  # drive to the floor
    assert tc.d_chase_zoom == pytest.approx(tc.zoom_min)
    tc.zoom_in()
    assert tc.d_chase_zoom == pytest.approx(tc.zoom_min)  # still at floor


def test_zoom_out_clamps_at_zoom_max():
    tc = _seeded_camera()
    tc.d_chase_tracking = tc.zoom_max
    tc.zoom_out()
    assert tc.d_chase_tracking == pytest.approx(tc.zoom_max)  # still at ceiling


def test_zoom_round_trip_returns_to_original():
    tc = _seeded_camera()
    seed = tc.d_chase_tracking
    tc.zoom_in()
    tc.zoom_out()
    assert tc.d_chase_tracking == pytest.approx(seed, abs=1e-9)


def test_zoom_persists_across_enter_exit_zoom_target():
    tc = _seeded_camera()
    # Zoom in once in tracking.
    tc.zoom_in()
    after_zoom = tc.d_chase_tracking
    # Enter and exit ZoomTarget — d_chase_tracking must be preserved.
    tc.enter_zoom_target()
    tc.exit_zoom_target()
    assert tc.d_chase_tracking == pytest.approx(after_zoom)


def test_enter_exit_zoom_target_toggles_flag():
    tc = _seeded_camera()
    assert tc.zoom_target_active is False
    tc.enter_zoom_target()
    assert tc.zoom_target_active is True
    tc.exit_zoom_target()
    assert tc.zoom_target_active is False


def test_snap_resets_zoom_state():
    tc = _seeded_camera()
    seed_tracking = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    # Mutate everything.
    tc.zoom_in()                  # d_chase_tracking down
    tc.zoom_target_active = True
    tc.d_chase_zoom = tc.zoom_max # d_chase_zoom up
    # Snap.
    tc.snap()
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)
    assert tc.d_chase_zoom == pytest.approx(seed_zoom)
    assert tc.zoom_target_active is False
    # Spring state also cleared (existing snap behaviour).
    assert tc._smoothed_eye is None
    assert tc._smoothed_basis is None
