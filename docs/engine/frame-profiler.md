# Frame profiler

Per-pass frame timing for both halves of the frame. Built because the renderer
and host loop had **no timing instrumentation of any kind** — no `perf_counter`
in the loop, no GL timer queries, no per-pass breakdown — so every statement
about where the 16.67 ms goes was a guess.

## Using it

Launch with `--developer` and press **`` ` ``** (backtick). One switch drives
both halves; a report is written to stderr every `REPORT_EVERY` (120) frames.
Press it again to stop.

For an unattended capture:

```bash
OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=600 ./build/dauntless --developer
```

`DAUNTLESS_PROFILE_FRAMES=N` enables both halves, sets swap interval 0, runs N
frames, prints one report and exits.

**Run it through `dauntless.exe`, not `python -c "host_loop.run()"`.** CEF only
initialises when the process was launched through the binary — its `main()`
calls `dispatch_subprocess` before Python starts — so a Python-driven capture
prints `cef.pump`/`cef.composite` as `0.000`, which reads as free and means
absent. That mistake cost two capture rounds. The build must therefore be
CEF-enabled: `cmake -B build -S . -DDAUNTLESS_ENABLE_CEF=ON`. Configure the one
canonical `build/` tree that way rather than standing up a second one —
CLAUDE.md's build-layout rule is explicit that there is a single tree and that
binaries elsewhere are to be treated as stale.

```
-- frame profile -- (EMA over 397 frames, alpha 0.15)
  python loop phases            cpu ms
    input                        0.034
    ui_panels                   10.698
    sim                          4.960
    ...
  render passes                 cpu ms   gpu ms  calls
    frame                        2.611   20.621      1
      anim                       0.171    0.001      1
      space.opaque               0.165    0.473      1
      present                    0.055   15.914      1   <- vsync wait ...
```

## The two halves

| Half | Where | What it times |
|---|---|---|
| Render passes | `native/src/renderer/frame_timer.{h,cc}`, scopes in `host_bindings.cc:frame()` | CPU (`steady_clock`) **and** GPU (`GL_TIMESTAMP`) per pass, genuinely nested |
| Python phases | `engine/core/frame_profiler.py`, marks in `host_loop.py` | CPU per loop phase, a flat timeline |

The Python half is a **flat phase timeline**, not nested scopes: the loop body
is one long linear sequence, so each phase is delimited by a single `mark()` at
the seam — a one-line insert per boundary instead of re-indenting 1,300 lines
into `with` blocks, and it cannot mis-nest. The C++ half keeps real nesting
because its passes genuinely nest.

## Reading it correctly

Four things the report states outright, because each is a way to read a correct
number and reach a wrong conclusion:

* **`present` may be the vsync wait — read the swap interval the report prints,
  do not assume it.** When the interval is 1, a large `present` next to small
  siblings means the frame finished **early** and blocked, not that presenting
  is expensive, and any headroom conclusion from that capture is worthless.
  When it is 0, `present` is the pipeline draining. The report states the
  interval (and prints `-1` when it could not be read, which is not `0`);
  hard-coding `glfwSwapInterval(1)` here is what previously told every headless
  reader the wrong thing.
* **The two totals nest, they do not add.** `r.frame()` runs inside the loop
  body, so the Python total already contains the render total.
* **Whole-frame GPU is first-timestamp-to-last, not a sum of scopes.** Scopes
  nest; summing them double-counts.
* **A missing render half says UNAVAILABLE.** A stale extension module yields an
  empty scope list, and a report that silently omitted the render passes would
  read as "the render costs nothing".

`calls` is the raw count from the last resolved frame, not an average, so a pass
that ran twice (the exterior view **and** the bridge viewscreen RTT both call
`render_space`) reads as `calls=2` rather than a number matching neither.

## Cost when off

Off by default. `push`/`pop` and `mark` are a predicted branch; no GL object is
created until it is enabled. The production render path is unchanged.

Results are read back `kRingDepth` (3) frames late so resolving never blocks on
the GPU — a profiler that calls `glGetQueryObjectui64v` on an unready query
stalls the CPU on the GPU and measures its own stall, which presents as
"rendering got slower". `test_resolving_does_not_stall_on_the_gpu` guards it.

The report prints to the console rather than a CEF overlay deliberately: the
CEF surface is uploaded in full every frame (no dirty-rect, no PBO), so a DOM
overlay mutating each frame would add paint work to the frame being measured.
Report output is ASCII-only — Windows consoles default to cp1252, and a
box-drawing character raised `UnicodeEncodeError` from inside the frame loop on
the first live run.

## Combat load — the capture that matters

⚠️ **The first captures taken with this profiler were all of an IDLE game.**
QuickBattle boots with `g_kEnemyList = []` (a lone Galaxy on a bridge), and
E3M1 / E2M1 / E8M1 each run 900 ticks with zero projectiles fired and zero hull
damage. Conclusions drawn from them were conclusions about a game doing nothing.
Use `engine/dev_missions/combat_stress.py`, and check the scene line before
believing any number:

```bash
OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_MISSION=engine.dev_missions.combat_stress   DAUNTLESS_COMBAT_SHIPS=16 DAUNTLESS_PROFILE_FRAMES=1200   ./build/dauntless --developer
```

17 ships, ~70 projectiles in flight, uncapped, CEF on:

```
  ui_panels      ~17.0        sim            ~70       r.frame     ~15-24
  render_prep    ~12.0          sim.combat   ~25-33
                                sim.gameloop ~35
                                  gl.ai       ~10-11
                                  gl.subsystems ~7.6
                                  gl.motion   ~5.6-6.1
                                  gl.proximity ~1.6
