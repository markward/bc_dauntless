# Hull Damage Tessellation — Plan 3: Crushability Bake

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CPU "thickness bake" that computes a per-vertex **crushability** weight ∈ [0,1] (thin hull → 1, thick hull → 0) by casting a ray inward from each vertex and measuring the distance to the opposite surface, plus the `MeshCpu::Vertex.crushability` field to hold it.

**Architecture:** A standalone, pure-CPU module in the `assets` library (`crushability_bake`). For each mesh vertex, cast a ray along `−normal` against that mesh's own triangles (a Möller–Trumbore helper local to the module — a deliberate mirror of `renderer::intersect_triangle`, kept local to avoid an `assets→renderer` circular dependency), take the nearest forward hit distance as the local hull thickness, and map it to crushability relative to the mesh's bounding-box diagonal. No GL, no model-load wiring, no GPU upload — those land in Plan 4 where the shader consumes the attribute.

**Tech Stack:** C++20, GLM, GoogleTest (`assets_tests` CPU suite — no GL context needed).

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Architecture.2 (offline thickness bake → crushability), §8 (bake-failure / no-hit fallback → mid value).

**Branch:** create `feat/hull-damage-crushability` off `main` (Plans 1 & 2 are merged to `main`).

---

## Key facts for the implementer (you have zero context — read these)

- This is the bc_dauntless project, an open C++ reimplementation of Star Trek: Bridge Commander. ONE build tree at the project root. Always: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **`MeshCpu`** (`native/src/assets/include/assets/mesh.h`) holds CPU-side mesh data: a `std::vector<Vertex> vertices` (each with `position`, `normal`, `uv`, `color`, `bone_indices`, `bone_weights`, `uv1`) and a flat `std::vector<std::uint32_t> indices` (3 per triangle). Positions and normals are in the mesh's own local frame (shape transform already baked in at build time).
- **The bake operates PER MESH**, casting each mesh's vertices against that same mesh's triangles, in the mesh's stored local frame. This is a deliberate approximation: a thin extremity (bow tip, saucer rim) is typically a single `NiTriShape`, and a cross-mesh "thickness" would be large anyway (→ low crushability), so per-mesh is both adequate and far cheaper than a whole-model O(V_total × T_total) cast. Note this in the module's header comment.
- **Möller–Trumbore reference:** the proven implementation is `renderer::intersect_triangle` in `native/src/renderer/ray_trace.cc` — double-sided (no backface cull), with `kDetEps = 1e-7` (parallel/degenerate reject) and `kTMin = 1e-5` (self-hit guard at the origin). The bake's local helper mirrors it exactly. The `kTMin` guard is what stops a vertex from self-hitting the triangles that share it (they intersect at t≈0).
- **Dependency rule:** the `assets` library links `nif glm glad stb_image` and must NOT depend on `renderer` (renderer depends on assets). So the bake CANNOT `#include <renderer/ray_trace.h>`. Carry a local triangle-intersect helper instead. (De-duplicating the two into a shared geometry lib is out of scope — a future cleanup.)
- **Tests:** the `assets_tests` target has a CPU suite under `native/tests/assets/cpu/` that runs with no GL context. Register new CPU test files in the `add_executable(assets_tests ...)` list in `native/tests/assets/CMakeLists.txt`. CPU tests can `#include <assets/...>` (public headers) and build synthetic `MeshCpu` objects directly.
- **Adding a `Vertex` field:** append it LAST (after `uv1`) so existing positional/aggregate initializations of `Vertex` are unaffected. The GPU upload (`mesh_upload.cc`) uses `sizeof(Vertex)` as stride and `offsetof` per attribute, so an appended field does not disturb existing vertex attributes — and Plan 3 does not add a new GPU attribute (Plan 4 does).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/assets/include/assets/mesh.h` | Add `float crushability` to `MeshCpu::Vertex` | Modify |
| `native/src/assets/include/assets/crushability_bake.h` | Public API: `CrushabilityParams`, `crushability_from_thickness`, `probe_thickness`, `bake_crushability` | Create |
| `native/src/assets/src/crushability_bake.cc` | Implementation + local Möller–Trumbore helper | Create |
| `native/src/assets/CMakeLists.txt` | Add `src/crushability_bake.cc` to the `assets` library | Modify |
| `native/tests/assets/cpu/crushability_bake_test.cc` | CPU unit tests (mapping, probe, bake) | Create |
| `native/tests/assets/CMakeLists.txt` | Register the test file | Modify |

---

## Task 1: Add the `crushability` vertex field

**Files:**
- Modify: `native/src/assets/include/assets/mesh.h`

- [ ] **Step 1: Add the field**

In `native/src/assets/include/assets/mesh.h`, inside `struct MeshCpu::Vertex`, append a new field as the LAST member (directly after `glm::vec2 uv1{};`):

```cpp
        /// Per-vertex hull "crushability" weight in [0,1] for hull-damage
        /// deformation: 1 = thin/easily-crushed (bow tip, saucer rim),
        /// 0 = thick/resists. Default 0.5 (the bake-absent / no-hit fallback,
        /// spec §8); assets::bake_crushability() overwrites it with the
        /// thickness-derived value. Plan 4 uploads it as a vertex attribute
        /// and the tessellation shaders read it.
        float       crushability = 0.5f;
