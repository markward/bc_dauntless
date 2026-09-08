# Hull Volume Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce correct, cached, SDK-resolution-honouring signed-distance hull volumes on disk, verifiable entirely headlessly, with no renderer changes.

**Architecture:** Fix the voxelizer's silent resolution collapse, add a signed distance field built from the hull triangle soup, define the `.dhv` container, cache baked volumes on disk keyed by a source fingerprint plus a baker version, feed the bake the per-ship resolution BC already authors, and turn six SDK damage-geometry entry points from truthy stubs into real flags.

**Tech Stack:** C++20 (`native/src/voxel`, GoogleTest via `native/tests/voxel`), Python 3 (`engine/appc`, pytest), pybind11 host bindings, CMake.

**Spec:** `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md`

## Plan split

The spec covers three shippable subsystems. This is plan 1 of 3.

| Plan | Covers | Spec sections |
|---|---|---|
| **1 — Foundations (this plan)** | voxelizer fix, SDF, `.dhv`, cache, authored resolution, SDK toggles | §3, §4, §5, §9 |
| 2 — Field as authority | per-instance mutable field, brushes, `sampler2D` transport, `opaque.frag` clip, breach interior, the quality **setting** | §6, §7, §10 |
| 3 — Breakables and dents | connected components, chunk spawn, radius gate, vertex displacement | §8, §7 (dents) |

Plan 1 changes nothing visible in game. That is deliberate: it is entirely
headless-testable, so it does not consume live-test rounds.

Spec §11's test list is distributed across all three plans; its
`opaque.frag`-carries-no-`sampler3D` guard belongs to plan 2 and must be written
BEFORE that shader is touched, since plan 2 is what adds field sampling to it.

Spec §10's persisted **quality setting** belongs to plan 2, not here: nothing
reads the cache yet in plan 1, so a user-facing knob would have nothing to
change. Plan 1 ships `kDefaultQuality` as a constant and plan 2 makes it
settable.

## Global Constraints

Every task's requirements implicitly include these.

- **Never spell `game` or `sdk` as a path segment** anywhere — not in `engine/`, `native/src`, `tools/`, or tests. Ask `engine/paths.py` (`game_root()`, `game_asset(rel)`, `sdk_scripts()`). Enforced by `tests/unit/test_path_indirection.py`.
- **Never capture a path at import.** No module-level constant may hold one; `paths.configure()` is callable again after boot.
- **Never add a `sampler3D` to `native/src/renderer/shaders/opaque.frag`.** Measured: it corrupts shading across 16 tests even on an unreachable branch. Not relevant to this plan's code, but do not "helpfully" add one.
- **1 model unit = 0.01 GU** (`BC_MODEL_SCALE` in `engine/host_loop.py:4474`). Volumes are in **model units** throughout; convert only at boundaries.
- **Shared checkout.** Stage with an explicit pathspec. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, or `git reset --hard`.
- **One build tree:** `cmake -B build -S . && cmake --build build -j`. Never run `cmake` inside `native/`.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). Never call a failure "pre-existing" by eyeball.
- **No `hasattr` guard on a new host binding.** `engine/host_loop.py:4780` documents a feature that shipped completely inert because a `hasattr` guard turned a loud boot failure into a silent skip.
- **Commit after every task.** End commit messages with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `native/src/voxel/include/voxel/distance_field.h` | `DistanceField` type, `point_triangle_distance`, `distance_field_from_tris` |
| `native/src/voxel/src/distance_field.cc` | their implementation |
| `native/src/voxel/include/voxel/dhv.h` | `.dhv` container: `HullVolumeMeta`, `write_dhv`, `read_dhv`, `kBakerVersion` |
| `native/src/voxel/src/dhv.cc` | serialization |
| `native/src/voxel/include/voxel/hull_volume_cache.h` | `HullVolumeCache` — bake-or-load, fingerprint validation |
| `native/src/voxel/src/hull_volume_cache.cc` | its implementation |
| `native/tests/voxel/voxelize_resolution_test.cc` | the resolution-collapse regression |
| `native/tests/voxel/distance_field_test.cc` | distance and sign correctness |
| `native/tests/voxel/dhv_test.cc` | round-trip and rejection |
| `native/tests/voxel/hull_volume_cache_test.cc` | bake, hit, invalidate |
| `engine/appc/hull_volume.py` | pushes a ship's authored damage resolution to native |
| `engine/appc/damage_geometry.py` | the six SDK damage-geometry flags and the breakable radius gate |
| `tests/unit/test_hull_volume_resolution.py` | resolution push |
| `tests/unit/test_damage_geometry_flags.py` | flags + fleet radius gate |

**Modified**

| File | Change |
|---|---|
| `native/src/voxel/src/voxelize.cc:70-83` | `surface_voxelize` becomes resolution-aware |
| `native/src/voxel/CMakeLists.txt` | add the three new sources |
| `native/tests/voxel/CMakeLists.txt` | add the four new tests |
| `native/src/host/host_bindings.cc` | `hull_volume_set_resolution` binding |
| `engine/renderer.py` | façade entry for the new binding |
| `engine/host_loop.py:4792` and `:5423` | **twin** call sites — both must push the resolution |
| `engine/appc/objects.py` | six module-level damage-geometry functions |
| `App.py` | export them |

---

## Task 1: Resolution-aware surface voxelization

Fixes spec §2.2 / §5. `surface_voxelize` point-samples every triangle exactly
153 times regardless of cell size, so above ~96³ the rasterized shell develops
pinholes, `solidify`'s flood fill pours through them, and the interior is eaten.
Solid fraction falls from ~13% to ~2% and scales as n². Nothing catches this
today because no test ever asked for a resolution above 48³.

**Files:**
- Modify: `native/src/voxel/src/voxelize.cc:70-83`
- Create: `native/tests/voxel/voxelize_resolution_test.cc`
- Modify: `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature change. `void voxel::surface_voxelize(VoxelVolume&, const std::vector<Tri>&)` keeps its declaration; only its behaviour is corrected. Every later task depends on `voxelize_into` producing a genuinely solid volume.

- [ ] **Step 1: Write the failing test**

Create `native/tests/voxel/voxelize_resolution_test.cc`:

```cpp
// native/tests/voxel/voxelize_resolution_test.cc
//
// The resolution-collapse regression. surface_voxelize used a FIXED 153
// barycentric samples per triangle regardless of cell size, so as cells shrank
// the rasterized shell developed pinholes and solidify()'s flood fill (seeded
// from every border voxel) poured through them and ate the interior. Measured
// on stock hulls 2026-09-08: solid fraction fell from ~13% at 48^3 to ~2% at
// 128^3, scaling as n^2 -- the signature of a surface-only result.
//
// A solid box exactly fills its own bounding grid minus voxelize_tris's
// one-cell margin, so the true fraction is ((n-2)/n)^3: 0.67 at n=16 rising to
// 0.95 at n=128. A collapsed volume reads ~0.05 and falls as n rises.
#include <gtest/gtest.h>

#include <voxel/voxelize.h>

#include <vector>

namespace {

// A CLOSED axis-aligned box as 12 triangles. Closed matters: the whole point is
// that the flood fill must not find a way in.
std::vector<voxel::Tri> box_tris(glm::vec3 lo, glm::vec3 hi) {
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z},
    };
    const int q[6][4] = {
        {0, 1, 2, 3},  // -Z
        {4, 5, 6, 7},  // +Z
        {0, 1, 5, 4},  // -Y
        {3, 2, 6, 7},  // +Y
        {0, 3, 7, 4},  // -X
        {1, 2, 6, 5},  // +X
    };
    std::vector<voxel::Tri> t;
    for (const auto& f : q) {
        t.push_back({c[f[0]], c[f[1]], c[f[2]]});
        t.push_back({c[f[0]], c[f[2]], c[f[3]]});
    }
    return t;
}

}  // namespace

TEST(VoxelizeResolution, SolidBoxStaysSolidAsResolutionRises) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    for (int n : {16, 32, 64, 128}) {
        const voxel::VoxelVolume v = voxel::voxelize_tris(tris, glm::ivec3(n));
        const double frac = static_cast<double>(v.solid_count())
                          / (static_cast<double>(n) * n * n);
        // True value is ((n-2)/n)^3 >= 0.67. A collapsed volume reads ~0.05.
        EXPECT_GT(frac, 0.5)
            << "resolution " << n << " collapsed to a shell (fraction " << frac << ")";
    }
}

TEST(VoxelizeResolution, SolidFractionRisesWithResolutionRatherThanFalling) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    const voxel::VoxelVolume coarse = voxel::voxelize_tris(tris, glm::ivec3(16));
    const voxel::VoxelVolume fine   = voxel::voxelize_tris(tris, glm::ivec3(128));

    const double fc = static_cast<double>(coarse.solid_count()) / (16.0 * 16 * 16);
    const double ff = static_cast<double>(fine.solid_count()) / (128.0 * 128 * 128);

    // The margin is a smaller fraction of a finer grid, so the true fraction
    // RISES. The bug made it fall by an order of magnitude.
    EXPECT_GT(ff, fc) << "fine=" << ff << " coarse=" << fc;
}

// A thin plate is the case a fixed sample count fails first: its triangles are
// large relative to the cell, so samples straddle whole cells.
TEST(VoxelizeResolution, ThinPlateIsNotPerforated) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(200.0f, 200.0f, 8.0f));
    const voxel::VoxelVolume v = voxel::voxelize_tris(tris, glm::ivec3(96));
    const double frac = static_cast<double>(v.solid_count()) / (96.0 * 96 * 96);
    // voxelize_tris fits the lattice to the AABB PER AXIS (cell =
    // extent/(dims-2)), so the plate's 8-unit Z becomes 96 very thin cells and
    // the plate fills its own grid minus the margin: ~((96-2)/96)^3 = 0.94.
    // The point of the case is the ASPECT RATIO -- the Z cells are 25x smaller
    // than the X/Y cells, so a sampler tuned to one axis perforates the others.
    EXPECT_GT(frac, 0.5) << "thin plate perforated (fraction " << frac << ")";
}
```

Register it in `native/tests/voxel/CMakeLists.txt` — add `voxelize_resolution_test.cc` to the `add_executable(voxel_tests ...)` source list, after `voxelize_test.cc`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='VoxelizeResolution.*'
```

Expected: `SolidBoxStaysSolidAsResolutionRises` FAILS at n=128 (fraction ≈ 0.05),
and `SolidFractionRisesWithResolutionRatherThanFalling` FAILS. If they pass, you
have not reproduced the bug — stop and re-read `voxelize.cc:71`.

