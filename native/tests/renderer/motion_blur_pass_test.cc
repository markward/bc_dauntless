#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/ldr_target.h>
#include <renderer/motion_blur_pass.h>
#include <renderer/window.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <memory>

namespace {
class MotionBlurPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"mblur-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
    // Fill a 64x64 LDR target with a vertical edge: left half black, right white.
    void fill_edge(renderer::LdrTarget& t) {
        t.resize(64, 64);
        t.bind();
        glEnable(GL_SCISSOR_TEST);
        glScissor(0, 0, 32, 64);  glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
        glScissor(32, 0, 32, 64); glClearColor(1,1,1,1); glClear(GL_COLOR_BUFFER_BIT);
        glDisable(GL_SCISSOR_TEST);
    }
};

// Static camera (prev_viewproj == current) yields a ~zero motion vector, so a
// pixel deep in the black region stays black (passthrough, no smear).
TEST_F(MotionBlurPassTest, StaticCameraIsPassthrough) {
    renderer::LdrTarget src; fill_edge(src);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);

    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    glm::mat4 inv_proj = glm::inverse(proj);
    glm::mat3 cam_rot  = glm::mat3(glm::inverse(view));
    glm::mat4 prev_vp  = proj * view;   // same as current => no motion

    renderer::MotionBlurPass m;
    m.draw(src.color_texture(), /*dst_fbo=*/0, 64, 64,
           inv_proj, cam_rot, glm::vec3(0), prev_vp);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(8, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);  // deep black side
    EXPECT_LT(px[0], 8);                       // still ~black: no smear
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// A yawed previous view-projection produces a horizontal motion vector, so a
// near-edge pixel changes vs the static (passthrough) result.
TEST_F(MotionBlurPassTest, CameraRotationBlursEdge) {
    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    glm::mat4 inv_proj = glm::inverse(proj);
    glm::mat3 cam_rot  = glm::mat3(glm::inverse(view));

    // Read the near-edge pixel under no motion (passthrough baseline).
    renderer::LdrTarget src0; fill_edge(src0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::MotionBlurPass m0;
    m0.draw(src0.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0), proj*view);
    unsigned char base[4] = {0}; glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, base);

    // Now a yawed previous view => horizontal reprojection => edge smears.
    // Negative yaw: prev camera looks left-of-center, so the world point near
    // the edge appears to the right in the prev frame, pulling samples rightward
    // (toward white) and producing visible smear at pixel 30.
    glm::mat4 prev_view = glm::rotate(view, glm::radians(-5.0f), glm::vec3(0,1,0));
    renderer::LdrTarget src1; fill_edge(src1);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::MotionBlurPass m1;
    m1.draw(src1.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0), proj*prev_view);
    unsigned char blur[4] = {0}; glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, blur);

    EXPECT_GT(std::abs(int(blur[0]) - int(base[0])), 10);   // edge measurably smeared
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Regression: the fullscreen triangle must survive CW-front, back-face cull.
TEST_F(MotionBlurPassTest, DrawsWhenBackfaceCullingEnabled) {
    glEnable(GL_CULL_FACE); glCullFace(GL_BACK); glFrontFace(GL_CW);

    renderer::LdrTarget src; src.resize(32,32); src.bind();
    glClearColor(0.5f,0.5f,0.5f,1.0f); glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);   // black if culled

    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    renderer::MotionBlurPass m;
    m.draw(src.color_texture(), 0, 64, 64, glm::inverse(proj),
           glm::mat3(glm::inverse(view)), glm::vec3(0), proj*view);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 80);     // would be 0 if culled
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));   // pass restored cull state
    glDisable(GL_CULL_FACE); glFrontFace(GL_CCW);   // clean up for other tests
}
}  // namespace
