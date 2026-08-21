#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "renderer/aabb.h"
#include "assets/model.h"

TEST(Aabb, ComputesCenterAndHalfExtentsFromVertexPositions) {
    std::vector<glm::vec3> verts = {
        {-1.0f, -2.0f, -3.0f},
        { 4.0f,  6.0f,  9.0f},
        { 0.0f,  0.0f,  0.0f},
    };
    renderer::Aabb box = renderer::compute_aabb(verts);
    EXPECT_FLOAT_EQ(box.center.x, 1.5f);
    EXPECT_FLOAT_EQ(box.center.y, 2.0f);
    EXPECT_FLOAT_EQ(box.center.z, 3.0f);
    EXPECT_FLOAT_EQ(box.half_extents.x, 2.5f);
    EXPECT_FLOAT_EQ(box.half_extents.y, 4.0f);
    EXPECT_FLOAT_EQ(box.half_extents.z, 6.0f);
}

TEST(Aabb, EmptyVertexListReturnsZeroBox) {
    std::vector<glm::vec3> verts;
    renderer::Aabb box = renderer::compute_aabb(verts);
    EXPECT_EQ(box.center, glm::vec3(0.0f));
    EXPECT_EQ(box.half_extents, glm::vec3(0.0f));
}

// ── compute_model_aabb walks node hierarchy ──

namespace {
void add_cpu_mesh(assets::Model& m, std::vector<glm::vec3> positions) {
    assets::MeshCpu cpu;
    for (auto& p : positions) {
        cpu.vertices.push_back({.position = p, .normal = glm::vec3(0, 0, 1)});
    }
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
}
}

TEST(ComputeModelAabb, AppliesNodeLocalTransforms) {
    // Two meshes, each a single point at NIF-local origin (0,0,0).
    // Mesh 0 lives under root (identity). Mesh 1 lives under a child
    // node translated to (10, 0, 0). Without walking the hierarchy,
    // both points are at origin → AABB center (0,0,0), half (0,0,0).
    // With hierarchy: points at (0,0,0) and (10,0,0) → center (5,0,0),
    // half (5,0,0).
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0},
    });
    m.nodes.push_back(assets::Node{
        .name = "child", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)),
        .meshes = {1},
    });
    add_cpu_mesh(m, {{0, 0, 0}});
    add_cpu_mesh(m, {{0, 0, 0}});

    renderer::Aabb box = renderer::compute_model_aabb(m);
    EXPECT_FLOAT_EQ(box.center.x, 5.0f);
    EXPECT_FLOAT_EQ(box.half_extents.x, 5.0f);
}

TEST(ComputeModelAabb, EmptyModelReturnsZero) {
    assets::Model m;
    renderer::Aabb box = renderer::compute_model_aabb(m);
    EXPECT_EQ(box.center, glm::vec3(0.0f));
    EXPECT_EQ(box.half_extents, glm::vec3(0.0f));
}

TEST(ComputeModelAabb, SkipsMeshesWithoutCpuData) {
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1, .meshes = {0},
    });
    m.meshes.emplace_back();  // GL-only mesh, cpu_data is nullopt
    renderer::Aabb box = renderer::compute_model_aabb(m);
    EXPECT_EQ(box.center, glm::vec3(0.0f));
    EXPECT_EQ(box.half_extents, glm::vec3(0.0f));
}

// ── compute_model_bounds: the leaf spheres a shape-aware test descends ──
//
// These used to be the AUTHORED per-NiTriShapeData spheres, one per mesh. Both
// halves of that turned out to be too coarse, measured with
// native/tools/dump_bounds:
//
//   * The authored sphere is fitted around the shape's AABB CENTRE, so on the
//     flat plates BC models are made of it is 5-22x looser than the geometry in
//     the thin direction. Galaxy's saucer shapes: half-extents (232, 96, 13),
//     sphere radius 251 -- 19x the plate's thickness. FedStarbase's mushroom
//     cap: half (93, 15, 93) GU, sphere radius 94 GU, so it claims 94 GU of
//     empty space BELOW a cap that is 15 GU thick.
//   * One sphere per mesh is not one sphere per PIECE. Three of FedStarbase's
//     five shapes each span the whole station (half-extents up to
//     (96, 161, 97) GU), so no per-mesh bound of any shape could open up the
//     volume under the mushroom.
//
// So the pieces are derived from the triangles instead: split the model's
// triangle soup spatially and bound each leaf. Spheres stay the primitive
// because every consumer already does sphere maths, and a leaf's sphere slack
// is small in absolute terms precisely because the leaf is small.

