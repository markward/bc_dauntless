# Performance register

The open performance problems, and the measured signals behind each one.
Read this before starting perf work. Update it whenever a capture is taken.

How to take and read a capture is in `docs/engine/frame-profiler.md`. This
file records **what the captures have shown** and **what we think it means**.
The two are kept apart on purpose.

## Rules

1. **Signals and issues are kept separate.** A signal is what a capture showed,
   with its numbers and the capture it came from. An issue is our reading of one
   or more signals. A new capture adds signals. It changes an issue only by
   citing them.
2. **Every signal has an evidence tier.**
   - **Measured:** read directly off a capture.
   - **Derived:** computed from measured numbers, with the method stated.
   - **Inferred:** our explanation of measured numbers, not yet tested.
3. **Counter-signals are recorded as well.** If a capture shows something is
   cheap, write that down. It is what stops us optimising the wrong thing.
4. **Never edit an old signal to match a new capture.** Add a new signal and
   mark the old one superseded. The history is what shows a fix worked.
5. **Only compare like with like:** the same scenario, build type, machine and
   window size. Read the scene line before trusting any number
   (`frame-profiler.md`, "Combat load").

---

## Baseline scenarios

`DAUNTLESS_PROFILE_FRAMES` turns the profiler on from boot and sets swap
interval 0, so frames are uncapped. It is set far beyond any session's length,
so the run lasts until you quit. A report is printed every 120 frames, plus
a final one on quit. Logs go **outside the project**, to
`~/Documents/dauntless-perf/`.

### B1 — E1M2, Haven Facility death at Vesuvi

```bash
DAUNTLESS_MISSION=Maelstrom.Episode1.E1M2.E1M2 DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/e1m2-haven-death-$(date +%Y%m%d-%H%M).log
```

1. Warp to Vesuvi.
2. Target the Haven Facility and press `]`. This is the dev key that destroys
   the target through the real death path (`engine/dev_keybindings.py`).
3. Wait for the death sequence to finish, then quit.

### B2 — Quick Battle, Sovereign vs 2 Birds of Prey

```bash
DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/qb-sov-vs-2bop-$(date +%Y%m%d-%H%M).log
```

1. In the setup screen, the player flies the Sovereign against two Birds of
   Prey. Save this as a preset.
2. Fight, then quit once the battle ends.

⚠️ **The ending is not yet fixed.** The plan was to end by ramming. C-002
could not ram, so the Birds of Prey were destroyed by weapons. Until the
ending is fixed (for example, `]` on each Bird of Prey after a set time), B2
runs are only roughly comparable.

### To catch hitches

Add `DAUNTLESS_PROFILE_SPIKES=<path> DAUNTLESS_PROFILE_SPIKE_MS=50` in place
of `DAUNTLESS_PROFILE_FRAMES`. This logs every frame of 50 ms or more, raw. It
turns off the periodic report, so it needs its own run (M-5).

---

## Captures

| ID | Date | Scenario | Commit | Build | Machine | Frames / reports | Notes |
|---|---|---|---|---|---|---|---|
| C-001 | 2026-10-17 22:18 | B1 | `57e6b66a` | **Debug** | M3 Pro, 3840×1200 external + built-in Retina | 2,683 / 23 | Window size not recorded. Sim paused in report 2. Exterior view from report 13. The kill shows as hull-damaged going 1→2 at report 14. |
| C-002 | 2026-10-17 22:20 | B2 | `57e6b66a` | **Debug** | same | 19,069 / 159 | Window size not recorded. Idle on bridge for reports 0–7, battle from about report 13. Ended by destroying the Birds of Prey, not by ramming. |

Log files: `~/Documents/dauntless-perf/e1m2-haven-death-20261017-2218.log` and
`qb-sov-vs-2bop-ram-20261017-2220.log`.

⚠️ **Both captures are from a Debug build.** C++ CPU scopes are slower than
they would be in Release; Python scopes are not affected. Do not compare these
captures against a Release capture.

### Headline numbers

The loop is the whole frame. fps = 1000 / loop. The numbers are averages over
the reports given.

| Capture, stage (reports) | Loop ms | ~fps | GPU ms | Largest GPU pass |
|---|---|---|---|---|
| C-001 bridge, before warp (3–12) | 35–38 | 26–28 | 14–19 | `bridge` 13.1 |
| C-001 Vesuvi exterior (13–21) | 44–52 | 19–23 | 28–31 | `space` 27.6 |
| C-002 bridge, before battle (0–4) | 18–22 | 45–54 | 5–7 | `bridge` 5.0–6.7 |
| C-002 combat (20–157) | 27–28 typical, 35 worst | 36 typical | 14–15 | `space` 8.5 |

---

## Signals

Newest first. Report numbers start at 0, in log order.

