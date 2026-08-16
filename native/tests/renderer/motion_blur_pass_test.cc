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
           inv_proj, cam_rot, glm::vec3(0), prev_vp, /*shutter=*/1.0f);

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
    m0.draw(src0.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0),
            proj*view, /*shutter=*/1.0f);
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
    m1.draw(src1.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0),
            proj*prev_view, /*shutter=*/1.0f);
    unsigned char blur[4] = {0}; glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, blur);

    EXPECT_GT(std::abs(int(blur[0]) - int(base[0])), 10);   // edge measurably smeared
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ── Shutter scale actually shortens the smear ──────────────────────────────
//
// The motion vector is a per-FRAME displacement, so at a dipped framerate the
// camera has travelled further and the blur grows -- it measures frames, not
// time. The host divides by the frame time (clamped to 1.0) to restore a fixed
// exposure duration. This proves the uniform is wired through and scales the
// result, rather than being accepted and ignored.
//
// Same yawed-previous-view setup as the smear test above, sampled at the same
// pixel, run at shutter 1.0 and 0.5.
TEST_F(MotionBlurPassTest, ShutterScaleReducesSmear) {
    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    glm::mat4 inv_proj = glm::inverse(proj);
    glm::mat3 cam_rot  = glm::mat3(glm::inverse(view));
    glm::mat4 prev_view = glm::rotate(view, glm::radians(-5.0f), glm::vec3(0,1,0));

    auto sample_at = [&](float shutter, const glm::mat4& prev_v) {
        renderer::LdrTarget src; fill_edge(src);
        glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
        glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
        renderer::MotionBlurPass m;
        m.draw(src.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0),
               proj * prev_v, shutter);
        unsigned char px[4] = {0};
        glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        return int(px[0]);
    };

    const int base = sample_at(1.0f, view);            // no motion => baseline
    const int full = sample_at(1.0f, prev_view);       // 60 fps worth of smear
    const int half = sample_at(0.5f, prev_view);       // 30 fps, normalised

    const int full_smear = std::abs(full - base);
    const int half_smear = std::abs(half - base);

    // Guards against a vacuous pass: if the setup stopped smearing at all,
    // "half smears less" would be trivially true and prove nothing.
    ASSERT_GT(full_smear, 10) << "the full-shutter case did not smear, so the "
                                 "comparison below is meaningless";
    EXPECT_LT(half_smear, full_smear)
        << "shutter 0.5 smeared as much as 1.0 (" << half_smear << " vs "
        << full_smear << ") -- u_shutter is not reaching the motion vector";
    EXPECT_GT(half_smear, 0) << "shutter 0.5 removed the blur entirely";
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
           glm::mat3(glm::inverse(view)), glm::vec3(0), proj*view,
           /*shutter=*/1.0f);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 80);     // would be 0 if culled
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));   // pass restored cull state
    glDisable(GL_CULL_FACE); glFrontFace(GL_CCW);   // clean up for other tests
}
}  // namespace
