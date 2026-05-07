# Game-Loop Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `tools/gameloop_harness.py` that runs all 35 SDK missions through `Initialize()`, fires `ET_MISSION_START`, and advances `GameLoop` for N ticks — providing a continuous progress metric as engine implementation matures.

**Architecture:** `gameloop_harness.py` imports shared SDK machinery (`setup_sdk`, `discover_missions`, `_BASELINE_MODULES`) from `tools/mission_harness.py` rather than duplicating it. `run_mission_with_loop()` performs the same state reset as `run_mission()`, then additionally fires `ET_MISSION_START` and advances `engine.core.loop.GameLoop` for `n_ticks` ticks. Return type is a three-tuple `(status, exc, ticks_completed)` with status `"pass"`, `"init_fail"`, or `"loop_fail"`.

**Tech Stack:** Python 3.11+, pytest, existing `engine/core/loop.py` (`GameLoop`), `engine/appc/events.py` (`TGEvent`), `tools/mission_harness.py` (shared SDK loader machinery).

---

## File Map

- **Create:** `tools/gameloop_harness.py` — new harness; imports shared machinery from `tools.mission_harness`, implements `run_mission_with_loop()` and `main()`
- **Create:** `tests/integration/test_gameloop_harness.py` — integration tests for `run_mission_with_loop`

---

### Task 1: Write the (failing) test file

**Files:**
- Create: `tests/integration/test_gameloop_harness.py`

- [ ] **Step 1: Write the test file**

```python
"""
Integration tests for tools/gameloop_harness.py.

Uses M1Basic (the minimal SDK tutorial mission) as the known-good subject.
Requires the full SDK under sdk/Build/scripts/.
"""
import sys
import types
import pytest
import App
from engine.appc.timers import TGTimer_Create
from engine.appc.events import TGEvent


@pytest.fixture(scope="session", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


def test_run_mission_with_loop_importable():
    from tools.gameloop_harness import run_mission_with_loop
    assert callable(run_mission_with_loop)


def test_zero_ticks_pass(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=0
    )
    assert status == "pass"
    assert exc is None
    assert ticks == 0


def test_sixty_ticks_pass(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    assert status == "pass"
    assert exc is None
    assert ticks == 60


def test_init_fail_bad_module(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop("nonexistent.MissingMission", n_ticks=60)
    assert status == "init_fail"
    assert isinstance(exc, ModuleNotFoundError)
    assert ticks == 0


def test_loop_fail_bad_timer(sdk_setup):
    """Mission whose timer handler raises is reported as loop_fail."""
    _mod_name = "_test_crashing_mission"
    _mod = types.ModuleType(_mod_name)

    def crash_handler(pObj, pEvent):
        raise RuntimeError("intentional loop crash")

    def Initialize(pMission):
        timer = TGTimer_Create()
        evt = TGEvent()
        evt.SetEventType(App.ET_AI_TIMER)
        evt.SetDestination(pMission)
        timer.SetTimerStart(1.0 / 60.0)
        timer.SetDelay(0.0)
        timer.SetEvent(evt)
        App.g_kTimerManager.AddTimer(timer)
        pMission.AddPythonFuncHandlerForInstance(
            App.ET_AI_TIMER, f"{_mod_name}.crash_handler"
        )

    _mod.Initialize = Initialize
    _mod.crash_handler = crash_handler
    sys.modules[_mod_name] = _mod

    try:
        from tools.gameloop_harness import run_mission_with_loop
        status, exc, ticks = run_mission_with_loop(_mod_name, n_ticks=300)
        assert status == "loop_fail"
        assert isinstance(exc, RuntimeError)
        assert ticks < 300
    finally:
        sys.modules.pop(_mod_name, None)


def test_idempotent(sdk_setup):
    """Two consecutive calls on the same mission produce the same result."""
    from tools.gameloop_harness import run_mission_with_loop
    s1, _, t1 = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    s2, _, t2 = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    assert s1 == s2 == "pass"
    assert t1 == t2 == 60
```

- [ ] **Step 2: Run tests to verify they all fail with ImportError**

```bash
uv run pytest tests/integration/test_gameloop_harness.py -v 2>&1 | head -30
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'tools.gameloop_harness'` (or ImportError).

---

### Task 2: Harness skeleton + init phase (`status == "pass"` with `n_ticks=0` and `"init_fail"`)

**Files:**
- Create: `tools/gameloop_harness.py`

- [ ] **Step 1: Create the file with state reset + Initialize() only**

