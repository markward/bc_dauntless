// native/tests/renderer/system_nebula_pass_test.cc
//
// Headless GL test for the system-scale nebula pass (profile haze). A GLSL
// error only surfaces at RUNTIME, so this is the compile check: constructing
// the Pipeline compiles + links system_nebula.frag (Shader throws on failure),
// and render() must actually draw a visible haze into an HDR target.
#include <gtest/gtest.h>

#include <renderer/frame.h>          // Lighting
#include <renderer/hdr_target.h>
#include <renderer/nebula_atmosphere.h>
#include <renderer/nebula_pass.h>    // NebulaVolume
#include <renderer/pipeline.h>
#include <renderer/system_nebula_pass.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <memory>
#include <vector>

namespace {

renderer::atmosphere::RadialProfile band_profile() {
    renderer::atmosphere::RadialProfile p;
    p.r = {0.0f, 60000.0f, 120000.0f, 240000.0f};
    p.nebula = {0.0f, 0.0f, 1.0f, 0.05f};
    p.k_sys = 2.0e-5f;
    p.star_radius = 2000.0f;
    p.cloud_rgb = glm::vec3(0.6f, 0.35f, 0.7f);
    p.star_rgb = glm::vec3(1.0f);
    return p;
}

class SystemNebulaPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "system-nebula-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        // Compiles + links system_nebula.frag; Shader throws on any error.
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        w.reset();
    }
};

}  // namespace

TEST_F(SystemNebulaPassTest, ProfileUploadAndClear) {
    renderer::SystemNebulaPass pass;
    EXPECT_FALSE(pass.has_profile());
    pass.set_profile(band_profile(), renderer::atmosphere::LookParams{});
    EXPECT_TRUE(pass.has_profile());
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    pass.clear_profile();
    EXPECT_FALSE(pass.has_profile());
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SystemNebulaPassTest, NoProfileNoVolumesDrawsNothing) {
    renderer::HdrTarget target;
    target.resize(64, 64);
    target.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClearDepth(1.0);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 300000.0f, 0.0f);
    cam.target = glm::vec3(0.0f);
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());

    renderer::SystemNebulaPass pass;
    renderer::Lighting lighting;
    pass.render(cam, *pipeline, {}, lighting, target.color_texture(),
                target.depth_texture(), inv_vp, cam.eye, 0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    float px[4] = {1.0f, 1.0f, 1.0f, 1.0f};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_FLOAT, px);
    EXPECT_EQ(px[3], 0.0f) << "no profile, no volumes: zero GL work";
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

TEST_F(SystemNebulaPassTest, ClumpsWithoutProfileRender) {
    renderer::HdrTarget target;
    target.resize(64, 64);
    target.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClearDepth(1.0);   // far plane everywhere: nothing occludes the clump
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.target = glm::vec3(0.0f, 1.0f, 0.0f);   // looking down +Y
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;
    cam.near = 1.0f;
    cam.far = 1.8e6f;
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());

    renderer::NebulaVolume v;
    v.spheres = {glm::vec4(0.0f, 5000.0f, 0.0f, 3000.0f)};   // at the look point
    v.rgb = glm::vec3(0.5f, 0.6f, 0.9f);
    v.visibility = 500.0f;
    v.fbm = glm::vec3(0.001f, 3.0f, 0.2f);
    v.seed = glm::vec3(1.0f, 2.0f, 3.0f);

    renderer::SystemNebulaPass pass;
    // No set_profile(): this run has no radial atmosphere at all, only a
    // local clump. The pass must still march and draw it.
    EXPECT_FALSE(pass.has_profile());
    renderer::Lighting lighting;
    pass.render(cam, *pipeline, {v}, lighting, target.color_texture(),
                target.depth_texture(), inv_vp, cam.eye, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_FLOAT, px);
    EXPECT_GT(px[3], 0.0f) << "clump drew nothing without a profile";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// The clump fbm must drift with time, exactly as nebula_volumetric.frag's
// density() does -- gameplay concealment (engine/appc/nebula_density.py)
// samples the same drifting field, so the visual clump has to match it.
// Renders the SAME clump-only scene twice, at two different `time` values,
// on two FRESH passes (no temporal history to blend the difference away)
// and asserts the centre pixel actually changed.
TEST_F(SystemNebulaPassTest, ClumpDensityDriftsWithTime) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.target = glm::vec3(0.0f, 1.0f, 0.0f);   // looking down +Y
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;
    cam.near = 1.0f;
    cam.far = 1.8e6f;
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());

    renderer::NebulaVolume v;
    // The ray from the origin toward +Y stays at x=0 for every sample point,
    // so u_time*0.01 (added only to the x argument of the fbm call) is the
    // ONLY thing that can move the sampled noise between the two renders --
    // isolating the drift term from ordinary spatial variation.
    v.spheres = {glm::vec4(0.0f, 5000.0f, 0.0f, 3000.0f)};
    v.rgb = glm::vec3(0.5f, 0.6f, 0.9f);
    v.visibility = 500.0f;
    v.fbm = glm::vec3(0.001f, 3.0f, 0.2f);
    v.seed = glm::vec3(1.0f, 2.0f, 3.0f);
    renderer::Lighting lighting;

    auto render_at = [&](float time_s) {
        renderer::HdrTarget target;
        target.resize(64, 64);
        target.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
        glClearDepth(1.0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        renderer::SystemNebulaPass pass;   // fresh: no temporal history
        pass.render(cam, *pipeline, {v}, lighting, target.color_texture(),
                    target.depth_texture(), inv_vp, cam.eye, time_s);
        EXPECT_EQ(glGetError(), GL_NO_ERROR);

        float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
        glReadPixels(32, 32, 1, 1, GL_RGBA, GL_FLOAT, px);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return glm::vec4(px[0], px[1], px[2], px[3]);
    };

    const glm::vec4 at_t0 = render_at(0.0f);
    const glm::vec4 at_t200 = render_at(200.0f);
    EXPECT_GT(at_t0.a, 0.0f) << "clump drew nothing at t=0";
    EXPECT_NE(at_t0, at_t200) << "clump did not drift with u_time";
}

