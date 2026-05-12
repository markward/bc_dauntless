# Shield-glow render pass — design

**Date:** 2026-05-12
**Status:** Design approved; implementation pending
**Related work:** TGColorA + consumer tracker (commit 513dd75); follow-on spec for tractor/phaser beam render pass to come.

## Goal

Render BC's hit-flash shield effect: on weapon impact, a colored hex-pattern bubble flares up around the impact point on the ship's shield mesh, tinted by the ship's `ShieldGlowColor`, decaying over ~1 s. At rest the shield is invisible. Default bubble silhouette is an AABB-fit ellipsoid; opted-in ships (sovereign) get a hull-inflated silhouette ("skin shielding").

## Background

`ShieldProperty.SetShieldGlowColor(TGColorA)` is called by 35 hardpoint files across every shielded ship class in the SDK (427 calls × 30 missions in the gameloop harness). The color value is now stored in the Phase 1 `ShieldProperty` shim data-bag at `_data[("ShieldGlowColor", ())]` (commit 513dd75) but nothing reads it. The renderer (`native/src/renderer/`) has no shield pass — only `opaque`, `sun`, `dust`, `backdrop`. This spec adds the consumer.

## Architecture

New file `native/src/renderer/shield_pass.cc`. Called from `frame.cc` in the order:

```
opaque ships → shield → dust → backdrop
```

Shield runs in additive blend, reads depth, doesn't write it, so dust/backdrop composite correctly.

### Data flow (Python → C++)

Two new host bindings in `native/src/host/host_bindings.cc`:

```cpp
host.shield_register(instance_id, mode, decay, default_color_rgba)
host.shield_hit(instance_id, world_point, rgba, intensity=1.0)
```

`shield_register` is called once per ship after its hardpoint imports — Python glue reads `ShieldProperty._data[("SkinShielding", ())]`, `_data[("ShieldGlowDecay", ())]`, and `_data[("ShieldGlowColor", ())]`, then pushes them to C++. The renderer stores a per-instance `ShieldState`:

```cpp
struct ShieldState {
    enum class Mode { Ellipsoid, Skin } mode;
    float decay_seconds;          // default 1.0
    glm::vec4 default_color;      // from ShieldGlowColor
    glm::vec3 aabb_center;        // ship-local
    glm::vec3 aabb_half_extents;  // ship-local
    Hit hits[8];                  // ring buffer
};

struct Hit {
    glm::vec3 point_world;
    glm::vec4 color_rgba;
    float intensity_at_t0;
    double t0_seconds;
    int texture_index;            // 0..3, picks shieldhit0N.TGA
};
```

`shield_hit` resolves color (substitute `default_color` when caller passes `(0,0,0,0)`), picks a slot (first empty, else dimmest), stores the hit with a random `texture_index ∈ [0..3]` and `t0 = now`.

### Per-frame draw

For each `ShieldState` with at least one live hit (intensity > 0.01 after decay):

1. Decay each slot: `current_intensity = intensity_at_t0 × exp(-(now - t0) / decay_seconds)`. Mark slots with `current_intensity < 0.01` empty.
2. Bind ellipsoid VAO (shared unit sphere) or skin VAO (per-NIF cached) based on `mode`.
3. Set uniforms: model matrix (see below), hit-list arrays, `hit_radius = max(aabb_half_extents) × 0.25`, `hex_tile_rate = 1/5` (one hex per ~5 m world space).
4. Draw.

Model matrix:
- **Ellipsoid:** `ship_world × translate(aabb_center) × scale(aabb_half_extents × 1.1)`
- **Skin:** `ship_world` (verts already in ship-local space and pre-inflated).

### Shader

Vertex stage: outputs both `world_position` (for hit-distance math) and `ship_local_position` — the bubble vertex in ship-local space, pre-`ship_world` transform. For ellipsoid: `ship_local_position = sphere_vert × ellipsoid_scale + aabb_center`. For skin: `ship_local_position = pre-inflated hull vert + normal × inflate_distance`. This pins the hex pattern to the ship (no swimming-hex artifact when the ship moves) and uses ship-local units (= world meters at 1:1 scale) for the tile rate.

Fragment stage:
1. Compute triplanar hex UV: `uv = triplanar(ship_local_position × hex_tile_rate, ship_local_normal)`. Triplanar blends the three axis-aligned 2D projections by `abs(normal)`, avoiding the seam a single-axis projection would have.
2. Sample `shieldhit_array[texture_index]` per active hit using the same UV (textures are interchangeable hex variants).
3. For each active hit: `falloff = smoothstep(hit_radius, 0, distance(world_pos, hit.point))`, accumulate `color += hit.color.rgb × hit.intensity × falloff`, `alpha += hex_sample.a × hit.intensity × falloff`.
4. Output `gl_FragColor = vec4(color × hex_sample.rgb, alpha)`.

Blend state: `glBlendFunc(GL_SRC_ALPHA, GL_ONE)` — alpha-weighted additive. Each hit's contribution is gated by its accumulated alpha (so fading hits contribute less); destination is added unchanged so multiple hits brighten the same pixel.

## Mesh generation

### Ellipsoid (default)

- Reuse existing `sphere_mesh.cc` unit sphere.
- AABB derived once per NIF at load time by scanning `assets/mesh.h::vertices`. Cached on the asset, not per-instance.
- One sphere mesh, scaled per-draw. All ellipsoid-mode ships share the VAO.

### Skin (opt-in)

