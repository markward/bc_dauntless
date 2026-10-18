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

### B1 — E1M2, Haven Facility death at Vesuvi (unattended)

E1M2 starts at Haven; no warp is needed. The station's object name is
`Facility`. The run needs nobody at the keyboard:

```bash
DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=Maelstrom.Episode1.E1M2.E1M2 DAUNTLESS_PROFILE_FRAMES=100000000 DAUNTLESS_DEV_DESTROY=Facility DAUNTLESS_DEV_VIEW=exterior DAUNTLESS_DEV_QUIT_AFTER_S=40 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/b1-$(date +%Y%m%d-%H%M).log
```

`engine/dev_scripted_run.py` waits for the opening cutscene to end, switches
to the exterior view, destroys `Facility` 10 s later through the same death
path as the `]` dev key, and quits 40 s after that. Each step prints a
`[dev-scripted]` line into the log. The window size is pinned
(`DAUNTLESS_WINDOW_SIZE`), and the `[profile]` header line records the
framebuffer actually drawn.

⚠️ **The window opens on the main display.** On the external 1× monitor,
1280x720 draws 1280x720 pixels. On the 2× laptop screen, the same window draws
four times as many. Compare only captures with the same `[profile]`
framebuffer line.

### B2 — Felix: Destroy, five Birds of Prey vs one Sovereign (unattended)

```bash
DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.felix_destroy DAUNTLESS_DEV_AUTOQUIT=1 DAUNTLESS_DEV_VIEW=exterior DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/b2-$(date +%Y%m%d-%H%M).log
```

`engine/dev_missions/felix_destroy.py`: the player's Bird of Prey and four AI
Bird of Prey wingmen in a V, against one enemy Sovereign 40 GU ahead. After 3 s
the player targets the Sovereign and Felix's Destroy order is pressed through
the Orders pane's real button. The run quits 5 s after the first
`ET_OBJECT_DESTROYED`, or at a 180 s cap. Each step prints a
`[felix_destroy]` line into the log.

