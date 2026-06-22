# Warp VFX — Procedural Galaxy Flythrough (Design)

**Date:** 2026-06-22
**Status:** Approved for planning
**Author:** brainstormed with Mark

## Goal

Turn the warp from an instant hard cut into a short, non-cinematic **transit**
where the player watches the real procedural galaxy stream past — nebulae and
star-clouds parallaxing as the viewpoint travels from the origin system to the
destination — with stars streaking for speed and a warp flash bracketing each
end. The camera stays **unlocked**; the effect works in whichever view the
player is in (exterior or bridge). This is Stage 2 of the warp arc, layered onto
the shipped Stage-1 spine and gating (`[[project_warp_mechanism_sdk]]`).

This is deliberately NOT a faithful reproduction of BC's warp set / fixed
cutscene "tunnel." BC moved the ship into a dedicated warp set with a frozen
camera and a `starstreak.tga` quad; we instead ride our **procedural starfield**
so the player sees themselves crossing the larger astronomical environment —
something BC's static tunnel never did.

## Background

**BC's warp effect (reference):** a hybrid C++/Python system — ship hidden,
moved into a C++ "warp set" holding a StarSphere + fixed cutscene camera, mesh
stretched via the `WES_*` state machine, `starstreak.tga` motion-blur for speed,
and `warpflash1-8.tga` fullscreen flashes masking the entry/exit set switches.
Assets in `game/`: `data/Textures/starstreak.tga`, `warpflash1-8.tga`,
`sfx/enter warp.wav`, `exit warp.wav`, `warp flash.wav`.

**Our procedural sky (the enabler):** the sky is **vantage-parameterized**.
`sky_projection.vantage_for_set(set, model)` returns the system's galaxy
coordinates; `sky_projection.project_sky(vantage, model)` re-projects every
nebula/star-cloud from that point (features grow, shrink, parallax, envelop).
The vantage is recomputed fresh each frame in `host_loop._aggregate_backdrops`,
so substituting an animated origin→destination vantage during warp makes the
galaxy fly past — no change to the backdrop descriptor structure.

**Performance note (the one real wrinkle):** the procedural sky is **baked into
a cubemap** once per system (`backdrop_pass.render_cubemap` /
`host_bindings.cc` bake at ~line 514, invalidated by `g_sky_dirty`). Animating
the vantage means the cubemap is stale unless re-baked, so the transit forces a
sky re-bake each frame while it runs — a brief, bounded cost (a handful of
seconds at warp time), covered by the toggle fallback below.

## Decisions (locked during brainstorming)

1. **Concept:** Approach A — procedural galaxy flythrough. The vantage animates
   origin→destination; stars streak; warp flash brackets entry/exit; the
   existing Stage-1 set-swap happens at the end (masked by the exit flash).
2. **No camera control / cutscene.** Camera stays unlocked; works in exterior or
   bridge view. The "motion" comes from the backdrop streaming past, not a
   camera move.
3. **Streak technique:** stretch the procedural star blobs along the travel
   direction in `backdrop.frag` (true "stars streak"), NOT the existing
   motion-blur pass (which keys off world-space motion the ship doesn't have
   during a vantage-driven warp).
4. **Modern-VFX toggle, default ON; OFF = the Stage-1 instant hard cut.** Clean
   fallback, perf escape hatch, stock-ish behavior when off.
5. **Procedural-sky dependency:** the galaxy flythrough rides the procedural
   sky. With procedural sky OFF, warp still does streaks + flash but skips the
   vantage parallax (nothing to animate).
6. **Fail-open:** a VFX error never blocks the warp — the set-swap still
   completes (same discipline as the warp spine/gates).

## Architecture

The warp becomes a timed transit owned by a per-frame **WarpVFX manager**, with
the set-swap still living in the `WarpSequence`:

```
t=0:      entry warp-flash; WarpVFX.start(src_vantage, dst_vantage, T, travel_dir)
[0, T):   per frame in the host loop — WarpVFX.tick(now):
            • vantage = lerp(src, dst, ease(progress))  -> galaxy streams past
            • streak_intensity ramps 0 -> peak -> hold  -> stars stretch
            • flash_intensity entry pulse fades
            • local sun/planet aggregation fades out     -> clean crossing
t≈T-ε:    exit warp-flash pulse (masks the swap)
t=T:      Stage-1 swap (ChangeRenderedSetAction -> place player -> finalize);
            WarpVFX.stop() (intensities -> 0; vantage now naturally = destination)
```

- **WarpVFX** (host_loop) owns transit state, ticked each frame against the
  game-time clock; `is_active()`, `vantage()`, `streak_intensity()`,
  `flash_intensity()`, `travel_dir()`.
- **WarpSequence** (warp.py) starts the manager + entry flash, holds `T` via a
  delayed action, then runs the existing swap actions; a final action stops the
  manager. When the toggle is OFF (or no player/destination), it stays the
  current instant sequence — Stage-1 behavior unchanged.
- The set-swap timing is the only change to the spine: instead of firing at
  t=0, the swap actions fire at t=T (after the transit), masked by the exit
  flash.

## Components

### `engine/host_loop.py` — WarpVFX manager + per-frame feed

- `class WarpVFX`: `start(src_vantage, dst_vantage, duration, travel_dir, now)`,
  `tick(now)`, `stop()`, `is_active()`, and the per-frame getters above.
  Game-time clock (`App.g_kTimerManager`), eased progress, clamped at 1.0.
