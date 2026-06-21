"""With strict GetSubmenuW, a system registration populates the live SDK Set
Course menu with system -> warp-point children carrying real labels."""
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.tg_ui.st_widgets import SortedRegionMenu


def _make_game():
    g = Game(); e = Episode(); m = Mission()
    e.SetCurrentMission(m); g.SetCurrentEpisode(e)
    return g


def _set_course_menu():
    helm = TacticalControlWindow.GetInstance().GetMenuList()[0]
    return next((c for c in helm._children
                 if isinstance(c, SortedRegionMenu)), None)


def test_system_registration_populates_warp_points():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    _set_current_game(_make_game())
    sys.modules.pop("Bridge.HelmMenuHandlers", None)
    sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as helm
    helm.CreateMenus()

    import Systems.Vesuvi.Vesuvi as vesuvi
    vesuvi.CreateMenus()

    sc = _set_course_menu()
    assert sc is not None
    vesuvi_node = next((c for c in sc._children
                        if c.GetLabel() == "Vesuvi"), None)
    assert vesuvi_node is not None, "Vesuvi system not under Set Course"
    warp_labels = [w.GetLabel() for w in vesuvi_node._children]
    assert len(warp_labels) >= 3, warp_labels
    # Labels are real strings from SetClass_MakeDisplayName, not stubs.
    for lbl in warp_labels:
        assert isinstance(lbl, str)
        assert "MakeDisplayName" not in lbl
    _set_current_game(None)
