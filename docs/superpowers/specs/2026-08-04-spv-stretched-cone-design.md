# Stretched (Elliptical, Oriented) Cone Emitter — Design

**Date:** 2026-08-04
**Status:** Approved (design); implementation pending
**Branch:** `feat/spv-stretched-cone`

**Motivation:** A **strip** light emitter (capsule) radiates omnidirectionally
around its segment, so it bleeds through/around hull geometry — you can't make it
look like light beaming out of a specific slit. A **cone** is directional, so a
*stretched* cone — one with an elliptical, rollable cross-section — gives a slit
beam that projects forward and doesn't wrap around the hull, at a tiny fraction of
the cost of real shadow maps (which were rejected: only the sun has a shadow map
today, and per-light shadow passes are too expensive). This is the agreed cheap,
shadow-free answer to "beam light out of a specific piece of geometry."

**Builds on:** the subsystem light-emitter feature ([[project-subsystem-light-emitters]],
merged `794f9cf9`) — the cone emitter kind, the forward dynamic-light path
(`DynamicLightDescriptor` / `opaque.frag` spot gate), the SPV emitter gizmo/scale/
rotate routing, the `DebugCone` wireframe, and the `SetLightEmitter*` persistence.
Reuses the **oriented-box-glow** orientation machinery ([[project-oriented-box-glow]]):
`SetGlowRegionOrientation`-style forward+up storage, `orthonormalize_basis`,
`rotate_about_axis`.

## Decisions (confirmed with Mark)

1. **Enhance the existing cone to elliptical** — no new emitter kind. A cone gains a
   second base radius; a round cone is the special case `radius_x == radius_y`. Every
   existing cone (e.g. the authored drydock cone) renders identically.
2. **Explicit roll via a full oriented frame** — the cone stores an `up` vector
   (aim/`axis` = forward). The Rotate tool rolls the slit (ring around the aim axis)
   and re-aims it (other rings), exactly like the oriented box glow.
3. **Defer the plane-gate** — ship the stretched cone alone. Its directionality already
   stops back-bleed for anything behind the aim; the front-of-mount plane clip is added
   later only if a wide cone still wraps around a curved hull.

## Non-goals

- No per-light shadow maps / real shadows (too expensive; the directional cone is the
  substitute).
- No plane-gate in this phase (deferred; documented above).
- No new emitter kind — this is the same "cone", generalized.
- No change to point / strip emitters, or to any non-cone dynamic light (torpedo glow).

## Data model

The cone emitter spec (`engine/appc/light_emitters.py` spec dict) gains two fields,
both with backward-compatible defaults:

| field | meaning | default (legacy/circular) |
|---|---|---|
| `radius` (existing) | base radius along the cone's **right** axis (= `radius_x`) | unchanged |
| `radius_y` (NEW) | base radius along the cone's **up** axis | `= radius` → circular |
| `up` (NEW, 3-tuple) | orientation up-vector; forward = normalized `axis` | derived perpendicular to `axis` (Gram-Schmidt vs world-up, fallback world-X — the same rule `DebugCone`/the renderer already use) |

The cone's oriented frame: `forward = normalize(axis)`, `up = normalize(up)`,
`right = normalize(cross(forward, up))`, then re-orthonormalize `up = cross(right, forward)`
(reuse `orthonormalize_basis`). `radius_x` maps to `right`, `radius_y` to `up`.

Half-angles are still **derived**, now two of them: `tₓ = radius_x/length`,
`t_y = radius_y/length` (tangents of the half-angles). Circular cone ⇒ `radius_y == radius`
⇒ `tₓ == t_y`.

## Renderer

### `DynamicLightDescriptor` (`native/src/renderer/include/renderer/frame.h`)

Add `glm::vec3 up{0,1,0}` and repurpose the existing cone field so the shader gets both
tangents + the frame. Concretely:
- `direction` (existing) = forward (world, unit).
- `cos_half_angle` (existing float, `< 0` sentinel = **not a cone**) is **repurposed to carry the major tangent `tₓ`** (`>= 0` for cones, `-1` for non-cone). *(Rename to `spot_tan_x` for clarity; the `< 0` sentinel semantics are preserved.)*
- NEW `up` (world, unit) + NEW `spot_tan_y` (float, minor tangent `t_y`).

Uniform upload (`frame.cc`, alongside the existing `u_dyn_light_dir`): add
`u_dyn_light_up[i] = vec4(up.xyz, spot_tan_y)`; `u_dyn_light_dir[i].w` = `spot_tan_x`
(or `-1`).

### Shader elliptical spot test (`opaque.frag`, dynamic-light loop)

