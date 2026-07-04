"""InSystemWarp must not disturb the integrator's _current_speed.

The warp is "instant transit" — semantically the ship crossed a long
distance, not "the ship came to a halt." The integrator ramps toward the
speed setpoint anyway, so any leftover velocity gets re-shaped by SetSpeed
on the next AI tick.

Why this matters: Intercept.Update calls InSystemWarp every tick when
fMaximumSpeed == 1e20 (BasicAttack's default). With ships rotating,
Intercept-driven ships often drift millimetres past the warp threshold,
retriggering InSystemWarp every few ticks. Each call that zeroed
_current_speed reset the acceleration ramp from 1.5 GU/s² * 0.0167s =
0.025 GU/s back to zero — so ships never reached more than ~2 GU/s, far
below their 6.3 GU/s MaxSpeed, and they never got within the 200 GU
MidRange where FireScript dispatches phasers.

The once-per-cycle convergence latch (`_warp_consumed`, set on ARRIVAL in
the multi-frame transit model) keeps re-calls after the warp from
re-warping the ship even when the target switches or the boundary drifts.
"""
from engine.appc.ships import ShipClass
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.subsystems import ImpulseEngineSubsystem

_DT = 1.0 / 60.0


def _make_ship(x: float, y: float, z: float) -> ShipClass:
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    s._impulse_engine_subsystem = ies
    return s


def _fly_transit_to_completion(ship, max_ticks=2000):
    for _ in range(max_ticks):
        if ship._insystem_warp_transit is None:
            return
        _step_ship_motion(ship, _DT)
    raise AssertionError("warp transit never completed")


def test_in_system_warp_preserves_current_speed():
    """The transit changes position, not velocity state. A ship moving at
    4 GU/s before the warp is still at 4 GU/s after arrival."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    ship._current_speed = 4.0
    warped = ship.InSystemWarp(target, 295.0)
    assert warped == 1, "ship should have engaged — distance 1000 > 295, facing +Y"
    _fly_transit_to_completion(ship)
    assert ship._current_speed == 4.0, (
        f"InSystemWarp should not reset _current_speed; got {ship._current_speed}"
    )


def test_in_system_warp_no_op_within_distance():
    """When already within warp distance, no transit and speed is
    untouched."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 100.0, 0.0)  # within 295
    ship._current_speed = 2.0
    warped = ship.InSystemWarp(target, 295.0)
    assert warped == 0
    assert ship._current_speed == 2.0
    # Position unchanged
    loc = ship.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == (0.0, 0.0, 0.0)


def test_in_system_warp_does_not_re_trigger_after_arrival():
    """One warp per StopInSystemWarp cycle: after the transit completes,
    re-calls return 0 so the AI proceeds with normal motion — even when
    the rotating ship drifts past the threshold or the target switches.
    (During the transit itself, re-calls return 1 — SDK bWarping.)"""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    first = ship.InSystemWarp(target, 295.0)
    assert first == 1, "first call should engage the transit"
    _fly_transit_to_completion(ship)
    target.SetTranslateXYZ(0.0, 2000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 0, "same target re-call: no re-warp"
    # A different target with the same threshold also shouldn't retrigger.
    other = _make_ship(0.0, -1500.0, 0.0)
    assert ship.InSystemWarp(other, 295.0) == 0, "target switch: still no re-warp"


def test_stop_in_system_warp_re_enables_warping():
    """LostFocus → StopInSystemWarp re-enables warping (a fresh transit
    can engage)."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    _fly_transit_to_completion(ship)
    ship.StopInSystemWarp()
    target.SetTranslateXYZ(0.0, 2000.0, 0.0)
    third = ship.InSystemWarp(target, 295.0)
    assert third == 1, "after StopInSystemWarp, a new warp can fire"
