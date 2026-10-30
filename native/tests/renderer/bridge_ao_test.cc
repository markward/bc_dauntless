// native/tests/renderer/bridge_ao_test.cc
//
// Screen-space ambient occlusion on the bridge's received light
// (BridgeAoPass). A synthetic L-shaped corner -- floor + wall meeting at
// x = 0, authored normals -- is drawn through BridgePass::render into an
// offscreen target and read back: the floor next to the wall must be darker
// than the open floor, the comm-set render must never see AO, and the AO must
// survive a viewport resize between frames. Every test skips cleanly when no
// GL context is available.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bridge_ao_pass.h>
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

#include <cmath>
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

// A 1.5-unit step, the depth of the DBridge side-panel frame: low floor
// z = 0 (x >= 0), riser x = 0 (normal +X), raised floor z = 1.5 (x < 0).
constexpr float kStepH = 1.5f;
std::unique_ptr<assets::Model> make_step() {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 low_c[4]   = {{0, -L, 0}, {L, -L, 0}, {L, L, 0}, {0, L, 0}};
    const glm::vec3 riser_c[4] = {{0, -L, 0}, {0, L, 0}, {0, L, kStepH}, {0, -L, kStepH}};
    const glm::vec3 high_c[4]  = {{-L, -L, kStepH}, {0, -L, kStepH}, {0, L, kStepH}, {-L, L, kStepH}};
    assets::MeshCpu cpu;
    append_quad(cpu, low_c, {0, 0, 1});
    append_quad(cpu, riser_c, {1, 0, 0});
    append_quad(cpu, high_c, {0, 0, 1});
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
const glm::vec3 kStepFoot{1.3f, 0.0f, 0.0f};   // low floor beside the riser, clear of the AO filter's bleed off the riser itself
const glm::vec3 kStepOpen{12.0f, 0.0f, 0.0f};  // low floor, clear of the step

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

const glm::vec3 kNearCorner{6.0f, 0.0f, 0.0f};   // floor, beside the wall
const glm::vec3 kOpenFloor{70.0f, 0.0f, 0.0f};   // floor, far from the wall

struct CornerImage {
    float near_corner = 0.0f;
    float open_floor = 0.0f;
};

const assets::Model* lookup_fn(unsigned long long h) {
    return reinterpret_cast<const assets::Model*>(h);
}

class BridgeAoFrame : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<renderer::BridgePass> pass;   // persists across frames
    std::unique_ptr<assets::Model> model;
    renderer::HdrTarget target;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kWin, kWin, "bridge-ao-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        pass = std::make_unique<renderer::BridgePass>();
        model = make_corner();
    }

    /// Mean red over a 9x9 block centred on the projection of `world_pt`.
    static float block_mean(const std::vector<float>& px, int vw, int vh,
                            const scenegraph::Camera& cam, const glm::vec3& world_pt) {
        const glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() * glm::vec4(world_pt, 1.0f);
        const glm::vec2 ndc = glm::vec2(clip) / clip.w;
        const int cx = static_cast<int>((ndc.x * 0.5f + 0.5f) * static_cast<float>(vw));
        const int cy = static_cast<int>((ndc.y * 0.5f + 0.5f) * static_cast<float>(vh));
        float sum = 0.0f;
        int n = 0;
        for (int y = cy - 4; y <= cy + 4; ++y)
            for (int x = cx - 4; x <= cx + 4; ++x) {
                if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
                sum += px[(static_cast<std::size_t>(y) * vw + x) * 4];
                ++n;
            }
        return n ? sum / static_cast<float>(n) : -1.0f;
    }

    CornerImage render_impl(int vw, int vh, bool ao_on, std::uint32_t comm_set_id) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        if (comm_set_id != 0) world.set_comm_set_id(iid, comm_set_id);

        const scenegraph::Camera cam = corner_camera(vw, vh);
        renderer::Lighting lighting;
        lighting.ambient = {0.6f, 0.6f, 0.6f};

        target.resize(vw, vh);
        target.bind();
        glViewport(0, 0, vw, vh);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass->set_ao_enabled(ao_on);
        pass->render(world, cam, *p, lookup_fn, lighting,
                     scenegraph::Pass::Bridge, comm_set_id);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

        // The pass restores the caller's FBO and viewport.
        GLint fbo = 0;
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        EXPECT_EQ(static_cast<std::uint32_t>(fbo), target.fbo());
        GLint vp[4] = {0, 0, 0, 0};
        glGetIntegerv(GL_VIEWPORT, vp);
        EXPECT_EQ(vp[2], vw);
        EXPECT_EQ(vp[3], vh);

        std::vector<float> px(static_cast<std::size_t>(vw) * vh * 4);
        glReadPixels(0, 0, vw, vh, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return {block_mean(px, vw, vh, cam, kNearCorner),
                block_mean(px, vw, vh, cam, kOpenFloor)};
    }

    /// The shallow step (make_step) seen from about 60 units, drawn with
    /// `tuning`: the floor just beside the step's foot vs open floor.
    CornerImage render_step(const renderer::BridgeAoTuning& tuning, float ambient = 0.6f) {
        constexpr int kStepWin = 512;
        if (!step_model) step_model = make_step();
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(step_model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);

        scenegraph::Camera cam;
        cam.eye = {40.0f, 0.0f, 45.0f};
        cam.target = {4.0f, 0.0f, 0.0f};
        cam.up = {0.0f, 0.0f, 1.0f};
        cam.aspect = 1.0f;
        cam.near = 0.5f;
        cam.far = 2000.0f;
        renderer::Lighting lighting;
        lighting.ambient = glm::vec3(ambient);

        target.resize(kStepWin, kStepWin);
        target.bind();
        glViewport(0, 0, kStepWin, kStepWin);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass->set_ao_tuning(tuning);
        pass->render(world, cam, *p, lookup_fn, lighting, scenegraph::Pass::Bridge, 0);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kStepWin) * kStepWin * 4);
        glReadPixels(0, 0, kStepWin, kStepWin, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return {block_mean(px, kStepWin, kStepWin, cam, kStepFoot),
                block_mean(px, kStepWin, kStepWin, cam, kStepOpen)};
    }
    std::unique_ptr<assets::Model> step_model;

    CornerImage render_corner(bool ao_on) { return render_impl(kWin, kWin, ao_on, 0); }
    CornerImage render_corner_at(int vw, int vh, bool ao_on) {
        return render_impl(vw, vh, ao_on, 0);
    }
    CornerImage render_corner_as_comm_set() { return render_impl(kWin, kWin, true, 1); }
};

}  // namespace

