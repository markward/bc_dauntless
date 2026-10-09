// native/tests/renderer/bridge_pbr_frame_test.cc
//
// Bridge PBR shading through the real bridge.frag (spec
// 2026-10-08-bridge-emitters §9, plan 2026-10-09-bridge-pbr Task 4): material
// channels (map -> per-shape override -> default), normal maps on a
// derivative tangent frame, the A/B switch, the diffuse ceiling, comm sets on
// legacy shading, and the new debug views. Skips cleanly without a GL context.
// Fixture: as bridge_highlight_test.cc, with planar UVs on the corner.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bloom_pass.h>
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
#include <assets/texture.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cmath>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {

constexpr int kWin = 256;

assets::Texture solid_1x1(glm::vec4 rgba);

// One quad from four corners with an authored normal `n`, wound
// counter-clockwise as seen from the side the normal faces. `uv_axes` picks
// which two position components (scaled by 1/100) become the UV; {-1, -1}
// leaves the UVs at zero (a UV-less mesh).
void append_quad(assets::MeshCpu& cpu, const glm::vec3 (&c)[4], const glm::vec3& n,
                 glm::ivec2 uv_axes) {
    const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
    for (const auto& p : c) {
        assets::MeshCpu::Vertex v;
        v.position = p;
        v.normal = n;
        if (uv_axes.x >= 0) v.uv = glm::vec2(p[uv_axes.x], p[uv_axes.y]) / 100.0f;
        cpu.vertices.push_back(v);
    }
    if (glm::dot(glm::cross(c[1] - c[0], c[2] - c[0]), n) >= 0.0f)
        cpu.indices.insert(cpu.indices.end(), {base, base + 1, base + 2, base, base + 2, base + 3});
    else
        cpu.indices.insert(cpu.indices.end(), {base, base + 2, base + 1, base, base + 3, base + 2});
}

