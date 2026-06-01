# Mesh-accurate Hit Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the approximate hit-point computation feeding `engine.appc.combat.apply_hit` with a real mesh-surface point produced by a new C++ ray-vs-triangle binding, consumed by both the torpedo and phaser code paths.

**Architecture:** Three layers, bottom-up. (1) Pure C++ `renderer::ray_trace_instance` performs bounding-sphere reject + per-mesh node-transform chain + Möller–Trumbore triangle test, returns closest hit. (2) Python binding `_dauntless_host.ray_trace_mesh` wraps it, looking up the model + world transform via `scenegraph::InstanceId`. (3) Python `engine.appc.combat._resolve_hit_point` encapsulates the three-tier fallback chain (mesh trace → bounding-sphere entry → caller-supplied legacy point) and is called from `projectiles.update_all` and `host_loop._advance_combat`.

**Tech Stack:** C++20 / glm / pybind11 / GoogleTest for the renderer layer; Python 3 / pytest for the engine + integration tests.

**Spec:** `docs/superpowers/specs/2026-06-01-mesh-accurate-hit-resolution-design.md`.
**Branch:** `feature/mesh-accurate-hit-resolution` (already created).

---

## File map

**New files**

| Path | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/ray_trace.h` | Public types: `RayHit`, `ray_trace_instance`, `intersect_triangle`. |
| `native/src/renderer/ray_trace.cc` | Implementation: triangle test, multi-mesh walk, sphere reject, normal reconstruction. |
| `native/tests/renderer/ray_trace_test.cc` | GoogleTest cases for the pure C++ algorithm against synthetic `assets::Model` fixtures. |
| `tests/integration/test_mesh_ray_trace.py` | Python binding-level tests (real Galaxy NIF + headless host). |
| `tests/integration/test_torpedo_hit_point_on_mesh.py` | Torpedo path produces mesh-surface hit points. |

**Edited files**

| Path | Change |
|---|---|
| `native/src/renderer/CMakeLists.txt` | Add `ray_trace.cc` to the `renderer` library sources. |
| `native/tests/renderer/CMakeLists.txt` | Add `ray_trace_test.cc` to `renderer_tests`. |
| `native/src/host/host_bindings.cc` | Bind `ray_trace_mesh`. |
| `engine/appc/combat.py` | Add `ray_sphere_entry` + `_resolve_hit_point`. |
| `engine/appc/projectiles.py` | `update_all` signature: add `host=None, ship_instances=None`; emit 4-tuples `(torpedo, ship, subsystem, hit_point)`. |
| `engine/host_loop.py` | Pass `host` + `ship_instances` to `update_all`; consume 4-tuple; replace phaser-loop `target_pos` with `_resolve_hit_point`. |
| `tests/unit/test_torpedo_advance.py` | Update tuple-shape assertions from 3-tuple to 4-tuple. |
| `tests/integration/test_phaser_damage_applied_through_apply_hit.py` | Add a test case proving the mesh-trace path lands hits on the hull surface (not at target centre). |

---

## Task 1: C++ ray-vs-triangle algorithm

**Files:**
- Create: `native/src/renderer/include/renderer/ray_trace.h`
- Create: `native/src/renderer/ray_trace.cc`
- Create: `native/tests/renderer/ray_trace_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/tests/renderer/CMakeLists.txt`

Builds the pure C++ algorithm with no scenegraph or host dependencies. All later layers consume this.

- [ ] **Step 1: Add the header declaring `RayHit`, `intersect_triangle`, and `ray_trace_instance`.**

Create `native/src/renderer/include/renderer/ray_trace.h`:

```cpp
// native/src/renderer/include/renderer/ray_trace.h
#pragma once

#include <optional>
#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

struct RayHit {
    glm::vec3 point{0.0f};   // World-space surface point.
    glm::vec3 normal{0.0f};  // Unit, outward-facing relative to incoming ray.
    float     t = 0.0f;      // World-space distance from origin along direction.
};

/// Möller–Trumbore ray-vs-triangle, double-sided (no backface culling).
/// Returns the t-value along `direction` at which the ray intersects the
/// triangle (v0, v1, v2), or std::nullopt if it misses or the intersection
/// is behind the origin / past max_dist. `direction` does not need to be
/// unit length — the returned t is in the same units as |direction|.
std::optional<float> intersect_triangle(
    glm::vec3 origin, glm::vec3 direction, float max_dist,
    glm::vec3 v0, glm::vec3 v1, glm::vec3 v2);

/// Walk every CPU-data mesh in `model`, transformed by
/// `instance_world * node_world`, and return the closest hit along the ray
/// (origin, unit direction, max_dist) — or std::nullopt for no hit.
///
/// Performs a world-space bounding-sphere coarse reject first; ships whose
/// bounding sphere the ray segment misses return std::nullopt immediately.
/// The returned normal is flipped so dot(normal, direction) <= 0.
std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist);

}  // namespace renderer
```

- [ ] **Step 2: Add `ray_trace.cc` to the renderer library.**

Edit `native/src/renderer/CMakeLists.txt` — find the `add_library(renderer STATIC` block and add `ray_trace.cc` alongside `aabb.cc`:

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
    dust_pass.cc
    aabb.cc
    ray_trace.cc
    shield_state.cc
    skin_shield.cc
    shield_pass.cc
    lens_flare_pass.cc
    torpedo_pass.cc
    hit_vfx_pass.cc
    phaser_pass.cc
    bridge_pass.cc
)
```

- [ ] **Step 3: Add `ray_trace_test.cc` to the renderer_tests target.**

Edit `native/tests/renderer/CMakeLists.txt` — find `add_executable(renderer_tests` and add `ray_trace_test.cc`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    lighting_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
    dust_pass_test.cc
    aabb_test.cc
    ray_trace_test.cc
    shield_state_test.cc
    skin_shield_test.cc
    lens_flare_pass_test.cc
    bridge_pass_test.cc
)
```

- [ ] **Step 4: Write failing gtest cases for `intersect_triangle`.**

Create `native/tests/renderer/ray_trace_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "renderer/ray_trace.h"
#include "assets/model.h"

// ── intersect_triangle ──────────────────────────────────────────────────────

TEST(IntersectTriangle, HitsCenterOfXyTriangleAtKnownT) {
    // Triangle in z=0 plane, ray along +z from (0,0,-5) hits centroid at t=5.
    glm::vec3 v0(-1, -1, 0), v1(1, -1, 0), v2(0, 1, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f, v0, v1, v2);
    ASSERT_TRUE(t.has_value());
    EXPECT_FLOAT_EQ(*t, 5.0f);
}

TEST(IntersectTriangle, MissReturnsNullopt) {
    glm::vec3 v0(-1, -1, 0), v1(1, -1, 0), v2(0, 1, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(5, 5, -5), glm::vec3(0, 0, 1), 100.0f, v0, v1, v2);
    EXPECT_FALSE(t.has_value());
}

