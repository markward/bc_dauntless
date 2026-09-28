"""A fresh headless world for tests that drive real SDK missions/menus: the
UI/menu singletons the SDK menu handlers touch reset, stale sets and event
handlers cleared, and a Game/Episode/Mission context current."""
import sys

import App
from engine.core.game import Game, Episode, Mission, _set_current_game


def _fresh_world():
    # Mirror tests/integration/test_bridge_menu_activation.py::_fresh_world:
    # reset the UI/menu singletons the SDK menu handlers touch, clear stale
    # sets + event handlers, then build a Game/Episode/Mission context.
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.target_menu import _reset_target_menu_singleton
    from engine.appc.tg_ui import st_widgets
    from engine.sdk_ui.widgets.ship_display import (
        _reset_create_count as _reset_ship_display,
    )

    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    # Handlers re-register on each Load; clear stale ones from prior tests.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    # Game/Episode/Mission scaffolding.
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
