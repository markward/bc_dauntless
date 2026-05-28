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

}  // namespace
