import pytest
import App
from engine.core.loop import GameLoop

TICK = 1.0 / 60.0


@pytest.fixture(autouse=True)
def reset_timer_managers():
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    yield
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()


def test_game_loop_initial_time():
    loop = GameLoop()
    assert loop.game_time == 0.0


def test_game_loop_tick_advances_game_time():
    loop = GameLoop()
    loop.tick()
    assert abs(loop.game_time - TICK) < 1e-9


def test_game_loop_advance_n_ticks():
    loop = GameLoop()
    loop.advance(60)
    assert abs(loop.game_time - 1.0) < 1e-6


def test_game_loop_tick_advances_realtime_manager():
    loop = GameLoop()
    loop.tick()
    assert abs(App.g_kRealtimeTimerManager.get_time() - TICK) < 1e-9


def test_game_loop_game_time_reads_timer_manager():
    loop = GameLoop()
    App.g_kTimerManager._time = 3.14
    assert loop.game_time == 3.14
    App.g_kTimerManager._time = 0.0
