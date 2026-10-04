"""Every corpus mod passes SubMenu in the details dict:
FedShipDef(abbrev, species, {'name':..., 'SubMenu': SubMenu}). The shim
used to read only name/iconName/shipFile from it, so nested QuickBattle
menus never appeared live -- the menu-injection tests set the attribute
directly and could not see it."""
import pytest

from engine import foundation
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def test_submenu_and_subsubmenu_come_from_details():
    d = ShipDefinition("Fed", "DCMPDefiant", 103,
                       {"name": "Defiant", "shipFile": "DCMPDefiant",
                        "SubMenu": "Defiant Class", "SubSubMenu": "Escorts"})
    assert d.SubMenu == "Defiant Class"
    assert d.SubSubMenu == "Escorts"
    assert "SubMenu" not in d.unknown_attributes


def test_absent_keys_stay_none():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X"})
    assert d.SubMenu is None and d.SubSubMenu is None


def test_a_later_attribute_still_wins():
    d = ShipDefinition("Fed", "X", 103, {"shipFile": "X", "SubMenu": "A"})
    d.SubMenu = "B"
    assert d.SubMenu == "B"