```

- [ ] **Step 2: Build to confirm nothing breaks**

Run: `cmake -B build -S . && cmake --build build -j --target assets`
Expected: compiles cleanly (appended trailing field with a default; existing `Vertex` initializations are unaffected).

- [ ] **Step 3: Run the existing assets tests to confirm no regression**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "MeshBuild|ModelBuild|MeshUpload|RigidBake|ModelCompose" --output-on-failure`
Expected: all PASS (the field addition must not disturb mesh build/upload/compose).

- [ ] **Step 4: Commit**

```bash
git add native/src/assets/include/assets/mesh.h
git commit -m "feat(assets): add crushability weight field to MeshCpu::Vertex"
```

---

## Task 2: Crushability mapping + module scaffold

Create the `crushability_bake` module with the pure thickness→weight mapping and the params struct, wired into the build and tests.

**Files:**
- Create: `native/src/assets/include/assets/crushability_bake.h`
- Create: `native/src/assets/src/crushability_bake.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Test: `native/tests/assets/cpu/crushability_bake_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/assets/cpu/crushability_bake_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <cmath>
#include <assets/crushability_bake.h>

using assets::crushability_from_thickness;

TEST(CrushabilityMapping, ThinIsHighThickIsLow) {
    // ref = 4.0: thickness 0 -> 1, thickness >= ref -> 0, linear between.
    EXPECT_FLOAT_EQ(crushability_from_thickness(0.0f, 4.0f), 1.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(4.0f, 4.0f), 0.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 4.0f), 0.75f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(2.0f, 4.0f), 0.5f);
}

TEST(CrushabilityMapping, ClampsAndHandlesDegenerateRef) {
    EXPECT_FLOAT_EQ(crushability_from_thickness(10.0f, 4.0f), 0.0f);  // beyond ref -> clamp 0
    EXPECT_FLOAT_EQ(crushability_from_thickness(-1.0f, 4.0f), 1.0f);  // negative -> clamp 1
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 0.0f), 0.0f);   // ref<=0 -> 0 (uncrushable)
}
```

Register it: add `cpu/crushability_bake_test.cc` to the `add_executable(assets_tests ...)` list in `native/tests/assets/CMakeLists.txt` (after `cpu/flip_frame_test.cc`).

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target assets_tests`
Expected: FAIL to compile — `assets/crushability_bake.h` not found.

- [ ] **Step 3: Create the header**

Create `native/src/assets/include/assets/crushability_bake.h`:

```cpp
// native/src/assets/include/assets/crushability_bake.h
#pragma once

#include <glm/glm.hpp>

#include <assets/mesh.h>

namespace assets {

/// Tuning for the hull-thickness crushability bake. Defaults are starting
/// points; tuned in Plan 4 against visual results.
struct CrushabilityParams {
    /// Reference thickness as a fraction of the mesh's bounding-box diagonal.
    /// A vertex whose inward hull thickness is <= thick_fraction*diag maps
    /// toward 1 (crushable); >= it maps to 0. Scale-invariant per mesh.
    float thick_fraction = 0.25f;
    /// Crushability assigned when the inward ray finds no opposite surface
    /// (open shell / grazing edge). Mid value per spec §8.
    float no_hit_value = 0.5f;
};

/// Map a hull thickness to a crushability weight in [0,1]: 0 thickness -> 1,
/// thickness >= ref -> 0, linear between. ref <= 0 returns 0 (uncrushable).
float crushability_from_thickness(float thickness, float ref);

/// Nearest forward intersection distance of the ray (origin, dir) against the
/// mesh's own triangles, searching (kTMin, max_dist]. Returns
/// +infinity if the ray hits nothing. `dir` should be unit length.
float probe_thickness(const MeshCpu& mesh, const glm::vec3& origin,
                      const glm::vec3& dir, float max_dist);

/// Bake per-vertex crushability into `mesh.vertices[*].crushability` by casting
/// each vertex's inward (-normal) ray against the mesh's own triangles and
/// mapping the nearest-hit distance (local hull thickness) to [0,1]. Vertices
/// with a zero-length normal, or whose inward ray hits nothing, get
/// params.no_hit_value. A mesh with no triangles is left unchanged.
///
/// Per-mesh approximation (see header note in the .cc): thickness is measured
/// against the vertex's own NiTriShape, not the whole ship.
void bake_crushability(MeshCpu& mesh, const CrushabilityParams& params = {});

}  // namespace assets
```

- [ ] **Step 4: Create the implementation (mapping only for now)**

Create `native/src/assets/src/crushability_bake.cc`:

```cpp
// native/src/assets/src/crushability_bake.cc
//
// Per-vertex hull "crushability" bake for hull-damage deformation (spec §2).
// PER-MESH approximation: each vertex's inward ray is cast against the vertex's
// own NiTriShape triangles, not the whole ship. Thin single-shape extremities
// (bow tip, saucer rim) crush; thick hull resists. Cross-mesh thickness would
// be large anyway (-> low crushability), so per-mesh is adequate and far
// cheaper than a whole-model cast.
#include "assets/crushability_bake.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace assets {

float crushability_from_thickness(float thickness, float ref) {
    if (ref <= 0.0f) return 0.0f;
    return std::clamp(1.0f - thickness / ref, 0.0f, 1.0f);
}

}  // namespace assets
```

- [ ] **Step 5: Add the source to the assets library**

In `native/src/assets/CMakeLists.txt`, add `src/crushability_bake.cc` to the `add_library(assets STATIC ...)` source list (after `src/cache.cc`, alphabetical-ish).

- [ ] **Step 6: Build and run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j --target assets_tests && ctest --test-dir build -R CrushabilityMapping --output-on-failure`
Expected: both mapping tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/assets/include/assets/crushability_bake.h \
        native/src/assets/src/crushability_bake.cc \
        native/src/assets/CMakeLists.txt \
        native/tests/assets/cpu/crushability_bake_test.cc \
        native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): add crushability_bake module + thickness->weight mapping"
```

---

## Task 3: Local triangle-intersect helper + `probe_thickness`

**Files:**
- Modify: `native/src/assets/src/crushability_bake.cc`
- Test: `native/tests/assets/cpu/crushability_bake_test.cc` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/assets/cpu/crushability_bake_test.cc`:

```cpp
#include <assets/mesh.h>
#include <limits>

