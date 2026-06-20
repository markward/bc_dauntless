# Bridge Dynamic Lighting Design

> **Status:** design only, not yet implemented.
> **Authored:** 2026-06-20.
> **Scope:** replaces BC's baked-lightmap bridge interior rendering with a
> fully dynamic forward-lit pipeline, plus an authoring workflow + JSON
> config format. Significant chunk of work (~4-5 sessions of renderer
> code, plus per-bridge content authoring). Defer until other gameplay
> priorities clear.

## 1. Motivation

The current bridge pass renders interior geometry via:

1. NIF-baked vertex colors,
2. Per-material `emissive` (light fixtures set to (1,1,1) so they stay
   bright under any ambient),
3. UV1 lightmap textures from BC's `_lm.tga` / `-lm.tga` / `_LM.tga`
   convention, multiplied over the base.

That works but locks us out of every visual upgrade we actually care
about:

| Limitation | Consequence |
|---|---|
| Lightmaps are tiny (BC authored them at low resolution) | Mucky, grainy quality across all bridge surfaces. |
| Static baked geometry | No bridge-character interaction with lighting; characters don't shadow surfaces, surfaces don't pick up bounced light from characters. |
| No reflection capture | Glossy LCARS panels and chair-arm specular highlights are impossible. |
| Pre-baked indirect | Damage VFX (sparks, electrical arcing, console fires) can't tint nearby surfaces. |
| Single ambient term | Alert-state color washes (red panels casting red bounce on the captain's chair) impossible. |

A fully baked replacement (high-res lightmaps via Blender/Cycles) was
considered and rejected because every limitation above survives the
upgrade — bake-it-once optimises for "static museum diorama," but our
bridge is a *living scene* (crew motion, combat damage, alert states,
glossy materials).

Conclusion: go fully dynamic.

## 2. High-level architecture

Per bridge, in active play:

- Up to **16 small dynamic lights**: `point`, `sphere`, `tube`,
  `polyline_tube`, or `bezier_tube` primitives.
- Exactly **1 LTC area light**, reserved for the ceiling panel/dome.
- **Shadow maps** for ~4-8 key lights only (alert-state strips, damage
  emitters). Other lights are unshadowed — bridge geometry has little
  internal occlusion so the artifacts are minor.
- **SSAO** as a post-pass for contact shadows + cove crevices.
- **Light probes deliberately out of scope.** With only 17 lights total,
  surfaces and characters sample all of them directly per frame — no
  binning, no probes, no indirect approximation needed.

The pixel-cost ceiling is well inside what modern desktop GPUs handle in
a per-fragment loop without any tiled forward+ binning machinery. See
§4 for the budget.

## 3. Light primitives

Single unified `Light` struct in shader-land handles every type via
endpoint degeneration:

```glsl
struct Light {
    vec3  p0;       // segment start
    vec3  p1;       // segment end (== p0 for point/sphere)
    vec3  color;
    float radius;   // 0 → point, >0 → sphere or tube
    float intensity;
};
```

Per-fragment evaluation (closest-point-on-segment + Karis representative-
point approximation for the radius term):

```
type        | p0 == p1 | radius | per-fragment ALU
------------|----------|--------|------------------
point       | yes      | 0      | ~5
sphere      | yes      | >0     | ~8  (closest-point-on-sphere)
tube        | no       | >0     | ~13 (closest-point-on-segment + radius)
polyline    | array    | >0     | ~13 × num_segments
bezier      | array*   | >0     | ~13 × tessellation
LTC rect    | corners  | —      | ~30-50 + 2 texture samples
```

*Bezier* is tessellated to a polyline at config-load time (cubic, 16-32
segments based on curvature heuristic), then runtime model is identical
to polyline.

**Polyline closest-point loop** (per light, per fragment):

```glsl
vec3 closest = polyline.v[0];
float best_d2 = dot(frag - closest, frag - closest);
for (int s = 0; s < polyline.segment_count; ++s) {
    vec3 cp = closest_point_on_segment(polyline.v[s], polyline.v[s+1], frag);
    float d2 = dot(frag - cp, frag - cp);
    if (d2 < best_d2) { best_d2 = d2; closest = cp; }
}
// evaluate tube light at `closest`
```

Per-light bounding-sphere culling up front rejects fragments outside the
light's range, so the polyline loop only runs where it matters.

## 4. Per-fragment ALU budget

Typical bridge composition:

| Type | Count | Segs each | ALU/light | Total |
|---|---|---|---|---|
| Point/sphere | ~10 | 1 | ~10 | 100 |
| Straight tubes | ~3 | 1 | ~13 | 40 |
| Polyline coves (Bezier or explicit) | ~3 | 8 | ~70 | 210 |
| LTC ceiling | 1 | — | ~50 | 50 |
| **Total** | 17 | | | **~400 ALU/frag** |

Trivial for any GPU made this decade. No tiled binning required; a
fixed-size UBO of `Light[16]` plus separate LTC uniforms handles
everything.

## 5. JSON config format

One file per bridge, lives at
`native/assets/sets/{BridgeName}/lighting.json` where `{BridgeName}` is
the NIF directory name (`EBridge`, `DBridge`) — not the SDK class name
(`SovereignBridge`, `GalaxyBridge`).

### 5.1 Full schema example

```jsonc
{
  "bridge": "EBridge",

  // ── Reusable per-alert-state behaviours. Apply by name. ──
  "animation_profiles": {
    "white_steady_dim_at_red": {
      "green":  {"color": [1.0, 0.95, 0.9], "intensity": 1.0},
      "yellow": {"color": [1.0, 0.95, 0.9], "intensity": 1.0},
      "red":    {"color": [1.0, 0.95, 0.9], "intensity": 0.1}
    },
    "red_pulse_slow": {
      "green":  {"intensity": 0.0},
      "yellow": {"intensity": 0.0},
      "red":    {"color": [1.0, 0.1, 0.1], "intensity": 1.0,
                 "animation": {"type": "sine", "period_s": 5.0}}
    },
    "blue_strobe": {
      "green":  {"intensity": 0.0},
      "red":    {"color": [0.4, 0.6, 1.0], "intensity": 1.5,
                 "animation": {"type": "square", "period_s": 2.0, "duty": 0.5}}
    }
  },

  // ── Singleton LTC for the big ceiling panel/dome. Exactly one. ──
  "ceiling_ltc": {
    "anchor_block": 11,
    "offset_gu": [0, 0, 0],
    "size_gu": [40, 60],
    "profile": "white_steady_dim_at_red",
    "emitter_mesh": 11
  },

  // ── Up to 16 small lights. `type` drives the shape. ──
  "lights": [
    // POINT
    {
      "name": "captain-chair-underglow",
      "type": "point",
      "anchor_block": 100,
      "offset_gu": [0, 0, -0.5],
      "profile": "white_steady_dim_at_red",
      "emitter_mesh": 100
    },

    // SPHERE
    {
      "name": "command-pillar-globe",
      "type": "sphere",
      "anchor_block": 55,
      "radius_gu": 0.4,
      "profile": "red_pulse_slow",
      "emitter_mesh": 55
    },

    // TUBE — three ways to specify the segment:
    {
      "name": "wall-strip-port-A",
      "type": "tube",
      "anchor_block": 29,
      "auto_extent": true,          // derive p0/p1 from mesh AABB long axis
      "radius_gu": 0.05,
      "profile": "white_steady_dim_at_red",
      "emitter_mesh": 29
    },
    {
      "name": "wall-strip-port-B",
      "type": "tube",
      "anchor_block": 30,
      "anchor_block_end": 31,        // two-mesh endpoints
      "radius_gu": 0.05,
      "profile": "white_steady_dim_at_red"
    },
    {
      "name": "wall-strip-port-C",
      "type": "tube",
      "anchor_block": 32,
      "end_offset_gu": [12, 0, 0],   // single mesh + offset to p1
      "radius_gu": 0.05,
      "profile": "white_steady_dim_at_red"
    },

    // POLYLINE_TUBE
    {
      "name": "ceiling-cove-port",
      "type": "polyline_tube",
      "vertices": [
        {"anchor_block": 41},
        {"anchor_block": 42, "offset_gu": [0, 0, 0.5]},
        {"anchor_block": 43},
        {"anchor_block": 44}
      ],
      "radius_gu": 0.05,
      "profile": "white_steady_dim_at_red",
      "emitter_mesh": 41
    },

    // BEZIER_TUBE
    {
      "name": "captain-chair-arc",
      "type": "bezier_tube",
      "control_points": [
        {"anchor_block": 50},
        {"position_gu": [10, 20, 5]},
        {"position_gu": [15, 25, 5]},
        {"anchor_block": 51}
      ],
      "tessellation": 16,
      "radius_gu": 0.03,
      "profile": "white_steady_dim_at_red"
    }
  ],

  // ── Per-state intensity modulation only (NO color, NO emit_map). ──
  // Color comes from the diffuse × NIF material.emissive; texel mask
  // comes from sibling _emit.tga (see §7). This block is intensity over
  // time, nothing else.
  "surface_emissive": {
    "16": {"green": 1.0, "yellow": 1.0, "red": 0.1},
    "20": {"green": 1.0, "yellow": 1.0, "red": 0.1}
  },

  // ── Manual mesh overrides for which surfaces get which post effects. ──
  "vfx_membership": {
    "gloss_eligible": [{"anchor_block": 520}, {"anchor_block": 524}],
    "rim_eligible":   []
  },

  "notes": "Hand-authored 2026-06-20 in dev-mode tool."
}
```

### 5.2 Common per-light fields

Every entry in `lights[]` and the `ceiling_ltc` singleton can carry:

- `name` — human-readable.
- `type` — one of `point`, `sphere`, `tube`, `polyline_tube`,
  `bezier_tube`, `ltc_rect`.
- `profile` — string key into `animation_profiles`.
- `emitter_mesh` — *optional* anchor_block of a mesh whose emissive
  should be driven by this light (see §8).
- `emissive_blend` — *optional*, `"replace"` (default) or `"add"`.
  Controls how the light's color × intensity composes with the mesh's
  existing material emissive when `emitter_mesh` is set.

### 5.3 Animation profile structure

```jsonc
"profile_name": {
  "green":  {"color": [...], "intensity": ..., "animation": {...}?},
  "yellow": { ... },
  "red":    { ... }
}
```

- Each state can independently specify color, intensity, and animation.
- Missing fields default: `color` → previous state's color, `intensity` → 0.
- Missing states → light is off in that state.
- `animation.type`: `sine`, `square`, `saw`. `period_s` + optional
  `duty` (for square) + optional `phase_s` for offset.

## 6. Anchor blocks: mesh identity

The `anchor_block` value is the NIF block index of the target mesh — the
number shown in `[N]` by `dump_nif_tree` (`[29] NiTriShape 'walllight 01
Material: Wall Light'`). Stable per-NIF-file, unique, durable across
asset reuse.

### 6.1 Resolution at runtime

1. **At model-build time** (in `assets::detail::build_model`), capture
   each NiTriShape's source block index and store it on the
   corresponding `assets::Mesh`. Build a `nif_block → mesh_index`
   lookup table on `assets::Model`. **This is a new field on Mesh and a
   new map on Model.**
2. **At config-load time**, for each `"anchor_block": N`:
   - Look up `mesh_index = block_to_mesh[N]`.
   - Walk the mesh's vertex positions to get its AABB center in
     model-local space.
   - Multiply by its owning node's world transform (already computed
     each frame in `walk_bridge_meshes`).
   - Add the JSON's `offset_gu` for the human-authored nudge.
   - That's the final world-space anchor position.

