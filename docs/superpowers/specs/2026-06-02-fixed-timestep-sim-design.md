# Fixed-Timestep Simulation — Decouple Sim Loop from Render Frame Rate

Date: 2026-06-02
Status: design, ready for implementation

## Problem

The Python host loop in [engine/host_loop.py](../../engine/host_loop.py) drives one
`loop.tick()` call per render frame inside a `glfwSwapInterval(1)` vsync-bound
loop ([host_loop.py:2378-2380](../../engine/host_loop.py#L2378-L2380)).
`GameLoop.tick()` ([engine/core/loop.py](../../engine/core/loop.py)) advances
every dt-driven subsystem (timer managers, AI, ship motion, shields, power) by
exactly `TICK_DELTA = 1.0 / 60.0`, regardless of how long the real frame took.

On any display refreshing faster than 60 Hz this scales every dt-driven system
proportionally: a 120 Hz monitor produces sim ticks at ~114 /s with a measured
sim ratio of 1.90×. The diagnostic HUD on `main` (commit `4b99301`) confirmed
the cause definitively when investigating a stopwatch measurement of shield
regen that finished in half the expected wall-clock time.

Affected systems: shield regen, weapon discharge / recharge, AI decision rate,
both timer managers, phaser damage accumulation, impulse-engine throttle
ramping, disabled-engine drag fraction, camera shake decay — every callsite
that consumes `TICK_DELTA` as truth.

The fix is to decouple simulation cadence from render cadence. Render at the
monitor refresh rate (unchanged); sim advances at a true fixed 60 Hz using a
real-time accumulator.

## Goal

The simulation advances `loop.tick()` exactly 60 times per real second on
any monitor refresh rate, with the render loop continuing to draw at whatever
rate vsync permits.

Definition of done:

- HUD tick rate reads ~60 ± small jitter on the diagnostic HUD regardless of
  monitor refresh rate.
- Shield regen on the Galaxy side face takes ~6 minutes from 0 → full on
  both 60 Hz and 120 Hz displays (±10 % wall-clock tolerance).
- All previously-green tests still pass; new tests cover the accumulator math,
  the spiral-of-death cap, and pause-resume semantics.
- Diagnostic `[` key and FPS HUD removed in a follow-up commit after
  verification.
- Gameplay no longer feels "fast" on the high-refresh display.

## Design

### The accumulator pattern

The Fiedler "Fix Your Timestep" accumulator, applied at the host-loop call
site:

```python
TICK_DT = 1.0 / 60.0
MAX_FRAME_DT = 0.25  # spiral-of-death safety cap

accumulator = 0.0
previous_real_time = time.monotonic()

while not r.should_close():
    now = time.monotonic()
    frame_dt = now - previous_real_time
    previous_real_time = now

    if pause.is_open:
        frame_dt = 0.0  # freeze game time during pause (see Pause semantics)

    if frame_dt < 0.0:
        frame_dt = 0.0  # defensive: monotonic clock shouldn't go backward

    if frame_dt > MAX_FRAME_DT:
        frame_dt = MAX_FRAME_DT  # bound catch-up after a render stall

    accumulator += frame_dt
    ticks_this_frame = 0
    while accumulator >= TICK_DT:
        loop.tick()
        ticks_this_frame += 1
        accumulator -= TICK_DT

    # ... existing per-frame render-side work continues here:
    #     CEF pump, mouse forwarding, pending-swap drain (gated on
    #     ticks_this_frame > 0 instead of "not pause.is_open"),
    #     camera, input, r.frame() ...
```

### Key design decisions

**Q1 — `MAX_FRAME_DT = 0.25`.** Standard Fiedler default. On a stalled frame
(CEF compile, GC pause, asset load) the inner loop runs at most ~15 sim ticks
to catch up; longer stalls drop game time rather than chain unbounded ticks.
The cap matters only during pathological frames — steady-state sim rate is
exactly 60 Hz regardless of this value.

**Q2 — Render interpolation: deferred.** Pure fixed-timestep without
interpolation can show stutter when render rate differs from sim rate (every
second render frame on a 120 Hz monitor shows the same sim state). The
accepted fix is `lerp(prev_state, current_state, accumulator / TICK_DT)`
inside the renderer, but every `set_world_transform` callsite (ships,
projectiles, camera, planets, dust, sun) would need a "previous" snapshot.
That is its own project. Ship the accumulator first; revisit interpolation
only if stutter is actually perceptible.

**Q3 — Pause behavior: freeze game time.** When `pause.is_open`, force
`frame_dt = 0`. This advances `previous_real_time` every frame so the
accumulator does not grow during pause, and no catch-up burst happens on
resume. Cleaner than an explicit "on resume" event because it is the
correct behavior regardless of how the pause state-machine evolves later.

**Q4 — Headless / test paths unchanged.** `GameLoop.advance(n)` runs N
sequential ticks without an accumulator and is the entry point used by tests.
That path stays untouched. Only the host-loop callsite changes.

**Time primitive: `time.monotonic()`.** Used instead of `time.time()` because
wall-clock can step backward (NTP adjust, DST transition) which would produce
a negative `frame_dt` and break the accumulator. `time.monotonic()` cannot
step backward.

### Scope of code change

**Changes — [engine/host_loop.py](../../engine/host_loop.py) only:**

- Add module-level constants near the top of `run()`: `TICK_DT = 1.0 / 60.0`
  (already present at line 2209 — kept) and `MAX_FRAME_DT = 0.25` (new).
- Replace the per-frame `if not pause.is_open: loop.tick()` block at
  [host_loop.py:2378-2380](../../engine/host_loop.py#L2378-L2380) with the
  accumulator loop.
- The `pending_swap` drain and `cam_control.snap()` follow-up — currently
  keyed off "we ticked this frame" — re-gate on
  `ticks_this_frame > 0` so they fire on any frame where at least one sim
  tick ran rather than every render frame.
- The diagnostic HUD counter (`_hud_tick_count`, added in commit `4b99301`)
  increments inside the accumulator while-loop instead of once per render
  frame iteration. After the fix, the HUD reads ~60 ± jitter on every
  display.

**Factored helper for testability:**

```python
def step_accumulator(accumulator, frame_dt, tick_dt, max_frame_dt):
    """Pure function. Returns (new_accumulator, n_ticks)."""
    if frame_dt < 0.0:
        frame_dt = 0.0  # defensive: monotonic clock shouldn't go backward
    if frame_dt > max_frame_dt:
        frame_dt = max_frame_dt
    accumulator += frame_dt
    n = 0
    while accumulator >= tick_dt:
        n += 1
        accumulator -= tick_dt
    return accumulator, n
```

The host loop calls this helper and then runs `loop.tick()` n times. Keeping
the math in a pure function makes the unit tests trivial.

**Does not change:**

- [engine/core/loop.py](../../engine/core/loop.py) — `GameLoop.tick()` and
  `GameLoop.advance(n)` are untouched. `TICK_DELTA = 1.0 / 60.0` inside the
  GameLoop stays as the per-tick advance amount.
- [native/src/renderer/window.cc:72](../../native/src/renderer/window.cc#L72)
  — `glfwSwapInterval(1)` stays. Render frames remain vsync-bound.
- Renderer transform paths — no interpolation work.

## Testing

### New unit tests (`tests/unit/test_timestep.py`)

The accumulator math is a pure function and can be tested without spinning up
the renderer or the game loop.

1. **`test_steady_state_60hz_emits_one_tick_per_frame`** — feed deltas
   `[1/60] * 600` (10 wall-clock seconds at 60 Hz render). Total ticks
   emitted = 600; final accumulator close to zero.
2. **`test_120hz_render_emits_60hz_sim`** — feed deltas `[1/120] * 1200`
   (10 seconds at 120 Hz render). Total ticks emitted ≈ 600 (599 ≤ n ≤ 600
   for FP tolerance) — sim still runs at 60 Hz. About half the frames
   produce 1 tick, half produce 0.
3. **`test_variable_deltas_emit_correct_tick_count`** — mix of
   `[1/60, 1/120, 1/30, 1/240, ...]`. Total ticks emitted matches
   `floor(sum(deltas) / TICK_DT)` within ±1.
4. **`test_stall_clamped_to_cap`** — feed `[1.0]` (a one-second stall) with
   `MAX_FRAME_DT=0.25`. Assert ticks emitted is bounded by 15 (not the 60
   a naive implementation without the cap would emit). Tightened to
   `14 ≤ n ≤ 15` so the test catches both "cap not applied" and off-by-one
   regressions.
5. **`test_pause_zero_dt_no_ticks`** — feed many `0.0` frame_dts (simulating
   paused state); zero ticks emitted; accumulator stays at zero.
6. **`test_negative_dt_treated_as_zero`** — call with `accumulator=0.0`,
   `frame_dt=-0.1`. Assert `n == 0, accumulator == 0.0` exactly — the only
   way both hold is if the negative-clamp branch fired. Defensive against
   a backward-stepping clock (shouldn't happen with `monotonic()`).

### Regression

Existing tests calling `GameLoop.advance(n)` keep passing unchanged. Run the
focused test file (full pytest is forbidden per CLAUDE.md memory).

### Visual smoke (manual, post-build)

- Launch on the 120 Hz MacBook: HUD reads tick rate ≈ 60.0, sim ratio ≈ 1.00.
- Launch on a 60 Hz monitor if available: same numbers.
- Pause for 10 wall-clock seconds, resume: ship does not lurch forward.
- Shield-regen wall-clock test: Galaxy side face from 0 → full takes
  ~6 minutes on both displays (±10 % wall-clock tolerance per definition of
  done).

## Diagnostic cleanup (follow-up commit)

After the smoke tests on real hardware pass, a single follow-up commit
removes the temporary diagnostics:

- `[` key shield-zero debug binding (commit `e986369`) in
  [host_loop.py](../../engine/host_loop.py).
- FPS / monitor / sim-ratio HUD added by commit `4b99301`:
  - Python `_hud_*` block in [host_loop.py](../../engine/host_loop.py).
  - `get_monitor_refresh_rate` binding in
    [native/src/host/host_bindings.cc](../../native/src/host/host_bindings.cc).
  - HUD elements in
    [native/assets/ui-cef/hello.html](../../native/assets/ui-cef/hello.html).

The cleanup is intentionally a separate commit — if smoke fails, the HUD is
still there to investigate without a revert.

## Parking lot (out of scope)

- **Render interpolation.** Store `(prev, current)` transforms per renderable,
  render `lerp(prev, current, accumulator / TICK_DT)`. Eliminates stutter on
  render-vs-sim rate mismatches. Touches every transform snapshot callsite in
  the renderer host bindings. Revisit only if stutter is actually visible on
  120+ Hz hardware after this fix lands.
- **Tick-rate smoothing.** `time.monotonic()` is stable, so smoothing of
  `frame_dt` should not be needed. Defer until evidence demands it.
- **Multi-threaded sim.** Not on the roadmap. Sim stays single-threaded
  inside the render-frame loop.
- **Variable physics timestep.** Sim is pinned at 60 Hz to match BC's
  documented tick rate (instrumentation Q1 finding, recorded in CLAUDE.md).

## References

- Glenn Fiedler, "Fix Your Timestep!" — https://gafferongames.com/post/fix_your_timestep/
- CLAUDE.md § "Open questions status" — Q1 confirms BC's 60 Hz fixed tick.
- `docs/superpowers/specs/2026-06-01-combat-damage-pipeline-design.md` §3 —
  every dt-driven decision in the combat arc assumed a true 60 Hz; the
  accumulator restores that assumption.
- Commit `4b99301` — diagnostic HUD that confirmed the cause.
- Commit `e986369` — `[` key shield-zero binding used to time the regen
  measurement.