namespace {
// Two facing quads: a small top quad at z=0 (x,y in [0,10]) and a larger
// bottom quad at z=-1 (x,y in [-5,15]). The bottom overhangs the top so a
// ray straight down from any top point lands in the bottom's interior
// (avoids fragile edge/corner hits).
assets::MeshCpu make_facing_quads() {
    assets::MeshCpu m;
    auto v = [](float x, float y, float z, glm::vec3 n) {
        assets::MeshCpu::Vertex vert;
        vert.position = {x, y, z};
        vert.normal = n;
        return vert;
    };
    const glm::vec3 up{0, 0, 1}, down{0, 0, -1};
    // 0..3 top quad (normal +z), 4..7 bottom quad (normal -z)
    m.vertices = {
        v(0, 0, 0, up),  v(10, 0, 0, up),  v(10, 10, 0, up),  v(0, 10, 0, up),
        v(-5, -5, -1, down), v(15, -5, -1, down),
        v(15, 15, -1, down), v(-5, 15, -1, down),
    };
    m.indices = {
        0, 1, 2,  0, 2, 3,        // top
        4, 5, 6,  4, 6, 7,        // bottom
    };
    return m;
}
}  // namespace

TEST(ProbeThickness, HitsOppositeSurface) {
    const assets::MeshCpu m = make_facing_quads();
    // From the centre of the top quad, straight down, must hit the bottom at t=1.
    const float t = assets::probe_thickness(m, {5, 5, 0}, {0, 0, -1}, 100.0f);
    EXPECT_NEAR(t, 1.0f, 1e-4f);
}

TEST(ProbeThickness, MissReturnsInfinity) {
    const assets::MeshCpu m = make_facing_quads();
    // From the top quad centre, straight UP (away from all geometry): no hit.
    const float t = assets::probe_thickness(m, {5, 5, 0}, {0, 0, 1}, 100.0f);
    EXPECT_TRUE(std::isinf(t));
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target assets_tests`
Expected: FAIL to compile — `probe_thickness` is declared but not defined (link error) — or, if the linker is lenient, a test run failure. Either way, not passing.

- [ ] **Step 3: Implement the helper and `probe_thickness`**

In `native/src/assets/src/crushability_bake.cc`, add an anonymous-namespace Möller–Trumbore helper (a local mirror of `renderer::intersect_triangle` — see header note; kept local to avoid an assets→renderer dependency), then `probe_thickness`. Insert both AFTER `crushability_from_thickness` and before the closing `}  // namespace assets`:

```cpp
namespace {

// Local mirror of renderer::intersect_triangle (native/src/renderer/ray_trace.cc):
// Möller-Trumbore, double-sided, kDetEps parallel reject, kTMin self-hit guard.
// Duplicated (not shared) to keep the assets library free of a renderer
// dependency; de-duplication into a shared geometry lib is a future cleanup.
std::optional<float> ray_triangle_t(
    const glm::vec3& origin, const glm::vec3& dir, float max_dist,
    const glm::vec3& v0, const glm::vec3& v1, const glm::vec3& v2) {
    constexpr float kDetEps = 1e-7f;
    constexpr float kTMin   = 1e-5f;
    const glm::vec3 e1 = v1 - v0;
    const glm::vec3 e2 = v2 - v0;
    const glm::vec3 p  = glm::cross(dir, e2);
    const float det = glm::dot(e1, p);
    if (std::abs(det) < kDetEps) return std::nullopt;
    const float inv_det = 1.0f / det;
    const glm::vec3 s = origin - v0;
    const float u = glm::dot(s, p) * inv_det;
    if (u < 0.0f || u > 1.0f) return std::nullopt;
    const glm::vec3 q = glm::cross(s, e1);
    const float v = glm::dot(dir, q) * inv_det;
    if (v < 0.0f || u + v > 1.0f) return std::nullopt;
    const float t = glm::dot(e2, q) * inv_det;
    if (t < kTMin || t > max_dist) return std::nullopt;
    return t;
}

}  // namespace

float probe_thickness(const MeshCpu& mesh, const glm::vec3& origin,
                      const glm::vec3& dir, float max_dist) {
    float best = std::numeric_limits<float>::infinity();
    for (std::size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const glm::vec3& v0 = mesh.vertices[mesh.indices[i + 0]].position;
        const glm::vec3& v1 = mesh.vertices[mesh.indices[i + 1]].position;
        const glm::vec3& v2 = mesh.vertices[mesh.indices[i + 2]].position;
        const std::optional<float> t = ray_triangle_t(origin, dir, max_dist, v0, v1, v2);
        if (t && *t < best) best = *t;
    }
    return best;
}
```

