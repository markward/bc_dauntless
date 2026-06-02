# Fixed-Timestep Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `engine.core.loop.GameLoop.tick()` advance exactly 60 times per real second regardless of monitor refresh rate, by inserting a Fiedler accumulator between the vsync-bound render loop and the sim loop.

**Architecture:** A pure helper function `step_accumulator(accumulator, frame_dt, tick_dt, max_frame_dt) -> (new_accumulator, n_ticks)` lives in a new module `engine/core/timestep.py`. The host loop in `engine/host_loop.py` calls it once per render frame, then runs `loop.tick()` n times. While paused, `frame_dt` is forced to zero so the accumulator never grows during pause. Tests exercise the pure helper in isolation; the host-loop change is verified by build + manual smoke.

**Tech Stack:** Python (host loop, sim, tests), C++ renderer host (untouched), CMake build system. Time primitive: `time.monotonic()`.

**Spec:** [docs/superpowers/specs/2026-06-02-fixed-timestep-sim-design.md](../specs/2026-06-02-fixed-timestep-sim-design.md)

---

## Task 0: Set up feature branch

**Files:**
- None (git operation only).

- [ ] **Step 1: Create and switch to a feature branch off main**

```bash
git checkout -b fixed-timestep-sim
```

- [ ] **Step 2: Confirm working tree is clean and on the new branch**

Run: `git status && git branch --show-current`
Expected: `working tree clean`, branch `fixed-timestep-sim`.

---

## Task 1: Pure accumulator helper (TDD)

The accumulator math is pure — no side effects, no engine dependencies — so it can be developed and tested in complete isolation from the host loop.

**Files:**
- Create: `engine/core/timestep.py`
- Create: `tests/unit/test_timestep.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_timestep.py`:

```python
"""Pure-function unit tests for the fixed-timestep accumulator.

The accumulator is independent of GameLoop and the renderer, so these
tests need no fixtures and run in milliseconds.
"""

from engine.core.timestep import step_accumulator

TICK_DT = 1.0 / 60.0
MAX_FRAME_DT = 0.25


def test_steady_state_60hz_emits_one_tick_per_frame():
    """At 60 Hz render, every frame produces exactly 1 sim tick."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(600):  # 10 seconds at 60 Hz
        accumulator, n = step_accumulator(
            accumulator, 1.0 / 60.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    assert total_ticks == 600
    assert accumulator < TICK_DT  # never grows unbounded


def test_120hz_render_emits_60hz_sim():
    """At 120 Hz render, sim still produces 60 ticks per real second."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(1200):  # 10 seconds at 120 Hz
        accumulator, n = step_accumulator(
            accumulator, 1.0 / 120.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    # Floating-point drift can give 599 or 600; both are acceptable.
    assert 599 <= total_ticks <= 600


def test_variable_deltas_emit_correct_tick_count():
    """Tick count matches floor(sum(deltas) / TICK_DT) within +-1."""
    deltas = [1.0 / 60.0, 1.0 / 120.0, 1.0 / 30.0, 1.0 / 240.0] * 100
    accumulator = 0.0
    total_ticks = 0
    for d in deltas:
        accumulator, n = step_accumulator(
            accumulator, d, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    expected = int(sum(deltas) / TICK_DT)
    assert abs(total_ticks - expected) <= 1


def test_stall_clamped_to_cap():
    """A 1-second stall produces at most ~15 ticks, not 60."""
    accumulator, n = step_accumulator(
        0.0, 1.0, TICK_DT, MAX_FRAME_DT
    )
    # MAX_FRAME_DT = 0.25; 0.25 / (1/60) = 15 exact ticks.
    # Floating-point residual drift can land on 14 or 15.
    assert n <= 15
    assert n >= 14
    # Accumulator should hold the leftover (< 1 tick).
    assert accumulator < TICK_DT


def test_pause_zero_dt_no_ticks():
    """When frame_dt is 0 (simulating paused frames), no ticks emit."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(600):  # 10 seconds of paused frames
        accumulator, n = step_accumulator(
            accumulator, 0.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    assert total_ticks == 0
    assert accumulator == 0.0


def test_negative_dt_treated_as_zero():
    """Defensive: a clock that steps backward (shouldn't happen with
    monotonic but be safe) does not produce negative ticks or shrink
    the accumulator."""
    accumulator, n = step_accumulator(
        0.5, -0.1, TICK_DT, MAX_FRAME_DT
    )
    # No new ticks should arise from the negative delta; accumulator
    # shouldn't grow beyond its pre-call value plus a clamped frame_dt.
    # The simplest acceptable behavior is: clamp frame_dt to 0.
    assert n >= 0
    assert accumulator <= 0.5 + 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_timestep.py -v`
