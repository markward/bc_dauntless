// native/tests/renderer/warp_in_flash_pass_test.cc
//
// GL tests for WarpInFlashPass (warp-in spec 6.3) through the REAL shaders
// (Pipeline compiles them, so a GLSL error fails here, not only at runtime):
// the flash draws additively, and a nearer depth hides it.
#include <gtest/gtest.h>
#include <renderer/warp_in_flash_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <memory>
#include <stdexcept>
#include <vector>

namespace {

constexpr int kSize = 64;

class WarpInFlashPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(kSize, kSize, "warp-in-flash-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }

    static scenegraph::Camera camera() {
        scenegraph::Camera cam;
        cam.eye    = {0.0f, 0.0f, 3.0f};
        cam.target = {0.0f, 0.0f, 0.0f};
        cam.up     = {0.0f, 1.0f, 0.0f};
        cam.aspect = 1.0f;
        return cam;
    }

    // Window depth of a point `dist` in front of the camera.
    static double window_depth_at(const scenegraph::Camera& cam, float dist) {
        const glm::vec4 clip = cam.proj_matrix() * glm::vec4(0.0f, 0.0f, -dist, 1.0f);
        return 0.5 * static_cast<double>(clip.z / clip.w) + 0.5;
    }

    static renderer::WarpInFlashDescriptor flash_at_origin() {
        renderer::WarpInFlashDescriptor f;
        f.world_center = {0.0f, 0.0f, 0.0f};
        f.forward      = {1.0f, 0.0f, 0.0f};
        f.radius       = 0.2f;
        f.age          = 0.1f;
        f.lifetime     = 1.0f;
        return f;
    }

    // Summed RGB over the frame after drawing `flashes` over a black clear
    // whose depth is `clear_depth`.
    double render_sum(const std::vector<renderer::WarpInFlashDescriptor>& flashes,
                      double clear_depth) {
        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClearDepth(clear_depth);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glClearDepth(1.0);
        renderer::WarpInFlashPass pass;
        pass.render(camera(), flashes, renderer::WarpInFlashParams{}, *pipeline);
        std::vector<unsigned char> px(kSize * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        double sum = 0.0;
        for (std::size_t i = 0; i < px.size(); i += 4) {
            sum += px[i] + px[i + 1] + px[i + 2];
        }
        return sum;
    }
};

}  // namespace

TEST_F(WarpInFlashPassTest, DrawsAdditively) {
    glEnable(GL_DEPTH_TEST);
    EXPECT_GT(render_sum({flash_at_origin()}, 1.0), 0.0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(WarpInFlashPassTest, HiddenByNearerDepth) {
    // Something 1 GU in front of the camera (2 GU in front of the flash).
    // The pass must enable the depth test itself: start with it off.
    glDisable(GL_DEPTH_TEST);
    EXPECT_EQ(render_sum({flash_at_origin()}, window_depth_at(camera(), 1.0f)), 0.0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(WarpInFlashPassTest, RestoresGlState) {
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    render_sum({flash_at_origin()}, 1.0);
    EXPECT_FALSE(glIsEnabled(GL_DEPTH_TEST));
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));
    GLboolean mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &mask);
    EXPECT_EQ(mask, static_cast<GLboolean>(GL_TRUE));
    GLint func = 0;
    glGetIntegerv(GL_DEPTH_FUNC, &func);
    EXPECT_EQ(func, GL_LESS);
}