### 6.2 Fallback identification

For human-authored configs, the parser should also accept (in order of
preference):

- `"anchor_block": N` — primary, used by the dev-mode tool.
- `"anchor_name": "..."` — durable across re-export; ambiguous when
  multiple NiTriShapes share a name.
- `"anchor_path": "Gamma/Normal/walllight 01"` — most readable; assumes
  unique paths in the NIF tree.

The dev-mode authoring tool always writes block index. Hand-edited
configs may use any of the three.

## 7. Emit-mask textures (`_emit.tga`)

### 7.1 Why

BC's bridge artists had three blunt instruments for "where does this
surface emit light":

1. Alpha channel of certain diffuse textures (`floorlight.tga` etc.) —
   couples emit mask to texture alpha, can't use alpha for actual
   transparency.
2. Per-material `emissive = (1,1,1)` — whole-mesh, no per-texel control.
3. `Red/Off GlowAlpha` NiNode grouping — whole-subtree toggle.

None of these handle "this DBridge panel has 3 inset bulbs and a black
bezel." The `_emit.tga` convention adds the missing per-texel
primitive.

### 7.2 Convention

For any diffuse texture `walllight.tga`, if a sibling file
`walllight_emit.tga` exists, it is auto-attached as a per-texel emissive
mask. Greyscale 8-bit, same resolution as the diffuse. Sample value
multiplies the emit contribution per fragment.

