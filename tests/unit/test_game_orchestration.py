"""Game -> Episode -> Mission orchestration cascade.

Mirrors the SDK QuickBattle entry chain (read-only ground truth):
  QuickBattleGame.Initialize(pGame) -> pGame.LoadEpisode("QuickBattle.QuickBattleEpisode")
  QuickBattleEpisode.Initialize(pEpisode) -> pEpisode.LoadMission("QuickBattle.QuickBattle", evt)
  <mission module>.Initialize(pMission)

These tests exercise the synchronous nested-load orchestration the SDK relies
on, using lightweight stub modules registered in sys.modules.
"""
import sys
import types

import pytest

from engine.core.game import (
    Game,
    Episode,
    Mission,
    Game_GetCurrentGame,
    _set_current_game,
)


@pytest.fixture(autouse=True)
def _reset_current_game():
    _set_current_game(None)
    yield
    _set_current_game(None)


def _make_stub_module(name, **funcs):
    """Register a throwaway module in sys.modules and remove it on teardown."""
    mod = types.ModuleType(name)
    for fn_name, fn in funcs.items():
        setattr(mod, fn_name, fn)
    sys.modules[name] = mod
    return mod


def test_load_episode_imports_and_initializes(request):
    seen = {}

    def Initialize(pEpisode):
        seen["episode"] = pEpisode

    _make_stub_module("test_stub_episode", Initialize=Initialize)
    request.addfinalizer(lambda: sys.modules.pop("test_stub_episode", None))

    game = Game()
    episode = game.LoadEpisode("test_stub_episode")

    # The created Episode is returned and wired as current on the game.
    assert isinstance(episode, Episode)
    assert game.GetCurrentEpisode() is episode
    # The module's Initialize ran with the new episode.
    assert seen["episode"] is episode


def test_load_mission_imports_initializes_and_posts_start_event(request):
    from engine.appc.events import TGEvent
    import App

    calls = []

    def Initialize(pMission):
        calls.append(("init", pMission))

    def PreLoadAssets(pMission):
        calls.append(("preload", pMission))

    _make_stub_module(
        "test_stub_mission", Initialize=Initialize, PreLoadAssets=PreLoadAssets
    )
    request.addfinalizer(lambda: sys.modules.pop("test_stub_mission", None))

    posted = []
    real_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: posted.append(evt)
    request.addfinalizer(
        lambda: setattr(App.g_kEventManager, "AddEvent", real_add)
    )

    episode = Episode()
    start_evt = TGEvent()
    start_evt.SetEventType(App.ET_MISSION_START)

    mission = episode.LoadMission("test_stub_mission", start_evt)

    assert isinstance(mission, Mission)
    assert episode.GetCurrentMission() is mission
    # PreLoadAssets ran (when present) before Initialize.
    assert calls == [("preload", mission), ("init", mission)]
    # The start event was posted to the event manager.
    assert posted == [start_evt]


def test_load_mission_without_preload_assets(request):
    from engine.appc.events import TGEvent
    import App

    calls = []

    def Initialize(pMission):
        calls.append(pMission)

    _make_stub_module("test_stub_mission_nopre", Initialize=Initialize)
    request.addfinalizer(lambda: sys.modules.pop("test_stub_mission_nopre", None))

    posted = []
    real_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: posted.append(evt)
    request.addfinalizer(
        lambda: setattr(App.g_kEventManager, "AddEvent", real_add)
    )

    episode = Episode()
    start_evt = TGEvent()
    mission = episode.LoadMission("test_stub_mission_nopre", start_evt)

    assert calls == [mission]
    assert posted == [start_evt]


def test_load_mission_none_start_event_does_not_post(request):
    import App

    def Initialize(pMission):
        pass

    _make_stub_module("test_stub_mission_noevt", Initialize=Initialize)
    request.addfinalizer(lambda: sys.modules.pop("test_stub_mission_noevt", None))

    posted = []
    real_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: posted.append(evt)
    request.addfinalizer(
        lambda: setattr(App.g_kEventManager, "AddEvent", real_add)
    )

    episode = Episode()
    mission = episode.LoadMission("test_stub_mission_noevt", None)

    assert episode.GetCurrentMission() is mission
    assert posted == []


def test_load_mission_start_event_destination_is_episode(request):
    from engine.appc.events import TGEvent
    import App

    _make_stub_module("test_stub_mission_dest", Initialize=lambda m: None)
    request.addfinalizer(lambda: sys.modules.pop("test_stub_mission_dest", None))

    real_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: None
    request.addfinalizer(
        lambda: setattr(App.g_kEventManager, "AddEvent", real_add)
    )

    episode = Episode()
    start_evt = TGEvent()
    episode.LoadMission("test_stub_mission_dest", start_evt)

    # Mirrors _init_mission: the ET_MISSION_START event targets the episode.
    assert start_evt.GetDestination() is episode


def test_set_preload_done_event_stores_event():
    game = Game()
    # Starts as None.
    assert game._preload_done_event is None
    sentinel = object()
    game.SetPreLoadDoneEvent(sentinel)
    assert game._preload_done_event is sentinel


def test_et_preload_done_constant_exists():
    import App
    # Distinct stable integer constant, contiguous with the Phase-1 ET block.
    assert isinstance(App.ET_PRELOAD_DONE, int)
    assert App.ET_PRELOAD_DONE != App.ET_MISSION_START
