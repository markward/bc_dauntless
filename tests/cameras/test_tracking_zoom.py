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
    seed_zoom = tc.zoom_target_scale
    tc.zoom_in()
    assert tc.d_chase_tracking == pytest.approx(seed * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.zoom_target_scale == pytest.approx(seed_zoom)  # unchanged


def test_zoom_in_in_zoom_target_decreases_zoom_target_scale():
    tc = _seeded_camera()
    tc.zoom_target_active = True
    tc.zoom_target_scale = 2.0
    seed_tracking = tc.d_chase_tracking
    tc.zoom_in()
    # ZoomTarget keeps CameraObjectClass.Zoom's x0.875 step.
    assert tc.zoom_target_scale == pytest.approx(2.0 * 0.875)
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)  # unchanged


def test_zoom_target_scale_seeds_at_the_fit_and_zoom_in_is_a_noop():
    """The scale multiplies the fit distance: 1.0 IS the fit, which is also
    the floor, so a zoom-in from the seed does nothing."""
    tc = _seeded_camera()
    assert tc.zoom_target_scale == pytest.approx(1.0)
    assert tc.ZOOM_TARGET_SCALE_DEFAULT == pytest.approx(1.0)
    assert tc.ZOOM_TARGET_SCALE_MIN == pytest.approx(1.0)
    assert tc.ZOOM_TARGET_SCALE_MAX == pytest.approx(5.0)
    tc.zoom_target_active = True
    tc.zoom_in()
    assert tc.zoom_target_scale == pytest.approx(1.0)
    tc.zoom_out()
    assert tc.zoom_target_scale == pytest.approx(1.125)
    tc.zoom_out()
    assert tc.zoom_target_scale == pytest.approx(1.125 ** 2)


def test_zoom_out_in_zoom_target_clamps_at_max_scale():
    tc = _seeded_camera()
    tc.zoom_target_active = True
    for _ in range(200):
        tc.zoom_out()
    assert tc.zoom_target_scale == pytest.approx(5.0)


def test_zoom_target_scale_is_independent_of_the_players_radius():
    a = _seeded_camera(radius=0.3)
    b = _seeded_camera(radius=30.0)
    assert a.zoom_target_scale == pytest.approx(b.zoom_target_scale)


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
    seed_zoom = tc.zoom_target_scale
    # Mutate everything.
    tc.zoom_in()                  # d_chase_tracking down
    tc.zoom_target_active = True
    tc.zoom_target_scale = tc.ZOOM_TARGET_SCALE_MAX  # zoomed all the way out
    # Snap.
    tc.snap()
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)
    assert tc.zoom_target_scale == pytest.approx(seed_zoom)
    assert tc.zoom_target_active is False
    # Spring state also cleared (existing snap behaviour).
    assert tc._smoothed_eye is None
    assert tc._smoothed_basis is None
