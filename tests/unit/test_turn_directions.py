"""Unit tests for ShipClass.TurnDirectionsToDirections.

The method computes an angular velocity that rotates primary_from
toward primary_to and (optionally) secondary_from toward secondary_to
around the primary axis, then writes the result via
SetTargetAngularVelocityDirect."""
import math

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem


def _make_ship():
    return ShipClass()


def test_aligned_inputs_zero_angular_velocity():
    """When primary_from already equals primary_to, the solver should
    drive angular velocity to zero."""
    ship = _make_ship()
    v = TGPoint3(0.0, 1.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(v, v, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)


def test_ninety_degree_turn_angular_velocity_around_expected_axis():
    """primary_from=+Y, primary_to=+X: rotation is 90° around -Z.
    Without IES clamp, the solver returns the gap-derived angular vel
    aligned with the cross product +Y × +X = -Z."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(1.0, 0.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    # Magnitude should be > 0 along Z (negative) and ~0 elsewhere.
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z < 0.0
    assert abs(av.z) == pytest.approx(math.pi / 2.0, rel=1e-6)


def test_one_eighty_degree_picks_perpendicular_axis():
    """primary_from=+Y, primary_to=-Y: cross product is zero, but
    the solver must still produce a non-zero angular velocity to
    flip the orientation. Falls back to an arbitrary perpendicular
    axis (cross with world up = +Z gives +X)."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, -1.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    mag = (av.x * av.x + av.y * av.y + av.z * av.z) ** 0.5
    assert mag > 1.0  # well above zero — flipping a full 180°


def test_secondary_constraint_adds_roll():
    """primary already aligned (+Y onto +Y) but secondary needs
    rotation around the primary axis: +Z secondary, +X target →
    angular velocity around primary axis +Y is non-zero."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, 1.0, 0.0)
    sf = TGPoint3(0.0, 0.0, 1.0)  # current "up" is +Z
    st = TGPoint3(1.0, 0.0, 0.0)  # desired "up" is +X (roll 90° around Y)
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    # Roll lives on the primary axis (+Y). |y| should dominate.
    assert abs(av.y) > 0.5
    assert abs(av.x) < 1e-6
    assert abs(av.z) < 1e-6


def test_clamp_to_max_angular_velocity():
    """If the ship has an ImpulseEngineSubsystem with a small
    MaxAngularVelocity, the per-axis magnitude must be clamped to
    that value."""
    ship = _make_ship()
    # Fresh ShipClass() has no IES slot — attach one so the clamp
    # branch can read MaxAngularVelocity. Mirrors test_player's
    # SetImpulseEngineSubsystem(ImpulseEngineSubsystem(...)) pattern.
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ies = ship.GetImpulseEngineSubsystem()
    # Populate so the clamp branch fires.
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(1.0)
    ies.SetMaxSpeed(100.0)  # non-zero so _max_accel branch is taken
    ies.SetMaxAccel(10.0)

    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(1.0, 0.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)
    av = ship.GetTargetAngularVelocitySetpoint()
    assert abs(av.x) <= 0.5 + 1e-9
    assert abs(av.y) <= 0.5 + 1e-9
    assert abs(av.z) <= 0.5 + 1e-9


def test_secondary_from_collinear_with_primary_target_adds_no_roll():
    """A secondary vector collinear with primary_to carries no roll information,
    and must contribute none.

    Projecting secondary_from onto the plane perpendicular to primary_to
    collapses to the zero vector in that case. Unitize() leaves a zero vector
    unchanged (math.py:98-108), so the dot product is 0.0 and acos(0) used to
    inject a spurious π/2 roll about primary_to — a phantom quarter turn that
    also doubled the returned ETA.

    Reached for real by TurnTowardDifference (ManeuverLoop): a 90° pitch makes
    the ship's current up exactly antiparallel to the commanded forward. The
    live symptom was a loop maneuver that yawed out of its own turn plane —
    observed as a first setpoint of (-0.280, 0.000, -0.280), pitch and yaw at
    once, where only pitch was commanded."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)   # current forward
    pt = TGPoint3(0.0, 0.0, -1.0)  # 90° pitch down
    sf = TGPoint3(0.0, 0.0, 1.0)   # current up — antiparallel to pt
    st = TGPoint3(0.0, 1.0, 0.0)   # up after that pitch
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    # Pure rotation about pf × pt = -X, magnitude π/2, nothing along pt.
    assert av.x == pytest.approx(-math.pi / 2.0, rel=1e-6)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)


def test_secondary_to_collinear_with_primary_target_adds_no_roll():
    """The same collapse on the other projection — secondary_to collinear with
    primary_to. Both projections are taken, so either can degenerate alone."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, 0.0, -1.0)
    sf = TGPoint3(1.0, 0.0, 0.0)   # projects fine
    st = TGPoint3(0.0, 0.0, -1.0)  # collinear with pt — collapses
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(-math.pi / 2.0, rel=1e-6)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)


def test_secondary_both_zero_is_noop_for_secondary():
    """When secondary_from or secondary_to is the zero vector, the
    secondary constraint is skipped entirely (mirrors the SDK guard
    in TurnToOrientation.Update where vSecondaryWorld defaults to
    (0,0,0) when no secondary direction is configured)."""
    ship = _make_ship()
    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(0.0, 1.0, 0.0)  # already aligned
    sf = TGPoint3(0.0, 0.0, 0.0)  # zero — skip secondary
    st = TGPoint3(1.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, sf, st)
    av = ship.GetTargetAngularVelocitySetpoint()
    # No primary correction, no secondary applied — all zero.
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)
