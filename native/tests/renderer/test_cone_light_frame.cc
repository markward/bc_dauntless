// native/tests/renderer/test_cone_light_frame.cc
//
// Task 1 (stretched-cone-emitter plan): elliptical, oriented cone/spot
// dynamic light type. Renders a flat, camera-facing plane lit by a single
// dynamic light and asserts:
//   1. Cone bounds: with spot_tan_x = spot_tan_y = tan(30deg) (a circular
//      cone) and the cone aimed straight down at the plane, an on-axis
//      fragment is lit and a fragment well outside the 30deg half-angle is
//      dark (ambient-only; here ambient/directional are both zero so it
//      reads exactly black).
//   2. Non-cone identity: the SAME light with spot_tan_x = -1 (the
//      point/strip default) lights BOTH fragments -- proving the
//      `tx >= 0.0` guard in opaque.frag never fires for non-cone lights,
//      so the production point/strip path stays byte-identical.
//   3. Elliptical bounds: a cone with a WIDE spot_tan_x (45deg) and a
//      NARROW spot_tan_y (10deg) lights a fragment offset along the wide
//      (x) axis but darkens the same-magnitude offset along the narrow
//      (y) axis -- proving the ellipse is actually anisotropic, not just
//      a relabeled circle.
//
// Uses a synthetic single-quad Model built directly from MeshCpu (no BC
// assets required), so this test runs whenever a GL context is available --
// unlike the Galaxy/Keldon-gated FrameTests in frame_test.cc.

#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <memory>
#include <vector>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <assets/mesh.h>
#include <assets/model.h>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
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

// Build the same quad in the x == 0 PLANE (spanning y and z), normal +X.
//
// Every vertex has x == 0.0 EXACTLY, so the interpolated v_position_ws.x is
// exactly 0.0 across the whole surface (interpolating a constant). Put the cone
// light at x == 0 too and dld.x is exactly 0 for every fragment -- which is what
// makes the degenerate-cone 0/0 reproducible instead of a lucky pixel. See
// ZeroWidthConeOnAxisPlaneIsFinite.
assets::Model make_plane_model_yz(float half_extent) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(4);
    cpu.vertices[0].position = {0.0f, -half_extent, -half_extent};
    cpu.vertices[1].position = {0.0f, -half_extent,  half_extent};
    cpu.vertices[2].position = {0.0f,  half_extent,  half_extent};
    cpu.vertices[3].position = {0.0f,  half_extent, -half_extent};
    // Normals point +Z, TOWARD the light, not along the quad's geometric +X.
    // Deliberate: the surface has to have nl > 0 or the cone gate's effect
    // multiplies out to nothing and the test cannot see it. Culling uses the
    // winding, not this, so the quad still renders.
    for (auto& v : cpu.vertices) v.normal = glm::vec3(0.0f, 0.0f, 1.0f);
    // Reversed relative to make_plane_model's Z=0 quad: viewed from +X the
    // camera's screen-right is world -Z, which flips the handedness, so
    // {0,1,2} would wind CW and be culled as a back face (GL_CCW front).
    cpu.indices = {0, 2, 1, 0, 3, 2};

    assets::Model m;
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
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
    // half-angle (circular: spot_tan_x == spot_tan_y). On-axis fragment
    // (0,0,0): angle 0 -> lit. Off-axis fragment (30,0,0): angle
    // atan(30/10) = 71.6 deg, well outside 30 deg -> dark. The off-axis
    // point is INSIDE the light's radius (dist 31.6 < 60), so a non-cone
    // (point) light at the same radius/intensity would light it --
    // isolating the cone gate, not radius falloff, as what darkens it.
    renderer::DynamicLightDescriptor light;
    light.pos_a = light.pos_b = glm::vec3(0.0f, 0.0f, 10.0f);
    light.color = glm::vec3(1.0f);
    light.radius = 60.0f;
    light.intensity = 100.0f;
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);
    light.up = glm::vec3(0.0f, 1.0f, 0.0f);
    light.spot_tan_x = std::tan(glm::radians(30.0f));
    light.spot_tan_y = std::tan(glm::radians(30.0f));
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

