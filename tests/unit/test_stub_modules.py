def test_loadspacehelper_create_ship_callable():
    import loadspacehelper
    result = loadspacehelper.CreateShip("Galaxy", None, "player", "Start")
    assert result is not None


def test_loadspacehelper_preload_ship_callable():
    import loadspacehelper
    # PreloadShip is a void procedure; it should not raise
    loadspacehelper.PreloadShip("Galaxy", 1)


def test_load_bridge_load_callable():
    import App
    import LoadBridge
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.tg_ui import st_widgets
    from engine.sdk_ui.widgets.ship_display import (
        # Clears BOTH _create_count AND the stale module-level _registry; a
        # prior host-loop test can leave _registry pointing at a registry that
        # already holds a "ship-player" panel, which would make LoadBridge.Load's
        # ShipDisplay_Create re-register it and raise "duplicate panel name".
        _reset_for_bridge_teardown as _reset_ship_display,
    )
    from engine.core.game import Game, Episode, Mission, _set_current_game
    # The SDK LoadBridge.Load registers a beep handler on the current Game, so
    # a live Game/Episode/Mission context is required.
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    # Clean slate so Load takes the CreateAndPopulateBridgeSet path rather
    # than the IsSameConfig short-circuit on a set left by a prior test.
    App.g_kSetManager._sets.clear()
    TacticalControlWindow._instance = None
    st_widgets._reset_module_state()
    _reset_ship_display()
    try:
        # The SDK LoadBridge.Load returns None (it builds the "bridge"
        # SetClass + crew as a side effect); the success signal is that the
        # set now exists, not the return value.
        LoadBridge.Load("GalaxyBridge")
        bridge = App.g_kSetManager.GetSet("bridge")
        assert bridge is not None
    finally:
        App.g_kEventManager._broadcast_handlers.clear()
        if hasattr(App.g_kEventManager, "_method_handlers"):
            App.g_kEventManager._method_handlers.clear()
        _set_current_game(None)
        TacticalControlWindow._instance = None
        st_widgets._reset_module_state()


def test_bridge_helm_menu_handlers_attr_set():
    import Bridge.HelmMenuHandlers
    Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0
