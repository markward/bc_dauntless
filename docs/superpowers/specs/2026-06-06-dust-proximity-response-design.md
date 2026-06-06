# Dust VFX proximity response — design

**Date:** 2026-06-06
**Status:** Approved, pending implementation plan

## Goal

Make the camera-anchored space-dust VFX react to nearby celestial bodies:

1. **Brighter** overall (baseline boost, unconditional).
2. **Denser near planets** — up to 5× density as the camera approaches a planet.
3. **Denser near suns** — up to 10× density as the camera approaches a sun.
4. **Pushed outward** — dust particles displaced radially away from a sun
   when within 100 game units (GU) of the sun's surface (solar-wind look).
5. **Tinted orange** — particle colour warms toward orange as the camera
   approaches a sun.

All distances are in game units (GU). See `engine/units.py` —
1 GU = 175 m.

## Current state

- The dust pass renders entirely in C++:
  `native/src/renderer/dust_pass.cc`, shaders
  `native/src/renderer/shaders/dust.{vert,frag}`, header
  `native/src/renderer/include/renderer/dust_pass.h`.
- `DustPass::render(camera, dt, pipeline)` is fed only the camera + frame
  delta. Tunable constants live in `dust_pass.h`
  (`kParticleCount = 512`, `kVolumeRadius = 40`, brightness range, etc.).
- Particles are seeded once in a cube `[-R, R]³` and toroidally wrapped
  around the camera in the vertex shader; the fragment shader clips the
  visible set to the inscribed sphere. Per-particle `jitter` (w channel)
  drives size and brightness.
- **Suns** already reach the renderer: `g_suns`
  (`renderer::SunDescriptor { position, radius, ... }`) is rebuilt each
  frame by `_aggregate_suns()` in `engine/host_loop.py` →
  `r.set_suns(...)` → `set_suns` binding in
  `native/src/host/host_bindings.cc`.
- **Planets** do *not* reach the renderer today. They live Python-side
  (`engine/appc/planet.py`, `Planet` with `GetRadius()` /
  `GetWorldLocation()`), tracked by `ProximityManager`.

## Design

### Data flow

Planets must reach the dust pass, mirroring the existing sun path:

- New host binding `set_dust_planets(list[dict])` in `host_bindings.cc`,
  storing into a module-level `std::vector<glm::vec4> g_dust_planets`
  (xyz = world position, w = radius). Exposed Python-side as
  `renderer.set_dust_planets(...)`.
- New `_aggregate_planets()` in `host_loop.py`, mirroring
  `_aggregate_suns()`: walk the active set(s) for `Planet` objects with
  `radius > 0`, emit `{position: (x,y,z), radius: r}`. Called each frame
  next to `r.set_suns(suns)`.
- `DustPass::render(...)` signature extended to also receive the sun list
  (`const std::vector<renderer::SunDescriptor>&`) and the planet list
  (`const std::vector<glm::vec4>&`). `frame()` in `host_bindings.cc`
  passes `g_suns` and `g_dust_planets`.

All proximity logic lives inside the dust pass (single responsibility);
Python only supplies positions + radii.

### 1. Brightness (unconditional)

Raise the brightness constants in `dust_pass.h` by ~1.6×:
`kBrightnessMin 0.5 → 0.8`, `kBrightnessMax 1.0 → 1.6`. No new code
paths; purely a constant change wired through the existing
`u_brightness_min/max` uniforms.

### 2 & 3. Density via overseed + variable draw count

Seed the instance buffer **once** at the 10× ceiling:
`kParticleCount × kMaxDensityMult = 512 × 10 = 5120` particles
(`generate_dust_particles` called with the overseeded count; the existing
seeding/wrap logic is unchanged).

`generate_dust_particles` emits particles in **independent random order**
(each is an iid uniform sample), so the first `N` of the 5120 is itself a
uniform random subset of the field. Density is therefore controlled by
**varying the instance draw count per frame** — the `instancecount`
argument to `glDrawElementsInstanced` — with **no shader cull and no
extra uniform**. The buffer is seeded once; only the draw count changes.

`draw_count = clamp(round(kParticleCount × multiplier), 0, seeded_count)`,
where `multiplier` ∈ `[1, 10]`:

- Far from all bodies → `multiplier = 1` → 512 drawn (the original look,
  reproduced as a random subset).
- Near a sun → up to `multiplier = 10` → all 5120 drawn (10×).
- Near a planet (no sun in range) → up to `multiplier = 5`.

A single faint additive speck appearing/disappearing as `draw_count`
changes by ±1 per frame is imperceptible, so no fade ramp is needed. GPU
cost scales with the drawn count (512–5120 cheap additive billboards).

**Radius-relative closeness.** For each body with centre `c` and radius
`rad`, let `d = distance(camera, c)`. Closeness ramps from 1 at the
surface to 0 at `kInfluenceRadii × rad` (default `kInfluenceRadii = 5`):

```
closeness = 1 - smoothstep(rad, kInfluenceRadii * rad, d)   // 1 at/inside surface, 0 far
multiplier_body = 1 + closeness * (peak - 1)
```

`peak = 5` for planets, `peak = 10` for suns.

**Sun precedence.** Take the max closeness across suns and the max across
planets. If any sun is in range (sun closeness > 0), the sun-derived
multiplier is used and the planet multiplier is ignored; otherwise the
planet multiplier is used. (Matches the "the sun" combine rule — the sun
dominates when both apply.)

