"""Bridge menu activation — LoadBridge.Load() builds ALL FIVE menus via the
real SDK Bridge/*MenuHandlers. Strict: no degraded pass. Spec:
docs/superpowers/specs/2026-06-12-bridge-menu-activation-design.md
"""
import json
import sys

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.sdk_ui.widgets.ship_display import _reset_create_count as _reset_ship_display
from engine.ui.crew_menu_panel import CrewMenuPanel


def _fresh_world():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    LoadBridge._reset_menus_created()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    # Handlers re-register on each Load; clear stale ones from prior tests.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    # Game/Episode/Mission scaffolding — mirrors
    # tests/integration/test_crew_menu_round_trip.py's _make_game() exactly.
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    # Drop any stale stub modules so the handlers' import chains see the
    # real SDK modules.
    for name in list(sys.modules):
        mod = sys.modules[name]
        if name.startswith("Bridge.") and "StubModule" in type(mod).__name__:
            sys.modules.pop(name)
    return game


def test_load_builds_all_five_menus():
    _fresh_world()
    try:
        LoadBridge.Load("GalaxyBridge")
        tcw = TacticalControlWindow.GetInstance()
        menus = tcw.GetMenuList()
        assert len(menus) == 5, [m.GetLabel() for m in menus]
        tac = tcw.GetTacticalMenu()
        assert tac is not None
        assert tac in menus
        pane = tcw.GetMenuParentPane(tac.GetLabel())
        assert pane is not None
        assert pane._visible is False
        assert st_widgets.SortedRegionMenu_GetWarpButton() is not None
        panel = CrewMenuPanel()
        payload = panel.render_payload()
        data = json.loads(payload[len("setCrewMenus("):-2])
        assert len(data["menus"]) == 5
    finally:
        _set_current_game(None)


def test_double_load_builds_menus_once():
    _fresh_world()
    try:
        LoadBridge.Load("GalaxyBridge")
        n = len(TacticalControlWindow.GetInstance().GetMenuList())
        LoadBridge.Load("GalaxyBridge")
        assert len(TacticalControlWindow.GetInstance().GetMenuList()) == n
    finally:
        _set_current_game(None)
