"""Unit tests for the CEF OSR resize-decision helper.

The helper decides whether the windowless CEF browser must be re-sized to
track the host window, and to what logical size + device-scale-factor. CEF
lays out HTML/CSS in *logical* pixels (window points) and rasterises at
logical x dsf device pixels; keeping the overlay 1:1 with the framebuffer
(no stretch, DPI-correct) means logical == window-points and dsf ==
framebuffer/window. See engine/host_loop.py:_compute_cef_resize.
"""

from engine.host_loop import _compute_cef_resize


def test_no_change_returns_none():
    # Startup non-Retina state: view already matches the window, dsf 1.0.
    assert _compute_cef_resize(1280, 720, 1280, 720, 1280, 720, 1.0) is None


def test_no_change_retina_returns_none():
    # Retina: framebuffer is 2x the window points, dsf 2.0, view matches.
    assert _compute_cef_resize(2560, 1440, 1280, 720, 1280, 720, 2.0) is None


def test_grow_window_reports_new_logical_size():
    # Window grew to 1600x900 points (non-Retina). New logical view must be
    # the window *points*, not the framebuffer pixels, else the UI re-stretches.
    out = _compute_cef_resize(1600, 900, 1600, 900, 1280, 720, 1.0)
    assert out == (1600, 900, 1.0)


def test_grow_window_retina_uses_points_not_pixels():
    # Retina window grown to 1600x900 points => framebuffer 3200x1800.
    # Logical view stays in points (1600x900); dsf stays 2.0.
    out = _compute_cef_resize(3200, 1800, 1600, 900, 1280, 720, 2.0)
    assert out == (1600, 900, 2.0)


def test_dpi_change_only_triggers_resize():
    # Window dragged to a different-DPI monitor: same point size, new dsf.
    out = _compute_cef_resize(1280, 720, 1280, 720, 1280, 720, 2.0)
    assert out == (1280, 720, 1.0)


def test_zero_window_size_is_ignored():
    # Minimised / zero-size window must not produce a degenerate resize.
    assert _compute_cef_resize(0, 0, 0, 0, 1280, 720, 1.0) is None
