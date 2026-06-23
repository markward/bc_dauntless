# Nebula Ship Wake — Design

**Date:** 2026-06-24
**Status:** Design approved, pending spec review
**Builds on:** the merged nebula work — V1 fog, volumetric clouds + tactical density, thunder/lightning, and hull discharges. This is follow-on **④** of the nebula roadmap (see `project_nebula_pockets` memory) — the **last** piece of Mark's original vision.

---

## 1. Vision

Flying through a nebula should leave a **wake** — "a visible representation of the ship disrupting the cloud it's flying through." The ship doesn't *clear* the cloud; it **stirs it up**: along the recent path the cloud churns, swirls, and **glows brighter** (the ship's passage energizes the charged particles), then settles back over a few seconds. A luminous, turbulent trail behind you, tying into the lightning/charged-particle theme.

## 2. Scope

**In scope:** a per-player **wake tracker** (ring buffer of recent positions) feeding a **churn+glow modification** inside the volumetric cloud's raymarch — animated turbulence + a self-glow lift along the trail, fading as the cloud settles. Gated by the existing **Volumetric Nebulae** toggle (the wake is part of the cloud).

**Out of scope:** clearing/carving the cloud (we churn, not clear); other ships' wakes (player-only V1); affecting concealment/gameplay (visual-only — your wake is behind you, not where you hide); a new toggle.

## 3. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Wake character | **Turbulent churn** (displaced, not cleared) | Mark's pick — the ship stirs the cloud, doesn't carve a tunnel |
| Energy | **Energized glow** (brighter, charged) | Ties to the charged-particle/lightning theme; the wake is luminous |
| Architecture | **Trail points fed into the volumetric raymarch** | The wake IS the cloud being disturbed — belongs in `density()`/lighting, reuses the volumetric pass, only shows when there's a cloud |
| Toggle | **None new — gated by Volumetric Nebulae** | The wake is a property of the volumetric cloud (no cloud → no wake) |
| Gameplay | **Visual only** (GPU-only; CPU concealment untouched) | Your own wake is behind you; it never disturbs your stealth |

## 4. Architecture

A **Python wake tracker** emits a bounded trail; the host feeds it to the volumetric pass, which applies the churn+glow in its existing raymarch. GPU-only.

### Components

| Unit | Location | Responsibility |
|---|---|---|
| **Wake tracker** | `engine/appc/nebula_wake.py` (new), ticked per-frame from the host loop | Ring buffer of the player's recent world positions, sampled **by distance moved** (~`SPACING` GU), each with an age. Caps at `N` points (oldest evicted). Emits `trail_points() -> [{pos, strength}]`, strength age-faded 1→0 over `LIFETIME`. Records only while in a nebula; clears on leaving. Pure logic, deterministic from the position history. |
| **Churn+glow** | `native/src/renderer/shaders/nebula_volumetric.frag` (extend) | Per march sample: `wake = max_i(strength_i · smoothstep(WAKE_RADIUS,0,dist(p, pos_i)))`. Where `wake>0`: add animated turbulence to density (`+= wake·turb(p·TURB_FREQ + u_time·SWIRL)·TURB_AMT`) and lift the self-glow (`+= wake·WAKE_GLOW`, hot-tinted). `wake==0` early-out keeps the common case cheap. |
| **Trail feed** | `set_nebula_wake` binding + `engine/renderer.py` wrapper + the volumetric pass uploads `u_wake[N]` (vec4 xyz=pos, w=strength) + `u_wake_count` | Mirrors the `u_spheres`/`u_sphere_count` upload. Bounded `N`. GPU-only — never touches the CPU concealment field. |
| **Host wiring** | `engine/host_loop.py` | Tick the tracker beside the other nebula drivers (reuse the in-nebula signal + `player.GetWorldLocation()`); per frame `r.set_nebula_wake(trail_points())` (empty when off / not in nebula / not moving); reset on mission swap. |

**Boundaries:** tracker = positions in → trail points out (no GL); shader churn = data-in→pixels-out; feed mirrors the existing sphere-array upload. Inert outside a nebula, when stationary, and when Volumetric Nebulae is off.

## 5. The wake tracker

- **Recording by distance:** drop a new trail point only when the ship has moved ~`SPACING` GU since the last (so fast/slow ships lay a comparably-spaced trail; a stationary ship lays none). Each point stores position + spawn time.
- **Cap at `N`:** oldest points evicted — `N` bounds both trail length and per-sample shader cost.
- **Fade:** strength ramps 1→0 over `LIFETIME` s (then dropped) — strongest right behind the ship, dying down the trail as the cloud settles. A brief front-rise eases the newest point in (no pop).
- **Outputs/tick:** `trail_points() -> [{pos:(x,y,z), strength:float}]`, ≤ `N`, freshest first, strength pre-faded. Deterministic (driven by where the ship went; no RNG).
- **Gating:** records only in a nebula; clears on leaving; host feeds `[]` when the toggle is off.
- **Dials:** `SPACING`, `N`, `LIFETIME`, front-rise time.

## 6. Churn+glow shader & feed

Per march sample `p` in `nebula_volumetric.frag`, compute one `wake` value (max over the `N` trail points of `strength · smoothstep(WAKE_RADIUS,0,dist)`), then where `wake>0`:
- **Agitate density:** add a second higher-frequency turbulence noise advected by `u_time` (`SWIRL`), scaled by `wake·TURB_AMT` — the trail churns and swirls.
- **Energize glow:** lift the self-glow term by `wake·WAKE_GLOW`, tinted toward a hot charged-particle colour — the trail reads as luminous.

