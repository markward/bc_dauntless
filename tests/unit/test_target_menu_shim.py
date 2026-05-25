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


def test_st_target_menu_inherits_st_top_level_menu():
    from engine.appc.characters import STTopLevelMenu
    menu = App.STTargetMenu("Targets")
    assert isinstance(menu, STTopLevelMenu)
    assert menu.GetLabel() == "Targets"


def test_st_target_menu_child_traversal():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b, ship_c = ShipClass(), ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B"); ship_c.SetName("C")
    sub_a, sub_b, sub_c = (
        App.STSubsystemMenu(ship_a),
        App.STSubsystemMenu(ship_b),
        App.STSubsystemMenu(ship_c),
    )
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    target_menu.AddChild(sub_c)

    assert target_menu.GetFirstChild() is sub_a
    assert target_menu.GetLastChild() is sub_c
    assert target_menu.GetNextChild(sub_a) is sub_b
    assert target_menu.GetNextChild(sub_c) is None
    assert target_menu.GetPrevChild(sub_c) is sub_b
    assert target_menu.GetPrevChild(sub_a) is None


def test_st_target_menu_get_object_entry_by_ship_identity():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b = ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B")
    sub_a = App.STSubsystemMenu(ship_a)
    sub_b = App.STSubsystemMenu(ship_b)
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    assert target_menu.GetObjectEntry(ship_a) is sub_a
    assert target_menu.GetObjectEntry(ship_b) is sub_b
    stranger = ShipClass(); stranger.SetName("?")
    assert target_menu.GetObjectEntry(stranger) is None


def test_create_w_installs_singleton():
    App._reset_target_menu_singleton()
    assert App.STTargetMenu_GetTargetMenu() is None

    menu = App.STTargetMenu_CreateW("Targets")
    assert isinstance(menu, App.STTargetMenu)
    assert menu.GetLabel() == "Targets"
    assert App.STTargetMenu_GetTargetMenu() is menu


def test_subsystem_menu_cast_lenient_passthrough():
    """Mirrors STMenu_Cast — real instance → self; None → None; other → pass through."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    assert App.STSubsystemMenu_Cast(menu) is menu
    assert App.STSubsystemMenu_Cast(None) is None
    sentinel = object()
    assert App.STSubsystemMenu_Cast(sentinel) is sentinel


def test_clear_target_list_removes_all_rows():
    target_menu = App.STTargetMenu("Targets")
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.ClearTargetList()
    assert target_menu.GetFirstChild() is None


def test_clear_persistent_target_drops_hint():
    target_menu = App.STTargetMenu("Targets")
    target_menu.SetPersistentTarget("USS Enterprise")
    assert target_menu.GetPersistentTarget() == "USS Enterprise"
    target_menu.ClearPersistentTarget()
    assert target_menu.GetPersistentTarget() is None
