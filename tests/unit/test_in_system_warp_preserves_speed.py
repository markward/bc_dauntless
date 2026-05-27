"""InSystemWarp should not zero the integrator's _current_speed.

The teleport is "instantaneous transit" — semantically the ship just
crossed a long distance, not "the ship came to a halt." The integrator
ramps toward the speed setpoint anyway, so any leftover velocity gets
re-shaped by SetSpeed on the next AI tick.

Why this matters: Intercept.Update calls InSystemWarp every tick when
fMaximumSpeed == 1e20 (BasicAttack's default). With ships rotating
(Slice H), Intercept-driven ships often drift millimetres past the
warp threshold, retriggering InSystemWarp every few ticks. Each call
that zeroed _current_speed reset the acceleration ramp from 1.5 m/s²
* 0.0167s = 0.025 m/s back to zero — so ships never reached more than
~2 m/s, far below their 6.3 m/s MaxSpeed, and they never got within
the 200 m MidRange where FireScript dispatches phasers.

Live-game symptom (reported by the user after Slices G/H/I/J): "still
no firing." The diagnostic test
tests/integration/test_m2objects_live_path.py reproduced this in
headless — ships stayed ~295 m apart for the full 15 s of ticking,
distance barely changing despite a setpoint of 6.3 m/s.
"""
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem


def _make_ship(x: float, y: float, z: float) -> ShipClass:
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    s._impulse_engine_subsystem = ies
    return s


def test_in_system_warp_preserves_current_speed():
    """The teleport changes position, not velocity state. Tests that
    a ship moving at 4 m/s before the warp is still at 4 m/s after."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    ship._current_speed = 4.0
    warped = ship.InSystemWarp(target, 295.0)
    assert warped == 1, "ship should have warped — initial distance 1000 > 295"
    assert ship._current_speed == 4.0, (
        f"InSystemWarp should not reset _current_speed; got {ship._current_speed}"
    )


def test_in_system_warp_no_op_within_distance():
    """When already within warp distance, no teleport and speed is
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


def test_in_system_warp_does_not_re_trigger_after_first_warp():
    """SDK semantics: InSystemWarp begins a multi-tick warp transition;
    subsequent calls return 0 so the AI proceeds with normal motion
    until StopInSystemWarp fires. Our stateless teleport converges to
    that by short-circuiting after the first call.

    Without this convergence Intercept.Update (called every 0.4 s on
    most ships) re-warps whenever the rotating ship drifts a few
    metres past the warp threshold or the target switches — clobbering
    the AI body's intercept motion. See M2Objects live-path diagnostic
    where ships orbited at ~290 m, never closing into firing range."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    first = ship.InSystemWarp(target, 295.0)
    assert first == 1, "first call should teleport"
    target.SetTranslateXYZ(0.0, 2000.0, 0.0)
    assert ship.InSystemWarp(target, 295.0) == 0, "same target re-call: no re-warp"
    # A different target with the same threshold also shouldn't retrigger.
    other = _make_ship(0.0, -1500.0, 0.0)
    assert ship.InSystemWarp(other, 295.0) == 0, "target switch: still no re-warp"


def test_stop_in_system_warp_re_enables_warping():
    """LostFocus → StopInSystemWarp re-enables warping (SDK's
    multi-tick warp begins fresh)."""
    ship = _make_ship(0.0, 0.0, 0.0)
    target = _make_ship(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    ship.StopInSystemWarp()
    target.SetTranslateXYZ(0.0, 2000.0, 0.0)
    third = ship.InSystemWarp(target, 295.0)
    assert third == 1, "after StopInSystemWarp, a new warp can fire"
