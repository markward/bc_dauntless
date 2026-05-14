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