TEST_F(SystemNebulaPassTest, SetDialsRebuildsTableOnlyForGOrFloor) {
    renderer::SystemNebulaPass pass;
    pass.set_profile(band_profile(), renderer::atmosphere::LookParams{});
    EXPECT_TRUE(pass.has_profile());
    const int after_initial_upload = pass.profile_rebuild_count();
    EXPECT_EQ(after_initial_upload, 1);

    // lane_size / lane_contrast / near_range: no table dependency, no rebuild.
    renderer::SystemNebulaPass::Dials d = pass.dials();
    d.lane_size = 20000.0f;
    d.lane_contrast = 0.9f;
    d.near_range = 45000.0f;
    pass.set_dials(d);
    EXPECT_EQ(pass.profile_rebuild_count(), after_initial_upload)
        << "a lane/near-range-only change must not rebuild the far-field table";
    EXPECT_TRUE(pass.has_profile());
    EXPECT_EQ(pass.dials().lane_size, 20000.0f);
    EXPECT_EQ(pass.dials().lane_contrast, 0.9f);
    EXPECT_EQ(pass.dials().near_range, 45000.0f);

    // g change: rebuilds.
    d.g = 0.2f;
    pass.set_dials(d);
    EXPECT_EQ(pass.profile_rebuild_count(), after_initial_upload + 1)
        << "a g change must rebuild the far-field table";
    EXPECT_TRUE(pass.has_profile());
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // floor change: rebuilds again.
    d.floor = 0.1f;
    pass.set_dials(d);
    EXPECT_EQ(pass.profile_rebuild_count(), after_initial_upload + 2)
        << "a floor change must rebuild the far-field table";
    EXPECT_TRUE(pass.has_profile());
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Setting the SAME g/floor again must not rebuild.
    pass.set_dials(d);
    EXPECT_EQ(pass.profile_rebuild_count(), after_initial_upload + 2)
        << "re-setting identical dials must not rebuild";
}

TEST_F(SystemNebulaPassTest, SetDialsWithoutProfileNeverRebuilds) {
    renderer::SystemNebulaPass pass;
    EXPECT_FALSE(pass.has_profile());
    EXPECT_EQ(pass.profile_rebuild_count(), 0);

    renderer::SystemNebulaPass::Dials d = pass.dials();
    d.g = 0.1f;
    d.floor = 0.5f;
    pass.set_dials(d);
    EXPECT_FALSE(pass.has_profile())
        << "no profile to rebuild: set_dials must not create one";
    EXPECT_EQ(pass.profile_rebuild_count(), 0);
    EXPECT_EQ(pass.dials().g, 0.1f);
    EXPECT_EQ(pass.dials().floor, 0.5f);
}

TEST_F(SystemNebulaPassTest, RendersVisibleHazeLookingAtTheStar) {
    renderer::HdrTarget target;
    target.resize(64, 64);
    target.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClearDepth(1.0);   // far plane everywhere: the sky branch of the shader
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 300000.0f, 0.0f);   // render-relative to the star
    cam.target = glm::vec3(0.0f);                  // looking at the star
    cam.up = glm::vec3(0.0f, 0.0f, 1.0f);
    cam.aspect = 1.0f;
    cam.near = 1.0f;
    cam.far = 1.8e6f;
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());

    renderer::SystemNebulaPass pass;
    pass.set_profile(band_profile(), renderer::atmosphere::LookParams{});
    pass.set_star(glm::vec3(0.0f));
    renderer::Lighting lighting;
    pass.render(cam, *pipeline, {}, lighting, target.color_texture(),
                target.depth_texture(), inv_vp, cam.eye, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    // The pass restores the caller's framebuffer: we are still on the target.
    GLint bound = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &bound);
    EXPECT_EQ(static_cast<GLuint>(bound), target.fbo());

    float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_FLOAT, px);
    // Line of sight crosses the 60k-240k GU band twice (~13 optical depths
    // at k=2e-5 would be opaque, but the ray also dives into the star, so
    // just require a real, partial, finite haze).
    EXPECT_GT(px[3], 0.0f) << "haze drew nothing";
    EXPECT_LT(px[3], 1.0f) << "haze saturated to opaque";
    for (int c = 0; c < 3; ++c) {
        EXPECT_TRUE(std::isfinite(px[c])) << "channel " << c;
        EXPECT_GE(px[c], 0.0f) << "channel " << c;
    }
    EXPECT_GT(px[0] + px[1] + px[2], 0.0f) << "haze has no colour";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}
