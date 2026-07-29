// native/tests/renderer/test_cone_light_frame.cc
//
// Task 1 (subsystem light emitters plan): cone/spot dynamic light type.
// Renders a flat, camera-facing plane lit by a single dynamic light and
// asserts:
//   1. Cone bounds: with cos_half_angle = cos(30deg) and the cone aimed
//      straight down at the plane, an on-axis fragment is lit and a
//      fragment well outside the 30deg half-angle is dark (ambient-only;
//      here ambient/directional are both zero so it reads exactly black).
//   2. Non-cone identity: the SAME light with cos_half_angle = -1 (the
//      point/strip default) lights BOTH fragments -- proving the
//      `cha >= 0.0` guard in opaque.frag never fires for non-cone lights,
//      so the production point/strip path stays byte-identical.
//
// Uses a synthetic single-quad Model built directly from MeshCpu (no BC
// assets required), so this test runs whenever a GL context is available --
// unlike the Galaxy/Keldon-gated FrameTests in frame_test.cc.

#include <gtest/gtest.h>

#include <cmath>
#include <memory>
#include <vector>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <assets/mesh.h>
#include <assets/model.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

namespace {

// Build a single-node, single-mesh Model: one flat quad centered at the
// origin in the Z=0 plane, facing +Z (normal (0,0,1)), CCW-wound (survives
// GL_CULL_FACE/GL_BACK/GL_CCW set up in pipeline.cc).
assets::Model make_plane_model(float half_extent) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(4);
    cpu.vertices[0].position = {-half_extent, -half_extent, 0.0f};
    cpu.vertices[1].position = { half_extent, -half_extent, 0.0f};
    cpu.vertices[2].position = { half_extent,  half_extent, 0.0f};
    cpu.vertices[3].position = {-half_extent,  half_extent, 0.0f};
    for (auto& v : cpu.vertices) v.normal = glm::vec3(0.0f, 0.0f, 1.0f);
    cpu.indices = {0, 1, 2, 0, 2, 3};

    assets::Model m;
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);  // compute_model_aabb (dynamic-light selection
                              // radius) reads cpu_data(), not the GL buffer.
    m.meshes.push_back(std::move(mesh));

    assets::Node root;
    root.name = "root";
    root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    root.meshes = {0};
    m.nodes.push_back(std::move(root));
    m.root_node = 0;
    return m;
}

// Project a world point through the camera's view/proj to an integer window
// pixel (origin bottom-left, matching glReadPixels's y convention).
glm::ivec2 project_to_pixel(const scenegraph::Camera& cam,
                             const glm::vec3& world_pos, int vw, int vh) {
    glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() * glm::vec4(world_pos, 1.0f);
    glm::vec3 ndc = glm::vec3(clip) / clip.w;
    return {static_cast<int>((ndc.x * 0.5f + 0.5f) * static_cast<float>(vw)),
            static_cast<int>((ndc.y * 0.5f + 0.5f) * static_cast<float>(vh))};
}

int read_pixel_total(int x, int y) {
    unsigned char px[4] = {0, 0, 0, 0};
    glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    return px[0] + px[1] + px[2];
}

class ConeLightFrameTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "cone-light-frame-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        // Avoid inheriting a stale bounding-radius entry keyed by a model
        // address another test happened to reuse (documented caveat on
        // g_model_radius_cache in frame.cc).
        renderer::reset_model_radius_cache();
        // Avoid inheriting a GL texture id from a PREVIOUS test's (already
        // destroyed) GL context: ensure_damage_decal_texture() in frame.cc
        // lazily loads game/data/Textures/Effects/Damage.tga once per
        // process and caches its id in a process-global, then binds it
        // UNCONDITIONALLY every draw_model() call (regardless of carve
        // count). Each ConeLightFrameTest gets its own fresh GL context
        // (see SetUp above), so a texture id minted in a prior context is
        // not a valid name in this one -- binding it is GL_INVALID_OPERATION
        // under a 3.3 core profile. reset_damage_decal_texture() forces a
        // reload against the now-current context.
        renderer::reset_damage_decal_texture();
    }
};

}  // namespace

