"""Engine power scales the motion caps — via the SLIDER, not received power.

BC's ImpulseEngineSubsystem::GetMaxSpeed (FUN_00561230, clean-room 2026-07-13)
ends in `return cur * powerSetting`, where powerSetting is +0x90 — the requested
fraction (GetPowerPercentageWanted), NOT received/normal power (+0x94/+0x98).
So a reactor that cannot feed the engines does not lower the ship's cap; only
turning the slider down does. See subsystems.impulse_output_fraction.
"""

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
    m = _effective_motion(_Ship(_engines()))
    assert abs(m.max_speed - 6.3) < 1e-9


def test_half_power_halves_caps():
    ies = _engines()
    ies.SetPowerPercentageWanted(0.5)
    m = _effective_motion(_Ship(ies))
    assert abs(m.max_speed - 3.15) < 1e-9
    assert abs(m.max_ang_vel - 0.2) < 1e-9


def test_boost_raises_caps():
    ies = _engines()
    ies.SetPowerPercentageWanted(1.25)
    m = _effective_motion(_Ship(ies))
    assert abs(m.max_speed - 6.3 * 1.25) < 1e-9


def test_starved_reactor_does_not_lower_the_caps():
    """The received-power fraction is deliberately NOT a term: BC reports the
    cap for the REQUESTED setting even when the battery is dry."""
    ies = _engines()
    ies._power_factor = 0.25      # received/normal
    ies._efficiency = 0.25
    m = _effective_motion(_Ship(ies))
    assert abs(m.max_speed - 6.3) < 1e-9


def test_engines_switched_off_zero_the_caps():
    ies = _engines()
    ies.TurnOff()
    m = _effective_motion(_Ship(ies))
    assert m.max_speed == 0.0
    assert m.max_ang_vel == 0.0
