# Phase 0 runbook — re-measure on main after the combat_threading merge

**For:** `2026-11-03-native-motion-and-proximity-design.md` §5.0. **Run 2026-11-03: C-283 to C-287, SIG-180 to SIG-183.** Written 2026-11-03, before the merge, from the perf register (`docs/reference/engine/perf-register.md` on `project/combat_threading`). Run it only after Mark says the merge is done, with the machine otherwise idle: no tests, builds or agents. The machine is shared and used for perf work.

## 0. Before any run

- On `project/native-motion-and-proximity`, freshly made from local `main` after the merge.
- Rebuild from the one build tree: `cmake --build build -j`. Do not reconfigure, and do not change `CMAKE_BUILD_TYPE`: captures so far are **Debug**, and phase 0 compares like with like.
- Note the commit hash for the capture rows.
- Confirm the native switch is on by default: no `DAUNTLESS_NATIVE_COMBAT` in the environment. The scene line must still read `64 AI ships`, and the log should show native combat active.
- Read the scene line of every log before trusting its numbers (`frame-profiler.md`, "Combat load").

## 1. Baseline pair (as C-278/C-279)

**Confirmed** (2026-11-03, from the fire-control runner `fc_bench_runs.sh`, used for C-281 to C-284). `DAUNTLESS_PROFILE_FRAMES=1500` makes the run quit by itself:

```
env -u DAUNTLESS_NATIVE_COMBAT -u DAUNTLESS_COMBAT_IDLE -u DAUNTLESS_COMBAT_AVOID OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=64 DAUNTLESS_DEV_VIEW=bridge DAUNTLESS_PROFILE_FRAMES=1500 caffeinate -i ./build/dauntless --developer > ~/Documents/dauntless-perf/p0-brawl-run1-cs64-bridge-<yyyymmdd-hhmm>.log 2>&1
```

- **Run length:** 1,500 frames, as C-278/C-279.
- **Repeat:** a second run with `run2` after a 90 s cool-down.
- **Scoring (SIG-157/158):** for each row, take the value ÷ the report's printed average ticks per frame, then the median of reports 3–11 (n = 9). Never divide by `calls`: it is the last frame's tick count.
- **Rows to record:**
  - `sim`, `sim.gameloop`, `gl.ai`, `gl.motion`, `gl.subsystems`, `gl.proximity`;
  - `sim.combat` and its `cb.*` rows, `sim.weapons`, `sim.effects`, `sim.collisions`;
  - `sim.render_xforms` and `sim.input` **per frame** (they are not per-tick roots, `frame_profiler.py:125`);
  - `k0.compute`…`k4.compute`;
  - median projectiles in flight.

## 2. Avoidance isolation (one run)

Same command with `DAUNTLESS_COMBAT_AVOID=0` (`combat_stress.py:132-153`, avoidance preprocessor off). `gl.ai`'s drop against §1 is the whole AvoidObstacles cost, SDK script included. It is the bound on phase 1's saving.

## 3. Spike log for `sim.input` (one run)

Same command plus `DAUNTLESS_PROFILE_SPIKES=~/Documents/dauntless-perf/p0-spikes-<stamp>.log`. The default threshold is `DAUNTLESS_PROFILE_SPIKE_MS` = 100. C-286 used 30, which is under this scene's ≈ 50 ms frame, so nearly every frame was logged raw: useful as a per-frame series, not as spikes.

The question: is `sim.input`'s 1.1 ms per frame, against ≈ 0.1 ms of its own code (SIG-178 counter-signal), a few large frames (a cyclic-GC pass is the leading guess) or a steady cost?
- **If spikes:** a second run with a `gc.callbacks` timer that prints gen-2 pass durations confirms it. That is a scratch wrapper, never committed.
- **If steady:** list its callees (bridge-officer pick, raw-key loop, mouse buttons) from §4's cProfile.

## 4. cProfile (one run, as C-280)

- C-280 used "a scratch wrapper mission around `combat_stress`, enabled after `Initialize`, dumped at exit", with `DAUNTLESS_PROFILE_FRAMES=900`. The wrapper was never committed, so rebuild it in the session scratchpad:
  - a module that imports `engine.dev_missions.combat_stress`, re-exports its mission functions, and wraps `Initialize` to call `cProfile.Profile().enable()` after the original returns;
  - an `atexit` hook that dumps to `~/Documents/dauntless-perf/p0-cprof-brawl-on-cs64-bridge-<stamp>.prof`.
  - `PYTHONPATH` does NOT work: `host_main.cc` `configure_python_path` overwrites it. It does add `$VIRTUAL_ENV/lib/*/site-packages`, so C-287 used a scratch `VIRTUAL_ENV` whose `lib/` holds a symlink `python3.11` → the real `.venv/lib/python3.11` plus `lib/p0/site-packages/<wrapper>.py`, with `DAUNTLESS_MISSION=<wrapper>`.
- **Shares only.** cProfile slows the tick about 3×, so catch-up hits the 15-tick cap. Never read absolute times from it.
- **Read** with `python3 -I -c "import pstats; ..."` from the scratchpad, never from inside the project:
  - callers and callees of `GetNearObjects`, `_candidates`, `location_is_stored`, `TestCourseOverride`, `NeedToAvoid`, `IsTypeOf`, `_step_ship_motion`, `_integrate_rotation`, `impulse_fractions`, `_sync_instance_transforms`, `subsystem_glow.update` and `transform_buffer.sample`;
  - the result count per query: `NeedToAvoid` calls ÷ `GetNearObjects` calls;
  - the checks' share: `IsTypeOf` calls ÷ `NeedToAvoid` calls. Check first in a five-type list gives 1 call per check and 5 per non-skipped object.

## 5. New timer rows (add before §1, in the phase 0 commit)

Name and nest them as the native-combat rows are (`native-infra-patterns.md` §8):

| Row | Wraps | Parent | Per tick? |
|---|---|---|---|
| `ai.avoid` | the SDK AvoidObstacles `Update` call, inside `ai_optimized`'s wrapper | `gl.ai` | yes |
| `prox.near` | `ProximityManager.GetNearObjects` | whichever scope calls it (mostly `ai.avoid`) | yes |
| `prox.line` | `ProximityManager.GetLineIntersectObjects` | as above | yes |
| `motion.kernel` | phase 2's native call (added in phase 2, not now) | `gl.motion` | yes |

- Scopes cost about 0.36 µs each (SIG-168). At ≈ 4 near-queries a tick that is negligible, but take the baseline pair (§1) **with** the new rows, so later phases compare like with like.
- If `ai.avoid` and `prox.*` need to be per-tick roots for scoring, add them to `PER_TICK_ROOTS` only if they are not nested under a per-tick root already; they are, under `gl.ai`.

## 6. Bigger battles (for phase 5; can wait until phase 5)

The same as §1 at `DAUNTLESS_COMBAT_SHIPS=128` and `256`, one run each. Check the scene line: the ring placement has to fit, and the fight has to start. Record per-tick native compute (`k*.compute`, later `motion.kernel`) against Python rows.

## 7. Record

- Capture rows `C-28x…` and signals `SIG-18x` in `perf-register.md`, with the commit, Debug, the scene line, and frames/ticks. Never edit SIG-178.
- One signal for the baseline, one for avoidance isolation, one for the `sim.input` explanation, one for the cProfile shares.
- Then update the design's §5 savings column from the new numbers.
