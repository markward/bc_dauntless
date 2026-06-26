"""ShipClass.GetWeaponSystemGroup(eGroup) — WG enum → WeaponSystem slot.

Matches TacticalInterfaceHandlers.py:387-405 + MapModeInterfaceHandlers.py:
131-133 (left=primary, right=secondary, middle=tertiary).  PR 2's
FireWeapons handler reads this.
"""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


def _add_group(ship, name, wst):
    p = WeaponSystemProperty(name)
    p.SetWeaponSystemType(wst)
    ship.GetPropertySet().AddToSet("Scene Root", p)


def test_returns_phasers_for_primary():
    ship = ShipClass_Create("Galaxy")
    _add_group(ship, "Phasers", WeaponSystemProperty.WST_PHASER)
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is ship.GetPhaserSystem()


def test_returns_torpedoes_for_secondary():
    ship = ShipClass_Create("Galaxy")
    _add_group(ship, "Torpedoes", WeaponSystemProperty.WST_TORPEDO)
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_SECONDARY) is ship.GetTorpedoSystem()


def test_returns_pulse_for_tertiary():
    ship = ShipClass_Create("X")
    _add_group(ship, "Pulse", WeaponSystemProperty.WST_PULSE)
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_TERTIARY) is ship.GetPulseWeaponSystem()


def test_returns_tractor_for_wg_tractor():
    ship = ShipClass_Create("Galaxy")
    _add_group(ship, "Tractors", WeaponSystemProperty.WST_TRACTOR)
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_TRACTOR) is ship.GetTractorBeamSystem()


def test_returns_none_for_invalid_group():
    ship = ShipClass_Create("Bare")
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_INVALID) is None
    assert ship.GetWeaponSystemGroup(999) is None


def test_returns_none_when_group_not_on_ship():
    ship = ShipClass_Create("Bare")
    ship.SetupProperties()
    assert ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is None


# ── Primary → pulse fallback for phaserless ships (e.g. Bird of Prey) ────────

def _ship_with_systems(*, phaser_banks, pulse_cannons):
    """Ship whose phaser/pulse systems have the given child-emitter counts."""
    from engine.appc.subsystems import (
        PhaserSystem, PulseWeaponSystem, PhaserBank, PulseWeapon,
    )
    ship = ShipClass_Create("X")
    phasers = PhaserSystem("Phasers")
    for i in range(phaser_banks):
        phasers.AddChildSubsystem(PhaserBank(f"Bank{i}"))
    pulse = PulseWeaponSystem("Pulse")
    for i in range(pulse_cannons):
        pulse.AddChildSubsystem(PulseWeapon(f"Cannon{i}"))
    ship.SetPhaserSystem(phasers)
    ship.SetPulseWeaponSystem(pulse)
    return ship


def test_primary_falls_back_to_pulse_when_no_phaser_banks():
    # Bird-of-Prey shape: zero phaser banks, two disruptor cannons.
    ship = _ship_with_systems(phaser_banks=0, pulse_cannons=2)
    assert ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is ship.GetPulseWeaponSystem()


def test_primary_keeps_phasers_when_ship_has_both():
    # Vorcha shape: has phaser banks AND pulse cannons → primary stays phasers.
    ship = _ship_with_systems(phaser_banks=2, pulse_cannons=2)
    assert ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is ship.GetPhaserSystem()


def test_primary_returns_empty_phasers_when_no_pulse_either():
    # No phasers and no pulse: return the (empty) phaser system, not pulse.
    ship = _ship_with_systems(phaser_banks=0, pulse_cannons=0)
    assert ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is ship.GetPhaserSystem()


def test_tertiary_still_returns_pulse_on_phaserless_ship():
    # The fallback doesn't disturb the tertiary mapping.
    ship = _ship_with_systems(phaser_banks=0, pulse_cannons=2)
    assert ship.GetWeaponSystemGroup(ShipClass.WG_TERTIARY) is ship.GetPulseWeaponSystem()
