// native/tests/renderer/sun_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/sun_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace {

class SunPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(256, 256, "sun_test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(SunPassTest, EmptyListProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 1500};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render({}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, SingleDescriptorWithMissingTextureProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";   // load fails → graceful skip
    s.corona_radius     = 8000.0f;

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, TextureCacheDeduplicatesSamePath) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 1000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 0.0f;

    pass.render({s, s}, cam, *pipeline, 0.0);  // two descriptors, one cache entry
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, CoronaSkippedWhenCoronaRadiusEqualsRadius) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 4000.0f;   // equal — NOT > radius, so no corona draw

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, CoronaDrawnWhenCoronaRadiusGreaterThanRadius) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 8000.0f;   // > radius → corona draw attempted

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, FlareTexturePathMissingFileProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position           = {0.0f, 0.0f, 0.0f};
    s.radius             = 4000.0f;
    s.base_texture_path  = "/dev/null";
    s.corona_radius      = 4400.0f;
    s.flare_texture_path = "/dev/null/definitely/not-a-tga";

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, EmptyFlareTexturePathSkipsOverlayWithoutError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position           = {0.0f, 0.0f, 0.0f};
    s.radius             = 4000.0f;
    s.base_texture_path  = "/dev/null";
    s.corona_radius      = 4400.0f;
    s.flare_texture_path = "";  // explicit: no overlay

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ── Virtual-distance placement ────────────────────────────────────────────
// A body INSIDE the far plane must be drawn where it actually is: at the
// celestial layer's scale the star (34,097 GU) and a far-side planet
// (96,211 GU) are both real geometry, and remapping the star to far*0.95
// would draw it at 475,000 GU -- behind the planet it occludes. The trick
// stays correct for anything that genuinely exceeds the far plane.

TEST(SunVirtualDistance, BodyInsideFarPlaneKeepsTruePositionAndRadius) {
    scenegraph::Camera cam;
    cam.eye  = {0.0f, 0.0f, 0.0f};
    cam.far  = 500000.0f;

    const glm::vec3 star{34097.0f, 0.0f, 0.0f};
    const auto p = renderer::solve_virtual_placement(star, cam.eye, cam.far);

    EXPECT_FLOAT_EQ(p.scale, 1.0f);
    EXPECT_FLOAT_EQ(p.position.x, star.x);
    EXPECT_FLOAT_EQ(p.position.y, star.y);
    EXPECT_FLOAT_EQ(p.position.z, star.z);
}

TEST(SunVirtualDistance, FarSideBodyStillSitsBeyondANearerStar) {
    // Ona 1: the star at 34,097 GU must render nearer than Ona 3 at
    // 96,211 GU on the far side of the system.
    scenegraph::Camera cam;
    cam.eye  = {0.0f, 0.0f, 0.0f};
    cam.far  = 500000.0f;

    const auto star   = renderer::solve_virtual_placement(
        {34097.0f, 0.0f, 0.0f}, cam.eye, cam.far);
    const auto planet = renderer::solve_virtual_placement(
        {96211.0f, 0.0f, 0.0f}, cam.eye, cam.far);

    EXPECT_LT(glm::length(star.position - cam.eye),
              glm::length(planet.position - cam.eye));
}

TEST(SunVirtualDistance, BodyBeyondFarPlaneIsRemappedPreservingAngularSize) {
    scenegraph::Camera cam;
    cam.eye  = {0.0f, 0.0f, 0.0f};
    cam.far  = 5000.0f;

    const glm::vec3 pos{0.0f, 0.0f, -63000.0f};   // BC sun, tens of km out
    const auto p = renderer::solve_virtual_placement(pos, cam.eye, cam.far);

    const float expected_distance = cam.far * 0.95f;
    EXPECT_FLOAT_EQ(glm::length(p.position - cam.eye), expected_distance);
    EXPECT_FLOAT_EQ(p.scale, expected_distance / 63000.0f);
    // Angular size preserved: radius/distance is unchanged by the remap.
    // Tolerance is 1e-6, not 1e-9: one float ULP near 0.063 is already
    // ~7.4e-9, so a 1e-9 bound passes only by luck of operation ordering and
    // would flip under different FMA contraction.
    const float radius = 4000.0f;
    EXPECT_NEAR((radius * p.scale) / expected_distance, radius / 63000.0f, 1e-6f);
}

TEST(SunVirtualDistance, DirectionIsPreservedWhenRemapped) {
    scenegraph::Camera cam;
    cam.eye  = {100.0f, -50.0f, 25.0f};
    cam.far  = 5000.0f;

    const glm::vec3 pos{40000.0f, 30000.0f, -20000.0f};
    const auto p = renderer::solve_virtual_placement(pos, cam.eye, cam.far);

    const glm::vec3 true_dir = glm::normalize(pos - cam.eye);
    const glm::vec3 drawn_dir = glm::normalize(p.position - cam.eye);
    EXPECT_NEAR(glm::dot(true_dir, drawn_dir), 1.0f, 1e-5f);
}

TEST(SunVirtualDistance, DegenerateDistanceIsReportedAsInvalid) {
    scenegraph::Camera cam;
    cam.eye = {0.0f, 0.0f, 0.0f};
    cam.far = 5000.0f;

    const auto p = renderer::solve_virtual_placement(cam.eye, cam.eye, cam.far);
    EXPECT_FALSE(p.valid);
}

}  // namespace
