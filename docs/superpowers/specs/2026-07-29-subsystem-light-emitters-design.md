# Subsystem-Attached Light Emitters — Design

**Date:** 2026-07-29
**Status:** Approved (design); implementation pending
**Branch:** `feat/spv-light-emitters`

**Motivation:** Ships should feel alive. Today the engine has *emissive* glow
volumes (self-illumination on the hull) but only one runtime light that casts
onto neighbours: a point light per in-flight torpedo. This feature adds
**light emitters** — deferred-in-spirit but forward-rendered dynamic lights,
attached to subsystems, that cast diffuse + specular onto the surrounding hull
and **flicker / go offline with the parent subsystem's health**. Three types:
**point**, **strip** (segment), **cone** (spotlight). Authored in the Ship
Property Viewer (SPV) with the transform / scale / rotate tools and a colour
wheel, persisted to `hardpoint_overrides.py`, rendered live in-mission.

**Builds on:**
- The SPV gizmo suite (Transform / Scale / Rotate) and oriented-box-glow work
  (`docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md`,
  `2026-07-27-spv-{scale,rotate}-tool*`, `2026-07-*-oriented-box-glow*`).
- The light-volume-nodes redesign and Edit/Add-Light modal
  (`2026-07-26-spv-{edit-light-glow-region,light-volume-nodes}*`,
  `2026-07-28-spv-light-type-modal-design.md`).
- The subsystem-glow driver `engine/appc/subsystem_glow.py` (state model + impulse gain).
- The dynamic-light forward path (`native/src/renderer/frame.h`,
  `dynamic_lights.cc`, `opaque.frag`, `host_bindings.cc:set_dynamic_lights`).

## Approach (grounded in a renderer probe)

The engine is a **forward renderer** with a complete dynamic-light path already
wired end-to-end. The probe (see `native/src/renderer/`) confirmed:

- `DynamicLightDescriptor` (`frame.h:129`): `pos_a`, `pos_b` (world GU; a point
  light is the degenerate segment `pos_a == pos_b`), `color` (linear RGB,
  HDR-capable), `radius` (GU; attenuation reaches exactly 0 here), `intensity`.
- Host list cap `kMaxDynamicLightsPerFrame = 64` (`frame.h:136`); per-draw
  uniform-array cap `kMaxDynamicLightsPerDraw = 4` (`frame.h:137`, shader
  `MAX_DYN_LIGHTS = 4` at `opaque.frag:46`).
- CPU selection `select_dynamic_lights` — top-K by luminance×intensity×attenuation,
  per instance (`dynamic_lights.cc:40`), called from `frame.cc`.
- Upload: `u_dyn_light_a` (pos_a.xyz, radius), `u_dyn_light_b` (pos_b.xyz),
  `u_dyn_light_color` (color×intensity), `u_dyn_light_count` (`frame.cc:377`).
  Plain `glUniform` arrays — no UBO/SSBO.
- Shader (`opaque.frag:490–518`): closest point on segment → windowed
  inverse-square attenuation, then **diffuse AND Blinn-Phong specular** folded
  into `spec_acc`. Must bit-match `dynamic_light_attenuation` (`dynamic_lights.cc:18`).
- Host binding `set_dynamic_lights` (`host_bindings.cc:2234`) takes dicts with
  position, color, radius, intensity, optional `position_b`.
- Current producer: one point light per in-flight torpedo (`host_loop.py:882`);
  `frame.h:126` comment names "future: hardpoint-attached point/line lights."

**Therefore:** point and strip lights that cast diffuse + specular already work.
We **extend** this path; we do **not** build a deferred renderer. The only new
renderer work is the **cone/spot** type. Normal-mapping ("in the future") is a
separate, out-of-scope job (needs tangent attributes + TBN).

## Non-goals

- No deferred / G-buffer renderer, no normal maps, no screen-space lighting pass.
- No live lit preview inside the SPV (the ship is a translucent hologram there);
  authoring is geometric (wireframe + gizmos), real cast light is seen in-mission.
