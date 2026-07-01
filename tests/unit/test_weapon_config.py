"""engine.appc.weapon_config — surface-agnostic reader + mutators for the
player's weapon configuration.  Both the weapons HUD panel and (later) the F2
tactical menu drive these helpers so state stays in sync.

Every helper is raise-safe: a ship missing a subsystem is a silent no-op on
mutation and an absent flag on read.
"""
from unittest.mock import patch

import pytest

from engine.appc.ships import ShipClass_Create
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import (
    CloakingSubsystem,
    PhaserSystem,
    PhaserBank,
    TorpedoSystem,
    TorpedoTube,
    TractorBeamSystem,
    TractorBeam,
)
from engine.appc.weapon_subsystems import TorpedoAmmoType
from engine.appc import weapon_config


# ── Construction helpers ────────────────────────────────────────────────────

def _bare_ship():
    ship = ShipClass_Create("Player")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    return ship


def _attach_torpedoes(ship, *, num_tubes=2, ammo_names=("Photon", "Quantum"),
                      ready_per_tube=100):
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Torpedoes"))
    parent._parent_ship = ship
    for i, name in enumerate(ammo_names):
        parent.AddAmmoType(TorpedoAmmoType(name, power_cost=20.0 + i))
    for i in range(num_tubes):
        tube = TorpedoTube(f"Tube {i}")
        tube._max_ready = ready_per_tube
        tube._num_ready = ready_per_tube
        parent.AddChildSubsystem(tube)
    ship._torpedo_system = parent
    return parent


def _attach_phasers(ship, *, banks=2):
    parent = PhaserSystem("Phasers")
    parent.TurnOn()
    parent._parent_ship = ship
    for i in range(banks):
        parent.AddChildSubsystem(PhaserBank(f"Bank {i}"))
    ship._phaser_system = parent
    return parent


def _attach_tractor(ship):
    parent = TractorBeamSystem("Tractors")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Tractors"))
    parent.SetSingleFire(1)
    parent._parent_ship = ship
    em = TractorBeam("Aft Tractor")
    em._max_charge = 10.0
    em._min_firing_charge = 1.0
    em._charge_level = 10.0
    parent.AddChildSubsystem(em)
    ship._tractor_beam_system = parent
    return parent


def _attach_cloak(ship):
    cloak = CloakingSubsystem("Cloak")
    cloak.TurnOn()
    ship._cloaking_subsystem = cloak
    return cloak


def _target():
    t = ShipClass_Create("Enemy")
    t.SetWorldLocation(TGPoint3(0, 40, 0))
    return t


# ── read_weapon_config: gating ──────────────────────────────────────────────

def test_bare_ship_has_no_config():
    cfg = weapon_config.read_weapon_config(_bare_ship())
    assert cfg["has_torpedoes"] is False
    assert cfg["has_phasers"] is False
    assert cfg["tractor_present"] is False
    assert cfg["cloak_present"] is False
    assert cfg["has_any_config"] is False


def test_torpedoes_present_and_fields():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=2, ammo_names=("Photon", "Quantum"),
                      ready_per_tube=125)
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["has_torpedoes"] is True
    assert cfg["torp_type"] == "Photon"          # lowest slot by default
    assert cfg["torp_count"] == 250              # 2 tubes × 125
    assert cfg["torp_types_cyclable"] is True    # two ammo types
    assert cfg["has_any_config"] is True


def test_torpedo_system_with_zero_tubes_not_present():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=0, ammo_names=("Photon",))
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["has_torpedoes"] is False


def test_single_ammo_type_not_cyclable():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=1, ammo_names=("Photon",))
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["torp_types_cyclable"] is False


def test_spread_options_reflect_tube_count():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=4, ammo_names=("Photon",))
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["spread"] == 1
    assert cfg["spread_options"] == [1, 2, 4]


def test_phasers_present_and_intensity_full_default():
    ship = _bare_ship()
    _attach_phasers(ship, banks=2)
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["has_phasers"] is True
    assert cfg["phaser_intensity"] == "Full"


def test_phaser_system_with_zero_banks_not_present():
    ship = _bare_ship()
    p = PhaserSystem("Phasers")
    p.TurnOn()
    ship._phaser_system = p
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["has_phasers"] is False


