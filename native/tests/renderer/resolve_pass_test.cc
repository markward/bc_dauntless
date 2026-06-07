#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_target.h>
#include <renderer/resolve_pass.h>
#include <renderer/window.h>
#include <memory>

namespace {
class ResolvePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"resolve-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(ResolvePassTest, PassthroughPreservesColorWithinTolerance) {
    renderer::HdrTarget hdr;
    hdr.resize(32, 32);
    hdr.bind();
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass resolve;
    resolve.set_hdr_enabled(false);
    resolve.draw(hdr.color_texture());

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 64,  2);
    EXPECT_NEAR(px[1], 128, 2);
    EXPECT_NEAR(px[2], 191, 2);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(ResolvePassTest, TonemapCompressesHighlightsWhenHdrOn) {
    renderer::HdrTarget hdr;
    hdr.resize(16, 16);
    hdr.bind();
    glClearColor(1.5f, 1.5f, 1.5f, 1.0f);   // above 1.0 — only representable in 16F
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass r;
    r.set_hdr_enabled(true);
    r.draw(hdr.color_texture());

    unsigned char on[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, on);
    EXPECT_LT(on[0], 250);   // ACES rolls the >1.0 highlight off below pure white
    EXPECT_GT(on[0], 150);   // but it's still bright
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(ResolvePassTest, PassthroughClampsHighlightsWhenHdrOff) {
    renderer::HdrTarget hdr; hdr.resize(16,16); hdr.bind();
    glClearColor(1.5f, 1.5f, 1.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::ResolvePass r; r.set_hdr_enabled(false);
    r.draw(hdr.color_texture());
    unsigned char off[4]; glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,off);
    EXPECT_EQ(off[0], 255);   // passthrough clamps 1.5 -> 1.0 -> 255
}
}  // namespace
