from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, EngineProperty,
)
from engine.appc.target_menu import STTargetMenu


def _build_ship():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    phasers = WeaponSystemProperty("Phasers")
    phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", phasers)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 2"))
    imp = EngineProperty("Port Impulse")
    imp.SetEngineType(EngineProperty.EP_IMPULSE)
    ps.AddToSet("Scene Root", imp)
    ship.SetupProperties()
    return ship


def test_phaser_row_has_two_child_rows():
    menu = STTargetMenu("targets")
    ship = _build_ship()
    menu.RebuildShipMenu(ship)
    row = menu.GetObjectEntry(ship)        # the per-ship STSubsystemMenu
    labels = [c.GetLabel() for c in row._children]
    assert "Phasers" in labels
    phaser_row = next(c for c in row._children if c.GetLabel() == "Phasers")
    child_labels = sorted(gc.GetLabel() for gc in phaser_row._children)
    assert child_labels == ["Dorsal Phaser 1", "Dorsal Phaser 2"]
