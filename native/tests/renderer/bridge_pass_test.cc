// native/tests/renderer/bridge_pass_test.cc
//
// BridgePassPartitioning: CPU-side, BridgePass's instance walk only sees
// bridge-tagged instances. BridgePassTest: through the real bridge.frag (a
// hidden window; skips cleanly without a GL context), a Bridge Lottie panel's
// live texture replaces the still on draw (spec
// 2026-10-28-bridge-lottie-panels-design.md §4-6), and a room with no panel
// sources renders byte-identically whether or not the panels update.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include "bridge_test_room.h"

#include <renderer/bridge_pass.h>
#include <renderer/bridge_quality.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>

#include <glm/glm.hpp>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace {

assets::Mesh make_stub_mesh(int material_index) {
    return assets::Mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0,
                        /*index_count=*/3, material_index, /*node_index=*/0);
}

}  // namespace

TEST(BridgePassPartitioning, SkipsNonBridgePassInstances) {
    assets::Model model;
    model.materials.push_back(assets::Material{});
    model.meshes.push_back(make_stub_mesh(0));
    assets::Node root;
    root.meshes = {0};
    model.nodes.push_back(std::move(root));
    model.root_node = 0;

    scenegraph::World world;
    auto h = reinterpret_cast<scenegraph::ModelHandle>(&model);
    auto iid_space = world.create_instance(h);   // default Pass::Space
    auto iid_bridge = world.create_instance(h);
    world.set_pass(iid_bridge, scenegraph::Pass::Bridge);
    (void)iid_space;

    int count = 0;
    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 1);  // only the bridge-tagged instance
}

namespace {

namespace fs = std::filesystem;
using namespace std::chrono_literals;

constexpr int kWin = 128;

int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return static_cast<int>(::getpid());
#endif
}

scenegraph::Camera corner_camera() {
    scenegraph::Camera cam;
    cam.eye = {60.0f, 0.0f, 90.0f};
    cam.target = {25.0f, 0.0f, 0.0f};
    cam.up = {0.0f, 0.0f, 1.0f};
    cam.aspect = 1.0f;
    cam.near = 0.5f;
    cam.far = 2000.0f;
    return cam;
}

class BridgePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    renderer::HdrTarget target;
    fs::path dir;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kWin, kWin, "bridge-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        auto base = fs::temp_directory_path() / "bridge-pass-panels";
        for (int i = 0;; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(current_pid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { dir = candidate; break; }
        }
        fs::create_directories(dir);
    }

    void TearDown() override {
        std::error_code ec;
        if (!dir.empty()) fs::remove_all(dir, ec);
    }

    std::unique_ptr<renderer::BridgePass> make_pass() const {
        auto pass = std::make_unique<renderer::BridgePass>();
        pass->set_ao_enabled(false);
        return pass;
    }

    /// One main-bridge frame of `model`; the whole RGBA float framebuffer.
    std::vector<float> render(renderer::BridgePass& pass, const assets::Model& model) {
        scenegraph::World world;
        auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&model));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        renderer::Lighting lighting;
        lighting.ambient = {0.6f, 0.6f, 0.6f};
        target.resize(kWin, kWin);
        target.bind();
        glViewport(0, 0, kWin, kWin);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass.render(world, corner_camera(), *p, bridge_test_room::lookup_fn, lighting);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kWin) * kWin * 4);
        glReadPixels(0, 0, kWin, kWin, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    }

    /// Mean RGB of a 9x9 block on the open floor, (70, 0, 0).
    static glm::vec3 floor_rgb(const std::vector<float>& px) {
        const scenegraph::Camera cam = corner_camera();
        const glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() *
                               glm::vec4(70.0f, 0.0f, 0.0f, 1.0f);
        const glm::vec2 ndc = glm::vec2(clip) / clip.w;
        const int cx = static_cast<int>((ndc.x * 0.5f + 0.5f) * kWin);
        const int cy = static_cast<int>((ndc.y * 0.5f + 0.5f) * kWin);
        glm::vec3 sum(0.0f);
        for (int y = cy - 4; y <= cy + 4; ++y)
            for (int x = cx - 4; x <= cx + 4; ++x) {
                const std::size_t i = (static_cast<std::size_t>(y) * kWin + x) * 4;
                sum += glm::vec3(px[i], px[i + 1], px[i + 2]);
            }
        return sum / 81.0f;
    }
};

}  // namespace

// The corner's floor carries a blue still, a grey `_emissive` stage and a
// panel whose solid_red.json sits beside the still. Before the panel is live
// the floor is the still plus the glow; once it is, the floor is the panel's
// red and the glow is gone (green and blue would carry the grey's 0.5).
TEST_F(BridgePassTest, LivePanelReplacesTheStillAndDropsEmissive) {
    auto model = bridge_test_room::make_two_mesh_corner({0.0f, 0.0f, 1.0f},
                                                        {0.6f, 0.6f, 0.6f});
    const fs::path albedo = dir / "hull.tga";
    {
        std::vector<std::uint8_t> tga = {0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                         1, 0, 1, 0, 24, 0, 0xFF, 0x00, 0x00};
        std::ofstream(albedo, std::ios::binary)
            .write(reinterpret_cast<const char*>(tga.data()),
                   static_cast<std::streamsize>(tga.size()));
    }
    fs::copy_file(fs::path(LOTTIE_FIXTURES) / "solid_red.json", dir / "hull.json");
    model->textures.push_back(bridge_test_room::solid_1x1({0.5f, 0.5f, 0.5f, 1.0f}));
    auto& mat = model->materials[0];
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Emissive)].texture_index =
        static_cast<int>(model->textures.size()) - 1;
    model->panel_sources.push_back(assets::PanelSource{albedo, {dir}, 0});
    mat.panel_index = 0;

    auto pass = make_pass();
    const glm::vec3 still = floor_rgb(render(*pass, *model));
    ASSERT_GT(still.b, 0.5f);   // blue still + grey glow
    ASSERT_GT(still.g, 0.4f);   // the glow

    glm::vec3 c = still;
    const auto deadline = std::chrono::steady_clock::now() + 2000ms;
    while (std::chrono::steady_clock::now() < deadline) {
        pass->update_panels(renderer::BridgeQuality::Medium);
        c = floor_rgb(render(*pass, *model));
        if (c.r > 0.1f && c.b < 0.1f) break;
        std::this_thread::sleep_for(5ms);
    }
    EXPECT_GT(c.r, 0.1f);
    EXPECT_LT(c.g, 0.01f);   // no emissive term
    EXPECT_LT(c.b, 0.01f);   // no still
}

// A room with no panel sources: the frames are the same bytes whether or not
// update_panels runs between them.
TEST_F(BridgePassTest, NoPanelSourcesRendersByteIdentically) {
    auto model = bridge_test_room::make_two_mesh_corner({0.6f, 0.5f, 0.4f},
                                                        {0.8f, 0.1f, 0.1f});
    auto plain = make_pass();
    auto updated = make_pass();
    std::vector<float> a, b;
    for (int i = 0; i < 3; ++i) {
        a = render(*plain, *model);
        updated->update_panels(renderer::BridgeQuality::Medium);
        b = render(*updated, *model);
        updated->update_panels(renderer::BridgeQuality::Medium);
    }
    ASSERT_EQ(a.size(), b.size());
    EXPECT_EQ(a, b);
}
