# Voxel Hull-Damage Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a correct solid voxel volume for any ship — by two independent paths (decode a shipped `*_vox.nif`, and voxelize the hull mesh) that validate each other on the Galaxy.

**Architecture:** New `native/src/voxel/` module owns a `VoxelVolume` value type, a hull voxelizer (triangle-soup → surface raster → flood-fill solidify), and an IoU comparator. The NIF decoder (extended in `native/src/nif/`) parses `NiBinaryVoxelData` into the same `VoxelVolume`. A debug point-dump lets us eyeball both. Validation = decode-vs-voxelize IoU on the Galaxy.

**Tech Stack:** C++17, glm, GoogleTest (`nif_tests` pattern), CMake. Voxelizer input is `assets::Model` (the existing scene-graph flattener with per-node transforms). Reference spec: `docs/superpowers/specs/2026-06-16-voxel-hull-damage-foundation-design.md`.

**Reverse-engineering note:** This plan has two phases. **Phase A (Tasks 1–5)** is fully knowable now (volume + voxelizer) and is plain TDD. **Phase B (Tasks 6–8)** decodes an undocumented binary format; Task 6 is an *investigation* whose findings pin the exact byte layout used by Tasks 7–8. Where a constant is recovered by investigation, the plan says so explicitly and the surrounding scaffolding is concrete. **Phase C (Tasks 9–10)** closes the validation loop. Re-read Task 6's findings before starting Task 7.

---

## File Structure

- `native/src/voxel/include/voxel/volume.h` — `VoxelVolume` type + index/query helpers (one responsibility: the volume data structure).
- `native/src/voxel/include/voxel/voxelize.h` — public voxelizer + comparator API.
- `native/src/voxel/src/volume.cc` — `VoxelVolume` methods, `iou`.
- `native/src/voxel/src/voxelize.cc` — `collect_hull_triangles`, `surface_voxelize`, `solidify`, `voxelize`.
- `native/src/voxel/src/decode.cc` — `from_nif_voxel_data` (payload → occupancy).
- `native/src/voxel/CMakeLists.txt` — `voxel` static lib.
- `native/src/nif/src/blocks/extra_data.cc` — **modify**: parse `NiBinaryVoxelData` header into typed fields (dims, bounds).
- `native/src/nif/include/nif/block.h` — **modify**: rename the speculative voxel header fields to recovered names.
- `native/tests/voxel/` — new gtest target `voxel_tests` (`volume_test.cc`, `voxelize_test.cc`, `decode_test.cc`).
- `native/tests/voxel/CMakeLists.txt` + register in `native/tests/CMakeLists.txt`.
- `native/tools/voxel_inspect/` — investigation + point-dump CLI.
- `docs/original_game_reference/engine/nif-voxel-format.md` — **created in Task 6**: the recovered format spec.

---

## Phase A — Volume + Voxelizer

### Task 1: Voxel module skeleton + `VoxelVolume`

**Files:**
- Create: `native/src/voxel/include/voxel/volume.h`
- Create: `native/src/voxel/src/volume.cc`
- Create: `native/src/voxel/CMakeLists.txt`
- Create: `native/tests/voxel/volume_test.cc`
- Create: `native/tests/voxel/CMakeLists.txt`
- Modify: `native/tests/CMakeLists.txt` (add `add_subdirectory(voxel)`)
- Modify: `native/CMakeLists.txt` or `native/src/CMakeLists.txt` (add `add_subdirectory(voxel)` next to the other `src/` modules)

- [ ] **Step 1: Write the failing test**

`native/tests/voxel/volume_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <voxel/volume.h>

using voxel::VoxelVolume;

TEST(VoxelVolume, IndexRoundTripAndSetGet) {
    VoxelVolume v;
    v.dims = {4, 3, 2};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 3 * 2, 0);

    EXPECT_EQ(v.index(0, 0, 0), 0u);
    EXPECT_EQ(v.index(3, 2, 1), 4u * 3u * 2u - 1u);  // last voxel

    EXPECT_FALSE(v.solid(2, 1, 1));
    v.set(2, 1, 1, true);
    EXPECT_TRUE(v.solid(2, 1, 1));
    EXPECT_EQ(v.solid_count(), 1u);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j voxel_tests`
Expected: FAIL to compile — `voxel/volume.h` not found.

- [ ] **Step 3: Write minimal implementation**