Expected: `ImportError` or `ModuleNotFoundError: No module named 'engine.core.timestep'`.

- [ ] **Step 3: Write the minimal implementation**

Create `engine/core/timestep.py`:

```python
"""Fixed-timestep accumulator helper.

Decouples simulation cadence from render frame rate using Glenn
Fiedler's "Fix Your Timestep" pattern. Pure function: no engine
dependencies, no side effects, trivially testable.

Used by `engine.host_loop.run()` once per render frame.
"""


def step_accumulator(accumulator, frame_dt, tick_dt, max_frame_dt):
    """Advance the accumulator by one render frame's wall-clock delta.

    Returns (new_accumulator, n_ticks). The caller is responsible for
    invoking the sim-tick callable exactly n_ticks times.

    - frame_dt is clamped to [0, max_frame_dt]. The lower bound guards
      against a backward-stepping clock (shouldn't happen with
      monotonic() but defensive). The upper bound is the
      spiral-of-death cap: after a stalled render frame, we accept
      that some game time is lost rather than chain unbounded ticks
      into the next frame.
    - Steady-state sim rate is 1 / tick_dt regardless of render rate.
    """
    if frame_dt < 0.0:
        frame_dt = 0.0
    elif frame_dt > max_frame_dt:
        frame_dt = max_frame_dt
    accumulator += frame_dt
    n = 0
    while accumulator >= tick_dt:
        n += 1
        accumulator -= tick_dt
    return accumulator, n
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_timestep.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Confirm GameLoop regression tests still pass**

Run: `uv run pytest tests/unit/test_loop.py -v`
Expected: all existing tests PASS — `engine/core/loop.py` was not touched.

- [ ] **Step 6: Commit**

```bash
git add engine/core/timestep.py tests/unit/test_timestep.py
git commit -m "$(cat <<'EOF'
feat(core): pure-function fixed-timestep accumulator

Adds engine.core.timestep.step_accumulator, a side-effect-free helper
that computes how many sim ticks the host loop should run for a given
render-frame delta. Implements the Fiedler accumulator pattern with a
spiral-of-death cap (MAX_FRAME_DT clamp) and defensive zero-clamp on
backward time. Tested in isolation; not yet wired into the host loop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire the accumulator into the host loop

Replace the per-frame `loop.tick()` callsite in `engine/host_loop.py` with the accumulator. Re-gate the camera follow-up on `ticks_this_frame > 0` instead of `not pause.is_open`. Move the HUD tick counter from "once per render frame" to "once per sim tick" so the diagnostic readout reflects the true sim rate.

**Files:**
- Modify: `engine/host_loop.py:2205-2216` (HUD setup block — add MAX_FRAME_DT, accumulator, previous_real_time)
- Modify: `engine/host_loop.py:2305-2319` (HUD tick-count emission — change tick-counting source)
- Modify: `engine/host_loop.py:2378-2392` (the `loop.tick()` callsite and the pending_swap drain)

- [ ] **Step 1: Read the current host-loop callsite to confirm line numbers**

