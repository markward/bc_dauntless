"""reset_sdk_globals clears bridge-menu state so a mission swap rebuilds
menus fresh (no stale-menu accumulation, no leaked warp-button registry)."""
import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.tg_ui import st_widgets
from engine.host_loop import reset_sdk_globals


def test_reset_clears_menu_state():
    # Dirty every piece of state the reset must clear.
    LoadBridge._menus_created = True
    tcw = TacticalControlWindow.GetInstance()
    from engine.appc.characters import STTopLevelMenu
    tcw.AddMenuToList(STTopLevelMenu("Helm"))
    st_widgets.SortedRegionMenu_SetWarpButton(object())

    reset_sdk_globals()

    assert LoadBridge._menus_created is False
    assert st_widgets.SortedRegionMenu_GetWarpButton() is None
    # Old instance orphaned; fresh singleton (created by the keyboard
    # re-point) holds no menus from the outgoing mission.
    fresh = TacticalControlWindow.GetInstance()
    assert fresh is not tcw
    assert fresh.GetMenuList() == []
    # Keyboard dispatch points at the fresh instance, not the orphan.
    assert App.g_kKeyboardBinding._default_destination is fresh


def test_pre_game_load_defers_menu_construction():
    from engine.core.game import _set_current_game
    _set_current_game(None)
    LoadBridge._reset_menus_created()
    TacticalControlWindow._instance = None
    App.g_kSetManager._sets.clear()
    LoadBridge.Load("GalaxyBridge")
    # No game yet: no menus, and the flag must NOT latch (the mission's
    # own Load() must still be able to build them).
    assert TacticalControlWindow.GetInstance().GetMenuList() == []
    assert LoadBridge._menus_created is False


def test_reset_rearms_ship_display_slots():
    from engine.sdk_ui.widgets import ship_display
    ship_display._create_count = 2          # both per-bridge slots consumed
    reset_sdk_globals()
    assert ship_display._create_count == 0
