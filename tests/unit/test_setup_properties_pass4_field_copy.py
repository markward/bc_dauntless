"""Pass 4 copies typed charge/reload fields from per-emitter property
to runtime emitter, in addition to the MaxCondition copy that already works.
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, PulseWeaponProperty,
    TractorBeamProperty, TorpedoTubeProperty,
)
from engine.appc.subsystems import PhaserBank, PulseWeapon, TractorBeam, TorpedoTube


def _phaser_parent_prop():
    p = WeaponSystemProperty("Phasers")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    return p


def _pulse_parent_prop():
    p = WeaponSystemProperty("Pulse")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PULSE)
    return p


def _tractor_parent_prop():
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    return p


def _torpedo_parent_prop():
    p = WeaponSystemProperty("Torpedoes")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    return p


def test_phaser_bank_inherits_property_charge_fields():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _phaser_parent_prop())

    phaser_prop = PhaserProperty("Dorsal Phaser 1")
    phaser_prop.SetMaxCharge(5.0)
    phaser_prop.SetMinFiringCharge(3.0)
    phaser_prop.SetNormalDischargeRate(1.0)
    phaser_prop.SetRechargeRate(0.08)
    ps.AddToSet("Scene Root", phaser_prop)

    ship.SetupProperties()
    bank = ship.GetPhaserSystem().GetWeapon(0)
    assert isinstance(bank, PhaserBank)
    assert bank.GetMaxCharge() == 5.0
    assert bank.GetMinFiringCharge() == 3.0
    assert bank.GetNormalDischargeRate() == 1.0
    assert bank.GetRechargeRate() == 0.08
    # Fresh ships spawn with phasers fully charged.
    assert bank.GetChargeLevel() == 5.0
    assert bank.GetChargePercentage() == 1.0


def test_pulse_weapon_inherits_property_charge_and_cooldown():
    ship = ShipClass_Create("VorCha")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _pulse_parent_prop())

    pulse_prop = PulseWeaponProperty("Forward Pulse")
    pulse_prop.SetMaxCharge(2.0)
    pulse_prop.SetCooldownTime(0.8)
    ps.AddToSet("Scene Root", pulse_prop)

    ship.SetupProperties()
    pulse = ship.GetPulseWeaponSystem().GetWeapon(0)
    assert isinstance(pulse, PulseWeapon)
    assert pulse.GetMaxCharge() == 2.0
    assert pulse.GetCooldownTime() == 0.8
    assert pulse.GetChargeLevel() == 2.0


def test_tractor_beam_inherits_property_charge_fields():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent_prop())

    tract_prop = TractorBeamProperty("Aft Tractor 1")
    tract_prop.SetMaxCharge(1.0)
    tract_prop.SetRechargeRate(0.5)
    ps.AddToSet("Scene Root", tract_prop)

    ship.SetupProperties()
    beam = ship.GetTractorBeamSystem().GetWeapon(0)
    assert isinstance(beam, TractorBeam)
    assert beam.GetMaxCharge() == 1.0
    assert beam.GetRechargeRate() == 0.5
    assert beam.GetChargeLevel() == 1.0


def test_torpedo_tube_inherits_property_reload_fields():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _torpedo_parent_prop())

    tube_prop = TorpedoTubeProperty("Forward Torpedo 1")
    tube_prop.SetImmediateDelay(0.25)
    tube_prop.SetReloadDelay(40.0)
    tube_prop.SetMaxReady(1)
    ps.AddToSet("Scene Root", tube_prop)

    ship.SetupProperties()
    tube = ship.GetTorpedoSystem().GetWeapon(0)
    assert isinstance(tube, TorpedoTube)
    assert tube.GetImmediateDelay() == 0.25
    assert tube.GetReloadDelay() == 40.0
    assert tube.GetMaxReady() == 1
    # Tubes start loaded.
    assert tube.GetNumReady() == 1


def test_pass4_field_copy_idempotent():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _phaser_parent_prop())
    phaser_prop = PhaserProperty("Dorsal Phaser 1")
    phaser_prop.SetMaxCharge(5.0)
    ps.AddToSet("Scene Root", phaser_prop)

    ship.SetupProperties()
    ship.SetupProperties()
    assert ship.GetPhaserSystem().GetNumWeapons() == 1
    bank = ship.GetPhaserSystem().GetWeapon(0)
    assert bank.GetMaxCharge() == 5.0
