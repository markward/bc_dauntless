"""Per-emitter runtime classes carry charge/reload state.  PR 1 only verifies
defaults and the getter surface; Pass 4 (Task 3) populates these from
property copies, PR 2 will fill/drain them.
"""
from engine.appc.subsystems import (
    PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def test_phaser_bank_default_charge_fields_zero():
    b = PhaserBank("Dorsal Phaser 1")
    assert b.GetMaxCharge() == 0.0
    assert b.GetMinFiringCharge() == 0.0
    assert b.GetNormalDischargeRate() == 0.0
    assert b.GetRechargeRate() == 0.0
    assert b.GetChargeLevel() == 0.0


def test_phaser_bank_charge_percentage_handles_zero_max():
    b = PhaserBank("Dorsal Phaser 1")
    assert b.GetChargePercentage() == 0.0


def test_phaser_bank_charge_percentage_partial():
    b = PhaserBank("Dorsal Phaser 1")
    b._max_charge = 5.0
    b._charge_level = 2.5
    assert b.GetChargePercentage() == 0.5


def test_phaser_bank_set_charge_level_clamps():
    b = PhaserBank("Dorsal Phaser 1")
    b._max_charge = 5.0
    b.SetChargeLevel(10.0)
    assert b.GetChargeLevel() == 5.0
    b.SetChargeLevel(-1.0)
    assert b.GetChargeLevel() == 0.0


def test_pulse_weapon_has_energy_weapon_state_and_cooldown():
    p = PulseWeapon("Forward Pulse")
    assert p.GetMaxCharge() == 0.0
    assert p.GetCooldownTime() == 0.0


def test_tractor_beam_has_energy_weapon_state():
    t = TractorBeam("Aft Tractor 1")
    assert t.GetMaxCharge() == 0.0
    assert t.GetRechargeRate() == 0.0


def test_torpedo_tube_default_reload_fields():
    t = TorpedoTube("Forward Torpedo 1")
    assert t.GetNumReady() == 0
    assert t.GetImmediateDelay() == 0.0
    assert t.GetReloadDelay() == 0.0
    assert t.GetMaxReady() == 0
    # BC inits GAME time to -1000.0 (combat-and-damage.md:757), not -inf --
    # see tests/unit/test_torpedo_tube_reload.py.
    assert t.GetLastFireTime() == -1000.0


def test_torpedo_tube_num_ready_setters():
    t = TorpedoTube("Forward Torpedo 1")
    t.SetNumReady(2)
    assert t.GetNumReady() == 2
    t.IncNumReady()
    assert t.GetNumReady() == 3
    t.DecNumReady()
    assert t.GetNumReady() == 2


def test_torpedo_tube_last_fire_time_roundtrip():
    t = TorpedoTube("Forward Torpedo 1")
    t.SetLastFireTime(123.4)
    assert t.GetLastFireTime() == 123.4