TEST(IntersectTriangle, BehindOriginReturnsNullopt) {
    glm::vec3 v0(-1, -1, 0), v1(1, -1, 0), v2(0, 1, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(0, 0, 5), glm::vec3(0, 0, 1), 100.0f, v0, v1, v2);
    EXPECT_FALSE(t.has_value());
}

TEST(IntersectTriangle, PastMaxDistReturnsNullopt) {
    glm::vec3 v0(-1, -1, 0), v1(1, -1, 0), v2(0, 1, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(0, 0, -100), glm::vec3(0, 0, 1), 5.0f, v0, v1, v2);
    EXPECT_FALSE(t.has_value());
}

TEST(IntersectTriangle, DoubleSidedHitFromBackface) {
    glm::vec3 v0(-1, -1, 0), v1(1, -1, 0), v2(0, 1, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(0, 0, 5), glm::vec3(0, 0, -1), 100.0f, v0, v1, v2);
    ASSERT_TRUE(t.has_value());
    EXPECT_FLOAT_EQ(*t, 5.0f);
}

TEST(IntersectTriangle, DegenerateTriangleReturnsNullopt) {
    glm::vec3 v0(0, 0, 0), v1(0, 0, 0), v2(0, 0, 0);
    auto t = renderer::intersect_triangle(
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f, v0, v1, v2);
    EXPECT_FALSE(t.has_value());
}

// ── ray_trace_instance helpers ──────────────────────────────────────────────

namespace {

// Build a model with a single triangle mesh under the root node, where the
// triangle lives in mesh-local space.
assets::Model single_triangle_model(glm::vec3 v0, glm::vec3 v1, glm::vec3 v2) {
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0},
    });
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = v0});
    cpu.vertices.push_back({.position = v1});
    cpu.vertices.push_back({.position = v2});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return m;
}

}  // namespace

TEST(RayTraceInstance, ReturnsHitOnSingleTriangleAtKnownPoint) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->point.x, 0.0f, 1e-5f);
    EXPECT_NEAR(hit->point.y, 0.0f, 1e-5f);
    EXPECT_NEAR(hit->point.z, 0.0f, 1e-5f);
    EXPECT_NEAR(hit->t, 5.0f, 1e-5f);
    // Normal must face the ray: ray direction is +z, so normal must have -z.
    EXPECT_LE(glm::dot(hit->normal, glm::vec3(0, 0, 1)), 0.0f);
}

TEST(RayTraceInstance, BoundingSphereMissReturnsNullopt) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});
    // Ray parallel to triangle plane, offset far in +y. Triangle AABB
    // half-extents are ~1 so the bounding sphere radius is ~sqrt(3)≈1.73.
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(100, 100, -5), glm::vec3(0, 0, 1), 100.0f);
    EXPECT_FALSE(hit.has_value());
}

TEST(RayTraceInstance, InstanceWorldTranslateRelocatesHit) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});
    glm::mat4 world = glm::translate(glm::mat4(1.0f), glm::vec3(100, 0, 0));
    auto hit = renderer::ray_trace_instance(
        m, world,
        glm::vec3(100, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->point.x, 100.0f, 1e-4f);
    EXPECT_NEAR(hit->point.z, 0.0f, 1e-4f);
}

TEST(RayTraceInstance, NodeLocalTransformApplied) {
    // Triangle's mesh-local vertices straddle origin, but its owning node
    // translates it to z=10. Ray from origin along +z must hit at z≈10.
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
    });
    m.nodes.push_back(assets::Node{
        .name = "child", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 0, 10)),
        .meshes = {0},
    });
    assets::MeshCpu cpu;
    cpu.vertices = {{.position = glm::vec3(-1, -1, 0)},
                    {.position = glm::vec3( 1, -1, 0)},
                    {.position = glm::vec3( 0,  1, 0)}};
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->point.z, 10.0f, 1e-4f);
    EXPECT_NEAR(hit->t, 15.0f, 1e-4f);
}

TEST(RayTraceInstance, ClosestHitWinsAcrossMeshes) {
    // Two triangles on parallel z planes, at z=0 and z=10. Ray from z=-5
    // along +z should hit the z=0 plane first.
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0, 1},
    });
    auto add_tri = [&](float z) {
        assets::MeshCpu cpu;
        cpu.vertices = {{.position = glm::vec3(-1, -1, z)},
                        {.position = glm::vec3( 1, -1, z)},
                        {.position = glm::vec3( 0,  1, z)}};
        cpu.indices = {0u, 1u, 2u};
        assets::Mesh mesh;
        mesh.set_cpu_data(std::move(cpu));
        m.meshes.push_back(std::move(mesh));
    };
    add_tri(10.0f);  // Mesh 0 — far.
    add_tri(0.0f);   // Mesh 1 — near.

    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->t, 5.0f, 1e-4f);
}

TEST(RayTraceInstance, EmptyModelReturnsNullopt) {
    assets::Model m;
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    EXPECT_FALSE(hit.has_value());
}

TEST(RayTraceInstance, MaxDistClipReturnsNullopt) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});
    // Triangle at z=0; ray from z=-100 reaches it at t=100, but max_dist=10.
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -100), glm::vec3(0, 0, 1), 10.0f);
    EXPECT_FALSE(hit.has_value());
}

TEST(RayTraceInstance, RayFromInsideHullHitsAndNormalFacesRay) {
    // Two opposing triangles forming a thin shell around origin; ray from
    // inside should hit one of them.
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0, 1},
    });
    auto add_tri = [&](float z) {
        assets::MeshCpu cpu;
        cpu.vertices = {{.position = glm::vec3(-5, -5, z)},
                        {.position = glm::vec3( 5, -5, z)},
                        {.position = glm::vec3( 0,  5, z)}};
        cpu.indices = {0u, 1u, 2u};
        assets::Mesh mesh;
        mesh.set_cpu_data(std::move(cpu));
        m.meshes.push_back(std::move(mesh));
    };
    add_tri(-5.0f);
    add_tri( 5.0f);

    // Ray from interior origin (0,0,0) along +z; first hit at z=5.
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, 0), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->point.z, 5.0f, 1e-4f);
    // Normal faces the incoming +z ray.
    EXPECT_LE(glm::dot(hit->normal, glm::vec3(0, 0, 1)), 0.0f);
}
```

- [ ] **Step 5: Run the failing tests to confirm linker error.**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
```
Expected: build fails with `undefined reference to renderer::intersect_triangle` / `renderer::ray_trace_instance`.

- [ ] **Step 6: Implement `ray_trace.cc`.**

Create `native/src/renderer/ray_trace.cc`:

