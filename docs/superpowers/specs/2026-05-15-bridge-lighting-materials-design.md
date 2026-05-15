# Bridge Lighting & Materials — Design

**Status:** Approved for implementation
**Date:** 2026-05-15
**Branch:** experimental (worktree)

## Purpose

The bridge interior currently renders without lighting and (likely) without textures. Investigation of `Dbridge.NIF` revealed two root causes and one structural fact about BC's bridge rendering:

1. **Asset pipeline bug.** `gather_material_inputs` reads `property_links` only from the `NiTriShape` itself. In v3.x BC NIFs, properties are commonly set on the parent `NiNode` and inherited by children. All 145 DBridge shapes have empty direct `property_links` and depend on inheritance. The current pipeline silently produces shapes with no material at all.
2. **Renderer architecture mismatch.** BC bridges do not use single-pass per-pixel base × lightmap modulation. The bridge geometry is split into two sets of meshes — 128 base-textured shapes and 17 separate "lightmap shapes" whose Base texture is a `_lm.tga` file. The lightmap shapes are drawn over the base shapes with multiply blend.
3. **Bridge-set lighting is independent.** The bridge's `SetClass` authors its own `CreateAmbientLight`; the renderer must use the bridge set's lighting in bridge mode, not the space scene's.

The MVP target is **static bridge geometry + alpha-tested LCARS panels**, lit by the bridge set's ambient and the baked lightmap pass.

## Investigation summary

`native/tools/probe_texture_stages` (added during this brainstorming) dumped DBridge.NIF's per-shape texture-property layout:

- **145 NiTriShape blocks**, all materials/textures inherited via parent-NiNode `property_links`.
- **128 shapes** use `NiTextureProperty` (single-stage) with `Map N.tga` base textures.
- **17 shapes** use `NiMultiTextureProperty` with **only Base stage populated**, where Base is a `_lm.tga` file. Stage 1 (Dark), Stage 2 (Detail), Stage 3 (Glow), Stage 4 (Gloss) are all empty across all 17.
- **0 NiAlphaProperty** anywhere — LCARS panels must rely on TGA alpha + alpha-test, not explicit blend properties.
- **0 NiAmbientLight / NiDirectionalLight** — bridge stores no real-time lights, confirming the existing static-analysis note.

## Approach

A dedicated bridge render pipeline:
- Pass A draws base-textured shapes opaquely, modulated by the bridge-set ambient.
- Pass B draws lightmap-tagged shapes with multiply blend over the framebuffer.

Detection of lightmap shapes is by **filename heuristic** — Base-stage texture filename ends in ` lm.tga` or `_lm.tga` (case-insensitive). This matches BC's authoring convention and avoids reverse-engineering NIF blend state.

Two shader pairs (chosen over a single-shader variant for clarity of intent and decoupled future tuning):
- `bridge.{vert,frag}` — `base × ambient`, alpha-test enabled.
- `lightmap.{vert,frag}` — pure texture sample, no alpha-test, no ambient.

The asset pipeline is fixed in two ways: property-link inheritance walks up the parent NiNode chain (general fix, affects all models), and a new `Material::lightmap_pass` flag is set when the filename predicate matches.

## Scope

### In scope (MVP)

1. **Asset pipeline — property-link inheritance.** `gather_material_inputs` walks up parent NiNodes; child properties override parent properties per type.
2. **Asset pipeline — lightmap tagging.** `Material::lightmap_pass` bool, set when the resolved Base-stage texture filename ends in ` lm.tga` or `_lm.tga` (case-insensitive).
3. **Engine — bridge-set lighting aggregation.** `engine/appc/lights.py` resolves the bridge `SetClass` and aggregates its ambient. New `r.set_bridge_lighting(...)` binding pushes it as `g_bridge_lighting` separate from `g_lighting`.
4. **Engine — `CreateAmbientLight` 4th-arg interpretation.** Inspect the runtime value for DBridge, pick the most visually sensible interpretation (dimmer-clamp vs. ignore), document the choice in `engine/appc/lights.py`.
5. **Renderer — bridge shader pair** `bridge.{vert,frag}` (base × ambient, alpha-test) and **lightmap shader pair** `lightmap.{vert,frag}` (pure sample).
6. **Renderer — `BridgePass`.** Two sub-passes per frame; partitions bridge-tagged instances by `Material::lightmap_pass`.

### Non-goals (deferred)

