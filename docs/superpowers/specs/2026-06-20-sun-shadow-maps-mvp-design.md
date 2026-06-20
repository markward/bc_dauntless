# Sun Shadow Maps (MVP) — Design

**Date:** 2026-06-20
**Status:** Approved design, pre-implementation
**Feature:** A new "Shadows" effect under the Modern VFX config group — ships and stations
cast and receive directional sun shadows in exterior view.

## Goal

Add basic shadow maps so spaceships (and stations) cast and receive real shadows from the
sun in exterior view. Ship-on-ship cast shadows and self-shadowing of hull greebles are the
target payoff. This is a deliberately minimal first version (a single orthographic shadow
map), structured so the obvious future upgrades — cascaded shadow maps for quality, and
moving local lights (torpedoes) — are additive rather than rewrites.

### Non-goals (explicit YAGNI / future rungs)

- **No cascaded shadow maps (CSM).** Single ortho box only. CSM is the quality upgrade path;
  this design avoids choices that would block it but does not build it.
- **No multi-light shadow array, no point/spot (torpedo) shadows.** The `ShadowLight` struct
  stays single (one directional caster). The array generalization is the future torpedo work.
- **No soft/area shadows, no screen-space contact shadows.**
- **Bridge interior, hologram, and viewscreen-static passes are untouched** (hologram has its
  own shader; bridge is interior).

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Caster/receiver scope | Ships **and** stations cast and receive; planets/asteroids excluded | Reuse existing `rim_eligible` flag (true for hull-like, false for planets/asteroids). Huge bodies would wreck a single ortho box. |
| Frustum fit | Player-centered, capped radius | Exterior camera orbits the player; keeps fixed-resolution shadows crisp where the camera looks. Distant combatants beyond the cap simply get no shadow. |
| Default state | **ON** | Consistent with the Modern VFX group (HDR, rim default on). |
| Light source | Single directional sun (`directional_dir_ws[0]`) | BC has one dominant light; multi-light is future work. |
| Technique | Basic single orthographic shadow map | Simplest thing that delivers ship-on-ship cast shadows. CSM is the upgrade, screen-space can't do cast shadows. |

## Architecture

**One shadow map, computed once per frame, shared by every view.** The shadow box is
light-relative and player-centered — independent of the *view* camera — so it is computed
once at the top of `frame()`, before the HDR target is bound, and both the main view and the
viewscreen RTT sample the same map at no extra cost.

```
frame():
  if dauntless_shadows::enabled():
    light = compute_light_matrix(player_pos, player_radius, light_dir, params)
    g_shadow_pass->render(world, light)     # depth-only, casters -> shadow FBO (2048²)
  ... bind HDR target ...
  render_space(view_camera):                # called for main view AND viewscreen RTT
    backdrop, sun
    submit_opaque_in_pass()                 # hull shader samples shadow map (PCF)
    ...rest of passes unchanged...
```

### New components (mirroring existing renderer patterns)

1. **`dauntless_shadows` toggle namespace** in `native/src/renderer/frame.cc` — same shape as
   `dauntless_rim` / `dauntless_hdr` (`enabled()` / `set_enabled()`, default `true`).
2. **`ShadowMapTarget`** — a depth-only FBO sibling to `hdr_target`:
   - One depth texture, `2048²`, `GL_DEPTH_COMPONENT24` (or `32F`).
   - Configured for **hardware PCF**: `GL_TEXTURE_COMPARE_MODE = GL_COMPARE_REF_TO_TEXTURE`,
     `GL_LINEAR` filtering, sampled as `sampler2DShadow`.
   - **Clamp-to-border, border color white** → any receiver outside the box samples "fully
     lit," so the capped radius produces no hard edge artifact at its boundary.
3. **`ShadowPass`** — depth-only pre-pass, global `g_shadow_pass`, constructed in `init()`.
   Minimal `shadow_depth.vert` + trivial fragment shader. Iterates
   `world.for_each_visible_in_pass(Pass::Space, ...)` filtered to casters.
4. **`ShadowLight` struct** — `{ glm::mat4 view_proj; float texel_world_size; }`. Deliberately
   single. Keeps the shape clean for a future array of slots without building it now.

### Config wiring (Modern VFX "Shadows" toggle)

Follows the exact path the rim/HDR toggles use:

- C++: `dauntless_shadows::set_enabled` in `frame.cc`; forward-declared and bound as
  `shadows_set_enabled` in `native/src/host/host_bindings.cc`.
- Python wrapper: `set_shadows_enabled(enabled)` in `engine/renderer.py` → `_h.shadows_set_enabled`.
- Settings: `shadows_on: bool = True` field in `SettingsSnapshot`
  (`engine/ui/configuration_panel.py`); `toggle:shadows` dispatch; applier
  `set_shadows=r.set_shadows_enabled` injected in `engine/host_loop.py`.
- CEF config panel: add a "Shadows" checkbox row alongside HDR/Rim in the configuration panel
  UI (HTML/JS).

## Caster/receiver predicate

Reuse the existing `Instance.rim_eligible` bool (true for hull-like ships + stations, false
for planets/asteroids):

- **Casters** (rendered into the shadow map): every visible `rim_eligible` instance in the
  Space pass.
- **Receivers** (sample the map in the hull shader): the same set.