**Same machinery as the existing `_glow` and `_specular` sibling
discovery in `material_build.cc`**. New `StageSlot::Emit`. New
`sibling_emit_for_image` map in `TextureLoadResult`. Couple-line
addition to `load_all_textures`.

When no sibling exists, sentinel-bind a 1×1 white fallback so the
shader sample returns 1.0 unconditionally (same trick as
`u_dark_map`). Byte-identical to a no-mask render.

### 7.3 File format

**TGA, 8-bit greyscale.** Reasons:

1. Pipeline already handles it (`decode_tga` returns `channels = 1`,
   maps to `Image::Format::R8`). Zero decoder work.
2. Sibling-discovery convention already exists in the texture loader.
3. Matches BC's `_glow` / `_specular` naming pattern.
4. ~25% the VRAM of an RGBA texture; trivial.
5. GIMP / Photoshop / Paint.NET export greyscale TGA cleanly.

### 7.4 No JSON binding for masks

The `_emit.tga` association is **purely convention-based**, never
declared in the JSON config. Reasons:

- Multiple meshes reusing the same diffuse texture would force the
  JSON to repeat the mask binding per mesh — wasteful and error-prone.
- The sibling discovery happens once per *texture*, not per *mesh*, and
  propagates automatically to every material that references the
  diffuse.
