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

### B2d — B2 with a scripted Sovereign kill (unattended)

B2 does not always produce a kill inside its 180 s cap (SIG-035). For a death
that happens every run, add the B1 destroy hook to B2:

```bash
DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.felix_destroy DAUNTLESS_DEV_AUTOQUIT=1 DAUNTLESS_DEV_VIEW=exterior DAUNTLESS_DEV_DESTROY=Enemy-Sovereign DAUNTLESS_DEV_QUIT_AFTER_S=40 DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/b2d-$(date +%Y%m%d-%H%M).log
```

The Sovereign dies 10 s in through the same death path as `]`, and the run
quits 5 s after `ET_OBJECT_DESTROYED`.

### B3 — Vesuvi Dust Cloud, parked, looking into the cloud (unattended)

For the system nebula and dust passes without B1's rock belt:

```bash
OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.vesuvi_dust_cloud DAUNTLESS_DEV_AUTOQUIT=1 DAUNTLESS_DEV_VIEW=exterior DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer 2>&1 | tee ~/Documents/dauntless-perf/b3-$(date +%Y%m%d-%H%M).log
```

`engine/dev_missions/vesuvi_dust_cloud.py`: the player Galaxy parked at
Vesuvi4's own "Player Start", 335 GU outside the cloud's MetaNebula sphere and
facing into it. No NPCs, no scripted events; the only rocks are Vesuvi4's 12
stock asteroids and what the Vesuvi profile adds. The player is made immune
to damage (`SetInvincible`), because the cloud's radiation and nebula damage
skip the God Mode check. 5 s in, the run switches to the exterior view and
prints `[vesuvi_dust_cloud] settled`, the start of the measured window. It
quits 60 s after that. Read the frame times from the reports after `settled`.

For nebula work, run it at `DAUNTLESS_WINDOW_SIZE=3840x2160`: there the frame is
GPU-bound, so frame time is the GPU cost (SIG-083). At 1280x720 the frame is
CPU-bound (SIG-078) and the GPU-focus spans are too noisy to rank changes
(SIG-082).

`DAUNTLESS_DEV_SCREENSHOT=<path.png>` writes one frame 5 s after `settled`, so
before/after builds picture the same moment.

The SDK `Initialize` of Vesuvi4 runs as in any mission, and `system_loader`
brings up the sibling Vesuvi regions on the first tick, as in real play.

### To attribute GPU cost

Two tools, both from boot, both used for P-1 (SIG-065, SIG-066):

- `DAUNTLESS_PROFILE_GPU_FOCUS=space.opaque,rock.puffs.draw,...` GPU-times
  those nested scopes as well as the top-level passes (M-1). It turns GPU
  timing on, so the frame times of that run are not real (M-6).
- `DAUNTLESS_DEV_RENDER_OFF=rock_puffs,volumetric_nebulae,...` (with
  `--developer`) switches features off at boot for a CPU-only A/B run. The
  names are in `engine/dev_render_off.py`; an unknown name stops the boot.

