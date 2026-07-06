"""Test that impulse engine power factor scales motion caps."""

from engine.appc.ship_motion import _effective_motion
from engine.appc.subsystems import ImpulseEngineSubsystem


class _Ship:
    def __init__(self, ies):
        self._ies = ies
    def GetImpulseEngineSubsystem(self):
        return self._ies


def _engines(max_speed=6.3, ang=0.4):
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxSpeed(max_speed)
    ies.SetMaxAngularVelocity(ang)
    ies.SetMaxAccel(2.0)
    ies.SetMaxAngularAccel(0.5)
    ies.SetNormalPowerPerSecond(150.0)
    ies.TurnOn()
    return ies


def test_full_power_unchanged():
    ies = _engines()
    ies._power_factor = 1.0
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 6.3) < 1e-9


def test_half_power_halves_caps():
    ies = _engines()
    ies._power_factor = 0.5
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 3.15) < 1e-9
    assert abs(m.max_ang_vel - 0.2) < 1e-9


def test_boost_raises_caps():
    ies = _engines()
    ies._power_factor = 1.25
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 6.3 * 1.25) < 1e-9