### 4. Push away from suns — animated solar-wind drift

> **Revised 2026-06-06 after in-game testing.** The original design used a
> static radial displacement gated to within 100 GU of the sun *surface*.
> That was a dead effect: BC sun radii are **1000–7000 GU**, so the camera
> only enters a 100 GU surface band by flying into the lethal corona — in
> normal flight the push never fired. And even when it did, a one-time
> constant offset of a uniform, camera-anchored, toroidally-wrapped dust
> field is imperceptible (no clearing, no motion). Replaced with an
> **animated outward drift** over the same radius-relative ramp as density
> and tint (which *were* visibly working).

The dust field already recycles seamlessly via the camera-relative
toroidal wrap in `dust.vert` — that is why flying through it reads as
motion. The drift reuses that exact mechanism: a time-accumulated outward
translation folded **inside** the wrap, so the whole local field streams
away from the sun and recycles with no pop and no fade.

- **Direction.** `compute_dust_influence` emits `sun_dir` = the unit vector
  from the nearest sun toward the camera (radially outward), or zero when
  no sun is in range. A *single* direction for the whole 40 GU dust volume
  is exact at sun scale (radii are thousands of GU, so the radial direction
  is constant across the field to <1°) and keeps the drift a clean
  translation that the wrap recycles perfectly. (A per-particle radial
  direction would make particles converge/diverge and break the wrap.)
- **Speed / ramp.** Drift speed = `kSunDriftSpeed` (GU/s) × `sun_tint`,
  where `sun_tint` is the nearest-sun closeness — the same radius-relative
  ramp (1 at the surface, 0 by `kInfluenceRadii × radius`) used by density
  and tint. So the drift ramps in over a reachable zone and is fastest near
  the surface.
- **Accumulation (CPU).** `DustPass` keeps `sun_drift_phase_` (GU), advanced
  each frame by `kSunDriftSpeed × sun_tint × dt` and wrapped to
  `[0, 2·kVolumeRadius)` for long-session precision (and gated by the same
  abnormal-`dt` guard the velocity streak uses). The per-frame
  `u_sun_drift = sun_dir × sun_drift_phase_` is sent to the shader.
- **Shader.** The wrap line becomes
  `local = mod(a_particle.xyz − u_camera_pos + u_sun_drift + R, 2R) − R`.
  When no sun is in range `u_sun_drift = 0`, reproducing the original
  behaviour exactly (no regression away from suns).

`kSunDriftSpeed = 25 GU/s` at the surface — a speck crosses the ~80 GU
field in a few seconds, reading as a steady solar-wind stream. Tunable.

### 5. Orange tint near suns

A single global scalar `u_sun_tint` = the nearest-sun **camera** closeness
(same radius-relative ramp as density, `[0, 1]`). The fragment shader
mixes the particle colour from white toward orange `#FF8030`
(`vec3(1.0, 0.502, 0.188)`):

```
vec3 tint = mix(vec3(1.0), vec3(1.0, 0.502, 0.188), u_sun_tint);
out_color = vec4(tex.rgb * v_brightness * tint, tex.a * fade);
```

Global (not per-particle) tint matches the "as we get closer" phrasing
and stays consistent with the global density ramp. Planets do not tint.

### Uniforms added

| Uniform | Stage | Meaning |
|---|---|---|
| `u_sun_drift` | vert | accumulated outward drift translation (GU), folded into the wrap; zero when no sun in range |
| `u_sun_tint` | frag | orange-mix factor ∈ [0,1] |

(Density needs no uniform — it is the per-frame `instancecount`. `u_sun_drift`
carries both direction and accumulated distance, and being zero off-sun also
serves as the "no sun in range" gate, so the shader needs no separate flag.)

### New tunable constants (`dust_pass.h`)

```
kMaxDensityMult  = 10     // overseed factor + sun density ceiling
kPlanetPeakMult  = 5
kInfluenceRadii  = 5.0f   // body-radius multiples for closeness ramp
kSunDriftSpeed   = 25.0f  // GU/s outward drift at the sun surface (closeness 1)
```

`kParticleCount` stays 512 as the *base* visible target; the seeded count
becomes `kParticleCount * kMaxDensityMult`.

## Testing

- `generate_dust_particles` already CPU-testable; add a test that the
  overseeded count produces the expected number of records.
- Factor the CPU proximity math into a **pure free function** (e.g.
  `compute_dust_influence(camera_pos, suns, planets) ->
  {density_mult, sun_dir, sun_tint}`) so it is unit-testable without a GL
  context. Cover:
  - planet ramp: 1× far, 5× at surface, monotonic in between;
  - sun ramp: 1× far, 10× at surface;
  - sun precedence: sun wins when both bodies are in range;
  - drift direction: `sun_dir` is the unit outward (sun → camera) vector
    when a sun is in range, zero when none is; planets never set it;
  - drift rate / tint: `sun_tint` is 1 at the surface, decreasing with
    distance, 0 beyond the influence zone.
- The animated drift itself (time accumulation + wrap fold) is visual and
  not unit-tested; the existing `wrap_local_for_test` regression guard
  stays as the wrap reference.

## Out of scope

- Planet tint / planet drift (per requirement, planets affect density
  only).
- Per-particle density or tint gradients across the field (global scalar
  is intentional).
- Dynamic re-seeding / buffer rebuilds for density (the overseed approach
  replaces `set_density`'s rebuild path for this feature; the existing
  `set_density` binding is left intact for any external callers).