`native/src/voxel/include/voxel/volume.h`:
```cpp
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>

namespace voxel {

/// Solid voxel volume. Occupancy is one byte per voxel (1 = solid), indexed
/// x-fastest then y then z. In-memory representation; the on-disk BC format
/// is bit-packed and decoded into this by from_nif_voxel_data().
struct VoxelVolume {
    glm::ivec3 dims{0};        // nx, ny, nz
    glm::vec3  origin{0.f};    // body-frame position of voxel (0,0,0) min corner
    glm::vec3  cell{1.f};      // cell size per axis
    std::vector<std::uint8_t> occ;

    std::size_t index(int x, int y, int z) const {
        return static_cast<std::size_t>(x)
             + static_cast<std::size_t>(dims.x) * (y + static_cast<std::size_t>(dims.y) * z);
    }
    bool solid(int x, int y, int z) const { return occ[index(x, y, z)] != 0; }
    void set(int x, int y, int z, bool v) { occ[index(x, y, z)] = v ? 1 : 0; }
    std::size_t solid_count() const;
};

}  // namespace voxel
```

`native/src/voxel/src/volume.cc`:
```cpp
#include <voxel/volume.h>

namespace voxel {

std::size_t VoxelVolume::solid_count() const {
    std::size_t n = 0;
    for (auto b : occ) n += (b != 0);
    return n;
}

}  // namespace voxel
```

`native/src/voxel/CMakeLists.txt`:
```cmake
add_library(voxel STATIC
    src/volume.cc
    src/voxelize.cc
    src/decode.cc
)
target_include_directories(voxel PUBLIC include)
target_link_libraries(voxel PUBLIC nif assets glm)
```
(Create empty `src/voxelize.cc` and `src/decode.cc` with just `#include` lines for now so the lib links; later tasks fill them.)

`native/tests/voxel/CMakeLists.txt`:
```cmake
add_executable(voxel_tests
    volume_test.cc
    voxelize_test.cc
    decode_test.cc
)
target_link_libraries(voxel_tests PRIVATE voxel GTest::gtest_main)
target_compile_definitions(voxel_tests PRIVATE
    OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}")
gtest_discover_tests(voxel_tests)
```
(Create empty `voxelize_test.cc` and `decode_test.cc` with `#include <gtest/gtest.h>` so the target builds.)

Add `add_subdirectory(voxel)` to `native/tests/CMakeLists.txt` (next to `add_subdirectory(scenegraph)`), and `add_subdirectory(voxel)` to the `src/` module list in `native/CMakeLists.txt` (find where `nif`, `assets`, `scenegraph` are added).

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j voxel_tests && ctest --test-dir build -R VoxelVolume --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel native/tests/voxel native/tests/CMakeLists.txt native/CMakeLists.txt
git commit -m "feat(voxel): module skeleton + VoxelVolume type"
```

---

### Task 2: Collect hull triangles from `assets::Model`

**Files:**
- Modify: `native/src/voxel/include/voxel/voxelize.h` (create)
- Modify: `native/src/voxel/src/voxelize.cc`
- Test: `native/tests/voxel/voxelize_test.cc`

Confirm `assets::Mesh`'s vertex/index field names before writing (`grep -n . native/src/assets/include/assets/mesh.h`). The code below assumes `mesh.vertices` (a `std::vector<glm::vec3>` of positions) and `mesh.indices` (a `std::vector<uint32_t>` triangle list). Adjust names to match.

- [ ] **Step 1: Write the failing test**

`native/tests/voxel/voxelize_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <voxel/voxelize.h>
#include <assets/model.h>

// Build a 1-triangle model: identity node, one mesh with 3 verts.
static assets::Model one_triangle_model() {
    assets::Model m;
    assets::Node n; n.parent_index = -1; n.meshes = {0};
    m.nodes = {n}; m.root_node = 0;
    assets::Mesh mesh;
    mesh.vertices = { {0,0,0}, {2,0,0}, {0,2,0} };
    mesh.indices  = { 0, 1, 2 };
    m.meshes = {mesh};
    return m;
}

