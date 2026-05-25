# tests/integration/test_target_list_sdk_integration.py
"""Load real SDK scripts against the target_menu shim."""
import App
from engine.appc.ships import ShipClass


def test_sdk_create_target_list_constructs_singleton():
    App._reset_target_menu_singleton()
    import Bridge.TacticalMenuHandlers as TMH
    pTacticalWindow = App.TacticalControlWindow_GetTacticalControlWindow()

    pPane = TMH.CreateTargetList(pTacticalWindow)

    assert pPane is not None
    assert isinstance(App.STTargetMenu_GetTargetMenu(), App.STTargetMenu)


def _populate_target_menu(target_menu, names):
    ships = []
    for n in names:
        ship = ShipClass(); ship.SetName(n)
        target_menu.AddChild(App.STSubsystemMenu(ship, n))
        ships.append(ship)
    return ships


def test_sdk_cycle_target_walks_visible_ships():
    from engine.core.game import Game, Episode, Mission, _set_current_game

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    ships = _populate_target_menu(target_menu, ["A", "B", "C"])

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)

    try:
        import TacticalInterfaceHandlers as TIH
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[1]
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[2]
        TIH.CycleTarget(1)  # wrap
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(0)  # reverse
        assert player.GetTarget() is ships[2]
    finally:
        _set_current_game(None)


def test_sdk_cycle_target_skips_invisible():
    from engine.core.game import Game, Episode, Mission, _set_current_game

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    ships = _populate_target_menu(target_menu, ["A", "B", "C"])
    target_menu.GetObjectEntry(ships[1]).SetNotVisible()

    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)

    try:
        import TacticalInterfaceHandlers as TIH
        TIH.CycleTarget(1)
        assert player.GetTarget() is ships[0]
        TIH.CycleTarget(1)
        # B hidden → skip to C.
        assert player.GetTarget() is ships[2]
    finally:
        _set_current_game(None)
