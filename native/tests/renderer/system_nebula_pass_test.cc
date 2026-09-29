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
