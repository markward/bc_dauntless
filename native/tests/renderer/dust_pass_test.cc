// native/tests/renderer/dust_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/dust_pass.h>

#include <glm/glm.hpp>

#include <cmath>

TEST(DustPassGen, DeterministicSeedProducesIdenticalBuffers) {
    auto a = renderer::generate_dust_particles(12345u, 100, 40.0f);
    auto b = renderer::generate_dust_particles(12345u, 100, 40.0f);
    ASSERT_EQ(a.size(), b.size());
    ASSERT_EQ(a.size(), 100u);
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].x, b[i].x) << "at index " << i;
        EXPECT_EQ(a[i].y, b[i].y);
        EXPECT_EQ(a[i].z, b[i].z);
        EXPECT_EQ(a[i].w, b[i].w);
    }
}

TEST(DustPassGen, AllPositionsInsideSphereWithCorrectJitter) {
    const float R = 40.0f;
    auto particles = renderer::generate_dust_particles(0xABCDu, 2048, R);
    ASSERT_EQ(particles.size(), 2048u);
    for (const auto& p : particles) {
        const float r = std::sqrt(p.x*p.x + p.y*p.y + p.z*p.z);
        EXPECT_LE(r, R + 1e-4f);
        EXPECT_GE(p.w, 0.0f);
        EXPECT_LT(p.w, 1.0f);
    }
}

TEST(DustPassGen, ZeroCountProducesEmptyBuffer) {
    auto particles = renderer::generate_dust_particles(1u, 0, 40.0f);
    EXPECT_TRUE(particles.empty());
}

TEST(DustPassGen, DifferentSeedsProduceDifferentBuffers) {
    auto a = renderer::generate_dust_particles(1u, 50, 40.0f);
    auto b = renderer::generate_dust_particles(2u, 50, 40.0f);
    ASSERT_EQ(a.size(), b.size());
    bool any_diff = false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (a[i] != b[i]) { any_diff = true; break; }
    }
    EXPECT_TRUE(any_diff);
}

TEST(DustPassWrap, WrappedLocalAlwaysInsideCube) {
    const float R = 40.0f;
    // A grid of arbitrary (particle, camera) pairs spanning several
    // sphere-widths in both directions.
    for (float px = -200.0f; px <= 200.0f; px += 37.0f) {
        for (float cx = -200.0f; cx <= 200.0f; cx += 41.0f) {
            const auto local = renderer::wrap_local_for_test(
                {px, 0.0f, 0.0f}, {cx, 0.0f, 0.0f}, R);
            EXPECT_GE(local.x, -R);
            EXPECT_LT(local.x,  R);
        }
    }
}

TEST(DustPassWrap, ZeroCameraOffsetIsIdentityInsideSphere) {
    const float R = 40.0f;
    const glm::vec3 inside(10.0f, -5.0f, 15.0f);
    const auto local = renderer::wrap_local_for_test(inside,
                                                     glm::vec3(0.0f), R);
    EXPECT_FLOAT_EQ(local.x, inside.x);
    EXPECT_FLOAT_EQ(local.y, inside.y);
    EXPECT_FLOAT_EQ(local.z, inside.z);
}

// --- GL-context smoke tests below ----------------------------------------

#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace {

class DustPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        window = std::make_unique<renderer::Window>(256, 256, "dust_test", false);
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(DustPassGLTest, RenderProducesNoGLError) {
    renderer::DustPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    // First call: have_prev_ false, velocity = 0; no streaks.
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // Second call: real dt, velocity = 0 (eye unchanged).
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DustPassGLTest, DisabledPassDoesNothing) {
    renderer::DustPass pass;
    pass.set_enabled(false);
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DustPassGLTest, SetDensityZeroIsSafe) {
    renderer::DustPass pass;
    pass.set_density(0);
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
