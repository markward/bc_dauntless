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


def test_target_row_uses_display_name():
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetDisplayName("USS Sovereign")

    menu = STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenu(ship)

    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.GetLabel() == "USS Sovereign"   # not the "player" identifier


def test_target_row_falls_back_to_name_when_no_display_name():
    ship = ShipClass_Create("Galaxy")
    ship.SetName("Cardassian_Galor1")
    # No SetDisplayName -> GetDisplayName falls back to GetName.

    menu = STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenu(ship)

    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.GetLabel() == "Cardassian_Galor1"
