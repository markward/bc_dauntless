# Warp-nacelle glow dimming on subsystem disable — design

**Date:** 2026-06-10
**Status:** Approved (brainstorming) — pending implementation plan

## Problem

When a ship's warp engine subsystem is disabled or destroyed, the nacelle's
steady-state glow (the field-grille / bussard emissive band) keeps shining as if
nothing happened. We want that glow to dim out for the affected nacelle.

The warp engine is exposed as an `EngineProperty` hardpoint (`EP_WARP`) with a
**single body-space point** (`GetPosition()`) and a **uniform radius**
(`GetRadius()`). Galaxy, for example, has two: `PortWarp` at `(-1.3, -2.1, -0.06)`
and `StarWarp`, each `SetRadius(1.2)` (`sdk/Build/scripts/ships/Hardpoints/Galaxy.py:907-918`).
A nacelle, however, is a long fore/aft **tube**, not a sphere. So we cannot just
dim a sphere at the hardpoint — we must discover how far the glowing tube extends
forward and backward from that point and dim that whole section.

## Key insight: dim the glow term only

The fragment shader adds a per-material **glow map** on top of the lit hull
(`u_glow_map`, `native/src/renderer/shaders/opaque.frag:242-254`). On non-glowing
hull, `glow.a ≈ 0`. If our dimming multiplies **only the glow term** (never the
base lit color), then any non-glowing geometry that happens to fall inside our
region is left untouched. This makes the spatial region forgiving: an over-sized
capsule is visually harmless except where actual glow texels live. It is why a
spatial approach beats trying to isolate a "nacelle node" (BC bakes nacelle glow
into the whole-hull glow texture; there is usually no separate nacelle geometry
node to target).

## Approach (decided)

Three layers: **detect** the tube extent once at load, **trigger** the dim factor
each frame from live subsystem state, **render** by attenuating the glow term in a
body-space capsule.

### 1. Detection — load/construction-time, one-shot, cached

Vertex-extent along the ship-forward axis. Chosen over (a) a pure formula and
(b) face-normal "cap" detection because it is the simplest method that is robust
to rounded, angular, and hull-integrated nacelle caps — it never needs a clean
cap to exist, only nearby geometry.

Algorithm, per `EP_WARP` engine:

1. Python reads the engine's `GetPosition()` (body-space `center`) and
   `GetRadius()` (`radius`) from the ship's hardpoints at construction.
2. Python calls a new C++ host binding
   `compute_nacelle_region(instance_id, center, radius)`.
3. C++ reuses the existing body-space node-walk (`native/src/renderer/aabb.cc:25-52`
   — composes node transforms, pulls every retained CPU vertex into body space;
   ship models keep CPU data, `host_bindings.cc:184-187`). It keeps vertices whose
   **lateral** distance (perpendicular to the ship-forward axis through `center`)
   is `<= radius * 1.25`. The 1.25 widens the cross-section to catch the full
   width/height of the nacelle.
4. Of the kept vertices, take `min`/`max` of the projection onto the ship-forward
   axis relative to `center`. That gives `aft` (negative) and `fore` (positive)
   extents.
5. The region `(center, radius*1.25, aft, fore)` is stored against the instance,
   indexed per engine.

**Fallback:** if too few vertices are captured (degenerate), substitute the
formula `aft = -2.5*radius`, `fore = +2.5*radius` so a region always exists.

**Axis assumption:** projection is onto **ship-forward (model +Y)**, correct for
the overwhelming majority of fore/aft nacelles. A PCA-discovered axis (covariance
of the captured cluster + 3×3 eigensolve) is a deliberately deferred upgrade for
angled nacelles; same cost class, ~20 extra lines, added only if a specific ship
looks wrong. Out of scope for the first cut.

**Coordinate frame note (verify during implementation):** `EngineProperty`
positions and NIF mesh vertices are both pre-instance-scale model/body units, and
the shader reconstructs `p_body` in that same frame (the decal system already
relies on this). Confirm no instance-scale factor needs to be applied to the
region before it reaches the shader.

### 2. Trigger — per-frame, Python