- [ ] **Step 3: Make the sampling resolution-aware**

Replace the body of `surface_voxelize` in `native/src/voxel/src/voxelize.cc`
(currently lines 70-83) with:

```cpp
void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris) {
    // Sample spacing must be FINER than the cell, or the rasterized shell
    // develops pinholes and solidify()'s flood fill pours through them and eats
    // the interior -- the volume then looks full but is a hollow shell.
    //
    // A FIXED sample count cannot do this: it is correct only at the one
    // resolution it was tuned for. The previous constant (16 per edge) was
    // right at 48^3 and silently wrong above ~96^3. MEASURED 2026-09-08: solid
    // fraction fell 13% -> 2% between 96^3 and 128^3, scaling as n^2.
    const float min_cell = std::min(v.cell.x, std::min(v.cell.y, v.cell.z));
    if (!(min_cell > 0.0f)) return;   // degenerate lattice: nothing to do

    for (const auto& t : tris) {
        const float longest = std::max(glm::length(t.b - t.a),
                             std::max(glm::length(t.c - t.a),
                                      glm::length(t.c - t.b)));
        // Half a cell between samples along the longest edge. The clamp bounds
        // worst-case cost on a single huge triangle; N*N samples are taken.
        int N = static_cast<int>(std::ceil(longest / (0.5f * min_cell)));
        if (N < 1) N = 1;
        if (N > 512) N = 512;

        for (int i = 0; i <= N; ++i)
        for (int j = 0; j + i <= N; ++j) {
            const float u = static_cast<float>(i) / N;
            const float w = static_cast<float>(j) / N;
            const glm::vec3 p = t.a + u * (t.b - t.a) + w * (t.c - t.a);
            const glm::ivec3 c = to_cell(v, p);
            if (glm::all(glm::greaterThanEqual(c, glm::ivec3(0))) &&
                glm::all(glm::lessThan(c, v.dims)))
                v.set(c.x, c.y, c.z, true);
        }
    }
}
```

Add `#include <algorithm>` to the include block at the top of the file if it is
not already present.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='VoxelizeResolution.*'
./build/native/tests/voxel/voxel_tests
```

Expected: the three new tests PASS, and the whole `voxel_tests` binary still
passes. `IouRealData*` tests compare a decoded BC volume against a re-voxelized
hull; a better rasterizer should raise IoU, never lower it. If any IoU test
fails, report it rather than loosening the test.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel/src/voxelize.cc native/tests/voxel/voxelize_resolution_test.cc native/tests/voxel/CMakeLists.txt
git commit -m "fix(voxel): sample triangles against cell size, not a fixed count

surface_voxelize took exactly 153 barycentric samples per triangle whatever
the cell size, so above ~96^3 the shell developed pinholes, solidify()'s
flood fill poured through them, and the interior was eaten. Measured on
stock hulls: solid fraction 13% -> 2% between 96^3 and 128^3, scaling as
n^2 -- a hollow shell returned silently as a full volume.

Not the assets: BC hulls are 99.5%+ manifold (0-0.5% boundary edges).

No test caught it because nothing ever asked for a resolution above 48^3,
which is exactly where SourceVolumeCache's mod-ship fallback sits.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Point-triangle distance

The primitive the distance field is built from. Separated because it is pure
geometry with exact expected values, and a bug here would be invisible inside a
whole-field test.

**Files:**
- Create: `native/src/voxel/include/voxel/distance_field.h`
- Create: `native/src/voxel/src/distance_field.cc`
- Create: `native/tests/voxel/distance_field_test.cc`
- Modify: `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: `voxel::Tri` from `voxel/voxelize.h`.
- Produces: `float voxel::point_triangle_distance(const glm::vec3& p, const Tri& t)` — unsigned distance, always ≥ 0.

- [ ] **Step 1: Write the failing test**

Create `native/tests/voxel/distance_field_test.cc`:

```cpp
// native/tests/voxel/distance_field_test.cc
//
// The signed distance field that replaces BC's occupancy grid. Distance is the
// whole point: every damage threshold becomes a real length instead of a cell
// count, which is what made the Warbird misbehave (its cells are 25 model units
// against everyone else's 15, so a threshold of "2 cells" meant 50 units there
// and 30 elsewhere).
#include <gtest/gtest.h>

#include <voxel/distance_field.h>
#include <voxel/voxelize.h>

#include <cmath>
#include <vector>

namespace {

// Triangle in the z = 0 plane: (0,0,0), (10,0,0), (0,10,0).
voxel::Tri flat_tri() {
    return voxel::Tri{glm::vec3(0.0f, 0.0f, 0.0f),
                      glm::vec3(10.0f, 0.0f, 0.0f),
                      glm::vec3(0.0f, 10.0f, 0.0f)};
}

}  // namespace

TEST(PointTriangleDistance, PointOnTheFaceIsZero) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, 0.0f),
                                               flat_tri()), 0.0f, 1e-4f);
}

TEST(PointTriangleDistance, PointAboveTheFaceIsThePerpendicular) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, 7.0f),
                                               flat_tri()), 7.0f, 1e-4f);
}

TEST(PointTriangleDistance, DistanceIsUnsignedBelowTheFaceToo) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, -7.0f),
                                               flat_tri()), 7.0f, 1e-4f);
}

TEST(PointTriangleDistance, NearestFeatureIsAVertexWhenBeyondACorner) {
    // Well outside the (0,0) corner, along -x -y: nearest point is that vertex.
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(-3.0f, -4.0f, 0.0f),
                                               flat_tri()), 5.0f, 1e-4f);
}

TEST(PointTriangleDistance, NearestFeatureIsAnEdgeWhenBesideOne) {
    // Beside the a-b edge (which lies along +x), 4 units away in -y.
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(5.0f, -4.0f, 0.0f),
                                               flat_tri()), 4.0f, 1e-4f);
}

TEST(PointTriangleDistance, DegenerateTriangleDoesNotProduceNaN) {
    const voxel::Tri d{glm::vec3(1.0f), glm::vec3(1.0f), glm::vec3(1.0f)};
    const float r = voxel::point_triangle_distance(glm::vec3(1.0f, 1.0f, 4.0f), d);
    EXPECT_TRUE(std::isfinite(r));
    EXPECT_NEAR(r, 3.0f, 1e-4f);
}
```

Register `distance_field_test.cc` in `native/tests/voxel/CMakeLists.txt`.

- [ ] **Step 2: Create the header**

Create `native/src/voxel/include/voxel/distance_field.h`:

```cpp
// native/src/voxel/include/voxel/distance_field.h
#pragma once

#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/voxelize.h>

namespace voxel {

/// Unsigned distance from `p` to triangle `t`. Always >= 0, always finite --
/// a degenerate (zero-area) triangle collapses to its vertex rather than
/// dividing by zero.
float point_triangle_distance(const glm::vec3& p, const Tri& t);

}  // namespace voxel
```

- [ ] **Step 3: Implement it**

Create `native/src/voxel/src/distance_field.cc`:

```cpp
// native/src/voxel/src/distance_field.cc
#include <voxel/distance_field.h>

#include <algorithm>
#include <cmath>

namespace voxel {

// Closest point on a triangle (Ericson, Real-Time Collision Detection, 5.1.5).
// Region-by-region: the three vertices, the three edges, then the interior.
float point_triangle_distance(const glm::vec3& p, const Tri& t) {
    const glm::vec3 ab = t.b - t.a;
    const glm::vec3 ac = t.c - t.a;
    const glm::vec3 ap = p - t.a;

    const float d1 = glm::dot(ab, ap);
    const float d2 = glm::dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) return glm::length(ap);          // vertex a

    const glm::vec3 bp = p - t.b;
    const float d3 = glm::dot(ab, bp);
    const float d4 = glm::dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) return glm::length(bp);            // vertex b

    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {                  // edge ab
        const float denom = d1 - d3;
        const float v = (std::abs(denom) > 1e-20f) ? d1 / denom : 0.0f;
        return glm::length(p - (t.a + v * ab));
    }

    const glm::vec3 cp = p - t.c;
    const float d5 = glm::dot(ab, cp);
    const float d6 = glm::dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) return glm::length(cp);            // vertex c

    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {                  // edge ac
        const float denom = d2 - d6;
        const float w = (std::abs(denom) > 1e-20f) ? d2 / denom : 0.0f;
        return glm::length(p - (t.a + w * ac));
    }

    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {    // edge bc
        const float denom = (d4 - d3) + (d5 - d6);
        const float w = (std::abs(denom) > 1e-20f) ? (d4 - d3) / denom : 0.0f;
        return glm::length(p - (t.b + w * (t.c - t.b)));
    }

    const float sum = va + vb + vc;                                 // interior
    if (!(std::abs(sum) > 1e-20f)) return glm::length(ap);          // degenerate
    const float inv = 1.0f / sum;
    return glm::length(p - (t.a + ab * (vb * inv) + ac * (vc * inv)));
}

}  // namespace voxel
```

Add `src/distance_field.cc` to the `add_library(voxel STATIC ...)` source list
in `native/src/voxel/CMakeLists.txt`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='PointTriangleDistance.*'
```

Expected: all six PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel/include/voxel/distance_field.h native/src/voxel/src/distance_field.cc native/tests/voxel/distance_field_test.cc native/src/voxel/CMakeLists.txt native/tests/voxel/CMakeLists.txt
git commit -m "feat(voxel): exact point-triangle distance

The primitive the hull distance field is built from. Region-based closest
point (Ericson 5.1.5), guarded so a zero-area triangle collapses to its
vertex rather than dividing by zero.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Signed distance field from a triangle soup

**Files:**
- Modify: `native/src/voxel/include/voxel/distance_field.h`
- Modify: `native/src/voxel/src/distance_field.cc`
- Modify: `native/tests/voxel/distance_field_test.cc`

**Interfaces:**
- Consumes: `point_triangle_distance` (Task 2), `voxelize_into` (Task 1).
- Produces:
  - `struct voxel::DistanceField { glm::ivec3 dims; glm::vec3 origin; glm::vec3 cell; float scale; std::vector<std::int8_t> dist; std::size_t index(int,int,int) const; float distance_at(int,int,int) const; }`
  - `DistanceField voxel::distance_field_from_tris(const std::vector<Tri>& tris, glm::vec3 cell, float band_cells)`
  - `constexpr float voxel::kDefaultBandCells = 4.0f;`

- [ ] **Step 1: Write the failing test**

Append to `native/tests/voxel/distance_field_test.cc`:

```cpp
namespace {

// A CLOSED axis-aligned box as 12 triangles.
std::vector<voxel::Tri> box_tris(glm::vec3 lo, glm::vec3 hi) {
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z},
    };
    const int q[6][4] = {{0,1,2,3},{4,5,6,7},{0,1,5,4},{3,2,6,7},{0,3,7,4},{1,2,6,5}};
    std::vector<voxel::Tri> t;
    for (const auto& f : q) {
        t.push_back({c[f[0]], c[f[1]], c[f[2]]});
        t.push_back({c[f[0]], c[f[2]], c[f[3]]});
    }
    return t;
}