// Floor z = 0 (x >= 0, normal +Z) and wall x = 0 (z >= 0, normal +X).
// with_uvs: floor uv = xy / 100, wall uv = yz / 100; else every uv is 0.
std::unique_ptr<assets::Model> make_corner(bool with_uvs) {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 floor_c[4] = {{0, -L, 0}, {L, -L, 0}, {L, L, 0}, {0, L, 0}};
    const glm::vec3 wall_c[4]  = {{0, -L, 0}, {0, L, 0}, {0, L, L}, {0, -L, L}};
    assets::MeshCpu cpu;
    append_quad(cpu, floor_c, {0, 0, 1}, with_uvs ? glm::ivec2(0, 1) : glm::ivec2(-1));
    append_quad(cpu, wall_c, {1, 0, 0}, with_uvs ? glm::ivec2(1, 2) : glm::ivec2(-1));
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

// The corner as TWO meshes so a reflection is identifiable by hue: mesh 0 the
// floor (material 0, grey `floor_rgb`), mesh 1 the wall (material 1, `wall_rgb`).
std::unique_ptr<assets::Model> make_two_mesh_corner(glm::vec3 floor_rgb, glm::vec3 wall_rgb) {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 floor_c[4] = {{0, -L, 0}, {L, -L, 0}, {L, L, 0}, {0, L, 0}};
    const glm::vec3 wall_c[4]  = {{0, -L, 0}, {0, L, 0}, {0, L, L}, {0, -L, L}};
    assets::MeshCpu floor_cpu, wall_cpu;
    append_quad(floor_cpu, floor_c, {0, 0, 1}, glm::ivec2(0, 1));
    append_quad(wall_cpu, wall_c, {1, 0, 0}, glm::ivec2(1, 2));
    floor_cpu.material_index = 0;
    floor_cpu.node_index = 0;
    wall_cpu.material_index = 1;
    wall_cpu.node_index = 0;
    // CPU data retained, as an interior load keeps it: the probe box is the
    // model's AABB from it.
    m->meshes.push_back(assets::upload_mesh(floor_cpu));
    m->meshes.back().set_cpu_data(floor_cpu);
    m->meshes.push_back(assets::upload_mesh(wall_cpu));
    m->meshes.back().set_cpu_data(wall_cpu);
    const glm::vec3 cols[2] = {floor_rgb, wall_rgb};
    for (int i = 0; i < 2; ++i) {
        m->textures.push_back(solid_1x1(glm::vec4(cols[i], 1.0f)));
        assets::Material mat;
        mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = i;
        m->materials.push_back(mat);
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

// A one-bone "officer": a bright green panel standing at x = 5 in front of
// the wall (normal +X), fully weighted to an identity bone, so the skinned
// sub-pass draws it where it stands. Between the probe and the wall: if a
// capture ever included officers, the floor would reflect green.
std::unique_ptr<assets::Model> make_green_officer() {
    auto m = std::make_unique<assets::Model>();
    constexpr float L = 300.0f;
    const glm::vec3 c[4] = {{5, -L, 0}, {5, L, 0}, {5, L, L}, {5, -L, L}};
    assets::MeshCpu cpu;
    append_quad(cpu, c, {1, 0, 0}, glm::ivec2(1, 2));
    for (auto& v : cpu.vertices) {
        v.bone_indices = {0, 0, 0, 0};
        v.bone_weights = {255, 0, 0, 0};
    }
    cpu.material_index = 0;
    cpu.node_index = 0;
    m->meshes.push_back(assets::upload_mesh(cpu));
    m->textures.push_back(solid_1x1({0.0f, 1.0f, 0.0f, 1.0f}));
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = 0;
    m->materials.push_back(mat);
    assets::Bone bone;
    bone.name = "Bip01";
    m->skeleton.bones.push_back(bone);
    m->skeleton.root_bone_index = 0;
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

// A 1x1 RGBA8 texture of `rgba` (0..1 per channel), owned by the returned
// assets::Texture (same upload as bridge_lighting_test.cc's red_1x1()).
assets::Texture solid_1x1(glm::vec4 rgba) {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    unsigned char px[4];
    for (int i = 0; i < 4; ++i)
        px[i] = static_cast<unsigned char>(std::lround(std::clamp(rgba[i], 0.0f, 1.0f) * 255.0f));
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    return assets::Texture(t, 1, 1, false);
}

class BridgePbrFrame : public ::testing::Test {
protected:
    // World point whose 9x9 screen block render_impl averages. The open floor
    // by default; the red-wall tests use the camera's target, (25, 0, 0),
    // where the mirror direction (-35, 0, 90) runs back into the x = 0 wall
    // (from (70, 0, 0) it would run up into the empty, black, sky).
    glm::vec3 sample_ = {70.0f, 0.0f, 0.0f};
    int floor_mesh = 0;
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<renderer::BridgePass> pass;
    std::unique_ptr<assets::Model> model;
    std::unique_ptr<assets::Model> officer;   // optional skinned instance
    renderer::HdrTarget target;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kWin, kWin, "bridge-pbr-frame-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        pass = std::make_unique<renderer::BridgePass>();
        pass->set_ao_enabled(false);
        model = make_corner(/*with_uvs=*/true);
    }

    /// Give the corner's material a solid-colour texture in `slot`.
    void set_map(assets::Material::StageSlot slot, glm::vec4 rgba) {
        model->textures.push_back(solid_1x1(rgba));
        model->materials[0].stages[static_cast<std::size_t>(slot)].texture_index =
            static_cast<int>(model->textures.size()) - 1;
    }
    void set_base(glm::vec4 rgba) { set_map(assets::Material::StageSlot::Base, rgba); }

    /// Mean RGB over a 9x9 block centred on the open floor, drawn as `draw_pass`
    /// filtered to `set_id` (0 = the main bridge view).
    glm::vec3 render_impl(const renderer::Lighting& lighting,
                          scenegraph::Pass draw_pass, std::uint32_t set_id) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, draw_pass);
        if (set_id != 0) world.set_comm_set_id(iid, set_id);
        if (officer) {
            auto oid = world.create_instance(
                reinterpret_cast<scenegraph::ModelHandle>(officer.get()));
            world.set_world_transform(oid, glm::mat4(1.0f));
            world.set_pass(oid, draw_pass);
            if (set_id != 0) world.set_comm_set_id(oid, set_id);
        }
        const scenegraph::Camera cam = corner_camera(kWin, kWin);
        target.resize(kWin, kWin);
        target.bind();
        glViewport(0, 0, kWin, kWin);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass->render(world, cam, *p, lookup_fn, lighting, draw_pass, set_id);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kWin) * kWin * 4);
        glReadPixels(0, 0, kWin, kWin, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        const glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() *
                               glm::vec4(sample_, 1.0f);
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

    static renderer::Lighting default_lighting() {
        renderer::Lighting lighting;
        lighting.ambient = {0.6f, 0.6f, 0.6f};
        return lighting;
    }
    glm::vec3 render_floor_with(const renderer::Lighting& lighting) {
        return render_impl(lighting, scenegraph::Pass::Bridge, 0);
    }
    glm::vec3 render_floor() { return render_floor_with(default_lighting()); }
    glm::vec3 render_as_comm_set() {
        return render_impl(default_lighting(), scenegraph::Pass::Comm, 7u);
    }

    unsigned long long handle() const {
        return reinterpret_cast<unsigned long long>(model.get());
    }

    /// The two-mesh corner: grey floor (mesh 0), bright red wall (mesh 1).
    void use_red_wall_corner(glm::vec3 wall = {1.0f, 0.0f, 0.0f}) {
        model = make_two_mesh_corner({0.6f, 0.6f, 0.6f}, wall);
        floor_mesh = 0;
        sample_ = {25.0f, 0.0f, 0.0f};
    }
    void set_floor_override(float rough, float metal) {
        pass->set_material_overrides(handle(), {{floor_mesh, rough, metal}});
    }
};

}  // namespace