The numbers are exponential moving averages (EMA) with alpha 0.15. One slow
frame of X ms adds at most 0.15·X to the next report. A one-report jump of
J ms therefore means **one frame of at least J / 0.15 ms**. This is a lower
bound, not the actual size.

| ID | Capture | What the data shows | Tier | Feeds |
|---|---|---|---|---|
| SIG-015 | C-001, C-002 | The scene line's ship count does not fall when a ship dies (24 throughout C-001; 3 throughout C-002). Only hull-damaged changes. | Measured | M-3 |
| SIG-014 | C-002 | Combat `sim` is 1.3–2.0 ms with 3 ships and 3–16 projectiles. **Counter-signal:** at this scale the Python sim is cheap. | Measured | A-4 |
| SIG-013 | C-001, C-002 | `ui_panels` is 0.5–1.8 ms throughout both captures. **Counter-signal:** cheap at 3 and 24 ships. Earlier captures saw 10–17 ms at 17 ships. | Measured | P-8 |
| SIG-012 | C-002 | Before the battle, on the bridge, `render_prep` is about 6 ms (reports 0–4). After that it is 0.2–0.8 ms, and in C-001's bridge it is 0.3 ms. | Measured | P-7 |
| SIG-011 | C-001, C-002 | `anim` CPU is 2.7–2.8 ms every frame in C-001 and 1.5–1.7 ms in C-002. It stays the same in exterior view, when no bridge is drawn. | Measured | P-6 |
| SIG-010 | C-001 r18 | After the kill, `viewscreen.rtt` CPU is 11.3 ms: `space.carve_stencil` 6.2 ms + `space.breach` 4.4 ms. That is the damaged station on the bridge viewscreen. | Measured | P-5 |
| SIG-009 | C-002 r20–157 | The post chain's GPU time in combat is `dof` 1.03 + `bloom` 1.38 + `resolve` 0.97 + `post` 1.65 = **5.0 ms**, about 35% of a 14 ms GPU frame. | Measured | P-3 |
| SIG-008 | C-001, C-002 | The `bridge` pass GPU time is 13.1 ms average in C-001 reports 3–12, but 3.2–4.8 ms in reports 0–2 of the same session, and 5.0–6.7 ms in C-002. The cause of the jump is unknown. | Measured | P-2 |
| SIG-007 | C-001 r13–21 | At Vesuvi, the `space` pass GPU time averages **27.6 ms**, against 8.5 ms in C-002 combat. The sub-passes cannot be timed (M-1). | Measured | P-1, M-1 |
| SIG-006 | C-001 r0–12 | Before the warp, `sim` is about 8 ms, of which **about 6.5 ms is outside every child scope**. After the warp the unscoped part is about 0.8 ms. | Derived (`sim` minus the sum of its direct children) | M-2 |
| SIG-005 | C-002 r7 | When the battle starts (ships go from 1 to 3), `sim` jumps to 9.4 ms, 8.8 ms of it unscoped. That means one frame of at least about 60 ms. | Derived (EMA bound) | A-2, M-2 |
| SIG-004 | C-002 r151 | When a Bird of Prey dies, `cb.damage_sys` jumps to 8.1 ms, so one frame of at least about 54 ms. | Derived (EMA bound) | A-2, P-4 |
| SIG-003 | C-001 r16 | At the Haven death, `cb.damage_sys` jumps from about 0 to **71.9 ms**, so one frame of **at least about 480 ms**. `sim.debris_chunks` reaches 7.5 ms and `space.opaque` CPU 8.8 ms in the same report. By the next report `cb.damage_sys` is 3.4 ms. | Derived (EMA bound) | A-2, P-4 |
| SIG-002 | C-002 combat | The frame costs the CPU's work **plus** the GPU's, not the larger of the two. In a typical report the loop is 27.6 ms: `cef.composite` CPU 15.7 ms (about the GPU frame of 14.3 ms) plus about 12 ms of other CPU work. | Derived | A-1 |
| SIG-001 | C-001, C-002 | The `cef.composite` CPU time tracks the whole GPU frame time across every report (**r = 0.992** in C-002, **0.994** in C-001). Examples: 15.7 vs 14.3 ms, 30.4 vs 31.4 ms. | Measured (correlation). The reason is inferred: see A-1. | A-1 |

---

## Issues — architectural

