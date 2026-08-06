"""ShipClass.TurnTowardDifference must command a world-space rotation *delta*.

The last missing member of the TurnToward* family. Its sole SDK caller is
AI/PlainAI/ManeuverLoop.py:126, the script module behind AI/Player/Defense,
AI/Player/DefenseNoTarget, QuickBattle/QuickBattleAI, AI/Compound/Parts/
NoSensorsEvasive and E3M1/KlingonManeuverAI.

Argument shape (ManeuverLoop.py:121-124): the turn axis is taken in MODEL space,
pushed to world with MultMatrixLeft(GetWorldRotation()), then Scale()d by the
radians still to turn — i.e. a world-frame axis·angle (rotation) vector, not a
heading like TurnTowardDirection takes. Return value (ManeuverLoop.py:126-130):
seconds to complete that turn; the caller halves it to schedule its next update.

Stubbed, it degraded silently: the ship never rotated, so ManeuverLoop's
observed-rotation accumulator never advanced, fTurnLeft never dropped below its
threshold, and Update returned US_ACTIVE forever (see the integration companion
tests/integration/test_maneuver_loop_smoke.py). docs/stub_heatmap.md ranked it
at 1,173 hits.
"""
import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem

_DT = 1.0 / 60.0


def _galaxy_ship():
    """Galaxy-class turn envelope, matching test_turn_toward_orientation.py."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def test_pitch_delta_writes_setpoint_about_the_commanded_axis():
    """A delta about world +X on an identity-attitude ship must write a body
    setpoint about +X (body frame == world frame at identity)."""
    ship = _galaxy_ship()

    eta = ship.TurnTowardDifference(TGPoint3(0.4, 0.0, 0.0))

    sp = ship.GetTargetAngularVelocitySetpoint()
    assert sp is not None, "no setpoint written — TurnTowardDifference is a no-op"
    assert sp.x > 0.0, f"wrong sign about the commanded axis: {sp.x}"
    assert abs(sp.y) < 1e-6 and abs(sp.z) < 1e-6, (
        f"leaked rotation onto uncommanded axes: {sp.y}, {sp.z}")
    assert eta > 0.0, f"ETA must be positive seconds for a real turn, got {eta}"


def test_pure_roll_delta_about_the_nose_is_commanded():
    """A delta about the ship's own forward axis is a pure roll: the forward
    vector is unchanged by it, so an implementation that only steers forward
    would silently do nothing. ManeuverLoop reaches this case whenever its turn
    axis is model-forward."""
    ship = _galaxy_ship()

    ship.TurnTowardDifference(TGPoint3(0.0, 0.5, 0.0))  # +Y == nose at identity

    sp = ship.GetTargetAngularVelocitySetpoint()
    assert sp is not None, "no setpoint written for a pure-roll delta"
    assert sp.y > 0.0, f"roll about the nose not commanded: {sp}"


def test_zero_delta_is_a_noop_and_returns_zero():
    """Matches TurnTowardDirection's contract: a zero-length command preserves
    any prior setpoint rather than stomping it with zeros."""
    ship = _galaxy_ship()
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.1, 0.0, 0.0))

    eta = ship.TurnTowardDifference(TGPoint3(0.0, 0.0, 0.0))

    assert eta == 0.0
    sp = ship.GetTargetAngularVelocitySetpoint()
    assert abs(sp.x - 0.1) < 1e-12, f"prior setpoint was stomped: {sp}"


def test_maneuver_loop_style_remainder_turn_completes():
    """Closed-loop, the way ManeuverLoop drives it: a fixed total angle about a
    fixed world axis, re-commanding only the rotation still outstanding each
    tick. The ship must actually traverse the full angle and settle there."""
    ship = _galaxy_ship()
    axis = TGPoint3(1.0, 0.0, 0.0)
    total = math.pi / 2.0

    def _observed():
        """Angle the nose has swung through, measured like ManeuverLoop does —
        from the attitude itself, not from what we commanded."""
        fwd = ship.GetWorldRotation().GetCol(1)
        return math.atan2(fwd.z, fwd.y)

    for _ in range(int(30.0 * 60)):
        remaining = total - _observed()
        if remaining > 1e-4:
            ship.TurnTowardDifference(
                TGPoint3(axis.x * remaining, axis.y * remaining, axis.z * remaining))
        _step_ship_motion(ship, _DT)

    assert abs(_observed() - total) < 0.02, (
        f"turn never completed: swung {_observed():.4f} of {total:.4f} rad")


def test_delta_is_measured_in_world_space_not_model_space():
    """The argument is already world-frame (ManeuverLoop pushes it through
    MultMatrixLeft before calling). From a rolled attitude, a delta about world
    +X must still turn about world +X — an implementation that re-applied the
    ship rotation would turn about the wrong axis here."""
    ship = _galaxy_ship()
    R = TGMatrix3(); R.MakeRotation(math.pi / 2.0, TGPoint3(0.0, 1.0, 0.0))
    ship.SetMatrixRotation(R)  # rolled 90° about the nose

    ship.TurnTowardDifference(TGPoint3(0.3, 0.0, 0.0))

    # Body→world: the setpoint is body-frame, so rotate it back out and compare
    # against the commanded world axis.
    sp = ship.GetTargetAngularVelocitySetpoint()
    world = TGPoint3(sp.x, sp.y, sp.z)
    world.MultMatrixLeft(ship.GetWorldRotation())
    assert world.x > 0.0, f"turned about the wrong world axis: {world}"
    assert abs(world.y) < 1e-6 and abs(world.z) < 1e-6, (
        f"commanded axis was rotated out of world +X: {world}")