def test_phaser_intensity_light_when_low():
    ship = _bare_ship()
    p = _attach_phasers(ship)
    p.SetPowerLevel(PhaserSystem.PP_LOW)
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["phaser_intensity"] == "Light"


def test_tractor_present_and_off_default():
    ship = _bare_ship()
    _attach_tractor(ship)
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["tractor_present"] is True
    assert cfg["tractor_on"] is False


def test_cloak_present_and_off_default():
    ship = _bare_ship()
    _attach_cloak(ship)
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["cloak_present"] is True
    assert cfg["cloak_on"] is False


def test_none_ship_is_all_absent():
    cfg = weapon_config.read_weapon_config(None)
    assert cfg["has_any_config"] is False
    assert cfg["torp_type"] == ""


# ── cycle_torpedo_type ──────────────────────────────────────────────────────

def test_cycle_torpedo_type_advances():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=1, ammo_names=("Photon", "Quantum"))
    weapon_config.cycle_torpedo_type(ship)
    assert weapon_config.read_weapon_config(ship)["torp_type"] == "Quantum"
    weapon_config.cycle_torpedo_type(ship)  # wraps
    assert weapon_config.read_weapon_config(ship)["torp_type"] == "Photon"


def test_cycle_torpedo_type_single_type_no_op():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=1, ammo_names=("Photon",))
    weapon_config.cycle_torpedo_type(ship)
    assert weapon_config.read_weapon_config(ship)["torp_type"] == "Photon"


def test_cycle_torpedo_type_absent_no_crash():
    weapon_config.cycle_torpedo_type(_bare_ship())  # must not raise
    weapon_config.cycle_torpedo_type(None)


# ── cycle_torpedo_spread ────────────────────────────────────────────────────

def test_cycle_torpedo_spread_wraps():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=4, ammo_names=("Photon",))
    assert weapon_config.read_weapon_config(ship)["spread"] == 1
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == 2
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == 4
    weapon_config.cycle_torpedo_spread(ship)  # wraps to 1
    assert weapon_config.read_weapon_config(ship)["spread"] == 1


def test_cycle_torpedo_spread_single_option_no_op():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=1, ammo_names=("Photon",))
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == 1


def test_cycle_torpedo_spread_absent_no_crash():
    weapon_config.cycle_torpedo_spread(_bare_ship())


# ── toggle_phaser_intensity ─────────────────────────────────────────────────

def test_toggle_phaser_intensity_flips():
    ship = _bare_ship()
    _attach_phasers(ship)
    weapon_config.toggle_phaser_intensity(ship)
    assert weapon_config.read_weapon_config(ship)["phaser_intensity"] == "Light"
    weapon_config.toggle_phaser_intensity(ship)
    assert weapon_config.read_weapon_config(ship)["phaser_intensity"] == "Full"


def test_toggle_phaser_intensity_absent_no_crash():
    weapon_config.toggle_phaser_intensity(_bare_ship())


# ── toggle_tractor ──────────────────────────────────────────────────────────

def test_toggle_tractor_on_then_off():
    ship = _bare_ship()
    parent = _attach_tractor(ship)
    ship._target = _target()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        weapon_config.toggle_tractor(ship)
        assert parent.IsFiring() == 1
        weapon_config.toggle_tractor(ship)
        assert parent.IsFiring() == 0


def test_toggle_tractor_absent_no_crash():
    weapon_config.toggle_tractor(_bare_ship())


# ── toggle_cloak ────────────────────────────────────────────────────────────

def test_toggle_cloak_on_then_off():
    ship = _bare_ship()
    cloak = _attach_cloak(ship)
    weapon_config.toggle_cloak(ship)
    assert cloak.IsTryingToCloak() == 1
    weapon_config.toggle_cloak(ship)
    assert cloak.IsTryingToCloak() == 0


def test_toggle_cloak_reflected_in_config():
    ship = _bare_ship()
    _attach_cloak(ship)
    weapon_config.toggle_cloak(ship)
    assert weapon_config.read_weapon_config(ship)["cloak_on"] is True


def test_toggle_cloak_absent_no_crash():
    weapon_config.toggle_cloak(_bare_ship())
