# Hull Volume Field Transport Implementation Plan (Plan 2a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the per-instance signed-distance field the thing `opaque.frag` clips the hull against, replacing the 24-sphere uniform array — and prove on screen that the transport works and looks right.

**Architecture:** Each damaged instance gets a mutable CPU copy of its baked field, carved by the same deposits that today feed `HullCarveField`. The field is packed into a 2D texture atlas (Z-slices tiled) and uploaded when dirty. `opaque.frag` samples it and discards below the surface threshold. Everything else — the breach scoop, the decals, the framework lattice — keeps working off the existing sphere list, unchanged.

**Tech Stack:** C++20 (`native/src/voxel`, `native/src/renderer`), GLSL 410, GoogleTest, pybind11, Python 3.

**Spec:** `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` (§6, §7)

## Why this slice, and what it deliberately leaves alone

The spec's §6–§7 is a large simultaneous change. The two things that could sink the whole approach are knowable much earlier:

1. **Does the transport survive this Mac's GL driver?** We measured that a `sampler2D` in `opaque.frag` is clean and a `sampler3D` corrupts shading across 16 tests. That was a *disabled-path* probe with a dummy fetch. It is not the same as a real per-instance atlas sampled per fragment on a live hull.
2. **Does a field-clipped hole look better than a sphere-clipped one?** The visible win is that overlapping carves merge into one arbitrary cavity and the 24-carve ceiling disappears — during a death cascade the current code evicts its own damage mid-sequence, so a dying ship visibly heals.

Both are answered by replacing only the hull clip. If the answer is no, we have spent one plan rather than three.

**Explicitly NOT in this plan** (they follow in 2b, once this is proven on screen):

- The `dent` brush and collision deformation.
- Rebuilding the breach interior on the field. The scoop keeps masking on the static source volume and keeps using the sphere list, so its shape and the hull hole stay close *by construction* — see Global Constraint 6.
- Deleting `carve_has_backing` / `carve_cavity_depth_cells`.
- The persisted quality setting (spec §10). `kDefaultQuality` stays a constant.
- Connected components, breakables, dents.

## Global Constraints

Every task's requirements implicitly include these.

1. **`opaque.frag` may contain NO `sampler3D`.** Measured: one there corrupts shading across `TangentBasisTest`, `ConeLightFrameTest`, `ExplosionLightFrameTest` and `CloakAmbientParityTest` even on a branch that never executes. The field reaches that shader as a **`sampler2D` atlas**. A `sampler3D` is fine in `breach.frag`, which already has one.
2. **A new sampler must be pointed at a free texture unit on EVERY path**, enabled or not. A sampler left on unit 0 collides with the bound 2D base-colour texture and returns `GL_INVALID_OPERATION` on every draw. Units in the opaque pass today: 0 base, 1 glow, 2 specular, 3 damage decal, 4 (used), 5 shadow map.
3. **An undamaged instance must take the stock path with zero added per-fragment cost**, exactly as `u_carve_enabled == 0` does today. Byte-identical rendering for an undamaged ship is a requirement, not an aspiration.
4. **Volumes are in MODEL UNITS.** 1 model unit = 0.01 GU (`BC_MODEL_SCALE`). Carve radii arrive in GU and are divided by the instance scale exactly as `hull_carve_add` already does.
5. **The value `renderer::hull_volume_resolution()` returns is BC's authored `SetDamageResolution`, NOT a cell size.** The cell size is `authored_res / quality`. Passing the authored value where a cell size belongs bakes every hull `quality`× too coarse, silently.
6. **The hull hole and the breach scoop must not drift.** The scoop still derives from the sphere list this plan does not remove, so the field brush must carve the SAME oblate shape `opaque.frag` computes today — full lateral radius, `kDepthFactor` along the surface normal. Do not "improve" the shape in this plan; that is a separate, live-tested change.
7. **Never spell `game` or `sdk` as a path segment**; ask `engine/paths.py`. **Never capture a path at import.** Enforced by `tests/unit/test_path_indirection.py`.
8. **One build tree:** `cmake -B build -S . && cmake --build build -j`. Never run `cmake` inside `native/`. **Shader edits need a reconfigure** — run `cmake -B build -S .` before building after touching a `.frag`/`.vert`.
9. **Shared checkout.** Stage with explicit pathspecs. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`.
10. **Gate:** `./scripts/check_tests.sh` exit 0; only `test_shield_level_change_announces` is baselined. **After any shader change, run the FULL `renderer_tests` binary**, not a filter — the `sampler3D` damage showed up in four suites the obvious filter would have missed.
11. Commit messages end with:
    `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `native/src/voxel/include/voxel/field_brush.h` | `field_carve_oblate` — the subtractive CSG brush |