// Cell index containing a body-frame point.
glm::ivec3 cell_of(const voxel::DistanceField& f, glm::vec3 p) {
    const glm::vec3 g = (p - f.origin) / f.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}

}  // namespace

TEST(DistanceField, SignIsNegativeInsideAndPositiveOutside) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    ASSERT_FALSE(f.dist.empty());

    const glm::ivec3 mid = cell_of(f, glm::vec3(50.0f));
    EXPECT_LT(f.distance_at(mid.x, mid.y, mid.z), 0.0f) << "box centre read as outside";

    // A cell in the margin, comfortably outside the box.
    EXPECT_GT(f.distance_at(0, 0, 0), 0.0f) << "margin cell read as inside";
}

TEST(DistanceField, DepthNearAFaceMatchesGeometry) {
    // Cell 2 units so the answer is not dominated by quantisation.
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(2.0f),
        voxel::kDefaultBandCells);

    // 5 units below the +Z face, far from every other face.
    const glm::ivec3 c = cell_of(f, glm::vec3(50.0f, 50.0f, 95.0f));
    const float d = f.distance_at(c.x, c.y, c.z);
    EXPECT_LT(d, 0.0f);
    // Within one cell of the true -5.
    EXPECT_NEAR(d, -5.0f, 2.0f);
}

TEST(DistanceField, HeightAboveAFaceMatchesGeometry) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(2.0f),
        voxel::kDefaultBandCells);

    const glm::ivec3 c = cell_of(f, glm::vec3(50.0f, 50.0f, 103.0f));
    const float d = f.distance_at(c.x, c.y, c.z);
    EXPECT_GT(d, 0.0f);
    EXPECT_NEAR(d, 3.0f, 2.0f);
}

TEST(DistanceField, FarFieldSaturatesRatherThanWrapping) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    // The band is 4 cells = 20 units; the box centre is 50 units from every
    // face, so it must clamp to the most negative representable value, not
    // wrap to a positive one.
    const glm::ivec3 mid = cell_of(f, glm::vec3(50.0f));
    EXPECT_NEAR(f.distance_at(mid.x, mid.y, mid.z), -127.0f * f.scale, 1e-3f);
}

TEST(DistanceField, EmptyInputYieldsAnEmptyField) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        {}, glm::vec3(5.0f), voxel::kDefaultBandCells);
    EXPECT_TRUE(f.dist.empty());
}

TEST(DistanceField, GridCoversTheHullPlusAMargin) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    // origin sits below the hull minimum, and the far corner above its maximum.
    EXPECT_LT(f.origin.x, 0.0f);
    const float far_x = f.origin.x + f.cell.x * static_cast<float>(f.dims.x);
    EXPECT_GT(far_x, 100.0f);
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake --build build --target voxel_tests -j
```

Expected: compile FAILS — `DistanceField` and `distance_field_from_tris` do not
exist.

- [ ] **Step 3: Declare the type**

Append to `native/src/voxel/include/voxel/distance_field.h`, inside
`namespace voxel`:

```cpp
/// Default half-width of the accurate band, in cells. Beyond this the stored
/// value saturates: no consumer probes deeper than a few cells, so the exact
/// far-field distance carries no information anyone uses.
inline constexpr float kDefaultBandCells = 4.0f;

/// Signed distance field over a uniform body-frame lattice, model units.
///
/// NEGATIVE inside the hull, POSITIVE outside. One signed byte per cell in
/// units of `scale`, saturating at +-127.
///
/// Why signed distance rather than occupancy: every damage threshold becomes a
/// real LENGTH instead of a cell count. The cavity-depth threshold that made
/// the Warbird cut breaches into nothing was expressed in cells, and the
/// Warbird's authored cells are 25 model units against the fleet's 15 -- so
/// "2 cells" silently meant 50 units on one ship and 30 on every other.
struct DistanceField {
    glm::ivec3 dims{0};
    glm::vec3  origin{0.0f};   // body-frame position of cell (0,0,0)'s min corner
    glm::vec3  cell{1.0f};     // model units per cell
    float      scale = 1.0f;   // model units per quantisation step
    std::vector<std::int8_t> dist;

    std::size_t index(int x, int y, int z) const {
        return static_cast<std::size_t>(x)
             + static_cast<std::size_t>(dims.x)
             * (static_cast<std::size_t>(y)
             +  static_cast<std::size_t>(dims.y) * static_cast<std::size_t>(z));
    }
    float distance_at(int x, int y, int z) const {
        return static_cast<float>(dist[index(x, y, z)]) * scale;
    }
};

/// Build a signed distance field for a hull triangle soup at the given cell
/// size. Grid is the tris' AABB plus a 2-cell margin. Sign comes from flood
/// fill (BC hulls are 99.5%+ manifold -- MEASURED -- so this is sound);
/// magnitude from the nearest triangle within `band_cells`, saturating beyond.
/// Returns an empty field when `tris` is empty or `cell` is degenerate.
DistanceField distance_field_from_tris(const std::vector<Tri>& tris,
                                       glm::vec3 cell,
                                       float band_cells = kDefaultBandCells);
```

- [ ] **Step 4: Implement it**

Append to `native/src/voxel/src/distance_field.cc`, inside `namespace voxel`
(and add `#include <unordered_map>` and `#include <cstdint>` at the top):

```cpp
namespace {

// Hash key for a triangle bin.
struct BinKey {
    int x, y, z;
    bool operator==(const BinKey& o) const { return x == o.x && y == o.y && z == o.z; }
};
struct BinHash {
    std::size_t operator()(const BinKey& k) const {
        // Cheap mix; bins are few relative to cells.
        return (static_cast<std::size_t>(k.x) * 73856093u)
             ^ (static_cast<std::size_t>(k.y) * 19349663u)
             ^ (static_cast<std::size_t>(k.z) * 83492791u);
    }
};

}  // namespace

DistanceField distance_field_from_tris(const std::vector<Tri>& tris,
                                       glm::vec3 cell,
                                       float band_cells) {
    DistanceField f;
    if (tris.empty()) return f;
    if (!(cell.x > 0.0f) || !(cell.y > 0.0f) || !(cell.z > 0.0f)) return f;
    if (!(band_cells > 0.0f)) return f;

    glm::vec3 mn(1e30f), mx(-1e30f);
    for (const auto& t : tris) {
        mn = glm::min(mn, glm::min(t.a, glm::min(t.b, t.c)));
        mx = glm::max(mx, glm::max(t.a, glm::max(t.b, t.c)));
    }

    // Two-cell margin so the outside band is representable all the way round.
    f.cell   = cell;
    f.origin = mn - cell * 2.0f;
    const glm::vec3 span = (mx - mn) / cell;
    f.dims = glm::ivec3(static_cast<int>(std::ceil(span.x)) + 5,
                        static_cast<int>(std::ceil(span.y)) + 5,
                        static_cast<int>(std::ceil(span.z)) + 5);

    const float band = band_cells * std::max(cell.x, std::max(cell.y, cell.z));
    f.scale = band / 127.0f;

    // Sign: the flood-filled occupancy of the SAME lattice.
    const VoxelVolume occ = voxelize_into(tris, f.dims, f.origin, f.cell);

    // Bin triangles by band-sized cells, each inserted into every bin its
    // band-expanded bbox touches. A voxel then need only consult its OWN bin:
    // any triangle within `band` of it is guaranteed to be there.
    std::unordered_map<BinKey, std::vector<std::uint32_t>, BinHash> bins;
    auto bin_of = [&](const glm::vec3& p) {
        return BinKey{static_cast<int>(std::floor(p.x / band)),
                      static_cast<int>(std::floor(p.y / band)),
                      static_cast<int>(std::floor(p.z / band))};
    };
    for (std::uint32_t i = 0; i < tris.size(); ++i) {
        const Tri& t = tris[i];
        const glm::vec3 tlo = glm::min(t.a, glm::min(t.b, t.c)) - band;
        const glm::vec3 thi = glm::max(t.a, glm::max(t.b, t.c)) + band;
        const BinKey lo = bin_of(tlo), hi = bin_of(thi);
        for (int z = lo.z; z <= hi.z; ++z)
        for (int y = lo.y; y <= hi.y; ++y)
        for (int x = lo.x; x <= hi.x; ++x)
            bins[BinKey{x, y, z}].push_back(i);
    }

    f.dist.assign(static_cast<std::size_t>(f.dims.x)
                * static_cast<std::size_t>(f.dims.y)
                * static_cast<std::size_t>(f.dims.z), 0);

    for (int z = 0; z < f.dims.z; ++z)
    for (int y = 0; y < f.dims.y; ++y)
    for (int x = 0; x < f.dims.x; ++x) {
        const glm::vec3 p = f.origin
                          + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        float best = band;
        auto it = bins.find(bin_of(p));
        if (it != bins.end())
            for (std::uint32_t ti : it->second)
                best = std::min(best, point_triangle_distance(p, tris[ti]));

        const float sign = occ.solid(x, y, z) ? -1.0f : 1.0f;
        float q = std::round(sign * best / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[f.index(x, y, z)] = static_cast<std::int8_t>(q);
    }
    return f;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='DistanceField.*'
```

Expected: all six PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/voxel/include/voxel/distance_field.h native/src/voxel/src/distance_field.cc native/tests/voxel/distance_field_test.cc
git commit -m "feat(voxel): signed distance field from a hull triangle soup

Negative inside, positive outside, one signed byte per cell saturating at a
4-cell band. Sign from flood-filled occupancy (sound: BC hulls measure
99.5%+ manifold), magnitude from the nearest triangle via band-sized bins.

Distance rather than occupancy is the point: a damage threshold becomes a
real length instead of a cell count. The cavity threshold that made the
Warbird cut breaches into nothing was in cells, and its authored cells are
25 model units against the fleet's 15 -- so '2 cells' meant 50 units there
and 30 everywhere else.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: The `.dhv` container

Spec §3. Binary, little-endian, one file per hull. Not a NIF: there is no
compatibility requirement with `stbc.exe` for these, and NIF v3.1 is poorly
documented.

