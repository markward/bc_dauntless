// native/tests/renderer/bridge_lighting_test.cc
//
// The bridge's single lighting path: a dull ceiling downlight scaled by the
// SDK bridge ambient, with lit surfaces held under the bloom threshold, and
// BC's baked lightmaps (the Dark slot) no longer drawn.
//
// DiffuseCeiling.* pin the CPU twin of bridge.frag's diffuse_ceiling() against
// the bloom threshold with no GL object constructed. BridgeLightingFrame.*
// render through BridgePass::render and read the pixels back; they skip
// cleanly when no GL context is available.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bloom_pass.h>
#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bridge_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <memory>
#include <stdexcept>
#include <utility>

using renderer::diffuse_ceiling;
using renderer::kBridgeLighting;

TEST(DiffuseCeiling, IdentityBelowTheKnee) {
    const glm::vec3 c{0.3f, 0.5f, 0.6f};   // max 0.6 < 0.7 * 0.88
    EXPECT_EQ(diffuse_ceiling(c, kBridgeLighting.diffuse_max), c);
}

TEST(DiffuseCeiling, NeverReachesTheBloomThreshold) {
    for (float b : {0.7f, 0.9f, 1.0f, 1.5f, 3.0f, 100.0f}) {
        const glm::vec3 out = diffuse_ceiling({b, b * 0.5f, b * 0.25f}, kBridgeLighting.diffuse_max);
        const float peak = std::max({out.r, out.g, out.b});
        // The roll is asymptotic, but in float exp() underflows for large b
        // (b = 100 gives exactly diffuse_max), so the ceiling is inclusive;
        // the invariant that matters -- strictly under bloom -- is strict.
        EXPECT_LE(peak, kBridgeLighting.diffuse_max) << b;
        EXPECT_LT(peak, renderer::kBloomThreshold) << b;
        EXPECT_LT(kBridgeLighting.diffuse_max, renderer::kBloomThreshold);
    }
}

TEST(DiffuseCeiling, HoldsHue) {
    const glm::vec3 in{2.0f, 1.0f, 0.5f};
    const glm::vec3 out = diffuse_ceiling(in, kBridgeLighting.diffuse_max);
    EXPECT_NEAR(out.g / out.r, 0.5f, 1e-5f);
    EXPECT_NEAR(out.b / out.r, 0.25f, 1e-5f);
}

TEST(DiffuseCeiling, ZeroCeilingDisables) {
    const glm::vec3 c{5.0f, 5.0f, 5.0f};
    EXPECT_EQ(diffuse_ceiling(c, 0.0f), c);
}

namespace {

constexpr int kSize = 64;

// One quad in the plane z = `z`, x in [1, 60], y in [-60, 60], with an
// authored normal `nz` (+1 floor, -1 ceiling). Wound counter-clockwise as
// seen from the side its normal faces, so the visible side is the front face.
void append_quad(assets::MeshCpu& cpu, float z, float nz) {
    const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
    const glm::vec3 corners[4] = {
        {1.0f, -60.0f, z}, {60.0f, -60.0f, z}, {60.0f, 60.0f, z}, {1.0f, 60.0f, z}};
    for (const auto& p : corners) {
        assets::MeshCpu::Vertex v;
        v.position = p;
        v.normal = {0.0f, 0.0f, nz};
        cpu.vertices.push_back(v);
    }
    if (nz > 0.0f) cpu.indices.insert(cpu.indices.end(),
                                      {base, base + 1, base + 2, base, base + 2, base + 3});
    else           cpu.indices.insert(cpu.indices.end(),
                                      {base, base + 2, base + 1, base, base + 3, base + 2});
}

GLuint black_1x1() {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const unsigned char px[4] = {0, 0, 0, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    return t;
}

class BridgeLightingFrame : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize,
                                                   "bridge-lighting-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
    }

    /// Floor quad (mesh 0, material 0) and ceiling quad (mesh 1, material 1),
    /// default materials (BridgePass's white fallback as the base texture).
    /// `dark_tex` != 0 is bound in the floor material's Dark stage.
    std::unique_ptr<assets::Model> make_model(GLuint dark_tex) {
        auto m = std::make_unique<assets::Model>();
        for (float nz : {1.0f, -1.0f}) {
            assets::MeshCpu cpu;
            append_quad(cpu, -nz, nz);   // floor at z=-1, ceiling at z=+1
            cpu.material_index = static_cast<int>(m->meshes.size());
            cpu.node_index = 0;
            m->meshes.push_back(assets::upload_mesh(cpu));
            m->materials.push_back(assets::Material{});
        }
        if (dark_tex != 0) {
            m->textures.emplace_back(dark_tex, 1u, 1u, false);
            auto& dark = m->materials[0].stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Dark)];
            dark.texture_index = 0;
            dark.uv_set = 0;
        }
        assets::Node root;
        root.name = "root";
        root.parent_index = -1;
        root.local_transform = glm::mat4(1.0f);
        root.meshes = {0, 1};
        m->nodes.push_back(std::move(root));
        m->root_node = 0;
        return m;
    }

    /// Render the scene from the origin looking along +X (floor fills the
    /// lower half, ceiling the upper) and return the 8-bit red value at the
    /// centre of each half: {floor, ceiling}.
    std::pair<int, int> render(const glm::vec3& ambient, GLuint dark_tex) {
        auto model = make_model(dark_tex);
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);

        scenegraph::Camera cam;
        cam.eye = {0.0f, 0.0f, 0.0f};
        cam.target = {10.0f, 0.0f, 0.0f};
        cam.up = {0.0f, 0.0f, 1.0f};
        cam.aspect = 1.0f;
        cam.near = 0.1f;
        cam.far = 1000.0f;

        renderer::Lighting lighting;
        lighting.ambient = ambient;

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::BridgePass pass;
        pass.render(world, cam, *p,
            [](unsigned long long h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            }, lighting);
        EXPECT_EQ(glGetError(), GL_NO_ERROR);

        unsigned char floor_px[4] = {0, 0, 0, 0};
        unsigned char ceil_px[4] = {0, 0, 0, 0};
        glReadPixels(kSize / 2, kSize / 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, floor_px);
        glReadPixels(kSize / 2, 3 * kSize / 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, ceil_px);
        return {floor_px[0], ceil_px[0]};
    }

    std::pair<int, int> render_floor_and_ceiling(const glm::vec3& ambient) {
        return render(ambient, 0);
    }

    int render_floor_with_dark_stage(GLuint dark_tex) {
        return render({0.6f, 0.6f, 0.6f}, dark_tex).first;
    }
};

}  // namespace

TEST_F(BridgeLightingFrame, FloorIsLitMoreThanCeiling) {
    auto [floor_px, ceiling_px] = render_floor_and_ceiling({0.6f, 0.6f, 0.6f});
    EXPECT_GT(floor_px, ceiling_px * 3);          // 1.0 vs 0.25 of ambient
}

TEST_F(BridgeLightingFrame, BrightAmbientNeverBlooms) {
    auto [floor_px, ceiling_px] = render_floor_and_ceiling({4.0f, 4.0f, 4.0f});
    (void)ceiling_px;
    EXPECT_LE(floor_px, static_cast<int>(255 * 0.88f) + 1);  // one 8-bit step of slack
}

TEST_F(BridgeLightingFrame, LightmapSlotIsIgnored) {
    // Same scene with a BLACK texture bound in the floor material's Dark stage:
    // the floor must be exactly as bright as without it.
    EXPECT_EQ(render_floor_with_dark_stage(black_1x1()), render_floor_with_dark_stage(0));
}
