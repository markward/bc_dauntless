"""
Integration test: M2Objects ship-creation and affiliation setup.

Verifies:
  1. CreateStartingObjects places real ShipClass objects in the Biranu1 set.
  2. Mission.GetFriendlyGroup() and GetEnemyGroup() contain the expected names.
  3. ShipClass_GetObject can retrieve a created ship from the set.
"""
import sys
import pytest
import App
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.ships import ShipClass, ShipClass_GetObject

_M2_PREFIXES = ("Custom.Tutorial",)


@pytest.fixture(autouse=True)
def game_context():
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kSetManager._sets.clear()
    yield game, episode, mission
    _set_current_game(None)
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kSetManager._sets.clear()
    for key in [k for k in sys.modules if k.startswith(_M2_PREFIXES)]:
        del sys.modules[key]
    for key in [k for k in sys.modules if k in ("loadspacehelper", "MissionLib",
                                                  "Systems.Biranu.Biranu1",
                                                  "Systems.Biranu.Biranu",
                                                  "ships.Galaxy")]:
        del sys.modules[key]


def test_create_starting_objects_places_ships(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    # Pre-create the set (normally done by CreateRegions/SetupSpaceSet)
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Biranu1")

    M2.CreateStartingObjects(mission)

    # Player and two Galaxy ships should be in the set
    player_ship = pSet.GetObject("player")
    galaxy1 = pSet.GetObject("Galaxy 1")
    galaxy2 = pSet.GetObject("Galaxy 2")
    assert isinstance(player_ship, ShipClass)
    assert isinstance(galaxy1, ShipClass)
    assert isinstance(galaxy2, ShipClass)


def test_friendly_group_populated(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Biranu1")

    M2.CreateStartingObjects(mission)

    friendlies = mission.GetFriendlyGroup()
    assert friendlies.IsNameInGroup("player")
    assert friendlies.IsNameInGroup("Galaxy 1")


def test_enemy_group_populated(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Biranu1")

    M2.CreateStartingObjects(mission)

    enemies = mission.GetEnemyGroup()
    assert enemies.IsNameInGroup("Galaxy 2")


def test_ship_class_get_object_finds_ships(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Biranu1")

    M2.CreateStartingObjects(mission)

    pShip = ShipClass_GetObject(pSet, "Galaxy 1")
    assert isinstance(pShip, ShipClass)
    assert pShip.GetName() == "Galaxy 1"


def test_create_regions_creates_biranu1_set(game_context):
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    M2.CreateRegions()

    pSet = App.g_kSetManager.GetSet("Biranu1")
    assert pSet is not None


def test_setup_ai_does_not_raise(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M2Objects.M2Objects as M2
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "Biranu1")
    M2.CreateStartingObjects(mission)

    M2.SetupAI()  # must not raise
