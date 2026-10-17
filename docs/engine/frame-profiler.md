# Frame profiler

Per-pass frame timing for both halves of the frame. Built because the renderer
and host loop had **no timing instrumentation of any kind** — no `perf_counter`
in the loop, no GL timer queries, no per-pass breakdown — so every statement
about where the 16.67 ms goes was a guess.

## Using it

Launch with `--developer`, open the pause menu's **Developer Options →
Diagnostics** tab, and toggle the frame profiler row. One switch drives both
halves; a report is written to stderr every `REPORT_EVERY` (120) frames.
Toggle it again to stop. (It used to live on backtick (`` ` ``) with no
on-screen state and no confirmation — `engine/dev_keybindings.py` moved it
after one stray keypress buried every other diagnostic line in the terminal
for the rest of a session, with no obvious way back.)

For an unattended capture:

```bash
OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=600 ./build/dauntless --developer
```

`DAUNTLESS_PROFILE_FRAMES=N` enables both halves, sets swap interval 0, runs N
frames, prints one report and exits.

### Spike capture — one-off long frames, to a file

The averaged report **cannot see a single slow frame**: a 5 s hitch is blended
in at alpha 0.15 and has decayed before the next 120-frame report prints. For a
load hitch (a warp arrival, a mission change) write the raw breakdown of every
slow frame to a file instead:

```bash
DAUNTLESS_PROFILE_SPIKES=/tmp/spikes.log ./build/dauntless
```

- Every frame at or over `DAUNTLESS_PROFILE_SPIKE_MS` (default 100) is appended
  as one record: the frame's **raw** Python phases/scopes (ms + calls), then the
  render scopes' raw CPU ms for the same frame (`profiler_last_frame_raw` — GPU
  resolves frames later and is left out), plus a context line (viewed set,
  player's set, warp tunnel up or not).
- Rows under 0.5 ms are omitted. Indented rows are included in their parent.
- Works **without** `--developer`; vsync is left alone; the periodic stderr
  report is suppressed while it is on. Toggling the profiler off from Developer
  Options stops the capture.
- Arrival-path scopes it reads: `warp.mission_change`, `warp.swap_set` ⊃
  `warp.region_init` / `warp.realize_set` ⊃ `realize.ship_model` /
  `realize.hull_prewarm`; `scene.system_load`, `scene.ships`, `scene.minors`,
  `scene.far_tier`, `scene.celestial` ⊃ `load.planet_model`;
  `scene.comm_sets`; `env.system_nebula`; native `rock.near.stream`,
  `space.far.build`, `sky.bake`, `rock.atlas.load`; `warp.place_player` and
  `warp.depart` (the QuickBattle arrival and the departure). During the
  tunnel: `warp.preload` (the destination preload's one step per frame,
  `engine/warp_preload.py`).

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
-- frame profile -- (EMA over 397 frames, alpha 0.15, swap interval 0 (uncapped))
  sim ticks: 4.0 avg, 4 last frame  (catch-up; ...)
  python loop phases                cpu ms calls
    input                            0.034     1
    ui_panels                       10.698     1
      ui.render_all                 10.410     1
        ui.target_list               6.202     1
    sim                              4.960     1
      sim.gameloop                   3.042     4 *
        gl.ai                        1.026     4 *
      sim.combat                     1.870     1
        cb.projectiles               0.901     1
    (an indented row is included in its parent's total -- do not sum the column)
    (* = per tick: summed over this frame's catch-up ticks ...)
  render passes                     cpu ms  gpu ms calls
    frame                            2.611  20.621     1
      anim                           0.171   0.001     1
      space.opaque                   0.165   0.473     1
      present                        0.055  15.914     1   <- vsync wait ...
```

## The two halves

| Half | Where | What it times |
|---|---|---|
| Render passes | `native/src/renderer/frame_timer.{h,cc}`, scopes in `host_bindings.cc:frame()` | CPU (`steady_clock`) per pass, genuinely nested; GPU by whichever timer the driver declares — `GL_TIMESTAMP` (every scope) or, on Apple's GL, `GL_TIME_ELAPSED` (**top-level passes only**; see "GPU timer selection") |
| Python phases | `engine/core/frame_profiler.py`, marks + scopes in `host_loop.py` | CPU per loop phase: a flat timeline of `mark()` phases with a nested `scope()` tree under each |

The Python half's **top level** is a flat timeline: the loop body is one long
linear sequence, so each phase is delimited by a single `mark()` at the seam —
a one-line insert per boundary instead of re-indenting 1,300 lines into `with`
blocks, and it cannot mis-nest.

**Underneath those phases it is a tree**, and has been since the `sim.gameloop`
split: `sim` ⊃ `sim.gameloop` ⊃ `gl.*`, `sim` ⊃ `sim.combat` ⊃ `cb.*`,
`ui_panels` ⊃ `ui.render_all` ⊃ `ui.<panel>`. `scope()` records the scope (or
mark phase) it opened inside and the report indents by that depth. Printed flat
— which it was — every child appeared *above* its parent with nothing marking
the relation, and summing the column counted the frame about three times.

## Reading it correctly

Things the report states outright, because each is a way to read a correct
number and reach a wrong conclusion:

* **Indented rows are INCLUDED in their parent's total.** `gl.ai` is part of
  `sim.gameloop` is part of `sim`. Do not sum the column.
* **`*` marks per-tick rows.** `sim.gameloop` and everything inside it is a sum
  over the frame's N catch-up ticks; its siblings `sim.weapons` / `sim.combat` /
  `sim.collisions` and everything inside *them* run **once per frame**. With the
  tick count printed above the table and nothing distinguishing the two, the
  natural move — divide everything by N — is wrong for half the rows. The
  `calls` column is the generic backstop: a row entered 4 times says `4`.
* **The tick count is printed twice, `avg` and `last frame`.** Every cost beside
  it is EMA-smoothed, so dividing one of those by a single frame's raw count
  mixes an instantaneous value into an average.
* **A GPU `-` means NOT MEASURED, never "free".** On Apple's GL the timer is
  `GL_TIME_ELAPSED`, which cannot nest, so only the children of `frame` (the
  top-level passes: `space`, `bloom`, `post`, `present`, ...) carry a GPU
  figure. Every nested row (`space.opaque`, `space.shield`, ...) keeps its CPU
  time and prints `-` for GPU, and the report says so in a line above the
  table. To get a nested pass's GPU time you must promote it to top level, or
  run on a driver with a timestamp counter.
* **`frame`'s GPU under `GL_TIME_ELAPSED` is the SUM of the timed passes**, not
  a span — they run in sequence, so the sum is the frame. GPU work outside
  every top-level scope is not covered (there is essentially none).
* **A GPU column of `0.000` may be a dead driver, not a free GPU.** If the
  driver declares no counter at all, the report prints **GPU TIMING
  UNAVAILABLE** from the first resolved frame. If it declares one but returns
  zeros, `gpu_ms` (only accumulated when `t1 >= t0`, so `>= 0` by
  construction) reads as free; when the **whole-frame** span is exactly 0
  across `GPU_ZERO_FRAMES` resolved frames the report prints **GPU TIMING
  UNAVAILABLE** and replaces the column with `-`.
* **An over-long name is clipped with a trailing `+`.** A silently clipped name
  reads as a different, shorter phase.

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
* **Under `GL_TIMESTAMP`, whole-frame GPU is first-timestamp-to-last, not a
  sum of scopes.** Scopes nest; summing them double-counts. "Last" means the last query **issued** —
  the outermost scope's end, which `end_frame()` issues *after* `present`'s.
  Taking the last sample *pushed* instead reported `present.end - frame.begin`
  and disagreed with the `frame` row printed directly above it.
* **A missing render half says UNAVAILABLE.** A stale extension module yields an
  empty scope list, and a report that silently omitted the render passes would
  read as "the render costs nothing".

`calls` is the raw count from the last resolved frame, not an average, so a pass
that ran twice (the exterior view **and** the bridge viewscreen RTT both call
`render_space`) reads as `calls=2` rather than a number matching neither.

## Cost when off

Off by default. The C++ `push`/`pop` and the Python `mark()` are a predicted
branch and nothing else; no GL object is created until it is enabled, so the
production render path is unchanged.

**`scope()` is the exception — it is not free when disabled.** It is a
`@contextmanager`, so every use builds a generator and a
`_GeneratorContextManager` *before* the `if not _enabled` inside it ever runs:
**~0.36 µs measured**. That is nothing at a phase seam or around a whole
subsystem, and it is real money inside a per-ship or per-projectile loop. Put
scopes at seams, not in inner loops.

Results are read back `kRingDepth` (3) frames late so resolving never blocks on
the GPU — a profiler that calls `glGetQueryObjectui64v` on an unready query
stalls the CPU on the GPU and measures its own stall, which presents as
"rendering got slower". `test_resolving_does_not_stall_on_the_gpu` guards it.
The availability check must therefore be on the last query **issued**
(`Record::last_query`), which is the *outermost* scope's end query, not
`samples.back()` — the last scope pushed, whose end query is issued earlier.

## Cost when ON — the profiler is not free on this Mac

Measured 2026-10-08, headless Debug build, `tools/bench_idle_passes.py`
(640x360, one shielded Galaxy; "loaded" = 40 extra hulls), profiler on vs off,
best of three rounds:

| Build | GPU timer | idle | loaded | GPU data |
|---|---|---|---|---|
| main before this change | `GL_TIMESTAMP` (0-bit, zeroed) | +2.0 ms | +3.7 ms | none |
| CPU-only (timer forced off) | none | ~0 | ~0 | none |
| current | `GL_TIME_ELAPSED`, top-level only | +0.6 ms | +2.4 ms | real |

So the `GL_TIME_ELAPSED` queries themselves cost real time — cheaper than the
dead timestamp queries they replace, but not free. **Where it lands** (loaded,
per-scope CPU, elapsed vs CPU-only): `present` +2.0 ms (2.72 vs 0.71), `space`
+0.4, `bloom` +0.12, `resolve` +0.06. So most of it shows up as swap time,
and the top-level passes' CPU rows are inflated by a little. No record is dropped as unavailable
(297 of 300 frames resolve — the 3 missing are the ring latency), so this is
not the in-flight-query-reuse stall the ring exists to prevent. The driver
mechanism behind the cost is **not established**. Read the per-pass CPU column
with that inflation in mind, and use the GPU column for relative pass
comparisons.

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

⚠️ **The numbers below were captured with `combat_stress` avoidance OFF, which
was the default at the time. It is now ON** — the mission imitates QuickBattle,
and `QuickBattle/QuickBattleAI.py` does wrap its attack tree in an
`AvoidObstacles` preprocessor, so off was never faithful to the scene being
imitated. A capture run today therefore includes avoidance in `gl.ai` and will
not reproduce these figures. Set `DAUNTLESS_COMBAT_AVOID=0` to match them, and
read the scene line — it announces `avoidance=ON/off` for exactly this reason.

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
* **This doc does not keep an exhaustive scope registry — read the call sites.**
  Features add their own `DAUNTLESS_FRAME_SCOPE`/`scope()` names as they ship and
  nest under whichever phase calls them; e.g. the rock-fields bands
  (`host_bindings.cc`) add `rock.near.stream`, `rock.near.draw`,
  `rock.fade.draw` (the translucent impostor fades), `rock.puffs.draw` and
  `rock.specks.draw`, alongside the earlier far-tier `space.far.*` scopes.
  Spike-capture attribution scopes (warp arrival): `gl.timers.game` /
  `gl.timers.real` (timer ticks in `loop.py`), `warp.depart`,
  `warp.place_player`, `warp.arrive_finalize`, `warp.exited_warp`,
  `warp.clear_targets` (the arrival actions in `engine/appc/warp.py`), and
  `rock.near.draw` split into `rock.near.build`, `rock.near.mesh_draw`,
  `rock.impostor.draw`, with `rock.atlas.load` (first-visit impostor atlas
  read + upload in `FarPass::atlas_for`).
  `planet_detail` (clipmap bake for the planet surface detail pass) is a
  top-level, GPU-timed scope — a sibling of `space`/`bloom`/`post`, not
  nested under any of them.

## Tests

* `tests/unit/test_frame_profiler.py` — attribution, smoothing, decay, tree
  indentation, per-tick marks, report wording, ASCII safety. No GL.
* `tests/host/test_frame_profiler_gl.py` — the GL query path on the real
  driver: timer chosen from the counter bits, no timestamp query on a 0-bit
  counter, `GL_TIME_ELAPSED` measuring exactly the top-level passes (nested
  rows unmeasured), resolution latency, per-frame `calls`, whole-frame total vs
  the `frame` row, the dead-GPU-column signal, no pipeline stall. On this Mac
  it exercises the `GL_TIME_ELAPSED` branch only; the `GL_TIMESTAMP` branch
  has no driver here to run on.
* `native/tests/renderer/frame_timer_test.cc` — `choose_gpu_timer` and
  `elapsed_times_depth`, no GL.

Two gaps, both deliberate and both worth knowing about:

* **The re-entry path in `FrameTimer::push()` is untested.** Reaching it needs a
  pass that genuinely runs twice in one frame (the bridge viewscreen RTT
  rendering the space scene alongside the exterior view), which an empty
  headless `h.frame()` never produces — everything comes back `calls=1`. A test
  that ran plain frames and asserted the names were *unique* used to sit here
  claiming to cover it; it could not fail, and has been deleted. A gtest driving
  `FrameTimer` directly (push/push/pop/pop the same name, read `results()`) is
  where this belongs.
* **`reset()` dropping the query pool is not covered either.** The failure it
  prevents needs a `shutdown()` + `init()` cycle, and a second `init()` in one
  process currently dies earlier for unrelated reasons (`GL error during
  upload_mesh: 0x502` — static GL handles surviving the context, see the GL
  context lifecycle notes).

---

# GPU timer selection — and why the GPU column used to be DEAD on this Mac

**Fixed 2026-10-08.** `FrameTimer` now reads `GL_QUERY_COUNTER_BITS` for both
targets on the first enabled frame (re-read on every enable) and picks
(`FrameTimer::choose_gpu_timer`):

| `GL_TIMESTAMP` bits | `GL_TIME_ELAPSED` bits | Timer | What gets a GPU figure |
|---|---|---|---|
| > 0 | any | `GL_TIMESTAMP` | every scope |
| 0 | > 0 | `GL_TIME_ELAPSED` | depth-1 scopes (children of `frame`); `frame` = their sum |
| 0 | 0 | none | nothing — GPU TIMING UNAVAILABLE |

A 0-bit `GL_TIMESTAMP` counter is **never queried** — not even to probe.
`profiler_frame()` reports `gpu_timer`, `timestamp_bits`, `elapsed_bits`, and
`timestamp_queries` (issued since the last enable; the test that this stays 0
on a 0-bit driver is how that rule is guarded). `profiler_scopes()` reports
`gpu_measured` per row. This **supersedes** the parked
`perf/idle-shield-weapons-pass` latch (`31c642eb`), which stopped the
timestamp queries only after 30 frames of zeros; its bench,
`tools/bench_idle_passes.py`, was carried over.

What follows is the history, kept because the reasoning still applies.

## The dead `GL_TIMESTAMP` column

Apple's GL returns **zeroed `GL_TIMESTAMP` counters**. Measured: 117 resolved
frames of exactly 0.

**Why (measured 2026-10-08, Apple M3 Pro, `GL_VERSION` "4.1 Metal - 90.5"):**
Apple's GL is a layer over Metal, and it **declares** it has no timestamp
counter — `glGetQueryiv(GL_TIMESTAMP, GL_QUERY_COUNTER_BITS)` returns **0**,
and `glGetInteger64v(GL_TIMESTAMP)` returns 0. That is the driver's honest
"unsupported", not a broken counter.

**`GL_TIME_ELAPSED` WORKS on the same driver.** It reports 32 counter bits, and
a `glBeginQuery`/`glEndQuery` probe around three bridge spans returned steady,
plausible figures over ~2,500 frames with **zero** zero-samples (normal
pre-pass ~0.63 ms, half-res SSAO kernel ~1.3 ms, main bridge draw ~1.1 ms —
and pre-pass + kernel matched the ~2 ms the AO added to `resolve`'s CPU stall).
So GPU timing on this Mac is not impossible; *this profiler's timer type* is.
The catch: `GL_TIME_ELAPSED` queries **cannot nest** (one active per target),
so a profiler built on them can time sequential top-level passes, not the
nested scopes this one reports. The probe is
`DAUNTLESS_BRIDGE_GPU_PROBE=1` in `native/src/renderer/bridge_pass.cc` on branch
`spike/bridge-lighting` (commit `efbde014`).

This is worse than a missing feature, because `gpu_ms` only accumulates when
`t1 >= t0`, so every span is `>= 0` **by construction** — a dead driver and a
completely free GPU produce identical output. There is no way to tell them apart
from the numbers alone.

The report still prints **GPU TIMING UNAVAILABLE** and blanks the column after
30 such frames, as a net for a driver that declares a counter yet returns zeros.

**Every GPU figure recorded on this Mac before 2026-10-08 was never measured.**
Discard them. The CPU columns are unaffected and remain trustworthy.

---

# Two scenes, two different bottlenecks

Profile the scene you actually mean to fix — the dominant cost moves completely
between them.

| Phase | QuickBattle / bridge | E3M1 / exterior |
|---|---|---|
| `render_prep` | **15.8 ms** | 0.8 ms |
| `ui_panels` | — | **10.7 ms** |
| `sim` | — | 5.0 ms |
| `r.frame` | 7.7 ms | — |

In the QuickBattle/bridge frame, inside `r.frame` (7.7 ms):

* `anim` **4.1 ms** — bone palettes for every animated instance, ungated.
* `cef.composite` **1.9 ms CPU** — the full-surface overlay upload. No
  dirty-rect, no PBO.

Both scenes: `scene_push` runs 0.7–1.5 ms (lights, backdrops, suns, planets,
nebulae, decals, warp VFX). ⚠️ This was reported as `starmap` until the phase was
split — the star map early-returns when closed and was **never** the cost. Real
`input` is 0.034 ms.

**The dominant costs are Python-side and CPU-side. None of them is a thread-count
problem.**

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
