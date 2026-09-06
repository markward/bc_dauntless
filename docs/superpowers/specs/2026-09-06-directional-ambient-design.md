# Directional ambient — design

**Date:** 2026-09-06
**Status:** approved, not implemented

## Problem

Exterior ambient is a single flat constant. `DEFAULT_AMBIENT` is
`(0.1, 0.1, 0.1)` (`engine/host_loop.py`), scaled to 0.3× when the filmic
toggle is on, and `opaque.frag` adds it to every fragment identically —
independent of the surface normal, the camera, or anything else in the scene.

The consequence is that the un-keyed side of every hull is a constant. Where
the directional term falls off, shading stops varying entirely, so the hull
reads as a flat silhouette rather than a solid object. This is most obvious on
the large curved surfaces BC's hero ships are mostly made of: a Galaxy's
saucer underside, a Sovereign's flank away from the star.

## What this is NOT

An earlier framing of this work proposed projecting the real environment
(nebulae, backdrops, suns) into spherical harmonics and lighting hulls from
it. That was **rejected on physical grounds**: real nebulae are extraordinarily
faint — you could not read by one — so sourcing meaningful hull illumination
from nebula colour would be inventing light that is not there. The reference
frames that prompted this work show coloured shadow-side hulls because a VFX
artist added a fill light, not because the nebula behind them is illuminating
anything.

So this is deliberately an **artistic control**, not a simulation. The goal is
that hulls read as three-dimensional. The mechanism is chosen for how it
looks and for having no absurd failure mode, not for physical derivation.

Consequences of that decision, both intentional:

- No cubemap bake, no GPU→CPU readback, no SH projection.
- The `sh_probe.{h,cc}` prior art on `spike/ebridge-emissive-sh` is **not**
  used. It remains the right starting point if we ever do want a real
  environment probe.

## The direction

The gradient axis is the **luminance-weighted vector sum of every directional
light**, not the direction of light 0:

```
D = Σ  normalize(dir_to_light_i) · luminance(color_i)
```

Keying off light 0 would be wrong the moment a set authors two stars, and
`aggregate_for_renderer` collects up to `MAX_DIRECTIONALS` (4) per set, so
multi-star sets are a real case rather than a hypothetical one.

The weighted sum handles every case without special-casing:

| Scene | Result |
|---|---|
| One star | `D` points at it — the intuitive behaviour |
| Two stars, same side | `D` between them, stronger |
| Two stars, opposite sides | `D ≈ 0`, gradient vanishes, ambient goes flat |
| No directionals | `D = 0`, ambient flat — identical to today |

The opposed-stars case is **correct, not a fallback**: with light arriving
from both sides there is no shadow side to fill. `|D|` scales the effect on
its own, so the degenerate cases need no branches.

This is mathematically the L1 spherical-harmonic direction term, exposed as
direction-plus-strength because that form is tunable by eye and SH
coefficients are not.

## Evaluation: mean-preserving

In `opaque.frag`:

```glsl
float d = dot(n_shade, u_ambient_dir_ws);      // [-1, 1], mean 0 over a sphere
vec3 ambient = u_ambient_light * (1.0 + u_ambient_gradient * d);
```

**The mean-preserving property is load-bearing and must not be refactored
away.** Because `d` averages to zero over a sphere, the average ambient across
a closed hull is unchanged: this redistributes ambient rather than adding it.
Turning the feature on therefore cannot shift overall exposure or brightness,
which matters because every prior VFX change here has needed a calibration
pass and because the filmic chain downstream is sensitive to input level.

A formulation like `ambient + gradient * (0.5 + 0.5 * d)` would add light and
brighten the whole scene. Do not use it.

`u_ambient_gradient == 0` is the stock path and must be **byte-identical** to
today's output — the convention already used for shadows, specular, normal
maps and MSAA.

`u_ambient_gradient == 1` swings ambient from 0 at the antipode to 2× on the
light-facing side. Values above 1 clamp negative on the far side and are
rejected: the strength is clamped to [0, 1] host-side.

## Where the direction is computed

Host-side, **once per frame**, from `Lighting::directional_dir_ws[]` and
`directional_color[]` — not per pixel, and not per draw. The result is two
uniforms (`u_ambient_dir_ws`, `u_ambient_gradient`) set alongside
`u_ambient_light` wherever that is already set in `frame.cc`.

`|D|` is folded into the strength so opposed stars cancel without a branch;
`u_ambient_dir_ws` carries the normalized direction, or any value when the
strength is 0 (the term vanishes regardless).

The computation belongs in `renderer/lighting.h` beside
`glossiness_to_specular_power`, which is the existing home for pure lighting
math with a companion `lighting_test.cc`.

## Scope

**Exterior hulls only** — `opaque.frag`, which the static and skinned vertex
paths share.

**Bridges are excluded.** BC bridge NIFs carry baked vertex colour and **no
vertex normals at all** (all zero — see
`project_bc_interior_lighting_two_workflows`). A normal-keyed gradient is
meaningless where there are no normals, and `bridge.frag` has its own ambient
path. Do not wire this into it.

Not in scope: particles, beams, torpedoes, shields, dust — all additive or
emissive, none of them normal-shaded.

## Testing

**Pure unit tests** (`native/tests/renderer/lighting_test.cc`) on the
direction computation, which needs no GL:

- one star → `D` equals that light's direction, strength > 0
- two stars, same side → direction between them
- two stars, exactly opposed and equal → strength collapses to ~0
- two stars opposed but unequal → direction favours the brighter
- zero directionals → strength 0
- luminance weighting: a dim red star loses to a bright white one
- strength clamped to [0, 1]

**Frame tests** (`renderer_tests`):

- at strength > 0, a light-facing fragment is brighter than a shadow-side one
- at strength 0, output is pixel-identical to the pre-change renderer
- mean preservation: the average over opposing normals is unchanged from
  strength 0 — this is the property most likely to be broken by a later edit,
  so it gets its own assertion

## Open: exposure

Whether this ships behind a setting, folds under the existing "Realistic
Lighting" master, or is simply always on with a tuned constant is
**deliberately deferred** until it has been seen in motion. The strength knob
exists from the start so it can be calibrated; where the knob is surfaced —
if at all — is a decision better made with the thing on screen, following the
"calibrate up, then down" practice.

The implementation must therefore keep the strength reachable for tuning
without committing to a player-facing control.