namespace {
/// A mesh of `count` unit triangles clustered around `center`.
void add_triangle_cluster(assets::Model& m, glm::vec3 center, int count,
                          float spread = 1.0f) {
    assets::MeshCpu cpu;
    for (int i = 0; i < count; ++i) {
        const float t = spread * static_cast<float>(i) / static_cast<float>(count);
        const glm::vec3 base = center + glm::vec3(t, 0.0f, 0.0f);
        const std::uint32_t v0 = static_cast<std::uint32_t>(cpu.vertices.size());
        cpu.vertices.push_back({.position = base, .normal = glm::vec3(0, 0, 1)});
        cpu.vertices.push_back({.position = base + glm::vec3(0.1f, 0, 0),
                                .normal = glm::vec3(0, 0, 1)});
        cpu.vertices.push_back({.position = base + glm::vec3(0, 0.1f, 0),
                                .normal = glm::vec3(0, 0, 1)});
        cpu.indices.insert(cpu.indices.end(), {v0, v0 + 1, v0 + 2});
    }
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
}

bool inside_any(const std::vector<renderer::BoundSphere>& spheres, glm::vec3 p) {
    for (const auto& s : spheres) {
        if (glm::length(p - s.center) <= s.radius) return true;
    }
    return false;
}

assets::Model one_node_model() {
    assets::Model m;
    m.root_node = 0;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
    });
    return m;
}
}  // namespace

TEST(ComputeModelBounds, SplitsOneMeshThatSpansAGap) {
    // THE case, in miniature. A single mesh with triangles at both ends and
    // nothing between them -- a starbase's mushroom cap over its base. One
    // bound per mesh swallows the gap whole; the pieces must leave it empty,
    // or the player cannot fly into it.
    assets::Model m = one_node_model();
    add_triangle_cluster(m, {-100.0f, 0.0f, 0.0f}, 64);
    add_triangle_cluster(m, {100.0f, 0.0f, 0.0f}, 64);
    m.nodes[0].meshes = {0, 1};

    auto spheres = renderer::compute_model_bounds(m);

    ASSERT_GE(spheres.size(), 2u);
    EXPECT_FALSE(inside_any(spheres, glm::vec3(0.0f, 0.0f, 0.0f)))
        << "the gap between the clusters must be free space";
    EXPECT_TRUE(inside_any(spheres, glm::vec3(-100.0f, 0.0f, 0.0f)));
    EXPECT_TRUE(inside_any(spheres, glm::vec3(100.0f, 0.0f, 0.0f)));
}

TEST(ComputeModelBounds, SplitsASingleMeshSpanningTheWholeModel) {
    // Not a gap between MESHES -- a gap inside ONE mesh, which is what
    // FedStarbase actually has: shape 0 alone spans the entire station, so
    // subdividing per-mesh could never open the volume under the cap.
    assets::Model m = one_node_model();
    m.nodes[0].meshes = {0};
    assets::MeshCpu cpu;
    auto push_tri = [&cpu](glm::vec3 at) {
        const std::uint32_t v0 = static_cast<std::uint32_t>(cpu.vertices.size());
        cpu.vertices.push_back({.position = at, .normal = glm::vec3(0, 0, 1)});
        cpu.vertices.push_back({.position = at + glm::vec3(0.1f, 0, 0),
                                .normal = glm::vec3(0, 0, 1)});
        cpu.vertices.push_back({.position = at + glm::vec3(0, 0.1f, 0),
                                .normal = glm::vec3(0, 0, 1)});
        cpu.indices.insert(cpu.indices.end(), {v0, v0 + 1, v0 + 2});
    };
    for (int i = 0; i < 64; ++i) push_tri({-100.0f, float(i) * 0.1f, 0.0f});
    for (int i = 0; i < 64; ++i) push_tri({100.0f, float(i) * 0.1f, 0.0f});
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    auto spheres = renderer::compute_model_bounds(m);

    ASSERT_GE(spheres.size(), 2u);
    EXPECT_FALSE(inside_any(spheres, glm::vec3(0.0f, 0.0f, 0.0f)));
}

