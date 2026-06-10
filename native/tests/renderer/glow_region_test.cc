#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "renderer/glow_region.h"
#include "assets/model.h"
#include "scenegraph/instance.h"

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

TEST(GlowRegion, FitsForeAftExtentFromTubeVertices) {
    // A tube along +Y from y=-3 to y=+5, cross-section within radius 1 of the
    // axis through center (0,0,0). Plus a far-away stray vertex OUTSIDE the
    // lateral radius that must be ignored.
    // Enough tube vertices (>= kGlowCapsuleMinCaptured=8) to trigger the mesh-fit
    // path rather than the fallback.
    assets::Model m;
    add_cpu_mesh(m, {
        {0.0f, -3.0f, 0.0f}, {0.5f,  0.0f, 0.5f}, {0.0f, 5.0f, 0.0f},
        {0.9f,  2.0f, 0.0f}, {0.0f,  1.0f, 0.0f}, {0.5f, 3.0f, 0.0f},
        {0.0f,  4.0f, 0.0f}, {0.3f, -1.0f, 0.3f}, {0.0f, -2.0f, 0.0f},
        {10.0f, 50.0f, 0.0f},   // lateral dist 10 > 1*1.25 -> ignored
    });
    auto reg = renderer::compute_capsule_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_TRUE(reg.active);
    EXPECT_NEAR(reg.aft, -3.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, 5.0f, 1e-4f);
    EXPECT_NEAR(reg.radius, 1.25f, 1e-4f);  // widened
}

TEST(GlowRegion, FallsBackToFormulaWhenCaptureDegenerate) {
    // No vertices near the axis -> fewer than kGlowCapsuleMinCaptured captured.
    assets::Model m;
    add_cpu_mesh(m, {{100.0f, 0.0f, 0.0f}, {100.0f, 1.0f, 0.0f}});
    auto reg = renderer::compute_capsule_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 2.0f);
    EXPECT_TRUE(reg.active);
    const float widened = 2.0f * renderer::kGlowCapsuleRadiusWiden;
    const float half = renderer::kGlowCapsuleFallbackHalfLenFactor * widened;
    EXPECT_NEAR(reg.fore, half, 1e-4f);
    EXPECT_NEAR(reg.aft, -half, 1e-4f);
}

TEST(GlowRegion, NonZeroCenterAxialProjectionsRelativeToCenter) {
    // Tube vertices span world-Y from -1 to +7. Center is at Y=2.
    // Axial projections (relative to center) are therefore:
    //   aft  = (-1) - 2 = -3
    //   fore = (+7) - 2 = +5
    // All vertices have |x|,|z| <= 0.9, well within the widened radius
    // (1.0 * kGlowCapsuleRadiusWiden = 1.25). Enough vertices (>= 8) to
    // use the mesh-fit path, not the fallback.
    assets::Model m;
    add_cpu_mesh(m, {
        {0.0f, -1.0f, 0.0f}, {0.5f,  0.0f, 0.5f}, {0.0f,  7.0f, 0.0f},
        {0.9f,  3.0f, 0.0f}, {0.0f,  2.0f, 0.0f}, {0.5f,  4.0f, 0.0f},
        {0.0f,  5.0f, 0.0f}, {0.3f,  1.0f, 0.3f}, {0.0f,  6.0f, 0.0f},
    });
    const glm::vec3 center(0.0f, 2.0f, 0.0f);
    const glm::vec3 axis(0.0f, 1.0f, 0.0f);
    auto reg = renderer::compute_capsule_region(m, center, axis, 1.0f);
    EXPECT_TRUE(reg.active);
    // aft and fore are axial projections relative to center
    EXPECT_NEAR(reg.aft,  -3.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, +5.0f, 1e-4f);
}

// ─────────────────────────────────────────────────────────────────────────────
// Production-path safety lock for the warp-nacelle glow-dimming feature.
//
// The feature's core safety guarantee is that an instance with NO active
// nacelle capsule contributes ZERO nacelle effect: frame.cc counts active
// nacelles into `nn`, calls `set_int("u_glow_region_count", nn)`, and the shader's
// `if (u_glow_region_count > 0)` skips the whole nacelle block. When nn == 0 the
// glow term is byte-identical to before the feature existed.
//
// The frame_test.cc harness CANNOT lock this directly: it needs real BC assets
// (GTEST_SKIP otherwise) and a GL context, and there is no uniform readback
// path (Shader::set_int has no getter), so "assert u_glow_region_count == 0" is not
// observable through that harness. These two CPU tests lock the guarantee at the
// data level — no GL, no assets, fully deterministic — by testing the REAL code
// that makes nn == 0 in production: the default member initializers on
// Instance::GlowRegion / Instance::glow_regions.

// Lock #1 — the REAL invariant: a default-constructed Instance (i.e. every
// production ship the moment it is created, before any nacelle is fitted) has
// ALL nacelle slots inactive. This is the property the `if (!n.active) continue`
// in frame.cc relies on to keep nn == 0. If a future edit changed Nacelle's
// default to active = true, nn would become nonzero for untouched instances and
// the production glow path would silently change — this test would catch it.
TEST(GlowRegionProductionPath, DefaultInstanceHasNoActiveNacelles) {
    scenegraph::Instance inst{};  // exactly what World::create_instance yields
    for (std::size_t i = 0; i < scenegraph::Instance::kMaxGlowRegions; ++i) {
        EXPECT_FALSE(inst.glow_regions[i].active)
            << "nacelle slot " << i << " defaulted to active; a production "
               "instance must have zero active nacelles so frame.cc sets "
               "u_glow_region_count == 0 and the glow path stays byte-identical";
    }
}

// Lock #2 — replicate frame.cc's exact active-count loop over the default array
// and assert it yields 0, documenting that an all-inactive instance produces
// u_glow_region_count == 0 (the value the shader treats as "skip the nacelle block
// entirely"). The loop body below is a faithful copy of frame.cc's draw_model
// counting loop (skip `!active`, else `++nn`).
TEST(GlowRegionProductionPath, ActiveCountLoopYieldsZeroForDefaultInstance) {
    scenegraph::Instance inst{};
    int nn = 0;
    for (const auto& n : inst.glow_regions) {  // mirrors frame.cc draw_model
        if (!n.active) continue;
        ++nn;
    }
    EXPECT_EQ(nn, 0)
        << "frame.cc would set u_glow_region_count == " << nn << " for a default "
           "instance; it must be 0 so the shader skips the nacelle block and "
           "the production glow term is unchanged by this feature";
}

TEST(GlowRegion, MultiNodeComposesChildTranslation) {
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

    auto reg = renderer::compute_capsule_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_TRUE(reg.active);
    // World Y after +4 translation: -2+4=2 to 3+4=7 -> aft=2, fore=7
    EXPECT_NEAR(reg.aft,  2.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, 7.0f, 1e-4f);
}
