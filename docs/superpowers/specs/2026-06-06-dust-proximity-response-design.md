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

### 2 & 3. Density via overseed + GPU cull

Seed the instance buffer **once** at the 10× ceiling:
`kParticleCount × kMaxDensityMult = 512 × 10 = 5120` particles
(`generate_dust_particles` called with the overseeded count; the existing
seeding/wrap logic is unchanged). The GPU always processes ~5120 cheap
additive billboards — acceptable cost.

A per-particle **stable cull rank** in `[0, 1)` is derived in the vertex
shader as a hash of the particle's seed position (`a_particle.xyz`,
constant per instance, independent of the toroidal wrap). The shader
draws a particle only when `rank < u_density_fraction`, with a narrow
smoothstep fade just below the threshold so particles fade in/out rather
than pop as the fraction changes.

`u_density_fraction = multiplier / kMaxDensityMult`, where `multiplier`
∈ `[1, 10]`:

- Far from all bodies → `multiplier = 1` → `density_fraction = 0.1` →
  ~512 drawn (the original look reproduced as a random subset).
- Near a sun → up to `multiplier = 10` → all 5120 drawn (10×).
- Near a planet (no sun in range) → up to `multiplier = 5`.

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

### 4. Push away from suns (absolute 100 GU)

The **nearest sun** (greatest camera closeness) supplies `u_sun_pos` and
`u_sun_radius` to the vertex shader. For each particle at world position
`p`:

```
to_part   = p - u_sun_pos
dir       = normalize(to_part)
surf_dist = length(to_part) - u_sun_radius        // distance from sun surface
if (surf_dist < kSunPushRange) {                   // kSunPushRange = 100 GU
    falloff = 1 - clamp(surf_dist / kSunPushRange, 0, 1)
    p += dir * kSunPushMax * falloff               // kSunPushMax = 8 GU
}
```

Push is applied to the wrapped world position **before** the billboard
corner/smear offset. Distance is measured from the sun **surface** (per
approval). The "is a sun in range" gate is folded into the `u_sun_push`
uniform: it carries `kSunPushMax` when a sun is in range and `0`
otherwise, so the shader needs no separate flag (in the pseudocode above,
`kSunPushMax` is `u_sun_push`).

`kSunPushMax = 8 GU` sits inside the 40 GU volume radius so pushed
particles stay within the field. `kSunPushRange = 100 GU` is absolute
(not radius-relative), per the requirement.

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
| `u_density_fraction` | vert | cull threshold ∈ [0,1] |
| `u_sun_pos` | vert | nearest sun centre (world) |
| `u_sun_radius` | vert | nearest sun radius |
| `u_sun_push` | vert | push strength (GU), 0 when no sun in range |
| `u_sun_tint` | frag | orange-mix factor ∈ [0,1] |

(`u_sun_push` folds `kSunPushMax` and the "is a sun in range" gate into
one value so the shader needs no separate flag.)

### New tunable constants (`dust_pass.h`)

```
kMaxDensityMult  = 10     // overseed factor + sun density ceiling
kPlanetPeakMult  = 5
kInfluenceRadii  = 5.0f   // body-radius multiples for closeness ramp
kSunPushRange    = 100.0f // GU, absolute
kSunPushMax      = 8.0f   // GU
```

`kParticleCount` stays 512 as the *base* visible target; the seeded count
becomes `kParticleCount * kMaxDensityMult`.

## Testing

- `generate_dust_particles` already CPU-testable; add a test that the
  overseeded count produces the expected number of records.
- Factor the CPU proximity math into a **pure free function** (e.g.
  `compute_dust_influence(camera_pos, suns, planets) ->
  {density_fraction, sun_pos, sun_radius, sun_push, sun_tint}`) so it is
  unit-testable without a GL context. Cover:
  - planet ramp: 1× far, 5× at surface, monotonic in between;
  - sun ramp: 1× far, 10× at surface;
  - sun precedence: sun wins when both bodies are in range;
  - push falloff: 0 beyond 100 GU of the surface, max near the surface,
    `u_sun_push = 0` when no sun in range;
  - tint: 0 far, → 1 at a sun surface.
- The existing `wrap_local_for_test` regression guard stays.

## Out of scope

- Planet tint / planet push (per requirement, planets affect density
  only).
- Per-particle density or tint gradients across the field (global scalar
  is intentional).
- Dynamic re-seeding / buffer rebuilds for density (the overseed approach
  replaces `set_density`'s rebuild path for this feature; the existing
  `set_density` binding is left intact for any external callers).
