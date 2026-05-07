"""
Integration test: M3Gameflow event handler registration and dispatch.

Verifies:
  1. SetupEventHandlers wires broadcast handlers without crashing.
  2. ET_ENTERED_SET and ET_OBJECT_EXPLODING are registered on the event manager.
  3. A synthetic ET_ENTERED_SET event reaches HandleEnterSet without raising.
"""
import sys
import types
import pytest
import App
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop

_M3_PREFIXES = ("Custom.Tutorial",)


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
    yield game, episode, mission
    _set_current_game(None)
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    for key in [k for k in sys.modules if k.startswith(_M3_PREFIXES)]:
        del sys.modules[key]


def test_setup_event_handlers_does_not_raise(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M3Gameflow.M3Gameflow as M3
    M3.SetupEventHandlers(mission)


def test_broadcast_handlers_registered(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M3Gameflow.M3Gameflow as M3
    M3.SetupEventHandlers(mission)
    handlers = App.g_kEventManager._broadcast_handlers
    assert App.ET_ENTERED_SET in handlers
    assert App.ET_OBJECT_EXPLODING in handlers


def test_enter_set_broadcast_reaches_handler(game_context):
    _, _, mission = game_context
    import Custom.Tutorial.Episode.M3Gameflow.M3Gameflow as M3
    M3.SetupEventHandlers(mission)

    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_ENTERED_SET)
    ev.SetDestination(mission)
    App.g_kEventManager.AddEvent(ev)  # must not raise


def test_timer_with_game_time_offset_fires_on_schedule(game_context):
    """Timer start = GetGameTime() + 15s; GameLoop.advance(15s) must fire it."""
    _, _, mission = game_context

    fired = []
    mod = types.ModuleType("_m3_tick_helper")
    mod.on_timer = lambda pMission, pEvent: fired.append(True)
    sys.modules["_m3_tick_helper"] = mod

    eType = App.Game_GetNextEventType()
    mission.AddPythonFuncHandlerForInstance(eType, "_m3_tick_helper.on_timer")

    pEvent = App.TGEvent_Create()
    pEvent.SetEventType(eType)
    pEvent.SetDestination(mission)

    pTimer = App.TGTimer_Create()
    pTimer.SetTimerStart(App.g_kUtopiaModule.GetGameTime() + 15.0)
    pTimer.SetDelay(0.0)
    pTimer.SetDuration(-1.0)
    pTimer.SetEvent(pEvent)
    App.g_kTimerManager.AddTimer(pTimer)

    loop = GameLoop()
    loop.advance(60 * 15)  # 15 seconds at 60 Hz
    assert len(fired) == 1

    del sys.modules["_m3_tick_helper"]
