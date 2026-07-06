"""PoweredSubsystem.TurnOn/TurnOff/IsOn + Set/GetPowerPercentageWanted.

Mirrors SDK App.py:5705-5708 surface. Used by ShipClass.SetAlertLevel to
flip weapon groups on/off and by WeaponSystem.StartFiring's gating check.
"""
from engine.appc.subsystems import PoweredSubsystem


def test_powered_subsystem_default_state():
    p = PoweredSubsystem("Test")
    assert p.IsOn() == 0
    # BC spawns every consumer at 100% wanted power (updated from old 0.0 shim
    # default — Task 1 of the power-management plan).
    assert p.GetPowerPercentageWanted() == 1.0


def test_turn_on_then_is_on():
    p = PoweredSubsystem("Test")
    p.TurnOn()
    assert p.IsOn() == 1


def test_turn_off_then_is_off():
    p = PoweredSubsystem("Test")
    p.TurnOn()
    p.TurnOff()
    assert p.IsOn() == 0


def test_power_percentage_wanted_roundtrip():
    p = PoweredSubsystem("Test")
    p.SetPowerPercentageWanted(0.75)
    assert p.GetPowerPercentageWanted() == 0.75


def test_power_percentage_wanted_coerces_to_float():
    p = PoweredSubsystem("Test")
    p.SetPowerPercentageWanted(1)
    assert isinstance(p.GetPowerPercentageWanted(), float)
    assert p.GetPowerPercentageWanted() == 1.0