```cpp
// native/src/renderer/ray_trace.cc
#include "renderer/ray_trace.h"

#include <limits>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>
#include <glm/gtc/matrix_inverse.hpp>

#include "renderer/aabb.h"

namespace renderer {

std::optional<float> intersect_triangle(
    glm::vec3 origin, glm::vec3 direction, float max_dist,
    glm::vec3 v0, glm::vec3 v1, glm::vec3 v2)
{
    // Möller–Trumbore, double-sided.
    constexpr float kEps = 1e-7f;
    const glm::vec3 e1 = v1 - v0;
    const glm::vec3 e2 = v2 - v0;
    const glm::vec3 p  = glm::cross(direction, e2);
    const float det = glm::dot(e1, p);
    if (std::abs(det) < kEps) return std::nullopt;  // Parallel / degenerate.
    const float inv_det = 1.0f / det;
    const glm::vec3 s = origin - v0;
    const float u = glm::dot(s, p) * inv_det;
    if (u < 0.0f || u > 1.0f) return std::nullopt;
    const glm::vec3 q = glm::cross(s, e1);
    const float v = glm::dot(direction, q) * inv_det;
    if (v < 0.0f || u + v > 1.0f) return std::nullopt;
    const float t = glm::dot(e2, q) * inv_det;
    if (t < kEps || t > max_dist) return std::nullopt;
    return t;
}

namespace {

// World-space sphere fully containing every CPU-data vertex of `model`
// after applying instance_world. Center = transformed AABB center; radius
// = length of transformed half-extents (a safe over-estimate for any
// affine instance_world).
struct WorldSphere { glm::vec3 center; float radius; };

WorldSphere compute_world_sphere(const assets::Model& model,
                                 const glm::mat4& instance_world) {
    Aabb local = compute_model_aabb(model);
    glm::vec3 c_world = glm::vec3(instance_world * glm::vec4(local.center, 1.0f));
    // Project half-extents onto world axes by taking absolute column lengths.
    glm::vec3 he = local.half_extents;
    glm::mat3 m3 = glm::mat3(instance_world);
    glm::vec3 he_world(
        std::abs(m3[0][0]) * he.x + std::abs(m3[1][0]) * he.y + std::abs(m3[2][0]) * he.z,
        std::abs(m3[0][1]) * he.x + std::abs(m3[1][1]) * he.y + std::abs(m3[2][1]) * he.z,
        std::abs(m3[0][2]) * he.x + std::abs(m3[1][2]) * he.y + std::abs(m3[2][2]) * he.z);
    return {c_world, glm::length(he_world)};
}

bool segment_hits_sphere(glm::vec3 origin, glm::vec3 direction, float max_dist,
                         glm::vec3 center, float radius) {
    if (radius <= 0.0f) return false;
    const glm::vec3 oc = origin - center;
    const float b = glm::dot(oc, direction);
    const float c = glm::dot(oc, oc) - radius * radius;
    if (c <= 0.0f) return true;          // Origin inside sphere.
    if (b >= 0.0f) return false;         // Sphere is behind the ray.
    const float disc = b * b - c;
    if (disc < 0.0f) return false;
    const float t_enter = -b - std::sqrt(disc);
    return t_enter <= max_dist;
}

// Mirror compute_model_aabb's one-pass node walk to build node_world for each
// node index. Caller can then iterate model.nodes and use node_world[i] for
// any node that owns meshes.
std::vector<glm::mat4> build_node_world(const assets::Model& model) {
    std::vector<glm::mat4> nw(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return nw;
    nw[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            nw[i] = nw[node.parent_index] * node.local_transform;
        }
    }
    return nw;
}

}  // namespace

std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist)
{
    if (model.nodes.empty() || model.meshes.empty()) return std::nullopt;

    // Bounding-sphere coarse reject (skip when model is empty / produces a
    // zero-radius sphere — then we have no geometry anyway and the inner
    // loop will return nullopt).
    const WorldSphere sphere = compute_world_sphere(model, instance_world);
    if (sphere.radius > 0.0f &&
        !segment_hits_sphere(origin, direction, max_dist,
                             sphere.center, sphere.radius)) {
        return std::nullopt;
    }

    const std::vector<glm::mat4> node_world = build_node_world(model);

    float best_t = std::numeric_limits<float>::infinity();
    glm::vec3 best_point(0.0f);
    glm::vec3 best_normal(0.0f);
    bool have_hit = false;

    for (std::size_t ni = 0; ni < model.nodes.size(); ++ni) {
        const auto& node = model.nodes[ni];
        for (int mesh_idx : node.meshes) {
            if (mesh_idx < 0 ||
                mesh_idx >= static_cast<int>(model.meshes.size())) continue;
            const auto& cpu_opt = model.meshes[mesh_idx].cpu_data();
            if (!cpu_opt) continue;
            const auto& cpu = *cpu_opt;
            if (cpu.indices.empty() || cpu.vertices.empty()) continue;

            const glm::mat4 mesh_world = instance_world * node_world[ni];
            const glm::mat4 mesh_world_inv = glm::inverse(mesh_world);
            const glm::vec3 origin_local =
                glm::vec3(mesh_world_inv * glm::vec4(origin, 1.0f));
            const glm::vec3 dir_local =
                glm::vec3(mesh_world_inv * glm::vec4(direction, 0.0f));
            const float dir_local_len = glm::length(dir_local);
            if (dir_local_len < 1e-12f) continue;
            const glm::vec3 dir_local_unit = dir_local / dir_local_len;
            const float max_dist_local = max_dist * dir_local_len;

            // Normal transform: transpose(inverse(M_3x3)) of mesh_world.
            const glm::mat3 normal_matrix =
                glm::transpose(glm::mat3(mesh_world_inv));

            for (std::size_t i = 0; i + 2 < cpu.indices.size(); i += 3) {
                const glm::vec3 v0 = cpu.vertices[cpu.indices[i + 0]].position;
                const glm::vec3 v1 = cpu.vertices[cpu.indices[i + 1]].position;
                const glm::vec3 v2 = cpu.vertices[cpu.indices[i + 2]].position;
                const auto t_local = intersect_triangle(
                    origin_local, dir_local_unit, max_dist_local, v0, v1, v2);
                if (!t_local) continue;
                // t_local is along the unit local direction; convert back to
                // world units by dividing by the local direction's length
                // (because dir_local = world_dir transformed → magnitude
                // changes when the instance has non-unit scale).
                const float t_world = *t_local / dir_local_len;
                if (t_world >= best_t) continue;
                best_t = t_world;
                const glm::vec3 hit_local =
                    origin_local + dir_local_unit * (*t_local);
                best_point = glm::vec3(mesh_world * glm::vec4(hit_local, 1.0f));
                const glm::vec3 n_local =
                    glm::normalize(glm::cross(v1 - v0, v2 - v0));
                best_normal = glm::normalize(normal_matrix * n_local);
                have_hit = true;
            }
        }
    }

    if (!have_hit) return std::nullopt;
    // Flip normal to face the incoming ray.
    if (glm::dot(best_normal, direction) > 0.0f) best_normal = -best_normal;
    return RayHit{best_point, best_normal, best_t};
}

}  // namespace renderer
```