| `native/src/voxel/src/field_brush.cc` | its implementation |
| `native/src/voxel/include/voxel/field_atlas.h` | `AtlasLayout`, `atlas_layout_for`, `pack_field_to_atlas` |
| `native/src/voxel/src/field_atlas.cc` | Z-slice tiling with a replicated 1-texel border |
| `native/src/renderer/include/renderer/instance_field_cache.h` | per-instance mutable field + its GL atlas texture |
| `native/src/renderer/instance_field_cache.cc` | lazy copy-on-first-carve, dirty upload |
| `native/tests/voxel/field_brush_test.cc` | brush CSG correctness |
| `native/tests/voxel/field_atlas_test.cc` | layout, packing, border replication |
| `native/tests/renderer/instance_field_cache_test.cc` | GL upload, lifetime, eviction |
| `native/tests/renderer/hull_field_clip_test.cc` | the shader clips against the atlas |

**Modified**

| File | Change |
|---|---|
| `native/src/renderer/shaders/opaque.frag` | sample the atlas; replace the sphere loop |
| `native/src/renderer/frame.cc` | bind the atlas, set its uniforms, keep `u_carve_invert` |
| `native/src/renderer/include/renderer/frame.h` | pass the cache through |
| `native/src/host/host_bindings.cc` | `hull_volume_set_cache_root`; carve into the field |
| `native/src/renderer/carve_field_cache.{h,cc}` | own a `voxel::HullVolumeCache` behind the cache root |
| `engine/renderer.py` | `hull_volume_set_cache_root` façade |
| `engine/host_loop.py` | push the cache root at boot |
| `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`, `native/tests/renderer/CMakeLists.txt` | register new sources and tests |
| `tests/unit/test_hull_volume_cache_root.py` | the root is resolved at use, never at import |

---

## Task 1: The subtractive brush

**Files:**
- Create: `native/src/voxel/include/voxel/field_brush.h`, `native/src/voxel/src/field_brush.cc`, `native/tests/voxel/field_brush_test.cc`
- Modify: `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: `voxel::DistanceField` (`voxel/distance_field.h`) — `dims`, `origin`, `cell`, `scale`, `dist`, `index()`, `distance_at()`, `empty()`.
- Produces:
  ```cpp
  namespace voxel {
  inline constexpr float kCarveDepthFactor = 0.45f;   // matches opaque.frag kDepthFactor
  void field_carve_oblate(DistanceField& f,
                          const glm::vec3& center_body,
                          const glm::vec3& normal_body,
                          float radius);
  }
  ```

**Why an oblate and not a sphere:** the breach scoop still derives from the sphere list this plan does not touch, and `opaque.frag` today clips an oblate — full lateral radius `r`, `kDepthFactor * r` along the hit normal. Carving the same shape keeps the hole and the scoop aligned by construction (Global Constraint 6). The visible win of this plan is the *union* of overlapping carves and the removal of the 24 ceiling, not a new shape.

- [ ] **Step 1: Write the failing test**

Create `native/tests/voxel/field_brush_test.cc`:

```cpp
// native/tests/voxel/field_brush_test.cc
//
// The subtractive brush. CSG subtraction on a signed distance field is
// d_new = max(d_old, -d_brush): a point is in (hull MINUS brush) iff it is
// inside the hull AND outside the brush.
//
// The brush is an OBLATE ellipsoid, not a sphere -- full lateral radius, and
// kCarveDepthFactor of it along the hit normal. That is the shape opaque.frag
// already clips, and the breach scoop still derives from the sphere list this
// plan does not remove, so carving the same shape keeps hole and scoop aligned.
#include <gtest/gtest.h>