TEST_F(BridgeAoFrame, InsideCornerIsDarkerThanOpenFloor) {
    const auto img = render_corner(/*ao_on=*/true);
    EXPECT_LT(img.near_corner, img.open_floor * 0.85);   // occluded
    EXPECT_GT(img.open_floor, render_corner(false).open_floor * 0.95);  // open floor ~unoccluded
}

// The main kernel alone, before the ambient (the look before the detail kernel).
renderer::BridgeAoTuning main_only() {
    renderer::BridgeAoTuning t;
    t.detail_samples = 0;
    t.detail_final = 0.0f;
    return t;
}

// Each point against the same render with AO strength 0, so view-dependent
// shading across the floor cancels out.
renderer::BridgeAoTuning no_ao() {
    renderer::BridgeAoTuning t = main_only();
    t.strength = 0.0f;
    return t;
}

// The default kernel cannot see a 1.5-unit step from the floor beside it: its
// lowest sample sits ~0.077 x 30 = 2.3 units off the floor (measured 0.994 of
// no-AO here; only the riser's own AO bleeds ~0.5 units onto the floor).
// Pins the blind spot the detail kernel exists for.
TEST_F(BridgeAoFrame, DefaultKernelIsBlindToAShallowStep) {
    const auto base = render_step(no_ao());
    const auto img = render_step(main_only());
    EXPECT_GT(img.near_corner, base.near_corner * 0.98);
}

