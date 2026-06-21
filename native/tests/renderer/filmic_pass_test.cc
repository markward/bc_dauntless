#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/ldr_target.h>
#include <renderer/filmic_pass.h>
#include <renderer/window.h>
#include <memory>

namespace {
class FilmicPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"filmic-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

// Center pixel: CA offset is ~0 and the vignette is ~full there, so a mid-grey
// input survives close to itself (only grain jitter). Confirms the pass runs
// GL-error-free and is roughly identity at the screen center.
TEST_F(FilmicPassTest, MidGreyCenterSurvivesWithinGrainTolerance) {
    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 128, 24);   // ~grey, within grain jitter (GRAIN_STRENGTH 0.15 → ±~19 8-bit)
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Vignette must darken the corners relative to the center on a uniform input.
TEST_F(FilmicPassTest, VignetteDarkensCorners) {
    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char center[4] = {0}, corner[4] = {0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
    glReadPixels(1,  1,  1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
    EXPECT_LT(corner[0] + 10, center[0]);   // corner clearly darker than center
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Regression: the fullscreen triangle must survive the Pipeline's CW-front,
// back-face cull state (else the screen is black).
TEST_F(FilmicPassTest, DrawsWhenBackfaceCullingEnabled) {
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CW);

    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);   // black if the triangle is culled
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 80);   // would be 0 if culled

    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));   // FilmicPass::draw must restore cull state
    glDisable(GL_CULL_FACE);   // leave global state clean
    glFrontFace(GL_CCW);          // restore default winding for other tests
}
}  // namespace