TEST(CollectHullTriangles, TransformsVertsToBodyFrame) {
    auto m = one_triangle_model();
    auto tris = voxel::collect_hull_triangles(m);
    ASSERT_EQ(tris.size(), 1u);
    EXPECT_FLOAT_EQ(tris[0].a.x, 0.f);
    EXPECT_FLOAT_EQ(tris[0].b.x, 2.f);
    EXPECT_FLOAT_EQ(tris[0].c.y, 2.f);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `collect_hull_triangles` undeclared.

- [ ] **Step 3: Write minimal implementation**

`native/src/voxel/include/voxel/voxelize.h`:
```cpp
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>
namespace assets { struct Model; }

namespace voxel {

struct Tri { glm::vec3 a, b, c; };

/// Flatten every mesh in the model into one triangle soup, each vertex
/// transformed by its node's accumulated world transform (root -> node).
std::vector<Tri> collect_hull_triangles(const assets::Model& model);

}  // namespace voxel
```

`native/src/voxel/src/voxelize.cc`:
```cpp
#include <voxel/voxelize.h>
#include <assets/model.h>

namespace voxel {

static glm::mat4 world_transform(const assets::Model& m, int node_idx) {
    glm::mat4 t(1.0f);
    // Walk parent chain, accumulating root -> node.
    std::vector<int> chain;
    for (int i = node_idx; i >= 0; i = m.nodes[i].parent_index) chain.push_back(i);
    for (auto it = chain.rbegin(); it != chain.rend(); ++it)
        t = t * m.nodes[*it].local_transform;
    return t;
}

std::vector<Tri> collect_hull_triangles(const assets::Model& model) {
    std::vector<Tri> out;
    for (int ni = 0; ni < static_cast<int>(model.nodes.size()); ++ni) {
        const glm::mat4 w = world_transform(model, ni);
        for (int mi : model.nodes[ni].meshes) {
            const auto& mesh = model.meshes[mi];
            for (std::size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
                auto P = [&](std::uint32_t vi) {
                    glm::vec4 p = w * glm::vec4(mesh.vertices[vi], 1.0f);
                    return glm::vec3(p);
                };
                out.push_back({P(mesh.indices[i]), P(mesh.indices[i+1]), P(mesh.indices[i+2])});
            }
        }
    }
    return out;
}

}  // namespace voxel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R CollectHullTriangles --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel native/tests/voxel/voxelize_test.cc
git commit -m "feat(voxel): collect hull triangles with world transforms"
```

---

### Task 3: Surface voxelization

**Files:**
- Modify: `native/src/voxel/include/voxel/voxelize.h`
- Modify: `native/src/voxel/src/voxelize.cc`
- Test: `native/tests/voxel/voxelize_test.cc`

- [ ] **Step 1: Write the failing test**

Append to `voxelize_test.cc`:
```cpp
TEST(SurfaceVoxelize, MarksVoxelsTrianglePassesThrough) {
    voxel::VoxelVolume v;
    v.dims = {8, 8, 8};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(8 * 8 * 8, 0);
    // A triangle lying in the z=4 plane spanning x,y in [1,6].
    std::vector<voxel::Tri> tris = {
        {{1,1,4},{6,1,4},{1,6,4}}
    };
    voxel::surface_voxelize(v, tris);
    EXPECT_GT(v.solid_count(), 0u);
    EXPECT_TRUE(v.solid(2, 2, 4));   // inside the triangle, on its plane
    EXPECT_FALSE(v.solid(2, 2, 0));  // far from the triangle
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `surface_voxelize` undeclared.

- [ ] **Step 3: Write minimal implementation**

Add to `voxelize.h`:
```cpp
/// Rasterize each triangle into the grid, marking every voxel the triangle
/// overlaps as solid. Voxels outside [0,dims) are skipped.
void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris);
```

Add to `voxelize.cc` (simple, correct-first triangle-AABB-overlap raster; optimize later if needed):
```cpp
#include <algorithm>
#include <cmath>