// ── A ZERO-width cone must emit nothing, WITHOUT poisoning the fragment ────
//
// spot_tan == 0 is trivially authorable -- SetLightEmitterRadius(i, 0.0) on a
// cone emitter, which the SPV's light editor can produce with one keystroke and
// which sat in hardpoint_overrides.py for several hours during the HDR
// black-square hunt. The old gate was `tx >= 0.0`, which let a zero tangent
// straight into `dot(dld, rgt) / (fz * tx)`.
//
// This test pins the SEMANTICS the guard must preserve: a zero-width cone had
// no interior before the fix either (num/0 == Inf -> saturated smoothstep ->
// spot 0), so it must not turn into a full point light on the way to losing the
// NaN. The light faces the plane head-on, so a point light here WOULD be bright
// and this assertion has teeth.
//
// It does NOT reproduce the NaN, and was verified not to: reverting the guard
// leaves it passing. The rasterizer shades at PIXEL CENTRES, so the fragment
// nearest the axis still sits half a pixel off it, leaving dot(dld, rgt) small
// but non-zero -- Inf, not NaN. ZeroWidthConeOnAxisPlaneIsFinite is the test
// that actually catches the bug.
//
// Rendered to a FLOAT target on purpose: the sibling tests read RGBA8, where a
// NaN converts to 0 and is indistinguishable from "correctly dark" -- the bug
// would hide inside the very assertion meant to catch it.
TEST_F(ConeLightFrameTest, ZeroWidthConeDoesNotBecomeAPointLight) {
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
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);
    light.up = glm::vec3(0.0f, 1.0f, 0.0f);
    light.spot_tan_x = 0.0f;   // radius 0 => zero-width cone
    light.spot_tan_y = 0.0f;
    std::vector<renderer::DynamicLightDescriptor> lights = {light};

    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    hdr.bind();
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

    glm::ivec2 onaxis_px = project_to_pixel(cam, glm::vec3(0.0f, 0.0f, 0.0f), 256, 256);
    float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glReadPixels(onaxis_px.x, onaxis_px.y, 1, 1, GL_RGBA, GL_FLOAT, px);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    for (int c = 0; c < 3; ++c) {
        EXPECT_TRUE(std::isfinite(px[c]))
            << "zero-width cone produced a non-finite channel " << c
            << " (got " << px[c] << ")";
    }
    // Ambient and directional are both zero, so "emits nothing" reads as black.
    // This pins the SEMANTICS the guard preserves: a zero-width cone had no
    // interior before the fix either (Inf -> saturated smoothstep -> spot 0),
    // so it must not become a full point light on the way to losing the NaN.
    EXPECT_FLOAT_EQ(px[0], 0.0f) << "a zero-width cone must not light anything";
    EXPECT_FLOAT_EQ(px[1], 0.0f);
    EXPECT_FLOAT_EQ(px[2], 0.0f);
}

// ── A zero-width cone must not LEAK light along its axis planes ───────────
//
// THE REGRESSION TEST for the `tx >= 0.0` gate letting spot_tan == 0 reach
// `dot(dld, rgt) / (fz * tx)`. Verified by reverting the guard and watching it
// fail.
//
// What actually goes wrong is worth stating precisely, because the obvious
// guess is wrong. 0/0 gives NaN, so e is NaN -- but spot is
// `1.0 - smoothstep(0.85, 1.0, e)`, and smoothstep clamps internally. On
// IEEE-maxNum hardware clamp(NaN, 0, 1) is 0, so t == 0, smoothstep returns 0,
// and spot comes out as 1.0. The NaN is swallowed and the light is applied at
// FULL strength exactly where the cone has no interior at all. (On hardware
// where clamp propagates NaN instead, the same expression poisons the fragment
// -- 0/0 is undefined behaviour either way, which is the deeper reason to
// guard it.)
//
// Making it deterministic: aiming the light at a point does not work, because
// fragments are shaded at PIXEL CENTRES and the nearest one still sits half a
// pixel off axis (num/0 == Inf, no leak). So the zero is arranged by
// construction -- the quad lies in the x == 0 plane with every vertex x == 0.0
// exactly, so interpolation gives v_position_ws.x == 0.0 for EVERY fragment;
// the light also sits at x == 0, so (lp - pos).x is exactly 0 and stays 0
// through L and dld; and fwd/upv are unit and axis-aligned, so
// rgt = cross(fwd, upv) = (1,0,0) exactly. dot(dld, rgt) == dld.x == 0 across
// the whole surface.
TEST_F(ConeLightFrameTest, ZeroWidthConeDoesNotLeakLightOnItsAxisPlane) {
    assets::Model plane = make_plane_model_yz(100.0f);
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&plane));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(300.0f, 0.0f, 0.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    renderer::DynamicLightDescriptor light;
    light.pos_a = light.pos_b = glm::vec3(0.0f, 0.0f, 10.0f);  // x == 0: the whole point
    light.color = glm::vec3(1.0f);
    light.radius = 60.0f;
    light.intensity = 100.0f;
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);
    light.up = glm::vec3(0.0f, 1.0f, 0.0f);
    light.spot_tan_x = 0.0f;   // radius 0 => zero-width cone, no interior
    light.spot_tan_y = 0.0f;
    std::vector<renderer::DynamicLightDescriptor> lights = {light};

    // Float target: an RGBA8 backbuffer would clamp away the overbright leak
    // this test is looking for, and turn any NaN into 0.
    renderer::HdrTarget hdr;
    hdr.resize(256, 256);
    hdr.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient = glm::vec3(0.25f);   // the ONLY light that may reach the hull
    lighting.directional_count = 0;
    submitter.submit_opaque(world, cam, *p,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, /*decal_time=*/0.0f, /*carve_cache=*/nullptr, &lights);

    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    std::vector<float> px(256 * 256 * 4);
    glReadPixels(0, 0, 256, 256, GL_RGBA, GL_FLOAT, px.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    int nonfinite = 0, rendered = 0, leaked = 0;
    float brightest = 0.0f;
    for (int i = 0; i < 256 * 256; ++i) {
        for (int c = 0; c < 3; ++c) {
            if (!std::isfinite(px[i * 4 + c])) ++nonfinite;
        }
        const float r = px[i * 4];
        if (r > 0.01f) ++rendered;
        // intensity 100 vs ambient 0.25: a leak is not subtle.
        if (std::isfinite(r) && r > 1.0f) ++leaked;
        if (std::isfinite(r) && r > brightest) brightest = r;
    }

    // Proves the quad actually rendered: without this a culled or off-screen
    // frame would report zero leaks and pass vacuously. This guard has already
    // caught one wrong winding.
    ASSERT_GT(rendered, 1000) << "the plane did not render (culled or "
                                 "off-screen), so nothing below proved anything";
    EXPECT_EQ(leaked, 0)
        << leaked << " fragments lit beyond ambient (brightest " << brightest
        << ") -- a zero-width cone has no interior, so spot_tan == 0 must not "
           "reach the divide in opaque.frag's cone gate";
    EXPECT_EQ(nonfinite, 0)
        << nonfinite << " non-finite components: on this hardware clamp() "
           "swallows the 0/0, but hardware that propagates NaN would poison "
           "the fragment here";
}