- An author drops `walllight_emit.tga` next to `walllight.tga`, every
  mesh in every bridge using that diffuse picks it up next build, zero
  JSON edits.

The edge case (same diffuse reused outside the bridge, mask leaks into
ship hull) is the same papercut `_glow` and `_specular` already live
with; escape hatch is to fork the texture if it ever bites.

## 8. Emission composition

### 8.1 Standalone (no light linked)

For a mesh that emits on its own schedule with no associated dynamic
light:

```
emit_color     = material.emissive  (from NIF NiMaterialProperty)
emit_per_state = json.surface_emissive[mesh][state]  if present  else 1.0
emit_per_texel = sample(diffuse_sibling_emit)         if found    else 1.0
final_emit     = emit_color × emit_per_state × emit_per_texel × diffuse.rgb
```

- `material.emissive` is from the NIF; the JSON **cannot override
  color**. Color identity lives with the diffuse, not the config.
- Per-state intensity modulation comes from `surface_emissive[state]`.
- Per-texel masking comes from the sibling `_emit.tga`.
- All three layers default to pass-through, so each case authors only
  the layers it needs.

| Need | What to author |
|---|---|
| Surface never emits | Nothing. (NIF emissive=0 + no JSON entry + no mask.) |
| Light fixture, always glowing | Nothing. (NIF emissive=(1,1,1) is sufficient.) |
| Light fixture, dims at red alert | `surface_emissive` entry, intensity-only. |
| DBridge panel with inset bulbs only | `_emit.tga` sibling. JSON optional. |
| Both: inset bulbs + alert-state dimming | `_emit.tga` + `surface_emissive` entry. |

