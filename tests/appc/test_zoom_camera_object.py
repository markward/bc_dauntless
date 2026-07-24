"""ZoomCameraObjectClass zoom-state machine (MenuEventHandler port)."""
import pytest
from engine.appc.bridge_set import ZoomCameraObjectClass


def _cam():
    # (x,y,z, qw,qx,qy,qz, name) — args mirror ZoomCameraObjectClass_Create.
    c = ZoomCameraObjectClass(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, "maincamera")
    c.SetMinZoom(0.64)
    c.SetMaxZoom(1.0)
    c.SetZoomTime(0.375)
    return c


def test_starts_disengaged():
    c = _cam()
    assert c.IsZoomed() == 0
    assert c.zoom_progress() == 0.0
    assert c.look_at is None


def test_engage_sets_factor_lookat_and_direction():
    c = _cam()
    c.engage(0.5, (1.0, 2.0, 3.0))
    assert c.IsZoomed() == 1
    assert c.active_factor == pytest.approx(0.5)
    assert c.look_at == (1.0, 2.0, 3.0)


def test_advance_eases_in_over_zoom_time_and_clamps():
    c = _cam()
    c.engage(0.5, None)
    c.advance(0.375 / 2)          # half the ease time
    assert c.zoom_progress() == pytest.approx(0.5, abs=1e-6)
    c.advance(10.0)               # overshoot clamps to 1.0
    assert c.zoom_progress() == 1.0


def test_disengage_eases_back_to_zero_and_clears_lookat():
    c = _cam()
    c.engage(0.5, (1.0, 0.0, 0.0))
    c.advance(10.0)               # fully in
    c.disengage()
    c.advance(10.0)               # fully out
    assert c.zoom_progress() == 0.0
    assert c.IsZoomed() == 0
    assert c.look_at is None      # cleared when _zoom_t hits 0


def test_mid_transition_reverse_resumes_from_current_progress():
    c = _cam()
    c.engage(0.5, None)
    c.advance(0.375 * 0.4)        # 40% in
    p = c.zoom_progress()
    c.disengage()                 # reverse mid-transition
    c.advance(0.375 * 0.1)        # step out a little
    assert c.zoom_progress() == pytest.approx(p - 0.1, abs=1e-6)  # smooth, no snap


def test_zero_zoom_time_falls_back_to_default_not_snap():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")  # never SetZoomTime
    c.engage(0.5, None)
    c.advance(0.375 / 2)          # half of the DEFAULT 0.375, not an instant snap
    assert c.zoom_progress() == pytest.approx(0.5, abs=1e-6)


def test_lookforward_clears_lookat():
    c = _cam()
    c.engage(0.5, (1.0, 2.0, 3.0))
    c.LookForward()
    assert c.look_at is None