**Files:**
- Create: `native/src/voxel/include/voxel/dhv.h`
- Create: `native/src/voxel/src/dhv.cc`
- Create: `native/tests/voxel/dhv_test.cc`
- Modify: `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: `voxel::DistanceField` (Task 3).
- Produces:
  - `struct voxel::HullVolumeMeta { std::uint16_t baker_version; std::uint32_t source_size; std::int64_t source_mtime; float authored_res; float quality; std::string source_path; }`
  - `constexpr std::uint16_t voxel::kBakerVersion = 1;`
  - `bool voxel::write_dhv(const std::filesystem::path&, const DistanceField&, const HullVolumeMeta&)`
  - `bool voxel::read_dhv(const std::filesystem::path&, DistanceField& out_field, HullVolumeMeta& out_meta)` — returns false on any rejection.

- [ ] **Step 1: Write the failing test**

Create `native/tests/voxel/dhv_test.cc`:

```cpp
// native/tests/voxel/dhv_test.cc
//
// The .dhv container. A cache file is untrusted input: it may be truncated by a
// crash mid-write, left behind by an older baker, or belong to a different
// hull. Every one of those must be REJECTED and rebaked, never half-read --
// a silently wrong hull volume is exactly the class of bug this subsystem
// exists to end.
#include <gtest/gtest.h>

#include <voxel/dhv.h>
#include <voxel/distance_field.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {

std::filesystem::path tmp_path(const char* name) {
    return std::filesystem::temp_directory_path() / name;
}

voxel::DistanceField sample_field() {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(3, 4, 5);
    f.origin = glm::vec3(-1.0f, -2.0f, -3.0f);
    f.cell   = glm::vec3(7.0f, 7.0f, 7.0f);
    f.scale  = 0.25f;
    f.dist.resize(3 * 4 * 5);
    for (std::size_t i = 0; i < f.dist.size(); ++i)
        f.dist[i] = static_cast<std::int8_t>(static_cast<int>(i) - 30);
    return f;
}

voxel::HullVolumeMeta sample_meta() {
    voxel::HullVolumeMeta m;
    m.baker_version = voxel::kBakerVersion;
    m.source_size   = 123456;
    m.source_mtime  = 1757000000;
    m.authored_res  = 10.0f;
    m.quality       = 2.0f;
    m.source_path   = "Ships/Galaxy/Galaxy.nif";
    return m;
}

}  // namespace

TEST(Dhv, RoundTripPreservesFieldAndMeta) {
    const auto p = tmp_path("dauntless_roundtrip.dhv");
    const voxel::DistanceField in = sample_field();
    const voxel::HullVolumeMeta mi = sample_meta();
    ASSERT_TRUE(voxel::write_dhv(p, in, mi));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    ASSERT_TRUE(voxel::read_dhv(p, out, mo));

    EXPECT_EQ(out.dims, in.dims);
    EXPECT_EQ(out.origin, in.origin);
    EXPECT_EQ(out.cell, in.cell);
    EXPECT_FLOAT_EQ(out.scale, in.scale);
    EXPECT_EQ(out.dist, in.dist);

    EXPECT_EQ(mo.baker_version, mi.baker_version);
    EXPECT_EQ(mo.source_size, mi.source_size);
    EXPECT_EQ(mo.source_mtime, mi.source_mtime);
    EXPECT_FLOAT_EQ(mo.authored_res, mi.authored_res);
    EXPECT_FLOAT_EQ(mo.quality, mi.quality);
    EXPECT_EQ(mo.source_path, mi.source_path);

    std::filesystem::remove(p);
}

TEST(Dhv, NegativeDistancesSurviveTheRoundTrip) {
    // int8 payload: a sign bug here inverts inside and outside, which would
    // read as "the whole ship is a hole".
    const auto p = tmp_path("dauntless_signs.dhv");
    voxel::DistanceField in = sample_field();
    in.dist[0] = -127;
    in.dist[1] = 127;
    in.dist[2] = 0;
    ASSERT_TRUE(voxel::write_dhv(p, in, sample_meta()));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    ASSERT_TRUE(voxel::read_dhv(p, out, mo));
    EXPECT_EQ(out.dist[0], -127);
    EXPECT_EQ(out.dist[1], 127);
    EXPECT_EQ(out.dist[2], 0);

    std::filesystem::remove(p);
}

TEST(Dhv, MissingFileIsRejected) {
    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(tmp_path("dauntless_absent.dhv"), out, mo));
}

TEST(Dhv, WrongMagicIsRejected) {
    const auto p = tmp_path("dauntless_badmagic.dhv");
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), sample_meta()));
    {
        std::fstream s(p, std::ios::in | std::ios::out | std::ios::binary);
        s.seekp(0);
        s.write("XXXX", 4);
    }
    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo));
    std::filesystem::remove(p);
}

TEST(Dhv, TruncatedPayloadIsRejected) {
    const auto p = tmp_path("dauntless_short.dhv");
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), sample_meta()));
    const auto full = std::filesystem::file_size(p);
    std::filesystem::resize_file(p, full - 10);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "a crash mid-write must not yield a half-read volume";
    std::filesystem::remove(p);
}

TEST(Dhv, OlderBakerVersionIsRejected) {
    const auto p = tmp_path("dauntless_oldbaker.dhv");
    voxel::HullVolumeMeta m = sample_meta();
    m.baker_version = static_cast<std::uint16_t>(voxel::kBakerVersion - 1);
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), m));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "bumping kBakerVersion must invalidate every stale cache entry";
    std::filesystem::remove(p);
}
```

Register `dhv_test.cc` in `native/tests/voxel/CMakeLists.txt`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake --build build --target voxel_tests -j
```

Expected: compile FAILS — `voxel/dhv.h` does not exist.

- [ ] **Step 3: Write the header**

Create `native/src/voxel/include/voxel/dhv.h`:

```cpp
// native/src/voxel/include/voxel/dhv.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

#include <voxel/distance_field.h>

namespace voxel {

/// Bump whenever bake OUTPUT changes for the same inputs. Every cached file
/// carries it, and read_dhv rejects any mismatch, so a baker change
/// invalidates the whole cache without anyone having to remember to clear it.
inline constexpr std::uint16_t kBakerVersion = 1;

/// Provenance stored alongside the field, so a cache entry can be validated
/// against the hull it claims to describe.
struct HullVolumeMeta {
    std::uint16_t baker_version = kBakerVersion;
    std::uint32_t source_size   = 0;   // hull nif size in bytes
    std::int64_t  source_mtime  = 0;   // hull nif mtime, unix seconds
    float         authored_res  = 0.0f;  // SetDamageResolution, as given
    float         quality       = 0.0f;  // cell = authored_res / quality
    std::string   source_path;           // diagnosis only, never for lookup
};

/// Write `field` + `meta` to `path`, creating parent directories. Writes to a
/// sibling temporary and renames, so a crash mid-write cannot leave a
/// half-written file where a valid one is expected. False on any I/O failure.
bool write_dhv(const std::filesystem::path& path,
               const DistanceField& field,
               const HullVolumeMeta& meta);

/// Read `path`. Returns false -- and leaves the outputs untouched -- for a
/// missing file, a bad magic, a format or baker version mismatch, implausible
/// dimensions, or a payload shorter than the header says. The caller's only
/// correct response to false is to rebake.
bool read_dhv(const std::filesystem::path& path,
              DistanceField& out_field,
              HullVolumeMeta& out_meta);

}  // namespace voxel
```

- [ ] **Step 4: Implement it**

Create `native/src/voxel/src/dhv.cc`:

```cpp
// native/src/voxel/src/dhv.cc
#include <voxel/dhv.h>

#include <cstring>
#include <fstream>
#include <system_error>
#include <vector>

namespace voxel {

namespace {

constexpr char  kMagic[4]        = {'D', 'H', 'V', '1'};
constexpr std::uint16_t kFormat  = 1;
// A hull volume is small (the whole stock fleet is ~7 MB at 2x quality). A
// header claiming more than this is corrupt, not ambitious.
constexpr std::uint64_t kMaxCells = 64ull * 1024 * 1024;

template <typename T>
void put(std::ostream& s, const T& v) {
    s.write(reinterpret_cast<const char*>(&v), sizeof(T));
}
template <typename T>
bool get(std::istream& s, T& v) {
    s.read(reinterpret_cast<char*>(&v), sizeof(T));
    return static_cast<bool>(s);
}

}  // namespace

bool write_dhv(const std::filesystem::path& path,
               const DistanceField& field,
               const HullVolumeMeta& meta) {
    std::error_code ec;
    if (path.has_parent_path())
        std::filesystem::create_directories(path.parent_path(), ec);

    const std::filesystem::path tmp = path.string() + ".tmp";
    {
        std::ofstream s(tmp, std::ios::binary | std::ios::trunc);
        if (!s) return false;

        s.write(kMagic, 4);
        put(s, kFormat);
        put(s, meta.baker_version);
        put(s, meta.source_size);
        put(s, meta.source_mtime);
        put(s, field.dims.x); put(s, field.dims.y); put(s, field.dims.z);
        put(s, field.origin.x); put(s, field.origin.y); put(s, field.origin.z);
        put(s, field.cell.x); put(s, field.cell.y); put(s, field.cell.z);
        put(s, meta.authored_res);
        put(s, meta.quality);
        put(s, field.scale);

        const std::uint32_t plen =
            static_cast<std::uint32_t>(meta.source_path.size());
        put(s, plen);
        s.write(meta.source_path.data(), static_cast<std::streamsize>(plen));

        s.write(reinterpret_cast<const char*>(field.dist.data()),
                static_cast<std::streamsize>(field.dist.size()));
        if (!s) return false;
    }
    std::filesystem::rename(tmp, path, ec);
    if (ec) { std::filesystem::remove(tmp, ec); return false; }
    return true;
}

bool read_dhv(const std::filesystem::path& path,
              DistanceField& out_field,
              HullVolumeMeta& out_meta) {
    std::ifstream s(path, std::ios::binary);
    if (!s) return false;

    char magic[4] = {};
    s.read(magic, 4);
    if (!s || std::memcmp(magic, kMagic, 4) != 0) return false;

    std::uint16_t format = 0;
    HullVolumeMeta m;
    DistanceField f;
    if (!get(s, format) || format != kFormat) return false;
    if (!get(s, m.baker_version) || m.baker_version != kBakerVersion) return false;
    if (!get(s, m.source_size)) return false;
    if (!get(s, m.source_mtime)) return false;
    if (!get(s, f.dims.x) || !get(s, f.dims.y) || !get(s, f.dims.z)) return false;
    if (!get(s, f.origin.x) || !get(s, f.origin.y) || !get(s, f.origin.z)) return false;
    if (!get(s, f.cell.x) || !get(s, f.cell.y) || !get(s, f.cell.z)) return false;
    if (!get(s, m.authored_res)) return false;
    if (!get(s, m.quality)) return false;
    if (!get(s, f.scale)) return false;

    std::uint32_t plen = 0;
    if (!get(s, plen)) return false;
    if (plen > 4096) return false;             // implausible: corrupt
    m.source_path.assign(plen, '\0');
    if (plen > 0) {
        s.read(m.source_path.data(), static_cast<std::streamsize>(plen));
        if (!s) return false;
    }

    if (f.dims.x <= 0 || f.dims.y <= 0 || f.dims.z <= 0) return false;
    const std::uint64_t cells = static_cast<std::uint64_t>(f.dims.x)
                              * static_cast<std::uint64_t>(f.dims.y)
                              * static_cast<std::uint64_t>(f.dims.z);
    if (cells > kMaxCells) return false;

    f.dist.resize(static_cast<std::size_t>(cells));
    s.read(reinterpret_cast<char*>(f.dist.data()),
           static_cast<std::streamsize>(cells));
    // gcount, not the stream state: a payload SHORTER than the header claims
    // is the crash-mid-write case, and must be rejected rather than padded.
    if (static_cast<std::uint64_t>(s.gcount()) != cells) return false;

    out_field = std::move(f);
    out_meta  = std::move(m);
    return true;
}

}  // namespace voxel
```