Run: `grep -n "loop.tick()\|loop = GameLoop\|_hud_tick_count\|pending_swap\|TICK_DT" engine/host_loop.py | head -30`
Expected: lines roughly matching the modify ranges above. If the file has drifted, adjust the edits to the actual line numbers — the code shape is what matters, not the literal numbers.

- [ ] **Step 2: Add MAX_FRAME_DT constant and initialise accumulator state**

In `engine/host_loop.py`, locate the block that currently reads (around line 2209):

```python
        TICK_DT = 1.0 / 60.0

        loop = GameLoop()
        ticks = 0
        init_audio()
        _bootstrap_firing_pipeline()

        # Diagnostic HUD: measure sim ticks per real second to confirm
        # whether the loop runs faster than 60 Hz (which would scale
        # shield-regen and every other dt-driven system proportionally).
        # Refresh rate is read once; tick rate is sampled every wall second.
        import time as _time_dbg
        _hud_monitor_hz = (_h.get_monitor_refresh_rate()
                           if _h is not None and hasattr(_h, "get_monitor_refresh_rate")
                           else 0)
        _hud_last_emit = _time_dbg.time()
        _hud_tick_count = 0
```

Replace it with:

```python
        TICK_DT = 1.0 / 60.0
        MAX_FRAME_DT = 0.25  # Fiedler spiral-of-death cap; only matters on stalled frames

        loop = GameLoop()
        ticks = 0
        init_audio()
        _bootstrap_firing_pipeline()

        # Fixed-timestep accumulator state. Sim runs at TICK_DT (60 Hz)
        # regardless of render refresh rate. See
        # engine/core/timestep.py and the spec at
        # docs/superpowers/specs/2026-06-02-fixed-timestep-sim-design.md.
        import time as _time_dbg
        from engine.core.timestep import step_accumulator
        _previous_real_time = _time_dbg.monotonic()
        _accumulator = 0.0

        # Diagnostic HUD: measure sim ticks per real second. Once the
        # accumulator is wired correctly, this reads ~60 on any display.
        _hud_monitor_hz = (_h.get_monitor_refresh_rate()
                           if _h is not None and hasattr(_h, "get_monitor_refresh_rate")
                           else 0)
        _hud_last_emit = _time_dbg.monotonic()
        _hud_tick_count = 0
```

Note: `time.monotonic()` replaces `time.time()` everywhere in this block. `monotonic` cannot step backward.

- [ ] **Step 3: Replace the per-frame tick block with the accumulator**

Locate the block that currently reads (around line 2378):

```python
            # --- Sim advance (skipped while paused) ---
            if not pause.is_open:
                loop.tick()

                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    cam_control.snap()
            else:
                had_pending_swap = False
```

Replace it with:

```python
            # --- Sim advance: fixed-timestep accumulator ---
            # frame_dt is the real wall-clock since the previous frame.
            # During pause we force it to 0 so the accumulator cannot
            # grow and there is no catch-up burst on resume. The cap
            # bounds the inner while-loop after a stalled render frame.
            _now = _time_dbg.monotonic()
            _frame_dt = _now - _previous_real_time
            _previous_real_time = _now
            if pause.is_open:
                _frame_dt = 0.0
            _accumulator, _sim_ticks_this_frame = step_accumulator(
                _accumulator, _frame_dt, TICK_DT, MAX_FRAME_DT
            )
            for _ in range(_sim_ticks_this_frame):
                loop.tick()
                _hud_tick_count += 1

            # Camera follow-up runs whenever at least one sim tick fired
            # this frame (previously gated on `not pause.is_open`,
            # equivalent because tick-per-frame meant tick == not paused).
            if _sim_ticks_this_frame > 0:
                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    cam_control.snap()
            else:
                had_pending_swap = False
```

- [ ] **Step 4: Remove the now-redundant per-render-frame HUD increment**

Locate the HUD emission block that currently reads (around line 2305):

