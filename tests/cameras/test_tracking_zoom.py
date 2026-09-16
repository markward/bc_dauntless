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
    seed_zoom = tc.zoom_target_radii
    tc.zoom_in()
    assert tc.d_chase_tracking == pytest.approx(seed * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.zoom_target_radii == pytest.approx(seed_zoom)  # unchanged


def test_zoom_in_in_zoom_target_decreases_zoom_target_radii():
    tc = _seeded_camera()
    # Pre-zoom-out so zoom_target_radii > the floor and the press is effective.
    tc.zoom_target_active = True
    tc.zoom_target_radii = tc.ZOOM_TARGET_MIN_RADII * 2.0
    seed_tracking = tc.d_chase_tracking
    seed_zoom = tc.zoom_target_radii
    tc.zoom_in()
    assert tc.zoom_target_radii == pytest.approx(seed_zoom * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)  # unchanged


def test_zoom_target_seeds_at_bc_shipped_distance_and_bounds():
    """CameraModes.ZoomTarget authors MinimumDistance 4.0 / Distance 4.0 /
    MaximumDistance 20.0 — multiples of the TARGET's radius (Min/Max are
    read only in the Zoom slot, FUN_0041F920). The default sits ON the
    floor, so a zoom-in from the seed is a no-op and only zoom-out does
    anything."""
    tc = _seeded_camera()
    assert tc.zoom_target_radii == pytest.approx(4.0)
    assert tc.ZOOM_TARGET_MIN_RADII == pytest.approx(4.0)
    assert tc.ZOOM_TARGET_MAX_RADII == pytest.approx(20.0)
    tc.zoom_target_active = True
    tc.zoom_in()
    assert tc.zoom_target_radii == pytest.approx(4.0)     # already at the floor
    tc.zoom_out()
    assert tc.zoom_target_radii == pytest.approx(4.0 / tc.ZOOM_FACTOR_PER_PRESS)


def test_zoom_out_in_zoom_target_clamps_at_max_radii():
    tc = _seeded_camera()
    tc.zoom_target_active = True
    for _ in range(200):
        tc.zoom_out()
    assert tc.zoom_target_radii == pytest.approx(tc.ZOOM_TARGET_MAX_RADII)


def test_zoom_target_radii_is_independent_of_the_players_radius():
    """The ZoomTarget distance is a multiple of the target's radius, read
    live at compute time — re-seeding the PLAYER's radius must not touch
    it. (Before: d_chase_zoom was ~2.1 x r_player, so a shuttle zooming on a
    starbase sat inside the station.)"""
    a = _seeded_camera(radius=0.3)
    b = _seeded_camera(radius=30.0)
    assert a.zoom_target_radii == pytest.approx(b.zoom_target_radii)


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
    seed_zoom = tc.zoom_target_radii
    # Mutate everything.
    tc.zoom_in()                  # d_chase_tracking down
    tc.zoom_target_active = True
    tc.zoom_target_radii = tc.ZOOM_TARGET_MAX_RADII  # zoomed all the way out
    # Snap.
    tc.snap()
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)
    assert tc.zoom_target_radii == pytest.approx(seed_zoom)
    assert tc.zoom_target_active is False
    # Spring state also cleared (existing snap behaviour).
    assert tc._smoothed_eye is None
    assert tc._smoothed_basis is None