Confirm any large focus row with an A/B: on this tile-based GPU a span can
hold work deferred from earlier draws.

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
| C-016 | 2026-10-18 10:00 | B1, **spike capture** (30 ms), headless | `perf/death-hitch` @ `8ca120a7` (= int/2026-10-18-01) | **Debug** | framebuffer 1280x720 | 42 spikes | `p4-b1-pre-1`. 15 freezes after the death. |
| C-017 | 2026-10-18 10:03 | as C-016 | same | **Debug** | 1280x720 | 32 spikes | `p4-b1-pre-2`. 6 freezes. |
| C-018 | 2026-10-18 10:05 | as C-016 | same | **Debug** | 1280x720 | 26 spikes | `p4-b1-pre-3`. 4 freezes. |
| C-019 | 2026-10-18 10:08 | B2, spike capture (30 ms), headless | same | **Debug** | 1280x720 | 7 spikes | `p4-b2-pre-1`. **No kill**: quit at the 180 s cap. |
| C-020 | 2026-10-18 10:11 | as C-019 | same | **Debug** | 1280x720 | 17 spikes | `p4-b2-pre-2`. **No kill** again. |
| C-021 | 2026-10-18 10:14 | **B2d**, spike capture (30 ms), headless | same | **Debug** | 1280x720 | 9 spikes | `p4-b2d-pre-1`. Sovereign destroyed by script at about 11 s. |
| C-022 | 2026-10-18 10:17 | B1, spike capture with the new `dmg.*`/`vd.*`/`hb.*`/`dc.*` scopes | same + scopes | **Debug** | 1280x720 | 246 spikes | `p4-b1-scoped-1`. |
| C-023 | 2026-10-18 10:21 | B1 + macOS `sample` (15 s at 1 ms) from the destroy | same + scopes | **Debug** | 1280x720 | — | `p4-b1-sample`; stack file in session scratch, not kept. |
| C-024 | 2026-10-18 10:24–10:45 | B1 with a **temporary** per-carve timing print (native and Python), four runs | scratch builds, never committed | **Debug** | 1280x720 | — | `p4-b1-diag`…`diag4`. For carve sizes and counts only: the print itself costs time (a full-field copy per carve in diag3). |
| C-025 | 2026-10-18 10:33–10:38 | B1 spike capture ×3, **first fix** (skip +127 cells, tight box, whole-box fill) | uncommitted intermediate | **Debug** | 1280x720 | — | `p4-b1-post-1`…`3`. Superseded by C-026. |
| C-026 | 2026-10-18 10:47–10:53 | B1 spike capture ×3, **block fill** | `87d93f22` | **Debug** | 1280x720 | 55 / 34 / 24 spikes | `p4-b1-post2-1`…`3`. |
| C-027 | 2026-10-18 10:50 | B2d spike capture | `87d93f22` | **Debug** | 1280x720 | 8 spikes | `p4-b2d-post-1`. |
| C-028 | 2026-10-18 10:51 | B2d + `sample` (20 s at 1 ms) from the destroy, spike threshold 100 ms | `87d93f22` | **Debug** | 1280x720 | 2 spikes (boot) | `p4-b2d-sample`. |
| C-029 | 2026-10-18 11:40 | B1 spike capture, **cold cache** after the baker-version bump | `5c11fe03` (uncommitted at run time) | **Debug** | 1280x720 | — | `p4-b1-cap-warm`. The prebake thread rebaked all 74 hulls in 113 s during the run: CPU contention, used only to warm the cache and read the new lattice sizes. |
| C-030 | 2026-10-18 11:45–11:51 | B1 spike capture ×3, **lattice sized by hole modifier**, warm cache | `5c11fe03` | **Debug** | 1280x720 | 16 / 15 / 15 spikes | `p4-b1-cap-1`…`3`. Prebake found 74/74 valid in 0.8 s. |
| C-031 | 2026-10-18 11:58 | B2d spike capture, lattice sized by hole modifier | `5c11fe03` | **Debug** | 1280x720 | 9 spikes | `p4-b2d-cap-1`. |
| C-032 | 2026-10-18 13:12 | B1 spike capture (20 ms), with a `vd.resolve` scope | `5c11fe03` + scope | **Debug** | 1280x720 | — | `p4-b1-cap-resolve`. |
| C-033 | 2026-10-18 13:30–13:35 | B1 spike capture (20 ms) ×3, **trace BVH prewarmed at spawn** | `16a686606` | **Debug** | 1280x720 | — | `p4-b1-bvh-1`…`3`. |
| C-034 | 2026-10-18 13:45–14:00 | B2d with **temporary** per-carve / per-deposit prints, two runs | scratch builds, never committed | **Debug** | 1280x720 | — | `p4-b2d-diag`, `p4-b2d-dep`. Carve sizes, slot radii and counts only. |
| C-035 | 2026-10-18 14:03–14:08 | B2d A/B, **every frame logged** (`SPIKE_MS=0`), unchanged-slot skip off ×2 / on ×2 | `83c55042` with the condition removed by copy / as committed | **Debug** | 1280x720 | 713 / 844 / 1043 / 786 frames after the death | `p4-b2d-all-noskip-1,2`, `p4-b2d-all-skip-1,2`. Logging every frame costs time itself: compare scope totals, not frame times. Earlier 20 ms A/B (`p4-b2d-noskip/skip-*`) could not see the breach frames. |
| C-036 | 2026-10-18 14:15 | B2d, every frame logged ×2, **breach field carved once** | `e19e2903` | **Debug** | 1280x720 | 651 / 659 frames after the death | `p4-b2d-all-defer-1,2`. |
| C-037 | 2026-10-18 14:20–14:22 | B2d, every frame logged, with `death.*` then `casc.*` scopes, plus one run with a **temporary** cProfile around the first cascade blast | `e19e2903` + scopes; cProfile build never committed | **Debug** | 1280x720 | — | `p4-b2d-death-1,2`, `p4-b2d-prof`. |
| C-038 | 2026-10-18 14:24 | B2d, every frame logged ×2, **Effects imported at boot** | `a80a45c0` | **Debug** | 1280x720 | — | `p4-b2d-effects-1,2`. |
| C-039 | 2026-10-18 14:35–14:37 | B2d, every frame logged ×2, **carve budget** | `bea8f97e` | **Debug** | 1280x720 | 1198 / 742 frames after the death | `p4-b2d-budget-1,2`. |
| C-040 | 2026-10-18 14:40–14:41 | B2d under `sample` (25 s from the death) until a lone `space.opaque` spike appeared: run 2 | `bea8f97e` | **Debug** | 1280x720 | — | `p4-b2d-p11-1,2`; stack file in session scratch, not kept. |
| C-041 | 2026-10-18 14:43 | B1 spike capture (20 ms), carve budget | `bea8f97e` | **Debug** | 1280x720 | — | `p4-b1-budget-1`. |
| C-042 | 2026-10-18 15:27 | Headless timing script: `init`, `set_project_asset_root`, then `prewarm_scuff_normal_texture` twice, ×3 | `e5e2e3b7` | **Debug** | 320x200 | — | Script in session scratch. Times the load directly instead of waiting for a random first scuff. |
| C-043 | 2026-10-18 15:28–15:29 | B2d spike capture (100 ms) ×3 | `e5e2e3b7` | **Debug** | 1280x720 | 2 spikes each (boot) | `p4-b2d-scuff-1,2,3`. |
| C-044 | 2026-10-18 16:49 | Read timing program: each loader's real files read byte-at-a-time (`istreambuf_iterator`) and in one block, min of 5 warm reads, bytes compared | scratch, `-O0 -g` like the Debug tree | **Debug** flags | — | — | Program in session scratch. Times the read alone, not decode or upload. |
| C-045 | 2026-10-18 16:50 | B1 spike capture (30 ms), **before** | `538f6aab` (branch `perf/renderer-file-reads` before its changes) | **Debug** | 1280x720 | 30 spikes | `p11f-b1-pre-1`. Ran to 107 s: the opening cutscene was longer than in later runs (55–75 s), so spike totals between B1 runs are not comparable; compare frames. |
| C-046 | 2026-10-18 16:55 | Headless timing script ×3: push the rock catalogue, `far_prefetch_atlases`, then `far_pump_atlas_uploads(1)` every 1 ms, timing each pump | `538f6aab` | **Debug** | 320x200 | — | Script in session scratch. 37 atlases. |
| C-047 | 2026-10-18 16:58 | B1 spike capture (30 ms), **one-block reads only** | `82ad3dca` | **Debug** | 1280x720 | 18 spikes | `p11f-b1-read-1`. |
| C-048 | 2026-10-18 17:01–17:05 | B1 spike capture (30 ms) ×3, atlas prefetch at the catalogue push, **old pump-started queue** | uncommitted intermediate on `82ad3dca` | **Debug** | 1280x720 | 19 / 19 / 19 spikes | `p11f-b1-prefetch-1`…`3`. |
| C-049 | 2026-10-18 17:12–17:17 | B1 spike capture (30 ms) ×3, **self-feeding decode workers**, prefetch at every catalogue push (no rock gate) | uncommitted intermediate (= `ec14d2e3` + an ungated far_tier) | **Debug** | 1280x720 | 22 / 19 / 20 spikes | `p11f-b1-pool-1`…`3`. |
| C-050 | 2026-10-18 17:19 | B2d spike capture (30 ms), **before** | `e5e2e3b7` build (the `perf/death-hitch` worktree) | **Debug** | 1280x720 | 5 spikes | `p11f-b2d-pre-1`. |
| C-051 | 2026-10-18 17:19–17:20 | B2d spike capture (30 ms) ×2, as C-049 (no rock gate) | as C-049 | **Debug** | 1280x720 | 7 / 6 spikes | `p11f-b2d-pool-1,2`. |
| C-052 | 2026-10-18 17:22–17:26 | B1 spike capture (30 ms) ×3, **prefetch gated on rock content** | `b829ce0c` | **Debug** | 1280x720 | 18 / 19 / 18 spikes | `p11f-b1-gate-1`…`3`. |
| C-053 | 2026-10-18 17:27–17:28 | B2d spike capture (30 ms) ×2, as C-052 | `b829ce0c` | **Debug** | 1280x720 | 5 / 5 spikes | `p11f-b2d-gate-1,2`. |
| C-054 | 2026-10-18 19:25 | **B1 retest on main `7b836585`** (after P-4, P-11), headless, exterior | `7b836585` | **Debug** | framebuffer 1280x720 | 40 reports | Same configuration as C-012. |
| C-055 | 2026-10-18 19:27 | **B2 retest on main `7b836585`**, headless, exterior | `7b836585` | **Debug** | framebuffer 1280x720 | 15,126 frames / 127 reports | The Sovereign started exploding at report 114 (about 140 s), destroyed at report 122. |
| C-056 | 2026-10-18 19:57 | **B1 spike capture (30 ms) on main `7b836585`**, headless | `7b836585` | **Debug** | framebuffer 1280x720 | 22 spikes | Spike log `rt-b1-spikes.log`, stdout `rt-b1-spikes.out`. |
| C-057 | 2026-10-18 19:59 | **B2d spike capture (30 ms) on main `7b836585`**, headless | `7b836585` | **Debug** | framebuffer 1280x720 | 3 spikes | Spike log `rt-b2d-spikes.log`, stdout `rt-b2d-spikes.out`. |
| C-058 | 2026-10-18 20:10 | **B1, P-1 before**, headless, CPU-only | `53f38422` (main) | **Debug** | framebuffer 1280x720 | 41 reports | `vg-b1-720-base`. Worktree `perf/vesuvi-gpu`. |
| C-059 | 2026-10-18 20:13 | as C-058 | `53f38422` | **Debug** | framebuffer **2560x1080** | 39 reports | `vg-b1-1080-base`. |
| C-060 | 2026-10-18 20:16 | B1, **GPU-timed** (`DAUNTLESS_PROFILE_GPU=1`) | `a9d824ab` (tooling only; no render change) | **Debug** | 2560x1080 | — | `vg-b1-1080-gpu`. Attribution only (M-6). |
| C-061 | 2026-10-18 20:18 | B1, **GPU focus** on 16 nested `space` scopes (`DAUNTLESS_PROFILE_GPU_FOCUS`) | `a9d824ab` | **Debug** | 2560x1080 | — | `vg-b1-1080-focus`. First capture with nested GPU times (M-1). |
| C-062 | 2026-10-18 20:21 | B1 CPU-only, **`DAUNTLESS_DEV_RENDER_OFF=rock_puffs`** | `a9d824ab` | **Debug** | 1280x720 | — | `vg-b1-1280x720-off-rock_puffs`. |
| C-063 | 2026-10-18 20:23 | as C-062 | `a9d824ab` | **Debug** | 2560x1080 | — | `vg-b1-2560x1080-off-rock_puffs`. |
| C-064 | 2026-10-18 20:25 | B1 CPU-only, **`DAUNTLESS_DEV_RENDER_OFF=volumetric_nebulae`** | `a9d824ab` | **Debug** | 1280x720 | — | `vg-b1-1280x720-off-volumetric_nebulae`. |
| C-065 | 2026-10-18 20:27 | as C-064 | `a9d824ab` | **Debug** | 2560x1080 | — | `vg-b1-2560x1080-off-volumetric_nebulae`. |
| C-066 | 2026-10-18 20:30 | B1, GPU focus on 6 scopes | `a9d824ab` | **Debug** | 1280x720 | — | `vg-b1-720-focus`. |
| C-067 | 2026-10-18 20:32 | B1, GPU focus on 6 scopes, **`DAUNTLESS_DEV_RENDER_OFF=msaa`**, quit 10 s after the destroy | `a9d824ab` | **Debug** | 2560x1080 | — | `vg-b1-1080-focus-nomsaa`. |
| C-068 | 2026-10-18 20:34–20:42 | Puff GL harness (`RockPuffGLTest`, 1920x1080 RGBA16F, no MSAA, Beol 4 tile field, 400 puffs): shader variants timed with `glFinish` around 20 draws, best of 3, plus pixel diffs | scratch test, never committed | **Debug** | 1920x1080 | — | Variants: production, noise off, lighting off, both off, 2 octaves, lighting per puff, hash table. |
| C-069 | 2026-10-18 20:43 | **B1, P-1 after**, headless, CPU-only | `0457bc3f` | **Debug** | 1280x720 | — | `vg-b1-720-after`. |
| C-070 | 2026-10-18 20:45 | as C-069 | `0457bc3f` | **Debug** | 2560x1080 | — | `vg-b1-1080-after`. |
| C-071 | 2026-10-18 20:47 | B1, GPU focus on 6 scopes, after | `0457bc3f` | **Debug** | 2560x1080 | — | `vg-b1-1080-after-focus`. |
| C-072 | 2026-10-18 21:27 | **B1 at 4K, P-1 before**, headless, CPU-only | `53f38422` (main checkout build) | **Debug** | framebuffer **3840x2160** | 23 reports | `vg-b1-4k-before`. |
| C-073 | 2026-10-18 21:29 | as C-072, **after** | `0457bc3f` | **Debug** | 3840x2160 | 25 reports | `vg-b1-4k-after`. |
| C-074 | 2026-10-18 21:31 | B1 at 4K, GPU focus on **6** scopes, after | `0457bc3f` | **Debug** | 3840x2160 | — | `vg-b1-4k-after-focus`. Totals not real: SIG-074. |
| C-075 | 2026-10-18 21:33 | B1 at 4K, GPU focus on **20** scopes (every nested `space` scope but the `rock.near.*` children), after | `0457bc3f` | **Debug** | 3840x2160 | — | `vg-b1-4k-after-focus20`. |
| C-076 | 2026-10-18 21:20 | Mark, by hand: E1M2 played in the Vesuvi belt (shooting rocks), **visible window**, CPU-only, after | `0457bc3f` | **Debug** | started 1280x720, then maximised on the laptop screen (drawn size not recorded) | 164 reports | `vg-4k-after`. No phase markers, scene changed throughout (24 → 56 objects, rock fragments 0 → 2,600): not comparable to B1. |
| C-077 | 2026-10-18 21:40 | B1 at 4K, CPU-only, **200 belt puffs** (`puff_belt_count` 2000 → 200 by a temporary edit of `far_dials.py` DEFAULTS, restored by copy) | `97239f45` + that edit | **Debug** | 3840x2160 | 27 reports | `vg-b1-4k-puffs200`. |
| C-078 | 2026-10-18 21:42 | as C-077, GPU focus on 20 scopes | same | **Debug** | 3840x2160 | — | `vg-b1-4k-puffs200-focus20`. |
| C-079 | 2026-10-18 21:52–22:05 | **Screenshots** (`DAUNTLESS_DEV_SCREENSHOT`, 5 s after the cutscene, before the destroy): before (fix reverted on a throwaway branch), after ×2, after with 200 belt puffs; pixel diffs, scene band = rows 300–850, columns 300–2200 (no HUD) | `c3c925cf` (after); `c3c925cf` with `0457bc3f` reverted (before) | **Debug** | 2560x1080 | — | `~/Documents/dauntless-perf/shots/`. |
| C-080 | 2026-10-19 15:09 | **First B3** (Vesuvi Dust Cloud, parked), headless, CPU-only | `e9960352` (`perf/b3-dust-cloud`) | **Debug** | framebuffer 1280x720 | 40 reports (39 after `settled`) | `b3-20261019-1509.log`. Another session's pytest held 1 core (load average 7.5 at the start). Scene line constant: 17 ships (all loaded Vesuvi sets), 1 hull-damaged, 200 puffs, 0 large rocks. |
| C-081 | 2026-10-19 15:11 | B3, GPU focus on 6 scopes (`space.system_nebula,space.dust,rock.puffs.draw,space.opaque,space.backdrop,space.suns`) | same | **Debug** | 1280x720 | — | `b3-focus-20261019-1511.log`. Attribution only (M-6). |
| C-082 | 2026-10-19 15:13 | B3 CPU-only, **`DAUNTLESS_DEV_RENDER_OFF=volumetric_nebulae`** | same | **Debug** | 1280x720 | 39 reports after `settled` | `b3-off-volumetric_nebulae-20261019-1513.log`. |
| C-083 | 2026-10-19 15:14 | B3, GPU focus on the same 6 scopes, **volumetric nebulae off** | same | **Debug** | 1280x720 | — | `b3-focus-off-volumetric_nebulae-20261019-1514.log`. Same focus set as C-081, so the totals compare (SIG-074). |
| C-084 | 2026-10-19 21:46–21:56 | B3, GPU focus (C-081's 6 scopes), **throwaway shader probe** (`DAUNTLESS_NEBULA_PROBE` bitmask, one run each): 0 none, 1 haze lanes fbm → 1, 2 clump fbm → 0.5, 4 no clumps, 8 half the haze steps, 16 stop below 1% transmittance, 32 sky lanes → 1, 35 = 1+2+32 | `364151245` + probe, never committed (restored by copy) | **Debug** | 1280x720 | about 30 reports each after `settled` | `b3-probe-<n>-*.log`. Attribution only (M-6). |
| C-085 | 2026-10-19 21:59–22:09 | as C-084, probes 0, 1, 35, 8 **interleaved twice** | same | **Debug** | 1280x720 | — | `b3-probe2-<n>-*.log`. |
| C-086 | 2026-10-19 22:11–22:18 | B3 **CPU-only at 4K**, probes 0, 35, 1, 8, volumetric nebulae off, 0 again | same | **Debug** | framebuffer **3840x2160** | 18–31 reports each after `settled` | `b3-4k-probe-<n>-*.log`. GPU-bound, so frame time is GPU time. |

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
an upper bound. The CPU-only re-captures (M-6) are SIG-022 for B1 and SIG-026 for B2, at
1280x720 rather than these captures' maximised Retina window, so they are not directly comparable.

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
| SIG-083 | C-086 | **B3 at 4K: the nebula is at least 13.4 ms of a 30 ms GPU-bound frame, and its noise is about 90% of that.** Frame medians after `settled`: baseline 30.0 and 29.9 ms (two runs, `present` 16.7–16.9 ms of GPU wait); nebula off 16.6 ms (the headless 60 Hz floor, SIG-070; `present` 0.7), so the nebula costs **at least** 13.4 ms. All noise off 17.7 ms (−12.4); haze lanes fbm off 19.8 (−10.2); half the haze steps 23.2 (−6.8). | Measured; the 90% is derived (12.4 / 13.4, a lower-bound denominator) | P-1 |
| SIG-082 | C-084, C-085 vs C-086 | **Counter-signal: at 1280x720 the GPU-focus span cannot rank nebula changes.** The probe-0 baseline's nebula median is 4.27, 5.52 and 3.04 ms in three runs of one build. Half the haze steps reads 4.20 / 4.43 / 4.16 ms there (no saving), while at 4K the same change saves 6.8 ms of frame (SIG-083). Only the large effect is stable at 720p: all noise off 2.11 / 2.26 / 1.98 ms. For nebula A/B, use 4K frame time. | Measured | M-1, P-1 |
| SIG-081 | C-081 | **C-081's 11.5 ms nebula is a GPU-wide slowdown, not the scene.** Its nebula span is 3.8–4.6 ms for 7 reports, then a flat 11.4–11.7 ms; at the same report every GPU span rises together (`space.opaque` 0.067 → 0.292, `bloom` 0.084 → 0.455, `post` 0.072 → 0.283). The same run logged the hull-volume prebake at 45.5 s, against 0.8 s in C-030. Cause not known: another GPU client (another session's tests were running) or a GPU clock change. **Supersedes SIG-079's 11.5 ms and SIG-080's 7×.** C-080's CPU-only frame times (SIG-078) are unaffected. | Measured / inferred (the cause) | P-1, M-6 |
| SIG-080 | C-081; B1 from SIG-073 | **Superseded by SIG-081: C-081 was slowed GPU-wide.** **The dust cloud's nebula costs about 7× Haven's per pixel.** B1 at Haven: 4.96 ms at 2560x1080, which is about 1.65 ms at 1280x720 if it scales with pixels as SIG-073 found. B3: 11.5 ms at 1280x720. If the pixel scaling holds here too, B3 at 2560x1080 would be about 35 ms of nebula and at 4K about 100 ms; not captured. | Derived (pixel scaling assumed, not measured for B3) | P-1 |
| SIG-079 | C-081, C-083 | **Superseded by SIG-081 (the 11.5 ms; the A/B direction stands, see SIG-083).** **B3: the system nebula is 11.5 of 13.7 ms GPU at 1280x720, confirmed by A/B.** With volumetric nebulae off the GPU frame is 13.68 → 1.14 ms and `space` 12.39 → 0.54 ms (same focus set). Counter-signals: `space.dust` 0.000 ms GPU, `rock.puffs.draw` 0.17 ms, `space.opaque` 0.24 ms, `space.backdrop` 0.23 ms; bloom + resolve + post 0.96 ms. | Measured | P-1 |
| SIG-078 | C-080, C-082 | **B3 at 1280x720 is CPU-bound, so the nebula does not show in its frame time.** After `settled`: median 12.86 ms (12.36–15.97, 39 reports; about 78 fps), render CPU 7.9 ms, `cef.composite` 0.53 ms (no GPU wait), `present` 0.24 ms. Volumetric nebulae off: median 12.71 ms (11.68–16.77), the same within noise. Of the CPU frame: `r.frame` 8.1 (`anim` 1.6, `space` CPU 1.1, `cef.composite` 0.5), `sim` 2.3 (`sim.collisions` 0.7), `ui_panels` 1.2, `scene_push` 1.0. To see the nebula in frame time, B3 needs a larger framebuffer (SIG-080). | Measured | P-1 |
| SIG-077 | C-079 | **The puff fix does not change the picture in game; 200 puffs does.** Before vs after differs exactly as much as two runs of the same build (scene band: mean 1.28 vs 1.27 levels, 11.2% vs 11.0% of pixels off by more than 2, max 33 vs 34; the run-to-run part is film grain, slow rock motion and a subtitle). 200 belt puffs: 18.0% of pixels off by more than 2, mean 1.62, and at brightness ×3 a lavender haze bank right of the ship is gone. | Measured | P-1 |
| SIG-076 | C-077, C-078 vs C-073, C-075 | **200 belt puffs instead of 2000 at 4K: 46.4 → 36.3 ms per frame** (21.6 → 27.6 fps), still GPU-bound (`present` waits 21 ms). The puff span 14.8 → 3.3 ms (4.5×, not 10×); the GPU frame 48.1 → 36.4 ms with the nebula (14.7 ms) now the largest item. | Measured | P-1 |
| SIG-075 | C-076 | **Mark's visible session after the fix, playing in the belt:** the outside view runs 25–32 ms a frame, mostly CPU-bound (`cef.composite` 0.7–1.5 ms, `present` under 1 ms in most reports), with two stretches of about 20 reports where `present` holds 5–10 ms (GPU-bound). A typical CPU frame of about 29 ms: `r.frame` 16.2 (minor rocks step 2.6, `anim` 2.8, `space` CPU 3.6, CEF pump + upload 2.4), `sim` 6.4 (`sim.collisions` 2.2), `ui_panels` 2.9, `scene_push` 2.2. Drawn size unknown. | Measured (weak: uncontrolled scene, unknown size) | P-1 |
| SIG-074 | C-074 vs C-075, C-073 | **Counter-signal: a GPU-focus run's pass TOTALS depend on the focus set; the focused spans do not.** In the same 4K scene, 6 focus scopes report a 69.7 ms GPU frame and 66.0 ms `space`; 20 scopes report 48.1 and 44.4. The CPU-only frame is 46.4 ms and GPU-bound (C-073), so the 6-scope totals cannot be real. The focused spans agree between the two runs within 0.1 ms (puffs 14.92 / 14.83, nebula 14.68 / 14.71, near rocks 4.39 / 4.34, backdrop 2.26 / 2.23). Mechanism not known. **This supersedes SIG-071's "GPU idle" reading** of C-071's `space` total: C-071 also used 6 scopes, so its 20.5 ms is the same artefact. Compare totals only between runs with the same focus set. | Measured / inferred (that C-071 is the same artefact) | M-1, P-1 |
| SIG-073 | C-075 | **P-1 at 4K after the fix:** GPU frame 48.1 ms, `space` 44.4: puffs 14.8, system nebula 14.7, `rock.near.draw` 4.3, backdrop 2.2, about 8 ms outside every focused scope (the MSAA resolve of a 3840x2160 4× RGBA16F target is the largest unscoped step; not timed alone); `bloom` + `resolve` + `post` 3.0. The nebula scales with pixels from 2560x1080 (4.96 → 14.7, 3.0× for 3.0× the pixels). | Measured / inferred (what the remainder is) | P-1 |
| SIG-072 | C-072, C-073 | **P-1 at 4K, before → after: 58.8 → 46.4 ms per frame** after the destroy (17 → 21.6 fps; 58.5 → 46.4 before it), still GPU-bound: the CPU waits 30.0 → 29.4 ms, now in `present` rather than `cef.composite`. No 60 Hz floor at this size. The 12.4 ms saving matches the puff span's 44% cut (SIG-071) applied to the about 26 ms the puffs would cost at 4K by SIG-067's pixel scaling. | Measured / derived (the 26 ms) | P-1 |
| SIG-071 | C-069, C-070 vs C-058, C-059; C-071 vs C-061 | **P-1 after the puff fix (`0457bc3f`):** the B1 exterior after the destroy runs at 16.6 ms at both sizes (1280x720: 19.8 → 16.6; 2560x1080: 20.6 → 16.6), with the `cef.composite` GPU wait gone at 1280x720 (6.6 → 0.46 ms, the same as during the cutscene) and mostly gone at 2560x1080 (8.4 → 1.4 ms; 4.0 ms before the destroy). Both sizes now sit on the SIG-070 floor, so the real gain is larger than the frame times show. The puff span's GPU time at 2560x1080 is 9.47 → 5.29 ms. **Not comparable:** C-071's `space` total (20.5 ms against 17.9) — once the GPU is not the bottleneck, a GPU-timed span also counts the GPU waiting for the CPU (inferred), so only the focused spans compare across the fix. | Measured / inferred (the idle reading) | P-1, M-1 |
| SIG-070 | C-062–C-065, C-069, C-070 | **Headless E1M2 cannot run faster than 60 Hz.** Whenever the GPU stops being the limit, the frame pins at 16.63–16.64 ms in every report, and `cef.pump` (`CefDoMessageLoopWork`) grows from 0.2–0.6 ms to 2–5 ms to fill the gap: it blocks until the 60 Hz mark. Not seen in B2 at the same size (C-055, 8–13 ms frames, `cef.pump` 0.2–0.7 ms) nor this morning's headless B1 (C-012 after the destroy: 15.5 ms, `cef.pump` 0.58 ms). Cause not known. | Measured | M-7, P-1 |
| SIG-069 | C-068 | **What the puff fragment shader spends its time on** (harness, ms per draw at 2000 / 1100 / 700 GU): production 2.30 / 3.70 / 2.86; noise replaced by its mean 0.79 / 1.26 / 0.98; lighting removed 1.79 / 2.87 / 2.21; both 0.30 / 0.48 / 0.37. So about **65% is the 16 sine hashes** of the value noise and about **22% the Lambert phase**, which is the same for every fragment of a puff. The Lambert phase computed per puff in the vertex shader is **bit-identical** (0 pixels differ). The hashes read from a table baked on the GPU with the same expression match the inline hash at every lattice point; the picture moves by at most 0.06/255 (half-float rounding, a few hundred of 2 million pixels). Together: 1.09 / 1.74 / 1.35 ms (2.1×). | Measured | P-1 |
| SIG-068 | C-067 vs C-061 | **Counter-signal: MSAA is not the puff cost.** With MSAA off the puff span is 7.8 ms (9.5 with 4× MSAA), the nebula unchanged (4.9), and the `space` total *rises* to 23.1 ms (17.9). Turning MSAA off is no fix. Where the extra time lands is not attributed. | Measured | P-1 |
| SIG-067 | C-066 vs C-061 | **The puffs scale with pixels, the nebula less.** At 1280x720: GPU frame 10.1 ms, `space` 9.7, puffs 3.12, nebula 2.30, backdrop 0.21. At 2560x1080 (3.0× the pixels): puffs 9.47 (3.0×), nebula 4.96 (2.2×). The puffs are fill-bound. ⚠️ At 1280x720 the GPU-timed frame (10.1 ms) is shorter than the CPU-only frame (19 ms) that still waits 6–7 ms in `cef.composite`: some GPU work outside the timed passes is not covered (inferred; headless hidden-window present is a candidate, compare SIG-023's visible 12.3 ms). | Measured / inferred | P-1, M-1 |
| SIG-066 | C-062–C-065 vs C-058, C-059 | **A/B: each of the puffs and the system nebula alone holds the GPU wait.** With `rock_puffs` off, `cef.composite` falls from 6.6 to 0.47 ms (1280x720) and from 8.4 to 1.3 ms (2560x1080); with `volumetric_nebulae` off, to 0.47 and 1.3 ms. Every A/B frame is 16.64 ms (SIG-070), so how far each one alone would take the frame is not measurable here. | Measured | P-1 |
| SIG-065 | C-061 | **P-1 attributed: inside `space` (17.9 ms GPU at 2560x1080), `rock.puffs.draw` is 9.47 ms and `space.system_nebula` 4.96 ms**; then `space.backdrop` 0.71, `rock.near.draw` 0.66, `space.opaque` 0.07, and every other focused scope ≤ 0.001 (suns, minors, specks, rock specks, shield, atmosphere, dust, rock fade, lens flare, weapons, particles). About 1.1 ms of `space` is outside every focused scope (the MSAA resolve and the unscoped builds). **Counter-signal:** splitting the query 16 ways moves the `space` total by 0.2 ms (17.94 vs 17.78 in C-060). ⚠️ On a tile-based GPU, an elapsed span may also hold deferred work from earlier draws flushed inside it; the A/B (SIG-066) is what confirms the two large rows. | Measured | P-1, M-1 |
| SIG-064 | C-060 | **The Vesuvi exterior's GPU frame at 2560x1080 is 19.1 ms, 17.8 of it `space`** (93%); `bloom` 0.31, `resolve` 0.28, `post` 0.29, `cef.composite` 0.41, `shadow` 0.000. | Measured | P-1 |
| SIG-063 | C-059 vs C-058 | **Counter-signal: the exterior frame barely grows with the window.** 2560x1080 (3.0× the pixels of 1280x720) runs 20.6 ms after the destroy against 19.8 ms, with `cef.composite` waiting 8.4 ms against 6.6. | Measured | P-1 |
| SIG-062 | C-058, C-059 | **P-1 before, B1 on main `53f38422`:** cutscene 21.0 ms (1280x720) / 21.5 ms (2560x1080); exterior before the destroy 19.1 / 21.1 ms; after the destroy 19.8 / 20.6 ms, with `cef.composite` 6.6 / 8.4 ms of CPU waiting on the GPU. Reproduces SIG-058. | Measured | P-1 |
| SIG-061 | C-057 | **B2d after P-4/P-11: the Sovereign's death is one 39.8 ms frame** (11.4 s in) and the only spike after loading: `cb.damage_sys` 21.6 ms = `vd.carve` 15.0 + `hb.split_detached` 6.3, plus `space.opaque` 5.9 ms (the field upload), `cb.death` 1.0 ms. Matches the residual SIG-045 left (one carve + the first BFS). Load frames: frame 1 1,286 ms, frame 2 169 ms (15 catch-up ticks). | Measured | P-4 |
| SIG-060 | C-056 | **B1 after P-4/P-11: no frame reaches 30 ms after the Facility destroy.** All 11 spikes after loading (31–56 ms, every 2–7 s) come before it, during the opening cutscene: either `gl.timers.real` 13–34 ms (the real-time timer callbacks the cutscene scripts run on) or `render_prep` 16–31 ms. This is the first attribution of the cutscene's extra sim time (M-2, SIG-022). The load frame is 8.94 s (frame 1; SIG-054: 8.5–8.75 s), then 30–49 ms catch-up frames 2–8. | Measured | P-4, M-2 |
| SIG-059 | C-055 vs C-015 | **B2 after P-4/P-11:** the fight runs at 8.2–12.9 ms per frame (about 80–120 fps), against about 9.5–10.5 ms in C-015: unchanged within run-to-run noise. **The Sovereign's death no longer shows in the periodic report:** `cb.damage_sys` peaks at 0.4 ms in the death report (C-015: 7.6 ms, a frame of at least about 50 ms); loop 12.7–14.3 ms around the death. A spike capture was not taken, so a single death frame of up to about 35 ms (SIG-045) is not ruled out. | Measured | P-4 |
| SIG-058 | C-054 vs C-012 | **B1 after P-4/P-11:** opening cutscene about 21 ms (C-012: 20 ms), and `sim` still carries about 6 ms outside every child scope during it (M-2). Exterior at Vesuvi before the destroy about 19–20 ms, unchanged, with `cef.composite` 6–9 ms of CPU waiting on the GPU (**the Vesuvi exterior is GPU-bound even at 1280x720**). After the destroy the frame now **stays** about 19.5 ms (C-012: dropped to 12.5 ms): the wreck stays drawn now, where before the fix the saturated wreck carves removed the station (SIG-030). The death no longer shows in the periodic report (`cb.damage_sys` 0.5 ms in the destroy report; C-012: 7.6 ms). | Measured / inferred (why the frame no longer drops) | P-1, P-4, M-2 |
| SIG-057 | C-053 vs C-050 | **Counter-signal: gated on rock content, a mission with no rocks is unchanged.** B2d draws no rock and now loads no atlas: 5 spikes in each run, at the same frames as before (frames 1, 2, about 120 and about 600; C-050: 1, 2, 158, 640), with no `scene.far_tier` time after the load frame. Frame 1's `space.breach` is 1.5–1.6 ms (2.8 ms before): the four `Damage1-4.tga` frames load there (SIG-055), now read in one block. | Measured | P-11 |
| SIG-056 | C-051 vs C-050 | **Counter-signal: prefetching at every catalogue push costs a rock-less mission.** With no rock gate, B2d (no rock drawn, so no atlas load before) uploaded atlases in its first frames: `scene.far_tier` 7.4–7.7 ms in frames 2–3, and frame 3 became a new 32 ms spike (11–12 catch-up sim ticks). Hence the gate in `b829ce0c`. | Measured | P-11 |
| SIG-055 | code reading; C-050 / C-053 frame 1 | **When each byte-wise loader ran:** in the first frame (load time): `frame.cc` `Damage.tga` (every hull draw calls it) and `breach_pass` `Damage1-4.tga` (every breach render calls it; frame 1 `space.breach` 2.8 → 1.5–1.6 ms with the read fix). At mission load: `bridge_pass` viewscreen off texture (`ViewscreenLoading.tga`, pushed from `MissionLib.ShowLoadingText`). On first use during play: `target_reticle_pass` (first target shown), `viewscreen_static_pass` (first SDK static), and `far_pass` atlases (each catalogue rock's first draw). Developer-only (Ship Property Viewer): `subsystem_pin_pass` glyphs, `decal_override` masks. | Derived (code) / measured (frame 1) | P-11 |
| SIG-054 | C-049, C-052 | **With self-feeding decode workers, B1's load frame pays 53–57 ms of atlas work instead of about 1 s:** `rock.atlas.load` 52.7–56.6 ms, 8 calls, all six runs, about 7 ms each, so upload only. The load frame drops from 10.0 s (C-045) to 8.5–8.75 s. The remaining 29 atlases upload one a frame from `far_tier`: every logged frame from 2 to 7 carries `scene.far_tier` 6.7–7.6 ms. Those frames were already slow catch-up frames (frame 2 72.9 ms in C-045, now 56–61 ms); frame 4 now reaches 30.8–32.4 ms. No atlas loads after that. | Measured | P-11 |
| SIG-053 | C-048 | **Counter-signal: a prefetch whose queue only a pump could advance did not help the load frame.** `rock.atlas.load` stayed at 880–958 ms over 8 calls. The 7 s nebula wait blocks the main thread, so only the first 4 atlases in index order decoded (the cap), not the 8 silicate rocks drawn at Vesuvi; those still loaded in the frame. | Measured / inferred (which 4) | P-11 |
| SIG-052 | C-047 | **The one-block read alone barely moves the atlases:** B1 load frame `rock.atlas.load` 1,054 → 962 ms, 8 calls (about 120 ms a rock left). | Measured | P-11 |
| SIG-051 | C-046 | **What an atlas load is made of.** 37 rocks (74 PNGs, 512² RGBA) decode + dilate on the 4 workers in 1,375–1,385 ms wall, about 150 ms of CPU a rock with the byte-wise read. Upload (two `glTexImage2D` + `glGenerateMipmap`, GL only) 7.6 ms median a rock (6.8–7.9), every pump without an upload under 0.03 ms. Derived split of a 132 ms lazy load (C-045): read about 19 ms (C-044), decode + dilate about 105 ms, upload about 7.6 ms. | Measured / derived (split) | P-11 |
| SIG-050 | C-045 | **The impostor atlases are the only loader that costs real time.** B1's load frame (frame 1, 10.0 s, 7.2 s of it `env.system_nebula`) holds `rock.atlas.load` 1,054 ms over 8 calls, under `viewscreen.rtt` → `rock.impostor.draw`: the 8 catalogue rocks drawn at Vesuvi, each loaded on its first draw. No later frame of the run loads one. Matches the lead (1,083 ms). | Measured | P-11 |
| SIG-049 | C-044 | **Counter-signal: every loader except the atlases reads under 100 KB.** Byte-wise reads cost about 36 ms per MB in Debug, one-block reads about a tenth. `target.tga` 1 KB 0.06 → 0.02 ms, `TargetArrow.tga` 8 KB 0.33 → 0.04 ms, each `Damage1-4.tga` 12 KB 0.48 → 0.06 ms, `Damage.tga` 64 KB 2.4 → 0.26 ms, each `Noise1-3.tga` 16 KB 0.62 → 0.07 ms, `ViewscreenLoading.tga` 98 KB 3.7 → 0.38 ms, each subsystem glyph 1 KB 0.05 → 0.02 ms, decal masks up to 42 KB 1.5 → 0.16 ms. The atlases: 74 files, 19.3 MB, 699 → 71 ms if all were read. Same bytes both ways. | Measured | P-11 |
| SIG-048 | C-044 | **The scuff normal map's read alone was 446 ms byte-wise against 45 ms in one block** (12.6 MB, warm cache), consistent with SIG-046's ~350 samples. | Measured | P-11 |
| SIG-047 | C-042, C-043 | **The scuff normal map now loads at boot in about 158 ms** (one-block read + decode + normal Z + mipmapped upload); a second call costs 0.004 ms, so no scuff can pay it again. By C-040's stack sample the old first-scuff load was about 440 ms. B2d ×3 at a 100 ms threshold: no spike after the two boot frames (three clean runs are weak on their own: the old spike showed in about a third of runs). | Measured | P-11 |
| SIG-046 | C-039, C-040 | **P-11 found: the lone ~575 ms `space.opaque` spike is the first collision-scuff draw loading `scuff_normal.tga`** (12.6 MB) in `renderer::ensure_scuff_normal_texture`: about 350 of the spike's samples are `read_file` copying the file one byte at a time through `istreambuf_iterator` (Debug), about 90 more decode it, rebuild normal Z and upload with mipmaps. It fires on the session's first scuff -- here the wreck about 11 s after the B2d destroy (22.1 s in C-039, 21.9 s in C-040 and C-027), in the no-death B2 runs near severance. | Measured | P-11 |
| SIG-045 | C-039, C-041 | **With a 3 ms per-frame carve budget, a ship's worst death frame is 33–37 ms** (one carve of 7–12 ms + the first `hb.split_detached` 4–5 ms), down from 45–50 ms with 4–6 carves in one frame (SIG-044); the carving spreads over 15–27 frames instead of 7–15 with a similar total. B1 is unchanged: its death frame is 23.4 ms (`cb.damage_sys` 6.3 ms). | Measured | P-4 |
| SIG-044 | C-038 | **With Effects imported at boot, `cb.death` in the death frame is 1.3–2.2 ms** (was 16.6–16.8). The death frames are now 45–50 ms, almost all SDK cascade carves: `vd.carve` 17–34 ms for 2–6 carves in one frame (about 5.7 ms each; `AddDamage` world carves plus their capsule cuts) and the first `hb.split_detached` 5–6 ms. | Measured | P-4 |
| SIG-043 | C-037 | **`cb.death`'s 16.8 ms was the first `import Effects`.** All of it is `death.cascade` → `casc.explosion` on the first blast only (15.8 ms; later blasts under 0.5 ms). cProfile of that call: the SDK loader parsing, transforming and compiling `Effects.py` (`sdk_code_cache` is per-process). Only five SDK missions import Effects themselves (E1M2 among them, so B1 never showed it); otherwise the engine's first import is `death_cascade` or `hull_hit_smoke`, so the first hull hit in such a mission is a candidate for the same cost (not measured). | Measured | P-4 |
| SIG-042 | C-036 | **With the breach carving the field once, a ship's death has no breach cost left:** `dmg.core_carve` after the death drops from 314–353 ms over 81–85 frames to 0–4 ms in 0–1 frames, and `cb.damage_sys` in total from 380–447 ms to about 80 ms. What is left is the death frame: `cb.death` 16.4 ms, two SDK wreck carves 19.7 ms (`vd.carve`), first `hb.split_detached` 4.4 ms (frame 63.6 ms in this capture). | Measured | P-4 |
| SIG-041 | C-034, C-035 | **A ship's warp-core breach re-carves the field every frame for 1.5 s.** Its hole eases from 0.1 GU to 0.25 × ship radius (1 GU, 100 model units, for a Sovereign) and `core_breach_carve` deposits each frame. Two cases, decided by where the SDK's random death carves land: (a) one lands by the core, the breach merges into its 100-unit slot without growing it, and re-carves it 92 times at 5.7 ms each, changing no cell (C-034); (b) none does, the breach owns a slot that grows every frame, and each of about 85 carves really changes cells, about 4 ms each, about 0.33 s in total (C-035, all four runs). Frames are about 16 ms, under any spike threshold used before, so earlier captures could not show it. **Counter-signal:** the unchanged-slot skip (`83c55042`) removes (a) only; (b) was unchanged by it. | Measured | P-4 |
| SIG-040 | C-033 | **With the trace BVH built at spawn, the Facility's death frame is 21–24 ms** (`cb.damage_sys` 4.4–7.2 ms: `vd.carve` 3.5–6.1, `hb.split_detached` 0.9; `vd.resolve` under 0.5 ms), and no frame after the death reaches 30 ms, in all three runs. About 16 ms of the frame is the ordinary Vesuvi exterior frame in Debug, not the death. | Measured | P-4 |
| SIG-039 | C-030, C-032 | **What the 31–34 ms death frame was:** about 16 ms ordinary frame (`r.frame` 11.5 ms + UI, scene push, other sim) + `dmg.visible` 14–15 ms = `vd.resolve` **7.7 ms, one call** + `vd.carve` 5–7 ms (two carves on the 90k lattice) + `hb.split_detached` 1 ms. `vd.resolve` is the death carve's surface-normal ray trace, the first trace against the station, which built its BVH lazily (`ensure_trace_accel`); later carves' `vd.resolve` stays under 0.5 ms. The build-vs-trace split is inferred from that, not timed separately. | Measured / inferred (split) | P-4 |
| SIG-038 | C-031 | **Counter-signal:** the lattice rule leaves a ship's death alone, as designed (modifier 1). The Sovereign's carve frames are `cb.damage_sys` 15–26 ms (`vd.carve` 7–21 ms, `hb.split_detached` 3–6 ms), against 15–27 ms in C-021 and 17–24 ms in C-027. | Measured | P-4 |
| SIG-037 | C-030 | **With the station lattice sized by its hole modifier (90k cells), the Facility death costs one 31–34 ms frame** (`cb.damage_sys` 14 ms: `vd.carve` 5 ms, `hb.split_detached` 1 ms) and **no other frame after the death reaches 30 ms**, in all three runs. Every other spike in these runs is before the destroy and matches C-016–C-018 at the same times (cutscene and load). The BFS running at all shows the instance has a field, so carving is not silently off. | Measured | P-4 |
| SIG-036 | baked cache headers | **Lattice size by hull** (cells, authored cell): ships 50k–800k (Sovereign 204k, Galaxy 512k, CardHybrid 790k), large ships 2.5–3.7M (Warbird, Sunbuster, KessokHeavy, Defiant-class mods), FedOutpost / SpaceFacility 13.4M, CommArray 10.8M, mod KessokMissile 13.4M, 8×-scaled catalogue rocks 4.0–5.8M, four stations at the old 16.7M ceiling. Only stations and the CommArray have `DamageRadMod` ≠ 1 (5–15). Whole-lattice passes scale with this count, so the station costs about 65× a Sovereign. | Measured | P-4 |
| SIG-035 | C-019, C-020 | B2 produced **no kill** in two runs out of two: both quit at the 180 s cap ("time cap, nobody died"). C-015 killed at about 160 s. B2 is not a reliable death scenario; B2d is. | Measured | P-4 |
| SIG-034 | C-019, C-020, C-027 | **Lone `space.opaque` spikes of 573–578 ms**, with nothing else slow in the frame: at 39.6 s (C-019) and 19.3 s (C-020) of B2 with no death, near `[severance]` lines, and 11 s after the B2d death in C-027. Absent from C-028. Not tied to the death path. Cause unknown. | Measured | P-11 |
| SIG-033 | C-021, C-027 | **Counter-signal:** a normal ship's death is not the station's problem. The Sovereign's death costs `cb.damage_sys` 15–27 ms per carve frame before the fix and 17–24 ms after: `vd.carve` 10–17 ms and `hb.split_detached` 3–6 ms. Its carves are ordinary size, so the brush still evaluates every cell in each reach box. | Measured | P-4 |
| SIG-032 | C-026 | **After the fix (B1 ×3):** no frame of 1 s or more (before: 4–15 per run). Worst frame 0.45 s: the first carve frame = `vd.carve` 62–117 ms + the first full `hb.split_detached` BFS 133 ms + the first full field upload in `space.opaque` 165–210 ms. One more frame of up to 0.40 s in two runs (a drain BFS of 175–240 ms + a full re-upload of 207–370 ms). Each later wreck carve: `vd.carve` 28–63 ms, with no BFS and no upload. | Measured | P-4 |
| SIG-031 | C-016–C-018, C-024 | **Why B1 varies.** SDK `Effects.ObjectExploding` gives the wreck a random 5–15 s life with a small explosion every 0–0.45 s. Each explosion has a 30% chance (`GetRandomNumber(10) < 3`) to call `AddDamage(point, radius/4, 600)`. Each such carve froze the game for about 1.7 s while game time barely advanced, so the run saw as many freezes as rolls came up: 15, 6 and 4. | Derived (SDK source + spike counts) | P-4 |
| SIG-030 | C-024 | **The slow carves are 35 GU wreck carves that cover the whole lattice.** Radius 3,501.5 model units = floor `influ` 4.377 GU (the station's radius / 4) × `DamageRadMod` 8 at 100 model units per GU. Reach box = all 153×283×310 = 13.4 M cells of the FedOutpost lattice, 1,450–1,500 ms each. Every other carve is under 13 ms (the core-breach growth carves run 0.1–12 ms). After the first two big carves **every cell is +127**; each later one changes 0 cells. | Measured | P-4 |
| SIG-029 | C-023 | Stack sample during the freezes: 5,087 of 5,125 samples inside `renderer::hull_carve_deposit` are in `voxel::field_carve_oblate`, the per-cell brush. The bake (`make_blank_like`, 38) and the backing gate (`volume_for_source`, 2) barely register. The `space.opaque` share is `InstanceFieldCache::upload`, re-uploading the field. | Measured | P-4 |
| SIG-028 | C-022 | Finer scopes: each freeze is `dmg.visible` → `vd.carve` (native `hull_carve_add`, 2 calls) 1.5–3.1 s, plus `hb.split_detached` about 135 ms, either in the same frame or a frame later from `hull_breakup.drain` (that is the `sim.debris_chunks` frame). `hb.spawn` never appears: no chunk breaks off. `dmg.cascade`, `dmg.core_breach` and `dmg.core_carve` stay under 0.5 ms. | Measured | P-4 |
| SIG-027 | C-016–C-018 | **The Facility death is not one hitch.** Spike capture at 30 ms: after the destroy the game freezes for **1.5–3.3 s, every 2–3 s**, for 11–36 s: 15, 6 and 4 freezes in three identical runs. Each freeze is almost all `cb.damage_sys`, with `space.opaque` 110–180 ms in the same frame, and `sim.debris_chunks` about 135 ms in a frame shortly after. Supersedes the lower bounds of SIG-003 and SIG-024. | Measured | P-4, A-2 |
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
| A-2 | **Heavy one-off work runs inside a single frame, with no budget.** Deaths, battle start and warp arrival each do their work all at once. | Measured (as lower bounds; P-4's station case now measured raw, SIG-027) | SIG-003, SIG-004, SIG-005, SIG-027; `frame-profiler.md` warp-tunnel frames of 100–180 ms | Size each case with a spike capture. Two cases are handled so far, each its own way: P-4's death carves run under a per-frame budget (SIG-045), and P-11's impostor atlases decode on workers from mission load (SIG-054). Then add a common way to spread work across frames or prepare it on a worker, instead of each subsystem doing its own thing. |
| A-3 | **Only some work can move to another thread.** CEF cannot: on macOS its UI thread must be the main thread. The Python sim cannot gain from threads because of the GIL. C++ work that doesn't touch Python can (asset decode, rock streaming, voxel carve), with a short GPU upload step at the end. | Constraint | — | Use this for A-2. Do not reopen the CEF-thread idea (see the CEF threading memory). |
| A-4 | **Sim cost grows with the number of Python calls.** Earlier captures: about 200,000 calls per tick at 100 ships, scaling linearly. `TimeSliceProcess` and sim LOD are barely used. | Measured in earlier captures. **Not visible in B1 or B2** (SIG-014). | SIG-014 (counter) | Add a large-fleet baseline (B3, for example `combat_stress` with 33+ ships) so this issue has signals of its own. |

## Issues — expensive systems

| ID | System | Status | Signals | Next step |
|---|---|---|---|---|
| P-1 | `space` pass at Vesuvi: 17.8 of 19.1 ms GPU at 2560x1080 (SIG-064); 27.6 ms on the Retina 4K screen (SIG-007) | **Attributed; puff cost cut twice** (branch `perf/vesuvi-gpu`, merged to main 2026-10-19 after the full gate; Mark live-checked both changes at Vesuvi). (a) Shader `0457bc3f`, below. (b) **Belt puffs 2000 → 200 by default** (Mark: looks the same at Haven, 2026-10-19): 4K 46.4 → 36.3 ms (SIG-076). The rock puffs were 9.5 ms and the system nebula 5.0 ms of the 17.9 ms `space` GPU time; nothing else over 0.7 ms (SIG-065, confirmed by A/B SIG-066). The puffs were fill- and shader-bound: 65% of their shading was sine hashes, 22% a per-puff-constant Lambert phase (SIG-067–SIG-069). Both now run once (the phase per puff in the vertex shader, the hashes from a GPU-baked table): puff span 9.5 → 5.3 ms, the GPU wait gone at 1280x720 and down to 1.4 ms at 2560x1080 (SIG-071), picture within 0.06/255 of before. **At 4K (3840x2160) the frame is 58.8 → 46.4 ms but still GPU-bound** (SIG-072): puffs and the system nebula are now about 15 ms each of a 48 ms GPU frame (SIG-073). | SIG-007, SIG-062–SIG-083 | (1) Done: Mark live-checked the shader fix and 200 belt puffs at Vesuvi Haven, 2026-10-19 (the ×3-brightened stills show a thinner haze bank, SIG-077; at normal brightness and in play he saw no difference). Only Vesuvi has a belt profile today; tile fields (Beol) use `puff_count`, unchanged at 400. (2) At 4K the system nebula (14.7 ms of a 36 ms GPU frame, scaling with pixels) is now the largest cost: it needs a cheaper fill (fewer fragments, e.g. a lower-resolution march, which changes the picture and needs Mark's eyes) to get 4K under about 33 ms. (3) The unscoped ~8 ms of `space` at 4K (likely the MSAA resolve) needs its own scope. (4) Frame times cannot fall below 16.6 ms in headless E1M2 at 1280x720 and 2560x1080 until M-7 is understood. (5) Inside the Vesuvi Dust Cloud (B3) at 4K the nebula is at least 13.4 ms of a 30 ms GPU-bound frame, and its fbm noise is about 90% of that (SIG-083); SIG-079/SIG-080 overstated it (SIG-081). The noise, not the march resolution, is the first lever. Measure nebula changes by B3 frame time at 4K (SIG-082). |
| P-2 | `bridge` pass, 13 ms GPU at times | Measured; cause of the 3→13 ms jump unknown | SIG-008 | Find what changed between C-001 reports 2 and 3 (alert state, probe capture, camera). Candidates: reflection-probe fill, SSAO quality, PBR lights. |
| P-3 | Post chain (dof + bloom + resolve + post), 5 ms GPU | Measured | SIG-009 | Cost each pass against what it adds visually. DOF alone is 0.9–2.2 ms. |
| P-4 | Death damage path (`cb.damage_sys`, `sim.debris_chunks`, `cb.death`) | **Fixed for the station; ship deaths reduced** (branch `perf/death-hitch`; merged to main `5fc58ec8`, live-verified 2026-10-18). Station: carves skip saturated cells and report a tight box (worst frame 3.25 s → 0.45 s, SIG-032); the damage lattice is sized by the hole modifier, FedOutpost 13.4M → 90k cells (→ 31–34 ms, SIG-037); the trace BVH is built at spawn (→ 21–24 ms, about 16 ms of it the ordinary frame, SIG-040). Ships: the core breach no longer re-carves the field every frame (SIG-041, SIG-042); Effects is imported at boot (`cb.death` 16.8 → 1.3–2.2 ms, SIG-043, SIG-044); queued carves run under a 3 ms per-frame budget (worst frame 45–50 → 33–37 ms, SIG-045). **Left:** one carve plus the first BFS in a ship's death frame. | SIG-003, SIG-004, SIG-024, SIG-027–SIG-033, SIG-036–SIG-045 | (1) Done: Mark checked the coarser station holes, the wreck and the breach growing on screen in game, 2026-10-18. (2) Measure whether the first hull hit in a mission without Effects paid the import too (should now be gone). |
| P-5 | Damaged hull on the viewscreen (`carve_stencil` + `breach`), 11 ms CPU | Measured, one report | SIG-010 | Check whether per-frame work could be cached while the damage is unchanged. |
| P-6 | `anim` bone palettes, 1.5–2.8 ms CPU every frame | Measured | SIG-011 | Skip instances that are not visible (e.g. the bridge crew in exterior view) or far away. `frame-profiler.md` already notes there is no gate. |
| P-7 | `render_prep` about 6 ms on the Quick Battle bridge before the battle | Measured; cause unknown | SIG-012 | Find which child scope is responsible. `frame-profiler.md`'s first capture saw 15.8 ms in the same scene. |
| P-8 | `ui_panels` (Python) at scale | Cheap at B1/B2 scale; 10–17 ms in earlier 17-ship captures | SIG-013 (counter) | Measure in B3. Profile each panel. The sensors panel may re-send its data every frame (inferred from the code). |
| P-9 | AI avoidance all-pairs scan | Earlier captures only | — | Needs B3. A spatial broadphase, as the projectile loop got. |
| P-11 | Lone `space.opaque` spikes of about 575 ms in B2/B2d; then the renderer's other byte-at-a-time and first-use file loads | **Spike fixed** (`e5e2e3b7`, branch `perf/death-hitch`): the first collision scuff loaded the 12.6 MB `scuff_normal.tga` in its draw, about 350 ms of it a byte-at-a-time read (SIG-046); it is now read in one block and loaded at boot, about 158 ms (SIG-047). **Follow-up done** (branch `perf/renderer-file-reads`; both merged to main `5fc58ec8`, live-verified 2026-10-18): no file in `native/src` reads through `istreambuf_iterator` any more (`82ad3dca`; `tests/tools/test_no_bytewise_file_reads.py` guards it). Every loader but the atlases reads under 100 KB, at most 0.4 ms now (SIG-049, SIG-055). The impostor atlases were the one real cost, about 1 s in B1's load frame and about 120 ms a rock on any later first draw (SIG-050–SIG-052): they now decode on self-feeding workers from mission load and upload one a frame (`ec14d2e3`, `b829ce0c`; 1,054 → 53–57 ms, SIG-054), only where the set has rocks (SIG-056, SIG-057). | SIG-034, SIG-046–SIG-057 | (1) The upload is 7.6 ms of GL a rock, one a frame for about 29 frames after a rock mission loads (SIG-054). If that matters, either upload only on first draw (no pump; holds about 2 MB of decoded RAM a rock) or build the mips on the worker so the upload is one `glTexImage2D` per level (changes the mip filter: needs a visual check). (2) First use during play is left only for the reticle and viewscreen static, each under 0.5 ms of read (SIG-049); their decode + upload is not measured, but they are 16 KB or smaller textures. |
| P-10 | CEF overlay full-surface upload, about 0.53 ms CPU a frame even when nothing repainted | Measured; small | SIG-020 | `DAUNTLESS_CEF_UPLOAD=on_paint` (on main since `a4e8e485`; still opt-in) skips unrepainted frames losslessly. Measure the paint rate in a HUD-heavy scene (B2) before deciding whether to make it the default. |

---

## Measurement gaps

Each of these limits what a capture can tell us. Closing one is perf work in
its own right.

| ID | Gap | Effect | Fix |
|---|---|---|---|
| M-1 | **Closed (branch `perf/vesuvi-gpu`, `a9d824ab`): `DAUNTLESS_PROFILE_GPU_FOCUS=a,b,...` GPU-times named nested scopes** by splitting the top-level pass's elapsed query around each one; the top-level row still totals all of it (16 splits moved `space` by 0.2 ms, SIG-065). Implies GPU timing, so attribution only (M-6). Two limits: on this tile-based GPU a span may hold earlier draws' deferred work, so confirm a large row by A/B (`DAUNTLESS_DEV_RENDER_OFF`, SIG-066); and pass totals change with the focus set while focused spans do not, so compare totals only between runs with the same focus list (SIG-074). | Was: P-1's 27.6 ms could not be broken down. | Done. |
| M-2 | Some `sim` time is outside every child scope. It happens during the E1M2 opening cutscene (SIG-022). | About 6.5 ms in E1M2 before the warp (SIG-006), and the battle-start hitch (SIG-005), cannot be attributed. | Add scopes until the unscoped part is under 0.5 ms. |
| M-3 | The log has no event markers (warp arrival, ship death, battle start), and the scene line does not count deaths (SIG-015). **Partly closed:** an unattended run prints `[dev-scripted]` lines for cutscene start/end, view, destroy and quit. | Reports are lined up with game events by inference. | Print a one-line marker to stderr on each such event while the profiler is on. |
| M-4 | Capture details are not written to the log: window size, build type, commit, quality settings. **Partly closed:** a `[profile]` line now records framebuffer and window size, headless, and GPU timing; `DAUNTLESS_WINDOW_SIZE=WxH` pins the size. Build type, commit and quality settings are still missing. | C-001 and C-002 lack window size. Build type had to be read from `CMakeCache.txt`. | Print a header line when profiling starts. |
| M-5 | The periodic report and spike capture cannot run together. | A hitch in a periodic capture gives only a lower bound (the EMA rule above). | Allow both at once, or always pair a periodic run with a spike run. |
| M-7 | **Headless E1M2 is capped at 60 Hz by `cef.pump`** (SIG-070): `CefDoMessageLoopWork` blocks to the 16.67 ms mark once the frame is faster. B2 is not capped, nor was this morning's headless B1 (C-012). | Any B1 frame under 16.6 ms reads as 16.6 ms, so a fix that removes a GPU bound shows as "16.6 ms" whatever its size (SIG-066, SIG-071). The `cef.composite` wait and GPU focus spans still show the change. | Find what makes CEF block (E1M2's HUD repainting at the windowless frame rate, 60, is a candidate: `browser_settings.windowless_frame_rate`). Until then, read frame time as `loop − cef.pump + about 0.4 ms`. |
| M-6 | **Mitigated (on main since `a4e8e485`): the profiler is now CPU-only by default; `DAUNTLESS_PROFILE_GPU=1` opts in to GPU timing** (SIG-021). With its GPU timer on, the profiler adds roughly the GPU frame time to every frame (SIG-019). It makes the CPU wait for the GPU, and the wait shows up in the overlay's draw call inside `cef.composite`. The earlier `frame-profiler.md` figure (+0.6 to +2.4 ms) came from a light headless bench and understates it. Mechanism not established. | Every loop time in C-001 and C-002 is inflated by about their GPU time. `cef.composite` reads as a big cost when it is really the profiler's wait. | Done: CPU-only is the default, and B1 and B2 have been re-captured with it (C-012–C-015; SIG-022, SIG-026). The CPU-only profiler still costs about 1.6 ms a frame (SIG-021). |
