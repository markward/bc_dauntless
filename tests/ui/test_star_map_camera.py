"""Star map camera and picking. The anchor is FIXED — clicking selects but
never re-centres (spec §5)."""
import math

import pytest

from engine.ui import star_map as sm

RECT = (200, 80, 640, 520)   # x, y, w, h in CEF logical px


def _scene():
    return sm.build_scene(model={
        "systems": [
            {"id": "vesuvi", "position": [0.0, 0.0, 0.0], "module": "m"},
            {"id": "tevron", "position": [100.0, 0.0, 0.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    })


def test_orbit_changes_angles_but_never_the_anchor():
    cam = sm.StarMapCamera(anchor=(1.0, 2.0, 3.0))
    before_yaw = cam.camera.yaw
    cam.orbit(0.4, 0.2)
    assert cam.camera.yaw != before_yaw
    assert cam.anchor == (1.0, 2.0, 3.0)
    assert cam.camera.target == (1.0, 2.0, 3.0)


def test_zoom_changes_distance_but_never_the_anchor():
    cam = sm.StarMapCamera(anchor=(1.0, 2.0, 3.0))
    before = cam.camera.distance
    cam.zoom(-3)
    assert cam.camera.distance < before
    assert cam.anchor == (1.0, 2.0, 3.0)


def test_zoom_is_clamped():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    for _ in range(200):
        cam.zoom(-10)
    assert cam.camera.distance >= sm.MIN_DISTANCE
    for _ in range(200):
        cam.zoom(10)
    assert cam.camera.distance <= sm.MAX_DISTANCE


def test_pitch_is_clamped_to_avoid_gimbal_flip():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    for _ in range(100):
        cam.orbit(0.0, 1.0)
    assert abs(cam.camera.pitch) < math.pi / 2


def test_there_is_no_way_to_move_the_anchor():
    """Anchor-moving is deliberately ABSENT, not deferred (spec §5)."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert not hasattr(cam, "set_anchor")
    assert not hasattr(cam, "focus")
    assert not hasattr(cam, "look_at")


def test_projection_is_rect_local_not_screen_absolute():
    """The map lives in a sub-rect. Coordinates the CEF labels consume must be
    relative to that rect, or every label lands offset by the modal position."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    projected = sm.project_points(_scene(), cam, RECT)
    anchored = next(p for p in projected if p["id"] == "vesuvi")
    assert anchored["visible"] is True
    # the anchor sits at the centre of the rect, in rect-local coords
    assert anchored["x"] == pytest.approx(RECT[2] / 2.0, abs=1.0)
    assert anchored["y"] == pytest.approx(RECT[3] / 2.0, abs=1.0)


def test_pick_takes_view_pixels_and_hits_the_anchored_system():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    cx = RECT[0] + RECT[2] / 2.0
    cy = RECT[1] + RECT[3] / 2.0
    assert sm.pick_system(cx, cy, _scene(), cam, RECT) == "vesuvi"


def test_pick_misses_outside_the_radius():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert sm.pick_system(RECT[0] + 2, RECT[1] + 2, _scene(), cam, RECT) is None


def test_pick_outside_the_rect_is_always_a_miss():
    """Clicks on the chrome or the list must not select a star behind them."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert sm.pick_system(5, 5, _scene(), cam, RECT) is None