```

**Combat is 20-50x the idle sim cost.** Idle it is ~1.4 ms; here it is ~70 ms.
Anything measured without a fight running tells you nothing about the frame.

### Measured improvements so far

| change | effect |
|---|---|
| projectile/ship broadphase | `sim` 166 → ~87 ms at matched load (~1.9x); `sim.combat` 81.7 → ~30 (~2.7x) |
| impulse derating computed once per ship-tick | motion path −27% by cProfile; `gl.motion` 10.45 → ~5.6-6.1 ms live |
| `TGMatrix3.MultMatrix` unrolled | 3.74x on the primitive, but only ~0.5 ms of `gl.motion` |

### Run-to-run variance is large — check for contention

The fight evolves differently each run, so projectile counts (and therefore
every sim number) vary. Worse, external CPU load inflates everything at once.
**The tell is correlation:** if `gl.ai`, `ui_panels` and `gl.motion` all move
together by 2-3x, that is contention, not a regression. Compare runs at similar
projectile counts, and discard runs where the untouched phases moved.

## First measured capture (idle — kept for the render-pass breakdown)

QuickBattle (boots to the bridge), headless, uncapped, CEF on, 600 frames:

```
  python loop phases            cpu ms      render passes         cpu ms   gpu ms
    render_prep                 15.777        frame                7.644   27.238
    r.frame                      7.696          anim               4.108    0.001
    ui_panels                    1.628          cef.composite      1.886    1.308
    sim                          1.379          bridge             1.103    0.404
    starmap                      0.717          post               0.050    0.987
    input                        0.041          present            0.075   24.014