- Viewscreen-as-render-target (space scene rendered into the bridge viewscreen).
- Stripping the space pass when bridge view is active (currently runs every frame as "wasted GPU work" per `host_bindings.cc:267-271`; deferred until the viewscreen-RTT path lands).
- Animated / red-alert bridge state.
- Per-ship-class bridge variants (DBridge is hardcoded today in `host_loop.py:502`).
- Bridge characters / skinned crew animation.
- Specular / glow on bridge geometry (not authored in stock content).
- Resolving the `CreateAmbientLight` 4th-arg semantics with certainty (we pick visually; the "true" answer is unconfirmed).
- Per-LCARS-panel alpha-test threshold tuning (hardcoded at 0.5 for v1).
- NIF `Dark`-stage lightmap support (modern authoring tools; stock content doesn't use it).

## Components

### 1. Asset pipeline — property-link inheritance

**Files:**
- `native/src/assets/src/model_build.cc`
- New unit test under `native/tests/assets/`

**Change:**
- Build a `child_link → parent_nif_block_index` map during `build_model`, alongside the existing node walk.
- `gather_material_inputs` takes that map. For each shape:
  1. Read the shape's own `property_links` first (highest priority).
  2. Walk up parent NiNodes; for each ancestor, append properties for any type slot not already filled by the child.
  3. Stop at the root.
- Property types in the inheritance set: `NiMaterialProperty`, `NiTextureProperty`, `NiMultiTextureProperty`, `NiAlphaProperty`, `NiZBufferProperty`, `NiVertexColorProperty`.

**Risk mitigation (ship regression):**
- Extend `probe_texture_stages` to report direct-vs-inherited provenance.
- Run across all ship NIFs under `game/data/Models/Ships/` before the change.
- Add a regression fixture test that loads a representative ship (e.g. Galaxy) and pins material count + per-material base-texture identity.
- Implementation done in a worktree on an experimental branch with manual visual diff before merge.

### 2. Asset pipeline — lightmap tagging

**Files:**
- `native/src/assets/include/assets/material.h` (add field)
- `native/src/assets/src/material_build.cc` (set field)
- `native/src/assets/src/material_build.h` (extend `MaterialInputs` with a texture-name accessor)
- `native/src/assets/src/model_build.cc` (wire texture-name lookup)

**Change:**
- Add `bool lightmap_pass = false;` to `assets::Material`.
- After Base-stage population, look up the underlying source filename. If the basename (case-insensitive) ends in ` lm.tga` or `_lm.tga`, set `lightmap_pass = true`.

**Tag on Material, not Mesh:** the tag is a property of the texture binding; two meshes sharing a material share the tag.

**Test:** synthetic `nif::File` with one shape whose Base texture is `foo lm.tga` asserts `Material::lightmap_pass == true`; negative case with `Map 19.tga`.

### 3. Engine — bridge-set lighting aggregation

**Files:**
- `engine/appc/lights.py` (new helpers; existing `aggregate_lighting` unchanged)
- `engine/host_loop.py` (one new call site in the tick loop)
- `native/src/host/host_bindings.cc` (new binding + global)
- `native/src/renderer/bridge_pass.cc` (reads new global; created in Component 5)

**Change:**
- `_resolve_bridge_set()` walks `SetClass` instances; returns the one whose name matches the player ship's bridge (BC convention: `"bridge"`, with subclasses like `"DBridge"`, `"FBridge"`); falls back to literal `"bridge"`; returns `None` if no bridge set exists.
- `aggregate_bridge_lighting()` returns ambient + (any) directionals from the resolved bridge set. Stock bridges author ambient only.
- New `r.set_bridge_lighting(...)` binding populates `g_bridge_lighting` (mirroring `g_lighting`).
- `BridgePass::render()` (Component 5) reads `g_bridge_lighting`; falls back to `g_lighting` if uninitialised.
- `engine/host_loop.run` calls `aggregate_bridge_lighting()` + `r.set_bridge_lighting(...)` each tick, alongside the existing space-lighting push.

**`CreateAmbientLight` 4th-arg:** observed values up to 19.0 for bridges. Current interpretation (`dimmer × color`) would blow out. Implementation will dump runtime values, eyeball the result with the current interpretation, and either clamp or switch to ignoring the value entirely. Choice and rationale documented in `engine/appc/lights.py`.

**Tests:**
- `engine/appc/lights.py` unit: fake `SetClass` named `"bridge"` with one `CreateAmbientLight`; `aggregate_bridge_lighting()` returns its ambient.
- Behavioural: with `_bridge_pass_enabled = True` and a distinct bridge ambient, the binding stub records the bridge ambient separate from space ambient.

### 4. Renderer — bridge and lightmap shaders

**New files:**
- `native/src/renderer/shaders/bridge.vert`
- `native/src/renderer/shaders/bridge.frag`
- `native/src/renderer/shaders/lightmap.vert`
- `native/src/renderer/shaders/lightmap.frag`

**`bridge.frag` body:**
```
vec4 base = texture(u_base_color, vUV0);
if (base.a < u_alpha_test_threshold) discard;
FragColor = vec4(base.rgb * u_ambient, 1.0);
```

**`lightmap.frag` body:**
```
FragColor = texture(u_lightmap, vUV0);
```

**Uniforms:**
- Both: `u_mvp` (mat4), `u_model` (mat4), one sampler2D on unit 0.
- `bridge.frag` only: `u_ambient` (vec3), `u_alpha_test_threshold` (float, default 0.5).

**Vertex inputs:** `aPos`, `aUV0`. (`aNormal` reserved for future use; unused for v1.)

**Registration:** in `pipeline.cc`, mirroring `opaque.vert/.frag`. Embedded via existing `embed_shader()` cmake mechanism — **shader edits require `cmake -B build -S .` to reconfigure** per the known constraint.

### 5. Renderer — `BridgePass`

**Files:**
- `native/src/renderer/include/renderer/bridge_pass.h` (new)
- `native/src/renderer/bridge_pass.cc` (new)
- `native/src/renderer/frame.cc` (drop `submit_opaque_in_pass`; the only caller was bridge)
- `native/src/renderer/include/renderer/frame.h` (drop the declaration)
- `native/src/host/host_bindings.cc` (replace inline bridge draw with `g_bridge_pass->render(...)`)

**Per-frame sequence (after color+depth clear in `host_bindings.cc:273-274`):**

**Sub-pass A — base geometry:**
- Bind `bridge.{vert,frag}`.
- GL state: `GL_DEPTH_TEST` on, depth-func `GL_LESS`, `glDepthMask(GL_TRUE)`, blending disabled.
- Set `u_ambient` from `g_bridge_lighting.ambient`.
- For each bridge-tagged instance, for each mesh with `Material::lightmap_pass == false`: set per-draw uniforms, bind base texture to unit 0, `glDrawElements`.

**Sub-pass B — lightmap multiply:**
- Bind `lightmap.{vert,frag}`.
- GL state: `GL_DEPTH_TEST` on, depth-func `GL_LEQUAL`, `glDepthMask(GL_FALSE)`, `GL_BLEND` on, `glBlendFunc(GL_DST_COLOR, GL_ZERO)`, `GL_POLYGON_OFFSET_FILL` on, `glPolygonOffset(-1.0f, -1.0f)`.
- For each bridge-tagged instance, for each mesh with `Material::lightmap_pass == true`: set per-draw uniforms, bind lightmap texture to unit 0, `glDrawElements`.
- Restore GL state at end.

**Why LEQUAL + polygon offset both:** `LEQUAL` handles coplanar lightmap geometry (the common case); polygon offset handles authoring drift. Standard fixed-function lightmap pattern.

**Walk efficiency:** 145 mesh-iterations × 2 sub-passes per frame; only 128 + 17 actually issue draws. Trivial. If perf ever matters, the obvious optimisation is sorting by texture inside each sub-pass.

**Tests:**
- Partitioning unit test: synthetic Model with mixed-tag materials; stubbed GL captures `glDrawElements` call order.
- Headless render test (Linux CI; macOS pixel readback unreliable): one base mesh + one lightmap mesh, framebuffer centre pixel ≈ `base × lightmap`.

## Risks

1. **Ship rendering regression from inheritance walk.** Mitigation per Component 1.
2. **Z-fighting between base and lightmap geometry.** Mitigation: `LEQUAL` + polygon offset. If still visible, fall back to a small camera-space depth bias in `lightmap.vert`.
3. **`CreateAmbientLight` 4th-arg interpretation.** Mitigation: pick visually during implementation; document rationale.
4. **Texture-path resolution for prefixed names.** Probe shows multi-tex stages reference paths like `DBridge/door 04a lm.tga`. The current `load_model(nif, texture_search_path)` may need to strip prefixes; verify in early implementation.
5. **LCARS alpha channels may not exist on stock TGAs.** Spot-check before relying on alpha-test. If TGAs are 24-bit, drop alpha-test from `bridge.frag` and accept opaque LCARS panels for v1.

## Deferred work (to be added to `native/src/host/docs/deferred_work.md`)

1. **Strip the space pass when bridge view is active.** Currently every frame, kept for future viewscreen-RTT. Cross-reference the viewscreen item.
2. **Viewscreen-as-render-target.** Render the space scene into the `DbridgeViewScreen.NIF` surface.
3. **Animated bridge state.** Red-alert tint, viewscreen flicker, station-screen content.
4. **Per-ship-class bridge variants.** DBridge hardcoded in `host_loop.py:502`; other classes need FBridge/EBridge/etc.
5. **Bridge characters / skinned animation.**
6. **Specular / glow on bridge geometry.** Not in stock content.
7. **Per-LCARS-panel alpha-test threshold tuning.** Currently 0.5 hardcoded.
8. **NIF `Dark`-stage lightmap support.** Modern authoring tools; non-stock content.
9. **`CreateAmbientLight` 4th-arg true semantics.** Document the chosen interpretation and the evidence; the underlying ground truth remains unconfirmed.

## Testing summary

| Layer | What |
|---|---|
| C++ unit | property-link inheritance walk; filename → `lightmap_pass`; bridge-pass partitioning |
| Python unit | `aggregate_bridge_lighting`; bridge-set resolution |
| C++ integration | DBridge.NIF loads with 145 meshes; 128 `lightmap_pass=false`, 17 `lightmap_pass=true` |
| Visual | F-key into bridge mode; eyeball vs stock-BC screenshot reference |
| Regression | Ship-fixture test pins material count + base-texture identity for a representative ship |