// Measured 0.903 of no-AO at 1.3 units from the riser (0.73 at 0.4, 0.97 at 2).
TEST_F(BridgeAoFrame, DetailKernelDarkensTheFootOfAShallowStep) {
    const auto base = render_step(no_ao());
    renderer::BridgeAoTuning t = main_only();
    t.detail_samples = 8;
    const auto img = render_step(t);
    EXPECT_LT(img.near_corner, base.near_corner * 0.95);
    EXPECT_GT(img.open_floor, base.open_floor * 0.98);   // clear of the step: untouched
}

// A spot straight down over the step, `radiance` linear.
void light_the_step(renderer::BridgePass& pass, float radiance) {
    pass.set_spots({{{6.0f, 0.0f, 40.0f}, {0.0f, 0.0f, -1.0f},
                     std::cos(glm::radians(60.0f)), std::cos(glm::radians(80.0f)),
                     200.0f, glm::vec3(radiance)}});
}

// AO darkens only the ambient downlight, so a step lit by a spot keeps the
// spot's full diffuse at its foot; detail_direct carries the detail AO onto it.
// Measured 0.311 -> 0.298 at the foot, open floor unchanged.
TEST_F(BridgeAoFrame, DetailDirectDarkensASpotLitStepFoot) {
    light_the_step(*pass, 400.0f);
    renderer::BridgeAoTuning t = main_only();
    t.detail_samples = 8;
    const auto received_only = render_step(t, 0.05f);
    t.detail_direct = 1.0f;
    const auto with_direct = render_step(t, 0.05f);
    pass->set_spots({});
    EXPECT_LT(with_direct.near_corner, received_only.near_corner * 0.97);
    EXPECT_GT(with_direct.open_floor, received_only.open_floor * 0.99);
}

// A brightly lit surface sits on the diffuse ceiling's knee, which flattens
// darkening applied before it: detail_final applies the detail AO after it.
// Measured at the foot: 0.822 none, 0.813 detail_direct 1, 0.752 detail_final 1.
TEST_F(BridgeAoFrame, DetailFinalShowsOnABrightStepFoot) {
    light_the_step(*pass, 4000.0f);
    renderer::BridgeAoTuning t = main_only();
    t.detail_samples = 8;
    const auto none = render_step(t);
    t.detail_direct = 1.0f;
    const auto before = render_step(t);
    t.detail_direct = 0.0f;
    t.detail_final = 1.0f;
    const auto after = render_step(t);
    pass->set_spots({});
    EXPECT_LT(after.near_corner, none.near_corner * 0.95);
    EXPECT_LT(after.near_corner, before.near_corner);
    EXPECT_GT(after.open_floor, none.open_floor * 0.99);
}

// Same for the main kernel: the inside corner under a bright spot (a chair's
// pool under the ceiling strips) only darkens its ambient share unless
// main_direct / main_final carry the main AO onto the light.
// Measured corner/open ratio: 0.808 ambient only, 0.759 direct, 0.708 final.
TEST_F(BridgeAoFrame, MainDirectAndFinalDarkenASpotLitCorner) {
    pass->set_spots({{{38.0f, 0.0f, 80.0f}, {0.0f, 0.0f, -1.0f},
                      std::cos(glm::radians(40.0f)), std::cos(glm::radians(60.0f)),
                      400.0f, glm::vec3(3000.0f)}});
    auto ratio = [&](const renderer::BridgeAoTuning& t) {
        pass->set_ao_tuning(t);
        const auto img = render_corner(/*ao_on=*/true);
        return img.near_corner / img.open_floor;
    };
    const float ambient_only = ratio(main_only());
    renderer::BridgeAoTuning t = main_only();
    t.main_direct = 1.0f;
    const float direct = ratio(t);
    t.main_direct = 0.0f;
    t.main_final = 1.0f;
    const float final_ = ratio(t);
    pass->set_spots({});
    EXPECT_LT(direct, ambient_only * 0.95);
    EXPECT_LT(final_, ambient_only * 0.95);
}

