"""ST stylized widgets used by Bridge/*MenuHandlers.CreateMenus().
Call shapes from sdk/Build/scripts/Bridge/HelmMenuHandlers.py:136-260."""
from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.st_widgets import (
    STCharacterMenu, STCharacterMenu_CreateW,
    STWarpButton, STWarpButton_CreateW,
    SortedRegionMenu, SortedRegionMenu_CreateW,
    SortedRegionMenu_SetWarpButton, SortedRegionMenu_GetWarpButton,
    SortedRegionMenu_SetPauseSorting, SortedRegionMenu_ClearSetCourseMenu,
    SortedRegionMenu_IsSortingPaused,
    STRoundedButton, STRoundedButton_CreateW, STRoundedButton_Cast,
    STSubPane, STSubPane_Create, STSubPane_Cast,
    STButton_Cast, STStylizedWindow_Cast, STToggle_Cast,
    STWarpButton_Cast, SortedRegionMenu_Cast,
    _reset_module_state,
)
from engine.appc.windows import STStylizedWindow_CreateW


def setup_function(_):
    _reset_module_state()


def test_character_menu_is_an_stmenu():
    m = STCharacterMenu_CreateW("Hail")
    assert isinstance(m, STMenu)
    assert m.GetLabel() == "Hail"


def test_warp_button_holds_warp_time_and_course_menu():
    b = STWarpButton_CreateW("Warp")
    course = SortedRegionMenu_CreateW("Set Course")
    b.SetWarpTime(5)
    b.SetCourseMenu(course)
    assert b.GetWarpTime() == 5.0
    assert b.GetCourseMenu() is course


def test_sorted_region_menu_module_registry():
    b = STWarpButton_CreateW("Warp")
    SortedRegionMenu_SetWarpButton(b)
    assert SortedRegionMenu_GetWarpButton() is b
    SortedRegionMenu_SetPauseSorting(1)       # state sink, must not raise
    SortedRegionMenu_ClearSetCourseMenu()     # state sink, must not raise


def test_module_state_resets():
    SortedRegionMenu_SetWarpButton(STWarpButton_CreateW("Warp"))
    _reset_module_state()
    assert SortedRegionMenu_GetWarpButton() is None


def test_casts():
    btn = STButton("X")
    assert STButton_Cast(btn) is btn
    assert STButton_Cast(None) is None
    assert STButton_Cast("nope") is None
    win = STStylizedWindow_CreateW("Helm")
    assert STStylizedWindow_Cast(win) is win
    rb = STRoundedButton_CreateW("OK")
    assert STRoundedButton_Cast(rb) is rb
    sp = STSubPane_Create()
    assert STSubPane_Cast(sp) is sp
    assert STToggle_Cast(btn) is None


def test_warp_button_destination_default_falsy():
    b = STWarpButton_CreateW("Warp")
    assert not b.GetDestination()          # SDK truth-branch must not fire
    b.SetDestination("Systems.Artrus.Artrus3")
    assert b.GetDestination() == "Systems.Artrus.Artrus3"


def test_toggle_state_and_factory():
    from engine.appc.tg_ui.st_widgets import STToggle, STToggle_CreateW
    t = STToggle_CreateW("Cloak", 1, "On", None, "Off", None)
    assert t.IsToggled() == 1
    t.SetNotToggled()
    assert t.IsToggled() == 0
    assert t.GetToggleState() == 0


def test_sorting_paused_reflects_flag():
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu_IsSortingPaused
    assert SortedRegionMenu_IsSortingPaused() == 0
    SortedRegionMenu_SetPauseSorting(1)
    assert SortedRegionMenu_IsSortingPaused() == 1


def test_new_casts():
    from engine.appc.tg_ui.st_widgets import STWarpButton_Cast, SortedRegionMenu_Cast
    b = STWarpButton_CreateW("Warp")
    m = SortedRegionMenu_CreateW("Set Course")
    assert STWarpButton_Cast(b) is b
    assert STWarpButton_Cast(m) is None
    assert SortedRegionMenu_Cast(m) is m
    assert SortedRegionMenu_Cast(None) is None
    # Lenient pass-through (STMenu_Cast pattern): non-matching objects flow
    # through so SDK call chains hit TGObject's stub-absorbing __getattr__.
    assert SortedRegionMenu_Cast(b) is b


def test_sorted_region_menu_clear_info_is_noop():
    m = SortedRegionMenu_CreateW("Set Course")
    m.ClearInfo()  # must not raise
