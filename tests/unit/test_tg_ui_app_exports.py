"""Every tg_ui symbol the SDK references resolves to a real object on App,
and FontsAndIcons registers against real managers (not _NamedStub)."""
import sys
import App


REAL_SYMBOLS = [
    "TGPane", "TGPane_Create", "TGPane_Cast",
    "TGIcon", "TGIcon_Create", "TGIcon_Cast",
    "TGParagraph", "TGParagraph_Create", "TGParagraph_CreateW", "TGParagraph_Cast",
    "TGIconGroup",
    "g_kFontManager", "g_kIconManager", "g_kImageManager",
    "g_kFocusManager", "g_kRootWindow",
    "GraphicsModeInfo", "GraphicsModeInfo_GetCurrentMode",
    "TGUIModule_PixelAlignValue",
    "STCharacterMenu", "STCharacterMenu_CreateW",
    "STToggle", "STToggle_CreateW", "STToggle_Cast",
    "STWarpButton", "STWarpButton_CreateW", "STWarpButton_Cast",
    "SortedRegionMenu", "SortedRegionMenu_CreateW", "SortedRegionMenu_Cast",
    "SortedRegionMenu_SetWarpButton", "SortedRegionMenu_GetWarpButton",
    "SortedRegionMenu_SetPauseSorting", "SortedRegionMenu_ClearSetCourseMenu",
    "SortedRegionMenu_IsSortingPaused",
    "STRoundedButton", "STRoundedButton_CreateW", "STRoundedButton_Cast",
    "STSubPane", "STSubPane_Create", "STSubPane_Cast",
    "STButton_Cast", "STStylizedWindow_Cast",
]


def test_symbols_are_real_not_stubs():
    for name in REAL_SYMBOLS:
        obj = getattr(App, name)
        assert not isinstance(obj, App._Stub), name


def test_ct_sorted_region_menu_still_an_stmenu_subclass():
    from engine.appc.characters import STMenu
    assert issubclass(App.CT_SORTED_REGION_MENU, STMenu)


def test_fonts_and_icons_registers_real_entries():
    # Re-import so registration runs against the real managers even if an
    # earlier test imported it when stubs were live.
    sys.modules.pop("FontsAndIcons", None)
    import FontsAndIcons  # noqa: F401
    assert ("Crillee", 12) in App.g_kFontManager._fonts
    assert "LCARS_1024" in App.g_kIconManager._registered


def test_lcars_1024_loader_runs_against_real_icon_group():
    sys.modules.pop("LCARS_1024", None)
    import LCARS_1024
    LCARS_1024.LoadLCARS_1024()
    g = App.g_kIconManager.GetIconGroup("LCARS_1024")
    assert g is not None
    assert g.GetIconLocation(10) is not None