```

E3M1 (exterior view), same conditions, redistributes sharply: `ui_panels`
10.7 ms, `sim` 5.0 ms, `render_prep` 0.8 ms. **The two scenes have different
bottlenecks** — profile the one you intend to fix.

Reading notes for this capture:

* `cef.composite` at 1.9 ms CPU is the full-surface overlay upload:
  `glTexSubImage2D` of the entire CEF surface every frame, no dirty-rect and no
  PBO, plus the `memcpy` in `OnPaint`. CEF hands us `dirtyRects` and the
  parameter is currently named-out and discarded.
* `anim` at 4.1 ms is bone-palette rebuilds for every animated instance with no
  visibility or distance gate — the bridge has a full crew.
* `scene_push` costs 0.7–1.5 ms. This number was originally reported as
  `starmap` — a phase name that spanned 239 lines of lights, backdrops, suns,
  planets, nebulae, decals and warp VFX, of which the star map was the first
  three. `_drive_star_map` early-returns when the modal is shut, so the star
  map was never the cost; the phase has been split.
* `present` holding most of the GPU time is the pipeline draining at the swap,
  not presentation cost. With swap interval 0 it is not a vsync wait.
* ⚠️ Taken on a hidden window; the GL device was not identified, so treat the
  GPU column as indicative. The CPU column is trustworthy.

## Scaling toward 100 ships

Headless combat driver (GameLoop + weapons + combat — the plain GameLoop does
not pump weapons, so a headless run fires nothing and profiles an idle game):

| ships | sim tick |
|---|---|
| 9 | 2.4 ms |
| 17 | 5.0 |
| 33 | 11.2 |
| 65 | 22.5 |
| 101 | **35.7** |

**Linear.** Ratios per doubling 2.02, 1.59 — there is no algorithmic wall
between here and 100 ships in this path; it is a constant-factor problem. At
101 ships the sim tick is ~2.1x a 16.67 ms frame budget on its own.

⚠️ **The headless driver understates combat.** It produces far fewer
projectiles than a live capture (87 at 101 ships, vs 240 at 33 ships live),
because the AI's fire scripts depend on host-loop state. Use it for *shape*
(complexity, call counts) and a live capture for *magnitude*.

### What is still quadratic

`gl.ai` → `pp:EngineAvoidObstacles` — avoidance no longer has its own GameLoop
phase. `tick_collision_avoidance` was removed from `GameLoop.tick` and the work
now runs as an `AvoidObstacles` preprocessor INSIDE `gl.ai`, so there is no
`gl.avoidance` row to look for. The scan is still all-pairs: it walks
`iter_set_objects(pSet)` per
ship, i.e. all-pairs, with per-pair collision-mask and hull-piece work. Per
ship it costs 0.06 / 0.12 / 0.41 / 1.11 ms at 9 / 17 / 33 / 33-with-more-combat
ships. It has an adaptive cadence (re-evaluate every 0.25 s when not evading)
which is what has hidden it so far, but in a dense fight most ships ARE
evading, so most re-evaluate every tick. **This is the thing that explodes
first at 100 ships.** It needs the same treatment the projectile loop got: a
spatial or distance broadphase before the per-pair work.

### The shape of what remains

After the wins below, a 100-ship profile is FLAT — the largest single entry is
`_out_of_action` at 2.7% of total. The sim makes **~200,000 Python function
calls per tick** at 100 ships (39.9 M over 200 ticks): 3.0 M isinstance,
2.4 M hasattr, 1.4 M getattr, 1.0 M implements, 1.1 M TGPoint3 allocations.

That changes what "optimising" means. There is no hot spot left to fix; the
cost is the *number of operations*. The routes are (a) do less per tick —
BC's own answer, `TimeSliceProcess`, is already present as `g_kAIManager` and
is barely used (`gl.timeslice` is 0.03 ms); (b) sim LOD, updating distant
ships at lower frequency; (c) move hot paths to C++.

## Gotchas for whoever extends it

* **Name phases for what they contain.** The first capture put 5.2 ms in a phase
  called `input`. Real input dispatch is 0.034 ms; the rest was the CEF panel
  pump and `_pump_contacts`. A mis-named phase is worse than an unmeasured one —
  it is a confident pointer at the wrong file.
* **A GL test must `shutdown()` in teardown.** `init()` raises when the host is
  already initialised, so leaving the context up makes every later host test
  fail at its own `init()`.
* `EMA_ALPHA` is duplicated in `frame_profiler.py` and `FrameTimer::kEmaAlpha`.
  Change both or the two halves of a report lag differently.
* **The table describes the last resolved frame, not every scope ever seen.**
  Passes change parent at runtime — `render_space` runs under `space` in the
  exterior view and under `viewscreen.rtt` on the bridge — so depth and order
  are recorded per frame. A first-sight tree printed this frame's children
  beneath the previous view's parent: every row correct, the tree a lie.
* **Check the scene line before believing anything.** Every early capture with
  this profiler measured a game with no combat in it, and nothing in the output
  said so. Combat is 20-50x the idle sim cost.
* **Open the box before choosing the fix.** `gl.motion` looked like a matrix
  problem from reading the code; unrolling the multiply (3.74x on the
  primitive) moved it 10.45 → 9.9 ms. cProfile then showed `MultMatrix` was
  2.5% of the path and `impulse_output_fraction` was 55%. Reasoning ahead of
  measurement picked the wrong target three times in one session.
* **Never assume the swap interval.** A hidden window already defaults to 0, so
  the original hard-coded "present is the vsync wait" note told every headless
  capture the opposite of the truth. It is read from the context now.

## Tests

* `tests/unit/test_frame_profiler.py` — attribution, smoothing, decay, report
  wording, ASCII safety. No GL.
* `tests/host/test_frame_profiler_gl.py` — the `GL_TIMESTAMP` path: resolution
  latency, non-negative/non-NaN GPU spans, per-frame `calls`, no pipeline stall.

---

# Building a headless sim harness: two traps

Both of these silently skew a profile, and both cost real time this session.

## 1. `_advance_weapons` / `_advance_combat` are PER FRAME, not per tick

`host_loop.py:7667` — the fixed-timestep loop body is **only `loop.tick()`**:

```python
for _ in range(_sim_ticks_this_frame):
    with frame_profiler.scope("sim.gameloop"):
        loop.tick()
# ...245 lines later, OUTSIDE the loop, once per frame:
_advance_weapons(_ships_this_tick, TICK_DT)
_advance_combat(...)
```

A harness that calls all three every iteration overweights the weapon and
combat pumps by the ticks-per-frame factor — **~10–15× at 100 ships**, where
the frame is slow enough that the accumulator runs 10–15 catch-up ticks. That
inverts the priority order: combat looks like 31% of a "tick" when in the live
mix it is a fraction of that, and everything inside `loop.tick()` (AI,
avoidance, motion, subsystems) is correspondingly understated.

Mirror the real cadence: N gameloop ticks, then the pumps once.

## 2. The fight has to develop before you measure

`combat_stress` starts with nothing in flight. Projectile count — and with it
the cost of the whole combat path — climbs for a long time:

| warmup ticks | projectiles | sim cost |
|---|---|---|
| 240 | 6 | 23.8 ms |
| 1200 | 32 | 28.4 ms |
| 3000 | 48 | 29.9 ms |

A 240-tick warmup is ~4 s of game time; the live captures that show 150–290
projectiles are 40–60 s in. Warm up for thousands of ticks, and **print the
projectile count next to every number** — a profile taken at 6 projectiles is
not a profile of a battle, and nothing in the output says so unless you make it.

Combining both: at 100 ships, tpf=10 and a 3000-tick warmup gives 121
projectiles and a 184 ms sim frame — 18.4 ms per gameloop tick.