- [ ] **Step 7: Build and run the renderer tests; expect all `IntersectTriangle.*` and `RayTraceInstance.*` tests to pass.**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests \
  && ./build/native/tests/renderer/renderer_tests --gtest_filter='IntersectTriangle.*:RayTraceInstance.*'
```
Expected: 14 tests pass (6 `IntersectTriangle.*` + 8 `RayTraceInstance.*`). If the test binary lives at a different path, find it with `find build -name renderer_tests -type f`.

- [ ] **Step 8: Commit.**

```bash
git add native/src/renderer/include/renderer/ray_trace.h \
        native/src/renderer/ray_trace.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/ray_trace_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): ray-vs-mesh trace for combat hit resolution

renderer::ray_trace_instance walks every CPU-data mesh in a Model,
chains node transforms (mirrors aabb.cc), bounding-sphere coarse
rejects, then runs Moller-Trumbore per triangle. Double-sided so a
ray originating inside the hull still hits; returns outward normal
relative to the incoming ray.

intersect_triangle exposed in the public header so callers can test
the algorithm in isolation against synthetic triangles.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Python binding `_dauntless_host.ray_trace_mesh`

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Create: `tests/integration/test_mesh_ray_trace.py`

Exposes the C++ helper to Python via the existing `_dauntless_host` module. Uses the same `g_world.get(id) → Instance*` plus `g_loaded_models[h-1]` lookup pattern other bindings already use.

- [ ] **Step 1: Add the binding implementation.**

Edit `native/src/host/host_bindings.cc`. Add this `#include` near the other renderer includes (search for `#include "renderer/aabb.h"` or similar; the file already includes other renderer headers):

```cpp
#include "renderer/ray_trace.h"
```

Then insert the new binding near `shield_hit` (around line 685, after the `shield_hit` block). Use this code verbatim:

```cpp
m.def("ray_trace_mesh",
      [](scenegraph::InstanceId id,
         std::tuple<float, float, float> origin,
         std::tuple<float, float, float> direction,
         float max_dist) -> py::object {
          auto* inst = g_world.get(id);
          if (inst == nullptr) {
              throw std::runtime_error("ray_trace_mesh: invalid InstanceId");
          }
          const auto h = inst->model_handle;
          if (h == 0 || h > g_loaded_models.size()) {
              throw std::runtime_error("ray_trace_mesh: instance has no model");
          }
          const assets::Model* model = g_loaded_models[h - 1].handle.get();
          if (model == nullptr) return py::none();

          const glm::vec3 o(std::get<0>(origin),
                            std::get<1>(origin),
                            std::get<2>(origin));
          glm::vec3 d(std::get<0>(direction),
                      std::get<1>(direction),
                      std::get<2>(direction));
          const float dlen = glm::length(d);
          if (dlen < 1e-9f) return py::none();
          d /= dlen;  // Tolerate non-unit input.

          auto hit = renderer::ray_trace_instance(
              *model, inst->world, o, d, max_dist);
          if (!hit) return py::none();
          return py::make_tuple(
              py::make_tuple(hit->point.x, hit->point.y, hit->point.z),
              py::make_tuple(hit->normal.x, hit->normal.y, hit->normal.z),
              hit->t);
      },
      py::arg("instance_id"),
      py::arg("origin"),
      py::arg("direction"),
      py::arg("max_dist"),
      "Ray-cast against an instance's loaded mesh. Returns "
      "((point), (normal), t) on hit or None on miss. Direction is "
      "auto-normalised; t is world-space distance from origin.");
```

- [ ] **Step 2: Build the extension.**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build, produces `build/python/_open_stbc_host.cpython-*.so` (the `_dauntless_host` Python import resolves to this).

- [ ] **Step 3: Write failing Python binding tests.**

Create `tests/integration/test_mesh_ray_trace.py`:

```python
"""Binding-level tests for _dauntless_host.ray_trace_mesh against a real
Galaxy NIF. The pure C++ algorithm is unit-tested with synthetic models
in native/tests/renderer/ray_trace_test.cc; this file validates the
Python<->C++ marshalling and the scenegraph/model lookup path.
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _identity_mat():
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _translation_mat(x, y, z):
    return [1.0, 0.0, 0.0, x,
            0.0, 1.0, 0.0, y,
            0.0, 0.0, 1.0, z,
            0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def galaxy_instance():
    """Headless host with a single Galaxy at world origin; yields the
    (_dauntless_host module, InstanceId) and shuts down on teardown."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    if not GALAXY_TEX.is_dir():
        pytest.skip("BC texture dir not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(256, 256, "ray-trace-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        h = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _dauntless_host.create_instance(h)
        _dauntless_host.set_world_transform(iid, _identity_mat())
        yield _dauntless_host, iid
    finally:
        _dauntless_host.shutdown()


def test_ray_through_center_returns_hit_on_or_near_hull(galaxy_instance):
    h, iid = galaxy_instance
    # Galaxy bounding sphere fits within ~300 units of origin; ray from
    # (0,0,-1000) along +z must hit somewhere on the hull at t < 1000.
    result = h.ray_trace_mesh(iid,
                              origin=(0.0, 0.0, -1000.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=2000.0)
    assert result is not None, "Ray fired straight at Galaxy should produce a hit"
    point, normal, t = result
    assert 0.0 < t < 1000.0
    # Hit point and t consistent: point ≈ origin + dir * t.
    assert abs(point[0] - 0.0) < 1.0
    assert abs(point[1] - 0.0) < 1.0
    assert abs(point[2] - (-1000.0 + t)) < 1.0
    # Normal is unit length and faces the incoming ray (dot <= 0 with +z).
    nlen = (normal[0]**2 + normal[1]**2 + normal[2]**2) ** 0.5
    assert abs(nlen - 1.0) < 0.01
    assert normal[2] <= 0.01


def test_ray_far_from_ship_returns_none(galaxy_instance):
    h, iid = galaxy_instance
    # Ray parallel to +z at x=10000 is well outside the bounding sphere.
    result = h.ray_trace_mesh(iid,
                              origin=(10000.0, 10000.0, -100.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=1000.0)
    assert result is None


def test_max_dist_clip_returns_none(galaxy_instance):
    h, iid = galaxy_instance
    # Aimed straight at Galaxy but capped before reaching it.
    result = h.ray_trace_mesh(iid,
                              origin=(0.0, 0.0, -1000.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=10.0)
    assert result is None


def test_instance_world_transform_translates_hit(galaxy_instance):
    h, iid = galaxy_instance
    # Move the Galaxy out by +500 in x; the same ray (along +z at x=0) now
    # misses; a ray at x=500 hits.
    h.set_world_transform(iid, _translation_mat(500.0, 0.0, 0.0))
    miss = h.ray_trace_mesh(iid,
                            origin=(0.0, 0.0, -1000.0),
                            direction=(0.0, 0.0, 1.0),
                            max_dist=2000.0)
    assert miss is None
    hit = h.ray_trace_mesh(iid,
                           origin=(500.0, 0.0, -1000.0),
                           direction=(0.0, 0.0, 1.0),
                           max_dist=2000.0)
    assert hit is not None
    point, _, _ = hit
    assert abs(point[0] - 500.0) < 1.0


def test_invalid_instance_id_raises(galaxy_instance):
    h, _ = galaxy_instance
    # Construct an InstanceId that was never created. The binding takes
    # an InstanceId object; build one via the public class.
    bogus = h.InstanceId()  # default index=0, generation=0 — not alive.
    # Generation mismatch on a never-allocated slot → get() returns nullptr.
    bogus_id = bogus
    # Force the index to a slot that's definitely never been allocated by
    # creating one via the binding's properties is not possible (readonly);
    # instead test that an obviously-stale id raises. The default-constructed
    # id has index 0 generation 0, which g_world.get() rejects.
    with pytest.raises(RuntimeError):
        h.ray_trace_mesh(bogus_id,
                         origin=(0.0, 0.0, 0.0),
                         direction=(0.0, 0.0, 1.0),
                         max_dist=10.0)
```