### 8.2 Linked to a dynamic light (color shifts at alert)

For a mesh that should **change color** under different conditions
(e.g. wall strip glowing white at green alert, pulsing red at red
alert), the JSON pairs it with a light via `emitter_mesh`. The light's
`animation_profile` provides color and timing; the mesh's emissive
follows.

When `emissive_blend = "replace"` (the default):

```
final_emit = light.profile.color[state] × light.profile.intensity[state] × animation(t)
                                       × diffuse.rgb
```

The NIF's `material.emissive` is bypassed entirely. The `_emit.tga`
sibling still gates per-texel.

When `emissive_blend = "add"`:

```
final_emit = (material.emissive + light.profile.color × intensity × anim) × diffuse.rgb
```

Used rarely — only when an artist wants a permanent baseline glow with a
dynamic boost on top. Default `replace` because most authored cases
need the surface to fully dim out at certain alert states (the
"`Red Off GlowAlpha`" use case).

### 8.3 Mutual exclusion

The two regimes are **mutually exclusive** by author intent:

- `surface_emissive` entries: surface dims/brightens over time, color
  unchanged.
- `emitter_mesh` link: surface changes color (and possibly intensity)
  driven by a paired light.

Authoring rule of thumb: *"Does this surface need to change colour
under any condition?"* Yes → pair with a light. No → just a
`surface_emissive` entry.

## 9. Asset layout

```
native/assets/sets/
├── EBridge/
│   ├── lighting.json              ← light placement + animation profiles
│   ├── walllight_emit.tga         ← per-texture emit masks
│   ├── floorlight_emit.tga
│   ├── commandstationlight_emit.tga
│   └── ...
└── DBridge/
    ├── lighting.json
    └── ...
```

- **`sets/`** not `bridges/` — matches BC's own `Models/Sets/` directory
  convention. Cargo bays, briefing rooms, any future interior set
  inherits the same layout.
- **Per-bridge dir name** = NIF directory name. Avoids the
  `Sovereign`/`SovereignBridge` papercut.
- All hand-authored customizations for a bridge live in one place —
  easy to diff in PRs, easy to copy as a starting point for a third
  bridge.
- The BC install (`game/data/Models/Sets/EBridge/High/`) is **never
  modified**. `PathResolver` extension adds the `native/assets/sets`
  override as a higher-priority search path; falls back to the BC
  install if a file isn't found.

## 10. Authoring tool (dev-mode editor)

Not required for the proof of concept — a small hand-authored JSON file
(~5 lights) validates everything up to and including alert-state
modulation. The editor exists to **scale** from 5 to 30 lights × N
bridges.

Workflow target:

1. `--developer` launches the bridge.
2. Hotkey enters light-edit mode.
3. WASD-fly the captain's chair camera.
4. Click a mesh → tool raycasts → identifies hit `assets::Mesh` → looks
   up its source NIF block index.
5. "Drop light here" — modal dialog picks type (`point`/`sphere`/`tube`/
   `polyline_tube`/`bezier_tube`/`ltc_rect`), assigns block index as
   anchor, starts `offset_gu` at zero.
6. Sliders for radius, intensity, color (or pick a named animation
   profile).
