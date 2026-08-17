from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, EngineProperty,
)
from engine.appc.target_menu import STTargetMenu
from engine.appc.perception import Contact


def _listed(*ships):
    """Contact records for ships the player can see and target — what
    perceived_by returns for an in-range, uncloaked, living contact.

    set_contacts takes perception.Contact records rather than bare ships: the
    record carries the frame's verdict, and the menu derives the listing from
    `targetable`. Row IsVisible is NOT derived from `perceivable` — set_contacts
    asserts SetVisible() on every listed row, so that flag answers nothing about
    detectability; readers that need it read `perceivable` off the record.
    The distance is 0.0 because nothing in this file reads it.
    """
    return [Contact(ship=s, surface_gu=0.0,
                    perceivable=True, targetable=True) for s in ships]




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
    menu.set_contacts(_listed(ship))
    row = menu.GetObjectEntry(ship)        # the per-ship STSubsystemMenu
    labels = [c.GetLabel() for c in row._children]
    assert "Phasers" in labels
    phaser_row = next(c for c in row._children if c.GetLabel() == "Phasers")
    child_labels = sorted(gc.GetLabel() for gc in phaser_row._children)
    assert child_labels == ["Dorsal Phaser 1", "Dorsal Phaser 2"]
