// native/tests/renderer/debug_volume_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/debug_volume_pass.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace {

class DebugVolumePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(
                256, 256, "debug-volume-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        glViewport(0, 0, 256, 256);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
};

}  // namespace

TEST_F(DebugVolumePassTest, EmptyConeListProducesNoGLError) {
    renderer::DebugVolumePass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 10};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    pass.render(std::vector<renderer::DebugCone>{}, cam);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DebugVolumePassTest, ConeRendersWithoutGLError) {
    renderer::DebugVolumePass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 10};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::DebugCone cone;
    cone.apex = glm::vec3(0.0f, 0.0f, 0.0f);
    cone.axis = glm::vec3(0.0f, 0.0f, -1.0f);
    cone.radius = 1.0f;
    cone.length = 2.0f;
    cone.color = glm::vec3(1.0f, 0.55f, 0.1f);

    pass.render(std::vector<renderer::DebugCone>{cone}, cam);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Axis parallel to the sphere/cylinder pass's fallback "up" vector (world +Y)
// must not degenerate the Gram-Schmidt basis into a zero-length cross product.
TEST_F(DebugVolumePassTest, ConeAlongWorldUpAxisRendersWithoutGLError) {
    renderer::DebugVolumePass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 10};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::DebugCone cone;
    cone.apex = glm::vec3(0.0f);
    cone.axis = glm::vec3(0.0f, 1.0f, 0.0f);
    cone.radius = 0.5f;
    cone.length = 1.5f;

    pass.render(std::vector<renderer::DebugCone>{cone}, cam);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DebugVolumePassTest, MultipleConesRenderWithoutGLError) {
    renderer::DebugVolumePass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 10};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::DebugCone a;
    a.apex = glm::vec3(-2.0f, 0.0f, 0.0f);
    a.axis = glm::vec3(1.0f, 0.0f, 0.0f);
    renderer::DebugCone b;
    b.apex = glm::vec3(2.0f, 0.0f, 0.0f);
    b.axis = glm::vec3(-1.0f, 0.0f, 0.0f);

    pass.render(std::vector<renderer::DebugCone>{a, b}, cam);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