Replace the circular cosine test with the elliptical tangent test, guarded by the same
sentinel so non-cone lights are byte-identical:

```glsl
float tx = u_dyn_light_dir[i].w;          // major tangent, or < 0 = not a cone
float spot = 1.0;
if (tx >= 0.0) {
    vec3  fwd = normalize(u_dyn_light_dir[i].xyz);
    vec3  upv = normalize(u_dyn_light_up[i].xyz);
    vec3  rgt = cross(fwd, upv);
    // guard degenerate up (parallel to fwd) — mirror DebugCone's fallback
    if (dot(rgt,rgt) > 1e-6) {
        rgt = normalize(rgt); upv = cross(rgt, fwd);
        float ty = u_dyn_light_up[i].w;
        vec3  dld = normalize(-L);         // light -> fragment
        float fz = dot(dld, fwd);
        if (fz > 1e-4) {
            float ex = dot(dld, rgt) / (fz * tx);
            float ey = dot(dld, upv) / (fz * ty);
            float e  = ex*ex + ey*ey;      // <=1 inside the elliptical cone
            spot = 1.0 - smoothstep(1.0 - kPenum, 1.0, e);
        } else {
            spot = 0.0;                    // behind the aim
        }
    }
}
att *= spot;
```

- `tx < 0` (point/strip) ⇒ `spot` stays `1.0` ⇒ **byte-identical** to today, and count==0
  frames untouched.
