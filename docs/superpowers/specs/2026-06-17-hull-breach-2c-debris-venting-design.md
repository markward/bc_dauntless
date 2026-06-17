# Hull Breach Renderer — 2c (Debris + Venting) — Design

**Date:** 2026-06-17
**Status:** Design approved, ready for implementation plan
**Scope:** Spec 2c of the hull-damage renderer, the final stage. Builds on the shipped 2a (carve + see-through hole + chunky voxel splat) and 2b (Path C interior scoop). 2c adds the **transient effects unique to a breach forming**: ejected hull debris, atmosphere/plasma venting, and a cooling molten rim. One spec, one feature.

## Motivation

2a/2b make a breach *exist and read as solid interior*, but the moment of breaching is silent — no material thrown off, no venting, no heat. 2c adds that, faithful to BC's destroyed-ship look. It deliberately does **not** re-implement the generic surface-damage VFX already shipped (persistent scorch decals with blackbody cooling embers + glow-flicker in `opaque.frag`; subsystem-damage particle emitters; the analytic `ParticlePass`). 2c covers only what is specific to a **breach event**.

## Approach (settled — "Approach A: analytic, event-driven")

A per-instance **breach-event ring** (modeled on the shipped `DamageDecalRing`) is the single source of truth. On a carve-add it records `{center_body, radius, birth_time, seed}`; entries expire after the effect duration. Three consumers read the active events each frame and compute their output **analytically** from `(birth_time, age, seed)` — no per-frame simulation state, no save/load, deterministic and unit-testable. Alternatives considered: stateful CPU particle simulation (more code, stateful, untestable motion, unneeded for decorative drift) and GPU/compute particles (ruled out — macOS caps us at OpenGL 4.1, no compute/SSBO).

Everything is gated by the existing **"Hull breaches" Modern VFX toggle**. Off ⇒ no events pushed, all consumers no-op, stock render path byte-identical.

## Data flow

```
Python hit_feedback (existing)
  └─ hull_carve_add(instance, center_body, radius)         [existing C++ binding]
       ├─ HullCarveField.add(...)                          [existing — permanent hole]
       └─ BreachEventRing.push({center, radius, now, seed}) [NEW — transient event]

Per frame (frame.cc, gated by dauntless_hull_damage::enabled()):
  active events = instance.breach_events.active(now)
  ├─ breach_pass  : scoop (existing) + molten-rim emissive keyed by event age   [§3]
  ├─ debris_pass  : N tumbling voxel cubes per event (analytic)                 [§2]
  └─ ParticlePass : venting-jet ParticleEmitterDescriptors built from events    [§3]
```

**Clock:** game time (the same clock the decal embers use, `u_decal_time`), so effects scale with time-warp and freeze on pause.

## Components

### 1. `BreachEventRing` (NEW — `native/src/scenegraph/`)
Fixed-capacity per-instance ring (capacity ~24, mirroring `HullCarveField::kMaxCarves` / `DamageDecalRing::kMaxDecals`). Runtime-only VFX, never serialized.
- `push(center_body, radius, birth_time, seed)` — overwrites the oldest slot when full.
- `active(now)` view / predicate — an event is active while `now − birth_time < kEventLife` where `kEventLife = max(kDebrisLife, kVentLife, kRimLife)`.
- `seed` is derived deterministically at push time (e.g. hash of `center_body` + a per-instance monotone counter) so chunk/jet randomness is stable across frames.
- One ring lives on `scenegraph::Instance` alongside the existing `HullCarveField carve`.

The *carve* (hole) is permanent; the *event* (burst/glow/vent) is transient. A breach whose event has expired is a quiet 2b scoop.

### 2. Debris — tumbling voxel chunks
**Chunk sampling (pure, testable).** For an event, sample up to `kChunkCount` (~12–24, capped independent of sphere size) **solid voxels inside the event's carve sphere** from the source fill (available via `SourceVolumeCache`/`CarveFieldCache`). Selection is seeded by the event seed → reproducible. Each chunk gets a body-frame origin (voxel center) and a **per-voxel-index hash → color** — the classic BC multicolor "guts" look (the same idea as the removed 2a cube splat), so the flying debris reads as chunky hull material distinct from the textured scoop wall. (A `Damage.tga`-tinted variant is a tuning alternative, deferred to implementation if the hash colors read poorly.)

