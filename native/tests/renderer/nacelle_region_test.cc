#include <gtest/gtest.h>
#include <glm/glm.hpp>
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