- No shadow casting from emitters.
- No new per-emitter health *curve*; we reuse the existing three-state glow model.

## Data model

An **emitter is an independent child node of a subsystem**: its own transform,
0..N per subsystem, never bound to a light volume (neither concept implies the
other). Health flicker/offline keys off the **parent subsystem**. Any subsystem
is emitter-capable (same as light volumes are now attachable to any subsystem).

The authored spec is stored in the **"baked shape" tuple form** already used by
volume specs, so it flows through the same seams (`region_spec_to_calls`, the
overlay resolver, the writer). Fields:

| field | point | strip | cone | notes |
|---|---|---|---|---|
| `kind` | `"point"` | `"strip"` | `"cone"` | string discriminant |
| `position` (3-tuple, GU) | centre | midpoint | apex | transform-tool target |
| `axis` (3-tuple, unit) | — (ignored) | segment axis | cone direction | rotate-tool target |
| `length` (GU) | — (0) | segment length | range | scale axial handle |
| `radius` (GU) | range | tube radius | base radius | scale perp handle |
| `color` (linear RGB 3-tuple) | ✓ | ✓ | ✓ | from hue/sat wheel |
| `intensity` (float, HDR) | ✓ | ✓ | ✓ | separate slider, ~0–8 |

- **Point** = degenerate segment; `axis`/`length` ignored; `radius` is the light
  range. Rotate is inert (as sphere is).
- **Strip** = segment from `position ± axis·(length/2)`; `radius` is the tube
  radius. Maps to the cylinder tooling exactly.
- **Cone** = apex at `position`, pointing along `axis`, reaching `length`, with
  base radius `radius`. **Half-angle is derived**: `atan(radius / length)` —
  never stored — so the Scale tool's perpendicular handles set the angle
  geometrically and the axial handle sets range.

At the producer boundary a strip/cone spec converts to the renderer struct:
`pos_a = position − axis·(length/2)`, `pos_b = position + axis·(length/2)` for a
strip; for a cone `pos_a = pos_b = position` (apex) with `direction = axis` and
`cos_half_angle = cos(atan(radius/length))`; point → `pos_a = pos_b = position`,
`cos_half_angle = -1` (no cone).

## Components & phases

One spec, four independently testable phases. Order A → B → C → D (renderer
foundation first, then data, then runtime, then authoring UI).

### Phase A — Renderer: cone/spot light type

**Files:** `native/src/renderer/frame.h`, `frame.cc`,
`native/src/renderer/shaders/opaque.frag`, `dynamic_lights.cc`,
`native/src/host/host_bindings.cc`.

- Extend `DynamicLightDescriptor` with `direction` (vec3, world) and
  `cos_half_angle` (float; `-1.0` = not a cone), plus a small `penumbra`
  (cos-space softness for a smooth edge; default a fixed epsilon).
- Upload one new uniform vec4 array `u_dyn_light_dir = (dir.xyz, cos_half_angle)`
  (`frame.cc`, next to the existing three arrays).
- In the `opaque.frag` dynamic-light loop, after computing the light direction
  `L` (from surface to the light / closest segment point), multiply the light's
  contribution by a **spot factor**:
  `spot = (cos_half_angle < 0.0) ? 1.0 : smoothstep(cos_half_angle - penumbra, cos_half_angle, dot(normalize(-L), dir))`.
  Point/strip pass `cos_half_angle = -1` → `spot == 1.0` → **existing torpedo
  point lights are byte-identical** (prove in the task: `-1` short-circuits
  before any new math).
- `set_dynamic_lights` accepts optional `direction` + `cos_half_angle` in each
  light dict; defaults keep old callers unchanged.
