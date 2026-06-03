"""SetImpulse semantics: the SDK convention is that the first
argument is a *fraction of max speed* (0.0..1.0), while SetSpeed
takes an absolute GU/s value (BC's internal unit; see engine.units).

Evidence:
* sdk/.../AI/PlainAI/Flee.py:38 — ``def SetSpeed(self, fSpeedFraction = 1.0)``
* sdk/.../AI/PlainAI/PhaserSweep.py:92 — ``def SetSpeedFraction(...)`` ⇒ SetImpulse
* sdk/.../AI/PlainAI/FollowObject.py:67 — ``fGoFastSpeed = 1.0`` then
  ``pShip.SetImpulse(fVel, ...)``
* sdk/.../AI/PlainAI/CircleObject.py:57 — ``SetCircleSpeed(fSpeed = 1.0)``;
  this fSpeed is used as ``fFastSpeed`` and multiplied by fuzzy weights
  in [0,1] before passing through SetImpulse.
* sdk/.../AI/PlainAI/Intercept.py:243 — ``fSpeed = fMaxSpeed`` then
  ``pShip.SetSpeed(fSpeed, ...)``; the literal GU/s path.
* engine/host_loop.py:651 — _PlayerControl converts impulse_level
  to absolute GU/s via ``(impulse_level / 9) * max_speed`` and writes
  it as the player's _current_speed directly (no setpoint).

Before this fix our engine aliased SetImpulse to SetSpeed, storing
the fraction as if it were GU/s. NonFedAttack's FollowObject body
therefore moved enemy ships at ~1 GU/s instead of ~6 GU/s (Galaxy's
hardpoint MaxSpeed), making them feel stationary in-game.

Contract:
* When the ship has an IES with MaxSpeed > 0, SetImpulse multiplies
  by MaxSpeed before storing the setpoint.
* When the ship has no IES (or MaxSpeed == 0), SetImpulse stores
  the value as-is. This preserves the headless-test fallback used
  by tests that don't populate an IES.
* SetSpeed is unchanged in all cases.
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem


def _fwd():
    return TGPoint3(0.0, 1.0, 0.0)


MODEL_SPACE = App.PhysicsObjectClass.DIRECTION_MODEL_SPACE


def test_set_impulse_full_throttle_scales_to_max_speed():
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)  # Galaxy hardpoint
    ship._impulse_engine_subsystem = ies

    ship.SetImpulse(1.0, _fwd(), MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(6.3)


def test_set_impulse_partial_throttle_scales_proportionally():
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ship._impulse_engine_subsystem = ies

    ship.SetImpulse(0.4, _fwd(), MODEL_SPACE)  # fGoMedSpeed default
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(6.3 * 0.4)


def test_set_impulse_negative_fraction_reverses():
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ship._impulse_engine_subsystem = ies

    ship.SetImpulse(-0.5, _fwd(), MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(-3.15)


def test_set_impulse_without_ies_treats_value_as_literal():
    """Test fallback: no IES (or MaxSpeed == 0) ⇒ value is stored as-is.
    This preserves backwards compatibility with the many ship_motion
    tests that construct bare ShipClass instances without an IES and
    pass literal GU/s values to SetImpulse."""
    ship = ShipClass()
    ship.SetImpulse(50.0, _fwd(), MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(50.0)


def test_set_impulse_with_zero_max_speed_ies_treats_value_as_literal():
    """IES populated but MaxSpeed never set (== 0). Same fallback as no
    IES — guards against accidental zero-division and matches the
    pattern used in _PlayerControl._max_accel."""
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("IES")  # no SetMaxSpeed call
    ship._impulse_engine_subsystem = ies
    ship.SetImpulse(42.0, _fwd(), MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(42.0)


def test_set_speed_is_always_literal():
    """SetSpeed must NOT scale by max speed regardless of IES — SDK
    Intercept.py passes the literal max_speed value through SetSpeed."""
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ship._impulse_engine_subsystem = ies

    ship.SetSpeed(50.0, _fwd(), MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == pytest.approx(50.0)