Add `src/dhv.cc` to `add_library(voxel STATIC ...)` in
`native/src/voxel/CMakeLists.txt`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='Dhv.*'
```

Expected: all six PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/voxel/include/voxel/dhv.h native/src/voxel/src/dhv.cc native/tests/voxel/dhv_test.cc native/src/voxel/CMakeLists.txt native/tests/voxel/CMakeLists.txt
git commit -m "feat(voxel): .dhv container for baked hull distance fields

Binary, little-endian, one file per hull, carrying dims/origin/cell/scale
plus the provenance a cache entry is validated against. Not a NIF: nothing
needs to read these but us, and NIF v3.1 is poorly documented.

A cache file is untrusted input. Bad magic, format or baker-version
mismatch, implausible dims, or a payload shorter than the header claims are
all REJECTED so the caller rebakes -- a silently wrong hull volume is the
bug class this subsystem exists to end. Writes go to a temporary and rename,
so a crash mid-write cannot leave a half-file where a valid one is expected.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Bake-and-cache

Spec §4. Bake on first use, cache on disk, validate against the source.

**Files:**
- Create: `native/src/voxel/include/voxel/hull_volume_cache.h`
- Create: `native/src/voxel/src/hull_volume_cache.cc`
- Create: `native/tests/voxel/hull_volume_cache_test.cc`
- Modify: `native/src/voxel/CMakeLists.txt`, `native/tests/voxel/CMakeLists.txt`

**Interfaces:**
- Consumes: `distance_field_from_tris` (Task 3), `write_dhv`/`read_dhv`/`HullVolumeMeta` (Task 4), `collect_hull_triangles_from_nif` (existing, `voxel/voxelize.h`).
- Produces:
  - `constexpr float voxel::kDefaultQuality = 2.0f;`
  - `class voxel::HullVolumeCache` with
    `explicit HullVolumeCache(std::filesystem::path cache_root)`,
    `const DistanceField& get(const std::filesystem::path& hull_nif, float authored_res, float quality)`,
    `std::filesystem::path path_for(const std::filesystem::path& hull_nif, float authored_res, float quality) const`.
  - `get` returns a reference stable for the cache's lifetime; an empty field on failure.

- [ ] **Step 1: Write the failing test**

Create `native/tests/voxel/hull_volume_cache_test.cc`:

```cpp
// native/tests/voxel/hull_volume_cache_test.cc
//
// Bake once, then load. The interesting cases are all invalidation: a stale
// entry that is USED is far worse than one that is missed, because it produces
// a hull whose damage volume silently does not match its geometry.
//
// No real hull assets: the cache is exercised through a synthetic .nif-free
// path by baking from triangles directly, plus disk-level checks on the
// resulting file.
#include <gtest/gtest.h>

#include <voxel/hull_volume_cache.h>
#include <voxel/dhv.h>

#include <filesystem>
#include <fstream>

namespace {

std::filesystem::path scratch_root() {
    return std::filesystem::temp_directory_path() / "dauntless_hvcache_test";
}

void clear_scratch() {
    std::error_code ec;
    std::filesystem::remove_all(scratch_root(), ec);
}

// A minimal file standing in for a hull source, so fingerprinting has
// something real to read. Baking from it yields an empty field (no triangles),
// which is fine: these tests are about keys, files and invalidation.
std::filesystem::path make_source(const char* name, const char* body) {
    const auto p = scratch_root() / name;
    std::filesystem::create_directories(scratch_root());
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    s << body;
    return p;
}

}  // namespace

TEST(HullVolumeCache, KeyChangesWithQualityAndResolution) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    const auto a = c.path_for(src, 10.0f, 1.0f);
    const auto b = c.path_for(src, 10.0f, 2.0f);
    const auto d = c.path_for(src,  8.0f, 2.0f);

    EXPECT_NE(a, b) << "quality must be part of the key";
    EXPECT_NE(b, d) << "authored resolution must be part of the key";
    EXPECT_EQ(a.extension().string(), ".dhv");
    clear_scratch();
}

TEST(HullVolumeCache, DistinctSourcesGetDistinctFiles) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto s1 = make_source("hullA.nif", "hull-a");
    const auto s2 = make_source("hullB.nif", "hull-b-longer");
    EXPECT_NE(c.path_for(s1, 10.0f, 2.0f), c.path_for(s2, 10.0f, 2.0f));
    clear_scratch();
}

TEST(HullVolumeCache, FirstGetWritesACacheFile) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_TRUE(std::filesystem::exists(c.path_for(src, 10.0f, 2.0f)))
        << "a bake must be persisted, or every launch pays for it again";
    clear_scratch();
}

TEST(HullVolumeCache, SecondGetReadsTheCacheRatherThanRebaking) {
    clear_scratch();
    const auto src = make_source("hullA.nif", "hull-a");
    const auto cache_root = scratch_root() / "cache";

    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
        EXPECT_EQ(warm.bakes(), 1u) << "a cold cache must bake exactly once";
    }

    voxel::HullVolumeCache cold(cache_root);   // fresh: no in-memory memo
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 0u)
        << "a valid cache file must be LOADED, not rebaked -- otherwise the "
           "cache is inert and every launch pays first-load cost again";
    clear_scratch();
}

TEST(HullVolumeCache, RepeatedGetUsesTheInMemoryMemo) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    (void)c.get(src, 10.0f, 2.0f);
    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(c.bakes(), 1u);
    clear_scratch();
}

TEST(HullVolumeCache, ChangedSourceInvalidatesTheEntry) {
    clear_scratch();
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
    }

    // Rewrite the source at a DIFFERENT LENGTH: the stored fingerprint no
    // longer matches, so the entry must not be served.
    make_source("hullA.nif", "hull-a-but-edited-and-rather-longer");

    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u)
        << "an edited hull must be rebaked; serving a stale volume gives a "
           "ship damage geometry that does not match its mesh";
    clear_scratch();
}

TEST(HullVolumeCache, ChangedQualityInvalidatesTheEntry) {
    clear_scratch();
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 1.0f);
    }
    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u) << "quality is part of the key";
    clear_scratch();
}

TEST(HullVolumeCache, CorruptCacheFileIsRebakedRatherThanTrusted) {
    clear_scratch();
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
    }
    const auto p = voxel::HullVolumeCache(cache_root).path_for(src, 10.0f, 2.0f);
    { std::ofstream s(p, std::ios::binary | std::ios::trunc); s << "junk"; }

    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u) << "junk must be rebaked, never half-trusted";

    voxel::DistanceField f;
    voxel::HullVolumeMeta m;
    EXPECT_TRUE(voxel::read_dhv(p, f, m))
        << "a corrupt entry must be REPLACED by a good one, not just ignored";
    clear_scratch();
}

TEST(HullVolumeCache, RepeatedGetReturnsTheSameObject) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    const voxel::DistanceField& a = c.get(src, 10.0f, 2.0f);
    const voxel::DistanceField& b = c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(&a, &b) << "references must stay stable for the cache's lifetime";
    clear_scratch();
}
```

Register `hull_volume_cache_test.cc` in `native/tests/voxel/CMakeLists.txt`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake --build build --target voxel_tests -j
```

Expected: compile FAILS — `voxel/hull_volume_cache.h` does not exist.

- [ ] **Step 3: Write the header**

Create `native/src/voxel/include/voxel/hull_volume_cache.h`:

```cpp
// native/src/voxel/include/voxel/hull_volume_cache.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <string>
#include <unordered_map>

#include <voxel/dhv.h>
#include <voxel/distance_field.h>

namespace voxel {

/// Default hull-volume quality multiplier: cell = authored_res / quality.
///
/// BC's authored SetDamageResolution is treated as the per-ship RATIO it
/// evidently is (Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15); this
/// sets absolute fidelity globally. 2 rather than 1 because a maximum-size
/// carve is 0.3 GU = 30 model units, which at a Galaxy's authored cell of 10 is
/// a 3-CELL radius -- too coarse to read as a torn hole. At 2x it is 6.
/// Memory is not the constraint: the whole 18-ship stock fleet is 1.0 MB
/// resident at 1x and 7.2 MB at 2x (MEASURED).
inline constexpr float kDefaultQuality = 2.0f;

/// Bakes a hull's signed distance field on first use and caches it on disk.
///
/// Lazy, in-memory-memoized, and keyed by hull path + authored resolution +
/// quality. A cached file is only used when its stored fingerprint still
/// matches the hull on disk AND its baker version matches this build --
/// otherwise it is rebaked. Serving a stale volume is worse than missing a
/// cache hit, because the damage volume would silently not match the geometry.
class HullVolumeCache {
public:
    explicit HullVolumeCache(std::filesystem::path cache_root);

    /// The field for `hull_nif` at this resolution and quality. Loads from
    /// disk when valid, else bakes and writes. The reference is stable for the
    /// lifetime of the cache. Returns an empty field when the hull cannot be
    /// read at all.
    const DistanceField& get(const std::filesystem::path& hull_nif,
                             float authored_res,
                             float quality);

    /// Where `get` would keep this entry. Public so callers (and tests) can
    /// reason about the cache without reaching into its internals.
    std::filesystem::path path_for(const std::filesystem::path& hull_nif,
                                   float authored_res,
                                   float quality) const;

    /// How many times this cache has actually BAKED rather than loaded.
    /// Diagnostics: first-load cost is the whole reason the cache exists, and
    /// a cache that silently never hits is indistinguishable from one that
    /// works except by this number.
    std::size_t bakes() const { return bakes_; }

private:
    std::filesystem::path root_;
    std::unordered_map<std::string, DistanceField> by_key_;
    std::size_t bakes_ = 0;
};

}  // namespace voxel
```