```python
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
from collections import Counter
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

    Returns (status, exc, ticks_completed) where status is one of:
      "pass"      — all n_ticks completed without exception
      "init_fail" — Initialize() raised; ticks_completed is 0
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
        mod = importlib.import_module(module_name)
        try:
            mod.Initialize(mission)
        except Exception as exc:
            return ("init_fail", exc, 0)

        return ("pass", None, ticks_done)
    except Exception as exc:
        return ("loop_fail", exc, ticks_done)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _mh._BASELINE_MODULES]:
            del sys.modules[key]
```

- [ ] **Step 2: Run zero-ticks and init-fail tests to verify they pass**

```bash
uv run pytest tests/integration/test_gameloop_harness.py::test_run_mission_with_loop_importable tests/integration/test_gameloop_harness.py::test_zero_ticks_pass tests/integration/test_gameloop_harness.py::test_init_fail_bad_module -v
```

Expected: all 3 PASS. `test_sixty_ticks_pass`, `test_loop_fail_bad_timer`, `test_idempotent` should still fail (ticks returns 0 instead of 60).

- [ ] **Step 3: Commit**

```bash
git add tools/gameloop_harness.py tests/integration/test_gameloop_harness.py
git commit -m "feat: add gameloop_harness skeleton with init phase"
```

---

### Task 3: Add game loop — ET_MISSION_START + tick advancement

**Files:**
- Modify: `tools/gameloop_harness.py` (lines after the inner `try/except` in `run_mission_with_loop`)

- [ ] **Step 1: Replace `return ("pass", None, ticks_done)` stub with loop**

In `tools/gameloop_harness.py`, replace this section inside `run_mission_with_loop`:

```python
        return ("pass", None, ticks_done)
    except Exception as exc:
        return ("loop_fail", exc, ticks_done)
```

With:

```python
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
```

- [ ] **Step 2: Run the full test suite to verify all six tests pass**

```bash
uv run pytest tests/integration/test_gameloop_harness.py -v
```

Expected output:
```
PASSED test_run_mission_with_loop_importable
PASSED test_zero_ticks_pass
PASSED test_sixty_ticks_pass
PASSED test_init_fail_bad_module
PASSED test_loop_fail_bad_timer
PASSED test_idempotent
6 passed
```

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
uv run pytest -q
```

Expected: all 207 tests pass (201 existing + 6 new), 0 failures.

- [ ] **Step 4: Commit**

```bash
git add tools/gameloop_harness.py
git commit -m "feat: complete gameloop_harness with ET_MISSION_START and tick loop"
```

---

### Task 4: Add `main()` and run baseline

**Files:**
- Modify: `tools/gameloop_harness.py` (append `main()` and `if __name__ == "__main__"` block)

- [ ] **Step 1: Append `main()` and CLI entry point to `tools/gameloop_harness.py`**

Add after the `run_mission_with_loop` function (before end of file):

```python
def _loop_error_key(exc: Exception) -> str:
    msg = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {msg[:80]}"


def main(n_ticks: int = _DEFAULT_TICKS) -> None:
    _mh.setup_sdk()
    missions = _mh.discover_missions()

    print("open_stbc game-loop harness")
    print("=" * 50)
    print(f"Found {len(missions)} missions, {n_ticks} ticks each (~{n_ticks / 60:.1f}s)\n")

    results: dict[str, tuple[str, "Exception | None", int]] = {}
    for name in missions:
        status, exc, ticks = run_mission_with_loop(name, n_ticks)
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
        errors: Counter[str] = Counter()
        for status, exc, ticks in results.values():
            if exc is not None:
                errors[_loop_error_key(exc)] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="open_stbc game-loop harness")
    parser.add_argument(
        "--ticks", type=int, default=_DEFAULT_TICKS,
        help=f"ticks per mission (default {_DEFAULT_TICKS} = ~5s at 60 Hz)"
    )
    args = parser.parse_args()
    main(args.ticks)
```

- [ ] **Step 2: Run the full test suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: 207 passed, 0 failed.

- [ ] **Step 3: Run the harness against all 35 missions (baseline reading)**

```bash
uv run python tools/gameloop_harness.py --ticks 300
```

This is the first baseline run. Record the PASS / INIT FAIL / LOOP FAIL counts — these become the starting benchmark for Phase 1 progress.

- [ ] **Step 4: Commit**

```bash
git add tools/gameloop_harness.py
git commit -m "feat: add main() and CLI to gameloop_harness; establish baseline"
```
