// native/tests/renderer/dust_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/dust_pass.h>

#include <glm/glm.hpp>

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

TEST(DustPassGen, AllPositionsInsideCubeWithCorrectJitter) {
    const float R = 40.0f;
    auto particles = renderer::generate_dust_particles(0xABCDu, 4096, R);
    ASSERT_EQ(particles.size(), 4096u);
    bool any_outside_sphere = false;
    for (const auto& p : particles) {
        EXPECT_GE(p.x, -R); EXPECT_LE(p.x, R);
        EXPECT_GE(p.y, -R); EXPECT_LE(p.y, R);
        EXPECT_GE(p.z, -R); EXPECT_LE(p.z, R);
        EXPECT_GE(p.w, 0.0f);
        EXPECT_LT(p.w, 1.0f);
        const float r2 = p.x*p.x + p.y*p.y + p.z*p.z;
        if (r2 > R*R) any_outside_sphere = true;
    }
    // Cube distribution: ~48% of particles fall in corners outside the
    // inscribed sphere. Confirm this is happening — proves we're not
    // accidentally still seeding in a sphere.
    EXPECT_TRUE(any_outside_sphere);
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

TEST(DustInfluence, NoBodiesIsBaseline) {
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f), {}, {});
    EXPECT_FLOAT_EQ(inf.density_mult, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);
}

TEST(DustInfluence, FarBodiesAreBaseline) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(10000.0f, 0.0f, 0.0f);
    sun.radius   = 50.0f;
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 9000.0f, 0.0f, 30.0f)  // far planet
    };
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f), {sun}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);
}

TEST(DustInfluence, PlanetSurfaceHitsPeakDensity) {
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 0.0f, 0.0f, 30.0f)
    };
    // Camera exactly at the surface (distance == radius) => closeness 1.
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(30.0f, 0.0f, 0.0f), {}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kPlanetPeakMult);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);   // planets never tint
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);   // planets never push
}

TEST(DustInfluence, SunSurfaceHitsPeakDensityAndTint) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f, 50.0f, 0.0f), {sun}, {});
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kSunPeakMult);
    EXPECT_FLOAT_EQ(inf.sun_tint, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, renderer::DustPass::kSunPushMax);
    EXPECT_FLOAT_EQ(inf.sun_radius, 50.0f);
}

TEST(DustInfluence, DensityIsMonotonicWithDistance) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    const float near = renderer::compute_dust_influence(
        glm::vec3(0.0f, 80.0f, 0.0f), {sun}, {}).density_mult;
    const float mid = renderer::compute_dust_influence(
        glm::vec3(0.0f, 150.0f, 0.0f), {sun}, {}).density_mult;
    const float far = renderer::compute_dust_influence(
        glm::vec3(0.0f, 260.0f, 0.0f), {sun}, {}).density_mult; // > 5*r
    EXPECT_GT(near, mid);
    EXPECT_GT(mid, far);
    EXPECT_FLOAT_EQ(far, 1.0f);
}

TEST(DustInfluence, SunWinsOverPlanetWhenBothInRange) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 60.0f, 0.0f, 30.0f)  // planet also near camera
    };
    // Camera at the sun surface: sun closeness 1 => sun density (10x),
    // not the planet's 5x.
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f, 50.0f, 0.0f), {sun}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kSunPeakMult);
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