TEST_F(BridgePbrFrame, PbrIsOnByDefault) {
    EXPECT_TRUE(pass->pbr_enabled());
}

TEST_F(BridgePbrFrame, DefaultMaterialMatchesLegacyWithinFresnel) {
    set_base({0.6f, 0.5f, 0.4f, 1.0f});
    pass->set_pbr_enabled(false);
    const glm::vec3 legacy = render_floor();
    pass->set_pbr_enabled(true);
    const glm::vec3 pbr = render_floor();
    // (1 - F) at F0 = 0.04 and the camera's ~55° view: within 6% per channel.
    for (int i = 0; i < 3; ++i) {
        EXPECT_NEAR(pbr[i], legacy[i], 0.06f * legacy[i] + 1e-3f) << i;
    }
    // ...but PBR really is a different path (the Fresnel loss is visible).
    EXPECT_LT(pbr.r, legacy.r);
}

TEST_F(BridgePbrFrame, MetalnessMapDarkensTheDiffuse) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dielectric = render_floor();
    set_map(assets::Material::StageSlot::Metalness, {1, 1, 1, 1});
    const glm::vec3 metal = render_floor();   // no probe yet: a metal has ~no diffuse
    EXPECT_LT(metal.r, dielectric.r * 0.5f);
}

TEST_F(BridgePbrFrame, OverrideAppliesWhenThereIsNoMap) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 base = render_floor();
    pass->set_material_overrides(handle(), {{0, -1.0f, 1.0f}});   // metal 1 by override
    EXPECT_LT(render_floor().r, base.r * 0.5f);
    pass->clear_material_overrides();
    EXPECT_NEAR(render_floor().r, base.r, 1e-4f);
}

TEST_F(BridgePbrFrame, OverrideForAnotherModelDoesNotApply) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 base = render_floor();
    pass->set_material_overrides(handle() + 1, {{0, -1.0f, 1.0f}});
    EXPECT_NEAR(render_floor().r, base.r, 1e-4f);
}

TEST_F(BridgePbrFrame, MapBeatsOverride) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_map(assets::Material::StageSlot::Metalness, {0, 0, 0, 1});   // map says dielectric
    const glm::vec3 by_map = render_floor();
    pass->set_material_overrides(handle(), {{0, -1.0f, 1.0f}});        // override says metal
    EXPECT_NEAR(render_floor().r, by_map.r, 1e-4f);
}

TEST_F(BridgePbrFrame, NormalMapChangesTheShading) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 flat = render_floor();
    // A tangent-space normal tilted hard sideways: the up-facing downlight
    // term drops.
    set_map(assets::Material::StageSlot::Bump, {1.0f, 0.5f, 0.5f, 1.0f});
    EXPECT_LT(render_floor().r, flat.r - 0.02f);
}

TEST_F(BridgePbrFrame, NormalMapOnAUvLessMeshIsHarmless) {
    model = make_corner(/*with_uvs=*/false);
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 no_map = render_floor();
    set_map(assets::Material::StageSlot::Bump, {1.0f, 0.5f, 0.5f, 1.0f});
    const glm::vec3 with_map = render_floor();
    for (int i = 0; i < 3; ++i) {
        EXPECT_TRUE(std::isfinite(with_map[i])) << i;
        EXPECT_NEAR(with_map[i], no_map[i], 1e-4f) << i;
    }
}