- [ ] **Step 4: Run the new tests; expect them to pass.**

Run:
```bash
uv run pytest tests/integration/test_mesh_ray_trace.py -v
```
Expected: 5 tests pass. If `_dauntless_host` is not built, all tests skip — re-run after step 2 succeeds.

- [ ] **Step 5: Commit.**

```bash
git add native/src/host/host_bindings.cc tests/integration/test_mesh_ray_trace.py
git commit -m "feat(host): expose ray_trace_mesh binding

Wraps renderer::ray_trace_instance. Looks up the instance's Model via
g_loaded_models, calls the trace with the instance world transform,
marshals the (point, normal, t) tuple back to Python or returns None
on miss. Raises on stale InstanceId.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Python helpers `ray_sphere_entry` + `_resolve_hit_point`

**Files:**
- Modify: `engine/appc/combat.py`
- Test: a new section in `tests/unit/test_combat_hit_resolution.py` (create)

Encapsulates the three-tier fallback so both call sites stay tiny.

- [ ] **Step 1: Write failing unit tests.**

Create `tests/unit/test_combat_hit_resolution.py`:

```python
"""ray_sphere_entry + _resolve_hit_point fallback chain."""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.combat import ray_sphere_entry, _resolve_hit_point


# ── ray_sphere_entry ────────────────────────────────────────────────────────

def test_ray_sphere_entry_hits_front_of_sphere():
    origin = TGPoint3(0, 0, -10)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=20.0,
                          center=center, radius=2.0)
    assert p is not None
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(0.0)
    assert p.z == pytest.approx(-2.0)


def test_ray_sphere_entry_origin_inside_returns_origin():
    origin = TGPoint3(0, 0, 0)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=10.0,
                          center=center, radius=2.0)
    assert p is not None
    # Inside the sphere: the "entry" is the origin itself.
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(0.0)
    assert p.z == pytest.approx(0.0)


def test_ray_sphere_entry_miss_returns_none():
    origin = TGPoint3(10, 10, -10)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=20.0,
                          center=center, radius=2.0)
    assert p is None


def test_ray_sphere_entry_past_max_dist_returns_none():
    origin = TGPoint3(0, 0, -100)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=10.0,
                          center=center, radius=2.0)
    assert p is None


# ── _resolve_hit_point ──────────────────────────────────────────────────────

class _FakeShip:
    def __init__(self, x, y, z, r=10.0):
        self._loc = TGPoint3(x, y, z)
        self._r = r
    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r


class _FakeHost:
    """Minimal host stub: ray_trace_mesh returns a preconfigured value."""
    def __init__(self, result):
        self._result = result
        self.calls = []
    def ray_trace_mesh(self, instance_id, origin, direction, max_dist):
        self.calls.append((instance_id, origin, direction, max_dist))
        return self._result


def test_resolve_returns_mesh_hit_when_trace_succeeds():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p.x == pytest.approx(1.0)
    assert p.y == pytest.approx(2.0)
    assert p.z == pytest.approx(3.0)


def test_resolve_falls_back_to_sphere_entry_when_trace_misses():
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=None)
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere of radius 2 at origin; ray enters at z=-2.
    assert p.z == pytest.approx(-2.0)