Stations therefore also *receive* shadows, not just cast — one step beyond "ships receive,"
but strictly nicer and it removes a special case. The meaningful exclusion (planets/asteroids
kept out so they don't blow up the box) falls out of `rim_eligible` for free.

## Light matrix fitting (the core logic)

Computed once per frame in a GL-free pure function `compute_light_matrix(...)`:

1. **Center** on the player ship's world position.
2. **Half-extent** `R = clamp(k · player_bound_radius, R_min, R_max)` — capped radius.
   `k`, `R_min`, `R_max` are tunable constants (starting guess `k ≈ 3`). Ships/stations beyond
   `R` of the player are not shadowed.
3. **Light view:** `eye = center − light_dir · D`, looking along `light_dir`
   (`directional_dir_ws[0]`). Up vector derived from the light basis to avoid the degeneracy
   when the sun is straight "above" — **never a world-Z reference** (consistent with the
   no-global-up rule).
4. **Ortho box:** `±R` in X/Y. Depth: `near` pulled back toward the sun by a `caster_reach`
   distance so a station between sun and ship is still captured ("extend near plane toward the
   light"); `far` covers the receiver slab.
5. **Texel snap:** snap the box center in light-space X/Y to whole-texel increments
   (`2R / 2048`) so shadow edges don't crawl/shimmer as the player moves or the box recenters.

Output: `view_proj` and `texel_world_size`, handed to both the shadow pass and the hull shader.

### Why this survives BC's scale

With 1000–7000 GU sun distances, the eye pushback `D` is large, but the box **depth range**
stays tight — only `caster_reach + receiver slab`, on the order of ship/station sizes. 24-bit
depth precision stays healthy. The fitting (tight depth range), not the orthographic-ness,
does the precision work. Orthographic is the physically correct projection for a distant
massive sun (parallel rays); a perspective light frustum would be wrong regardless of cost.

## Hull shader integration (receiving)

In `opaque.vert` / `opaque.frag`:

- Vertex shader passes world-space position (already available for decals/rim) to the fragment
  stage.
- Fragment computes `shadow_coord = u_light_view_proj · vec4(world_pos, 1)`, then samples
  `u_shadow_map` (`sampler2DShadow`, dedicated texture unit) with a **3×3 PCF** kernel.
- `shadow_factor ∈ [0,1]` multiplies **only the `directional[0]` (sun) diffuse + specular**
  contribution. Ambient and any other lights are untouched — shadowed hull falls to
  ambient-lit, not black.
- Gated by `u_shadows_enabled` (from `dauntless_shadows::enabled()`) and applied only for hull
  instances. When off, the shader path is **byte-identical to today**.

New uniforms set in `draw_model()`: `u_shadows_enabled` (int), `u_light_view_proj` (mat4),
`u_shadow_map` (sampler), `u_shadow_texel` (float — drives PCF step + normal offset).

## Acne mitigation (three layers)

BC hulls have fine greebles, so a single technique is not enough:

1. **Normal-offset bias** — before projecting the receiver point into light space, push it
   along its world normal by `~k · u_shadow_texel`. Most robust single fix for detailed
   geometry; largely avoids the peter-panning a pure depth bias causes.
2. **Slope-scaled + constant depth bias** in the shadow pass (`glPolygonOffset`) — small,
   as a backstop.
3. **Cull-face choice in the depth pass** — front-face culling is the textbook acne cure, but
   the basis is **left-handed (det = −1, the X-flip in `_ship_world_matrix`)**, so the winding
   is already inverted. The culled face is a single named constant determined **empirically**
   against a known pitched ship, not assumed to be `GL_FRONT`, and documented. This is the one
   spot expecting a round of visual tuning.

## Performance

One extra depth-only render of 2–6 hull instances at `2048²`, plus one PCF sample per hull
fragment. Negligible at this scene scale — no bloom-style mip chain, no per-light cost (single
light). If `R_max` is hit in a large battle, shadows soften but cost is unchanged.

## Testing

GPU pixel output is not unit-testable, so verification splits three ways:

1. **C++ unit test for the fitting math** — `compute_light_matrix(...)` is extracted as a
   GL-free free function. Tests: box center tracks the player; half-extent honors the
   `R_min/R_max` clamp; texel-snap quantizes the center; a point known to sit between sun and
   ship lands inside the near-extended frustum.
2. **Python plumbing test** — `set_shadows_enabled` reaches the binding; `SettingsSnapshot.shadows_on`
   defaults `True`; the `toggle:shadows` config dispatch round-trips.
3. **Visual verification** (run skill, exterior view) — a ship casts a moving shadow on a
   second ship and self-shadows its own greebles; toggle-off matches stock; a pitched ship
   shows no acne (the cull-face tuning checkpoint).

## Build/rebuild notes

- Shader (`.vert`/`.frag`) edits require a **`cmake -B build -S .` reconfigure** before
  `cmake --build` (embedded-header regeneration; not auto-detected).
- Edits to `host_bindings.cc` need a `dauntless` rebuild (compiled into both the binary and the
  `_dauntless_host` module).

## File touch list (anticipated)

- `native/src/renderer/frame.cc` — `dauntless_shadows` namespace; light-matrix call;
  new uniforms in `draw_model()`.
- `native/src/renderer/shadow_map_target.{h,cc}` — new depth FBO (new files).
- `native/src/renderer/shadow_pass.{h,cc}` — new depth-only pass (new files).
- `native/src/renderer/shaders/shadow_depth.vert` (+ trivial fragment) — new.
- `native/src/renderer/shaders/opaque.vert` / `opaque.frag` — receive + PCF sample.
- `native/src/renderer/light_matrix.{h,cc}` — GL-free `compute_light_matrix` (new, testable).
- `native/src/host/host_bindings.cc` — pass ownership/construction in `init()`; per-frame
  shadow compute+render; `shadows_set_enabled` binding.
- `engine/renderer.py` — `set_shadows_enabled` wrapper.
- `engine/ui/configuration_panel.py` — `shadows_on` field + `toggle:shadows` dispatch.
- `engine/host_loop.py` — initial setting + applier wiring.
- CEF config panel UI (HTML/JS) — "Shadows" checkbox row.
- Tests: C++ fitting-math unit test; Python toggle-plumbing test.
