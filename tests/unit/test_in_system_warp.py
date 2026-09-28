"""Unit tests for ShipClass.InSystemWarp + ShipClass.StopInSystemWarp.

Multi-frame transit model: InSystemWarp engages a warp only when the ship is
beyond the drop distance AND its nose is on the target
(IN_SYSTEM_WARP_FACING_COS); the ship then cruises toward
(target − unit_dir · distance) at IN_SYSTEM_WARP_SPEED_GUPS (BC's fixed 75),
advanced per tick by warp_flight.step (from ship_motion) — never a same-tick
teleport. While the transit runs InSystemWarp returns 1 (SDK bWarping);
on arrival `_warp_consumed` latches (one warp per StopInSystemWarp cycle).
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.ship_motion import _step_ship_motion

_DT = 1.0 / 60.0


def _step_until_done(ship, max_ticks=200_000):
    """Advance the motion integrator until the transit ends."""
    for _ in range(max_ticks):
        if ship._insystem_warp_transit is None:
            return
        _step_ship_motion(ship, _DT)
    raise AssertionError("warp transit never completed")


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
    """distance == fDistance → no warp. Boundary check."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 100.0, 0.0)
    assert ship.InSystemWarp(target, 100.0) == 0
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_requires_facing_target():
    """The nose must be on the target before the warp engages (BC ships
    visibly turn, then jump). Identity rotation faces +Y; a target at
    (300, 400, 0) is 53° off (dot 0.8 < 0.985) → no engage, no motion."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(300.0, 400.0, 0.0)
    assert ship.InSystemWarp(target, 100.0) == 0
    assert ship._insystem_warp_transit is None
    assert ship.IsDoingInSystemWarp() == 0
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_engages_transit_not_teleport():
    """Facing + far → engage: returns 1, reports IsDoingInSystemWarp,
    but the ship has NOT moved yet — the integrator flies the transit."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)   # dead ahead (+Y)
    assert ship.InSystemWarp(target, 295.0) == 1
    assert ship.IsDoingInSystemWarp() == 1
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_transit_arrives_at_radius_edge():
    """Stepping the integrator lands the ship exactly on the drop edge
    (0, 705, 0) and ends the transit."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 1
    _step_until_done(ship)
    p = ship.GetTranslate()
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(705.0)
    assert p.z == pytest.approx(0.0)
    assert ship.IsDoingInSystemWarp() == 0


def test_in_system_warp_transit_takes_multiple_ticks():
    """The cruise is finite-speed: every ship flies at BC's fixed 75 GU/s,
    so 705 GU takes several ticks — after one
    tick the ship must NOT yet be at the drop edge, and the mid-transit
    velocity must be published (camera smear / SPEED read it)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    _step_ship_motion(ship, _DT)
    p = ship.GetTranslate()
    assert 0.0 < p.y < 705.0
    assert ship.IsDoingInSystemWarp() == 1
    v = ship.GetVelocity()
    assert v.y == pytest.approx(75.0)


def test_in_system_warp_mid_transit_recall_reports_warping():
    """SDK bWarping semantics: while the transit runs, Intercept re-calls
    InSystemWarp every AI tick and must see 1 (it then skips its normal
    speed control) without re-engaging a second warp."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 1
    _step_ship_motion(ship, _DT)
    transit = ship._insystem_warp_transit
    assert ship.InSystemWarp(target, 295.0) == 1
    assert ship._insystem_warp_transit is transit   # same transit object


def test_in_system_warp_preserves_current_speed():
    """Engaging and flying the transit changes position only;
    _current_speed (the impulse integrator state) is left intact so the
    AI's normal setpoint ramp resumes seamlessly on arrival."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship._current_speed = 80.0
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    _step_until_done(ship)
    assert ship._current_speed == 80.0
    # Arrival velocity drops back to the pre-warp impulse speed along
    # the approach line — not the warp cruise speed.
    v = ship.GetVelocity()
    assert v.y == pytest.approx(80.0)


def test_in_system_warp_does_not_change_speed_when_no_engage():
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


def test_stop_in_system_warp_aborts_transit():
    """StopInSystemWarp (SDK Intercept.LostFocus) cancels an in-flight
    transit: the ship stops where it is and IsDoingInSystemWarp drops."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    _step_ship_motion(ship, _DT)
    mid = ship.GetTranslate()
    mid_y = mid.y
    ship.StopInSystemWarp()
    assert ship.IsDoingInSystemWarp() == 0
    _step_ship_motion(ship, _DT)      # no transit → no warp motion
    p = ship.GetTranslate()
    assert p.y == pytest.approx(mid_y)


def test_set_ai_aborts_transit():
    """A change of orders aborts the warp — the transit belongs to the AI
    that requested it (All Stop mid-warp must not keep flying it)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    ship.SetAI(object())
    assert ship._insystem_warp_transit is None
    ship.InSystemWarp(target, 295.0)
    ship.ClearAI()
    assert ship._insystem_warp_transit is None


@pytest.mark.parametrize("authored_max", [None, 3.7, 6.3, 20.0])
def test_in_system_warp_cruises_at_bcs_fixed_75_gups(authored_max):
    """BC's in-system warp is one fixed speed for every ship: measured 74.95
    GU/s on a Galaxy (MaxSpeed 6.3) and 74.92 on a Kessok Heavy (3.7) in
    stbc-oracle's warp_* captures (bible 7.3). Never scaled by the ship's
    impulse -- so a slow ship's intercept is not slower, and in-system warp
    stays well under the ~470 GU/s where a flash would read as warp."""
    ship = ShipClass()
    if authored_max is not None:
        from engine.appc.subsystems import ImpulseEngineSubsystem
        ies = ImpulseEngineSubsystem("Impulse Engines")
        ies._max_speed = authored_max
        ship.SetImpulseEngineSubsystem(ies)
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass()
    target.SetTranslateXYZ(0.0, 5000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 1
    _step_ship_motion(ship, _DT)
    assert ship.GetVelocity().y == pytest.approx(75.0)