Both scale with `wake`, so the effect is strongest right behind the ship and fades down the trail and at the tube edge. **Dials:** `WAKE_RADIUS`, `TURB_FREQ`, `TURB_AMT`, `SWIRL`, `WAKE_GLOW`.

**Feed:** `set_nebula_wake(points)` → `u_wake[N]` + `u_wake_count`, uploaded by the volumetric pass (mirrors `u_spheres`). Empty list → `u_wake_count = 0` → the shader is byte-identical to the plain cloud.

## 7. Toggle, integration & testing

**Toggle:** none new — gated by the existing `dauntless_volumetric_nebulae::enabled()` (no cloud → no wake).

**Integration (host loop):** tick the tracker each sim frame when in a nebula (reuse the in-nebula signal + player world position); per frame `r.set_nebula_wake(trail_points())`; reset on mission swap.

**Testing:**
- **Tracker (pytest):** a point recorded only after moving ~`SPACING` GU (not per tick); stationary → none; strength fades 1→0 over `LIFETIME`, points drop at end of life; buffer caps at `N` (oldest evicted); clears on leaving the nebula; reset on swap; deterministic from a position sequence.
- **Shader (C++ FrameTest):** a volume with a wake point near the camera → the region around it is brighter/agitated vs a no-wake control; empty wake list → byte-identical to the plain cloud.
- **Live (Mark):** fly through a nebula — a luminous, churning, swirling trail forms behind you and settles over a few seconds, strongest right behind the ship; toggling Volumetric Nebulae off removes it with the cloud; framerate holds.

## 8. Performance — risk and Plan B

**The risk:** the wake adds an `N`-point loop to **every cloud sample** in the already perf-sensitive quarter-res raymarch (the cloud cost we fought down in the volumetric round). At `N≈24` and ~64 march steps that's ~1500 extra distance ops/pixel, plus the turbulence eval where `wake>0`.

**First levers (tuning, try before Plan B):**
- Lower `N` and `WAKE_RADIUS` (shorter/tighter wake = fewer points, smaller affected region).
- The `wake==0` early-out already skips the turbulence eval for the (common) non-wake samples.
- Evaluate the wake on a coarser cadence (e.g. every other march step) and interpolate.

**Plan B (structural, if tuning isn't enough) — in order of preference:**

1. **Decoupled additive wake (cheapest, ships for sure).** Drop the wake out of the raymarch entirely and render it as its own **additive pass** — glowing turbulent billboards/particles spawned along the trail (reuse the existing particle/`dust_pass`/`hit_vfx`-style billboard infrastructure). Zero added cost to the cloud raymarch; the wake renders independently and is gated by the same toggle. **Trade:** the wake is *overlaid on* the cloud rather than *the cloud itself being disturbed* — slightly less integrated (it won't occlude/blend with the volumetric density per-sample), but visually still a luminous churning trail, and it decouples the cost completely. This is the safe fallback.

2. **Volume-texture injection (keeps the integrated look, more infra).** Splat the trail into a small low-res **3D texture** once per frame (CPU splat or a tiny compute/raster step); the raymarch then samples that texture **O(1) per step** instead of looping `N` points. Removes the per-sample loop cost regardless of trail length while keeping the wake *inside* the cloud (true density agitation + glow). **Trade:** more infrastructure (a 3D texture target + per-frame splatting), and the wake resolution is bounded by the texture size.

**Decision rule:** ship the in-raymarch design (§4–6) if it holds 60 Hz after the first-lever tuning; if not, fall back to **Plan B #1** (decoupled additive) as the pragmatic ship-it option, and only reach for **#2** (volume injection) if the decoupled look loses too much of the "disturbing the actual cloud" feel. The choice is made at live verification with real frame-times, not guessed now.

## 9. Key risks

- **Performance** (the headline) — see §8; the in-raymarch loop is the risk, with a documented two-tier Plan B.
- **The churn look** — turbulence freq/swirl/glow are procedural-shader dials needing live calibration from "noisy smear" to "energized wake."
- **Wake/concealment mismatch** (minor) — the wake is GPU-only, so an enemy sitting in your wake sees a churned-glowing trail but is still concealment-hidden there. Acceptable (rare; your own wake never affects your stealth).

## 10. Key references

- `native/src/renderer/shaders/nebula_volumetric.frag` (`density()`, the march loop, `u_spheres`/`u_sphere_count` feed) — where the churn+glow hooks in.
- `native/src/renderer/nebula_volumetric_pass.cc` (uniform upload, `render()` signature, `u_time`) — the feed + the scratch/half-res cost context for §8.
- `engine/appc/nebula_runtime.py` (the in-nebula signal) + `nebula_thunder.py`/`hull_discharge.py` (driver shape to mirror).
- `dauntless_volumetric_nebulae` toggle (frame.cc / host_bindings / renderer.py) — the gate this reuses.
- Plan B #1 infrastructure: `native/src/renderer/dust_pass.cc` / `hit_vfx_pass.cc` / the particle system (additive billboards along a trail).
- Plan B #2 infrastructure: `hdr_target` / scratch-target patterns for a 3D texture target.