- A module-level `g_warp_vfx` instance (or attached to the controller).
- `_aggregate_backdrops`: while `g_warp_vfx.is_active()`, use
  `g_warp_vfx.vantage()` instead of `vantage_for_set(...)`; force a sky re-bake
  while active (renderer hook / `g_sky_dirty`).
- Per-frame render section (~line 4298): when active, feed
  `r.set_warp_streak_intensity(...)`, `r.set_warp_flash_intensity(...)`,
  `r.set_warp_travel_dir(...)`, and fade the local sun/planet aggregation.

### `engine/appc/warp.py` — sequence integration

- `WarpSequence_Create` (toggle ON): capture `src`/`dst` vantage via
  `sky_projection.vantage_for_set` and a travel direction; `_WarpTransitBegin`
  action (start manager + entry flash), then the swap actions held by
  `delay=duration`, then `_WarpTransitEnd` (stop manager). The warp button's
  `warp_time` drives the duration (default ~4–5 s, tunable).
- Toggle OFF or no procedural sky / no mapped vantage: emit the current instant
  sequence (Stage-1 hard cut).

### Native renderer (one cmake rebuild)

- `backdrop.frag`: `u_warp_streak_intensity` (0..1) + `u_travel_direction`
  (vec3, world space) — elongate the procedural star distance-falloff along the
  travel direction so stars stretch into streaks; intensity 0 ⇒ byte-identical
  to current.
- Warp **flash**: `u_warp_flash_intensity` in `resolve.frag`
  (`frag_color = mix(frag_color, vec3(1.0), i)`); intensity 0 ⇒ unchanged.
- `dauntless_warp_vfx` namespace (streak/flash intensity, travel dir) +
  pybind setters, read per-frame in `frame()`.
- Force the procedural-sky cubemap re-bake while streak intensity > 0 (so the
  animated vantage is visible).

### `engine/renderer.py` + CEF config

- `set_warp_streak_intensity(float)`, `set_warp_flash_intensity(float)`,
  `set_warp_travel_dir((x,y,z))`, and `set_warp_flythrough_enabled(bool)` /
  `warp_flythrough_enabled()` — mirroring the `motion_blur` wrappers.
- A "Warp Flythrough" row under the Modern VFX config group (same end-to-end
  pattern as motion blur / filmic), default ON.

## Error handling & edge cases

- **Fail-open:** the transit/manager never raises out into the warp path; on any
  error the set-swap still fires (warp completes), worst case as an instant cut.
- **Toggle OFF:** instant Stage-1 hard cut, no transit, no re-bake.
- **Procedural sky OFF:** streaks + flash still play; vantage parallax skipped.
- **No galaxy-mapped vantage** for origin or destination: skip the parallax (use
  a static vantage), keep streaks + flash.
- **Toggle flipped OFF mid-warp:** finish the current transit cleanly (don't
  snap); applies next warp.
- **Mission swap / teardown during warp:** `WarpVFX.stop()`; intensities reset to
  0 so a stale streak/flash can't persist.
- **Off-path parity:** streak/flash intensity 0 and toggle off ⇒ the render path
  is unchanged from today (no regression to normal play).

## Testing

**Headless (pytest):**
- `WarpVFX` tick math: progress 0→1 over duration, eased, clamped; `vantage()`
  equals `src` at t=0 and `dst` at t≥duration; `streak/flash_intensity` envelopes.
- Sequence: toggle ON inserts the transit and holds `duration` before the swap;
  toggle OFF stays the current instant sequence; the swap still fires after the
  transit (player ends in destination).
- Vantage override active only while `is_active()`; `_aggregate_backdrops` uses
  the warp vantage during transit and the set vantage otherwise.
- No-procedural-sky path: warp completes, no parallax, no crash.
- Fail-open: a forced error in the VFX tick still lets the warp complete.

**Native:**
- Shaders compile (ctest); intensity-0 path byte-identical to current frames
  (off parity).

**Live human gate (Mark):**
- Warp in exterior view → galaxy streams past, stars streak, entry/exit flash,
  arrive in the new system; bridge view unaffected (camera unlocked).
- Toggle OFF → instant hard cut. Tune duration / streak strength / flash to
  taste (bias strong first per calibrate-up-then-down).

## Out of scope

- Forced cutscene camera / BC warp-set / fixed "tunnel" framing.
- Ship-mesh stretch (`WES_*` state machine) — deferred; the flythrough +
  streaks + flash carry the effect.
- Warp audio (enter/exit/flash SFX) — a small follow-up; not required for the
  visual.
- The bridge viewscreen showing the flythrough (the player can switch to
  exterior to watch).
- Reworking the cubemap-bake architecture — we accept the per-frame re-bake
  during the brief transit, with the toggle as the escape hatch.

## Related

`[[project_warp_mechanism_sdk]]`, `[[project_modern_vfx_design]]`,
`[[project_render_scale_followup]]`, `[[feedback_vfx_calibrate_up_then_down]]`,
`[[feedback_shader_rebuild]]`, `engine/appc/sky_projection.py`,
`engine/appc/sector_model.py`, `native/src/renderer/backdrop_pass.cc`,
`native/src/renderer/shaders/backdrop.frag`, `engine/appc/warp.py`.
