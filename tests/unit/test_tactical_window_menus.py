"""TacticalControlWindow menu attachment — the CrewMenuPanel observation
surface. SDK: HelmMenuHandlers.CreateMenus does
  pTacticalControlWindow.AddChild(pHelmPane, 0.0, 0.0)
  pTacticalControlWindow.AddMenuToList(pHelmMenu)
"""
from engine.appc.windows import TacticalControlWindow
from engine.appc.characters import STTopLevelMenu


def setup_function(_):
    TacticalControlWindow._instance = None


def test_add_menu_to_list_and_read_back():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tactical = STTopLevelMenu("Tactical")
    tcw.AddMenuToList(helm)
    tcw.AddMenuToList(tactical)
    assert tcw.GetMenuList() == [helm, tactical]


def test_add_menu_is_idempotent():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tcw.AddMenuToList(helm)
    tcw.AddMenuToList(helm)
    assert tcw.GetMenuList() == [helm]


def test_add_child_is_recorded():
    tcw = TacticalControlWindow.GetInstance()
    tcw.AddChild(object(), 0.0, 0.0)  # must not raise
    assert tcw.GetMenuList() == []    # children are not menus


def _pane_with_menu(label):
    from engine.appc.windows import STStylizedWindow_CreateW
    pane = STStylizedWindow_CreateW("StylizedWindow", "NoMinimize", label, 0.0, 0.0)
    menu = STTopLevelMenu(label)
    pane.AddChild(menu, 0.0, 0.0, 0)
    return pane, menu


def test_find_menu_by_label_and_missing_returns_none():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tcw.AddMenuToList(helm)
    assert tcw.FindMenu("Helm") is helm
    assert tcw.FindMenu("Nope") is None


def test_find_menu_coerces_tgstring_like_labels():
    from engine.appc.localization import _TGString
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    tcw.AddMenuToList(helm)
    assert tcw.FindMenu(_TGString("Helm")) is helm


def test_get_menu_parent_pane():
    tcw = TacticalControlWindow.GetInstance()
    pane, menu = _pane_with_menu("Tactical")
    tcw.AddChild(pane, 0.0, 0.0)
    tcw.AddMenuToList(menu)
    assert tcw.GetMenuParentPane("Tactical") is pane
    assert tcw.GetMenuParentPane("Nope") is None


def test_tactical_menu_pointer_roundtrip():
    tcw = TacticalControlWindow.GetInstance()
    assert tcw.GetTacticalMenu() is None
    menu = STTopLevelMenu("Tactical")
    tcw.SetTacticalMenu(menu)
    assert tcw.GetTacticalMenu() is menu


def test_stmenu_is_completely_visible_mirrors_visibility():
    m = STTopLevelMenu("Helm")
    assert m.IsCompletelyVisible() == 1
    m.SetNotVisible()
    assert m.IsCompletelyVisible() == 0


def test_stbutton_chosen_toggle_round_trip():
    from engine.appc.characters import STButton
    b = STButton("Fire")
    assert b.IsChosen() == 0
    b.SetChosen(not b.IsChosen())     # SDK toggle idiom (TacticalControlHandlers.py:190)
    assert b.IsChosen() == 1
    b.SetChosen(not b.IsChosen())
    assert b.IsChosen() == 0


def test_get_menu_parent_pane_skips_non_matching_panes():
    tcw = TacticalControlWindow.GetInstance()
    other_pane, other_menu = _pane_with_menu("Science")
    pane, menu = _pane_with_menu("Tactical")
    tcw.AddChild(other_pane, 0.0, 0.0)
    tcw.AddChild(pane, 0.0, 0.0)
    tcw.AddMenuToList(other_menu)
    tcw.AddMenuToList(menu)
    assert tcw.GetMenuParentPane("Tactical") is pane
    # Menu known to TCW but contained in no recorded pane -> None.
    orphan = STTopLevelMenu("Helm")
    tcw.AddMenuToList(orphan)
    assert tcw.GetMenuParentPane("Helm") is None