def test_resolve_returns_fallback_when_host_is_none():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    p = _resolve_hit_point(
        host=None, ship_instances=None, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback


def test_resolve_returns_fallback_when_ship_instances_missing():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p = _resolve_hit_point(
        host=host, ship_instances={}, ship=ship,  # ship not in map
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
    assert host.calls == []  # binding must not be called without an iid


def test_resolve_returns_fallback_when_binding_missing():
    """If host exists but lacks ray_trace_mesh (older build), fall through."""
    class HostWithoutTrace:
        pass
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    p = _resolve_hit_point(
        host=HostWithoutTrace(), ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere entry preferred when ray clearly intersects sphere; otherwise
    # fallback.
    assert p.z == pytest.approx(-2.0)


def test_resolve_falls_back_to_caller_point_when_sphere_also_misses():
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=None)
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        # Ray that misses the bounding sphere entirely.
        ray_origin=TGPoint3(100, 100, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
```

- [ ] **Step 2: Run the failing tests; confirm `ImportError`.**

Run:
```bash
uv run pytest tests/unit/test_combat_hit_resolution.py -v
```
Expected: collection failure / `ImportError: cannot import name 'ray_sphere_entry'`.

- [ ] **Step 3: Implement the helpers in `combat.py`.**

Edit `engine/appc/combat.py`. After the `sphere_hit` function (around line 17), insert:

```python
def ray_sphere_entry(origin, direction, max_dist: float,
                     center, radius: float):
    """Return the entry point of the ray (origin, unit `direction`) into
    the sphere (`center`, `radius`), or `None` if the ray's segment of
    length `max_dist` misses the sphere.

    If `origin` is already inside the sphere, returns `origin` (the
    "entry" degenerates to the start of the ray).
    """
    if radius <= 0.0:
        return None
    ox = origin.x - center.x
    oy = origin.y - center.y
    oz = origin.z - center.z
    # Direction is assumed unit length.
    b = ox * direction.x + oy * direction.y + oz * direction.z
    c = ox * ox + oy * oy + oz * oz - radius * radius
    if c <= 0.0:
        # Inside or on the sphere — entry is the origin itself.
        return origin
    if b >= 0.0:
        return None  # Sphere is behind the ray.
    disc = b * b - c
    if disc < 0.0:
        return None
    t_enter = -b - disc ** 0.5
    if t_enter < 0.0 or t_enter > max_dist:
        return None
    return TGPoint3(
        origin.x + direction.x * t_enter,
        origin.y + direction.y * t_enter,
        origin.z + direction.z * t_enter,
    )


def _resolve_hit_point(host, ship_instances, ship,
                       ray_origin, ray_direction,
                       max_dist: float, fallback_point):
    """Three-tier hit-point fallback:

    1. If `host` is wired with `ray_trace_mesh` and `ship` has a renderer
       `InstanceId` in `ship_instances`, run the mesh trace and return the
       returned surface point on hit.
    2. Otherwise (or on mesh miss), if the ray segment intersects the
       ship's bounding sphere, return the sphere-entry point.
    3. Otherwise return `fallback_point` — each caller's pre-project
       legacy point (`torpedo._position` for projectiles; `target_pos`
       for phasers). Preserves headless and broken-binding behaviour.
    """
    # Step 1: mesh trace.
    iid = None
    if ship_instances is not None:
        iid = ship_instances.get(ship)
    if (host is not None
            and iid is not None
            and hasattr(host, "ray_trace_mesh")
            and ray_direction is not None):
        try:
            result = host.ray_trace_mesh(
                iid,
                (ray_origin.x, ray_origin.y, ray_origin.z),
                (ray_direction.x, ray_direction.y, ray_direction.z),
                max_dist,
            )
        except Exception:
            result = None
        if result is not None:
            (px, py, pz), _normal, _t = result
            return TGPoint3(px, py, pz)
    # Step 2: sphere entry.
    if ray_direction is not None:
        center = ship.GetWorldLocation()
        radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
        entry = ray_sphere_entry(ray_origin, ray_direction, max_dist,
                                 center, radius)
        if entry is not None:
            return entry
    # Step 3: fallback.
    return fallback_point
```

- [ ] **Step 4: Run the tests; expect all to pass.**

Run:
```bash
uv run pytest tests/unit/test_combat_hit_resolution.py -v
```
Expected: 10 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add engine/appc/combat.py tests/unit/test_combat_hit_resolution.py
git commit -m "feat(combat): ray_sphere_entry + _resolve_hit_point helpers

Three-tier fallback chain (mesh trace -> sphere entry -> caller
legacy point) so both projectile and phaser callers can share one
resolution path without duplicating the host-lookup / fallback logic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Refactor `projectiles.update_all` to emit hit points

**Files:**
- Modify: `engine/appc/projectiles.py`
- Modify: `tests/unit/test_torpedo_advance.py`

Adds `host` + `ship_instances` keyword args, returns 4-tuples `(torpedo, ship, subsystem, hit_point)`. Behaviour with `host=None` is identical to today's: `hit_point = torpedo._position` (the post-advance value).

- [ ] **Step 1: Update existing torpedo unit tests to consume 4-tuples.**

Edit `tests/unit/test_torpedo_advance.py`. Change `test_torpedo_collides_with_ship_sphere` to assert the new tuple shape:

```python
def test_torpedo_collides_with_ship_sphere():
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)
    hits = update_all(dt=0.1, all_ships=[src, target])
    # Position advances to (1,0,0); distance to (5,0,0) = 4 < radius 10 ⇒ hit
    assert len(hits) == 1
    assert hits[0][0] is t
    assert hits[0][1] is target
    # New: 4-tuple emits the hit point. Headless (no host) → torpedo._position.
    assert len(hits[0]) == 4
    assert hits[0][3].x == pytest.approx(t._position.x)
    assert hits[0][3].y == pytest.approx(t._position.y)
    assert hits[0][3].z == pytest.approx(t._position.z)
```

- [ ] **Step 2: Add a new test asserting the host/ship_instances path is wired.**

Append to `tests/unit/test_torpedo_advance.py`:

```python
def test_torpedo_uses_host_ray_trace_mesh_when_supplied():
    """When host + ship_instances are supplied, hit_point comes from the
    mesh trace, not the post-advance position."""
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)

    class FakeHost:
        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return ((7.0, 7.0, 7.0), (0.0, 0.0, -1.0), 1.0)

    instance_sentinel = object()
    hits = update_all(
        dt=0.1, all_ships=[src, target],
        host=FakeHost(),
        ship_instances={target: instance_sentinel},
    )
    assert len(hits) == 1
    _, ship, _, hit_point = hits[0]
    assert ship is target
    assert hit_point.x == pytest.approx(7.0)
    assert hit_point.y == pytest.approx(7.0)
    assert hit_point.z == pytest.approx(7.0)
```

- [ ] **Step 3: Run the tests; expect 2 failures.**

Run:
```bash
uv run pytest tests/unit/test_torpedo_advance.py -v
```
Expected: `test_torpedo_collides_with_ship_sphere` fails with `IndexError` (still 3-tuple), and `test_torpedo_uses_host_ray_trace_mesh_when_supplied` fails because `update_all` does not accept `host` / `ship_instances` kwargs.

- [ ] **Step 4: Update `update_all`.**

Edit `engine/appc/projectiles.py`. Replace the function (currently around lines 109–151) with:

```python
def update_all(dt: float, all_ships, *, host=None, ship_instances=None) -> list[tuple]:
    """Advance every active torpedo by dt.  Returns list of
    (torpedo, hit_ship, hit_subsystem, hit_point) tuples that connected
    this tick. Expired torpedoes (TTL or impact) are removed from
    _active.

    `host` and `ship_instances` are forwarded to combat._resolve_hit_point;
    when omitted (headless tests, no renderer), hit_point degrades to the
    torpedo's post-advance position — matching the pre-project behaviour.
    """
    from engine.appc.combat import (pick_target_subsystem, sphere_hit,
                                    _resolve_hit_point)
    from engine.appc.math import TGPoint3

    hits: list[tuple] = []
    expired: list[Torpedo] = []

    for t in list(_active):
        # 1. Steer if homing within guidance window.
        if t._target_ship is not None and t._age < t._guidance_lifetime:
            _steer_toward(t, t._target_ship, dt)
        # 2. Advance position + age.
        prev_pos = TGPoint3(t._position.x, t._position.y, t._position.z)
        t._position = t._position + t._velocity * dt
        t._age += dt
        if t._age >= t._ttl:
            expired.append(t)
            continue
        # 3. Collide.
        for ship in all_ships:
            if ship is t._source_ship:
                continue
            if ship.IsDead():
                continue
            if sphere_hit(t._position, ship.GetWorldLocation(), ship.GetRadius()):
                # Build the per-tick ray and resolve the hit point through
                # the three-tier fallback (mesh trace / sphere entry /
                # post-advance position).
                seg = t._position - prev_pos
                seg_len = seg.Length()
                if seg_len > 1e-9:
                    aim_unit = TGPoint3(
                        seg.x / seg_len, seg.y / seg_len, seg.z / seg_len)
                else:
                    aim_unit = None
                hit_point = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=ship,
                    ray_origin=prev_pos,
                    ray_direction=aim_unit,
                    max_dist=seg_len,
                    fallback_point=t._position,
                )
                # If the player locked a specific subsystem on this
                # target, route damage there directly; otherwise pick the
                # nearest hardpoint to the resolved hit point.
                if (t._target_subsystem is not None
                        and t._target_ship is ship):
                    subsystem = t._target_subsystem
                else:
                    subsystem = pick_target_subsystem(ship, hit_point)
                hits.append((t, ship, subsystem, hit_point))
                expired.append(t)
                break

    for t in expired:
        expire(t)

    return hits
