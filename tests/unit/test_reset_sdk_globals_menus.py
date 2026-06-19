"""reset_sdk_globals clears bridge-menu state so a mission swap rebuilds
menus fresh (no stale-menu accumulation, no leaked warp-button registry)."""
import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.tg_ui import st_widgets
from engine.host_loop import reset_sdk_globals


def test_reset_clears_menu_state():
    # Dirty every piece of state the reset must clear.
    tcw = TacticalControlWindow.GetInstance()
    from engine.appc.characters import STTopLevelMenu
    tcw.AddMenuToList(STTopLevelMenu("Helm"))
    st_widgets.SortedRegionMenu_SetWarpButton(object())

    reset_sdk_globals()

    assert st_widgets.SortedRegionMenu_GetWarpButton() is None
    # Old instance orphaned; fresh singleton (created by the keyboard
    # re-point) holds no menus from the outgoing mission.
    fresh = TacticalControlWindow.GetInstance()
    assert fresh is not tcw
    assert fresh.GetMenuList() == []
    # Keyboard dispatch points at the fresh instance, not the orphan.
    assert App.g_kKeyboardBinding._default_destination is fresh


def test_reset_clears_viewscreen_in_use_flag():
    """If a mission is swapped away while its bridge viewscreen is on,
    MissionLib.g_bViewscreenOn is left at 1. On the next mission's load,
    MissionLib.ViewscreenOn() sees the viewscreen as "already in use" and
    enters a 2-second retry loop that never completes — stalling the briefing
    sequence (the comm character never speaks or renders). reset_sdk_globals
    must clear the flag on every swap so the next ViewscreenOn turns on cleanly."""
    import MissionLib
    MissionLib.SetViewscreenOn()          # g_bViewscreenOn = 1 (mid-briefing)
    assert MissionLib.IsViewscreenOn()

    reset_sdk_globals()

    assert not MissionLib.IsViewscreenOn()


def test_reset_rearms_ship_display_slots():
    from engine.sdk_ui.widgets import ship_display
    ship_display._create_count = 2          # both per-bridge slots consumed
    reset_sdk_globals()
    assert ship_display._create_count == 0


def test_reset_rewires_hotkeys_to_fresh_tcw():
    from engine.ui import crew_menu_hotkeys
    from engine.ui.crew_menu_panel import CrewMenuPanel
    from engine.appc.characters import STTopLevelMenu
    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(TacticalControlWindow.GetInstance(), panel)

    reset_sdk_globals()

    fresh = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    fresh.AddMenuToList(helm)
    panel.render_payload()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_INPUT_TALK_TO_HELM)
    evt.SetDestination(fresh)
    App.g_kEventManager.AddEvent(evt)
    assert panel._open_menu_id is not None
    crew_menu_hotkeys._wired_panel = None      # don't leak into other tests