TEST_F(ConeLightFrameTest, NegativeSpotTanActsAsNonConeIdentity) {
    // Same geometry/light as above but spot_tan_x = -1 (the point/
    // strip default). Both fragments must now be lit: proves the
    // `tx >= 0.0` guard in opaque.frag keeps spot == 1.0 for non-cone
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
    light.spot_tan_x = -1.0f;
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
        << "spot_tan_x=-1 must light the off-axis fragment too (spot "
           "factor 1.0) -- this is the byte-identity guard for point/strip "
           "lights.";
}

TEST_F(ConeLightFrameTest, EllipticalConeBoundsToEllipse) {
    // Same apex/aim as ConeBoundsToHalfAngle, but WIDE along x (45 deg) and
    // NARROW along y (10 deg), up = (0,1,0). Height (apex -> plane) is 10 GU.
    // A 6 GU offset along x subtends atan(6/10) = 30.96 deg < 45 deg -> lit.
    // The SAME 6 GU offset along y subtends the same 30.96 deg, but that is
    // well outside the 10 deg y half-angle -> dark. Equal offset, opposite
    // verdicts: proves the ellipse is genuinely anisotropic, not a relabeled
    // circle.
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
    light.direction = glm::vec3(0.0f, 0.0f, -1.0f);
    light.up = glm::vec3(0.0f, 1.0f, 0.0f);
    light.spot_tan_x = std::tan(glm::radians(45.0f));
    light.spot_tan_y = std::tan(glm::radians(10.0f));
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

    glm::ivec2 onaxis_px   = project_to_pixel(cam, glm::vec3(0.0f, 0.0f, 0.0f), 256, 256);
    glm::ivec2 wide_px     = project_to_pixel(cam, glm::vec3(6.0f, 0.0f, 0.0f), 256, 256);
    glm::ivec2 narrow_px   = project_to_pixel(cam, glm::vec3(0.0f, 6.0f, 0.0f), 256, 256);

    EXPECT_GT(read_pixel_total(onaxis_px.x, onaxis_px.y), 0)
        << "on-axis fragment should be lit inside the elliptical cone";
    EXPECT_GT(read_pixel_total(wide_px.x, wide_px.y), 0)
        << "6 GU offset along the WIDE (45 deg) x-axis should be lit";
    EXPECT_EQ(read_pixel_total(narrow_px.x, narrow_px.y), 0)
        << "the same 6 GU offset along the NARROW (10 deg) y-axis should be "
           "dark -- proves x and y half-angles are independent";
}
