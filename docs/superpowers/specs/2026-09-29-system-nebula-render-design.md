# System-scale nebula rendering — a star-centred atmosphere (design)

**Date:** 2026-09-29
**Status:** design approved section by section (2026-09-29); awaiting review of
this written spec. Not implemented.
**Supersedes:** the developer-only nebula spike (`engine/systems/profile_render.py`,
plan `2026-09-28-radial-system-profile.md` Task 13) and `nebula_volumetric_pass`.
**Relates to:** `2026-09-23-radial-system-profile-design.md` (the `nebula` column
this draws), `2026-06-23-volumetric-nebulae-design.md` (the pass it replaces),
`2026-09-23-celestial-layer-design.md` (true-distance sun, 1.8M GU far plane)
**Area:** new `native/src/renderer/system_nebula_pass.{h,cc}` + shaders,
`native/src/host/host_bindings.cc`, `engine/host_loop.py`, `engine/systems/profile.py`,
`native/src/renderer/lens_flare_pass.cc`

## Why

Two live findings on the spike (Mark, 2026-09-28/29):

1. **The cloud glows instead of concealing.** The volumetric shader adds a
   constant self-glow (`u_self_glow` 0.25 × colour) plus isotropic scatter
   (× 1.2 from every directional light) at every sample. Net effect: an emitter.
   Wanted: a cloud that *veils a bright remnant* — forward-lit toward the star,
   dark elsewhere, with only a faint emissive floor.
2. **Nothing hides the sun from the thin outer system**, although a bank of cloud
   lies between you and it. The spike was a 3,000 GU sphere around the player;
   the shell at ~123,500 GU was never drawn from outside.

## The idea

The radial profile is spherically symmetric about the star, so this is the
**planet-atmosphere problem with the star at the centre**. Render it the way
atmospheres are rendered: a precomputed far-field lookup table for the
unbounded, smooth part, plus a short near-field march for structure.

## Look (approved)

- **Distant view: halfway between a veiled star and a visible bank.** The sun is
  dimmed and tinted, with a soft halo where the shell catches its light, and the
  sky carries broad lanes — large-scale structure, not fine texture — with the
  sun glimmering through thin parts.
- **Near view:** thin, forward-lit haze with lanes that parallax over tens of
  thousands of GU; BC's local clump stays locally dense.
- **Emissive floor:** a faint glow in the cloud's colour, never fully black.

## Architecture

**One pass for everything: `system_nebula_pass`.** It occupies the volumetric
pass's slot in `render_space_vfx` — after the sun and hulls, before bloom and the
HDR flare — so drawing over the sun veils its disc, bloom and HDR flare by
construction.

| setting (existing "volumetric nebula" toggle) | renders |
|---|---|
| on | `system_nebula_pass`: profile haze (mapped systems) + every local MetaNebula as a density bump (all sets, incl. Multi5/6) |
| off | BC's faithful `nebula_pass`, unchanged |

Ships **`--developer`-only** until Mark approves it live, then to production
behind the setting.

### Per system (on load, and when the profile changes)

Python pushes, through a new binding: the profile rows (`nebula` column and
distances), the cloud colour, the star's colour and radius, and the veil
coefficient `k_sys` (below). C++ builds the **far-field table** on the CPU
(GLSL 4.1 on this Mac has no compute shaders; a CPU build is also testable):

- 2D, **256 (radius) × 128 (μ)**, where radius is the start point's distance
  from the star (0 → the far plane, 1.8M GU, non-linear spacing concentrated
  where the profile has breakpoints) and μ is the cosine between the view
  direction and the outward radial.
- Two RGB channels: **transmittance** `T(r, μ)` from the start point along the
  ray to the far plane, and **inscatter** `S(r, μ)` — star light scattered toward
  the start point along that ray, plus the emissive floor.
- The last profile row persists outward to the far plane (the profile's own
  rule), so a ray through the floor integrates finitely.

### Per frame, per pixel

Quarter resolution with the existing depth-aware upsample and temporal
reprojection (history disabled while dashing or when the eye jumps, as today).

1. **Near field:** march from the eye to `min(scene depth, near range)`, near
   range 30,000 GU, ~64 steps growing geometrically with distance (fine near the
   eye for clumps and hulls, coarse far out). Accumulate premultiplied light
   and transmittance.
2. **Far field:** if the ray reaches the near range without hitting a hull, add
   `T_near × S(r_end, μ_end)` from the table and multiply transmittance by
   `T(r_end, μ_end)`. If a hull lies beyond the near range, use the standard
   finite-segment form: `T(a→b) = T(a)/T(b)`, `S(a→b) = S(a) − T(a→b)·S(b)`.
3. **Distant banks:** the far-field contribution is modulated by low-frequency
   noise in *view direction* (sky-anchored), so distant banks show structure
   without parallax — correct for features tens of thousands of GU away.

