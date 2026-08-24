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
OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=600 ./build-cef/dauntless.exe --developer
```

`DAUNTLESS_PROFILE_FRAMES=N` enables both halves, sets swap interval 0, runs N
frames, prints one report and exits.

**Run it through `dauntless.exe`, not `python -c "host_loop.run()"`.** CEF only
initialises when the process was launched through the binary — its `main()`
calls `dispatch_subprocess` before Python starts — so a Python-driven capture
prints `cef.pump`/`cef.composite` as `0.000`, which reads as free and means
absent. That mistake cost two capture rounds. Use a CEF-enabled build tree
(`build-cef/`); the default `build/` is configured `-DDAUNTLESS_ENABLE_CEF=OFF`.

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

* **`present` is the vsync wait.** `window.cc` sets `glfwSwapInterval(1)`, so a
  large `present` next to small siblings means the frame finished **early** and
  blocked — not that presenting is expensive. Any headroom conclusion drawn from
  a vsync-capped capture is worthless. Capture with swap interval 0 to measure
  real cost.
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

## First measured capture

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
* `starmap` costs 0.7–1.5 ms for a **closed** modal.
* `present` holding most of the GPU time is the pipeline draining at the swap,
  not presentation cost. With swap interval 0 it is not a vsync wait.
* ⚠️ Taken on a hidden window; the GL device was not identified, so treat the
  GPU column as indicative. The CPU column is trustworthy.

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
* **Never assume the swap interval.** A hidden window already defaults to 0, so
  the original hard-coded "present is the vsync wait" note told every headless
  capture the opposite of the truth. It is read from the context now.

## Tests

* `tests/unit/test_frame_profiler.py` — attribution, smoothing, decay, report
  wording, ASCII safety. No GL.
* `tests/host/test_frame_profiler_gl.py` — the `GL_TIMESTAMP` path: resolution
  latency, non-negative/non-NaN GPU spans, per-frame `calls`, no pipeline stall.