- Circular cone (`tx == ty`) is the special case — a round beam. Existing authored cones
  render with the same half-angle boundary (`tan = radius/length`); only the falloff
  *formulation* changes from cosine to tangent (still a cone visual — acceptable; the
  byte-identity guarantee is for **non-cone** lights, not for the cone's own look).
- `kPenum` = a small fixed cos-/e-space softness (reuse today's penumbra intent).

### `set_dynamic_lights` binding (`host_bindings.cc`)

Accept optional dict keys `up` (3-tuple) and `spot_tan_x`/`spot_tan_y` (or keep
`cos_half_angle` as the input name and convert — the producer will send tangents).
Defaults keep non-cone callers (torpedoes) unchanged.

### `DebugCone` wireframe (`debug_volume_pass.{h,cc}`)

`DebugCone` gains `radius_y` + `up` so the overlay draws the actual elliptical, rolled
beam: the render matrix uses columns `right·radius_x`, `up·radius_y`, `forward·length`
(instead of a uniform-radius circular base). A circular cone (`radius_y == radius_x`,
derived up) draws exactly as today. Keep the existing zero-axis NaN guard.

## SPV authoring

### Scale tool (`ship_property_viewer_panel.py`)

The cone's scale kind becomes **3-field**: `Radius X / Radius Y / Length`
(`_scale_kind_and_fields` cone arm → e.g. `"radius_xy_length"`). `_set_scale_field`
writes `radius` (X), `radius_y` (Y), or `length`. `_begin_scale_drag` maps each gizmo
handle to a field by alignment with the cone's **oriented** frame: the handle along
`forward` → Length; the handle along `right` → Radius X; the handle along `up` → Radius Y.
(Point stays radius-only; strip stays radius+length.)

### Rotate tool

The cone becomes **oriented** (forward + up), like the box: `_apply_ring_drag_angle`'s
cone branch rotates BOTH `axis`(forward) and `up` via `rotate_about_axis`, then
`orthonormalize_basis` — instead of the strip's single-axis rotation. Rolling the ring
around the cone's own aim axis rolls the slit; the other rings re-aim it. Strip keeps its
single-axis rotate. Copy/Paste/Mirror: the cone's rotate clipboard carries the full
orientation (like `box_orientation`) so it can be mirrored (negate X of forward+up) and
pasted onto another cone; strip/cylinder-axis clipboards stay `cylinder_axis`.

### Value panels + overlay

Scale value panel lists Radius X / Radius Y / Length for a cone. The wireframe overlay
(`build_emitter_overlay` cone branch) passes `radius_y` + world-space `up` to
`set_debug_cones` so the drawn beam matches. Nudge/Copy/Paste/Mirror all continue to work.

## Persistence

Two new `SetLightEmitter*` setters (recorded via the property data-bag, same mechanism as
the rest of the family): `SetLightEmitterRadiusY(j, ry)` and
`SetLightEmitterUp(j, ux, uy, uz)`. `emitter_spec_to_calls` emits them **for cones only**,
and **only when non-default** (radius_y != radius, or up != the derived default) to keep
`hardpoint_overrides.py` clean. `baked_emitters` reads them back with the circular/derived
defaults, so every existing saved cone loads byte-identically. The
`emitter_spec_to_struct` cone branch outputs `up` + `spot_tan_x`/`spot_tan_y` for the
producer/renderer.

## Data flow

```
SPV: scale perp handles -> radius_x / radius_y ; rotate rings -> forward/up (roll+aim)
  -> _pending_emitter[i] (whole-list restage)  -> Save
  -> emitter_spec_to_calls -> SetLightEmitterRadiusY/Up -> hardpoint_overrides.py
Reload: baked_emitters (defaults for circular/legacy) -> per-ship cache
Runtime: emitter_spec_to_struct -> {direction, up, spot_tan_x, spot_tan_y, ...}
  -> set_dynamic_lights -> u_dyn_light_dir/up -> opaque.frag elliptical spot test
Overlay: build_emitter_overlay -> set_debug_cones (radius_x, radius_y, up) -> DebugCone
```

## Edge cases

- **Legacy cone** (only `radius`, no `radius_y`/`up`): reader defaults `radius_y = radius`,
  `up` = derived ⇒ circular, identical render.
- **Degenerate up** (parallel to forward): shader + `DebugCone` fall back (guard on
  `cross` magnitude), same rule as the existing `DebugCone`.
- **`length == 0`**: tangents guard `max(length, 1e-6)` (as the current cone does).
- **Point/strip + all non-cone lights**: `spot_tan_x < 0` sentinel ⇒ `spot = 1.0` ⇒
  byte-identical; count==0 frames unchanged.
- **Circular cone**: `radius_y == radius`, `tx == ty` ⇒ round beam (same half-angle
  boundary as today).

## Testing strategy

- **ctest FrameTest:** an elliptical cone (`radius_x != radius_y`) lights a wide-but-narrow
  region — a fragment inside the major axis but outside the minor is dark, proving the
  ellipse; plus the existing "point light `spot_tan_x = -1` is byte-identical" guard; plus
  a circular cone (`radius_x == radius_y`) still bounds a round region.
- **pytest:** spec round-trip (radius_y/up setters ↔ `baked_emitters` with legacy defaults);
  `emitter_spec_to_struct` cone outputs the two tangents + up; a legacy cone (no radius_y/up)
  loads circular; `emitter_spec_to_calls` omits the setters when default and emits when not.
- **pytest (panel):** cone scale is 3-field and each handle writes the right radius/length;
  cone rotate rotates forward+up (oriented) and re-orthonormalizes; a sibling emitter stays
  untouched (whole-list dense invariant); Copy/Paste/Mirror on a cone round-trips the
  orientation.
- Gate throughout: `scripts/check_tests.sh` (build + pytest + ctest vs `known_failures.txt`).

**Migration notes (repurposing `cos_half_angle` → tangent):** the existing cone
`FrameTest` (`native/tests/renderer/test_cone_light_frame.cc`) and
`light_emitters.emitter_spec_to_struct` both currently produce/consume
`cos_half_angle = cos(atan2(radius, length))`. When the field is repurposed to the
major tangent, BOTH must migrate in the same task that changes the shader/struct
(the FrameTest's cone setup switches to the tangent input; `emitter_spec_to_struct`
emits `spot_tan_x`/`spot_tan_y` instead of `cos_half_angle`). The `< 0` "not a cone"
sentinel is preserved, so the point/strip byte-identity tests are unaffected.

## Phasing (one spec → ~4 tasks)

- **A. Renderer** — `DynamicLightDescriptor` `up`/tangents, `frame.cc` upload, `opaque.frag`
  elliptical spot test (byte-identity guarded), `set_dynamic_lights` keys, elliptical
  `DebugCone`. (ctest)
- **B. Spec + persistence** — `radius_y`/`up` in the spec + defaults, `emitter_spec_to_struct`
  cone tangents/up, `SetLightEmitterRadiusY`/`SetLightEmitterUp` setters,
  `emitter_spec_to_calls` (cone-only, non-default), `baked_emitters` reader defaults. (pytest)
- **C. SPV scale + rotate** — cone 3-field scale (`radius_xy_length`), oriented cone rotate
  (forward+up), value panels, Copy/Paste/Mirror orientation for cones. (pytest)
- **D. Overlay + producer wiring** — `build_emitter_overlay` cone passes radius_y/up; the
  runtime producer feeds the tangents/up; end-to-end. (pytest)

## Rollout

Branch `feat/spv-stretched-cone` off `main`, task-by-task via subagent-driven-development,
gated by `scripts/check_tests.sh`. `hardpoint_overrides.py` is machine-owned — never staged
by subagents; the controller commits Mark's in-game saves separately (auto-keep policy).
Merge is Mark's call after an in-game pass. Never pushed without Mark's say-so.
