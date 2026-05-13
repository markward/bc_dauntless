"""PhaserBank, PulseWeapon, TractorBeam, TorpedoTube — live child classes.

Each one is a per-hardpoint weapon emitter that hangs under the matching
parent WeaponSystem.  All subclass WeaponSystem so they inherit firing
state, target, and the SetProperty back-ref; fields will be added as
SDK callers demand.
"""
from engine.appc.subsystems import (
    WeaponSystem, PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def test_phaser_bank_is_weapon_system():
    bank = PhaserBank("Forward Phaser 1")
    assert isinstance(bank, WeaponSystem)
    assert bank.GetName() == "Forward Phaser 1"


def test_pulse_weapon_is_weapon_system():
    pw = PulseWeapon("Forward Pulse")
    assert isinstance(pw, WeaponSystem)
    assert pw.GetName() == "Forward Pulse"


def test_tractor_beam_is_weapon_system():
    tb = TractorBeam("Aft Tractor 1")
    assert isinstance(tb, WeaponSystem)
    assert tb.GetName() == "Aft Tractor 1"


def test_torpedo_tube_is_weapon_system():
    tt = TorpedoTube("Forward Torpedo 1")
    assert isinstance(tt, WeaponSystem)
    assert tt.GetName() == "Forward Torpedo 1"


def test_child_weapon_inherits_property_back_reference():
    from engine.appc.properties import TractorBeamProperty
    tb = TractorBeam("Aft Tractor 1")
    p = TractorBeamProperty("Aft Tractor 1")
    tb.SetProperty(p)
    assert tb.GetProperty() is p
