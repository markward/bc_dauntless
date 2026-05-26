"""Tests for the sensor-visibility update path that drives
STSubsystemMenu.SetVisible/SetNotVisible based on range from the player."""
import App
from engine.appc.ships import ShipClass, ShipClass_Create


def _ship(name, x=0.0, y=0.0, z=0.0):
    s = ShipClass_Create("test")
    s.SetName(name)
    s.SetTranslateXYZ(x, y, z)
    return s


def _setup_game_with_player():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = _ship("Player", 0.0, 0.0, 0.0)
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def test_in_range_ship_remains_visible():
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        nearby = _ship("Nearby", 1000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(nearby)

        update_target_list_visibility(target_menu, [nearby], player, range_units=30000.0)

        assert target_menu.GetObjectEntry(nearby).IsVisible() == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_out_of_range_ship_becomes_invisible():
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        far = _ship("Far", 100000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(far)

        update_target_list_visibility(target_menu, [far], player, range_units=30000.0)

        assert target_menu.GetObjectEntry(far).IsVisible() == 0
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_ship_pops_back_when_back_in_range():
    """Out → in transition flips visibility back to 1."""
    from engine.appc.subsystems import update_target_list_visibility

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        wanderer = _ship("Wanderer", 100000.0, 0.0, 0.0)
        target_menu.RebuildShipMenu(wanderer)
        update_target_list_visibility(target_menu, [wanderer], player, range_units=30000.0)
        assert target_menu.GetObjectEntry(wanderer).IsVisible() == 0

        wanderer.SetTranslateXYZ(500.0, 0.0, 0.0)
        update_target_list_visibility(target_menu, [wanderer], player, range_units=30000.0)
        assert target_menu.GetObjectEntry(wanderer).IsVisible() == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