#include <voxel/distance_field.h>
#include <voxel/field_brush.h>

#include <cmath>
#include <vector>

namespace {

// A solid block: every cell reads -20 model units (deep inside), cell 1 unit,
// origin at 0, so cell (i,j,k)'s centre is (i+0.5, j+0.5, k+0.5).
voxel::DistanceField solid_block(int n) {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(n, n, n);
    f.origin = glm::vec3(0.0f);
    f.cell   = glm::vec3(1.0f);
    f.scale  = 0.25f;                       // 127 * 0.25 ~= 31.75 units of range
    f.dist.assign(static_cast<std::size_t>(n) * n * n,
                  static_cast<std::int8_t>(-80));   // -20 units
    return f;
}

glm::ivec3 cell_of(const voxel::DistanceField& f, glm::vec3 p) {
    const glm::vec3 g = (p - f.origin) / f.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}

const glm::vec3 kUp(0.0f, 0.0f, 1.0f);

}  // namespace

TEST(FieldBrush, CentreOfTheCarveBecomesOutside) {
    voxel::DistanceField f = solid_block(40);
    voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    const glm::ivec3 c = cell_of(f, glm::vec3(20.0f, 20.0f, 20.0f));
    EXPECT_GT(f.distance_at(c.x, c.y, c.z), 0.0f)
        << "the carve centre must read as outside the hull";
}

TEST(FieldBrush, MaterialWellOutsideTheCarveIsUntouched) {
    voxel::DistanceField f = solid_block(40);
    const glm::ivec3 far = cell_of(f, glm::vec3(35.0f, 35.0f, 20.0f));
    const float before = f.distance_at(far.x, far.y, far.z);
    voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    EXPECT_FLOAT_EQ(f.distance_at(far.x, far.y, far.z), before)
        << "a carve must not modify material outside its own reach";
}

TEST(FieldBrush, ShapeIsOblateNotSpherical) {
    // Lateral reach is the full radius; along the normal it is kCarveDepthFactor
    // of it. At 0.8*r laterally the point is carved; at 0.8*r along the normal
    // (which exceeds 0.45*r) it is not.
    voxel::DistanceField f = solid_block(40);
    const glm::vec3 c(20.0f, 20.0f, 20.0f);
    const float r = 8.0f;
    voxel::field_carve_oblate(f, c, kUp, r);

    const glm::ivec3 lat = cell_of(f, c + glm::vec3(0.8f * r, 0.0f, 0.0f));
    EXPECT_GT(f.distance_at(lat.x, lat.y, lat.z), 0.0f) << "lateral reach too short";

    const glm::ivec3 along = cell_of(f, c + kUp * (0.8f * r));
    EXPECT_LT(f.distance_at(along.x, along.y, along.z), 0.0f)
        << "carve reaches too deep along the normal -- it is not oblate";
}

TEST(FieldBrush, OverlappingCarvesUnionRatherThanReplace) {
    // The whole point of the field over a sphere list: two overlapping carves
    // leave ONE cavity, and neither undoes the other.
    voxel::DistanceField f = solid_block(40);
    voxel::field_carve_oblate(f, glm::vec3(16.0f, 20.0f, 20.0f), kUp, 5.0f);
    voxel::field_carve_oblate(f, glm::vec3(24.0f, 20.0f, 20.0f), kUp, 5.0f);
    for (float x : {16.0f, 20.0f, 24.0f}) {
        const glm::ivec3 c = cell_of(f, glm::vec3(x, 20.0f, 20.0f));
        EXPECT_GT(f.distance_at(c.x, c.y, c.z), 0.0f)
            << "x=" << x << " should be inside the merged cavity";
    }
}

