#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "renderer/nacelle_region.h"
#include "assets/model.h"

namespace {
// Single-node model whose vertices we control directly in body space.
void add_cpu_mesh(assets::Model& m, std::vector<glm::vec3> positions) {
    assets::MeshCpu cpu;
    for (auto& p : positions) {
        cpu.vertices.push_back({.position = p, .normal = glm::vec3(0, 0, 1)});
    }
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    int mesh_idx = static_cast<int>(m.meshes.size());
    m.meshes.push_back(std::move(mesh));
    assets::Node node;
    node.name = "root";
    node.meshes.push_back(mesh_idx);
    m.nodes.push_back(std::move(node));
    m.root_node = 0;
}
}  // namespace

TEST(NacelleRegion, FitsForeAftExtentFromTubeVertices) {
    // A tube along +Y from y=-3 to y=+5, cross-section within radius 1 of the
    // axis through center (0,0,0). Plus a far-away stray vertex OUTSIDE the
    // lateral radius that must be ignored.
    // Enough tube vertices (>= kNacelleMinCaptured=8) to trigger the mesh-fit
    // path rather than the fallback.
    assets::Model m;
    add_cpu_mesh(m, {
        {0.0f, -3.0f, 0.0f}, {0.5f,  0.0f, 0.5f}, {0.0f, 5.0f, 0.0f},
        {0.9f,  2.0f, 0.0f}, {0.0f,  1.0f, 0.0f}, {0.5f, 3.0f, 0.0f},
        {0.0f,  4.0f, 0.0f}, {0.3f, -1.0f, 0.3f}, {0.0f, -2.0f, 0.0f},
        {10.0f, 50.0f, 0.0f},   // lateral dist 10 > 1*1.25 -> ignored
    });
    auto reg = renderer::compute_nacelle_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_TRUE(reg.active);
    EXPECT_NEAR(reg.aft, -3.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, 5.0f, 1e-4f);
    EXPECT_NEAR(reg.radius, 1.25f, 1e-4f);  // widened
}

TEST(NacelleRegion, FallsBackToFormulaWhenCaptureDegenerate) {
    // No vertices near the axis -> fewer than kNacelleMinCaptured captured.
    assets::Model m;
    add_cpu_mesh(m, {{100.0f, 0.0f, 0.0f}, {100.0f, 1.0f, 0.0f}});
    auto reg = renderer::compute_nacelle_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 2.0f);
    EXPECT_TRUE(reg.active);
    const float widened = 2.0f * renderer::kNacelleRadiusWiden;
    const float half = renderer::kNacelleFallbackHalfLenFactor * widened;
    EXPECT_NEAR(reg.fore, half, 1e-4f);
    EXPECT_NEAR(reg.aft, -half, 1e-4f);
}

TEST(NacelleRegion, NonZeroCenterAxialProjectionsRelativeToCenter) {
    // Tube vertices span world-Y from -1 to +7. Center is at Y=2.
    // Axial projections (relative to center) are therefore:
    //   aft  = (-1) - 2 = -3
    //   fore = (+7) - 2 = +5
    // All vertices have |x|,|z| <= 0.9, well within the widened radius
    // (1.0 * kNacelleRadiusWiden = 1.25). Enough vertices (>= 8) to
    // use the mesh-fit path, not the fallback.
    assets::Model m;
    add_cpu_mesh(m, {
        {0.0f, -1.0f, 0.0f}, {0.5f,  0.0f, 0.5f}, {0.0f,  7.0f, 0.0f},
        {0.9f,  3.0f, 0.0f}, {0.0f,  2.0f, 0.0f}, {0.5f,  4.0f, 0.0f},
        {0.0f,  5.0f, 0.0f}, {0.3f,  1.0f, 0.3f}, {0.0f,  6.0f, 0.0f},
    });
    const glm::vec3 center(0.0f, 2.0f, 0.0f);
    const glm::vec3 axis(0.0f, 1.0f, 0.0f);
    auto reg = renderer::compute_nacelle_region(m, center, axis, 1.0f);
    EXPECT_TRUE(reg.active);
    // aft and fore are axial projections relative to center
    EXPECT_NEAR(reg.aft,  -3.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, +5.0f, 1e-4f);
}

TEST(NacelleRegion, MultiNodeComposesChildTranslation) {
    // Root node (identity, no meshes). Child node translated +4 along Y,
    // carrying a mesh whose local vertices span Y from -2 to +3.
    // After composition the world positions span Y from 2 to 7.
    // Without node-world composition (i.e. if the child were treated as
    // root) the raw local Y range would be -2..+3 instead of 2..+7 --
    // so the correct aft/fore distinguish the two cases unambiguously.
    // center=(0,0,0), axis=(0,1,0), radius=1.0. All x,z <= 0.5.
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {},
    });
    m.nodes.push_back(assets::Node{
        .name = "child", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 4.0f, 0.0f)),
        .meshes = {0},
    });
    m.root_node = 0;
    // Add mesh 0: local vertices Y in [-2, +3], all within lateral radius.
    assets::MeshCpu cpu;
    const std::vector<glm::vec3> local_pts = {
        {0.0f, -2.0f, 0.0f}, {0.5f, -1.0f, 0.0f}, {0.0f,  0.0f, 0.0f},
        {0.5f,  1.0f, 0.0f}, {0.0f,  2.0f, 0.0f}, {0.5f,  3.0f, 0.0f},
        {0.0f,  1.5f, 0.0f}, {0.5f,  0.5f, 0.5f},
    };
    for (const auto& p : local_pts) {
        cpu.vertices.push_back({.position = p, .normal = glm::vec3(0, 0, 1)});
    }
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    auto reg = renderer::compute_nacelle_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_TRUE(reg.active);
    // World Y after +4 translation: -2+4=2 to 3+4=7 -> aft=2, fore=7
    EXPECT_NEAR(reg.aft,  2.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, 7.0f, 1e-4f);
}
