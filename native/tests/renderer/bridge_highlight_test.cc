// native/tests/renderer/bridge_highlight_test.cc
//
// Bridge editor selection tint (spec 2026-10-08-bridge-emitters §4): the
// selected mesh of the selected model is tinted toward cyan, a hovered one
// faintly, every other draw untouched. Skips cleanly without a GL context.
// (includes: as bridge_ao_test.cc)
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bridge_pass.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {

constexpr int kWin = 256;

// One quad from four corners with an authored normal `n`, wound
// counter-clockwise as seen from the side the normal faces.
void append_quad(assets::MeshCpu& cpu, const glm::vec3 (&c)[4], const glm::vec3& n) {
    const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
    for (const auto& p : c) {
        assets::MeshCpu::Vertex v;
        v.position = p;
        v.normal = n;
        cpu.vertices.push_back(v);
    }
    if (glm::dot(glm::cross(c[1] - c[0], c[2] - c[0]), n) >= 0.0f)
        cpu.indices.insert(cpu.indices.end(), {base, base + 1, base + 2, base, base + 2, base + 3});
    else
        cpu.indices.insert(cpu.indices.end(), {base, base + 2, base + 1, base, base + 3, base + 2});
}

// Floor z = 0 (x >= 0, normal +Z) and wall x = 0 (z >= 0, normal +X).
std::unique_ptr<assets::Model> make_corner() {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 floor_c[4] = {{0, -L, 0}, {L, -L, 0}, {L, L, 0}, {0, L, 0}};
    const glm::vec3 wall_c[4]  = {{0, -L, 0}, {0, L, 0}, {0, L, L}, {0, -L, L}};
    assets::MeshCpu cpu;
    append_quad(cpu, floor_c, {0, 0, 1});
    append_quad(cpu, wall_c, {1, 0, 0});
    cpu.material_index = 0;
    cpu.node_index = 0;
    m->meshes.push_back(assets::upload_mesh(cpu));
    m->materials.push_back(assets::Material{});
    assets::Node root;
    root.name = "root";
    root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    root.meshes = {0};
    m->nodes.push_back(std::move(root));
    m->root_node = 0;
    return m;
}

scenegraph::Camera corner_camera(int w, int h) {
    scenegraph::Camera cam;
    cam.eye = {60.0f, 0.0f, 90.0f};
    cam.target = {25.0f, 0.0f, 0.0f};
    cam.up = {0.0f, 0.0f, 1.0f};
    cam.aspect = static_cast<float>(w) / static_cast<float>(h);
    cam.near = 0.5f;
    cam.far = 2000.0f;
    return cam;
}

const assets::Model* lookup_fn(unsigned long long h) {
    return reinterpret_cast<const assets::Model*>(h);
}

class BridgeHighlightFrame : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<renderer::BridgePass> pass;
    std::unique_ptr<assets::Model> model;
    renderer::HdrTarget target;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kWin, kWin, "bridge-highlight-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        pass = std::make_unique<renderer::BridgePass>();
        pass->set_ao_enabled(false);
        model = make_corner();
    }

    /// Mean RGB over a 9x9 block centred on the open floor.
    glm::vec3 render_floor() {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        const scenegraph::Camera cam = corner_camera(kWin, kWin);
        renderer::Lighting lighting;
        lighting.ambient = {0.6f, 0.6f, 0.6f};
        target.resize(kWin, kWin);
        target.bind();
        glViewport(0, 0, kWin, kWin);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass->render(world, cam, *p, lookup_fn, lighting, scenegraph::Pass::Bridge, 0);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kWin) * kWin * 4);
        glReadPixels(0, 0, kWin, kWin, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        const glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() *
                               glm::vec4(70.0f, 0.0f, 0.0f, 1.0f);
        const glm::vec2 ndc = glm::vec2(clip) / clip.w;
        const int cx = static_cast<int>((ndc.x * 0.5f + 0.5f) * kWin);
        const int cy = static_cast<int>((ndc.y * 0.5f + 0.5f) * kWin);
        glm::vec3 sum(0.0f);
        int n = 0;
        for (int y = cy - 4; y <= cy + 4; ++y)
            for (int x = cx - 4; x <= cx + 4; ++x) {
                const std::size_t i = (static_cast<std::size_t>(y) * kWin + x) * 4;
                sum += glm::vec3(px[i], px[i + 1], px[i + 2]);
                ++n;
            }
        return sum / static_cast<float>(n);
    }

    unsigned long long handle() const {
        return reinterpret_cast<unsigned long long>(model.get());
    }
};

}  // namespace

TEST_F(BridgeHighlightFrame, NoHighlightIsTheLitColour) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), -1, -1);
    const glm::vec3 none = render_floor();
    EXPECT_EQ(plain, none);
}

TEST_F(BridgeHighlightFrame, SelectedMeshIsTintedTowardCyan) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), 0, -1);
    const glm::vec3 sel = render_floor();
    EXPECT_GT(sel.b - sel.r, plain.b - plain.r + 0.05f);
}

TEST_F(BridgeHighlightFrame, HoverIsFainterThanSelection) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), -1, 0);
    const glm::vec3 hov = render_floor();
    pass->set_highlight(handle(), 0, -1);
    const glm::vec3 sel = render_floor();
    EXPECT_GT(hov.b - hov.r, plain.b - plain.r + 0.01f);
    EXPECT_LT(hov.b - hov.r, sel.b - sel.r);
}

TEST_F(BridgeHighlightFrame, AnotherModelsMeshIndexDoesNotTint) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle() + 1, 0, 0);   // a different model handle
    EXPECT_EQ(render_floor(), plain);
    pass->clear_highlight();
    EXPECT_EQ(render_floor(), plain);
}
