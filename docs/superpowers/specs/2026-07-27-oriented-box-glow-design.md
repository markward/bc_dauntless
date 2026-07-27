# Oriented Box Glow Regions — Design

**Date:** 2026-07-27
**Status:** Draft for review
**Motivation:** The SPV Rotate tool only works on Cylinder light volumes, because a BC Box glow region is defined by **position + scale only** — it is always body-axis-aligned, with no orientation to rotate, store, or render. This feature gives Box glow regions an **orientation** (a Dauntless extension to the glow schema) so the Rotate tool can tilt them, persisted to the machine-owned override and rendered tilted by the glow shader.

**Builds on:** the real Box glow (`docs/engine/damagetool-and-hull-damage-gaps.md` Gap-2 lineage, `native/src/renderer/glow_region.cc` + `opaque.frag`'s `u_glow_region_e`), the SPV Rotate tool (`docs/superpowers/specs/2026-07-27-spv-rotate-tool-design.md`), and the light-volume override path (`region_spec_to_calls` → `set_region` → `hardpoint_overrides.py`).

## Goal

A Box light volume can carry a 3-DOF orientation. The Rotate tool rotates it (rings + degrees panel), the glow shader draws the box tilted, the SPV wireframe shows it tilted, and the orientation persists in the override. **Existing box overrides (no orientation) render byte-identically** (default = axis-aligned).

Developer-facing for editing; the render path is production (any ship with an oriented box glow).

## Key decisions

1. **Orientation representation: a (forward, up) unit-vector basis** (right = forward × up derived), body-frame. Default `forward = (0, 1, 0)`, `up = (0, 0, 1)` — the current axis-aligned box, so existing boxes are unchanged.
   - Gimbal-free (unlike Euler), composes correctly under the Rotate tool's incremental ring rotations (rotate both vectors with the existing `rotate_about_axis`), and mirrors BC's `SetOrientation(forward, up)` idiom.
2. **Persisted via a new indexed setter `SetGlowRegionOrientation(index, fx, fy, fz, ux, uy, uz)`** — a Dauntless extension (BC has no box-orientation setter; the override file is machine-owned and ours to extend). Read back like the other multi-arg `SetGlowRegion*` setters.
3. **Rotate becomes shape-aware**: Cylinder → rotate the `axis` (as today); **Box → rotate the (forward, up) basis**; Sphere → still inert (rotationally symmetric). The panel is unchanged (X/Y/Z degree accumulators, display-only).
4. **Shader orientation via two new uniforms** (`u_glow_region_f` = forward, `u_glow_region_g` = up); the box inside-test rotates the sample into the box's local frame before the extent test. Identity basis ⇒ no-op ⇒ existing boxes byte-identical.

## Background facts (verified)

- Shader `opaque.frag`: `u_glow_region_a..e[MAX_GLOW_REGIONS]` (5 vec4/region). Box: `e = (shape_flag, half_extent.xyz)`; `glow_region_mult` tests `abs(p_body − center) > half_extents` in **body space** (axis-aligned). `a = (center.xyz, radius)`.
- `native/src/renderer/glow_region.cc`: `GlowRegion` struct + `add_sphere_region`/`add_box_region`/`compute_capsule_region`; uploaded per-frame (`frame.cc`) into the `u_glow_region_*` arrays.
- Box region spec (Python): `{"shape":"Box", "position":(x,y,z), "scale":(sx,sy,sz)}`. `region_spec_to_calls` emits `SetGlowRegionShape/Position/Scale`. `resolve_baked_region` box → `("box", center, half_extents)`. `baked_glow_regions` reads the `GlowRegion*` setter args from the property data-bag via `read_indexed_setter_args`.
- The SPV box wireframe (`glow_region_overlay._box(center, ex, ey, ez)`) already takes **three arbitrary edge vectors** — currently the body axes × half-extents, rotated by ship R. It can draw an oriented box unchanged; only the edge-vector computation changes.
- Rotate tool: `_rotate_target()` (cylinder-only), `_rotate_axis`/`_apply_ring_drag_angle` rotate the `axis` vector via `rotate_about_axis`, stored in `_pending_light[i]["axis"]`; Save routes `_pending_light` via `region_spec_to_calls` → `set_region`.

## Components

### A. Glow-region property: the orientation setter (engine)

- Add `SetGlowRegionOrientation(index, fx, fy, fz, ux, uy, uz)` to the engine's glow-region-bearing property (the class the hardpoint calls `SetGlowRegion*` on; same place `SetGlowRegionScale` lives). It records into the property data-bag like the other indexed setters (so `read_indexed_setter_args(prop, "GlowRegionOrientation", i)` reads it back).
- `engine/appc/subsystem_glow.py`:
  - `baked_glow_regions` box entry gains `"orientation"`: `read_indexed_setter_args(prop, "GlowRegionOrientation", i)` → `(forward3, up3)` or `None` (absent ⇒ default identity).
  - `resolve_baked_region` box branch returns the orientation (forward, up) alongside center + half_extents — default identity when absent.

### B. Region spec + writer (Python)

- Box spec gains `"orientation"`: `((fx,fy,fz), (ux,uy,uz))`, default identity. Flows through `_light_region_spec`, `_light_annotation`, `set_light`, `set_region`, `resolve_baked_region` — same "baked-shaped" discipline as the other fields.
- `region_spec_to_calls` box branch appends `("SetGlowRegionOrientation", (index, fx,fy,fz, ux,uy,uz))` **only when the orientation is non-identity** (so unrotated boxes emit exactly as today — no churn to existing overrides).
- The override writer (`hardpoint_override_writer.py`) handles the 7-arg indexed setter like `SetGlowRegionScale` (keyed by index; multi-arg read-back). Add a round-trip test.

### C. Rotate tool: box orientation editing (Python)

- `_rotate_target()`: accept a light whose effective shape is **Box** as well as Cylinder (Sphere still None).
- Shape-aware rotate application:
  - Cylinder → rotate `axis` (unchanged).
  - Box → rotate BOTH `forward` and `up` about the ring/nudge body axis via `rotate_about_axis`, storing the new basis in `_pending_light[i]["orientation"]`. Re-orthonormalize (up ← up − (up·f)f, normalize; right = f×u) to keep the basis clean after repeated rotations.
- `rotate_copy`/`rotate_paste` carry the orientation for a box (kind = "box_orientation") vs the axis for a cylinder (kind = "cylinder_axis") — kind-matched paste. `rotate_mirror` for a box reflects the basis across the ship X=0 plane (negate the X component of forward + up, re-orthonormalize, preserve handedness) — matching the cylinder's X-flip intent.
- The panel (`rotate_values`) is unchanged (X/Y/Z accumulators). `_rotate_accum` stays display-only for both shapes.

### D. Shader: oriented box inside-test (native)

- `opaque.frag`: add `uniform vec4 u_glow_region_f[MAX_GLOW_REGIONS];` (forward.xyz) and `u_glow_region_g[]` (up.xyz). For a **box** region, build `R = mat3(right, forward, up)` (columns; right = normalize(cross(forward, up)); forward/up normalized), transform the sample into box-local `d = transpose(R) * (p_body − center)`, then test `abs(d) > half_extents`. When forward/up are the default basis (or zero ⇒ treat as identity), `R = I` and the test is identical to today ⇒ **byte-identical for existing boxes**. Cylinder/sphere branches untouched.
- Uniform budget: +2 vec4/region (5 → 7). Confirm against `MAX_GLOW_REGIONS` and the platform min-uniform floor; glow regions are few, so this is expected to fit. (If it doesn't, fall back to a single quaternion vec4 `u_glow_region_f`.)

### E. `GlowRegion` + upload + primitive (native)

- `GlowRegion` struct gains `glm::vec3 forward{0,1,0}; glm::vec3 up{0,0,1};` (identity default).
- `add_box_region(center, half_extents, forward, up)` sets them; the existing 2-arg call sites default to identity.
- `frame.cc` uploads `forward`/`up` into `u_glow_region_f`/`_g` for every region (cylinder/sphere just carry the identity default, unused by their branches).
- The Python→native bridge that pushes glow regions (the SPV live glow + the ship glow controller path) carries the orientation for box regions.

### F. SPV wireframe: oriented box (Python)

- `glow_region_overlay`: for a box, compute the three edge vectors from the box orientation basis — `ex = shipR · (R · (half.x, 0, 0))`, `ey = shipR · (R · (0, half.y, 0))`, `ez = shipR · (R · (0, 0, half.z))` — where R is built from (forward, up). `_box` already accepts arbitrary ex/ey/ez, so the wireframe tilts with no `DebugBox` change. Identity orientation ⇒ current body-aligned wireframe.

## Data flow (rotate a box glow)

```
Rotate tool + Box light selected -> ring drag / nudge
  panel: rotate forward+up about body axis k (rotate_about_axis), re-orthonormalize
  -> _pending_light[i]["orientation"] = (forward, up)
  live: SPV wireframe tilts (oriented edge vectors); if the live glow is pushed, shader tilts too
Save -> region_spec_to_calls(0, spec) appends SetGlowRegionOrientation(0, f.., u..)
     -> set_region -> hardpoint_overrides.py
Reload / any ship with an oriented box -> baked_glow_regions reads orientation
     -> GlowRegion.forward/up -> u_glow_region_f/g -> shader draws the box tilted
```

## Edge cases / compatibility

- **Existing boxes (no orientation)**: `read_indexed_setter_args` returns None ⇒ default identity ⇒ shader `R = I` ⇒ byte-identical render; `region_spec_to_calls` emits no `SetGlowRegionOrientation` ⇒ no override churn.
- **Cylinder/Sphere unaffected**: their shader branches ignore forward/up; Rotate on a cylinder still edits `axis`; Sphere still inert.
- **Basis drift**: re-orthonormalize on every rotate op so repeated ring drags can't skew the basis.
- **Mirror handedness**: negating X of forward+up flips handedness; re-derive right = f×u so the box stays a proper (non-mirrored) rotation.
- **Uniform limit**: if +2 vec4/region overflows, use a single quaternion uniform instead (noted in Component D).

## Testing strategy

- **Property/reader**: `SetGlowRegionOrientation` records + `read_indexed_setter_args` reads back (forward, up); absent ⇒ None.
- **Writer round-trip**: a box override with `SetGlowRegionOrientation` survives `emit(read_models(...))`; an identity/absent orientation emits no orientation call.
- **Region spec**: `region_spec_to_calls` box appends the orientation call only when non-identity; `resolve_baked_region` box returns the basis; default identity.
- **Rotate model (pytest)**: `_rotate_target()` accepts a Box light; a nudge/drag rotates forward+up about the named axis (assert the rotated, re-orthonormalized basis); Mirror reflects X + keeps right-handed; Copy/Paste kind-matched (box_orientation vs cylinder_axis); Sphere still inert.
- **Wireframe (pytest)**: `glow_region_overlay` box edge vectors reflect the orientation (a 90° box orientation swaps the expected edges); identity ⇒ current vectors.
- **Native (host test)**: `add_box_region` accepts forward/up; a box region with identity orientation uploads/renders unchanged (production byte-identical); the shader compiles with the new uniforms.
- **Shader byte-identical**: an existing baked box (no orientation) renders the same as before the change (guard via the existing box-glow host/frame tests).

## Rollout

Continue on `feat/spv-gizmo-tools` (or a fresh branch off it), task-by-task via subagent-driven-development, gated by `scripts/check_tests.sh`. Merge is Mark's call after an in-game pass. Never pushed without Mark's say-so.

## Open questions for review

1. **Orientation storage** — forward+up basis (this design) vs a single quaternion (`SetGlowRegionOrientation(index, qx,qy,qz,qw)`, 1 uniform). Basis is more readable + matches BC's `SetOrientation`; quaternion is 1 uniform vs 2 and never needs re-orthonormalization. Preference?
2. **Scope of the render path** — do you want oriented box glow to drive the **live in-scene glow** immediately (push orientation through the ship glow controller), or is the SPV wireframe + persisted-then-reloaded render enough for v1 (matching how radius/shape edits already only reach the live template on reload)?