- [ ] **Step 4: Implement it**

Create `native/src/voxel/src/hull_volume_cache.cc`:

```cpp
// native/src/voxel/src/hull_volume_cache.cc
#include <voxel/hull_volume_cache.h>

#include <voxel/voxelize.h>
#include <nif/file.h>

#include <cstdio>
#include <sstream>
#include <system_error>

namespace voxel {

namespace {

// Stable 64-bit hash of the key string. Only needs to avoid collisions across
// one install's hull set, and the file's own header is re-validated on read, so
// a collision degrades to a rebake rather than to a wrong volume.
std::uint64_t fnv1a(const std::string& s) {
    std::uint64_t h = 1469598103934665603ull;
    for (unsigned char c : s) { h ^= c; h *= 1099511628211ull; }
    return h;
}

std::uint32_t file_size_of(const std::filesystem::path& p) {
    std::error_code ec;
    const auto n = std::filesystem::file_size(p, ec);
    return ec ? 0u : static_cast<std::uint32_t>(n);
}

std::int64_t mtime_of(const std::filesystem::path& p) {
    std::error_code ec;
    const auto t = std::filesystem::last_write_time(p, ec);
    if (ec) return 0;
    return static_cast<std::int64_t>(t.time_since_epoch().count());
}

std::string key_string(const std::filesystem::path& hull,
                       float authored_res, float quality) {
    std::ostringstream os;
    os << hull.string() << '|' << authored_res << '|' << quality;
    return os.str();
}

}  // namespace

HullVolumeCache::HullVolumeCache(std::filesystem::path cache_root)
    : root_(std::move(cache_root)) {}

std::filesystem::path HullVolumeCache::path_for(
        const std::filesystem::path& hull_nif,
        float authored_res, float quality) const {
    char name[64];
    std::snprintf(name, sizeof name, "%016llx.dhv",
                  static_cast<unsigned long long>(
                      fnv1a(key_string(hull_nif, authored_res, quality))));
    return root_ / name;
}

const DistanceField& HullVolumeCache::get(
        const std::filesystem::path& hull_nif,
        float authored_res, float quality) {
    const std::string key = key_string(hull_nif, authored_res, quality);
    auto it = by_key_.find(key);
    if (it != by_key_.end()) return it->second;

    const std::filesystem::path cache_file =
        path_for(hull_nif, authored_res, quality);
    const std::uint32_t size  = file_size_of(hull_nif);
    const std::int64_t  mtime = mtime_of(hull_nif);

    // Try the cache. Accept only when the entry still describes THIS hull, at
    // THIS resolution and quality. read_dhv has already rejected a wrong baker
    // version, a bad magic and a short payload.
    {
        DistanceField f;
        HullVolumeMeta m;
        if (read_dhv(cache_file, f, m) &&
            m.source_size == size &&
            m.source_mtime == mtime &&
            m.authored_res == authored_res &&
            m.quality == quality) {
            auto [ins, _] = by_key_.emplace(key, std::move(f));
            return ins->second;
        }
    }

    // Bake.
    ++bakes_;
    DistanceField field;
    if (std::filesystem::exists(hull_nif)) {
        nif::File f = nif::load(hull_nif);
        const std::vector<Tri> tris = collect_hull_triangles_from_nif(f);
        if (!tris.empty()) {
            const float cell = (quality > 0.0f && authored_res > 0.0f)
                             ? authored_res / quality
                             : 0.0f;
            if (cell > 0.0f)
                field = distance_field_from_tris(tris, glm::vec3(cell));
        }
    }

    HullVolumeMeta meta;
    meta.baker_version = kBakerVersion;
    meta.source_size   = size;
    meta.source_mtime  = mtime;
    meta.authored_res  = authored_res;
    meta.quality       = quality;
    meta.source_path   = hull_nif.string();
    write_dhv(cache_file, field, meta);   // best effort: a read-only cache dir
                                          // must not stop the game loading

    auto [ins, _] = by_key_.emplace(key, std::move(field));
    return ins->second;
}

}  // namespace voxel
```

Add `src/hull_volume_cache.cc` to `add_library(voxel STATIC ...)` in
`native/src/voxel/CMakeLists.txt`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build --target voxel_tests -j
./build/native/tests/voxel/voxel_tests --gtest_filter='HullVolumeCache.*'
./build/native/tests/voxel/voxel_tests
```

Expected: all nine PASS, whole binary green.

- [ ] **Step 6: Commit**

```bash
git add native/src/voxel/include/voxel/hull_volume_cache.h native/src/voxel/src/hull_volume_cache.cc native/tests/voxel/hull_volume_cache_test.cc native/src/voxel/CMakeLists.txt native/tests/voxel/CMakeLists.txt
git commit -m "feat(voxel): bake hull distance fields once, cache them on disk

Keyed by hull path + authored resolution + quality; an entry is used only
when its stored fingerprint still matches the hull and its baker version
matches this build. Anything else rebakes -- serving a stale volume is worse
than missing a hit, because the damage volume would silently stop matching
the geometry.

Quality defaults to 2x. A maximum-size carve is 0.3 GU = 30 model units,
which at a Galaxy's authored cell of 10 is a 3-cell radius: too coarse to
read as a torn hole. Memory is not the constraint -- the whole stock fleet
measures 1.0 MB resident at 1x, 7.2 MB at 2x.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Feed the bake BC's authored resolution

Spec §2.3 / §9. `ShipProperty.SetDamageResolution` is authored per ship in every
hardpoint file, copied onto the ship at `engine/appc/ships.py:1164`, stored in
`_damage_resolution` — and **read by nothing**. This wires it to the baker.

**Files:**
- Create: `engine/appc/hull_volume.py`
- Create: `tests/unit/test_hull_volume_resolution.py`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`
- Modify: `engine/host_loop.py:4792` **and** `engine/host_loop.py:5423`

**Interfaces:**
- Consumes: `HullVolumeCache` (Task 5); `ShipClass.GetDamageResolution()` (existing, `engine/appc/ships.py:855`).
- Produces:
  - native binding `_dauntless_host.hull_volume_set_resolution(instance_id: int, resolution: float) -> None`
  - `engine.renderer.hull_volume_set_resolution(iid, resolution)`
  - `engine.appc.hull_volume.push_resolution(ship, iid) -> bool` — True when a positive resolution was pushed.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_hull_volume_resolution.py`:

```python
"""BC authors a damage-volume resolution per ship; we never read it.

`ShipProperty.SetDamageResolution` is set in every hardpoint file (Shuttle 6,
Akira 8, Galaxy 10, Warbird 12, stations 15) and copied onto the ship at
engine/appc/ships.py:1164 -- into a field nothing consumes. It is the per-ship
detail ratio the hull-volume baker needs, and it is also finer than what BC
itself shipped: the Warbird's authored 12 against a baked cell size of 25 is
why its breaches cut into nothing.
"""
import pytest

from engine.appc import hull_volume


class FakeShip:
    def __init__(self, resolution):
        self._resolution = resolution

    def GetDamageResolution(self):
        return self._resolution


class Recorder:
    def __init__(self):
        self.calls = []

    def hull_volume_set_resolution(self, iid, resolution):
        self.calls.append((iid, resolution))


@pytest.fixture
def recorder(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


def test_authored_resolution_reaches_the_renderer(recorder):
    assert hull_volume.push_resolution(FakeShip(8.0), 42) is True
    assert recorder.calls == [(42, 8.0)]


def test_each_ship_pushes_its_own_resolution(recorder):
    hull_volume.push_resolution(FakeShip(6.0), 1)    # Shuttle
    hull_volume.push_resolution(FakeShip(12.0), 2)   # Warbird
    assert recorder.calls == [(1, 6.0), (2, 12.0)]


def test_unset_resolution_is_not_pushed(recorder):
    """The field defaults to 0.0 (engine/appc/ships.py:91). Pushing that would
    make the baker divide by zero; the native default must stand instead."""
    assert hull_volume.push_resolution(FakeShip(0.0), 7) is False
    assert recorder.calls == []


def test_negative_resolution_is_not_pushed(recorder):
    assert hull_volume.push_resolution(FakeShip(-3.0), 7) is False
    assert recorder.calls == []


def test_a_ship_without_the_accessor_is_skipped(recorder):
    """Not every DamageableObject is a ShipClass."""
    assert hull_volume.push_resolution(object(), 7) is False
    assert recorder.calls == []


def test_a_renderer_failure_does_not_propagate(recorder, monkeypatch):
    """Spawn must never fail because a VFX detail could not be pushed."""
    def boom(iid, resolution):
        raise RuntimeError("no renderer")
    monkeypatch.setattr(recorder, "hull_volume_set_resolution", boom)
    assert hull_volume.push_resolution(FakeShip(10.0), 7) is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_hull_volume_resolution.py -v
```

Expected: FAIL — `ModuleNotFoundError: engine.appc.hull_volume`.

- [ ] **Step 3: Add the native binding**

In `native/src/host/host_bindings.cc`, immediately after the `m.def("hull_carve_add", ...)` block (which ends around line 4140), add:

```cpp
    // BC authors a damage-volume resolution per ship
    // (ShipProperty.SetDamageResolution, in every hardpoint file). It is the
    // cell size in MODEL UNITS the hull volume should be baked at -- a per-ship
    // detail ratio, which the quality multiplier then scales globally.
    m.def("hull_volume_set_resolution",
          [](scenegraph::InstanceId id, float resolution) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;      // stale id — drop silently
              if (!(resolution > 0.0f)) return; // unset: keep the native default
              // An Instance holds a model_handle, not a path. resolve_model is
              // the idiom used throughout this file (e.g. line 4169), and
              // model->source is the same key breach_pass.cc:328 hands to
              // CarveFieldCache::get_for_source -- so the resolution is keyed
              // by exactly the string the volume will be looked up by.
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return;
              renderer::set_hull_volume_resolution(model->source, resolution);
          },
          pybind11::arg("instance_id"), pybind11::arg("resolution"));
```

