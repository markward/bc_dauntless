# Persistent Damage VFX — Phased Design

**Status:** SUPERSEDED by [`2026-06-08-persistent-damage-decals-design.md`](./2026-06-08-persistent-damage-decals-design.md).
The UV-space damage-mask approach below failed smoke testing (mirrored UVs painted
damage on both hull halves; uniform black splotches; a shield-gating wiring bug). It
is retained only as a record of what not to do. Do not extend this spec — the
object-space decal design supersedes it in full.
**Date:** 2026-06-07
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-06-damage-attribution-design.md`](./2026-06-06-damage-attribution-design.md) — the upstream model. Every persistent-damage feature in this spec consumes the per-hit record `(world_position, surface_normal, post_shield_damage, splash_radius, primary_subsystem)` that `apply_hit` already broadcasts on `WeaponHitEvent`.
- [`2026-06-01-damage-vfx-bridge-feedback-design.md`](./2026-06-01-damage-vfx-bridge-feedback-design.md) — the interior / bridge-camera side of damage feedback (sound, shake). Out of scope here; this spec is purely about exterior hull representation.
- [`2026-05-12-object-emitter-emission-design.md`](./2026-05-12-object-emitter-emission-design.md) — the emitter-attachment machinery that Phases 5 and 6 build on.
- The parked first attempt at a persistent damage VFX brainstorm: this spec replaces it.

## 1. Goal

Reproduce the original game's persistent damage VFX vocabulary on the modern engine without VOX-mesh boolean cutting and without per-ship authored damage stages. Specifically:

1. **Scorch marks** that accumulate on the hull where weapons have struck, persist across ticks, and visually deepen as the same area takes repeat hits.
2. **Hull silhouette change** ("chunks blown out") when accumulated damage at a region exceeds a threshold — without the cut-face stretching / T-junction / interior-leak glitches the original VOX system produced.
3. **Streaming gas / smoke plumes** from impact sites on the hull, randomised in angle and lifetime, gated by accumulated damage at that region.
4. **Subsystem-state-driven plumes** (e.g. damaged warp nacelles vent gas) — same emitter mechanism, different trigger, different anchor.

The original game implemented (1) with a per-instance scorch overlay, (2) with the VOX system, (3) with hardpoint-anchored particle emitters, and (4) was added by modders using the same emitter mechanism. We're collapsing all four into one unified pipeline driven by a single **per-instance damage mask** (a UV-space texture) plus the existing hardpoint emitter machinery.

This is multi-session work. Phases below are ordered by both visual impact and engineering dependency; each phase ships working, testable software on its own.

## 2. Diagnosis — what's in place vs missing

What we have:
- `WeaponHitEvent` broadcast on every hit, carrying mesh-accurate `(P, N)` in world space, the resolved `r_hit` splash radius, and the post-shield damage amount. (`engine/appc/events.py`, populated by `engine/appc/combat.py:apply_hit`.)
- `host.ray_trace_mesh` returns surface point + normal on the loaded NIF geometry. Hit position is accurate to the rendered mesh, not just the bounding sphere. (`native/src/renderer/ray_trace.cc`.)
- Damage attribution: hull always takes full post-shield damage; subsystems within splash take weighted damage independently. (`engine/appc/combat.py`.)
- Hit feedback stubs: `engine/appc/hit_feedback.py` already dispatches on severity tier (shield-only / hull-pen / critical) but currently fires only audio + screen shake; the renderer-side `hit_vfx.spawn(point)` is a placeholder billboard.
- Per-instance ship state lives in the renderer host (`native/src/host/`) as `ModelInstance` records keyed by `InstanceId`.
- Asset inventory: `Textures/Effects/Damage.tga` (128×128 RGBA — the scorch brush), `ExplosionA.tga` / `ExplosionB.tga`, `spark.tga` / `rough.tga` / `smooth.tga`, `Noise1-3.tga`. All present in the stock game install.
- The `Effects.py` factory pattern (`PhaserHullHit`, `TorpedoHullHit`, `CreateSmokeHigh`, `CreateDebrisSmoke`, etc.) defines the contract our SDK callers expect.
- NIF vertex normals carry hard-edge information as split vertices with diverging normals (confirmed by inspection of Galaxy / Sovereign / Akira / BirdOfPrey: >45° divergence at hundreds-to-thousands of positions per ship). PN-triangle tessellation preserves these creases automatically.

What's missing:
- No per-instance scorch / damage state on the renderer side. `hit_vfx` spawns a transient billboard at the hit point and discards it; nothing accumulates.
- No fragment shader for hull damage — the current hull pass renders base diffuse + glow + specular, no scorch composite.
- No tessellation pipeline. Hulls render as authored, with the original LOD's triangle count.
- No sustained emitter bound to a damage-state predicate. Existing emitters (sun corona, dust) are time-driven, not damage-driven.
- No on-disk smoother-mesh cache. Each ship renders the original NIF mesh at its three authored LODs.

## 3. Locked design decisions

These are settled by the brainstorm conversation that produced this spec and are not open for relitigation in implementation.

### 3.1 The damage mask is the single source of truth

A **per-instance UV-space damage mask** carries all persistent damage state. R8 texture (single channel = damage intensity), 512×512 per ship instance (256 KB), allocated lazily on first hit. Stored on the renderer's `ModelInstance` record; survives across ticks; cleared on ship destruction or explicit repair.

All four visual features above are derived from this one texture:

- Scorch (feature 1) reads the mask, composites `Damage.tga` colour over the base hull texture.
- Silhouette change (feature 2) reads the mask, drives fragment `discard` and tessellation-shader vertex displacement.
- Impact-site plumes (feature 3) read mask intensity at hardpoint positions to decide which emitters are active.
- Subsystem plumes (feature 4) read the SDK's `subsystem.IsDamaged()` directly, but use the same emitter machinery as (3).

This means we never have to author or precompute damage assets per ship. The artist's existing UV unwrap + texture is the full input.

### 3.2 Hits are painted at the mesh-accurate UV, not the world position

When `apply_hit` fires, the C++ ray-trace already returns the surface point and triangle. We extend the ray-trace binding to also return the triangle index and barycentric coordinates. The per-hit pipeline becomes:

1. `apply_hit` resolves `(P, N, triangle_index, barycentrics, r_hit)`.
2. Engine-side: damage gets attributed to subsystems per the existing spec.
3. Renderer-side: paint a radial brush of `Damage.tga` into the mask at the triangle's UV, with brush radius proportional to `r_hit`.

The triangle index plus barycentrics plus the mesh's per-vertex UVs give us the exact `(u, v)` for the impact. The brush radius scales the splash extent into UV space using the triangle's UV-area / world-area ratio (so a 0.15 GU splash on a triangle in dense UV space paints a larger UV circle than the same splash on a triangle in sparse UV space).

### 3.3 UV seams are rasterised into both islands

When a hit lands at a position whose neighbourhood spans a UV seam, the brush gets rasterised into **both** UV islands the seam separates. We pre-compute a per-mesh seam-adjacency table at NIF load time (positions duplicated with matching normals on either side are seam pairs; from each pair we know which two UV regions are physically adjacent).

Without this, holes that span the seam visibly split and the damage looks fake. With it, the mask is geometrically consistent across the hull surface.

### 3.4 The asset contract from `Effects.py` is preserved for the factories this spec covers

Our `engine/appc/effects.py` (new module) exposes the subset of `sdk/Build/scripts/Effects.py` factories that this spec implements — the sustained / persistent ones:

- `CreateSmokeHigh`, `CreateDebrisSmoke` — backed by the Phase 5 sustained emitter system, reading `ExplosionB.tga` as the smoke base.
- `CreateExplosionPuff{High,Med,Low}`, `CreateExplosionPlumeHigh` — the puff/plume forms used by sustained venting, reading `ExplosionA.tga`.

The one-shot hit factories (`PhaserHullHit`, `TorpedoHullHit`, `TorpedoShieldHit`, `CreateWeaponSparks`, `CreateObjectExplosion`, etc.) are explicitly out of scope here; they live in `engine/appc/hit_feedback.py` / `engine/appc/hit_vfx.py` with their own wiring to the same on-disk sprites. Mission scripts that call those factories are served by the existing per-event path, not the persistent mask path.

The boundary: anything that **accumulates** or **persists** between ticks lives in this spec. Anything **one-shot per `WeaponHitEvent`** lives in the existing feedback / vfx modules.

### 3.5 Tessellation is opt-in and bake-cached

The base hull mesh renders without tessellation by default. Tessellation kicks in only on instances with damage (mask non-zero) and only on a tile-by-tile basis where the mask exceeds a threshold. This keeps the GPU cost proportional to the **amount of damage in view**, not the number of ships rendered.

A first-load offline pass produces `<ship>_smooth.nif` — a moderately denser mesh, ~3-4× the original triangle count, smoothed by a Catmull-Clark-style subdivision that respects the split-vertex hard edges. This cache is computed once per ship and persists on disk. Modders' new NIFs trigger an automatic bake on first load (same idiom the original engine used for `_vox.nif`).

### 3.6 Hardpoint emitters use the existing object-emitter machinery

Phases 5 and 6 don't introduce a new emitter system. They extend [`object_emitter`](./2026-05-12-object-emitter-emission-design.md) with a "predicate + duration" gating layer:

```
emitter_binding = (
    anchor: HardpointId | ImpactSiteUV,
    predicate: Callable[[ShipInstance], bool],
    duration: Optional[float],  # None = while predicate true
    effect: EffectFactory,       # references Effects.py-style factory
)
```

Predicates query damage state (mask intensity at the hardpoint position, or `subsystem.IsDamaged()`); emitters spawn / despawn based on predicate transitions.

### 3.7 What's not in this spec

- One-shot hit-flash, shield ripple, spark burst on individual impacts. Those live in `engine/appc/hit_feedback.py` and `engine/appc/hit_vfx.py`; they fire per-event, don't accumulate, and don't need the mask. The existing implementation just needs to wire to the right textures (`ExplosionA.tga` etc.) — that's a small ticket, not part of this spec.
- Bridge-interior damage feedback (sound, shake, console sparks). Covered by `2026-06-01-damage-vfx-bridge-feedback-design.md`.
- Cinematic ship-destruction sequence. Builds on Phase 4 (silhouette state) but warrants its own spec when we get there.

## 4. Phases

Each phase is an independently-shippable session: brainstorm-as-needed → plan → implement → merge. Order is chosen so that visual impact is positive from Phase 1 onwards, even before later phases land.

### Phase 1 — Per-instance damage mask infrastructure (no shader changes yet)

Smallest unit; pure engine + renderer plumbing.

- Extend `host.ray_trace_mesh` to return `(point, normal, t, triangle_index, barycentrics)`.
- Allocate an R8 damage mask texture on `ModelInstance`, lazily on first hit. Texture stays GPU-resident.
- Implement `damage_mask::paint(instance_id, triangle_index, barycentrics, brush_radius)`. Rasterises a radial soft-edge brush into the mask at the triangle's UV, using the mesh's per-vertex UVs to convert barycentrics → UV.
- Pre-compute the per-mesh seam-adjacency table at NIF load time. Use it in `paint` to rasterise into adjacent UV islands when a brush spans a seam.
- Wire `apply_hit` → `host.damage_mask_paint(instance_id, ...)`. Mask updates per hit but isn't read by anything yet — Phase 2 introduces the shader.
- Tests: synthetic hits at known UV positions write to known mask coordinates; seam-spanning hits write to both islands; a hit at the same triangle twice accumulates intensity.

Visual result: nothing yet. This is the substrate for everything below.

### Phase 2 — Scorch shading

Uses the Phase 1 mask. Smallest visual change.

- Add a new sampler binding to the hull fragment shader: `u_damage_mask`.
- Sample the mask at the fragment's UV; mix `Damage.tga` colour over the base hull texture proportional to mask intensity.
- Per-instance binding: each ship renders with its own mask. Instances without damage render exactly as before (mask defaults to a 1×1 zero-intensity texture).
- Implement the bind path in `native/src/renderer/`.
- Tests: render a known-damaged ship, sample the framebuffer at the painted region, assert the colour shifted toward scorch.

Visual result: scorch marks appear where hits land. No silhouette change yet. This alone closes 60% of the original VOX visual contract.

### Phase 3 — Discard + parallax (fake silhouette change)

Cheap silhouette change using the mask.

- Extend the fragment shader: where `mask > 0.7`, `discard`. At the edge band `0.5 < mask < 0.7`, use the mask gradient as a parallax offset to give the "hole" some apparent depth.
- Author normal-map derivative from the mask alpha gradient inline in the shader.
- Tests: visual regression against captured reference images at fixed damage states.

Visual result: holes appear at high-damage regions. From normal viewing angles the hole reads as 3D; from glancing angles the flatness is visible. Acceptable for space combat (the camera rarely sits at the hull plane).

### Phase 4 — Tessellation + displacement (real silhouette change)

Promote Phase 3's fake holes to real geometry. Highest engineering cost of all the phases.

- Offline mesh-bake pass: given `<ship>.nif`, produce `<ship>_smooth.nif` with ~3-4× triangle count via subdivision that respects split-vertex hard edges. Tool lives in `tools/` or `native/tools/`. Persists output beside the input file.
- Modder support: if `<ship>_smooth.nif` is absent at load time, generate it on first load (matching the original engine's `_vox.nif` idiom).
- Runtime PN-triangle tessellation pass on the hull. Tess factor: 1 (no extra subdivision) when mask is zero in the triangle's UV region; up to 8 when mask is high (gives curved cut rims).
- Tessellation evaluation shader: vertex displacement inward proportional to mask intensity. Combined with the Phase 3 discard, this produces actual silhouette holes with curved beveled rims.
- Tests: visual regression against Phase 3 references showing the silhouette now changes from glancing angles; tessellation perf benchmark verifying steady state with N ships under typical engagement loads.

Visual result: real chunk-missing geometry, modern fidelity, none of the VOX cut-face artefacts.

### Phase 5 — Sustained impact-site emitters (streaming gas plumes)

Uses the mask to know where damage is concentrated.

- New module `engine/appc/sustained_emitters.py`. On each tick, per ship instance, sample the mask at a sparse set of candidate positions (the ship's hardpoint positions plus a few sampled high-damage cells from the mask). Where mask intensity exceeds a threshold and no emitter is currently bound, spawn one.
- Emitter spec: `CreateSmokeHigh`-style parameters, anchored to a frame on the ship at the hardpoint position. Randomised emit angle (60° variance per the SDK's `SetAngleVariance(60.0)` precedent) and lifetime.
- Despawn condition: mask intensity at the anchor drops below threshold (e.g. due to repair), or instance is destroyed.
- Tests: synthetic ship with painted damage at known positions spawns the expected number of emitters; despawning works when damage clears.

Visual result: damaged hulls visibly leak gas from impact sites. Persistent, randomised, anchored to where the hits landed.

### Phase 6 — Subsystem-driven emitters (mod-style nacelle plumes)

Same emitter machinery, predicate-driven instead of mask-driven.

- Extend `sustained_emitters.py` with predicate / anchor pairs registered per (ship-class, subsystem-name). Default registrations: warp nacelles emit while `WarpEngines.IsDamaged() and not WarpEngines.IsDestroyed()`; impulse engines emit gas while `ImpulseEngines.IsDamaged()`; warp core emits sparks while critical.
- Anchor lookup: the subsystem hardpoint position from `subsystem.GetPosition()` transformed into world via `_subsystem_world_position` (already exists in `combat.py`).
- Optional duration cap to match the original mod behaviour ("plume for 30 seconds after damage threshold reached, then fade").
- Tests: damage a Galaxy's warp engines, advance ticks, assert emitter appears at the nacelle position; clear damage, assert emitter fades.

Visual result: damaged subsystems visibly affect their corresponding hull region — nacelles vent gas, impulse engines smoke, warp core sparks.

## 5. Non-goals

- **Authored per-ship damage stages.** Every visual layer is derived from the runtime mask or from existing subsystem state. No artist re-authoring per ship.
- **Voxel-based damage representation.** The existing `_vox.nif` files are not consumed by this design (though the offline tool in Phase 4 could read them as a sanity check on smoother-mesh bake quality if it helps).
- **Procedural debris chunks flung off the hull on heavy hits.** Future work; gated on the death-sequence spec.
- **Repair animations.** Mask is monotonically additive in this spec; repair would clear regions, but the visual transition (e.g. fade-out, animated patching) is not designed here. Stock BC didn't model this either — repair quietly restored subsystem state without visual feedback.
- **Per-weapon-type custom brush patterns.** All weapons paint with the same `Damage.tga` for v1. Per-weapon distinctions (phaser is thin/elongated, torpedo is round, disruptor is jagged) is a polish item for after Phase 3.
- **Save / load of the mask.** Mask is runtime state; saves don't persist it. After load, ship damage state is reflected only by subsystem conditions, and the mask rebuilds organically as combat resumes. Matches stock BC's save/load fidelity.

## 6. Parking lot

- **Mask resolution.** 512×512 R8 is the proposed default. Higher-res (1024) gives crisper holes but quadruples memory. Lower-res (256) saves memory but visible pixelation at close range. Default stands until profiling.
- **Subdivision algorithm choice for Phase 4 bake.** Catmull-Clark vs PN-triangle vs simple loop-subdivide. Catmull-Clark produces the smoothest result on quad-like topology but BC NIFs are tri-only; PN-triangle works directly on triangles. Defer to Phase 4 brainstorm.
- **Tessellation hardware floor.** Some older laptops won't tessellate well. Phase 4 should ship behind a graphics-quality toggle so Phase 3's fake holes remain the fallback.
- **Damage that exposes "interior" geometry.** When Phase 4 cuts an actual hole, what does the camera see through it? Skybox, by default. For hero ships, an authored low-poly interior shell could be added later. Not in scope for v1.
- **Decal projection from multiple normal directions.** A hit on the saucer rim's edge in shared UV space might project a brush whose centre is on the rim but whose edge wraps to a face that visually faces away from the camera. The seam-rasterisation logic addresses this geometrically; we may discover visual artefacts that warrant a normal-aware brush falloff. Phase 1 testing will reveal if this is real.
- **Per-instance mask GC.** A scene with hundreds of dead ships could leak mask memory. Add a destructor hook in `ModelInstance::destroy` to free the GPU texture.

## 7. Open questions

- **Q1 — exact brush function for the mask paint.** A radial Gaussian, a hard circle, a tile of `Damage.tga` itself? Affects the visual character of scorch. Defer to Phase 1 implementation; the brush is a one-line shader change later.
- **Q2 — UV stretch on Catmull-Clark-subdivided meshes.** When we densify the mesh in Phase 4, the new vertices need UVs. Linear interpolation across the parent triangle works at low subdivision levels but stretches at high levels. May need a follow-up UV-relaxation pass. Investigate during Phase 4.
- **Q3 — emitter pooling.** A heavy fleet engagement could spawn dozens of sustained emitters across many ships. The existing `object_emitter` machinery may need a global cap or per-instance prioritisation. Investigate during Phase 5.
- **Q4 — does the SDK's `Effects.PhaserHullHit` consumer code expect a specific lifetime / size from the spawned particle controller?** Our reimplementation routes the call through the mask path; if mission scripts assume the returned `EffectAction` reference is retained somewhere, we need to honour that contract. Audit during Phase 1 wiring of one-shot effects.

## 8. Workflow

This spec produces six independently-plannable sessions. Recommended order is Phases 1 → 6 in sequence; Phases 5 and 6 could parallelise after Phase 4 ships if there's appetite for two threads.

Each phase's session starts with the brainstorming-skill flow against this spec as input, produces its own plan in `docs/superpowers/plans/`, executes via `subagent-driven-development`, and merges to main. The phase boundaries are deliberately drawn so each one ships visible improvement to the game (Phase 1 is plumbing only, but Phases 2-6 each light up a specific visual feature).

When a phase ships, this spec gets a "shipped $DATE" annotation on that phase's section, and any open questions resolved during implementation get answered in §7. The spec evolves with the work.