Add `#include <optional>` to the `.cc`'s include block (alongside `<algorithm>`, `<cmath>`, `<limits>`).

- [ ] **Step 4: Run to verify they pass**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "ProbeThickness|CrushabilityMapping" --output-on-failure`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/crushability_bake.cc native/tests/assets/cpu/crushability_bake_test.cc
git commit -m "feat(assets): add ray-triangle probe_thickness for the crushability bake"
```

---

## Task 4: `bake_crushability` — the per-vertex bake

**Files:**
- Modify: `native/src/assets/src/crushability_bake.cc`
- Test: `native/tests/assets/cpu/crushability_bake_test.cc` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/assets/cpu/crushability_bake_test.cc`:

```cpp
TEST(BakeCrushability, ThinFaceCrushesMoreThanNoHitEdge) {
    assets::MeshCpu m = make_facing_quads();
    assets::bake_crushability(m);  // default params

    // Top-quad vertices (normal +z) cast down, hit the overhanging bottom at
    // thickness 1 (thin) -> crushability well above the 0.5 fallback.
    for (std::size_t i = 0; i < 4; ++i) {
        EXPECT_GT(m.vertices[i].crushability, 0.5f)
            << "top vertex " << i << " should read as thin/crushable";
    }
    // Bottom-quad corners (normal -z) cast up but the smaller top quad does not
    // cover them, so the ray misses -> no_hit_value (0.5).
    for (std::size_t i = 4; i < 8; ++i) {
        EXPECT_FLOAT_EQ(m.vertices[i].crushability, 0.5f)
            << "bottom corner " << i << " should fall back to no_hit_value";
    }
}

TEST(BakeCrushability, ZeroNormalGetsNoHitValue) {
    assets::MeshCpu m = make_facing_quads();
    m.vertices[0].normal = {0, 0, 0};  // degenerate normal
    assets::bake_crushability(m);
    EXPECT_FLOAT_EQ(m.vertices[0].crushability, 0.5f);
}

TEST(BakeCrushability, EmptyMeshIsLeftUnchanged) {
    assets::MeshCpu m;  // no vertices, no indices
    assets::bake_crushability(m);  // must not crash
    EXPECT_TRUE(m.vertices.empty());
}

TEST(BakeCrushability, RespectsCustomNoHitValue) {
    assets::MeshCpu m = make_facing_quads();
    assets::CrushabilityParams p;
    p.no_hit_value = 0.1f;
    assets::bake_crushability(m, p);
    EXPECT_FLOAT_EQ(m.vertices[4].crushability, 0.1f);  // a missing bottom corner
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target assets_tests`
Expected: FAIL to compile/link — `bake_crushability` not defined.

- [ ] **Step 3: Implement `bake_crushability`**

In `native/src/assets/src/crushability_bake.cc`, add after `probe_thickness` (before the closing `}  // namespace assets`):

```cpp
void bake_crushability(MeshCpu& mesh, const CrushabilityParams& params) {
    if (mesh.vertices.empty() || mesh.indices.size() < 3) return;

    // Bounding-box diagonal gives a per-mesh, scale-invariant reference: a
    // vertex is "thin" relative to the size of its own shape.
    glm::vec3 lo(std::numeric_limits<float>::infinity());
    glm::vec3 hi(-std::numeric_limits<float>::infinity());
    for (const auto& vert : mesh.vertices) {
        lo = glm::min(lo, vert.position);
        hi = glm::max(hi, vert.position);
    }
    const float diag = glm::length(hi - lo);
    const float ref = params.thick_fraction * diag;
    const float max_dist = (diag > 0.0f) ? diag : 1.0f;  // no ray exceeds the shape

    for (auto& vert : mesh.vertices) {
        const float nlen = glm::length(vert.normal);
        if (nlen < 1e-8f) {            // degenerate normal -> can't cast inward
            vert.crushability = params.no_hit_value;
            continue;
        }
        const glm::vec3 inward = -vert.normal / nlen;
        const float thickness = probe_thickness(mesh, vert.position, inward, max_dist);
        vert.crushability = std::isinf(thickness)
            ? params.no_hit_value
            : crushability_from_thickness(thickness, ref);
    }
}
```