```

- [ ] **Step 5: Run the tests; expect all to pass.**

Run:
```bash
uv run pytest tests/unit/test_torpedo_advance.py -v
```
Expected: 9 tests pass (8 pre-existing — one of which is the updated `test_torpedo_collides_with_ship_sphere` — plus the new `test_torpedo_uses_host_ray_trace_mesh_when_supplied`).

- [ ] **Step 6: Commit.**

```bash
git add engine/appc/projectiles.py tests/unit/test_torpedo_advance.py
git commit -m "refactor(projectiles): update_all emits resolved hit point per tuple

update_all now returns (torpedo, ship, subsystem, hit_point) tuples
and accepts host/ship_instances kwargs forwarded to the new
combat._resolve_hit_point helper. With host=None (headless path),
hit_point equals torpedo._position so existing behaviour is preserved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Wire `host_loop._advance_combat` torpedo branch + integration test

**Files:**
- Modify: `engine/host_loop.py`
- Create: `tests/integration/test_torpedo_hit_point_on_mesh.py`

`_advance_combat` already receives `host` and `ship_instances`; this task just forwards them to `update_all` and switches to the 4-tuple.

- [ ] **Step 1: Write failing integration test for torpedo path.**

Create `tests/integration/test_torpedo_hit_point_on_mesh.py`:

```python
"""Torpedo impact point is the mesh-trace return value when a host is
wired, not the torpedo's post-advance position."""
import pytest
from unittest.mock import patch

from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGPoint3
from engine.appc import projectiles
from engine.appc.projectiles import Torpedo, register
from engine.host_loop import _advance_combat


class _CapturingHost:
    """Stub host: ray_trace_mesh returns a fixed surface point so the
    test can prove it propagated through to apply_hit's hit_point."""
    SURFACE_POINT = (12.5, -3.0, 7.25)

    def __init__(self):
        self.shield_hits = []
    def ray_trace_mesh(self, iid, origin, direction, max_dist):
        return (self.SURFACE_POINT, (0.0, 0.0, -1.0), 1.0)
    def shield_hit(self, instance_id, point, rgba, intensity):
        self.shield_hits.append(point)
    def __getattr__(self, name):
        # set_torpedoes / set_hit_vfx / set_phaser_beams are touched by
        # _advance_combat; provide silent no-op accessors so the call
        # doesn't raise.
        return lambda *a, **kw: None


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def test_torpedo_hit_uses_mesh_trace_point():
    from tests.unit.test_torpedo_advance import _FakeShip

    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = Torpedo()
    t._position = TGPoint3(0, 0, 0)
    t._velocity = TGPoint3(10, 0, 0)
    t._ttl = 30.0
    t._age = 0.0
    t._source_ship = src
    t._damage = 100.0
    register(t)

    host = _CapturingHost()
    captured = {}
    sentinel = object()

    # Patch apply_hit to capture the hit_point it receives.
    import engine.appc.combat as combat
    orig_apply_hit = combat.apply_hit

    def spy(ship, damage, hit_point, source, subsystem=None):
        captured["hit_point"] = hit_point

    with patch.object(combat, "apply_hit", spy):
        _advance_combat([src, target], dt=0.1,
                        host=host,
                        ship_instances={target: sentinel})

    assert "hit_point" in captured, "apply_hit was never called"
    p = captured["hit_point"]
    assert p.x == pytest.approx(_CapturingHost.SURFACE_POINT[0])
    assert p.y == pytest.approx(_CapturingHost.SURFACE_POINT[1])
    assert p.z == pytest.approx(_CapturingHost.SURFACE_POINT[2])
```

(Patching strategy: `_advance_combat` does `from engine.appc.combat import apply_hit` at function scope on each call, so patching `engine.appc.combat.apply_hit` is picked up at call time.)

- [ ] **Step 2: Run the test; expect failure.**

Run:
```bash
uv run pytest tests/integration/test_torpedo_hit_point_on_mesh.py -v
```
Expected: failure — captured `hit_point` is `torpedo._position` (approx `(1.0, 0.0, 0.0)`), not the mesh-trace return.

- [ ] **Step 3: Update `_advance_combat`'s torpedo block.**

Edit `engine/host_loop.py`. Replace the existing torpedo block (currently around lines 227–245). The replacement:

```python
    hits = projectiles.update_all(
        dt, ships_list,
        host=host, ship_instances=ship_instances,
    )
    for torpedo, ship, subsystem, hit_point in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship, subsystem=subsystem)
        hit_vfx.spawn(hit_point)
        if (host is not None
                and ship_instances is not None
                and hasattr(host, "shield_hit")):
            iid = ship_instances.get(ship)
            if iid is not None:
                # Resolved hit point — on the hull when the mesh trace
                # succeeded; on the bounding-sphere shell otherwise.
                host.shield_hit(
                    instance_id=iid,
                    point=(hit_point.x, hit_point.y, hit_point.z),
                    rgba=(0.0, 0.0, 0.0, 0.0),
                    intensity=1.0,
                )
```

- [ ] **Step 4: Run the test; expect success.**

Run:
```bash
uv run pytest tests/integration/test_torpedo_hit_point_on_mesh.py -v
```
Expected: 1 test passes.

- [ ] **Step 5: Rerun the previously-passing torpedo + combat suites to confirm no regressions.**