namespace voxel {
namespace {
glm::ivec3 to_cell(const VoxelVolume& v, glm::vec3 p) {
    glm::vec3 g = (p - v.origin) / v.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}
bool tri_overlaps_voxel(const Tri& t, glm::vec3 lo, glm::vec3 hi); // SAT, defined below
}  // namespace

void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris) {
    for (const auto& t : tris) {
        glm::vec3 mn = glm::min(t.a, glm::min(t.b, t.c));
        glm::vec3 mx = glm::max(t.a, glm::max(t.b, t.c));
        glm::ivec3 c0 = glm::clamp(to_cell(v, mn), glm::ivec3(0), v.dims - 1);
        glm::ivec3 c1 = glm::clamp(to_cell(v, mx), glm::ivec3(0), v.dims - 1);
        for (int z = c0.z; z <= c1.z; ++z)
        for (int y = c0.y; y <= c1.y; ++y)
        for (int x = c0.x; x <= c1.x; ++x) {
            glm::vec3 lo = v.origin + glm::vec3(x, y, z) * v.cell;
            glm::vec3 hi = lo + v.cell;
            if (tri_overlaps_voxel(t, lo, hi)) v.set(x, y, z, true);
        }
    }
}
}  // namespace voxel
```
Implement `tri_overlaps_voxel` with the standard triangle/AABB separating-axis test (Akenine-Möller "Fast 3D Triangle-Box Overlap Testing"). A correct, compact implementation: test the 3 box-face axes (AABB of the triangle vs. the box — already pruned by the loop bounds, so cheap), the triangle normal axis, and the 9 edge cross-product axes. If you want to keep Task 3 minimal, a sufficient first cut is: subsample the triangle (barycentric grid, ~N=8 per edge) and mark the voxel each sample falls in. Replace with full SAT only if validation (Task 10) shows gaps. Pick the subsample version first:
```cpp
namespace { bool tri_overlaps_voxel(const Tri&, glm::vec3, glm::vec3) { return false; } }
// ...and instead, in surface_voxelize, replace the inner overlap test with sampling:
```
Sampling variant of `surface_voxelize` (use this one):
```cpp
void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris) {
    const int N = 16;  // samples per edge; dense enough to leave no gaps at grid res
    for (const auto& t : tris) {
        for (int i = 0; i <= N; ++i)
        for (int j = 0; j + i <= N; ++j) {
            float u = float(i) / N, w = float(j) / N;
            glm::vec3 p = t.a + u * (t.b - t.a) + w * (t.c - t.a);
            glm::ivec3 c = to_cell(v, p);
            if (glm::all(glm::greaterThanEqual(c, glm::ivec3(0))) &&
                glm::all(glm::lessThan(c, v.dims)))
                v.set(c.x, c.y, c.z, true);
        }
    }
}
```
Use the sampling variant; drop the SAT stub.

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R SurfaceVoxelize --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel
git commit -m "feat(voxel): triangle surface voxelization (barycentric sampling)"
```

---

### Task 4: Flood-fill solidification

**Files:**
- Modify: `native/src/voxel/include/voxel/voxelize.h`
- Modify: `native/src/voxel/src/voxelize.cc`
- Test: `native/tests/voxel/voxelize_test.cc`

- [ ] **Step 1: Write the failing test**

Append to `voxelize_test.cc`:
```cpp
TEST(Solidify, FillsHollowBoxInterior) {
    voxel::VoxelVolume v;
    v.dims = {6, 6, 6};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(6 * 6 * 6, 0);
    // Hollow shell: mark the outer faces of a 1..4 cube as solid, interior empty.
    for (int z = 1; z <= 4; ++z)
    for (int y = 1; y <= 4; ++y)
    for (int x = 1; x <= 4; ++x) {
        bool shell = (x==1||x==4||y==1||y==4||z==1||z==4);
        if (shell) v.set(x, y, z, true);
    }
    EXPECT_FALSE(v.solid(2, 2, 2));        // interior empty before
    voxel::solidify(v);
    EXPECT_TRUE(v.solid(2, 2, 2));         // interior filled after
    EXPECT_FALSE(v.solid(0, 0, 0));        // exterior still empty
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `solidify` undeclared.

- [ ] **Step 3: Write minimal implementation**

Add to `voxelize.h`:
```cpp
/// Solid-fill the interior: BFS-flood "exterior empty" from all border
/// voxels through empty space; every voxel never reached is marked solid.
/// Robust to small surface leaks (a leak lets the flood bleed inward).
void solidify(VoxelVolume& v);
```

Add to `voxelize.cc`:
```cpp
#include <queue>