| ID | Issue | Status | Signals | Next step |
|---|---|---|---|---|
| A-1 | **The CPU and GPU take turns instead of overlapping.** Each frame the CPU stalls in `cef.composite` until the GPU has finished, then does its own work. Frame time is about CPU + GPU, not the larger of the two. | **Inferred, strongly supported.** The suspected mechanism is that the full-surface `glTexSubImage2D` of the CEF texture forces a sync on Apple's GL. This is not proven. | SIG-001, SIG-002 | Experiment: skip the upload on frames with no new CEF paint, then check whether loop time falls toward the larger of CPU and GPU. A damage-only upload plan is drafted and parked at `~/.claude/plans/wise-rolling-kite.md`. A PBO or double-buffered texture is the fallback. Potential gain: close to 2× in every scene. |
| A-2 | **Heavy one-off work runs inside a single frame, with no budget.** Deaths, battle start and warp arrival each do their work all at once. | Measured (as lower bounds) | SIG-003, SIG-004, SIG-005; `frame-profiler.md` warp-tunnel frames of 100–180 ms | Size each case with a spike capture. Then add a common way to spread work across frames or prepare it on a worker, instead of each subsystem doing its own thing. |
| A-3 | **Only some work can move to another thread.** CEF cannot: on macOS its UI thread must be the main thread. The Python sim cannot gain from threads because of the GIL. C++ work that doesn't touch Python can (asset decode, rock streaming, voxel carve), with a short GPU upload step at the end. | Constraint | — | Use this for A-2. Do not reopen the CEF-thread idea (see the CEF threading memory). |
| A-4 | **Sim cost grows with the number of Python calls.** Earlier captures: about 200,000 calls per tick at 100 ships, scaling linearly. `TimeSliceProcess` and sim LOD are barely used. | Measured in earlier captures. **Not visible in B1 or B2** (SIG-014). | SIG-014 (counter) | Add a large-fleet baseline (B3, for example `combat_stress` with 33+ ships) so this issue has signals of its own. |

## Issues — expensive systems

| ID | System | Status | Signals | Next step |
|---|---|---|---|---|
| P-1 | `space` pass at Vesuvi, 27.6 ms GPU | Measured; cause unknown | SIG-007 | Close M-1 first. Candidates: system haze, rock puffs (2000), rock fields, planets. None tested. |
| P-2 | `bridge` pass, 13 ms GPU at times | Measured; cause of the 3→13 ms jump unknown | SIG-008 | Find what changed between C-001 reports 2 and 3 (alert state, probe capture, camera). Candidates: reflection-probe fill, SSAO quality, PBR lights. |
| P-3 | Post chain (dof + bloom + resolve + post), 5 ms GPU | Measured | SIG-009 | Cost each pass against what it adds visually. DOF alone is 0.9–2.2 ms. |
| P-4 | Death damage path (`cb.damage_sys`, `sim.debris_chunks`) | Measured, lower bound ≥ 480 ms | SIG-003, SIG-004 | Spike capture of B1, then find what `damage_sys` does all at once on death. Linked to A-2. |
| P-5 | Damaged hull on the viewscreen (`carve_stencil` + `breach`), 11 ms CPU | Measured, one report | SIG-010 | Check whether per-frame work could be cached while the damage is unchanged. |
| P-6 | `anim` bone palettes, 1.5–2.8 ms CPU every frame | Measured | SIG-011 | Skip instances that are not visible (e.g. the bridge crew in exterior view) or far away. `frame-profiler.md` already notes there is no gate. |
| P-7 | `render_prep` about 6 ms on the Quick Battle bridge before the battle | Measured; cause unknown | SIG-012 | Find which child scope is responsible. `frame-profiler.md`'s first capture saw 15.8 ms in the same scene. |
| P-8 | `ui_panels` (Python) at scale | Cheap at B1/B2 scale; 10–17 ms in earlier 17-ship captures | SIG-013 (counter) | Measure in B3. Profile each panel. The sensors panel may re-send its data every frame (inferred from the code). |
| P-9 | AI avoidance all-pairs scan | Earlier captures only | — | Needs B3. A spatial broadphase, as the projectile loop got. |

---

## Measurement gaps

Each of these limits what a capture can tell us. Closing one is perf work in
its own right.

| ID | Gap | Effect | Fix |
|---|---|---|---|
| M-1 | Apple GL can only time top-level passes. Nested rows print `-` for GPU. | P-1's 27.6 ms cannot be broken down. | An opt-in mode that promotes one chosen sub-pass to top level. |
| M-2 | Some `sim` time is outside every child scope. | About 6.5 ms in E1M2 before the warp (SIG-006), and the battle-start hitch (SIG-005), cannot be attributed. | Add scopes until the unscoped part is under 0.5 ms. |
| M-3 | The log has no event markers (warp arrival, ship death, battle start), and the scene line does not count deaths (SIG-015). | Reports are lined up with game events by inference. | Print a one-line marker to stderr on each such event while the profiler is on. |
| M-4 | Capture details are not written to the log: window size, build type, commit, quality settings. | C-001 and C-002 lack window size. Build type had to be read from `CMakeCache.txt`. | Print a header line when profiling starts. |
| M-5 | The periodic report and spike capture cannot run together. | A hitch in a periodic capture gives only a lower bound (the EMA rule above). | Allow both at once, or always pair a periodic run with a spike run. |
| M-6 | The profiler is not free: +0.6 ms idle, +2.4 ms loaded (`frame-profiler.md`). | Every number here includes it. | Keep it on for every baseline, so comparisons stay fair. |