`host_bindings.cc` already includes `renderer/carve_field_cache.h` transitively
via `renderer/frame.h`; if the build cannot see `set_hull_volume_resolution`,
add `#include <renderer/carve_field_cache.h>` to its include block rather than
declaring the function locally.

Add to `native/src/renderer/include/renderer/carve_field_cache.h`, in
`namespace renderer`, above `class CarveFieldCache`:

```cpp
/// Record the authored damage-volume cell size (model units) for a hull source.
/// Set from Python at spawn out of BC's ShipProperty.SetDamageResolution.
void set_hull_volume_resolution(const std::filesystem::path& source, float cell);

/// The authored cell size for a hull source, or 0 when none was set.
float hull_volume_resolution(const std::filesystem::path& source);
```

And in `native/src/renderer/carve_field_cache.cc`, above `CarveFieldCache::~CarveFieldCache()`:

```cpp
namespace {
std::unordered_map<std::string, float>& resolution_table() {
    static std::unordered_map<std::string, float> t;
    return t;
}
}  // namespace

void set_hull_volume_resolution(const std::filesystem::path& source, float cell) {
    if (source.empty() || !(cell > 0.0f)) return;
    resolution_table()[source.string()] = cell;
}

float hull_volume_resolution(const std::filesystem::path& source) {
    auto it = resolution_table().find(source.string());
    return (it == resolution_table().end()) ? 0.0f : it->second;
}
```

Add `#include <string>` and `#include <unordered_map>` to that .cc if absent.

- [ ] **Step 4: Add the renderer façade entry**

In `engine/renderer.py`, add `"hull_volume_set_resolution"` to the `__all__`-style
name list, which is alphabetical — insert it after `"hdr_set_enabled",` and
before `"init",` (around line 51). Then add:

```python
def hull_volume_set_resolution(iid: InstanceId, resolution: float) -> None:
    """Record BC's authored damage-volume cell size for this instance's hull.

    No hasattr guard, deliberately. host_loop.py:4780 documents a feature that
    shipped completely inert because a hasattr guard turned a loud missing-
    binding failure into a silent per-ship skip.
    """
    _h.hull_volume_set_resolution(iid, float(resolution))
```

- [ ] **Step 5: Write the Python module**

Create `engine/appc/hull_volume.py`:

```python
"""Push BC's authored damage-volume resolution to the hull-volume baker.

`ShipProperty.SetDamageResolution` is authored per ship in every hardpoint file
-- Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15 -- and copied onto the
ship by `ShipClass` property application. Until now nothing read it.

It is the cell size, in MODEL UNITS, that the ship's damage volume should be
baked at: a per-ship detail ratio which a global quality multiplier then scales.
It is also finer than what BC itself shipped (Galaxy 10 vs a baked 15, Akira 8
vs 15, Warbird 12 vs 25) -- and the Warbird, the worst mismatch in the fleet, is
exactly the ship whose breaches were seen cutting into nothing.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md
"""
from engine import renderer as _renderer

__all__ = ["push_resolution"]


def push_resolution(ship, iid) -> bool:
    """Send `ship`'s authored resolution for instance `iid`.

    Returns True only when a positive resolution was actually pushed. A ship
    that never had one keeps the native default rather than being handed 0.0,
    which the baker would divide by.

    Never raises: a ship must spawn even if this VFX detail cannot be recorded.
    """
    getter = getattr(ship, "GetDamageResolution", None)
    if getter is None:
        return False
    try:
        resolution = float(getter())
    except (TypeError, ValueError):
        return False
    if not resolution > 0.0:
        return False
    try:
        _renderer.hull_volume_set_resolution(iid, resolution)
    except Exception:
        return False
    return True
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_hull_volume_resolution.py -v
```

Expected: all six PASS.

- [ ] **Step 7: Wire both spawn sites**

There are **two** instance-registration sites and both must push, or the feature
works for ships spawned one way and not the other.

In `engine/host_loop.py`, after `session.ship_instances[ship] = iid` (line 4792)
and after `sess.ship_instances[ship] = iid` (line 5423), add at the same
indentation:

```python
        # BC's authored damage-volume cell size for this hull
        # (ShipProperty.SetDamageResolution). Best-effort: never block spawn.
        try:
            from engine.appc.hull_volume import push_resolution
            push_resolution(ship, iid)
        except Exception as _e:
            dev_mode.log_swallowed("push hull volume resolution", _e)
```

Match the surrounding indentation at each site — the second is nested one level
deeper than the first.

- [ ] **Step 8: Build and run the full gate**

```bash
cmake -B build -S . && cmake --build build -j
./scripts/check_tests.sh
```

Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression
from this task — fix it, do not baseline it.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/hull_volume.py tests/unit/test_hull_volume_resolution.py engine/renderer.py engine/host_loop.py native/src/host/host_bindings.cc native/src/renderer/carve_field_cache.cc native/src/renderer/include/renderer/carve_field_cache.h
git commit -m "feat(engine): consume BC's authored damage-volume resolution

ShipProperty.SetDamageResolution is authored in every hardpoint file
(Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15), copied onto the
ship at ships.py:1164, and read by nothing. It is the per-ship cell size the
hull-volume baker needs.

It is finer than what BC itself shipped -- Galaxy 10 vs a baked 15, Akira 8
vs 15, Warbird 12 vs 25 -- and the Warbird, the worst mismatch in the fleet,
is the ship whose breaches were observed cutting into nothing.

Pushed from BOTH instance-registration sites in host_loop; wiring only one
would work for ships spawned one way and silently not the other. No hasattr
guard on the binding: host_loop.py:4780 records a feature that shipped
entirely inert because one turned a loud failure into a silent skip.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Make the SDK damage-geometry switches real

Spec §9. Six `App.DamageableObject_*` entry points are truthy `_NamedStub`s
today (verified by import, not inference). `E3M1.py:3001-3003` reads three of
them to save and restore damage state around a cutscene.

**Files:**
- Create: `engine/appc/damage_geometry.py`
- Create: `tests/unit/test_damage_geometry_flags.py`
- Modify: `engine/appc/objects.py`
- Modify: `App.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `engine.appc.damage_geometry`:
  - `BREAKABLE_MIN_RADIUS_GU = 2.381`
  - `set_damage_geometry_enabled(v)` / `is_damage_geometry_enabled() -> int`
  - `set_volume_damage_geometry_enabled(v)` / `is_volume_damage_geometry_enabled() -> int`
  - `set_breakable_components_enabled(v)` / `is_breakable_components_enabled() -> int`
  - `breakables_allowed_for(ship) -> bool`
  - `reset()` — restores defaults (used by the test-isolation fixture)
- And, re-exported through `engine.appc.objects` and `App`:
  `DamageableObject_SetDamageGeometryEnabled`, `DamageableObject_IsDamageGeometryEnabled`, `DamageableObject_SetVolumeDamageGeometryEnabled`, `DamageableObject_IsVolumeDamageGeometryEnabled`, `DamageableObject_SetBreakableComponentsEnabled`, `DamageableObject_IsBreakableComponentsEnabled`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_damage_geometry_flags.py`:

```python
"""BC's damage-geometry switches, which were truthy stubs.

App.DamageableObject_{Set,Is}{DamageGeometry,VolumeDamageGeometry,
BreakableComponents}Enabled are real Appc surface. Ours were `_NamedStub`s, so
`IsVolumeDamageGeometryEnabled()` returned a truthy stub object rather than a
flag -- the classic silent-stub bug class this project keeps a heatmap for.

E3M1.py:3001-3003 reads all three into g_pVisibleDamageState to save and
restore damage state around a cutscene.

Policy: in Dauntless damage is always on, so all three default enabled, but the
setters are honoured so a mission can still suppress damage for a cutscene.
Breakable components additionally require a hull larger than a Cardassian
Galor.
"""
import pytest

import App
from engine.appc import damage_geometry


class FakeShip:
    def __init__(self, radius_gu):
        self._radius = radius_gu

    def GetRadius(self):
        return self._radius


@pytest.fixture(autouse=True)
def _reset():
    damage_geometry.reset()
    yield
    damage_geometry.reset()


# --- the flags themselves ---------------------------------------------------

def test_all_three_default_on():
    """In Dauntless damage is always on."""
    assert damage_geometry.is_damage_geometry_enabled() == 1
    assert damage_geometry.is_volume_damage_geometry_enabled() == 1
    assert damage_geometry.is_breakable_components_enabled() == 1


def test_setters_round_trip():
    damage_geometry.set_damage_geometry_enabled(0)
    assert damage_geometry.is_damage_geometry_enabled() == 0
    damage_geometry.set_damage_geometry_enabled(1)
    assert damage_geometry.is_damage_geometry_enabled() == 1


def test_the_three_flags_are_independent():
    """E3M1 saves and restores them separately; sharing state would restore
    the wrong values."""
    damage_geometry.set_volume_damage_geometry_enabled(0)
    assert damage_geometry.is_volume_damage_geometry_enabled() == 0
    assert damage_geometry.is_damage_geometry_enabled() == 1
    assert damage_geometry.is_breakable_components_enabled() == 1


def test_getters_return_ints_not_objects():
    """The bug being fixed: a truthy stub OBJECT passed `if x:` and was stored
    into g_pVisibleDamageState, so the restore wrote a stub back."""
    for getter in (damage_geometry.is_damage_geometry_enabled,
                   damage_geometry.is_volume_damage_geometry_enabled,
                   damage_geometry.is_breakable_components_enabled):
        assert type(getter()) is int


# --- the App-module surface -------------------------------------------------

@pytest.mark.parametrize("name", [
    "DamageableObject_SetDamageGeometryEnabled",
    "DamageableObject_IsDamageGeometryEnabled",
    "DamageableObject_SetVolumeDamageGeometryEnabled",
    "DamageableObject_IsVolumeDamageGeometryEnabled",
    "DamageableObject_SetBreakableComponentsEnabled",
    "DamageableObject_IsBreakableComponentsEnabled",
])
def test_app_surface_is_real_not_a_stub(name):
    fn = getattr(App, name)
    assert type(fn).__name__ != "_NamedStub", f"{name} is still a stub"


def test_app_setter_drives_the_flag():
    App.DamageableObject_SetVolumeDamageGeometryEnabled(0)
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 0
    App.DamageableObject_SetVolumeDamageGeometryEnabled(1)
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 1


def test_e3m1_save_and_restore_round_trips():
    """The exact shape of E3M1.py:2998-3022."""
    saved = [App.DamageableObject_IsDamageGeometryEnabled(),
             App.DamageableObject_IsVolumeDamageGeometryEnabled(),
             App.DamageableObject_IsBreakableComponentsEnabled()]
    App.DamageableObject_SetDamageGeometryEnabled(0)
    App.DamageableObject_SetVolumeDamageGeometryEnabled(0)
    App.DamageableObject_SetBreakableComponentsEnabled(0)
    App.DamageableObject_SetDamageGeometryEnabled(saved[0])
    App.DamageableObject_SetVolumeDamageGeometryEnabled(saved[1])
    App.DamageableObject_SetBreakableComponentsEnabled(saved[2])
    assert App.DamageableObject_IsDamageGeometryEnabled() == 1
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 1
    assert App.DamageableObject_IsBreakableComponentsEnabled() == 1


# --- the radius gate --------------------------------------------------------

# Bounding radii MEASURED from the stock hull NIFs, 2026-09-08, in GU.
# Mark's rule: breakable above a Cardassian Galor.
BREAKABLE = [
    ("Akira", 2.552), ("Nebula", 2.416), ("Ambassador", 3.144),
    ("Keldon", 3.160), ("Transport", 3.238), ("KessokLight", 3.340),
    ("Galaxy", 3.500), ("Vorcha", 3.523), ("Sovereign", 3.807),
    ("CardHybrid", 4.960), ("Warbird", 6.516), ("KessokHeavy", 7.500),
]
NOT_BREAKABLE = [
    ("Shuttle", 0.141), ("BirdOfPrey", 1.335), ("Freighter", 1.955),
    ("CardFreighter", 2.002), ("Marauder", 2.020), ("Galor", 2.381),
]


@pytest.mark.parametrize("name,radius", BREAKABLE)
def test_ships_larger_than_a_galor_are_breakable(name, radius):
    assert damage_geometry.breakables_allowed_for(FakeShip(radius)), name


@pytest.mark.parametrize("name,radius", NOT_BREAKABLE)
def test_ships_no_larger_than_a_galor_are_not(name, radius):
    assert not damage_geometry.breakables_allowed_for(FakeShip(radius)), name


def test_the_nebula_margin_is_deliberate():
    """The Nebula clears the Galor by 1.5% (2.416 vs 2.381). This test exists
    so that a change to how GetRadius is derived -- an OPEN question against
    the clean-room reference, which puts a Galaxy nearer 4 GU than our 3.5 --
    surfaces as a failure instead of silently re-sorting the fleet."""
    assert damage_geometry.BREAKABLE_MIN_RADIUS_GU == pytest.approx(2.381)
    assert damage_geometry.breakables_allowed_for(FakeShip(2.416))
    assert not damage_geometry.breakables_allowed_for(FakeShip(2.381))


def test_the_global_flag_overrides_the_radius_gate():
    """A mission disabling breakables must disable them for a Sovereign too."""
    damage_geometry.set_breakable_components_enabled(0)
    assert not damage_geometry.breakables_allowed_for(FakeShip(3.807))


def test_a_ship_without_a_radius_is_not_breakable():
    assert not damage_geometry.breakables_allowed_for(object())
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_damage_geometry_flags.py -v
```