Run:
```bash
uv run pytest tests/unit/test_torpedo_advance.py tests/unit/test_combat_hit_resolution.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add engine/host_loop.py tests/integration/test_torpedo_hit_point_on_mesh.py
git commit -m "feat(host_loop): torpedo hits use resolved mesh point

_advance_combat's torpedo branch consumes update_all's new 4-tuple
and forwards the resolved hit_point to apply_hit, hit_vfx, and
shield_hit so the visible impact lands on the hull.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Wire `_advance_combat` phaser branch + integration test extension

**Files:**
- Modify: `engine/host_loop.py`
- Modify: `tests/integration/test_phaser_damage_applied_through_apply_hit.py`

Replaces the phaser-loop's `target_pos` consumer with a `_resolve_hit_point` call. Continuous-fire arc-check + falloff still use `dist`/`aim_unit` derived from the unchanged `target_pos`.

- [ ] **Step 1: Add an integration test case asserting the phaser path uses the mesh trace.**

Append to `tests/integration/test_phaser_damage_applied_through_apply_hit.py`:

```python
def test_phaser_hit_point_comes_from_host_ray_trace_mesh(galaxy_red):
    """When a host is supplied with ray_trace_mesh, apply_hit receives
    the surface point, not target.GetWorldLocation()."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    SURFACE_POINT = (1.5, 47.25, -2.0)  # Distinct from target_pos.

    class FakeHost:
        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return (SURFACE_POINT, (0.0, -1.0, 0.0), 1.0)
        def shield_hit(self, instance_id, point, rgba, intensity):
            pass
        def __getattr__(self, name):
            return lambda *a, **kw: None

    captured = {}
    import engine.appc.combat as combat
    orig = combat.apply_hit

    def spy(ship_, damage, hit_point, source, subsystem=None):
        captured["hit_point"] = hit_point

    sentinel = object()
    with patch.object(combat, "apply_hit", spy), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        _advance_combat([ship, target], dt=0.1,
                        host=FakeHost(),
                        ship_instances={target: sentinel})

    assert "hit_point" in captured, "apply_hit was never called"
    hp = captured["hit_point"]
    assert hp.x == pytest.approx(SURFACE_POINT[0])
    assert hp.y == pytest.approx(SURFACE_POINT[1])
    assert hp.z == pytest.approx(SURFACE_POINT[2])
```

Add the missing import at the top of the test file (it already imports `patch`; add `pytest` if it isn't already there):

```python
import pytest
```

(check the file head — pytest is implicit via the `galaxy_red` fixture but `pytest.approx` needs an explicit import).

- [ ] **Step 2: Run the new test; expect failure.**

Run:
```bash
uv run pytest tests/integration/test_phaser_damage_applied_through_apply_hit.py::test_phaser_hit_point_comes_from_host_ray_trace_mesh -v
```
Expected: failure — `hit_point` matches `target.GetWorldLocation()` (the old code path), not `SURFACE_POINT`.

- [ ] **Step 3: Update the phaser block in `_advance_combat`.**

Edit `engine/host_loop.py`. The phaser block currently around lines 266–310. Replace it with the version below (only the `damage > 0` arm changes — everything above it stays):

```python
            damage = _phaser_damage_for_tick(
                max_damage=bank.GetMaxDamage(),
                max_damage_distance=bank.GetMaxDamageDistance(),
                dist=dist,
                dt=dt,
            )
            if damage > 0:
                from engine.appc.combat import _resolve_hit_point
                impact_point = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
                apply_hit(target, damage, impact_point,
                          source=ship, subsystem=target_sub)
                if (host is not None
                        and ship_instances is not None
                        and hasattr(host, "shield_hit")):
                    iid = ship_instances.get(target)
                    if iid is not None:
                        host.shield_hit(
                            instance_id=iid,
                            point=(impact_point.x, impact_point.y, impact_point.z),
                            rgba=(0.0, 0.0, 0.0, 0.0),
                            intensity=1.0,
                        )
```

- [ ] **Step 4: Run the new test; expect success.**

Run:
```bash
uv run pytest tests/integration/test_phaser_damage_applied_through_apply_hit.py -v
```
Expected: all 3 tests pass (the 2 pre-existing + the new mesh-trace test).

- [ ] **Step 5: Run the integration smoke suite to confirm no other regressions.**

Run the focused integration set the spec touches (do NOT run the full suite — CLAUDE.md warns full pytest OOMs the host):

```bash
uv run pytest tests/unit/test_torpedo_advance.py \
              tests/unit/test_combat_hit_resolution.py \
              tests/integration/test_phaser_damage_applied_through_apply_hit.py \
              tests/integration/test_torpedo_hit_point_on_mesh.py \
              tests/integration/test_mesh_ray_trace.py -v
```
Expected: all pass (or skip with no-asset / no-GL messages for the mesh-ray-trace and torpedo-on-mesh tests on machines without the BC install or a display).

- [ ] **Step 6: Commit.**

```bash
git add engine/host_loop.py tests/integration/test_phaser_damage_applied_through_apply_hit.py
git commit -m "feat(host_loop): phaser hits use resolved mesh point

The phaser continuous-fire loop now feeds apply_hit and shield_hit
with the _resolve_hit_point output. Damage falloff still keys off
the emitter->aim distance, so firing math is unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Visual smoke verification

**Files:** none (manual verification).

The spec's §6.5 visual smoke is the definition-of-done gate before merging.

- [ ] **Step 1: Build the renderer host.**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: `./build/dauntless` is produced.

- [ ] **Step 2: Launch and load the combat mission.**

Run `./build/dauntless` and load the mission that puts a Galaxy and a Warbird in firing range — Mark's standard combat-smoke launch. The exact load path is whatever the current dauntless entry point auto-runs; no specific UI flow is part of the gate.

- [ ] **Step 3: Verify phaser beam terminus on hull.**

Target the Warbird (target list / front-arc), hold LBUTTON to fire phasers. Visually confirm: beam terminus is ON the Warbird's hull surface, NOT at the centre of the bounding sphere (which would visibly extend a few hundred units past where the hull starts).

- [ ] **Step 4: Verify torpedo impact on hull.**

Fire a torpedo at the Warbird. Visually confirm: detonation flash spawns ON the hull, NOT at the bounding-sphere boundary.

- [ ] **Step 5: If both visuals check out, record completion.**

Optionally take a screenshot (`Cmd+Shift+4` on macOS) and stash in `docs/project/`; not required.

- [ ] **Step 6: Final commit summarising the project.**

```bash
git commit --allow-empty -m "chore: project 1 (mesh-accurate hit resolution) complete

Definition-of-done met:
- _h.ray_trace_mesh binding callable from Python.
- Torpedo + phaser paths feed mesh-accurate hit points into apply_hit.
- Three-tier fallback (mesh / sphere / legacy point) keeps headless
  and pre-binding paths green.
- Visual smoke: beam + torpedo impacts land on hull in E1M1.

Next: Project 2 (subsystem damage propagation).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Out of scope reminders

Do not touch in this project:
- `pick_target_subsystem` semantics (Project 2).
- `_shield_face_from_hit_point` rotation correctness (Project 3).
- Damage VFX surface-normal consumption (Project 4).
- Subsystem-failure gameplay (Project 5).
- BVH acceleration (parking lot).