TEST(BridgeAoTuning, DefaultsAreMarksLivePick) {
    const renderer::BridgeAoTuning t;
    EXPECT_EQ(t.radius, renderer::kBridgeLighting.ao_radius);
    EXPECT_EQ(t.strength, renderer::kBridgeLighting.ao_strength);
    EXPECT_EQ(t.bias, renderer::kBridgeLighting.ao_bias);
    EXPECT_EQ(t.bias_dist, 0.01f);
    EXPECT_EQ(t.bias_facing, 0.0f);
    EXPECT_EQ(t.min_len, 0.1f);
    EXPECT_EQ(t.main_direct, 0.0f);
    EXPECT_EQ(t.main_final, 0.0f);
    EXPECT_EQ(t.detail_samples, 8);
    EXPECT_EQ(t.detail_direct, 0.0f);
    EXPECT_EQ(t.detail_final, 1.0f);
}

TEST_F(BridgeAoFrame, CommSetRenderNeverBindsAo) {
    render_corner(true);                                  // main view: AO computed
    // Same model, tagged as a comm set, rendered with comm_set_id != 0:
    const auto comm = render_corner_as_comm_set();
    // A comm set draws the legacy shading (no PBR), so compare it with the
    // main view drawn legacy too, AO off: any difference would be AO.
    pass->set_pbr_enabled(false);
    const auto plain = render_corner(false);
    pass->set_pbr_enabled(true);
    EXPECT_EQ(comm.near_corner, plain.near_corner);       // no AO darkening at all
}

TEST_F(BridgeAoFrame, ResizeBetweenFramesKeepsAoValid) {
    render_corner_at(256, 256, true);
    const auto small = render_corner_at(128, 96, true);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_LT(small.near_corner, small.open_floor * 0.85);
}

TEST_F(BridgeAoFrame, RawDepthSamplerNeverLeaksPastTheBridgeDraw) {
    render_corner(true);
    GLint bound = -1;
    glActiveTexture(GL_TEXTURE4);
    glGetIntegerv(GL_SAMPLER_BINDING, &bound);
    glActiveTexture(GL_TEXTURE0);
    EXPECT_EQ(bound, 0);
    // The AO and pre-pass depth textures must not stay bound either: the next
    // frame's nested normal pre-pass renders INTO the depth texture's FBO with
    // a program that samples unit 4 -- a feedback loop (GL 4.1 §9.3.1).
    for (GLenum unit : {GL_TEXTURE3, GL_TEXTURE4}) {
        GLint tex = -1;
        glActiveTexture(unit);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex);
        EXPECT_EQ(tex, 0) << "unit " << (unit - GL_TEXTURE0);
    }
    glActiveTexture(GL_TEXTURE0);
}

TEST(BridgeAoShader, CompilesAndLinksAtEverySampleCount) {
    std::unique_ptr<renderer::Window> win;
    try {
        win = std::make_unique<renderer::Window>(64, 64, "bridge-ao-shader-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }
    renderer::BridgeAoPass ao;
    const scenegraph::Camera cam = corner_camera(64, 64);
    for (int samples : {24, 32, 64}) {
        renderer::BridgeAoSettings s;
        s.samples = samples;
        bool drew = false;
        EXPECT_TRUE(ao.render(cam, 64, 64, s, [&] { drew = true; })) << samples;
        EXPECT_TRUE(drew) << samples;
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR)) << samples;
        EXPECT_NE(ao.ao_texture(), 0u) << samples;
        EXPECT_EQ(ao.ao_width(), 32) << samples;    // default resolution_scale 0.5
        EXPECT_EQ(ao.ao_height(), 32) << samples;
    }
    EXPECT_FALSE(ao.render(cam, 4, 64, {}, [] {}));  // too small: AO invalid
}