- Per unique NIF, cached: build `SkinShieldMesh`:
  - Same triangle topology as hull.
  - Positions = `hull_pos + hull_normal × inflate_distance`.
  - `inflate_distance = max(aabb_half_extents) × 0.05` (≈5% of the ship's largest axis).
- All instances of the same NIF share the GPU buffer.
- Triplanar mapping (not NIF UVs) so the hex pattern tiles uniformly regardless of hull texture layout.

## Python side

### `ShieldProperty.SetSkinShielding(value)`

No new code required. The Phase 1 shim's generic `__getattr__` data-bag at [engine/appc/properties.py:24-46](../../engine/appc/properties.py#L24-L46) auto-handles arbitrary `Set*` calls. Hardpoints opt in by calling `ShieldGenerator.SetSkinShielding(1)`. The Python glue layer reads `_data[("SkinShielding", ())]` at ship-register time and pushes the mode to C++.

### Sovereign hardpoint shim

Copy `sdk/Build/scripts/ships/Hardpoints/sovereign.py` → `<root>/ships/Hardpoints/sovereign.py`. Add `ShieldGenerator.SetSkinShielding(1)` after the existing shield-setup block. Requires empty `<root>/ships/__init__.py` and `<root>/ships/Hardpoints/__init__.py` so Python's standard finder picks up the dotted import path. Per CLAUDE.md this is the second shadowed-SDK location after `LoadBridge.py`; a third triggers consolidation to a `shims/` directory.

### Python glue (`engine/renderer.py` or new `engine/shields.py`)

- On ship instance creation, after the hardpoint module has executed, call `host.shield_register(instance_id, mode, decay, default_color)`. Pull values from the `ShieldProperty` data-bag.
- On weapon impact (damage-system Phase 2 work; out of scope for this spec), call `host.shield_hit(...)` with the impact point and per-weapon flash color.
- Debug fallback for verification before damage-system wiring exists: F9 keypress fires `host.shield_hit(player_target, player_target_center, (0,0,0,0), 1.0)`.

## Testing

### Headless unit tests

- `tests/unit/test_shield_property_skin.py`:
  - `ShieldProperty().SetSkinShielding(1)` stores `1` at `_data[("SkinShielding", ())]`.
  - Importing the sovereign shim results in skin mode being set on the ShieldGenerator.
  - Importing akira/galaxy hardpoints leaves `SkinShielding` absent (ellipsoid mode).

- `native/tests/test_shield_state.cc`:
  - `push_hit → tick(dt) → active hit list` decays with the right exp curve.
  - Ring buffer slot reuse: when full, the dimmest slot is evicted.
  - Color resolution: `(0,0,0,0)` substitutes `default_color`; nonzero passes through.
  - Texture index is stable for a slot's lifetime (not re-randomized per frame).

- `native/tests/test_aabb_extraction.cc`:
  - Given a known mesh, `compute_aabb(mesh.vertices)` returns the expected center and half-extents.

- `native/tests/test_skin_inflate.cc`:
  - Given a hull mesh, `build_skin_shield_mesh(hull, inflate=0.05)` produces verts pushed outward along normals, identical triangle topology, no degenerate triangles.

### Visual verification

Per memory note (`feedback_macos_headless_pixel_tests.md`), macOS GLFW hidden windows don't reliably present BACK→FRONT swaps — `read_pixel` returns garbage. Trust the visible binary, not pixel scans.

Manual checklist via `./build/open_stbc` with F9 debug binding:

- Default ship (e.g. Galaxy player ship): F9 fires hit at ship center → ellipsoid bubble flash sized roughly to ship AABB, fades over ~1 s.
- Sovereign: F9 → hull-conforming flash silhouette, not ellipsoid.
- Rapid repeated F9 presses on same ship: overlapping flashes brighten additively, fade independently.
- Hit color matches `ShieldGeneratorShieldGlowColor` from the hardpoint (Federation blue for Fed ships, etc.).
- Two ships near each other each show their own bubble; bubbles don't bleed into each other.

## Out of scope

- Damage-system integration (real impact points from weapon hits). F9 debug fires synthetic hits until the damage system lands.
- Persistent low-shield warning bubble.
- Shield depletion fade (alpha modulated by shield strength).
- Tactical-view shield outline.
- Per-quadrant shields (front/rear/top/bottom/left/right). `SetMaxShields(direction, value)` is stored but unused by the render pass. One bubble per ship.
- Beam render pass (phaser, tractor) — separate spec, next round.

## Implementation phases

Each phase is independently reviewable and ships a working state.

1. **C++ foundation (no GL).** `ShieldState`, ring buffer, AABB extraction, skin-mesh inflate. `native/tests/` unit tests pass. No host bindings yet.
2. **Ellipsoid render pass + bindings + F9 debug.** `shield_pass.cc`, shader, `host.shield_register`, `host.shield_hit`, F9 keybinding. Visible bubble flash on every ship. All ships render in ellipsoid mode.
3. **Sovereign shim + `SetSkinShielding` Python tests.** Project-root shadow ships/Hardpoints/sovereign.py with the opt-in call. Phase 1 tests verify the data-bag plumbing. Renderer still draws ellipsoid for sovereign — flag is plumbed but not yet honored.
4. **Skin-mesh path.** NIF-aware mesh inflate + per-NIF cache, mode dispatch in `shield_pass`, sovereign now renders hull-conforming silhouette.

## Open questions

None blocking. Tunables (`hex_tile_rate`, `hit_radius` multiplier, `inflate_distance` multiplier, decay default) are settled by feel during phase 2.