```python
                # Debug HUD push — once per real second, derive the actual
                # tick rate from the wall-clock delta between samples.
                _hud_tick_count += 1
                _hud_now = _time_dbg.time()
                _hud_dt = _hud_now - _hud_last_emit
                if _hud_dt >= 1.0:
                    _hud_fps = _hud_tick_count / _hud_dt
                    _h.cef_execute_javascript(
                        "setDebugHud(" + repr(_hud_fps) + ", " +
                        repr(_hud_monitor_hz) + ");"
                    )
                    _hud_last_emit = _hud_now
                    _hud_tick_count = 0
```

Replace it with (drop the per-frame increment — `_hud_tick_count` is now incremented inside the accumulator loop in Step 3 — and switch the timestamp to `monotonic`):

```python
                # Debug HUD push — once per real second, derive the actual
                # sim tick rate from the wall-clock delta between samples.
                # Counter is incremented inside the accumulator loop, so
                # the reading reflects true sim ticks (not render frames).
                _hud_now = _time_dbg.monotonic()
                _hud_dt = _hud_now - _hud_last_emit
                if _hud_dt >= 1.0:
                    _hud_fps = _hud_tick_count / _hud_dt
                    _h.cef_execute_javascript(
                        "setDebugHud(" + repr(_hud_fps) + ", " +
                        repr(_hud_monitor_hz) + ");"
                    )
                    _hud_last_emit = _hud_now
                    _hud_tick_count = 0
```

- [ ] **Step 5: Run the timestep tests to confirm they still pass**

