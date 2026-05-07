"""
Integration test: MissionLib.CreateTimer fires a Python callback.

Full path exercised:
  MissionLib.CreateTimer
    -> App.TGEvent_Create / App.TGTimer_Create
    -> App.g_kTimerManager.AddTimer
    -> App.g_kTimerManager.tick(delta)
    -> TGEventManager.AddEvent
    -> Mission.ProcessEvent
    -> registered Python callback
"""
import sys
import types
import pytest
import App
from engine.core.game import Game, Episode, Mission, _set_current_game

TICK = 1.0 / 60.0


@pytest.fixture(autouse=True)
def game_context():
    """Set up a minimal Game/Episode/Mission stack for MissionLib."""
    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield game, episode, mission
    _set_current_game(None)
    # Reset timer manager state between tests
    App.g_kTimerManager._timers.clear()


def test_create_timer_fires_callback(game_context):
    _, _, mission = game_context

    fired = []

    mod = types.ModuleType("tests.integration.test_missionlib_timer_helper")
    mod.on_timer = lambda pObj, pEv: fired.append(True)
    sys.modules["tests.integration.test_missionlib_timer_helper"] = mod

    import MissionLib
    MissionLib.CreateTimer(
        App.ET_AI_TIMER,
        "tests.integration.test_missionlib_timer_helper.on_timer",
        fStart=TICK,
        fDelay=0.0,
        fDuration=-1.0,
    )

    # Should not have fired yet
    assert fired == []

    # One tick — fires
    App.g_kTimerManager.tick(TICK)
    assert fired == [True]

    # One-shot: does not fire again
    App.g_kTimerManager.tick(TICK)
    assert fired == [True]
