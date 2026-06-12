"""Run the REAL sdk/Build/scripts/Bridge/HelmMenuHandlers.CreateMenus().

conftest pre-stubs Bridge.HelmMenuHandlers as a _StubModule (MissionLib
writes attributes onto it), so this test swaps in the real module and
restores the stub afterwards.
"""
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.core.game import Game, Episode, Mission, _set_current_game


def _make_game():
    """Minimal game/episode/mission scaffold required by CreateMenus."""
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    return game


def _fresh_real_helm():
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _restore(saved, saved_bare):
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved
    if saved_bare is not None:
        sys.modules["HelmMenuHandlers"] = saved_bare


def test_create_menus_builds_helm_tree():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    game = _make_game()
    _set_current_game(game)
    real, saved, saved_bare = _fresh_real_helm()
    try:
        real.CreateMenus()
        tcw = TacticalControlWindow.GetInstance()
        menus = tcw.GetMenuList()
        assert len(menus) >= 1
        helm = menus[0]
        labels = [c.GetLabel() for c in helm._children if hasattr(c, "GetLabel")]
        # TGL lookup may localize; assert on structure not exact strings:
        from engine.appc.tg_ui.st_widgets import STWarpButton, SortedRegionMenu
        assert any(isinstance(c, STWarpButton) for c in helm._children)
        assert any(isinstance(c, SortedRegionMenu) for c in helm._children)
        assert len(labels) >= 5
        from engine.appc.tg_ui.st_widgets import SortedRegionMenu_GetWarpButton
        assert SortedRegionMenu_GetWarpButton() is not None
    finally:
        _restore(saved, saved_bare)
        _set_current_game(None)