TEST(FieldBrush, CarvingIsMonotonic) {
    // Re-carving the same place must never restore material.
    voxel::DistanceField f = solid_block(40);
    const glm::vec3 c(20.0f, 20.0f, 20.0f);
    voxel::field_carve_oblate(f, c, kUp, 8.0f);
    const glm::ivec3 q = cell_of(f, c + glm::vec3(6.0f, 0.0f, 0.0f));
    const float after_big = f.distance_at(q.x, q.y, q.z);
    voxel::field_carve_oblate(f, c, kUp, 2.0f);      // smaller, same centre
    EXPECT_GE(f.distance_at(q.x, q.y, q.z), after_big)
        << "a later smaller carve must not heal the hull";
}

TEST(FieldBrush, EmptyFieldIsANoOp) {
    voxel::DistanceField f;                  // dims {0,0,0}
    voxel::field_carve_oblate(f, glm::vec3(0.0f), kUp, 5.0f);
    EXPECT_TRUE(f.empty());
}

TEST(FieldBrush, NonPositiveRadiusIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, 0.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, -3.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrush, DegenerateNormalDoesNotProduceNaN) {
    voxel::DistanceField f = solid_block(20);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), glm::vec3(0.0f), 4.0f);
    for (std::int8_t v : f.dist) EXPECT_TRUE(v >= -127 && v <= 127);
}

TEST(FieldBrush, CarveOutsideTheGridDoesNotWriteOutOfBounds) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(500.0f, 500.0f, 500.0f), kUp, 5.0f);
    EXPECT_EQ(f.dist, before);
}
```

Register `field_brush_test.cc` in `native/tests/voxel/CMakeLists.txt`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
```
Expected: compile FAILS — `voxel/field_brush.h` does not exist.

- [ ] **Step 3: Write the header**

Create `native/src/voxel/include/voxel/field_brush.h`:

```cpp
// native/src/voxel/include/voxel/field_brush.h
#pragma once

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// Depth of a carve along the hit normal, as a fraction of its lateral radius.
/// MUST equal opaque.frag's kDepthFactor: the breach scoop still derives from
/// the sphere list, so hole and scoop only stay aligned while both use this
/// same oblate. Change one, change both, and live-test the pair.
inline constexpr float kCarveDepthFactor = 0.45f;

/// Subtract an oblate breach from the hull: full lateral radius `radius`,
/// kCarveDepthFactor * radius along `normal_body`, centred on the hull surface.
///
/// CSG subtraction on a signed distance field is `d = max(d, -d_brush)`, which
/// is monotonic: a carve can only ever remove material, never restore it. That
/// is what lets overlapping carves merge into one cavity instead of evicting
/// each other, which the fixed 24-slot sphere array could not do.
///
/// All arguments are body frame, MODEL UNITS. A degenerate normal falls back to
/// +Z rather than producing NaN. Empty field, non-positive radius, or a carve
/// entirely off the grid are all no-ops.
void field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius);

}  // namespace voxel
```

- [ ] **Step 4: Implement it**

Create `native/src/voxel/src/field_brush.cc`:

```cpp
// native/src/voxel/src/field_brush.cc
#include <voxel/field_brush.h>

#include <algorithm>
#include <cmath>

namespace voxel {

void field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius) {
    if (f.empty()) return;
    if (!(radius > 0.0f)) return;
    if (!(f.scale > 0.0f)) return;

    glm::vec3 n = normal_body;
    const float nl = glm::length(n);
    n = (nl > 1e-4f) ? n / nl : glm::vec3(0.0f, 0.0f, 1.0f);

    const float depth = kCarveDepthFactor * radius;

    // Only cells within the brush's AABB can change. The lateral reach is the
    // full radius on every axis, so a radius-sized box bounds the oblate.
    const glm::vec3 lo = center_body - glm::vec3(radius);
    const glm::vec3 hi = center_body + glm::vec3(radius);
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)),
                          int(std::floor(g.z)));
    };
    glm::ivec3 c0 = to_cell(lo);
    glm::ivec3 c1 = to_cell(hi);
    c0 = glm::max(c0, glm::ivec3(0));
    c1 = glm::min(c1, f.dims - 1);
    if (c0.x > c1.x || c0.y > c1.y || c0.z > c1.z) return;   // wholly off-grid

    for (int z = c0.z; z <= c1.z; ++z)
    for (int y = c0.y; y <= c1.y; ++y)
    for (int x = c0.x; x <= c1.x; ++x) {
        const glm::vec3 p =
            f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        const glm::vec3 v = p - center_body;
        const float along   = glm::dot(v, n);
        const glm::vec3 lat = v - along * n;
        const float ld      = glm::length(lat);

        // Signed distance to the oblate, scaled back to model units. Dividing
        // each axis by its own half-extent turns the ellipsoid into a unit
        // sphere; multiplying the result by the SMALLEST half-extent keeps the
        // value a conservative (never over-deep) distance, which is what the
        // max() below needs to stay monotonic.
        const float u = ld / radius;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(radius, depth);

        const std::size_t i = f.index(x, y, z);
        const float d_old = static_cast<float>(f.dist[i]) * f.scale;
        const float d_new = std::max(d_old, -d_brush);

        float q = std::round(d_new / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[i] = static_cast<std::int8_t>(q);
    }
}

}  // namespace voxel
```

Add `src/field_brush.cc` to `add_library(voxel STATIC ...)` in `native/src/voxel/CMakeLists.txt`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrush.*'
./build/native/tests/voxel/voxel_tests
```
Expected: all nine PASS, whole binary green.

- [ ] **Step 6: Commit**

```bash
git add native/src/voxel/include/voxel/field_brush.h native/src/voxel/src/field_brush.cc native/tests/voxel/field_brush_test.cc native/src/voxel/CMakeLists.txt native/tests/voxel/CMakeLists.txt
git commit -m "feat(voxel): subtractive oblate brush for hull distance fields

CSG subtraction d = max(d, -d_brush): monotonic, so a carve can only remove
material. That is what lets overlapping carves merge into one cavity instead
of evicting each other the way the fixed 24-slot sphere array does -- during
a death cascade the current code evicts its own damage mid-sequence and a
dying ship visibly heals.

Oblate, not spherical, matching opaque.frag's kDepthFactor: the breach scoop
still derives from the sphere list, so hole and scoop stay aligned only while
both use the same shape.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Atlas packing

A 3D field must reach `opaque.frag` as a `sampler2D` (Global Constraint 1). Z-slices are tiled into a 2D grid, each tile carrying a replicated 1-texel border so hardware bilinear filtering inside a slice cannot bleed across a tile seam.

