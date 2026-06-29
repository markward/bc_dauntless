import pytest
from engine.core.game import Game, Episode, Mission, Game_GetCurrentGame, _set_current_game
from engine.appc.events import TGEventHandlerObject


def test_game_episode_mission_chain():
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    assert Game_GetCurrentGame() is game
    assert Game_GetCurrentGame().GetCurrentEpisode() is episode
    assert Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission() is mission


def test_no_game_returns_none():
    _set_current_game(None)
    assert Game_GetCurrentGame() is None


def test_mission_is_event_handler():
    mission = Mission()
    assert isinstance(mission, TGEventHandlerObject)


def test_mission_set_database_loads_tgl_and_returns_it():
    # SDK: g_pMissionDatabase = pMission.SetDatabase("data/TGL/.../E1M1.tgl").
    # The returned DB must resolve the mission's lines (text + voice wav), and
    # GetDatabase() must return the same object so MissionLib.GetMissionDatabase
    # works. Without this, mission VO lines collapse to zero duration.
    mission = Mission()
    db = mission.SetDatabase("data/TGL/Maelstrom/Episode 1/E1M1.tgl")
    assert db is not None
    assert mission.GetDatabase() is db
    assert db.HasString("E1M1Briefing1")
    assert "Admiral Liu" in db.GetString("E1M1Briefing1")
    assert db.GetFilename("E1M1Briefing1").endswith("E1M1Briefing1.mp3")


def test_mission_set_database_accepts_db_object():
    # Non-string arg (an already-loaded DB) is stored as-is and returned.
    mission = Mission()
    sentinel = object()
    assert mission.SetDatabase(sentinel) is sentinel
    assert mission.GetDatabase() is sentinel


def test_mission_get_database_default_none():
    assert Mission().GetDatabase() is None


def test_game_get_player_initially_none():
    from engine.core.game import Game
    g = Game()
    assert g.GetPlayer() is None


def test_game_set_and_get_player():
    from engine.core.game import Game
    g = Game()
    sentinel = object()
    g.SetPlayer(sentinel)
    assert g.GetPlayer() is sentinel


def test_game_get_player_set_returns_player_ships_set():
    # SDK Conditions/FriendliesInPlayerSetStronger.py:88 calls
    # pGame.GetPlayerSet() to find the set the player ship is in.
    import App
    from engine.appc.ships import ShipClass

    pSet = App.SetClass_Create()
    pSet.SetName("S")
    player = ShipClass()
    pSet.AddObjectToSet(player, "Player")

    g = Game()
    g.SetPlayer(player)
    assert g.GetPlayerSet() is pSet


def test_game_get_player_set_none_when_no_player():
    g = Game()
    assert g.GetPlayerSet() is None