TEST_F(BridgePbrFrame, DiffuseNeverReachesBloomEvenWithPbr) {
    set_base({1, 1, 1, 1});
    renderer::Lighting bright;
    bright.ambient = glm::vec3(8.0f);
    const glm::vec3 c = render_floor_with(bright);
    EXPECT_LT(std::max(c.r, std::max(c.g, c.b)), renderer::kBloomThreshold);
}

TEST_F(BridgePbrFrame, CommSetAndOfficersDrawCleanWithPbrOn) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    render_as_comm_set();                     // comm set path: legacy shading, no GL error
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Comm sets (another ship's room on the viewscreen) keep legacy shading even
// with PBR on: a metal map that blacks out the main bridge's floor leaves the
// comm set's floor exactly the legacy colour.
TEST_F(BridgePbrFrame, CommSetKeepsLegacyShading) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_map(assets::Material::StageSlot::Metalness, {1, 1, 1, 1});
    pass->set_pbr_enabled(false);
    const glm::vec3 legacy = render_floor();
    pass->set_pbr_enabled(true);
    const glm::vec3 comm = render_as_comm_set();
    for (int i = 0; i < 3; ++i) EXPECT_NEAR(comm[i], legacy[i], 1e-4f) << i;
}

TEST_F(BridgePbrFrame, DebugViewsDrawWithoutGlErrors) {
    for (int v = 6; v <= 10; ++v) {
        pass->set_debug_view(static_cast<renderer::BridgeDebugView>(v));
        render_floor();
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR)) << v;
    }
    pass->set_debug_view(renderer::BridgeDebugView::Off);
}

// Debug views 6/7 show the resolved channel: an override of roughness 0.5 and
// metalness 0.25 reads back as those greys (the HDR target is linear float).
TEST_F(BridgePbrFrame, RoughnessAndMetalnessViewsShowTheResolvedChannel) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    pass->set_material_overrides(handle(), {{0, 0.5f, 0.25f}});
    pass->set_debug_view(renderer::BridgeDebugView::Roughness);
    EXPECT_NEAR(render_floor().r, 0.5f, 1e-3f);
    pass->set_debug_view(renderer::BridgeDebugView::Metalness);
    EXPECT_NEAR(render_floor().r, 0.25f, 1e-3f);
    pass->clear_material_overrides();
    pass->set_debug_view(renderer::BridgeDebugView::Roughness);
    EXPECT_NEAR(render_floor().r, 1.0f, 1e-3f);   // default roughness 1
    pass->set_debug_view(renderer::BridgeDebugView::Off);
}

// Units 1/5/6 are unbound when render() returns: the next pass never inherits
// a bridge map.
TEST_F(BridgePbrFrame, MapUnitsAreUnboundAfterRender) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_map(assets::Material::StageSlot::Bump, {0.5f, 0.5f, 1.0f, 1.0f});
    set_map(assets::Material::StageSlot::Roughness, {0.5f, 0.5f, 0.5f, 1.0f});
    set_map(assets::Material::StageSlot::Metalness, {0.0f, 0.0f, 0.0f, 1.0f});
    render_floor();
    for (GLenum unit : {GL_TEXTURE1, GL_TEXTURE5, GL_TEXTURE6}) {
        glActiveTexture(unit);
        GLint bound = -1;
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound);
        EXPECT_EQ(bound, 0) << (unit - GL_TEXTURE0);
    }
    glActiveTexture(GL_TEXTURE0);
}

// ── Reflection probes (plan Task 6) ─────────────────────────────────────────

TEST_F(BridgePbrFrame, ASmoothMetalFloorReflectsTheRedWall) {
    use_red_wall_corner();
    set_floor_override(/*rough=*/0.05f, /*metal=*/1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(1.0f, 1.0f);
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(c.r, c.g * 1.5f);                 // the floor shows red
    EXPECT_GT(c.r, 0.05f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgePbrFrame, RoughFloorReflectsLessDistinctly) {
    use_red_wall_corner();
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    set_floor_override(0.05f, 1.0f);
    const glm::vec3 smooth = render_floor();
    set_floor_override(1.0f, 1.0f);
    const glm::vec3 rough = render_floor();
    EXPECT_GT(smooth.r - smooth.g, rough.r - rough.g);
}

TEST_F(BridgePbrFrame, ProbeMixCrossFadesBetweenTheTwoProbes) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(2.0f, 0.5f);          // green probe 4x brighter
    pass->request_probe_capture();
    pass->set_probe_mix(0.0f);
    const float green = render_floor().r;
    pass->set_probe_mix(1.0f);
    const float yr = render_floor().r;
    pass->set_probe_mix(0.5f);
    const float mid = render_floor().r;
    EXPECT_GT(green, yr);
    EXPECT_LT(mid, green); EXPECT_GT(mid, yr);
}

TEST_F(BridgePbrFrame, ReflectionOfABrightSourceMayExceedTheThreshold) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(40.0f, 40.0f);        // the captured room is very bright
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(std::max(c.r, std::max(c.g, c.b)), renderer::kBloomThreshold);
}