TEST_F(ConeLightFrameTest, ConeBoundsToHalfAngle) {
    assets::Model plane = make_plane_model(100.0f);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&plane));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 300.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    // Cone apex 10 GU above the plane, aimed straight down (-Z), 30 deg
    // half-angle. On-axis fragment (0,0,0): angle 0 -> lit. Off-axis
    // fragment (30,0,0): angle atan(30/10) = 71.6 deg, well outside 30 deg
    // -> dark. The off-axis point is INSIDE the light's radius (dist 31.6 <
    // 60), so a non-cone (point) light at the same radius/intensity would
    // light it -- isolating the cone gate, not radius falloff, as what
    // darkens it.
    renderer::DynamicLightDescriptor light;
    light.pos_a = light.pos_b = glm::vec3(0.0f, 0.0f, 10.0f);
    light.color = glm::vec3(1.0f);
    light.radius = 60.0f;
    light.intensity = 100.0f;
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);
    light.cos_half_angle = std::cos(glm::radians(30.0f));
    std::vector<renderer::DynamicLightDescriptor> lights = {light};

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient = glm::vec3(0.0f);
    lighting.directional_count = 0;
    submitter.submit_opaque(world, cam, *p,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, /*decal_time=*/0.0f, /*carve_cache=*/nullptr, &lights);

    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    glm::ivec2 onaxis_px  = project_to_pixel(cam, glm::vec3(0.0f, 0.0f, 0.0f), 256, 256);
    glm::ivec2 offaxis_px = project_to_pixel(cam, glm::vec3(30.0f, 0.0f, 0.0f), 256, 256);

    int onaxis_total  = read_pixel_total(onaxis_px.x, onaxis_px.y);
    int offaxis_total = read_pixel_total(offaxis_px.x, offaxis_px.y);

    EXPECT_GT(onaxis_total, 0)
        << "on-axis fragment should be lit inside the 30 deg cone";
    EXPECT_EQ(offaxis_total, 0)
        << "fragment 71.6 deg off-axis (well outside the 30 deg cone, but "
           "still inside the light's radius) must be dark -- the spot gate, "
           "not radius falloff, must be what excludes it";
}

TEST_F(ConeLightFrameTest, NegativeCosHalfAngleActsAsNonConeIdentity) {
    // Same geometry/light as above but cos_half_angle = -1 (the point/
    // strip default). Both fragments must now be lit: proves the
    // `cha >= 0.0` guard in opaque.frag keeps spot == 1.0 for non-cone
    // lights -- this feature does not change existing point/strip
    // rendering.
    assets::Model plane = make_plane_model(100.0f);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&plane));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 300.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    renderer::DynamicLightDescriptor light;
    light.pos_a = light.pos_b = glm::vec3(0.0f, 0.0f, 10.0f);
    light.color = glm::vec3(1.0f);
    light.radius = 60.0f;
    light.intensity = 100.0f;
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);  // ignored: not a cone
    light.cos_half_angle = -1.0f;
    std::vector<renderer::DynamicLightDescriptor> lights = {light};

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient = glm::vec3(0.0f);
    lighting.directional_count = 0;
    submitter.submit_opaque(world, cam, *p,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, /*decal_time=*/0.0f, /*carve_cache=*/nullptr, &lights);

    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    glm::ivec2 onaxis_px  = project_to_pixel(cam, glm::vec3(0.0f, 0.0f, 0.0f), 256, 256);
    glm::ivec2 offaxis_px = project_to_pixel(cam, glm::vec3(30.0f, 0.0f, 0.0f), 256, 256);

    EXPECT_GT(read_pixel_total(onaxis_px.x, onaxis_px.y), 0);
    EXPECT_GT(read_pixel_total(offaxis_px.x, offaxis_px.y), 0)
        << "cos_half_angle=-1 must light the off-axis fragment too (spot "
           "factor 1.0) -- this is the byte-identity guard for point/strip "
           "lights.";
}
