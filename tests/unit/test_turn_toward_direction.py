"""Unit tests for ShipClass.TurnTowardDirection.

SDK callers (AI/PlainAI/FollowObject.py:148,
AI/PlainAI/EvadeTorps.py:137, AI/PlainAI/Flee.py:142,
AI/PlainAI/MoveToObjectSide.py:182/261, AI/PlainAI/Warp.py:388,
AI/Preprocessors.py:1705) pass a world-space direction vector
(already the delta they computed, NOT a world point) and expect the
ship to set its angular-velocity setpoint to rotate world-forward
onto that direction.

Distinct from TurnTowardLocation: this entry point does NOT subtract
ship_location from the argument. Same return value semantics
(estimated seconds to align) as TurnDirectionsToDirections, used
by Flee/Warp.
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.ships import ShipClass


def test_direction_ahead_zero_angular_velocity():
    """Identity rotation (world-forward = +Y), direction +Y → zero AV."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship.TurnTowardDirection(TGPoint3(0.0, 100.0, 0.0))
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z == pytest.approx(0.0, abs=1e-9)


def test_direction_plus_x_yaws_around_minus_z():
    """World-forward (+Y) × world-target-dir (+X) = -Z → AV around -Z."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship.TurnTowardDirection(TGPoint3(100.0, 0.0, 0.0))
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(0.0, abs=1e-9)
    assert av.y == pytest.approx(0.0, abs=1e-9)
    assert av.z < 0.0
    assert abs(av.z) == pytest.approx(math.pi / 2.0, rel=1e-6)


def test_ship_position_is_ignored():
    """TurnTowardDirection takes a world-space direction; the ship's
    own position does NOT enter the calculation. Pins the contract
    distinguishing it from TurnTowardLocation."""
    a = ShipClass(); a.SetTranslateXYZ(0.0, 0.0, 0.0)
    b = ShipClass(); b.SetTranslateXYZ(1000.0, -500.0, 47.0)
    a.TurnTowardDirection(TGPoint3(1.0, 0.0, 0.0))
    b.TurnTowardDirection(TGPoint3(1.0, 0.0, 0.0))
    av_a = a.GetTargetAngularVelocitySetpoint()
    av_b = b.GetTargetAngularVelocitySetpoint()
    assert (av_a.x, av_a.y, av_a.z) == pytest.approx((av_b.x, av_b.y, av_b.z))


def test_zero_length_direction_is_noop():
    """A zero-length direction would yield NaN through Unitize; the
    method must guard. Existing setpoint is preserved."""
    ship = ShipClass(); ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    prior = TGPoint3(0.1, 0.2, 0.3)
    ship.SetTargetAngularVelocityDirect(prior)
    ship.TurnTowardDirection(TGPoint3(0.0, 0.0, 0.0))
    av = ship.GetTargetAngularVelocitySetpoint()
    assert (av.x, av.y, av.z) == pytest.approx((0.1, 0.2, 0.3))


def test_returns_eta_estimate_for_warp_and_flee_callers():
    """Warp.py:388 and Flee.py:142 capture the return value into
    fTime / fTurnTime to schedule the next AI update — the contract
    is a non-negative float."""
    ship = ShipClass(); ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    eta = ship.TurnTowardDirection(TGPoint3(1.0, 0.0, 0.0))
    assert isinstance(eta, float)
    assert eta >= 0.0


def test_uses_column_vector_forward_after_yaw():
    """Ship yawed +π/2 around Z faces world -X (column-vector
    convention). Direction (-1,0,0) is already ahead → zero AV.
    Pins that TurnTowardDirection reads forward via GetCol(1), not
    GetRow(1) — same invariant guarded for TurnTowardLocation."""
    ship = ShipClass(); ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    ship.SetMatrixRotation(R)
    ship.TurnTowardDirection(TGPoint3(-100.0, 0.0, 0.0))
    av = ship.GetTargetAngularVelocitySetpoint()
    assert av.x == pytest.approx(0.0, abs=1e-6)
    assert av.y == pytest.approx(0.0, abs=1e-6)
    assert av.z == pytest.approx(0.0, abs=1e-6)