Run: `uv run pytest tests/unit/test_timestep.py tests/unit/test_loop.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Smoke-import the host loop module**

The host-loop module isn't directly unit-testable (it runs the renderer), but `python -c "import engine.host_loop"` confirms there are no syntax or import errors.

Run: `uv run python -c "import engine.host_loop"`
Expected: exits cleanly with no output.

- [ ] **Step 7: Run a sim-driving test to catch regressions in `GameLoop.advance(n)` semantics**

The accumulator path doesn't touch `GameLoop.advance(n)` but a regression in the engine modules it imports would surface here.

Run: `uv run pytest tests/unit/test_gameloop_shield_regen.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(cat <<'EOF'
feat(host_loop): decouple sim tick rate from render frame rate

Wires engine.core.timestep.step_accumulator between the vsync-bound
render loop and GameLoop.tick(). Sim now advances at exactly 60 Hz
regardless of monitor refresh rate; previously it ticked once per
render frame and scaled with display refresh (114/s measured on a
120 Hz MacBook, sim ratio 1.90x).

- Adds MAX_FRAME_DT = 0.25 s spiral-of-death cap on a stalled frame.
- Pause freezes frame_dt to zero so the accumulator cannot grow
  during pause; resume continues exactly where pause left off, no
  catch-up burst.
- Camera pending-swap drain re-gated on "at least one sim tick ran
  this frame" instead of "not paused" (equivalent semantics).
- Switches to time.monotonic() throughout the loop entry to defend
  against backward wall-clock steps (NTP adjust, DST).
- HUD counter moved from once-per-render-frame to once-per-sim-tick
  so the diagnostic readout reflects true sim rate after the fix.

GameLoop.tick() and GameLoop.advance(n) are unchanged; the test path
is identical to before.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Build the renderer and run visual smoke

The unit tests prove the math is right. This task confirms the wiring is right by running the actual game and reading the diagnostic HUD.

**Files:**
- None modified. Build artifacts only.

- [ ] **Step 1: Rebuild the renderer host binary**

CLAUDE.md is explicit that the canonical build tree is `<project-root>/build/`. Never build from inside `native/`.

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds without errors; produces `build/dauntless` and the Python extension `build/python/_open_stbc_host.cpython-*.so`.

- [ ] **Step 2: Launch the game**

Run: `./build/dauntless`
Expected: the game window opens, mission loads, the top-right diagnostic HUD shows tick rate / monitor / sim ratio.

- [ ] **Step 3: Read the HUD and capture the result**

Wait ~5 seconds after the mission loads so the HUD has stabilized. Note the displayed values for:
- tick rate (expected: ~60.0 ± 1)
- monitor (expected: 120 on MacBook ProMotion, 60 on a 60 Hz external)
- sim ratio (expected: 1.00 ± 0.02)

Expected result: **tick rate is ~60 regardless of monitor refresh rate. Sim ratio is ~1.00.**

If the HUD reads ~120 on the MacBook, the accumulator is not being driven correctly — re-check Step 3 of Task 2 (the increment lives inside the `for _ in range(_sim_ticks_this_frame)` loop, not at render-frame scope).

- [ ] **Step 4: Pause-resume smoke test**

While in-game, open the pause menu (ESC), wait 10 wall-clock seconds, then unpause.

Expected:
- The ship does not lurch forward on resume.
- Once unpaused, the HUD tick rate returns to ~60.
- No visible "catch-up" hitching.

If the ship lurches, the pause `frame_dt = 0` branch isn't firing — re-check Step 3 of Task 2.

- [ ] **Step 5: Shield regen wall-clock test**

This is the original symptom that motivated the fix.

Launch the game (mission with a Galaxy-class player ship), use the `[` debug key to zero shields on the player, and time with a stopwatch how long it takes the side face to refill from 0 to full.

Expected: ~6 minutes (±10 %, i.e. 5:24 to 6:36) on any display.

Before the fix, on a 120 Hz display this completed in ~3 minutes.

- [ ] **Step 6: If all smokes pass, the fix is verified — no commit needed in this task**

This is a verification-only task. If anything fails, debug and amend the previous commit. Don't move to Task 4 until smoke is green.

---

## Task 4: Diagnostic cleanup (follow-up commit)

After the smoke tests pass, remove the temporary diagnostics. This is intentionally a separate commit so the HUD survives a partial-success scenario.

**Files:**
- Modify: `engine/host_loop.py` (remove `_hud_*` block, remove `[` key handler)
- Modify: `native/src/host/host_bindings.cc` (remove `get_monitor_refresh_rate` binding)
- Modify: `native/assets/ui-cef/hello.html` (remove debug HUD elements + `setDebugHud` JS)

- [ ] **Step 1: Identify all FPS/HUD wiring**

Run: `git show 4b99301 --stat && git show e986369 --stat 2>/dev/null || echo "e986369 not found, locate the [ key handler manually"`
Expected: lists the files added/changed by the diagnostic commits. Use this as the work list.

- [ ] **Step 2: Remove `_hud_*` initialization in host_loop.py**

In the block edited in Task 2 Step 2, remove the diagnostic HUD section:

```python
        # Diagnostic HUD: measure sim ticks per real second. Once the
        # accumulator is wired correctly, this reads ~60 on any display.
        _hud_monitor_hz = (_h.get_monitor_refresh_rate()
                           if _h is not None and hasattr(_h, "get_monitor_refresh_rate")
                           else 0)
        _hud_last_emit = _time_dbg.monotonic()
        _hud_tick_count = 0
```

Keep the accumulator state (`_previous_real_time`, `_accumulator`, `step_accumulator` import, `_time_dbg` import) — those are now load-bearing for normal operation.

- [ ] **Step 3: Remove the per-tick HUD increment in the accumulator loop**

The line `_hud_tick_count += 1` inside `for _ in range(_sim_ticks_this_frame):` gets removed:

```python
            for _ in range(_sim_ticks_this_frame):
                loop.tick()
```

- [ ] **Step 4: Remove the HUD emission block**

The entire block edited in Task 2 Step 4 (the `_hud_now`/`_hud_dt`/`setDebugHud` emission) is removed.

- [ ] **Step 5: Remove the `[` key shield-zero debug handler**

In `engine/host_loop.py`, find the block that handles `_h.keys.KEY_LEFT_BRACKET` (around line 2427 pre-cleanup) and delete it. The handler is the entire `if (_h is not None and _h.key_pressed(_h.keys.KEY_LEFT_BRACKET) ...)` block including its body.

- [ ] **Step 6: Remove `get_monitor_refresh_rate` binding in native/src/host/host_bindings.cc**

Run: `grep -n "get_monitor_refresh_rate\|GetMonitorRefreshRate" native/src/host/host_bindings.cc`
Locate the function and its registration. Delete both.

- [ ] **Step 7: Remove HUD elements in native/assets/ui-cef/hello.html**

Run: `grep -n "setDebugHud\|tick rate\|sim ratio\|monitor:" native/assets/ui-cef/hello.html`
Delete the HUD `<div>` (and any associated CSS / `setDebugHud` JS function).

- [ ] **Step 8: Rebuild and smoke**

Run: `cmake -B build -S . && cmake --build build -j`
Then: `./build/dauntless`

Expected:
- Build succeeds.
- Game launches; no diagnostic HUD in the top-right corner.
- No console errors about missing `get_monitor_refresh_rate` or `setDebugHud`.
- `[` key no longer zeroes shields.

- [ ] **Step 9: Run the test suite to confirm nothing relied on the diagnostic bindings**

Run: `uv run pytest tests/unit/test_timestep.py tests/unit/test_loop.py tests/unit/test_gameloop_shield_regen.py -v`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add engine/host_loop.py native/src/host/host_bindings.cc native/assets/ui-cef/hello.html
git commit -m "$(cat <<'EOF'
chore: remove fixed-timestep diagnostic HUD and [ debug key

The FPS / monitor / sim-ratio HUD (commit 4b99301) and the [ key
shield-zero debug binding (commit e986369) served their purpose
diagnosing and validating the fixed-timestep fix. Both removed now
that the fix has landed and shield regen times match SDK math on
high-refresh displays.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Merge to main

**Files:**
- None.

- [ ] **Step 1: Confirm the branch builds and tests cleanly**

Run: `uv run pytest tests/unit/test_timestep.py tests/unit/test_loop.py tests/unit/test_gameloop_shield_regen.py -v && cmake --build build -j`
Expected: all tests PASS; build succeeds.

- [ ] **Step 2: Merge into main**

Ask the user to confirm before merging — this is a shared-state action.

```bash
git checkout main
git merge --no-ff fixed-timestep-sim
```

Expected: clean merge commit. If the user prefers a PR over a direct merge, push the branch and ask them how they want it integrated.

---

## Spec coverage check

- ✅ Accumulator pattern at the host-loop callsite — Task 2.
- ✅ `MAX_FRAME_DT = 0.25` cap — Task 1 (constant in tests), Task 2 (constant in host loop).
- ✅ Pause behavior freezes `frame_dt` — Task 2 Step 3.
- ✅ `GameLoop.advance(n)` untouched — Task 2 modifies only `host_loop.py`; verified by Task 1 Step 5 and Task 2 Step 7.
- ✅ HUD counter relocated to per-sim-tick — Task 2 Steps 3-4.
- ✅ `time.monotonic()` instead of `time.time()` — Task 2 Step 2.
- ✅ Six unit tests (steady state, 120 Hz, variable, cap, pause, defensive negative-dt) — Task 1 Step 1.
- ✅ Regression on `GameLoop` — Task 1 Step 5, Task 2 Step 7.
- ✅ Visual smoke (HUD, pause-resume, shield regen wall-clock) — Task 3.
- ✅ Diagnostic cleanup as follow-up commit — Task 4.

## Parking lot (deferred per spec)

- Render interpolation — not in this plan.
- Tick-rate smoothing — not in this plan.
- Multi-threaded sim — not in this plan.
