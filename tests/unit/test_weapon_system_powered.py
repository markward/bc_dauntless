"""WeaponSystem subclasses should expose PoweredSubsystem's power API."""
from engine.appc.subsystems import (
    PoweredSubsystem, WeaponSystem,
    PhaserSystem, TorpedoSystem, PulseWeaponSystem, TractorBeamSystem,
)


def test_weapon_system_is_powered():
    assert issubclass(WeaponSystem, PoweredSubsystem)


def test_phaser_has_power_accessors():
    p = PhaserSystem("Phaser System")
    p.SetNormalPowerPerSecond(300.0)
    assert p.GetNormalPowerPerSecond() == 300.0


def test_torpedo_has_power_accessors():
    t = TorpedoSystem("Torpedo System")
    t.SetNormalPowerPerSecond(50.0)
    assert t.GetNormalPowerPerSecond() == 50.0


def test_pulse_and_tractor_have_power_accessors():
    PulseWeaponSystem("Pulse").SetNormalPowerPerSecond(100.0)
    TractorBeamSystem("Tractor").SetNormalPowerPerSecond(75.0)
