from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty, PhaserProperty
from engine.ui.target_list_view import _resolve_subsystem_by_name


def _ship():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ph = WeaponSystemProperty("Phasers")
    ph.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", ph)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ship.SetupProperties()
    return ship


def test_resolves_top_level_subsystem():
    ship = _ship()
    assert _resolve_subsystem_by_name(ship, "Phasers") is not None


def test_resolves_child_leaf_subsystem():
    ship = _ship()
    leaf = _resolve_subsystem_by_name(ship, "Dorsal Phaser 1")
    assert leaf is not None
    assert leaf.GetName() == "Dorsal Phaser 1"


def test_unknown_name_returns_none():
    assert _resolve_subsystem_by_name(_ship(), "No Such System") is None
