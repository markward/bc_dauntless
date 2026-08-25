#include <gtest/gtest.h>
#include <array>
#include <optional>
#include <limits>
#include <random>
#include <vector>
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

// -- the BVH ----------------------------------------------------------------
//
// ray_trace_instance walks a median-split BVH over a model-space triangle
// soup instead of testing every triangle linearly. Leaves hold up to 8
// triangles, so EVERY test above -- all of which use one or two triangles --
// produces a single leaf node and never traverses the tree at all. The
// acceleration structure was completely uncovered by them.
//
// A BVH is exactly the kind of code where "it compiles and the simple cases
// pass" means nothing: the failure mode is a wrongly-bounded interior node
// that silently drops a hit for some ray directions. So this diffs it against
// brute force -- the thing it replaced -- over a model big enough to be a real
// tree, with rays fired from every direction.

namespace {

struct SoupModel {
    assets::Model model;
    std::vector<std::array<glm::vec3, 3>> tris;   // model space
};

/// A pseudo-random triangle soup spread across several nodes and meshes, so
/// the tree spans node transforms rather than one flat buffer.
SoupModel random_soup(int n_meshes, int tris_per_mesh, unsigned seed) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> pos(-30.0f, 30.0f);
    std::uniform_real_distribution<float> tiny(-4.0f, 4.0f);

    SoupModel out;
    out.model.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1, .local_transform = glm::mat4(1.0f),
    });
    for (int m = 0; m < n_meshes; ++m) {
        const glm::vec3 node_off(pos(rng) * 0.2f, pos(rng) * 0.2f, pos(rng) * 0.2f);
        const glm::mat4 node_xf = glm::translate(glm::mat4(1.0f), node_off);
        out.model.nodes.push_back(assets::Node{
            .name = "n", .parent_index = 0,
            .local_transform = node_xf,
            .meshes = {m},
        });
        assets::MeshCpu cpu;
        for (int i = 0; i < tris_per_mesh; ++i) {
            const glm::vec3 base(pos(rng), pos(rng), pos(rng));
            glm::vec3 v[3];
            for (int c = 0; c < 3; ++c) {
                v[c] = base + glm::vec3(tiny(rng), tiny(rng), tiny(rng));
                cpu.vertices.push_back({.position = v[c]});
                cpu.indices.push_back(
                    static_cast<std::uint32_t>(cpu.vertices.size() - 1));
            }
            // Record the MODEL-space triangle for the brute-force reference.
            out.tris.push_back({glm::vec3(node_xf * glm::vec4(v[0], 1.0f)),
                                glm::vec3(node_xf * glm::vec4(v[1], 1.0f)),
                                glm::vec3(node_xf * glm::vec4(v[2], 1.0f))});
        }
        assets::Mesh mesh;
        mesh.set_cpu_data(std::move(cpu));
        out.model.meshes.push_back(std::move(mesh));
    }
    return out;
}

/// The pre-BVH algorithm: test every triangle, keep the nearest.
/// instance_world is identity in these cases, so model space == world space.
std::optional<float> brute_force_t(const SoupModel& s,
                                   glm::vec3 o, glm::vec3 d, float max_dist) {
    float best = std::numeric_limits<float>::infinity();
    bool hit = false;
    for (const auto& t : s.tris) {
        auto r = renderer::intersect_triangle(o, d, max_dist, t[0], t[1], t[2]);
        if (!r || *r >= best) continue;
        best = *r;
        hit = true;
    }
    if (!hit) return std::nullopt;
    return best;
}

}  // namespace

TEST(RayTraceBvh, MatchesBruteForceOverManyRandomRays) {
    SoupModel s = random_soup(6, 60, 1234u);
    ASSERT_EQ(s.tris.size(), 360u) << "soup must be far past the 8-tri leaf size";

    std::mt19937 rng(99u);
    std::uniform_real_distribution<float> u(-1.0f, 1.0f);
    std::uniform_real_distribution<float> far(40.0f, 90.0f);

    int hits = 0, misses = 0;
    for (int i = 0; i < 3000; ++i) {
        glm::vec3 dir(u(rng), u(rng), u(rng));
        if (glm::length(dir) < 1e-3f) continue;
        dir = glm::normalize(dir);
        const glm::vec3 origin = -dir * far(rng);

        auto want = brute_force_t(s, origin, dir, 400.0f);
        auto got = renderer::ray_trace_instance(
            s.model, glm::mat4(1.0f), origin, dir, 400.0f);

        ASSERT_EQ(want.has_value(), got.has_value()) << "ray " << i;
        if (want) {
            // The NEAREST triangle, not merely some triangle: a BVH that
            // stops descending too early reports a farther hit.
            EXPECT_NEAR(*want, got->t, 1e-3f) << "ray " << i;
            ++hits;
        } else {
            ++misses;
        }
    }
    // The scenario has to exercise both outcomes, or "agrees with brute force"
    // is a statement about nothing.
    EXPECT_GT(hits, 200) << "rays almost never hit; the soup is not being tested";
    EXPECT_GT(misses, 50) << "rays always hit; misses are untested";
}

TEST(RayTraceBvh, MatchesBruteForceForRaysStartingInsideTheHull) {
    // Interior origins stress the slab test tmin clamp at 0 and the self-hit
    // epsilon, neither of which an exterior ray reaches.
    SoupModel s = random_soup(4, 50, 77u);
    std::mt19937 rng(5u);
    std::uniform_real_distribution<float> u(-1.0f, 1.0f);
    std::uniform_real_distribution<float> inside(-12.0f, 12.0f);

    int checked = 0;
    for (int i = 0; i < 1500; ++i) {
        glm::vec3 dir(u(rng), u(rng), u(rng));
        if (glm::length(dir) < 1e-3f) continue;
        dir = glm::normalize(dir);
        const glm::vec3 origin(inside(rng), inside(rng), inside(rng));

        auto want = brute_force_t(s, origin, dir, 500.0f);
        auto got = renderer::ray_trace_instance(
            s.model, glm::mat4(1.0f), origin, dir, 500.0f);
        ASSERT_EQ(want.has_value(), got.has_value()) << "ray " << i;
        if (want) EXPECT_NEAR(*want, got->t, 1e-3f) << "ray " << i;
        ++checked;
    }
    EXPECT_GT(checked, 1000);
}

TEST(RayTraceBvh, AxisAlignedRaysAreNotDroppedByTheSlabTest) {
    // inv_dir carries infinities for these, and 0*inf is NaN. If the slab test
    // mishandles that it rejects whole subtrees and silently loses hits -- and
    // a random-direction sweep will essentially never produce an exactly
    // axis-aligned ray, so it has to be asked for directly.
    SoupModel s = random_soup(4, 50, 2024u);
    const glm::vec3 dirs[6] = {
        {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    std::mt19937 rng(31u);
    std::uniform_real_distribution<float> lat(-25.0f, 25.0f);

    int checked = 0;
    for (int i = 0; i < 600; ++i) {
        const glm::vec3 d = dirs[i % 6];
        glm::vec3 o(lat(rng), lat(rng), lat(rng));
        o -= d * 120.0f;   // start well outside, aimed straight down an axis
        auto want = brute_force_t(s, o, d, 500.0f);
        auto got = renderer::ray_trace_instance(
            s.model, glm::mat4(1.0f), o, d, 500.0f);
        ASSERT_EQ(want.has_value(), got.has_value()) << "axis ray " << i;
        if (want) EXPECT_NEAR(*want, got->t, 1e-3f) << "axis ray " << i;
        ++checked;
    }
    EXPECT_EQ(checked, 600);
}