TEST(ComputeModelBounds, LeavesACompactMeshWhole) {
    // Subdivision is not free -- every leaf is another sphere the Python
    // narrow phase and collision_avoidance iterate each tick. A blob with
    // nothing to separate must not be shredded into dozens of them.
    assets::Model m = one_node_model();
    add_triangle_cluster(m, {0.0f, 0.0f, 0.0f}, 8);
    m.nodes[0].meshes = {0};

    auto spheres = renderer::compute_model_bounds(m);
    EXPECT_EQ(spheres.size(), 1u);
}

TEST(ComputeModelBounds, StaysWithinTheLeafBudget) {
    // The budget is what keeps the per-tick cost bounded for a dense hull.
    assets::Model m = one_node_model();
    for (int i = 0; i < 16; ++i) {
        add_triangle_cluster(m, {float(i) * 50.0f, 0.0f, 0.0f}, 256, 20.0f);
        m.nodes[0].meshes.push_back(i);
    }

    auto spheres = renderer::compute_model_bounds(m);
    EXPECT_LE(spheres.size(), std::size_t(renderer::kMaxHullBoundLeaves));
    EXPECT_GT(spheres.size(), 1u);
}

TEST(ComputeModelBounds, AppliesNodeLocalTransforms) {
    // A child node offset by 100 must move its triangles with it, or every
    // piece collapses onto the root.
    assets::Model m = one_node_model();
    m.nodes[0].meshes = {0};
    m.nodes.push_back(assets::Node{
        .name = "child", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(100, 0, 0)),
        .meshes = {1},
    });
    add_triangle_cluster(m, {0, 0, 0}, 64);
    add_triangle_cluster(m, {0, 0, 0}, 64);

    auto spheres = renderer::compute_model_bounds(m);

    ASSERT_GE(spheres.size(), 2u);
    EXPECT_TRUE(inside_any(spheres, glm::vec3(0.0f, 0.0f, 0.0f)));
    EXPECT_TRUE(inside_any(spheres, glm::vec3(100.0f, 0.0f, 0.0f)));
    EXPECT_FALSE(inside_any(spheres, glm::vec3(50.0f, 0.0f, 0.0f)));
}

TEST(ComputeModelBounds, ScalesWithNodeScale) {
    assets::Model m = one_node_model();
    m.nodes[0].local_transform = glm::scale(glm::mat4(1.0f), glm::vec3(3.0f));
    m.nodes[0].meshes = {0};
    add_triangle_cluster(m, {0, 0, 0}, 8, 2.0f);

    auto spheres = renderer::compute_model_bounds(m);
    ASSERT_EQ(spheres.size(), 1u);
    // The cluster spans 2 units before scaling, 6 after; the leaf sphere has
    // to grow with it rather than describe a region the hull outgrew.
    EXPECT_GT(spheres[0].radius, 2.0f);
}

TEST(ComputeModelBounds, SkipsMeshesWithoutCpuData) {
    assets::Model m = one_node_model();
    m.nodes[0].meshes = {0, 1};
    add_triangle_cluster(m, {0, 0, 0}, 8);
    m.meshes.push_back(assets::Mesh{});          // GL-only, cpu_data is nullopt

    auto spheres = renderer::compute_model_bounds(m);
    EXPECT_EQ(spheres.size(), 1u);
}

TEST(ComputeModelBounds, IgnoresMeshesWithNoTriangles) {
    // Vertices with no index buffer draw nothing and bound nothing; admitting
    // them would create phantom point-obstacles.
    assets::Model m = one_node_model();
    m.nodes[0].meshes = {0};
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = {5, 0, 0}, .normal = glm::vec3(0, 0, 1)});
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    EXPECT_TRUE(renderer::compute_model_bounds(m).empty());
}

TEST(ComputeModelBounds, EmptyModelReturnsNothing) {
    assets::Model m;
    EXPECT_TRUE(renderer::compute_model_bounds(m).empty());
}
