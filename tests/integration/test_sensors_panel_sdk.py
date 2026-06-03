"""Integration smoke test: the SDK's CreateRadarDisplay helper from
Bridge/TacticalMenuHandlers.py runs against the headless shim and
registers a working RadarDisplay with the TacticalControlWindow."""
import App


def test_sdk_create_radar_display_runs():
    """Imports and invokes the actual SDK CreateRadarDisplay function."""
    pTCW = App.TacticalControlWindow_GetTacticalControlWindow()
    # CreateRadarDisplay is at sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:471
    # It calls App.RadarDisplay_Create + SetUseScrolling + SetRadarDisplay.
    from Bridge import TacticalMenuHandlers
    try:
        pRadar = TacticalMenuHandlers.CreateRadarDisplay(pTCW)
        assert pRadar is not None
        assert pTCW.GetRadarDisplay() is pRadar
    finally:
        # TCW is a session singleton — clear so subsequent tests start clean.
        pTCW.SetRadarDisplay(None)


def test_sensors_panel_renders_for_empty_world():
    """With no ships in the player's spatial set, SensorsPanel emits
    a visible-true / empty-contacts payload — not a crash."""
    import json
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass
    from engine.core.game import Game, Episode, Mission, _set_current_game

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    spatial = SetClass()
    App.g_kSetManager.AddSet(spatial, "smoke_set")
    player._containing_set = spatial
    _set_current_game(game)

    App._reset_target_menu_singleton()
    App.STTargetMenu_CreateW("Targets")

    try:
        panel = SensorsPanel()
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setRadar(")
        state = json.loads(script[len("setRadar("):-2])
        assert state["visible"] is True
        assert state["contacts"] == []
        assert state["range_gu"] > 0.0
    finally:
        App.g_kSetManager.DeleteSet("smoke_set")
        _set_current_game(None)
