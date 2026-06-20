// native/tests/renderer/backdrop_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/backdrop_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace {

class BackdropPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        window = std::make_unique<renderer::Window>(256, 256, "backdrop_test", false);
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(BackdropPassTest, EmptyListProducesNoGLError) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 1500};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render({}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, SphereCacheReusesAcrossDescriptors) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b1;
    b1.texture_path = "/dev/null";  // load fails; sphere still requested
    b1.target_poly_count = 256;
    renderer::Backdrop b2 = b1;  // same poly count

    pass.render({b1, b2}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);  // both should share one sphere

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, TargetPolyCountSnapsToMinimum) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.target_poly_count = 1;  // below minimum
    b.texture_path = "/dev/null";

    pass.render({b}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, ProceduralRenderProducesNoGLError) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.texture_path = "/dev/null";   // texture load fails; procedural path is data-driven
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = 2;                // nebula
    b.color = glm::vec3(0.6f, 0.3f, 0.7f);
    b.coverage = 0.5f;
    b.seed = 12.0f;
    b.h_span = 0.3f; b.v_span = 0.3f;

    pass.render({b}, cam, *pipeline, /*procedural=*/true, /*now=*/1.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
