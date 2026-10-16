"""The surface BridgeHandlers.FindCourseButton walks (SDK BridgeHandlers.py
:1350-1367), which HelmUpdateToolTip uses for Kiska's "Destination :" line:

    pMenu = App.SortedRegionMenu_GetRoot()
    for i in range(pMenu.GetNumChildren()):
        pChild = pMenu.GetNthChild(i)
        if pChild.IsTypeOf(App.CT_SORTED_REGION_MENU): ...
    pButton.GetName(kName)

Every one of those was a stub or a wrong answer, so the line never resolved.
"""
import App
from engine.appc.characters import STMenu, STTopLevelMenu
from engine.appc.tg_ui import st_widgets


def _set_course_tree():
    """The shape HelmMenuHandlers.CreateMenus:197-206 + Systems/Utils.py:76-93
    build: Set Course (no region) > system (default region) > regions."""
    root = App.SortedRegionMenu_CreateW("Set Course")
    system = App.SortedRegionMenu_CreateW("Vesuvi", "Systems.Vesuvi.Vesuvi6")
    for label, region in (("Vesuvi Dust Cloud", "Systems.Vesuvi.Vesuvi4"),
                          ("Haven Colony", "Systems.Vesuvi.Vesuvi6")):
        system.AddChild(App.SortedRegionMenu_CreateW(label, region), 0, 0, 0)
    root.AddChild(system, 0, 0, 0)
    warp = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(warp)
    warp.SetCourseMenu(root)
    return root, system, warp


# ── SortedRegionMenu_GetRoot ─────────────────────────────────────────────────

def test_get_root_is_the_set_course_menu_the_warp_button_was_given():
    st_widgets._reset_module_state()
    root, _system, _warp = _set_course_tree()
    assert App.SortedRegionMenu_GetRoot() is root


def test_get_root_is_none_before_the_helm_menu_exists():
    st_widgets._reset_module_state()
    # Never a truthy _NamedStub: FindCourseButton would walk it as a menu.
    assert App.SortedRegionMenu_GetRoot() is None


# ── STMenu child walk ────────────────────────────────────────────────────────

def test_stmenu_counts_and_indexes_its_children():
    root, system, _warp = _set_course_tree()
    assert root.GetNumChildren() == 1
    assert root.GetNthChild(0) is system
    assert system.GetNumChildren() == 2
    assert system.GetNthChild(1).GetLabel() == "Haven Colony"


def test_stmenu_nth_child_out_of_range_is_none_not_wraparound():
    _root, system, _warp = _set_course_tree()
    assert system.GetNthChild(2) is None
    assert system.GetNthChild(-1) is None


def test_a_leaf_region_has_no_children():
    _root, system, _warp = _set_course_tree()
    assert system.GetNthChild(0).GetNumChildren() == 0


# ── STMenu.IsTypeOf through the CT_ registry ─────────────────────────────────

def test_sorted_region_menu_is_type_of_its_own_tag_and_stmenu():
    menu = App.SortedRegionMenu_CreateW("Vesuvi", "Systems.Vesuvi.Vesuvi6")
    assert menu.IsTypeOf(App.CT_SORTED_REGION_MENU) == 1
    assert menu.IsTypeOf(App.CT_ST_MENU) == 1


def test_plain_stmenu_is_not_a_sorted_region_menu():
    menu = App.STMenu_CreateW("Orbit Planet")
    assert menu.IsTypeOf(App.CT_ST_MENU) == 1
    assert menu.IsTypeOf(App.CT_SORTED_REGION_MENU) == 0


def test_stmenu_is_not_a_ship():
    assert App.STMenu_CreateW("Hail").IsTypeOf(App.CT_SHIP) == 0


# ── STMenu.GetName(kString) ──────────────────────────────────────────────────

def test_stmenu_get_name_fills_the_tgstring_with_its_label():
    """SWIG STMenu.GetName (App.py:7758) fills a TGString; every SDK caller
    uses that form (BridgeHandlers.py:1416, BridgeMenus.py:134, E4M4.py:1015,
    UITree.py:262)."""
    menu = App.SortedRegionMenu_CreateW("Haven Colony", "Systems.Vesuvi.Vesuvi6")
    k = App.TGString()
    assert menu.GetName(k) is None
    assert k.GetCString() == "Haven Colony"


def test_top_level_menu_get_name_fills_the_tgstring_too():
    k = App.TGString()
    STTopLevelMenu("Helm").GetName(k)
    assert k.GetCString() == "Helm"


def test_stmenu_get_name_without_an_argument_is_unchanged():
    menu = STMenu("Helm")
    assert menu.GetName() == ""


# ── The SDK walk itself ──────────────────────────────────────────────────────

def test_find_course_button_resolves_a_region_to_its_row():
    st_widgets._reset_module_state()
    _set_course_tree()
    from engine.ui import tooltip_dispatch
    handlers = tooltip_dispatch._bridge_handlers()
    button = handlers.FindCourseButton("Systems.Vesuvi.Vesuvi4")
    assert button is not None
    k = App.TGString()
    button.GetName(k)
    assert k.GetCString() == "Vesuvi Dust Cloud"


def test_find_course_button_misses_an_unlisted_region():
    st_widgets._reset_module_state()
    _set_course_tree()
    from engine.ui import tooltip_dispatch
    handlers = tooltip_dispatch._bridge_handlers()
    assert handlers.FindCourseButton("Systems.Belaruz.Belaruz1") is None