Output is premultiplied `(light, 1 − T)` blended `ONE, ONE_MINUS_SRC_ALPHA`
over the HDR target, as the volumetric pass does today.

### The sun and its flares

- Disc, bloom, HDR flare: veiled automatically by the draw order.
- **Billboard flare:** its visibility is a single CPU depth read that cannot see
  fog. It gains a brightness input set from Python each frame to the
  transmittance from the eye to the star. The eye→star line is radial, so this
  is exactly `exp(−k_sys · ∫ nebula(r) dr)` from the eye's radius down to the
  star's surface — the same numbers the table uses.

### Clumps

Each local MetaNebula becomes a density bump with its **own** colour, fbm dials
and seed (no more "first volume's dials for all"). The clump fbm must stay the
same function as `engine/appc/nebula_density.py`, which gameplay concealment
reads — a parity test pins it. Removing clumps from rendering later (Mark's
stated goal) is dropping this input, not a redesign; their gameplay side
(enter/exit, the one-off hit, concealment) is untouched.

## Look model (approved)

**Density** at a point `p`, radius `r` from the star:

```
σ(p) = k_sys · nebula(r) · lanes(p)  +  Σ clump_i(p)
```

- `lanes(p)`: low-frequency 3D noise, mean 1.0, feature size ~15,000 GU,
  world-anchored.
- Clumps keep BC-scale extinction (derived from their visibility, ~1/145 GU at
  Vesuvi 4), so the clump is locally thick while the haze is thin.

**The veil sets `k_sys`.** BC's visibility cannot be reused at system scale — at
145 GU the shell would hide the sun from everywhere beyond it. Instead `k_sys` is
solved per system so that **the star's transmittance seen from the system's
outermost region equals the veil dial** (default **0.15**: veiled, glimmering).
For Vesuvi (from Haven) this gives `k_sys ≈ 2 × 10⁻⁵ /GU`. Consequence: within a
thousand GU the haze is barely visible; it builds with distance.

**Lighting** per unit density:

- **Forward scatter** from the star's actual position, Henyey–Greenstein phase,
  `g = 0.6`; colour = star colour × cloud colour; the star's light at the sample
  is attenuated by the table's transmittance from the star to that point, so the
  shell's inner face glows and its far side is darker.
- **Emissive floor:** `0.03 × cloud colour × density` (today's self-glow: 0.25).

**Dials** — named constants, live-tunable under `--developer`: veil (0.15), lane
size (15,000 GU), lane contrast, forward bias `g` (0.6), emissive floor (0.03),
near range (30,000 GU).

## What is removed

- The spike now: `engine/systems/profile_render.py`, its host-loop hook and tests.
- `native/src/renderer/nebula_volumetric_pass.{h,cc}`, `shaders/nebula_volumetric.frag`
  (the upsample shader stays if the new pass reuses it) — only after Mark
  approves `SystemNebulaPass` live; until then production keeps the old pass
  and `--developer` selects between them via the volumetric-nebula setting.

## What must not change

- Gameplay concealment (the clump fbm parity above; the profile's `sensors`
  column is separate and unaffected).
- The faithful path with the setting off.
- Warp tunnel: nebula feeds stay empty while streaking.
- Production with the setting on but without `--developer`, until approval.

## Testing

- **Table build (C++):** matches closed-form integrals for a constant-density
  profile; transmittance is monotonic along a ray; the floor integrates to the
  far plane finitely.
- **Near + far = whole ray:** a CPU reference marcher over the full ray agrees
  with near-march + table within tolerance, including the finite-segment case —
  the join is the likeliest bug.
- **Veil calibration:** star transmittance from Vesuvi's outermost region equals
  the veil dial.
- **Flare transmittance (Python):** the radial integral is exact for the
  piecewise-linear profile.
- **Clump fbm parity** between the GLSL and `nebula_density.py`.
- **Headless GL smoke test** of the pass.
- **Live (Mark):** the veiled remnant from Haven; lanes while flying; the clump
  near Vesuvi 4; no white-out anywhere; frame cost via the CPU profiler scope
  `space.system_nebula` (GPU timing is dead on this Mac); the bridge viewscreen,
  which runs the same pass at 640×360.

## Unknowns to measure, not guess

- **Cost.** Quarter-res, ~64 steps is the same order as today's pass, but GPU
  timing is unavailable — judged by eye and CPU frame time.
- **Whether 30,000 GU of near field shows lanes well** at `k_sys ≈ 2e-5`; the
  near range and lane contrast are the dials if not.
- **The veil default.** 0.15 is a starting point for Mark to tune.
- **Clump vs haze seam** near Vesuvi 4, where BC-scale extinction meets system
  haze.