namespace voxel {

void solidify(VoxelVolume& v) {
    const glm::ivec3 d = v.dims;
    std::vector<std::uint8_t> exterior(v.occ.size(), 0);
    std::queue<glm::ivec3> q;
    auto push_if_empty = [&](int x, int y, int z) {
        if (x < 0 || y < 0 || z < 0 || x >= d.x || y >= d.y || z >= d.z) return;
        std::size_t i = v.index(x, y, z);
        if (v.occ[i] == 0 && exterior[i] == 0) { exterior[i] = 1; q.push({x, y, z}); }
    };
    // Seed from every border voxel.
    for (int z = 0; z < d.z; ++z)
    for (int y = 0; y < d.y; ++y)
    for (int x = 0; x < d.x; ++x)
        if (x==0||y==0||z==0||x==d.x-1||y==d.y-1||z==d.z-1) push_if_empty(x, y, z);
    // BFS through empty space.
    const int dx[6]={1,-1,0,0,0,0}, dy[6]={0,0,1,-1,0,0}, dz[6]={0,0,0,0,1,-1};
    while (!q.empty()) {
        glm::ivec3 c = q.front(); q.pop();
        for (int k = 0; k < 6; ++k) push_if_empty(c.x+dx[k], c.y+dy[k], c.z+dz[k]);
    }
    // Anything not reached and not already solid surface = interior solid.
    for (std::size_t i = 0; i < v.occ.size(); ++i)
        if (exterior[i] == 0) v.occ[i] = 1;
}

}  // namespace voxel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R Solidify --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel
git commit -m "feat(voxel): flood-fill interior solidification"
```

---

### Task 5: `voxelize()` orchestrator (bbox → grid)

**Files:**
- Modify: `native/src/voxel/include/voxel/voxelize.h`
- Modify: `native/src/voxel/src/voxelize.cc`
- Test: `native/tests/voxel/voxelize_test.cc`

The resolution rule is *provisional* here (caller passes target dims); Task 10 replaces the dims source with BC's recovered rule. This task just wires bbox → origin/cell → surface → solidify.

- [ ] **Step 1: Write the failing test**

Append to `voxelize_test.cc`:
```cpp
TEST(Voxelize, SolidCubeModelIsMostlySolid) {
    // Axis-aligned solid cube hull from x,y,z in [0,4], 12 triangles.
    assets::Model m;
    assets::Node n; n.parent_index = -1; n.meshes = {0};
    m.nodes = {n}; m.root_node = 0;
    assets::Mesh mesh;
    glm::vec3 c[8] = {{0,0,0},{4,0,0},{4,4,0},{0,4,0},{0,0,4},{4,0,4},{4,4,4},{0,4,4}};
    for (auto& p : c) mesh.vertices.push_back(p);
    // 12 triangles (two per face).
    int f[12][3] = {{0,1,2},{0,2,3},{4,6,5},{4,7,6},{0,4,5},{0,5,1},
                    {1,5,6},{1,6,2},{2,6,7},{2,7,3},{3,7,4},{3,4,0}};
    for (auto& t : f) { mesh.indices.push_back(t[0]); mesh.indices.push_back(t[1]); mesh.indices.push_back(t[2]); }
    m.meshes = {mesh};

    voxel::VoxelVolume v = voxel::voxelize(m, glm::ivec3(16, 16, 16));
    // A solid 4x4x4 box in a 16^3 grid sized to a small margin should fill
    // a large, contiguous central region.
    EXPECT_GT(v.solid_count(), 100u);
    glm::ivec3 mid = v.dims / 2;
    EXPECT_TRUE(v.solid(mid.x, mid.y, mid.z));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `voxelize` undeclared.

- [ ] **Step 3: Write minimal implementation**

Add to `voxelize.h`:
```cpp
/// Voxelize a hull into a solid volume at the given grid resolution.
/// Computes a tight body-frame AABB (with a 1-voxel margin), surface-
/// rasterizes the triangle soup, then flood-fill solidifies.
VoxelVolume voxelize(const assets::Model& model, glm::ivec3 dims);
```

Add to `voxelize.cc`:
```cpp
namespace voxel {

VoxelVolume voxelize(const assets::Model& model, glm::ivec3 dims) {
    auto tris = collect_hull_triangles(model);
    glm::vec3 mn(1e30f), mx(-1e30f);
    for (const auto& t : tris) {
        mn = glm::min(mn, glm::min(t.a, glm::min(t.b, t.c)));
        mx = glm::max(mx, glm::max(t.a, glm::max(t.b, t.c)));
    }
    VoxelVolume v;
    v.dims = dims;
    glm::vec3 extent = mx - mn;
    v.cell = extent / glm::vec3(dims - 2);        // 1-voxel margin each side
    v.origin = mn - v.cell;                        // shift so margin voxels are empty
    v.occ.assign(std::size_t(dims.x) * dims.y * dims.z, 0);
    surface_voxelize(v, tris);
    solidify(v);
    return v;
}

}  // namespace voxel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R Voxelize --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel
git commit -m "feat(voxel): voxelize() orchestrator (bbox -> surface -> solidify)"
```

---

## Phase B — Decode (reverse-engineering)

> Re-read these tasks' findings doc (`docs/original_game_reference/engine/nif-voxel-format.md`, created in Task 6) before implementing Tasks 7–8. The exact byte offsets / packing are recovered in Task 6 and referenced — not guessed — in 7–8.

### Task 6: Capture fixture + decode investigation (the format gate)

**Files:**
- Create: `native/tools/voxel_inspect/main.cc`
- Create: `native/tools/voxel_inspect/CMakeLists.txt` (+ register in `native/tools/CMakeLists.txt`)
- Create: `docs/original_game_reference/engine/nif-voxel-format.md` (findings)

This task is **investigation**, not TDD. It produces (a) a tool that prints candidate parses of a `*_vox.nif`, and (b) a written format spec. Success = a documented layout whose decoded dims/bounds are plausible against the Galaxy hull AABB.

- [ ] **Step 1: Build the inspect tool**

`native/tools/voxel_inspect/main.cc` — load a NIF, find the `NiBinaryVoxelData` block, and print: the current parsed header fields (`unknown_short1..3`, `unknown_7_floats`), the `raw_voxel_payload` length, the first/last 64 payload bytes as hex, and the payload byte histogram (helps spot RLE run markers vs. bit-packing). Reuse `nif::load` and the existing block structs.
```cpp
// Pseudostructure — fill with real nif API:
// auto file = nif::load(argv[1]);
// for each block: if holds NiBinaryVoxelData -> print shorts, floats,
//   payload.size(), hex dump head/tail, byte histogram.
```

- [ ] **Step 2: Run it on three ships and a base**

Run:
```bash
cmake --build build -j voxel_inspect
./build/.../voxel_inspect game/data/Models/Ships/Galaxy/Galaxy_vox.nif
./build/.../voxel_inspect game/data/Models/Ships/Sovereign/Sovereign_vox.nif
./build/.../voxel_inspect game/data/Models/Ships/Shuttle/Shuttle_vox.nif
./build/.../voxel_inspect game/data/Models/Bases/DryDock/DryDock_vox.nif
```
Expected: header shorts and floats printed; payload length printed.

- [ ] **Step 3: Solve the layout**

Determine, by inspection across the four files:
1. Do the 3 shorts equal a plausible `(nx, ny, nz)`? Cross-check: `nx*ny*nz` bits (÷8) ≈ payload length → **bit-packed**, no RLE. If payload is much smaller → **RLE**; inspect for run-length structure in the histogram/hex.
2. What do the 7 floats encode? Compare against the hull's body-frame AABB (load `Galaxy.nif` via `assets::build_model`, compute AABB). Expect origin (3) + cell-size (3) + 1 spare, or min(3)+max(3)+1. Identify which.
3. Axis/origin/bit order (x-fastest?) — note as a hypothesis to confirm in Task 8 via the point-dump.

- [ ] **Step 4: Write the findings doc**

Write `docs/original_game_reference/engine/nif-voxel-format.md` with: exact field meanings of the 3 shorts + 7 floats, the payload encoding (bit-packed vs RLE) with the precise unpacking procedure, the index/bit order, and the Galaxy's decoded dims/bounds vs. its mesh AABB. This doc is the contract Tasks 7–8 implement.

- [ ] **Step 5: Commit**

```bash
git add native/tools/voxel_inspect native/tools/CMakeLists.txt docs/original_game_reference/engine/nif-voxel-format.md
git commit -m "feat(voxel): vox-format inspect tool + recovered format spec"
```

---

### Task 7: Structured header parse in the NIF decoder

**Files:**
- Modify: `native/src/nif/include/nif/block.h` (rename voxel header fields per findings)
- Modify: `native/src/nif/src/blocks/extra_data.cc`
- Test: `native/tests/nif/` — add `voxel_data_test.cc` to the `nif_tests` source list in `native/tests/CMakeLists.txt`

Use the field meanings recovered in Task 6. Below, `dim_x/dim_y/dim_z` and the `bounds` interpretation are the **recovered** names; rename to match the findings doc.

- [ ] **Step 1: Write the failing test**

`native/tests/nif/voxel_data_test.cc` (uses the existing `sample_paths.h` / `OPEN_STBC_PROJECT_ROOT` pattern):
```cpp
#include <gtest/gtest.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>

TEST(VoxelDataHeader, GalaxyDimsAndBoundsAreRecovered) {
    std::filesystem::path p =
        std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "BC asset absent: " << p;
    auto f = nif::load(p);
    const nif::NiBinaryVoxelData* vd = nullptr;
    for (const auto& b : f.blocks)
        if (auto* p2 = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = p2;
    ASSERT_NE(vd, nullptr);
    // Replace the literal expectations with the values recorded in the
    // findings doc from Task 6 (Galaxy's actual decoded dims).
    EXPECT_GT(vd->dim_x, 0);
    EXPECT_GT(vd->dim_y, 0);
    EXPECT_GT(vd->dim_z, 0);
    EXPECT_EQ(vd->raw_voxel_payload.size() > 0 || vd->occupancy_bits.size() > 0, true);
}
```
After Task 6, tighten the `EXPECT_GT`s to `EXPECT_EQ`s against the recorded Galaxy dims.

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j nif_tests`
Expected: FAIL to compile — `dim_x` not a member (still named `unknown_short1`).

- [ ] **Step 3: Rename fields + parse them**

In `block.h`, rename `unknown_short1/2/3` → `dim_x/dim_y/dim_z` and `unknown_7_floats` → a named `bounds` struct per the findings. In `extra_data.cc`'s `parse_NiBinaryVoxelData_body`, keep reading the same byte positions but into the renamed fields (no behavior change yet — still capture the payload into `raw_voxel_payload`). Update any other references to the old field names (`grep -rn unknown_short native/`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j nif_tests && ctest --test-dir build -R VoxelDataHeader --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/nif native/tests/nif/voxel_data_test.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): name NiBinaryVoxelData dims+bounds per recovered format"
```

---

### Task 8: Decode payload → `VoxelVolume`

**Files:**
- Modify: `native/src/voxel/src/decode.cc`
- Modify: `native/src/voxel/include/voxel/voxelize.h` (declare `from_nif_voxel_data`)
- Test: `native/tests/voxel/decode_test.cc`

Implement the unpacking procedure recorded in the findings doc (bit-packed or RLE).

- [ ] **Step 1: Write the failing test**

`native/tests/voxel/decode_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <voxel/voxelize.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>

TEST(DecodeVoxNif, GalaxyDecodesToPlausibleSolidVolume) {
    std::filesystem::path p =
        std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "BC asset absent: " << p;
    auto f = nif::load(p);
    const nif::NiBinaryVoxelData* vd = nullptr;
    for (const auto& b : f.blocks)
        if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
    ASSERT_NE(vd, nullptr);

    voxel::VoxelVolume v = voxel::from_nif_voxel_data(*vd);
    EXPECT_EQ(v.occ.size(), std::size_t(v.dims.x) * v.dims.y * v.dims.z);
    // A ship hull fills a meaningful but minority fraction of its bbox.
    double frac = double(v.solid_count()) / double(v.occ.size());
    EXPECT_GT(frac, 0.02);
    EXPECT_LT(frac, 0.90);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `from_nif_voxel_data` undeclared.

- [ ] **Step 3: Implement decode per findings**

Declare in `voxelize.h`:
```cpp
namespace nif { struct NiBinaryVoxelData; }
namespace voxel {
/// Decode a parsed NiBinaryVoxelData block into a VoxelVolume, following the
/// layout in docs/original_game_reference/engine/nif-voxel-format.md.
VoxelVolume from_nif_voxel_data(const nif::NiBinaryVoxelData& vd);
}
```
Implement in `decode.cc`: set `dims` from `dim_x/y/z`, set `origin`/`cell` from the `bounds` interpretation, then unpack the payload into `occ` using the exact procedure from the findings doc (bit-packed: iterate bits in the recorded order; RLE: expand runs). Confirm bit/axis order by dumping points (Task 9) and eyeballing against the hull.

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R DecodeVoxNif --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel
git commit -m "feat(voxel): decode NiBinaryVoxelData payload into VoxelVolume"
```

---

## Phase C — Validation + viz

### Task 9: Debug point-dump

**Files:**
- Modify: `native/tools/voxel_inspect/main.cc` (add `--dump-obj <out.obj>` mode)

- [ ] **Step 1: Add an OBJ point/cube dump**

Extend `voxel_inspect` so that given a `*_vox.nif` (decode path) *or* a hull `*.nif` (`assets::build_model` → `voxelize`), it writes one OBJ vertex (or a tiny cube) per solid voxel at its body-frame center (`origin + (x+0.5,y+0.5,z+0.5)*cell`). This is the eyeball test for bit/axis order and for the voxelizer.

- [ ] **Step 2: Dump decode vs. voxelize for the Galaxy**

Run:
```bash
cmake --build build -j voxel_inspect
./build/.../voxel_inspect --dump-obj /tmp/galaxy_decoded.obj game/data/Models/Ships/Galaxy/Galaxy_vox.nif
./build/.../voxel_inspect --dump-obj /tmp/galaxy_voxelized.obj --from-hull game/data/Models/Ships/Galaxy/Galaxy.nif
```
Expected: two OBJ files written. Open both in a mesh viewer; the decoded cloud must look like the Galaxy, and the two clouds must roughly coincide. Fix bit/axis order in `decode.cc` if the decoded cloud is transposed/mirrored.

- [ ] **Step 3: Commit**

```bash
git add native/tools/voxel_inspect
git commit -m "feat(voxel): OBJ point-dump for decode/voxelize eyeballing"
```

---

### Task 10: IoU validation + recover the resolution rule (the gate)

**Files:**
- Modify: `native/src/voxel/include/voxel/voxelize.h` (declare `iou`, `voxelize_matching`)
- Modify: `native/src/voxel/src/volume.cc` (`iou`)
- Modify: `native/src/voxel/src/voxelize.cc` (`voxelize_matching` — uses BC's recovered dims rule)
- Test: `native/tests/voxel/decode_test.cc` (the integration gate)

- [ ] **Step 1: Write the failing test**

Append to `decode_test.cc`:
```cpp
TEST(VoxelValidation, GalaxyVoxelizeMatchesDecodeIoU) {
    namespace fs = std::filesystem;
    fs::path vox = fs::path(OPEN_STBC_PROJECT_ROOT) / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    fs::path hull = fs::path(OPEN_STBC_PROJECT_ROOT) / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!fs::exists(vox) || !fs::exists(hull)) GTEST_SKIP() << "BC asset absent";

    voxel::VoxelVolume decoded = /* load vox + from_nif_voxel_data (as in DecodeVoxNif) */;
    voxel::VoxelVolume ours    = voxel::voxelize_matching(hull, decoded);  // same dims/bounds
    double iou = voxel::iou(decoded, ours);
    EXPECT_GT(iou, 0.85);   // tighten as the voxelizer is tuned
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j voxel_tests`
Expected: FAIL to compile — `iou` / `voxelize_matching` undeclared.

- [ ] **Step 3: Implement IoU + dims-matched voxelize**

`iou` in `volume.cc` (requires equal dims; assert): intersection / union over the solid sets.
```cpp
double iou(const VoxelVolume& a, const VoxelVolume& b) {
    // assert a.dims == b.dims
    std::size_t inter = 0, uni = 0;
    for (std::size_t i = 0; i < a.occ.size(); ++i) {
        bool x = a.occ[i] != 0, y = b.occ[i] != 0;
        inter += (x && y); uni += (x || y);
    }
    return uni ? double(inter) / double(uni) : 1.0;
}
```
`voxelize_matching(hull_path, ref)`: load hull via `assets::build_model`, then voxelize into a volume that uses `ref.dims/origin/cell` exactly (so IoU is well-defined). This also confirms whether BC's per-ship resolution rule (from the findings) reproduces `ref.dims` when derived from the hull AABB — record that rule in the findings doc.

- [ ] **Step 4: Run, then tune to pass**

Run: `cmake --build build -j voxel_tests && ctest --test-dir build -R VoxelValidation --output-on-failure`
Expected: initially may be below threshold. Tune surface sampling density, solidify leak handling, and origin/cell alignment until IoU > 0.85. Each tuning change: re-run, inspect the OBJ dumps for where they disagree.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel native/tests/voxel/decode_test.cc
git commit -m "feat(voxel): IoU validation gate — voxelize matches decode on Galaxy"
```

---

## Self-Review

**Spec coverage:**
- VoxelVolume type → Task 1. ✓
- Decoder → Tasks 6–8. ✓
- Voxelizer (gather tris, surface, flood-fill solidify) → Tasks 2–5. ✓
- BC-matched resolution → Task 10 (recovered rule) + Task 6 findings. ✓
- Validation IoU gate → Task 10. ✓
- Debug viz + binding → Task 9 (OBJ dump; Python binding deferred — the OBJ dump satisfies the eyeball need without the `host_bindings.cc`→`dauntless` rebuild cost; add a binding later only if the renderer spec needs runtime access).
- Testing strategy (decoder fixture, voxelizer determinism, cube fill, Galaxy IoU) → Tasks 1–5, 7–8, 10. ✓
- Non-goals (encode, SDF) → correctly absent. ✓
- Visual target reference → documentation only, no foundation task (correct; renderer spec). ✓

**Placeholder scan:** The RE tasks (6–8) intentionally reference values "recovered in Task 6 / recorded in the findings doc" — this is a real dependency, not a lazy placeholder; Task 6 produces the concrete contract. Confirm `assets::Mesh` field names in Task 2 before coding (flagged inline).

**Type consistency:** `VoxelVolume` (`dims`/`origin`/`cell`/`occ`, `index`/`solid`/`set`/`solid_count`) is consistent across Tasks 1–10. `Tri`, `collect_hull_triangles`, `surface_voxelize`, `solidify`, `voxelize`, `from_nif_voxel_data`, `iou`, `voxelize_matching` signatures are consistent across declaration and use.