**Files:**
- Create: `native/src/voxel/include/voxel/field_atlas.h`, `native/src/voxel/src/field_atlas.cc`, `native/tests/voxel/field_atlas_test.cc`
- Modify: `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: `voxel::DistanceField`.
- Produces:
  ```cpp
  namespace voxel {
  struct AtlasLayout {
      int tile_w = 0, tile_h = 0;      // dims.x + 2, dims.y + 2 (1-texel border)
      int tiles_x = 0, tiles_y = 0;    // slice grid
      int width = 0, height = 0;       // tile_w * tiles_x, tile_h * tiles_y
      int slices = 0;                  // dims.z
      bool valid() const { return width > 0 && height > 0 && slices > 0; }
  };
  AtlasLayout atlas_layout_for(const glm::ivec3& dims);
  std::vector<std::uint8_t> pack_field_to_atlas(const DistanceField& f,
                                                const AtlasLayout& l);
  }
  ```
  Payload is `GL_R8`: the signed byte `d` is stored as `d + 128`, so 128 is the surface. The shader compares `texel - 0.5` against zero.

**Tests to write first** (`field_atlas_test.cc`), each asserting a stated behaviour:

- `LayoutIsRoughlySquare` — for `dims.z = 37`, `tiles_x * tiles_y >= 37` and neither dimension exceeds the other by more than one tile.
- `LayoutCoversEverySlice` — `tiles_x * tiles_y >= dims.z` for `dims.z` of 1, 2, 16, 37, 66.
- `DegenerateDimsYieldAnInvalidLayout` — a zero component gives `valid() == false`, and `pack_field_to_atlas` returns empty.
- `PackedSizeMatchesTheLayout` — `bytes.size() == width * height`.
- `CellValueRoundTripsThroughTheAtlas` — construct a field with a known distinct value per cell; for a sample of cells, compute the atlas texel index from the layout and assert it holds `d + 128`.
- `BorderReplicatesTheEdgeTexel` — a tile's border texel equals its nearest interior texel, on all four edges and the corners. **This is the test that matters**: without it, hardware bilinear at a slice edge samples a neighbouring slice's data and the hull grows holes at tile seams.
- `SlicesDoNotBleedIntoEachOther` — two adjacent slices given uniformly different values stay separated by their borders.
- `EmptyFieldPacksToNothing` — an empty field yields an empty buffer, not a crash.

**Implementation notes for the engineer:**
- `tiles_x = ceil(sqrt(dims.z))`, `tiles_y = ceil(dims.z / tiles_x)`.
- Tile `s` occupies origin `((s % tiles_x) * tile_w, (s / tiles_x) * tile_h)`.
- Interior texel `(x, y)` of slice `s` sits at `(tile_ox + 1 + x, tile_oy + 1 + y)`.
- Fill the border by clamping the source coordinate into `[0, dims-1]` — the same rule `GL_CLAMP_TO_EDGE` would apply within a slice.
- Unused tiles (when `tiles_x * tiles_y > dims.z`) are filled with `128 + 127` (fully outside), so a sampling bug there reads as empty space rather than as hull.

Commit as `feat(voxel): pack a distance field into a 2D slice atlas`.

---

## Task 3: Cache root plumbing

Spec §4 requires the cache root to be resolved through `engine/paths.py` **at use, never at import**. Nothing in plan 1 exercised that, so it is untested surface. This task closes it and gives `CarveFieldCache` a real `HullVolumeCache`.

**Files:**
- Modify: `native/src/renderer/include/renderer/carve_field_cache.h`, `native/src/renderer/carve_field_cache.cc`, `native/src/host/host_bindings.cc`, `engine/renderer.py`, `engine/host_loop.py`
- Create: `tests/unit/test_hull_volume_cache_root.py`

**Interfaces:**
- Produces:
  - `void renderer::set_hull_volume_cache_root(const std::filesystem::path&)`
  - `voxel::HullVolumeCache& renderer::hull_volume_cache()` — constructed on first use with the configured root; an unset root yields a cache rooted at a temp path so nothing crashes.
  - binding `_dauntless_host.hull_volume_set_cache_root(root: str) -> None`
  - `engine.renderer.hull_volume_set_cache_root(root)` — **no `hasattr` guard** (Constraint: `host_loop.py:4780` documents a feature that shipped inert because of one).

**Follow the `set_game_root` precedent exactly** — `host_bindings.cc:1682` and `engine/renderer.py:206` are the model, including the alphabetical position in `_REQUIRED_BINDINGS`.

**Python side:** a small helper that computes the root as `<project root>/cache/hull_volumes` — matching the existing `cache/icons/...` convention in `engine/ui/weapon_icons.py`, and already covered by the `cache/` line in `.gitignore`. Push it once at boot, next to the other renderer configuration.

**Tests** (`tests/unit/test_hull_volume_cache_root.py`):
- The root ends in `cache/hull_volumes`.
- It is computed **at call time**, not captured at import: monkeypatch the project-root source, call again, assert the value changed.
- The literal segments `game` and `sdk` do not appear in it.
- A renderer failure propagates (matching the `push_resolution` contract established in plan 1 — the caller's `log_swallowed` is the visibility mechanism).

Commit as `feat(renderer): resolve the hull-volume cache root through paths`.

---

## Task 4: Per-instance field cache

**Files:**
- Create: `native/src/renderer/include/renderer/instance_field_cache.h`, `native/src/renderer/instance_field_cache.cc`, `native/tests/renderer/instance_field_cache_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `voxel::DistanceField`, `voxel::field_carve_oblate` (Task 1), `voxel::AtlasLayout`/`pack_field_to_atlas` (Task 2), `renderer::hull_volume_cache()` (Task 3), `scenegraph::InstanceId`.
- Produces:
  ```cpp
  namespace renderer {
  class InstanceFieldCache {
  public:
      struct Entry {
          unsigned int tex2d = 0;        // GL_R8 atlas
          voxel::AtlasLayout layout;
          glm::vec3 origin{0.0f};
          glm::vec3 cell{1.0f};
          glm::ivec3 dims{0};
          float scale = 1.0f;
      };
      ~InstanceFieldCache();
      /// Carve into this instance's field, creating it (copy-on-first-carve
      /// from the baked cache) if it does not exist yet. No-op when the hull
      /// has no baked field.
      void carve(scenegraph::InstanceId id, const std::filesystem::path& source,
                 float authored_res, const glm::vec3& center_body,
                 const glm::vec3& normal_body, float radius);
      /// The uploaded atlas for this instance, or nullptr if it has none.
      /// Uploads lazily when dirty. Must be called with a GL context current.
      const Entry* get(scenegraph::InstanceId id);
      void forget(scenegraph::InstanceId id);      // instance destroyed
      std::size_t size() const;
  };
  }
  ```

