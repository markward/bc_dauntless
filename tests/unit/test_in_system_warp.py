"""Unit tests for ShipClass.InSystemWarp + ShipClass.StopInSystemWarp.

Stateless teleport model: each InSystemWarp call checks distance to
target and either teleports the ship to the edge of the warp radius
(returning 1) or does nothing (returning 0)."""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


def test_in_system_warp_returns_zero_for_none_target():
    """Defensive: SDK callers (Intercept.Update) gate on truthy target
    but the engine must also be safe to call with None."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    assert ship.InSystemWarp(None, 100.0) == 0
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_returns_zero_when_already_inside_radius():
    """Ship 50 units from target, warp distance 100 → no-op."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 50.0, 0.0)
    assert ship.InSystemWarp(target, 100.0) == 0
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_returns_zero_when_exactly_at_radius():
    """distance == fDistance → no teleport. Boundary check."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 100.0, 0.0)
    assert ship.InSystemWarp(target, 100.0) == 0
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_far_call_teleports_to_radius_edge():
    """Ship 1000 from target, warp distance 295 → ship ends up at
    (target - unit_dir * 295) = (0, 705, 0)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 1
    p = ship.GetTranslate()
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(705.0)
    assert p.z == pytest.approx(0.0)


def test_in_system_warp_far_call_works_diagonally():
    """Ship at origin, target at (300, 400, 0) → distance 500.
    With fDistance=100, unit dir = (0.6, 0.8, 0), arrival =
    target - unit * 100 = (300 - 60, 400 - 80, 0) = (240, 320, 0)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(300.0, 400.0, 0.0)
    assert ship.InSystemWarp(target, 100.0) == 1
    p = ship.GetTranslate()
    assert p.x == pytest.approx(240.0)
    assert p.y == pytest.approx(320.0)
    assert p.z == pytest.approx(0.0, abs=1e-9)


def test_in_system_warp_preserves_current_speed():
    """The teleport changes position only; _current_speed is left
    intact. The integrator's setpoint-driven ramp on the next AI tick
    pulls the ship to whatever speed the AI body wrote — there is no
    physical reason to discard the kinematic velocity state. Earlier
    behaviour (zeroing it) caused repeated boundary crossings under
    Intercept-driven combat to clobber the acceleration ramp; see
    tests/unit/test_in_system_warp_preserves_speed.py for the full
    motivation."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship._current_speed = 80.0
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    assert ship._current_speed == 80.0


def test_in_system_warp_does_not_change_speed_when_no_teleport():
    """If the call is a no-op (ship already inside radius),
    _current_speed must be left alone — the ship is still under
    impulse control and may have a non-zero speed to preserve."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship._current_speed = 50.0
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 50.0, 0.0)  # already inside radius
    ship.InSystemWarp(target, 100.0)
    assert ship._current_speed == 50.0


def test_stop_in_system_warp_is_noop_observable():
    """In the stateless model, StopInSystemWarp has no state to clear.
    Calling it must not raise and must not change ship state."""
    ship = ShipClass()
    ship.SetTranslateXYZ(7.0, 8.0, 9.0)
    ship._current_speed = 42.0
    ship.StopInSystemWarp()
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (7.0, 8.0, 9.0)
    assert ship._current_speed == 42.0
