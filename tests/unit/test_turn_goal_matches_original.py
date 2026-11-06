"""A ship turning toward a point follows the original's planned turn.

Measured on stbc.exe (stbc-oracle results_mac/turnto, Galaxy turnloc*):
TurnTowardLocation on a fixed point plans a cubic whose angular acceleration
falls linearly from +MaxAngularAccel to -MaxAngularAccel, so a turn of theta
takes sqrt(6 theta / A) and peaks at A tau / 4, past MaxAngularVelocity on a
big turn. The goal is stored: one call turns the ship exactly as one per frame
does, and an about-face yaws (up stays up). Dauntless used to cap the rate at
MaxAngularVelocity, steer only when the AI re-issued the call, and pitch over
for an about-face; the 180 deg turn reached 10 deg 1.9 s late.
"""
import math

import pytest

from engine.appc.math import TGPoint3
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem

_DT = 1.0 / 60.0


def _galaxy():
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _point(az_deg):
    a = math.radians(az_deg)
    return TGPoint3(100.0 * math.sin(a), 100.0 * math.cos(a), 0.0)


def _angle(ship, pt):
    f = ship.GetWorldRotation().GetCol(1)
    p = ship.GetWorldLocation()
    d = TGPoint3(pt.x - p.x, pt.y - p.y, pt.z - p.z)
    d.Unitize()
    return math.degrees(math.acos(max(-1.0, min(1.0, f.Dot(d)))))


def _fly(ship, pt, seconds, reissue):
    rows = []
    for i in range(int(seconds * 60)):
        if reissue or i == 0:
            ship.TurnTowardLocation(pt)
        _step_ship_motion(ship, _DT)
        w = ship._current_angular_velocity
        rows.append(((i + 1) * _DT, _angle(ship, pt), math.sqrt(w.x * w.x + w.y * w.y + w.z * w.z)))
    return rows


# (bearing deg, original's time to within 10 deg, original's peak rate)
@pytest.mark.parametrize("az,t10,peak", [(45, 4.38, 0.187), (90, 7.08, 0.265), (180, 10.80, 0.374)])
def test_turn_follows_the_originals_planned_cubic(az, t10, peak):
    rows = _fly(_galaxy(), _point(az), 20.0, reissue=True)
    got_t10 = next(t for t, a, _ in rows if a < 10.0)
    assert got_t10 == pytest.approx(t10, abs=0.15)
    assert max(w for _, _, w in rows) == pytest.approx(peak, abs=0.005)
    assert rows[-1][1] < 0.1


def test_one_command_turns_the_ship_as_one_per_frame_does():
    every = _fly(_galaxy(), _point(90), 12.0, reissue=True)
    once = _fly(_galaxy(), _point(90), 12.0, reissue=False)
    for (_, a1, _), (_, a2, _) in zip(every[::30], once[::30]):
        assert a2 == pytest.approx(a1, abs=0.05)


def test_an_about_face_yaws():
    ship = _galaxy()
    _fly(ship, _point(180), 15.0, reissue=True)
    assert ship.GetWorldRotation().GetCol(2).z == pytest.approx(1.0, abs=1e-3)


def test_another_angular_command_replaces_the_goal():
    ship = _galaxy()
    pt = _point(90)
    ship.TurnTowardLocation(pt)
    for _ in range(60):
        _step_ship_motion(ship, _DT)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))
    for _ in range(600):
        _step_ship_motion(ship, _DT)
    w = ship._current_angular_velocity
    assert abs(w.z) < 1e-3
    assert _angle(ship, pt) > 45.0          # stopped short: the goal no longer steers


def test_complete_stop_ends_the_goal():
    """CompleteStop replaces the angular setpoint with a fresh zero, so the
    goal no longer owns it and never steers again: it is cleared, as every
    other angular command clears it (kernel M, which cannot see `goal[1] is
    setpoint`, would otherwise steer it)."""
    ship = _galaxy()
    pt = _point(90)
    ship.TurnTowardLocation(pt)
    for _ in range(30):
        _step_ship_motion(ship, _DT)
    ship.CompleteStop()
    assert ship._turn_goal is None
    for _ in range(600):
        _step_ship_motion(ship, _DT)
    w = ship._current_angular_velocity
    assert (w.x, w.y, w.z) == (0.0, 0.0, 0.0)
    assert _angle(ship, pt) > 45.0
