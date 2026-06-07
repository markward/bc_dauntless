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
    // bloom_tex arg: HDR-off branch ignores it; reuse the hdr color tex as dummy.
    resolve.draw(hdr.color_texture(), hdr.color_texture());

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 64,  2);
    EXPECT_NEAR(px[1], 128, 2);
    EXPECT_NEAR(px[2], 191, 2);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The "faithful + glow" operator is identity below the knee, so a 0.5
// midtone stays near stock with HDR on (the Muted Film grade's 0.95
// exposure + faint tint land it ~124) — NOT crushed the way a full filmic
// tonemap would (ACES mapped 0.5 -> ~0.39 -> ~99). This pins that HDR-on
// does not dim BC's emissive / LDR-authored content like a film curve.
TEST_F(ResolvePassTest, HdrOnPreservesMidtoneBrightness) {
    renderer::HdrTarget hdr;
    hdr.resize(16, 16);
    hdr.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Black bloom source so bloom doesn't affect this assertion.
    renderer::HdrTarget bloom_dummy;
    bloom_dummy.resize(8, 8);
    bloom_dummy.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass r;
    r.set_hdr_enabled(true);
    r.draw(hdr.color_texture(), bloom_dummy.color_texture());

    unsigned char on[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, on);
    EXPECT_GT(on[0], 112);   // near stock — far above a filmic curve's ~99 crush
    EXPECT_LT(on[0], 132);   // and not blown out
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// At the top of the range the soft shoulder gently rolls a 1.0 input below
// pure white (shoulder(1.0) ~= 0.963 -> ~246), where HDR-off hard-clips to
// 255 — confirming the shoulder softens highlights without a hard clip.
TEST_F(ResolvePassTest, HdrOnSoftShoulderRollsTopOfRange) {
    renderer::HdrTarget hdr;
    hdr.resize(16, 16);
    hdr.bind();
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::HdrTarget bloom_dummy;
    bloom_dummy.resize(8, 8);
    bloom_dummy.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass r;
    r.set_hdr_enabled(true);
    r.draw(hdr.color_texture(), bloom_dummy.color_texture());

    unsigned char on[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, on);
    EXPECT_LT(on[0], 254);   // softened below pure white
    EXPECT_GT(on[0], 230);   // but still very bright
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(ResolvePassTest, PassthroughClampsHighlightsWhenHdrOff) {
    renderer::HdrTarget hdr; hdr.resize(16,16); hdr.bind();
    glClearColor(1.5f, 1.5f, 1.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::ResolvePass r; r.set_hdr_enabled(false);
    // bloom_tex arg: HDR-off branch ignores it; reuse the hdr color tex as dummy.
    r.draw(hdr.color_texture(), hdr.color_texture());
    unsigned char off[4]; glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,off);
    EXPECT_EQ(off[0], 255);   // passthrough clamps 1.5 -> 1.0 -> 255
}

// ── Regression: fullscreen triangle must survive the Pipeline's cull state ──
// The Pipeline enables GL_CULL_FACE with CW front faces. The fullscreen
// triangle winds CCW and would be culled as a back face → black backbuffer.
// Disable+restore in ResolvePass::draw must protect against this.
TEST_F(ResolvePassTest, DrawsWhenBackfaceCullingEnabled) {
    // Reproduce the Pipeline's GL state: CW front faces, cull back faces.
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CW);

    renderer::HdrTarget hdr;
    hdr.resize(32, 32);
    hdr.bind();
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);   // black: if the triangle is culled, this stays black
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass resolve;
    resolve.set_hdr_enabled(false);
    resolve.draw(hdr.color_texture(), hdr.color_texture());

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 64,  2);   // would be 0 (black) if the fullscreen tri is culled
    EXPECT_NEAR(px[1], 128, 2);
    EXPECT_NEAR(px[2], 191, 2);

    glDisable(GL_CULL_FACE);      // leave global state clean for other tests
}
}  // namespace
