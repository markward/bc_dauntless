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
