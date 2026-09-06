// native/tests/renderer/hdr_msaa_resolve_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/hdr_target.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>
#include <memory>

namespace {

constexpr int kW = 64;
constexpr int kH = 48;

class HdrMsaaResolveTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "resolve-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }

    // Clear whatever is currently bound to a known colour and depth.
    static void clear_to(float r, float g, float b, float a, float depth) {
        glClearColor(r, g, b, a);
        glClearDepth(depth);
        glDepthMask(GL_TRUE);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
};

TEST_F(HdrMsaaResolveTest, ResolvedColourMatchesSingleSampleReference) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());

    renderer::HdrTarget dst;
    dst.resize(kW, kH);

    ms.bind();
    clear_to(0.25f, 0.5f, 0.75f, 1.0f, 0.5f);
    ms.resolve_to(dst);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float px[4] = {0, 0, 0, 0};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
    EXPECT_NEAR(px[0], 0.25f, 1e-3f);
    EXPECT_NEAR(px[1], 0.50f, 1e-3f);
    EXPECT_NEAR(px[2], 0.75f, 1e-3f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// THE LOAD-BEARING TEST. glBlitFramebuffer's depth sample selection is
// implementation-defined. nebula_volumetric.frag reads this depth to
// terminate its march; if the resolve loses it, nebulae clip against hulls.
TEST_F(HdrMsaaResolveTest, ResolvedDepthMatchesSingleSampleReference) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    // Reference: a plain single-sample target cleared to the same depth.
    renderer::HdrTarget reference;
    reference.resize(kW, kH);
    reference.bind();
    clear_to(0.0f, 0.0f, 0.0f, 1.0f, 0.375f);
    float ref_depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &ref_depth);

    // Subject: multisample cleared identically, then resolved.
    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());
    renderer::HdrTarget dst;
    dst.resize(kW, kH);

    ms.bind();
    clear_to(0.0f, 0.0f, 0.0f, 1.0f, 0.375f);
    ms.resolve_to(dst);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float got_depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &got_depth);

    // 24-bit depth: one LSB is ~6e-8. 1e-5 is loose enough for the format and
    // far tighter than any plausible wrong-sample or dropped-blit result.
    EXPECT_NEAR(got_depth, ref_depth, 1e-5f);
    EXPECT_NEAR(got_depth, 0.375f, 1e-5f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// The resolve must actually write. Without this, a resolve_to() that silently
// did nothing would still pass the two tests above if the destination
// happened to hold the expected value already.
TEST_F(HdrMsaaResolveTest, ResolveOverwritesPriorDestinationContents) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrTarget dst;
    dst.resize(kW, kH);
    dst.bind();
    clear_to(1.0f, 0.0f, 0.0f, 1.0f, 0.9f);      // destination starts RED

    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());
    ms.bind();
    clear_to(0.0f, 1.0f, 0.0f, 1.0f, 0.1f);      // source is GREEN
    ms.resolve_to(dst);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float px[4] = {0, 0, 0, 0};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
    EXPECT_NEAR(px[0], 0.0f, 1e-3f);             // red gone
    EXPECT_NEAR(px[1], 1.0f, 1e-3f);             // green arrived
    float depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &depth);
    EXPECT_NEAR(depth, 0.1f, 1e-5f);             // depth overwritten too
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

TEST_F(HdrMsaaResolveTest, MismatchedSizeIsANoOpNotACrash) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    renderer::HdrTarget dst;
    dst.resize(kW * 2, kH);           // deliberately wrong size

    ms.bind();
    clear_to(1.0f, 0.0f, 0.0f, 1.0f, 0.5f);
    ms.resolve_to(dst);               // must not blit, must not raise GL error
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

}  // namespace