- **Cap note:** the hard `MAX_DYN_LIGHTS = 4` per draw is unchanged in Phase A.
  If ship-authoring in Phase D shows overlap starving lights, bump to 8 in a
  follow-up (uniform budget is ample); v1 relies on the existing luminance
  selection to pick the 4 brightest per hull draw.

**Test:** a `FrameTest` (ctest) renders a cone light onto a plane and asserts
the lit region is bounded by the half-angle (lit inside, dark outside); a second
asserts a point light with `cos_half_angle = -1` produces the pre-change image
(identity guard).

### Phase B — Emitter spec, persistence, baked reader

**Files:** new `engine/appc/light_emitters.py`; extend the property data-bag
setters and `engine/appc/hardpoint_override_writer.py` / the `set_region` seam;
tests under `tests/`.

- Define the emitter spec dataclass/dict form above and helpers to (a) build a
  default spec per kind, (b) convert an authored spec to renderer-struct form
  (the `pos_a/pos_b/direction/cos_half_angle` derivation).
- Persistence mirrors oriented-box-glow: a recorded **`SetLightEmitter`** setter
  family on the subsystem property template (captured via the data-bag
  `__getattr__`, indexed like glow regions). No BC-native equivalent — this is a
  Dauntless extension, byte-identical to how `SetGlowRegionOrientation` was added.
- `light_emitters.baked_emitters(prop)` reads the recorded setters back at ship
  build (mirroring `subsystem_glow.baked_glow_regions`), returning specs per
  subsystem index.
- Writer: emitters persist to machine-owned `hardpoint_overrides.py` through the
  existing writer seam (full-replace semantics per subsystem, like `set_region`),
  so a removed emitter leaves no orphan setters.

**Test (pytest):** round-trip a spec of each kind through
setter-record → `baked_emitters` → struct-conversion; assert derived
`cos_half_angle` for a cone; assert removal clears setters; assert the writer
emits valid `hardpoint_overrides.py` text (and drops an emptied block).

### Phase C — Runtime producer + health/flicker/impulse linkage

**Files:** `engine/host_loop.py` (new producer alongside
`_build_dynamic_light_render_data`), `engine/appc/light_emitters.py` (state
resolution), tests.

- Each frame, walk active ships' subsystems (`iter_active_ships`); for each
  authored emitter, resolve output intensity:
  - Base = `color × intensity`.
  - **State via `subsystem_glow.glow_state(sub)`**: `HEALTHY` → ×1.0;
    `DISABLED` → **flicker** (a game-time waveform × per-emitter phase, computed
    in Python — no shader change); `DESTROYED` → ×0.0 (off).
  - **Impulse-parent emitters** additionally ×`subsystem_glow.impulse_gain(frac, now, powered)`
    so they brighten with commanded throttle exactly like the impulse glow.
- Convert each active emitter to `DynamicLightDescriptor`(s) and feed the same
  64-light host list as torpedoes via `set_dynamic_lights`. Existing selection
  arbitrates the per-draw budget; a fully-off (destroyed / flicker-dark) emitter
  emits nothing that frame (or intensity 0), so it never wastes a slot.

**Test (pytest):** a healthy subsystem → steady emitter; disabled → intensity
varies over successive game-times (flicker), never full-steady; destroyed → no
light / intensity 0; an impulse-parented emitter scales with the throttle frac.
Producer is pure/data-returning so it is unit-testable without a renderer
(patch `host_io._h`).

### Phase D — SPV authoring

**Files:** `engine/ui/ship_property_viewer.py`,
`engine/ui/ship_property_viewer_panel.py`,
`native/assets/ui-cef/{index.html, js/ship_property_viewer.js, css/*}`,
`native/src/renderer/` (wireframe cone primitive for the debug-volume pass), tests.

- **Tree:** a **"Light Emitter"** child node (one per emitter) under a subsystem,
  rendered like a Light Volume row. New `_selected_emitter_index`, mutually
  exclusive with `selected_index` / `_selected_light_index` (extend the existing
  two-way selection to three-way). Selecting an emitter shows only its wireframe.