Each frame, for each warp engine, the engine reads
`warp_sub.IsDisabled() or warp_sub.IsDestroyed()`
(`engine/appc/subsystems.py:378`, `:982` — both derive from live condition vs
`DisabledPercentage * MaxCondition`). It drives a per-region `dim_factor`:

- **Target** `1.0` (full glow) when healthy, `~0.08` (faint residual) when
  disabled/destroyed.
- **Transition: "flicker then die."** On the disable edge, run a brief electrical
  stutter (~0.4 s) reusing the `stutter()` shaping already in
  `opaque.frag:69`, then settle to the dark target. On repair, fade back up
  smoothly. The flicker is driven by a per-region disable timestamp passed to the
  shader so the stutter is evaluated GPU-side, consistent with how the Scorch
  glow-flicker decal already works.

Pushed to the renderer via `set_nacelle_dim(instance_id, region_index, target,
disable_time)`. Re-enable is automatic because the trigger reads live condition
each frame.

### 3. Render — opaque pass + shader

The opaque pass uploads active regions as uniform arrays, mirroring the decal
upload (`native/src/renderer/frame.cc`):

- `u_nacelle_count` (int)
- per region, packed into `vec4`s: `center.xyz + radius`, `axis.xyz + aft`,
  `fore + dim_target + disable_time + (pad)`.

The fragment shader (which already reconstructs `p_body`) tests each region as a
capsule: lateral distance to the axis `<= radius` **and** axial projection within
`[aft, fore]`. Inside, it computes the live dim multiplier from `dim_target` and
the flicker shaping at `disable_time`, and multiplies the **glow term only**
(`glow.rgb * glow.a`) by it. Base lit color, specular, rim, and decal emissive are
untouched.

## Production safety

- Gated exactly like the decal system: `u_nacelle_count == 0` → the shader loop
  never executes → the render path is **byte-identical** to today. Ships with no
  warp engines, or with the feature disabled, render unchanged.
- **No save/load state.** Regions are recomputed from hardpoints at construction
  on every load; `dim_factor` re-derives from live subsystem condition. Nothing
  to serialize.

## Components and boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `compute_nacelle_region` (C++ binding) | One-shot body-space vertex walk → capsule extent | `aabb.cc` walk, retained CPU mesh data |
| `set_nacelle_dim` (C++ binding) | Push per-region dim target + disable time | scenegraph instance state |
| Nacelle-region store (C++/scenegraph) | Hold per-instance capsule list + live dim state | the two bindings |
| Opaque-pass uniform upload (C++) | Marshal active regions into shader uniforms | nacelle-region store |
| `opaque.frag` capsule attenuation (GLSL) | Dim glow term inside capsules; flicker shaping | `p_body`, `stutter()` |
| Python warp-glow driver (`engine/appc`) | Read `EP_WARP` hardpoints at construction; per-frame `IsDisabled` → dim target | subsystems API, the bindings |

## Testing

- **Detection unit test (C++):** synthetic model with a known tube; assert
  `compute_nacelle_region` returns the expected `aft`/`fore` within tolerance;
  assert the degenerate fallback fires and returns the formula extents.
- **Trigger unit test (Python):** drive a `WarpEngineSubsystem` through
  healthy → disabled → repaired; assert the pushed dim target and disable
  timestamp follow `IsDisabled()`/`IsDestroyed()`.
- **Render safety:** assert `u_nacelle_count == 0` produces an unchanged frame
  (no nacelle uniforms bound), preserving the byte-identical-production guarantee.
- **Visual confirmation:** load a Galaxy, disable one warp engine, confirm only
  that nacelle's glow flickers and dims while the other stays lit. Use focused
  test subsets only — never the full pytest suite (OOMs the host).

## Deferred / out of scope

- PCA-discovered tube axis for angled nacelles (first cut assumes ship-forward).
- Glow-texel-aware capture (sampling glow-texture alpha per vertex) to exclude
  glowing hull sharing the nacelle's column — only needed if forward hull glow
  bleeds into a region in practice.
- Any animated warp-sequence interaction (this design covers steady-state nacelle
  glow only).