The fight still varies run to run, so the time to the first kill is part of
each capture, not a constant. The earlier hand-run B2 (Quick Battle, the
player's Sovereign against two Birds of Prey, C-002) is retired: its ending
depended on the player.

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
| C-003 | 2026-10-17 22:53–22:59 | `combat_stress`, 4 ships, `DAUNTLESS_CEF_UPLOAD` = always / on_paint / never, visible window | `perf/cef-upload-sync` (pre-`60b74418`) | **Debug** | same | 3,000 each | ⚠️ Ran **during a pytest run** (CPU contention), and the binary **lacked the `cef.upload`/`cef.draw` scopes** (a stale `host_bindings.cc` object). Use only for upload counts and relative `cef.composite`. |
| C-004 | 2026-10-17 23:03 | `combat_stress`, 4 ships, always, **headless** | `perf/cef-upload-sync` | **Debug** | same | 3,000 | First capture with the `cef.upload` / `cef.draw` scopes. |
| C-005 | 2026-10-17 23:05 | as C-004, plus draw section timing | `perf/cef-upload-sync` | **Debug** | same | 3,000 | |
| C-006 | 2026-10-17 23:07 | as C-005, **profiler off** (`timeout 90`) | `perf/cef-upload-sync` | **Debug** | same | ~6 stats lines | Timing from the `[cef-upload]` line only. |
| C-007 | 2026-10-17 23:08–23:11 | `combat_stress`, paired profiler on (3,600 frames) / off (`timeout 100`), headless | `60b74418` code | **Debug** | same | 5 / 7 stats lines | Frame time from the `[cef-upload]` line, independent of the profiler. |
| C-008 | 2026-10-17 23:12–23:15 | `rock_fields_inside`, paired profiler on (3,000) / off (`timeout 100`), headless | `60b74418` code | **Debug** | same | 4 / 7 stats lines | GPU frame about 10.5 ms with the profiler on (bridge view). |
| C-009 | 2026-10-18 08:34 | `rock_fields_inside`, **CPU-only profiler** (the new default), 3,000 frames, headless | `perf/cef-upload-sync` | **Debug** | same | 3,000 | First capture in the CPU-only mode. Frame time from both the report and the `[cef-upload]` line. |
| C-010 | 2026-10-18 08:41 | B1, by hand | **old build** (main checkout, GPU timing on) | **Debug** | 4K laptop screen, window size not recorded | 26 reports | Meant as the CPU-only re-run, but ran from the main checkout. Another GPU-timed capture, comparable to C-001. |
| C-011 | 2026-10-18 08:44 | B1 unattended, headless, **bridge view only** | `perf/cef-upload-sync` | **Debug** | 1280x720 | 37 reports | First unattended run. Stayed on the bridge, so not comparable to C-001. |
| C-012 | 2026-10-18 08:47 | B1 unattended, headless, exterior | `perf/cef-upload-sync` | **Debug** | 1280x720 | 47 reports | |
| C-013 | 2026-10-18 08:50 | B1 unattended, **visible**, exterior | `perf/cef-upload-sync` | **Debug** | framebuffer 1280x720 (external monitor, 1×) | 35 reports | First capture with the `[profile]` header line. |
| C-014 | 2026-10-18 08:52 | B1 unattended, visible, exterior | `perf/cef-upload-sync` | **Debug** | framebuffer 1512x945 (external monitor, 1×) | 45 reports | Aimed at the laptop's maximised size, but opened on the 1× monitor. |
| C-015 | 2026-10-18 09:36 | **B2 (Felix: Destroy)** unattended, headless, exterior | `perf/cef-upload-sync` | **Debug** | framebuffer 1280x720 | 17,225 frames / 144 reports | First ship destroyed: the enemy Sovereign, exploding at report 134 (about 160 s in), removed at report 139. |

Logs for C-003 to C-008: `~/Documents/dauntless-perf/cef-*.log`, `cef2-*` …
`cef6-*`.

C-001 and C-002 ran maximised on the 4K laptop screen (Retina, 2×), so they drew
several times the pixels of the 1280x720 captures below.

Log files: `~/Documents/dauntless-perf/e1m2-haven-death-20261017-2218.log` and
`qb-sov-vs-2bop-ram-20261017-2220.log`.

⚠️ **Both captures are from a Debug build.** C++ CPU scopes are slower than
they would be in Release; Python scopes are not affected. Do not compare these
captures against a Release capture.

### Headline numbers

The loop is the whole frame. fps = 1000 / loop. The numbers are averages over
the reports given.

⚠️ **These loop times are inflated by roughly the GPU frame time.** With its
GPU timer on, the profiler makes the CPU wait for the GPU every frame
(SIG-019). Without the profiler the CPU and GPU overlap. Treat these numbers as
an upper bound until B1 and B2 are re-captured with the CPU-only profiler, which is now the default (M-6).

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
| SIG-026 | C-015 | B2 at 1280x720, exterior, 6 ships and 0–20 projectiles in flight: about **10 ms** per frame (about 100 fps) for most of the fight, rising to 11–12.5 ms near the end. The Sovereign's death costs `cb.damage_sys` 7.6 ms in the death report (one frame of at least about 50 ms), with `space.particles` 1.7 ms. `cb.damage_sys` now hitches at a death in all three scenarios (C-001, C-012–14, C-015). | Measured / derived (EMA bound) | P-4, A-2 |
| SIG-025 | C-011 | On the E1M2 bridge after the cutscene, `render_prep` is about **6 ms** (0.3 ms during the cutscene). So P-7 is not specific to Quick Battle. | Measured | P-7 |
| SIG-024 | C-012, C-013, C-014 | **The Facility destroy hitch varies widely between identical runs.** `sim` in the destroy report: 7.6 ms (C-012), 7.8 ms (C-013), **211 ms** (C-014), meaning one frame of at least about 50 ms in the first two and about 1.4 s in the last. Mostly `cb.damage_sys` again. | Derived (EMA bound) | P-4, A-2 |
| SIG-023 | C-013, C-014 | **The drawn size moves the exterior from CPU-bound to GPU-bound.** Before the destroy at Vesuvi, the frame is 12.3 ms at 1280x720 and 19.0 ms at 1512x945 (1.55× the pixels). `cef.composite` is 0.5 vs **8.0 ms**: in CPU-only mode it is the CPU waiting for a GPU that is behind (real backpressure, not the M-6 artifact). | Measured | P-1, M-4 |
| SIG-022 | C-013 | CPU-only B1 at 1280x720: opening cutscene on the bridge about **20 ms** (49 fps); exterior at Vesuvi about **12.5 ms** (80 fps). During the cutscene `sim` is 7.8 ms with about 6 ms outside every child scope; after it, 1.8 ms. **The unscoped sim time of SIG-006 belongs to the cutscene.** | Measured | M-2 |
| SIG-021 | C-009 vs C-008 | With the CPU-only profiler, `rock_fields_inside` runs at **22.9 ms** per frame: 1.6 ms above profiler-off (21.3 ms) and 6.8 ms below GPU-timed (29.7 ms). `cef.composite` drops to 0.52 ms, the upload alone. The report's python loop total (22.7 ms) matches the profiler-independent frame time (22.9 ms). | Measured | M-6 |
| SIG-020 | C-003, C-004, C-007 | The overlay rarely repaints in `combat_stress` and `rock_fields_inside`: 3–31 paints in total over 2,400–4,200 frames. With `on_paint`, 96–100% of uploads are skipped. A full-surface upload costs about **0.53 ms CPU** a frame (headless window size). Not measured in a HUD-heavy scene. | Measured | P-10 |
| SIG-019 | C-007, C-008 | **The profiler's GPU timing adds roughly the GPU frame time to every frame.** Frame time measured without the profiler: `combat_stress` 25.4 ms on vs 22.2 ms off (GPU about 2.7 ms); `rock_fields_inside` 29.7 ms on vs 21.3 ms off (GPU about 10.5 ms). With the profiler on, the overlay draw takes 2.5 ms and 7.7 ms respectively; with it off, 0.005 ms. The wait does not move elsewhere; it disappears. | Measured | A-1, M-6 |
| SIG-018 | C-006 | With the profiler off, the overlay draw section takes **0.005 ms**, against 2.6 ms with it on in the same scene (C-005). | Measured | A-1, M-6 |
| SIG-017 | C-005 | Inside `cef.draw`, the GL state queries (`glIsEnabled`, `glGetIntegerv`) take 0.000 ms and setup 0.001 ms. The whole wait (about 2.6 ms) is in the block that sets state and calls `glDrawArrays` into the default framebuffer. | Measured | A-1 |
| SIG-016 | C-004 | `cef.upload` is a steady 0.52–0.63 ms, even when uploading every frame. `cef.draw` varies from 0.8 to 3.0 ms and follows the GPU frame time. **The upload is not where the CPU waits.** | Measured | A-1 |
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
| SIG-002 *(superseded by SIG-019: the serialisation is caused by the profiler)* | C-002 combat | The frame costs the CPU's work **plus** the GPU's, not the larger of the two. In a typical report the loop is 27.6 ms: `cef.composite` CPU 15.7 ms (about the GPU frame of 14.3 ms) plus about 12 ms of other CPU work. | Derived | A-1 |
| SIG-001 | C-001, C-002 | The `cef.composite` CPU time tracks the whole GPU frame time across every report (**r = 0.992** in C-002, **0.994** in C-001). Examples: 15.7 vs 14.3 ms, 30.4 vs 31.4 ms. | Measured (correlation). The reason is inferred: see A-1. *Cause found in SIG-019: the profiler.* | A-1 |

---

## Issues — architectural

| ID | Issue | Status | Signals | Next step |
|---|---|---|---|---|
| A-1 | ~~The CPU and GPU take turns instead of overlapping.~~ | **Closed: not an engine problem.** The serialisation is real only while the profiler's GPU timer is on, and it disappears without it (SIG-019). The upload was never the cause (SIG-016, SIG-017). Moved to M-6. | SIG-001, SIG-002, SIG-016–SIG-019 | None for the engine. The upload policy stays as a small separate win (P-10). |
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
| P-10 | CEF overlay full-surface upload, about 0.53 ms CPU a frame even when nothing repainted | Measured; small | SIG-020 | `DAUNTLESS_CEF_UPLOAD=on_paint` (branch `perf/cef-upload-sync`) skips unrepainted frames losslessly. Measure the paint rate in a HUD-heavy scene (B2) before deciding whether to make it the default. |

---

## Measurement gaps

Each of these limits what a capture can tell us. Closing one is perf work in
its own right.

| ID | Gap | Effect | Fix |
|---|---|---|---|
| M-1 | Apple GL can only time top-level passes. Nested rows print `-` for GPU. | P-1's 27.6 ms cannot be broken down. | An opt-in mode that promotes one chosen sub-pass to top level. |
| M-2 | Some `sim` time is outside every child scope. It happens during the E1M2 opening cutscene (SIG-022). | About 6.5 ms in E1M2 before the warp (SIG-006), and the battle-start hitch (SIG-005), cannot be attributed. | Add scopes until the unscoped part is under 0.5 ms. |
| M-3 | The log has no event markers (warp arrival, ship death, battle start), and the scene line does not count deaths (SIG-015). **Partly closed:** an unattended run prints `[dev-scripted]` lines for cutscene start/end, view, destroy and quit. | Reports are lined up with game events by inference. | Print a one-line marker to stderr on each such event while the profiler is on. |
| M-4 | Capture details are not written to the log: window size, build type, commit, quality settings. **Partly closed:** a `[profile]` line now records framebuffer and window size, headless, and GPU timing; `DAUNTLESS_WINDOW_SIZE=WxH` pins the size. Build type, commit and quality settings are still missing. | C-001 and C-002 lack window size. Build type had to be read from `CMakeCache.txt`. | Print a header line when profiling starts. |
| M-5 | The periodic report and spike capture cannot run together. | A hitch in a periodic capture gives only a lower bound (the EMA rule above). | Allow both at once, or always pair a periodic run with a spike run. |
| M-6 | **Mitigated on `perf/cef-upload-sync`: the profiler is now CPU-only by default; `DAUNTLESS_PROFILE_GPU=1` opts in to GPU timing** (SIG-021). With its GPU timer on, the profiler adds roughly the GPU frame time to every frame (SIG-019). It makes the CPU wait for the GPU, and the wait shows up in the overlay's draw call inside `cef.composite`. The earlier `frame-profiler.md` figure (+0.6 to +2.4 ms) came from a light headless bench and understates it. Mechanism not established. | Every loop time in C-001 and C-002 is inflated by about their GPU time. `cef.composite` reads as a big cost when it is really the profiler's wait. | Done: CPU-only is the default. Remaining: re-capture B1 and B2 in CPU-only mode. The CPU-only profiler still costs about 1.6 ms a frame (SIG-021). |