**Ownership contract:** owns GL textures, so it must be constructed and destroyed while a GL context is current — the same contract `CarveFieldCache` documents.

**Behaviours to test** (`instance_field_cache_test.cc`, using the existing GL fixture pattern from `carve_backing_test.cc`'s neighbours):
- An instance that was never carved has no entry (`get` returns nullptr) — **so an undamaged ship costs nothing** (Global Constraint 3).
- The first carve creates an entry whose `dims`/`origin`/`cell` match the baked field.
- `get` twice without an intervening carve uploads once (expose an `uploads()` counter for the same reason plan 1's cache exposes `bakes()` — a cache that silently re-uploads every frame is otherwise indistinguishable from one that works).
- A carve marks it dirty and the next `get` re-uploads.
- `forget` releases the entry and its texture.
- A hull with no baked field never creates an entry.
- Two instances of the same hull get independent fields — carving one must not damage the other. **This is the per-instance guarantee**; get it wrong and every Galaxy in the sector shares one ship's damage.

Commit as `feat(renderer): per-instance mutable hull field with a GL atlas`.

---

## Task 5: Clip the hull against the field

The load-bearing task. **Read Global Constraints 1, 2, 3 and 10 again before starting.**

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`, `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`
- Create: `native/tests/renderer/hull_field_clip_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Shader change.** Add, beside the existing carve uniforms:

```glsl
uniform sampler2D u_hull_field;      // R8 slice atlas; 128 = the hull surface
uniform int   u_hull_field_enabled;  // 0 = stock path, zero per-fragment cost
uniform vec3  u_hull_field_origin;   // body frame
uniform vec3  u_hull_field_cell;     // model units per cell
uniform vec3  u_hull_field_dims;     // float, to avoid int division in the shader
uniform vec2  u_hull_field_tiles;    // tiles_x, tiles_y
uniform vec2  u_hull_field_texel;    // 1 / atlas size
```

Sampling is a helper that converts a body-frame point to a cell coordinate, samples the two bracketing Z-slices with hardware bilinear (safe because Task 2 replicated the tile borders), and lerps. Keep it in one function so the clip and any later consumer cannot drift.

The clip replaces the `for (int i = 0; i < u_carve_count; i++)` body: discard when the sampled value reads outside the hull. **`u_carve_invert` must keep working** — the stencil-marking pass draws the same hull with the test flipped, and the breach scoop depends on it.

**Point the sampler at a free unit on every path** (Constraint 2). Units 0–5 are taken; use 6.

**Tests** (`hull_field_clip_test.cc`), modelled on the existing `hull_clip_test.cc`:
- Disabled field renders the hull unchanged (stock path).
- A fragment inside a carved region is discarded.
- A fragment outside it survives.
- `u_carve_invert` flips both of the above.
- A degenerate vertex normal with the ambient gradient on stays finite — **the canary that caught the `sampler3D` corruption**. Copy its structure from `HullClipTest.DegenerateNormalWithGradientOnStaysFinite`.

- [ ] **After the shader change, run the FULL renderer binary, not a filter:**

```bash
cmake -B build -S .          # shader edits need a reconfigure
cmake --build build -j
./build/native/tests/renderer/renderer_tests
```

Expected: **0 failures.** If `TangentBasisTest`, `ConeLightFrameTest`, `ExplosionLightFrameTest` or `CloakAmbientParityTest` fail, the sampler has tripped the driver bug in a new form — **stop and report it**, do not tune around it. Those four suites are the measured signature.

Commit as `feat(renderer): clip the hull against its distance field`.

---

## Task 6: Wire carves into the field

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`hull_carve_add`), `native/src/renderer/frame.cc`
- Modify: `native/tests/renderer/instance_field_cache_test.cc` (integration case)

Every deposit that today lands in `HullCarveField` also carves the instance field, using the same body-frame centre, normal and derived visible radius that the sphere already receives — so the two representations describe the same damage.

**Keep the sphere list.** The breach scoop, the framework lattice and the breach-event ring all still read it. Removing it is 2b's job.

`frame.cc` binds the instance's atlas when one exists and sets `u_hull_field_enabled = 1`; otherwise it leaves the stock path exactly as today.

**Tests:**
- A carve deposited through the same path used in production appears in both the sphere field and the instance field.
- 30 carves — more than the 24-slot ceiling — all survive in the field. **This is the visible win**: the sphere array would have evicted six.
- An instance destroyed and recreated with the same id does not inherit the old field.

- [ ] **Final step: the full gate**

```bash
./scripts/check_tests.sh
```
Expected exit 0, only `test_shield_level_change_announces` baselined.

Commit as `feat(renderer): carve the instance field alongside the sphere list`.

---

## Done criteria

- `./scripts/check_tests.sh` exits 0.
- The full `renderer_tests` binary is green, with particular attention to `TangentBasisTest`, `ConeLightFrameTest`, `ExplosionLightFrameTest`, `CloakAmbientParityTest`.
- An undamaged ship renders byte-identically to before.
- More than 24 carves survive on one hull.
- `.dhv` files appear under `cache/hull_volumes/` after a run and are reused on the next — the plan-1 criterion that could not be met until Task 3 built a real cache root.

## What a live test should judge

This is the first plan with something to see. Watch for, in order:

1. **Does anything look corrupted?** Shading artifacts, black patches, flickering — that is the driver hazard, and it is why the shader tests above are non-negotiable before you run it.
2. **Do overlapping carves merge?** During a death cascade a ship should develop growing connected cavities rather than a fixed number of discrete spheres that pop in and out as the array evicts.
3. **Does damage stop disappearing?** The 24-slot eviction currently makes a dying ship visibly heal mid-sequence. That should be gone.
4. **Does the hole still line up with the interior?** The scoop is still sphere-derived; if hole and interior have drifted apart, Global Constraint 6 has been violated somewhere.
