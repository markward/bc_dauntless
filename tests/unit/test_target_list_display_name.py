"""Target-list rows must show the localized display name, not the raw internal
identifier.

Regression: STTargetMenu.RebuildShipMenu labelled each row with ship.GetName()
("player", "Cardassian_Galor1") instead of ship.GetDisplayName() ("USS
Sovereign", "Galor"). The hail list already used the display name, so only the
tactical target list showed identifiers — and only once sensor identification
started populating it (sensors are now on by default).
"""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.target_menu import STTargetMenu_CreateW
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




def test_target_row_uses_display_name():
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetDisplayName("USS Sovereign")

    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(_listed(ship))

    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.GetLabel() == "USS Sovereign"   # not the "player" identifier


def test_target_row_falls_back_to_name_when_no_display_name():
    ship = ShipClass_Create("Galaxy")
    ship.SetName("Cardassian_Galor1")
    # No SetDisplayName -> GetDisplayName falls back to GetName.

    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(_listed(ship))

    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.GetLabel() == "Cardassian_Galor1"
