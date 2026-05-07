"""
Game-loop harness for open_stbc.

Discovers all SDK mission scripts, calls Initialize(pMission), fires
ET_MISSION_START, and advances the GameLoop for N ticks.  Reports per-mission
status and a grouped failure summary.

Usage:
    uv run python tools/gameloop_harness.py
    uv run python tools/gameloop_harness.py --ticks 600
"""
import argparse
import importlib
import signal
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tools.mission_harness as _mh

_LOOP_TIMEOUT = 30  # seconds — longer than initialize-only (15 s)
_DEFAULT_TICKS = 300  # ~5 seconds at 60 Hz


def run_mission_with_loop(
    module_name: str, n_ticks: int = _DEFAULT_TICKS
) -> "tuple[str, Exception | None, int]":
    """Initialize mission, fire ET_MISSION_START, advance GameLoop for n_ticks.

    Caller must invoke _mh.setup_sdk() before calling this function.

    Returns (status, exc, ticks_completed) where status is one of:
      "pass"      — all n_ticks completed without exception
      "init_fail" — Initialize() or import raised; ticks_completed is 0
      "loop_fail" — exception during loop; ticks_completed < n_ticks
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.events import TGEvent
    import App
    from engine.appc.placement import _waypoint_registry

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kSetManager._sets.clear()
    _waypoint_registry.clear()
    App._next_event_type_id = 200

    ticks_done = 0

    def _alarm_handler(signum, frame):
        raise TimeoutError(f"timed out after {_LOOP_TIMEOUT}s")

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(_LOOP_TIMEOUT)
    try:
        try:
            mod = importlib.import_module(module_name)
            mod.Initialize(mission)
        except Exception as exc:
            return ("init_fail", exc, 0)

        # Fire ET_MISSION_START — episode is destination, broadcast handlers also fire
        start_evt = TGEvent()
        start_evt.SetEventType(App.ET_MISSION_START)
        start_evt.SetDestination(episode)
        App.g_kEventManager.AddEvent(start_evt)

        from engine.core.loop import GameLoop
        loop = GameLoop()
        for i in range(n_ticks):
            loop.tick()
            ticks_done = i + 1

        return ("pass", None, ticks_done)
    except Exception as exc:
        return ("loop_fail", exc, ticks_done)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _mh._BASELINE_MODULES]:
            del sys.modules[key]
