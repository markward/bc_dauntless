#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "renderer/ray_trace.h"
#include "assets/model.h"

// ── intersect_triangle ──────────────────────────────────────────────────────

TEST(IntersectTriangle, HitsCenterOfXyTriangleAtKnownT) {
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
    EXPECT_LE(glm::dot(hit->normal, glm::vec3(0, 0, 1)), 0.0f);
}

TEST(RayTraceInstance, BoundingSphereMissReturnsNullopt) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});
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
    add_tri(10.0f);
    add_tri(0.0f);

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
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -100), glm::vec3(0, 0, 1), 10.0f);
    EXPECT_FALSE(hit.has_value());
}

TEST(RayTraceInstance, RayFromInsideHullHitsAndNormalFacesRay) {
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

    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, 0), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR(hit->point.z, 5.0f, 1e-4f);
    EXPECT_LE(glm::dot(hit->normal, glm::vec3(0, 0, 1)), 0.0f);
}

// ── the per-model trace cache ───────────────────────────────────────────────
//
// ray_trace_instance caches the node-world chain and the model AABB on the
// Model (Model::trace_cache_built), because rebuilding them per ray was 1.81 ms
// of a 2.37 ms trace. Both are functions of the model's own geometry, so the
// cache is only sound if NOTHING instance-dependent leaks into it.
//
// Every test above builds a FRESH model, so none of them traces one model
// twice -- the entire cache-reuse path was uncovered, and a cache poisoned
// with the first call's instance transform would have passed all of them.

TEST(RayTraceInstanceCache, SameModelAtTwoTransformsGivesTwoDifferentHits) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});

    // The FIRST trace must use a non-identity transform. Calibrated against a
    // deliberately poisoned cache (one that bakes the first call's
    // instance_world into the cached bound): with an identity first call the
    // poison is a no-op and this test passes while the defect is live. The
    // populating call has to be the interesting one.
    const glm::mat4 moved =
        glm::translate(glm::mat4(1.0f), glm::vec3(100, 0, 0));
    auto a = renderer::ray_trace_instance(
        m, moved,
        glm::vec3(100, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(a.has_value());
    EXPECT_NEAR(a->point.x, 100.0f, 1e-4f);

    // Second trace of the SAME model, back at the origin. A cache holding the
    // first call's transform either misses the bounding sphere here or reports
    // the x=100 hit point.
    auto b = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(b.has_value()) << "cached bound rejected a ray that hits";
    EXPECT_NEAR(b->point.x, 0.0f, 1e-4f);
    EXPECT_NEAR(b->point.z, 0.0f, 1e-4f);

    // ...and back again, so the cache is not merely tracking the latest call.
    auto c = renderer::ray_trace_instance(
        m, moved,
        glm::vec3(100, 0, -5), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(c.has_value());
    EXPECT_NEAR(c->point.x, 100.0f, 1e-4f);
}

TEST(RayTraceInstanceCache, CachedBoundStillCullsAMissAfterAHit) {
    auto m = single_triangle_model({-1, -1, 0}, {1, -1, 0}, {0, 1, 0});

    const glm::mat4 moved =
        glm::translate(glm::mat4(1.0f), glm::vec3(0, 0, 40));
    auto hit = renderer::ray_trace_instance(
        m, moved,
        glm::vec3(0, 0, 35), glm::vec3(0, 0, 1), 100.0f);
    ASSERT_TRUE(hit.has_value());

    // Same model, ray far off to the side. The cached AABB must still produce
    // a bounding sphere that rejects it -- a cache that stored a degenerate or
    // stale bound would let this through to the triangle loop (slow but still
    // a miss) or, worse, report a hit.
    auto miss = renderer::ray_trace_instance(
        m, glm::mat4(1.0f),
        glm::vec3(100, 100, -5), glm::vec3(0, 0, 1), 100.0f);
    EXPECT_FALSE(miss.has_value());
}

TEST(RayTraceInstanceCache, CachedNodeChainStillAppliesNodeLocalTransforms) {
    // A two-level hierarchy: the child's translate must survive caching. If
    // ensure_trace_cache built the chain wrongly (e.g. identity), the hit
    // would land at z=0 instead of z=10 -- and it would do so consistently,
    // so a single-call test could not tell the difference.
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

    for (int pass = 0; pass < 2; ++pass) {
        auto hit = renderer::ray_trace_instance(
            m, glm::mat4(1.0f),
            glm::vec3(0, 0, -5), glm::vec3(0, 0, 1), 100.0f);
        ASSERT_TRUE(hit.has_value()) << "pass " << pass;
        EXPECT_NEAR(hit->point.z, 10.0f, 1e-4f) << "pass " << pass;
    }
}