7. Save → writes/updates `native/assets/sets/{BridgeName}/lighting.json`.

For polyline lights specifically: "click along a mesh edge to
auto-create a polyline that follows the geometry" shortcut. Pick a
starting vertex, drag along the mesh, the tool emits a polyline with
vertices snapped to the underlying edge loop. Without this shortcut,
hand-placing 8 vertices per polyline is impractical.

Estimated effort: ~1.5 sessions, after the renderer + loader phases
prove the underlying data model is correct.

## 11. Phased build order

Each phase has its own off-ramp — if the visual quality of an earlier
phase already meets the bar, later phases can be deferred or dropped.

| # | Phase | Goal | Authored how | Effort |
|---|---|---|---|---|
| 1 | **Phong forward pass, hard-coded** | Prove dynamic point lighting beats the current lightmap visually. 2-3 lights hard-coded in C++. | Inline `glm::vec3` constants. | ~1 session |
| 2 | **Light primitive variety** | Add sphere, tube, polyline, bezier, LTC to the shader. | Still hard-coded. | ~1 session |
| 3 | **JSON loader** | Lock schema, Python parser, anchor_block resolution, push light array per frame. | Hand-written JSON, ~5 lights. | ~0.5 session |
| 4 | **Profiles + alert state** | Runtime intensity/color modulation responding to alert state. | Same JSON file. | ~0.5 session |
| 5 | **Shadow maps for key lights** | 4-8 lights with cheap depth-only shadow passes. | JSON flag. | ~1.5 sessions |
| 6 | **SSAO post-pass** | Contact shadows, cove crevices. | None (auto). | ~0.5 session |
| 7 | **Dev-mode editor** | Raycast-pick, drop light, save. | This is the chicken; phases 1-4 are the egg. | ~1.5 sessions |

**Phase 1 doubles as a go/no-go gate.** If hard-coded Phong with no
shadows already looks worse than BC's lightmap, the whole plan needs to
back up. Cheap to build, cheap to discard.

## 12. Removals from the existing codebase

Once the new pipeline ships, remove:

- `assets::Material::lightmap_pass` field and its setting in
  `material_build.cc::build_material` (the `filename_is_lightmap`
  block).
- The `walk_bridge_meshes` second pass with `want_lightmap_pass=true`
  in `bridge_pass.cc::render`.
- The UV1 lightmap sampling in `bridge.frag` (`u_dark_map`, `v_uv1`)
  unless we keep a vestigial path for community packs that still ship
  `_lm.tga` siblings (probably not — game is too niche).
- The `lightmap_pass` partition tests in
  `tests/renderer/bridge_pass_test.cc`.
- BC `_lm.tga` / `-lm.tga` / `_LM.tga` filename-pattern handling in
  `filename_is_lightmap()`.

The `_glow` and `_specular` sibling-discovery paths **stay** —
they're used by ship hulls, not bridges.

## 13. Why we rejected baked lightmaps

Considered: bake high-resolution AO + per-static-light shadow maps in
Blender/Cycles, output as auxiliary textures plus a higher-quality
lightmap UV unwrap. ~1-3 sessions to integrate, near-zero runtime cost.

Rejected because **bridges are not static dioramas**:

1. **No character interaction.** Crew (Saffi, Picard, etc.) move
   around the bridge; pre-baked light doesn't shadow them or receive
   their bounce.
2. **No glossy reflections.** Pre-baked indirect captures only diffuse
   bounce. Reflections on LCARS panels and chair arms need realtime
   capture.
3. **Damage VFX limited.** Sparks/arcing/console fires from damage
   states can only be local emitters — they wouldn't color-shift
   nearby surfaces.
4. **VRAM cost.** A good per-bridge lightmap at 2K is ~16MB, more
   with shadow maps per static light. Multiple bridges + LODs adds
   up.
5. **Authoring burden.** Each bridge needs clean lightmap UV unwraps
   with margins (BC's NIFs don't ship these), plus the bake step
   itself.