- **Add:** right-click a subsystem → **Add Light Emitter…** → a modal reusing the
  light-type-modal pattern but for emitters:
  - **Type picker:** Point / Strip / Cone.
  - **Colour wheel:** hue + saturation at full value (pure chromaticity),
    mouse-drag; a small readout of the RGB/hex.
  - **Intensity slider:** 0..~8 HDR, mouse-drag + fine steppers.
  - Apply stages a default-sized emitter of that type/colour and selects it.
  - Mouse-only throughout (no keyboard→CEF): wheel and slider are pointer drags,
    steppers are click targets.
- **Edit / Remove:** right-click the emitter node → **Edit Emitter…** (same
  modal, re-pick type / colour / intensity, geometry preserved) / **Remove Light
  Emitter**.
- **Gizmos:** reuse `GizmoPass` (handle_kind 0/1/2). Transform / Scale / Rotate
  route to emitter params identically to volumes:
  - Point ↔ sphere (transform = position, scale = radius/range, rotate inert).
  - Strip ↔ cylinder (transform = midpoint, scale = length + radius, rotate = axis).
  - Cone ↔ cylinder + angle (transform = apex, rotate = direction, scale axial =
    range, scale perpendicular = base radius = derived angle).
  - Wireframe outline in the emitter's colour: point → sphere, strip → cylinder
    (both exist), **cone → new cone wireframe** (a small `DebugCone`-style
    primitive in the debug-volume pass).
- **Persistence:** on Save, emitter specs route through Phase B's writer to
  `hardpoint_overrides.py` (auto-keep + commit per the standing override policy).

**Test (pytest):** panel tests mirroring the volume tests — add each kind →
child node appears + selected; edit changes type/colour/intensity, geometry
preserved; remove clears; gizmo drag on each kind moves the right param
(reuse the existing gizmo test harness); render payload carries the emitter node.

## Colour & intensity

The colour wheel picks **hue + saturation** at full value; a **separate HDR
intensity** slider (can exceed 1.0 → drives bloom) scales output. Stored as
linear RGB (`color`) + `intensity`, matching `set_dynamic_lights`' `color ×
intensity` split. The wheel is a new CEF control (canvas-drawn HS disc, pointer
drag), the only substantial new UI.

## Edge cases

- **Cone with `length == 0`** (or radius 0): guard the `atan` — clamp to a min
  length/radius so the half-angle is finite; the Scale tool already floors at
  `SCALE_MIN`.
- **Emitter on a destroyed/disabled subsystem at author time:** the SPV shows it
  normally (authoring is state-independent); state only affects the in-mission
  producer.
- **More than 4 emitters overlapping one hull draw:** existing luminance
  selection keeps the 4 brightest; documented constraint, `log()` nothing (not a
  silent cap that hides coverage — it's a per-frame LOD by design). Revisit the
  cap only if it reads wrong in-game.
- **Identity/no-op safety:** existing torpedo point lights must render
  byte-identical after Phase A (`cos_half_angle = -1` short-circuit). Prove it in
  the Phase A task.
- **Removal leaves no orphans:** full-replace per subsystem in the writer, same
  as glow `set_region([])`.

## Testing strategy

- **pytest** for Phases B/C/D (spec round-trip, persistence, producer/health
  state, panel tree/modal/gizmo routing).
- **ctest `FrameTest`** for the Phase A cone shader (bounded lit region +
  identity guard).
- Gate throughout: `scripts/check_tests.sh` (build + pytest + ctest vs
  `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball.

## Rollout

Branch `feat/spv-light-emitters` off `main`, task-by-task via
subagent-driven-development, gated by `scripts/check_tests.sh`. `hardpoint_overrides.py`
edits (Mark's tunings) are never staged in subagent commits — the controller
commits them separately per the auto-keep policy. Merge is Mark's call after an
in-game pass. Never pushed without Mark's say-so.