TEST_F(BridgePbrFrame, NoCaptureMeansNoSpecularAndNoGlError) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_floor_override(0.05f, 1.0f);
    const glm::vec3 c = render_floor();          // u_has_probe = 0
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    // A metal floor with no probe has neither diffuse nor specular.
    EXPECT_LT(std::max(c.r, std::max(c.g, c.b)), 1e-3f);
}

// The captured room is sampled straight along R in debug view 9: the probe at
// (60, 0, 40) looking along the floor's mirror direction sees the red wall.
TEST_F(BridgePbrFrame, ProbeMirrorViewShowsTheCapture) {
    use_red_wall_corner();
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    pass->set_debug_view(renderer::BridgeDebugView::ProbeMirror);
    const glm::vec3 c = render_floor();
    pass->set_debug_view(renderer::BridgeDebugView::Off);
    EXPECT_GT(c.r, 0.05f);
    EXPECT_GT(c.r, c.g * 1.5f);
}

// The capture draws the room diffuse-only: the reflecting floor's own metal
// (black in the capture) and the viewscreen must not end up in the probe.
// A wall the capture saw RED stays red in the reflection after the wall's
// texture changes, until the next capture -- the probe is never per-frame.
TEST_F(BridgePbrFrame, ProbesAreNotRecapturedEveryFrame) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    const glm::vec3 first = render_floor();
    // Repaint the wall blue in place (same model handle): no recapture.
    model->textures[1] = solid_1x1({0.0f, 0.0f, 1.0f, 1.0f});
    const glm::vec3 again = render_floor();
    EXPECT_GT(again.r, again.b);
    EXPECT_NEAR(again.r, first.r, 1e-3f);
    pass->request_probe_capture();               // now it does
    const glm::vec3 after = render_floor();
    EXPECT_GT(after.b, after.r);
}

// A different bridge model (handle change) marks the probes dirty by itself.
TEST_F(BridgePbrFrame, ANewBridgeModelRecapturesTheProbes) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    EXPECT_GT(render_floor().r, 0.05f);
    auto old = std::move(model);                 // keep the old handle unique
    use_red_wall_corner({0.0f, 0.0f, 1.0f});
    set_floor_override(0.05f, 1.0f);
    const glm::vec3 c = render_floor();          // no request_probe_capture()
    EXPECT_GT(c.b, c.r * 1.5f);
}

// reset_probes() (mission swap) drops the captures: no specular until the
// next request.
TEST_F(BridgePbrFrame, ResetProbesDropsTheReflection) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    EXPECT_GT(render_floor().r, 0.05f);
    pass->reset_probes();
    const glm::vec3 c = render_floor();
    EXPECT_LT(std::max(c.r, std::max(c.g, c.b)), 1e-3f);
}

// Units 7/8/9 (probe cubes, BRDF LUT) are unbound when render() returns.
TEST_F(BridgePbrFrame, ProbeUnitsAreUnboundAfterRender) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    render_floor();
    for (GLenum unit : {GL_TEXTURE7, GL_TEXTURE8}) {
        glActiveTexture(unit);
        GLint bound = -1;
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &bound);
        EXPECT_EQ(bound, 0) << (unit - GL_TEXTURE0);
    }
    glActiveTexture(GL_TEXTURE9);
    GLint lut = -1;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &lut);
    EXPECT_EQ(lut, 0);
    glActiveTexture(GL_TEXTURE0);
}

// Comm sets keep legacy shading even once probes exist.
TEST_F(BridgePbrFrame, CommSetIgnoresTheProbes) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_pbr_enabled(false);
    const glm::vec3 legacy = render_floor();
    pass->set_pbr_enabled(true);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    render_floor();                              // captures
    const glm::vec3 comm = render_as_comm_set();
    for (int i = 0; i < 3; ++i) EXPECT_NEAR(comm[i], legacy[i], 1e-4f) << i;
}