- [ ] **Step 4: Run to verify all pass**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "BakeCrushability|ProbeThickness|CrushabilityMapping" --output-on-failure`
Expected: all PASS.

- [ ] **Step 5: Run the broader assets suite to confirm no regression**

Run: `ctest --test-dir build -R "assets|Mesh|Model|Crushability|Probe|Bake" --output-on-failure`
Expected: all PASS/SKIPPED (the bake is additive and used by nothing else yet).

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/crushability_bake.cc native/tests/assets/cpu/crushability_bake_test.cc
git commit -m "feat(assets): bake per-vertex crushability from inward hull thickness"
```

---

## Self-Review

**Spec coverage (Plan 3 scope = spec §Architecture.2 thickness bake, §8 no-hit fallback):**
- §2 "cast a ray inward from the vertex along −normal and measure the distance to the next back-facing intersection = local hull thickness" → Task 4 `bake_crushability` (inward = −normal) + Task 3 `probe_thickness`. ✓
- §2 "reuse the Möller–Trumbore tracer" → mirrored locally as `ray_triangle_t` (dependency rationale documented; the spec's "reuse" intent is met without a circular dep). ✓
- §2 "normalize thickness to a weight — thin → 1.0, thick → 0.0" → Task 2 `crushability_from_thickness` + per-mesh bbox-diagonal reference in Task 4. ✓
- §2 "stored as a new per-vertex attribute on `MeshCpu::Vertex`" → Task 1 `float crushability`. ✓
- §8 "if the ray-cast bake fails for a model, default crushability to a mid value" → `no_hit_value = 0.5f`, also the field's default. ✓
- §2 "uploaded as an extra vertex attribute" + "caching: sidecar file" + model-load wiring → **deferred to Plan 4** (where the shader consumes the attribute and the eager-vs-lazy bake decision lives). Explicitly out of Plan 3 scope; noted in the plan header and in "What comes next".

**Placeholder scan:** No TBD/TODO. `thick_fraction = 0.25f` / `no_hit_value = 0.5f` are documented defaults with an explicit "tuned in Plan 4" note — real values, not placeholders. The per-mesh approximation and the helper-duplication are documented design decisions, not gaps.

**Type consistency:** `crushability_from_thickness(float thickness, float ref)`, `probe_thickness(const MeshCpu&, const glm::vec3&, const glm::vec3&, float)`, `bake_crushability(MeshCpu&, const CrushabilityParams&)`, and `CrushabilityParams{ thick_fraction, no_hit_value }` are used identically across the header (Task 2), the impl (Tasks 2–4), and the tests. The `MeshCpu::Vertex.crushability` field (Task 1) is the bake's write target (Task 4) and the test read target. The default `0.5f` is consistent between the field default (Task 1) and `no_hit_value` (Task 2). ✓

---

## What comes next (not this plan)

- **Plan 4 (absorbs the deferred bake plumbing):** the displacement pipeline — add the `crushability` GPU vertex attribute (location 7) in `mesh_upload.cc`; wire `bake_crushability` into the model-load path with a sidecar cache (bake once per model, keyed by model path); adaptive TCS; TES displacement from the crater field, weighted by the barycentrically-interpolated crushability, with normal recompute; crater uniform upload; `frame.cc` patch draw path gated on `query_gl_caps().tessellation_available` and `hull_deform_crater_count > 0`.
- **Plan 5:** dent/gouge fragment shading (triplanar `Damage.tga` + procedural) + Modern VFX config toggles.
- **Plan 6:** eligibility manager + `engine/appc/hull_deformation.py` (GU depth/kind mapping) + `hit_feedback` dispatch hook; also picks up the two Plan 2 deferrals (M1 wrapper-pattern decision, M3 binding-level transform integration test).
