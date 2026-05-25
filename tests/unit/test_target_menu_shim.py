"""Unit tests for the target-list SDK shim (engine/appc/target_menu.py)."""
import App
from engine.appc.ships import ShipClass


def test_st_subsystem_menu_records_ship_and_defaults_visible():
    ship = ShipClass()
    ship.SetName("Test Ship")
    menu = App.STSubsystemMenu(ship)
    assert menu.GetShip() is ship
    assert menu.IsVisible() == 1


def test_st_subsystem_menu_show_name_methods_are_noops():
    """ShowUnknownName / ShowRealName never called by SDK; must not raise."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    menu.ShowUnknownName()
    menu.ShowRealName()


def test_st_component_menu_is_st_menu_subclass():
    """STComponentMenu never invoked from SDK Python; bare subclass is enough."""
    from engine.appc.characters import STMenu
    assert issubclass(App.STComponentMenu, STMenu)
