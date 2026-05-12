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