// Cost of one capture of both probes (logged, not asserted).
TEST_F(BridgePbrFrame, CaptureCostIsLogged) {
    use_red_wall_corner();
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    render_floor();                              // warm: shaders, LUT
    pass->request_probe_capture();
    render_floor();                              // warm: probe allocation
    glFinish();
    const auto t0 = std::chrono::steady_clock::now();
    pass->request_probe_capture();
    render_floor();
    glFinish();
    const auto t1 = std::chrono::steady_clock::now();
    render_floor();
    glFinish();
    const auto t2 = std::chrono::steady_clock::now();
    const double with_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    const double plain_ms = std::chrono::duration<double, std::milli>(t2 - t1).count();
    std::printf("[bridge-probe] capture of both probes: ~%.2f ms (frame with capture %.2f ms, "
                "without %.2f ms)\n", with_ms - plain_ms, with_ms, plain_ms);
}

// Box projection: from a probe at (200, 0, 40) the floor's raw mirror
// direction (-35, 0, 90) leaves the room through the open top (z = 554 at
// x = 0: black). Projected against the room's AABB it lands on the wall at
// (0, 0, ~64), which the probe sees red. Without the projection this is black.
TEST_F(BridgePbrFrame, BoxProjectionFindsTheWallFromAnOffsetProbe) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({200.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(c.r, 0.05f);
    EXPECT_GT(c.r, c.g * 1.5f);
}

// Officers are excluded from the capture: a green "officer" panel standing
// between the probe and the red wall is drawn in the view but never captured,
// so the floor still reflects red.
TEST_F(BridgePbrFrame, OfficersAreNotInTheProbes) {
    use_red_wall_corner();
    officer = make_green_officer();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    const glm::vec3 c = render_floor();
    EXPECT_GT(c.r, 0.05f);
    EXPECT_GT(c.r, c.g * 1.5f);
}

// A request made before any bridge is drawn (the host requests at bridge
// load, possibly before the instance exists) stays pending: it is not spent
// capturing an empty, black room.
TEST_F(BridgePbrFrame, ARequestWaitsForABridgeToCapture) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->request_probe_capture();
    scenegraph::World empty;
    target.resize(kWin, kWin);
    target.bind();
    glViewport(0, 0, kWin, kWin);
    pass->render(empty, corner_camera(kWin, kWin), *p, lookup_fn, default_lighting());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_TRUE(pass->probe_capture_pending());
    const glm::vec3 c = render_floor();
    EXPECT_FALSE(pass->probe_capture_pending());
    EXPECT_GT(c.r, c.g * 1.5f);
}

// ── Alert ambient scale lives in the pass (Task 6 fix round 1) ─────────────

// The probes capture at ambient x probe scale only: with probe scales (1, 1)
// a capture taken at alert scale 1.5 reflects exactly what one at 1.0 does.
TEST_F(BridgePbrFrame, CaptureIgnoresTheAlertAmbientScale) {
    use_red_wall_corner();
    set_floor_override(0.05f, 1.0f);             // metal floor: reflection only
    pass->set_probe_origin({60.0f, 0.0f, 40.0f});
    pass->set_probe_scales(1.0f, 1.0f);
    pass->set_alert_ambient_scale(1.5f);
    pass->request_probe_capture();
    const glm::vec3 at_15 = render_floor();
    pass->set_alert_ambient_scale(1.0f);
    pass->request_probe_capture();
    const glm::vec3 at_10 = render_floor();
    EXPECT_GT(at_10.r, 0.05f);
    for (int i = 0; i < 3; ++i) EXPECT_NEAR(at_15[i], at_10[i], 1e-4f) << i;
}

// The main view's lit floor follows the alert scale; a comm set never does.
TEST_F(BridgePbrFrame, AlertScaleBrightensTheMainViewOnly) {
    set_base({0.4f, 0.4f, 0.4f, 1.0f});
    EXPECT_FLOAT_EQ(pass->alert_ambient_scale(), 1.0f);
    const glm::vec3 main_10 = render_floor();
    const glm::vec3 comm_10 = render_as_comm_set();
    pass->set_alert_ambient_scale(1.5f);
    const glm::vec3 main_15 = render_floor();
    const glm::vec3 comm_15 = render_as_comm_set();
    EXPECT_GT(main_15.r, main_10.r + 0.02f);
    for (int i = 0; i < 3; ++i) EXPECT_NEAR(comm_15[i], comm_10[i], 1e-6f) << i;
}