The user's lighting list (alert-state color shifts, glossy LCARS,
character interaction, damage VFX response) is exactly the set baked
lighting can't deliver.

## 14. Why we rejected realtime SDF / Lumen-style GI

Considered: generate signed-distance fields from bridge geometry at
load, raymarch for soft shadows + AO. Truly dynamic.

Rejected because:

- ~3-5 sessions of real engineering work.
- Visual ceiling lower than a good bake for not-much-faster runtime.
- Forward rendering with selective shadow maps + SSAO gets us 80% of
  the visual win for ~half the engineering cost.

If we ever want global illumination later (light bouncing off the
captain's chair onto the floor, etc.), SDF GI is the right next step —
but not for the v1 of this pipeline.

## 15. Why no light probes (deferred)

With only 17 lights total per bridge, every surface and character can
sample every light directly each frame in a fixed-size shader loop.
That's the cheapest possible path; light probes add complexity (probe
placement, runtime sample-and-interpolate) for indirect approximation
that direct sampling already covers.

If we later add more lights, or want bounced indirect light from
emissive surfaces back onto the room (a glowing LCARS panel lighting up
the chair next to it), probes become the natural addition. Saved for
when needed.

## 16. Open questions for implementation session

These were *not* resolved in the design conversation; flag them when
work starts:

1. **Shadow map atlas vs separate textures per light?** Atlas saves
   binding overhead; separate textures are simpler. Probably atlas at
   our scale.
2. **LTC LUT storage** — bake into the binary as embedded data, or load
   from disk at startup? Heitz reference includes a Python script to
   generate the LUTs.
3. **Damage emitter integration** — how does damage VFX wire its own
   light into the bridge's light array? Probably a separate
   `damage_lights` slot reserved in the UBO, populated from the damage
   system per frame.
4. **What about *non-bridge* interiors** (Engineering, Sickbay) when we
   eventually get to them? The asset layout is generic (`native/assets/
   sets/`), but does the JSON schema generalize cleanly, or is some of
   it bridge-specific (alert state)?
5. **Per-light bounding sphere** — author-supplied (in JSON) or
   auto-derived from radius + intensity attenuation curve? Auto is
   simpler but less flexible.
6. **Anchor identifier durability** — block-index works for now; if BC
   modders ever re-export the bridge NIFs, the indices shuffle and the
   JSON config breaks. Mitigation: support both `anchor_block` and
   `anchor_name` / `anchor_path`, parser tries block first, falls back
   to name+occurrence.

## 17. References

Read first in any future implementation session:

- This document.
- [CLAUDE.md](../../../CLAUDE.md) — project conventions, especially the
  bridge pass section and the BC game-unit convention.
- [native/src/renderer/bridge_pass.cc](../../../native/src/renderer/bridge_pass.cc)
  — current bridge rendering pipeline. The `walk_bridge_meshes`
  template + `draw_mesh` per-shape routine are the natural integration
  points.
- [native/src/renderer/shaders/bridge.frag](../../../native/src/renderer/shaders/bridge.frag)
  — current bridge fragment shader. The new pipeline replaces the
  `light = max(u_ambient, u_emissive)` term with the per-light loop.
- [native/src/assets/src/material_build.cc](../../../native/src/assets/src/material_build.cc)
  — `_glow` and `_specular` sibling-discovery code; the `_emit` path
  follows the same pattern.
- [native/src/assets/src/path_resolver.cc](../../../native/src/assets/src/path_resolver.cc)
  — multi-dir search; the `native/assets/sets/` override path slots
  in here.
- Heitz et al., "Real-Time Polygonal-Light Shading with Linearly
  Transformed Cosines" (2016) — reference for the LTC implementation.
- Karis, "Real Shading in Unreal Engine 4" SIGGRAPH 2013 course notes —
  representative-point approximations for sphere and tube lights.
