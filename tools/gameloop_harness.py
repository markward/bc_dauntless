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

# Make the C++-built _dauntless_host extension importable (mirrors tests/conftest.py).
_BUILD_PYTHON = _PROJECT_ROOT / "build" / "python"
if _BUILD_PYTHON.is_dir() and str(_BUILD_PYTHON) not in sys.path:
    sys.path.insert(0, str(_BUILD_PYTHON))

import tools.mission_harness as _mh
import App as _App  # imported at module level so App is in _BASELINE_MODULES and persists across runs

_LOOP_TIMEOUT = 30  # seconds — longer than initialize-only (15 s)
_DEFAULT_TICKS = 36000  # ~10 minutes at 60 Hz


def _return(status, exc, ticks_done, state=None, return_state=False):
    """Return a 3-tuple by default, 4-tuple when return_state=True.

    state is None for init_fail (mission never built); populated for
    pass/loop_fail paths so callers can inspect post-run mission state.
    """
    if return_state:
        return (status, exc, ticks_done, state)
    return (status, exc, ticks_done)


def run_mission_with_loop(
    module_name: str,
    n_ticks: int = _DEFAULT_TICKS,
    profile: bool = False,
    return_state: bool = False,
):
    """Initialize mission, fire ET_MISSION_START, advance GameLoop for n_ticks.

    Caller must invoke _mh.setup_sdk() before calling this function.

    Returns (status, exc, ticks_completed) where status is one of:
      "pass"      — all n_ticks completed without exception
      "init_fail" — Initialize() or import raised; ticks_completed is 0
      "loop_fail" — exception during loop; ticks_completed < n_ticks

    When ``return_state=True``, returns a 4-tuple
    (status, exc, ticks_completed, state) where ``state`` is a dict
    captured INSIDE the try block (before the finally cleanup tears down
    sys.modules and the current-game pointer). For init_fail, state is
    None — the mission was never built.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.events import TGEvent
    import App

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    # Delegate to host_loop's reset so we don't drift: it clears all the
    # globals AND re-registers the engine's keyboard-dispatch broadcast
    # handler.  A previous duplicated reset body here dropped the handler
    # and silently broke the firing chain in any integration test that
    # ran after the harness.
    from engine.host_loop import reset_sdk_globals
    reset_sdk_globals()
    if profile:
        App._stub_tracker.set_mission(module_name)
        App._emission_recorder.set_mission(module_name)

    ticks_done = 0

    def _alarm_handler(signum, frame):
        raise TimeoutError(f"timed out after {_LOOP_TIMEOUT}s")

    def _capture_state():
        if not return_state:
            return None
        return {
            "mission": mission,
            "episode": episode,
            "game": game,
            "set_manager": App.g_kSetManager,
        }

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(_LOOP_TIMEOUT)
    try:
        try:
            mod = importlib.import_module(module_name)
            mod.Initialize(mission)
        except Exception as exc:
            return _return("init_fail", exc, 0, None, return_state)

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

        return _return("pass", None, ticks_done, _capture_state(), return_state)
    except Exception as exc:
        return _return("loop_fail", exc, ticks_done, _capture_state(), return_state)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        if profile:
            App._stub_tracker.reset_mission()
            App._emission_recorder.reset_mission()
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _mh._BASELINE_MODULES]:
            del sys.modules[key]


def _loop_error_key(exc: Exception) -> str:
    msg = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {msg[:80]}"


_PROFILE_ROWS = 50


def _print_profile_report(n_ticks: int, n_missions: int) -> None:
    rows = _App._stub_tracker.report()
    print(f"\nStub call profile  ({n_ticks} ticks × {n_missions} missions)")
    print("─" * 62)
    if not rows:
        print("  (no stub calls recorded)")
        return
    print(f"  {'Rank':>4}  {'Stub method':<40}  {'Missions':>8}  {'Calls':>5}")
    for rank, (name, mission_count, total_calls) in enumerate(rows[:_PROFILE_ROWS], 1):
        print(f"  {rank:>4}  {name:<40}  {mission_count:>8}  {total_calls:>5}")
    if len(rows) > _PROFILE_ROWS:
        print(f"  ... {len(rows) - _PROFILE_ROWS} more rows omitted")


def _print_color_consumer_report() -> None:
    rows = _App._color_consumer_tracker.report()
    print(f"\nColor consumer report  ({len(rows)} unique (setter, mission, caller, rgba) tuples)")
    print("─" * 110)
    if not rows:
        print("  (no TGColorA-bearing stub calls recorded — enable producers first)")
        return
    # Per-setter rollup: which engine surfaces matter most, and across how many missions.
    from collections import defaultdict
    by_setter: dict = defaultdict(lambda: {"missions": set(), "calls": 0, "callers": set()})
    for name, mission, caller, _rgba, count in rows:
        by_setter[name]["missions"].add(mission)
        by_setter[name]["calls"] += count
        by_setter[name]["callers"].add(caller)
    print(f"  {'Rank':>4}  {'Setter':<48}  {'Missions':>8}  {'Calls':>6}  {'Callers':>7}")
    summary = sorted(
        by_setter.items(), key=lambda kv: (-len(kv[1]["missions"]), -kv[1]["calls"], kv[0])
    )
    for rank, (name, agg) in enumerate(summary, 1):
        print(
            f"  {rank:>4}  {name:<48}  {len(agg['missions']):>8}  {agg['calls']:>6}  {len(agg['callers']):>7}"
        )

    # Detail dump grouped by setter — first 5 distinct callers each.
    print("\nDetail (first 5 callers per setter):")
    for name, agg in summary:
        print(f"\n  {name}  [{agg['calls']} calls, {len(agg['missions'])} missions]")
        callers = sorted(agg["callers"])[:5]
        for c in callers:
            print(f"      {c}")


def main(n_ticks: int = _DEFAULT_TICKS, profile: bool = False, color_consumers: bool = False) -> None:
    _mh.setup_sdk()
    missions = _mh.discover_missions()
    if color_consumers:
        _App._color_consumer_tracker.enable()
        # color recording needs the per-mission tag the stub tracker maintains
        profile = True

    print("open_stbc game-loop harness")
    print("=" * 50)
    print(f"Found {len(missions)} missions, {n_ticks} ticks each (~{n_ticks / 60:.1f}s)\n")

    results: dict[str, tuple[str, "Exception | None", int]] = {}
    for name in missions:
        status, exc, ticks = run_mission_with_loop(name, n_ticks, profile=profile)
        results[name] = (status, exc, ticks)
        if status == "pass":
            print(f"  PASS  {name} ({ticks}/{n_ticks} ticks)")
        elif status == "init_fail":
            err = (str(exc).splitlines() or [""])[0][:80]
            print(f"  INIT  {name}")
            print(f"         {type(exc).__name__}: {err}")
        else:
            err = (str(exc).splitlines() or [""])[0][:80]
            print(f"  LOOP  {name} ({ticks}/{n_ticks} ticks)")
            print(f"         {type(exc).__name__}: {err}")

    passed = sum(1 for s, _, _ in results.values() if s == "pass")
    init_fail = sum(1 for s, _, _ in results.values() if s == "init_fail")
    loop_fail = sum(1 for s, _, _ in results.values() if s == "loop_fail")

    print(f"\n{'=' * 50}")
    print(f"PASS:      {passed:3d}")
    print(f"INIT FAIL: {init_fail:3d}")
    print(f"LOOP FAIL: {loop_fail:3d}")
    print(f"Total:     {len(results):3d}")

    if init_fail + loop_fail:
        from collections import Counter
        errors: Counter[str] = Counter()
        for status, exc, ticks in results.values():
            if exc is not None:
                errors[_loop_error_key(exc)] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")

    if profile:
        _print_profile_report(n_ticks, len(missions))
    if color_consumers:
        _print_color_consumer_report()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="open_stbc game-loop harness")
    parser.add_argument(
        "--ticks", type=int, default=_DEFAULT_TICKS,
        help=f"ticks per mission (default {_DEFAULT_TICKS} = ~10 min at 60 Hz)"
    )
    parser.add_argument(
        "--profile", action="store_true",
        help="print ranked stub call profile after the run"
    )
    parser.add_argument(
        "--color-consumers", action="store_true",
        help="record every stub call that receives a TGColorA and dump a per-setter consumer report"
    )
    args = parser.parse_args()
    main(args.ticks, profile=args.profile, color_consumers=args.color_consumers)