**Analytic motion** for chunk `i`, given `age = now − birth_time` and `h = hash(seed, i)`:
- Position: `origin + dir_i · speed_i · age` — `dir_i` biased radially outward from the breach center (sprays out of the hole), `speed_i` from `h`. No gravity, no collision (decorative drift in space).
- Rotation: `angle = spin_i · age` (constant per-chunk angular velocity → tumbling).
- Fade: alpha (and optional shrink) ramps to 0 over `kDebrisLife` (~1.5–3 s); culled past that.

**Render — `debris_pass` (NEW — `native/src/renderer/`).** Instanced unit **cubes** scaled to the voxel cell, transformed by `instance.world · chunk_transform(event, age, i)`, colored per chunk. Depth-tested against the scene (chunks correctly occlude / are occluded), alpha-blended for the fade. Reuses the cube-instancing approach proven in 2a.

### 3. Venting jets + molten rim
**Venting jets — reuse `ParticlePass`.** A pure function `event → ParticleEmitterDescriptor[]` builds, per active event:
- Origin at the breach center; direction **outward along the breach surface normal** (atmosphere/plasma escaping).
- Wispy alpha-blended analytic billboards (existing particle quads), pale plasma/gas tint, widening + thinning along travel.
- Emission rate strongest at `age ≈ 0`, tapering to 0 over `kVentLife` (~1.5–2.5 s) — finite depressurization. After that the event yields no descriptors.

`frame.cc` collects descriptors from all active events and hands them to the existing `ParticlePass` — no new render code.

**Molten rim — emissive on the scoop, keyed by event age.** Add a blackbody emissive term to the breach scoop shader (`breach.frag`): the carved wall glows hottest at `age ≈ 0` and **cools white→orange→red→dark** over `kRimLife` (~2–4 s), strongest near the rim, fading with depth into the scoop. Reuses the scoop geometry already drawn, and the **same `blackbody(heat)` ramp `opaque.frag` uses for decal embers** (consistent cooling color across all damage).
- Integration: `breach_pass` draws the scoop per carve slot, so it correlates each slot to the nearest active breach event (the event was spawned from that carve's center) to get the age it passes to the shader. No matching active event ⇒ emissive term is 0 (cold hole). One small lookup per scoop draw.

## Testing
- **Pure (gtest):** `BreachEventRing` push/overwrite + `active(now)` expiry; chunk-transform (position advances along `dir·speed·age`; alpha → 0 at `kDebrisLife`; deterministic for fixed seed); chunk sampling (N solid voxels inside the sphere, reproducible); venting-descriptor taper (rate → 0 at `kVentLife`; jet along surface normal); rim blackbody ramp (heat → 0 at `kRimLife`, monotone cool).
- **GL (skip-able):** `debris_pass` draws `kChunkCount` cubes for a fresh event, nothing once expired / toggle off; scoop carries emissive for a fresh event, none once expired.
- **Manual (in-game, Mark drives — no synthetic input / capture):** breach a Galaxy → chunks spray out + tumble + fade; jets vent then taper; rim glows then cools to the quiet 2b scoop; sustained fire shows no clutter or stutter; "Hull breaches" off ⇒ none of it.

## Performance / scale
Bounded by construction: fixed-capacity event ring (~24), events expire in a few seconds (a handful active at once); debris capped at `kChunkCount` per event (not per-voxel); venting uses the existing analytic billboard cap; the rim is one emissive term on already-drawn geometry. No per-frame allocation, no simulation buffer.

## Non-goals (2c)
- **No collision/physics** on debris — decorative drift only (the "decorative motion" decision).
- **No save/load** — runtime-only VFX (the event ring is never serialized).
- **No destruction / break-apart sequence** — 2c is *per-breach combat* VFX; whole-ship destruction is separate future work.
- **No new toggle, no gravity.** Chunk count, velocities, and the three durations (`kDebrisLife`/`kVentLife`/`kRimLife`) are eyeball-tunable constants (like the 2b texture scale), defaulted sensibly.