Expected: FAIL — `ModuleNotFoundError: engine.appc.damage_geometry`.

- [ ] **Step 3: Write the module**

Create `engine/appc/damage_geometry.py`:

```python
"""BC's damage-geometry switches — real flags, not stubs.

`App.DamageableObject_{Set,Is}{DamageGeometry,VolumeDamageGeometry,
BreakableComponents}Enabled` are genuine Appc surface. Ours were `_NamedStub`s,
so every getter returned a truthy stub object instead of a flag.
`Maelstrom/Episode3/E3M1/E3M1.py:3001-3003` reads all three into
`g_pVisibleDamageState` to save and restore damage state around a cutscene, so
the stubs were being stored and written back.

Policy: in Dauntless damage is always on, so all three default enabled. The
setters are still honoured, because a mission legitimately wants to suppress
damage for a cutscene.

`BreakableComponents` is BC's name for pieces breaking off a ship. Hulls are
authored as named body sections (Galaxy: `Ent-D Saucer Section`, `Ent-D-Hull`,
`Ent-D-Neck`; Galor: `galor wing left`/`right`), so the pieces exist -- but the
names are ad-hoc per ship and nothing in the SDK designates breakability, so we
detect breaks from the hull volume rather than from authored data.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md §8-§9.
"""

__all__ = [
    "BREAKABLE_MIN_RADIUS_GU",
    "reset",
    "set_damage_geometry_enabled", "is_damage_geometry_enabled",
    "set_volume_damage_geometry_enabled", "is_volume_damage_geometry_enabled",
    "set_breakable_components_enabled", "is_breakable_components_enabled",
    "breakables_allowed_for",
]

# A Cardassian Galor's bounding radius, MEASURED from its stock hull NIF
# (238.1 model units x BC_MODEL_SCALE 0.01). Mark's rule: a ship breaks into
# components only if it is larger than a Galor.
#
# The Nebula clears this by 1.5% (2.416), and how GetRadius should be derived is
# itself an open question against the clean-room reference -- so
# tests/unit/test_damage_geometry_flags.py pins the whole stock fleet either
# side of this line. Change the constant and that test tells you exactly which
# ships changed sides.
BREAKABLE_MIN_RADIUS_GU = 2.381

# In Dauntless damage is always on.
_DEFAULTS = {"damage": 1, "volume": 1, "breakable": 1}
_state = dict(_DEFAULTS)


def reset() -> None:
    """Restore launch defaults. For test isolation and mission swaps."""
    _state.update(_DEFAULTS)


def _set(key, value) -> None:
    try:
        _state[key] = 1 if int(value) else 0
    except (TypeError, ValueError):
        pass


def set_damage_geometry_enabled(value) -> None:
    _set("damage", value)


def is_damage_geometry_enabled() -> int:
    return _state["damage"]


def set_volume_damage_geometry_enabled(value) -> None:
    _set("volume", value)


def is_volume_damage_geometry_enabled() -> int:
    return _state["volume"]


def set_breakable_components_enabled(value) -> None:
    _set("breakable", value)


def is_breakable_components_enabled() -> int:
    return _state["breakable"]


def breakables_allowed_for(ship) -> bool:
    """True when `ship` may break into components: the global flag is on AND
    the hull is larger than a Galor. Strictly larger — a Galor is the floor,
    not the smallest qualifier."""
    if not _state["breakable"]:
        return False
    getter = getattr(ship, "GetRadius", None)
    if getter is None:
        return False
    try:
        radius = float(getter())
    except (TypeError, ValueError):
        return False
    return radius > BREAKABLE_MIN_RADIUS_GU
```

- [ ] **Step 4: Export the App-module surface**

At the end of `engine/appc/objects.py`, add:

```python
# --- BC's damage-geometry switches (App-module functions, not methods) ------
# App.py binds these at module level (App.py:11251-11261), not on the class.
# They were truthy _NamedStubs; E3M1 stores their results and writes them back.
from engine.appc import damage_geometry as _damage_geometry


def DamageableObject_SetDamageGeometryEnabled(value) -> None:
    _damage_geometry.set_damage_geometry_enabled(value)


def DamageableObject_IsDamageGeometryEnabled() -> int:
    return _damage_geometry.is_damage_geometry_enabled()


def DamageableObject_SetVolumeDamageGeometryEnabled(value) -> None:
    _damage_geometry.set_volume_damage_geometry_enabled(value)


def DamageableObject_IsVolumeDamageGeometryEnabled() -> int:
    return _damage_geometry.is_volume_damage_geometry_enabled()


def DamageableObject_SetBreakableComponentsEnabled(value) -> None:
    _damage_geometry.set_breakable_components_enabled(value)


def DamageableObject_IsBreakableComponentsEnabled() -> int:
    return _damage_geometry.is_breakable_components_enabled()
```

In `App.py`, extend the `from engine.appc.objects import (...)` block (lines
113-122) by adding these six names after `DamageableObject_GetObjectByID,`:

```python
    DamageableObject_SetDamageGeometryEnabled,
    DamageableObject_IsDamageGeometryEnabled,
    DamageableObject_SetVolumeDamageGeometryEnabled,
    DamageableObject_IsVolumeDamageGeometryEnabled,
    DamageableObject_SetBreakableComponentsEnabled,
    DamageableObject_IsBreakableComponentsEnabled,
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_damage_geometry_flags.py -v
```

Expected: all PASS (33 including the parametrized fleet cases).

- [ ] **Step 6: Add the flags to the leak-reset fixture**

Module-level state leaks across tests. In `tests/conftest.py`, find the autouse
`_reset_leakable_engine_globals` fixture and add a reset for this module,
matching the style of the resets already there:

```python
    try:
        from engine.appc import damage_geometry
        damage_geometry.reset()
    except Exception:
        pass
```

The bare `except Exception: pass` matches the style of every other reset in that
fixture (`tests/conftest.py:704-729`): the fixture is autouse, so an import
failure there would fail every test in the suite rather than the one that
matters.

- [ ] **Step 7: Run the full gate**

```bash
./scripts/check_tests.sh
```

Expected: exit 0. Watch specifically for tests that previously relied on a
truthy stub here — a getter now returning `0` where a stub was truthy is a
behaviour change, and any such failure is real, not noise.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/damage_geometry.py engine/appc/objects.py App.py tests/unit/test_damage_geometry_flags.py tests/conftest.py
git commit -m "feat(appc): real flags for BC's damage-geometry switches

App.DamageableObject_{Set,Is}{DamageGeometry,VolumeDamageGeometry,
BreakableComponents}Enabled were all truthy _NamedStubs, so every getter
returned a stub object rather than a flag. E3M1.py:3001-3003 reads all three
into g_pVisibleDamageState and writes them back around a cutscene, so the
stubs were being stored and restored.

In Dauntless damage is always on: all three default enabled, setters still
honoured so a mission can suppress damage for a cutscene.

Breakable components additionally require a hull larger than a Cardassian
Galor (2.381 GU, measured). The Nebula clears that by 1.5% and our GetRadius
derivation is an open question against the clean-room reference, so the test
pins the whole stock fleet either side of the line -- a change to radius
derivation fails loudly instead of silently re-sorting the fleet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Done criteria for plan 1

- `scripts/check_tests.sh` exits 0.
- `.dhv` files appear under `cache/hull_volumes/` after a run and are reused on the next.
- `voxelize_tris` no longer collapses: solid fraction rises with resolution.
- `SetDamageResolution` reaches the baker from both spawn paths.
- No `App.DamageableObject_*Enabled` name resolves to a `_NamedStub`.
- Nothing visible changes in game. Plan 2 makes the field authoritative.
