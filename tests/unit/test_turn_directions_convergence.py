"""TurnDirectionsToDirections must converge from ANY attitude.

Two properties fixed together (live symptom: the ship "waves its nose
around in circles in a back and forth motion" and never lands on target):

1. Frame: the solver builds a WORLD-frame axis·angle vector, but the
   integrator (ship_motion._integrate_rotation) treats the setpoint as
   BODY-frame rates. The solver must convert (v_body = Rᵀ·v_world) —
   unconverted it is only correct near identity attitude.
2. Damping: the commanded rate is capped at √(2·MaxAngularAccel·θ) so a
   rate-saturated turn can always decelerate into alignment instead of
   overshooting and hunting (±MaxAngVel²/2·MaxAngAccel per swing).

The closed loop mimics the SDK usage: the AI re-commands via
TurnTowardLocation each tick (Intercept does this every Update), the
integrator ramps and rotates between commands.
"""
import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.appc.ship_motion import _step_ship_motion

_DT = 1.0 / 60.0


def _galaxy_ship():
    """Real Galaxy-class turn limits (sdk/.../Hardpoints/galaxy.py:782-785)."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _face_dot(ship, target):
    fwd = ship.GetWorldRotation().GetCol(1)
    d = TGPoint3(target.x, target.y, target.z)
    d.Unitize()
    return fwd.x * d.x + fwd.y * d.y + fwd.z * d.z


def _run_closed_loop(ship, target, seconds):
    """Re-command + integrate at 60 Hz; return per-tick face_dot history."""
    history = []
    for _ in range(int(seconds * 60)):
        ship.TurnTowardLocation(target)
        _step_ship_motion(ship, _DT)
        history.append(_face_dot(ship, target))
    return history


def test_turn_converges_from_arbitrary_attitude():
    """The live failure case: attitude far from identity. The nose must
    land on the target and STAY there — no hunting."""
    ship = _galaxy_ship()
    Rx = TGMatrix3(); Rx.MakeRotation(1.1, TGPoint3(1.0, 0.0, 0.0))
    Rz = TGMatrix3(); Rz.MakeRotation(2.3, TGPoint3(0.0, 0.0, 1.0))
    ship.SetMatrixRotation(Rx.MultMatrix(Rz))
    target = TGPoint3(500.0, -300.0, 200.0)

    history = _run_closed_loop(ship, target, seconds=20.0)

    assert history[-1] > 0.999, f"never converged: final dot {history[-1]:.3f}"
    # Settled: once aligned it must not wander off again.
    settle = [d for d in history[-300:]]           # last 5 s
    assert min(settle) > 0.995, f"hunting after alignment: min {min(settle):.3f}"


def test_turn_does_not_overshoot_and_hunt():
    """A pure 180° reversal at Galaxy rates: alignment error must shrink
    monotonically once the ship is decelerating — the overshoot beyond
    alignment must stay tiny (the √(2aθ) profile sheds rate in time)."""
    ship = _galaxy_ship()                          # identity: faces +Y
    target = TGPoint3(0.0, -1000.0, 0.0)           # dead astern

    history = _run_closed_loop(ship, target, seconds=30.0)

    peak = max(history)
    peak_at = history.index(peak)
    assert peak > 0.999, "never reached alignment"
    # After first alignment, no swing back below 0.99 (old behaviour dove
    # to ~0.94 and oscillated for tens of seconds).
    tail = history[peak_at:]
    assert min(tail) > 0.99, f"overshoot/hunt after alignment: min {min(tail):.3f}"


def test_turn_still_converges_near_identity():
    """Regression: the pre-fix behaviour was correct near identity — the
    body-frame conversion must not break the easy case."""
    ship = _galaxy_ship()
    target = TGPoint3(300.0, 400.0, 0.0)           # 37° off the nose

    history = _run_closed_loop(ship, target, seconds=10.0)

    assert history[-1] > 0.999
    assert min(history[-120:]) > 0.995
