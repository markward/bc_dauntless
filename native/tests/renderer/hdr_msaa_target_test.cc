// native/tests/renderer/hdr_msaa_target_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>
#include <memory>

namespace {

class HdrMsaaTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "msaa-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(HdrMsaaTargetTest, CapsReportAtLeastFourSamples) {
    // Every GL 3.3+ implementation must support at least 4. If this fails the
    // context is not what we think it is.
    const renderer::GlCaps caps = renderer::query_gl_caps();
    EXPECT_GE(caps.max_samples, 4);
}

TEST_F(HdrMsaaTargetTest, ClampNeverExceedsCapsAndPassesZeroThrough) {
    renderer::GlCaps caps;
    caps.max_samples = 4;
    EXPECT_EQ(renderer::clamp_msaa_samples(0, caps), 0);   // 0 means "off"
    EXPECT_EQ(renderer::clamp_msaa_samples(2, caps), 2);
    EXPECT_EQ(renderer::clamp_msaa_samples(4, caps), 4);
    EXPECT_EQ(renderer::clamp_msaa_samples(8, caps), 4);   // clamped down
    EXPECT_EQ(renderer::clamp_msaa_samples(-3, caps), 0);  // nonsense is off
}

TEST_F(HdrMsaaTargetTest, CreatesCompleteFramebufferAtEachSampleCount) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    for (int s : {2, 4, 8}) {
        if (s > caps.max_samples) continue;
        renderer::HdrMsaaTarget t;
        t.resize(128, 96, s);
        EXPECT_TRUE(t.valid()) << "samples=" << s;
        EXPECT_EQ(t.width(), 128);
        EXPECT_EQ(t.height(), 96);
        EXPECT_EQ(t.samples(), s);
        t.bind();
        EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE)
            << "samples=" << s;
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "samples=" << s;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// NOTE on FBO names: GL recycles them. glDeleteFramebuffers frees the name and
// the next glGenFramebuffers hands the SAME integer straight back, so
// "fbo() != previous" does NOT prove a reallocation and "fbo() == previous"
// does NOT prove a no-op. These tests therefore assert observable state
// (dimensions, sample count, completeness), never name identity. The stronger
// proof that a no-op preserves contents lives in the resolve test, which can
// actually read pixels back.
TEST_F(HdrMsaaTargetTest, ResizeToSameParamsKeepsTheSameConfiguration) {
    renderer::HdrMsaaTarget t;
    t.resize(100, 100, 4);
    ASSERT_TRUE(t.valid());
    t.resize(100, 100, 4);
    EXPECT_TRUE(t.valid());
    EXPECT_EQ(t.width(), 100);
    EXPECT_EQ(t.height(), 100);
    EXPECT_EQ(t.samples(), 4);
}

TEST_F(HdrMsaaTargetTest, ChangingSampleCountAppliesTheNewCount) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    if (caps.max_samples < 4) GTEST_SKIP() << "needs 4x";
    renderer::HdrMsaaTarget t;
    t.resize(100, 100, 2);
    ASSERT_EQ(t.samples(), 2);
    t.resize(100, 100, 4);
    EXPECT_EQ(t.samples(), 4);
    EXPECT_TRUE(t.valid());
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// Guards the destroy() path: a live target told samples < 2 must release its
// buffers and report invalid, not keep stale multisample storage around.
TEST_F(HdrMsaaTargetTest, ResizingToZeroSamplesTearsDownALiveTarget) {
    renderer::HdrMsaaTarget t;
    t.resize(100, 100, 4);
    ASSERT_TRUE(t.valid());
    t.resize(100, 100, 0);
    EXPECT_FALSE(t.valid());
    EXPECT_EQ(t.fbo(), 0u);
    EXPECT_EQ(t.samples(), 0);
}

TEST_F(HdrMsaaTargetTest, ZeroSamplesIsInvalidAndAllocatesNothing) {
    renderer::HdrMsaaTarget t;
    t.resize(128, 96, 0);
    EXPECT_FALSE(t.valid());
    EXPECT_EQ(t.fbo(), 0u);
}

}  // namespace
