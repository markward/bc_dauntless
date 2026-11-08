// native/tests/renderer/hdr_format_test.cc
//
// The colour format of the HDR targets is chosen PER INSTANCE
// (HdrTarget/HdrMsaaTarget::set_color_format). The main scene, its MSAA twin,
// the viewscreen and DOF targets and the bloom chain run R11F_G11F_B10F (half
// the bandwidth of RGBA16F); the default stays RGBA16F because bridge AO keeps
// signed normals in an HdrTarget, and the dev nonfinite probe needs alpha and
// negatives (R11KeepsNaNAndClampsNegatives documents why).
//
// Skipped automatically when no GL context is available (headless CI).

#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/bloom_pass.h>
#include <renderer/gl_caps.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 48;

using renderer::HdrColorFormat;

class HdrFormat : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "hdr-format-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }

    static GLint texture_format(std::uint32_t tex) {
        GLint f = 0;
        glBindTexture(GL_TEXTURE_2D, tex);
        glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_INTERNAL_FORMAT, &f);
        glBindTexture(GL_TEXTURE_2D, 0);
        return f;
    }

    // The colour attachment's internal format, read through the FBO so it works
    // for the MSAA target's renderbuffer (which has no public handle).
    static GLint msaa_color_format(const renderer::HdrMsaaTarget& ms) {
        GLint rb = 0;
        glBindFramebuffer(GL_FRAMEBUFFER, ms.fbo());
        glGetFramebufferAttachmentParameteriv(
            GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
            GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, &rb);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        GLint f = 0;
        glBindRenderbuffer(GL_RENDERBUFFER, static_cast<GLuint>(rb));
        glGetRenderbufferParameteriv(GL_RENDERBUFFER,
                                     GL_RENDERBUFFER_INTERNAL_FORMAT, &f);
        glBindRenderbuffer(GL_RENDERBUFFER, 0);
        return f;
    }

    static int msaa_samples() {
        return renderer::clamp_msaa_samples(4, renderer::query_gl_caps());
    }
};

TEST_F(HdrFormat, DefaultIsRgba16f) {
    renderer::HdrTarget t;
    EXPECT_EQ(t.color_format(), HdrColorFormat::Rgba16f);
    t.resize(kW, kH);
    EXPECT_EQ(texture_format(t.color_texture()), GL_RGBA16F);

    renderer::HdrMsaaTarget ms;
    EXPECT_EQ(ms.color_format(), HdrColorFormat::Rgba16f);
    const int samples = msaa_samples();
    if (samples >= 2) {
        ms.resize(kW, kH, samples);
        ASSERT_TRUE(ms.valid());
        EXPECT_EQ(msaa_color_format(ms), GL_RGBA16F);
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(HdrFormat, R11AllocatesR11F_G11F_B10F) {
    renderer::HdrTarget t;
    t.set_color_format(HdrColorFormat::R11g11b10f);
    EXPECT_EQ(t.color_format(), HdrColorFormat::R11g11b10f);
    t.resize(kW, kH);
    EXPECT_EQ(texture_format(t.color_texture()), GL_R11F_G11F_B10F);
    glBindFramebuffer(GL_FRAMEBUFFER, t.fbo());
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER),
              static_cast<GLenum>(GL_FRAMEBUFFER_COMPLETE));
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    const int samples = msaa_samples();
    if (samples >= 2) {
        renderer::HdrMsaaTarget ms;
        ms.set_color_format(HdrColorFormat::R11g11b10f);
        EXPECT_EQ(ms.color_format(), HdrColorFormat::R11g11b10f);
        ms.resize(kW, kH, samples);
        ASSERT_TRUE(ms.valid());
        EXPECT_EQ(msaa_color_format(ms), GL_R11F_G11F_B10F);
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The size key alone would early-return: a format change must reallocate on
// the next resize even at the same size (the probe toggles mid-session).
TEST_F(HdrFormat, FormatChangeReallocatesAtSameSize) {
    renderer::HdrTarget t;
    t.resize(kW, kH);
    ASSERT_EQ(texture_format(t.color_texture()), GL_RGBA16F);
    t.set_color_format(HdrColorFormat::R11g11b10f);
    t.resize(kW, kH);
    EXPECT_EQ(texture_format(t.color_texture()), GL_R11F_G11F_B10F);
    EXPECT_EQ(t.width(), kW);
    EXPECT_EQ(t.height(), kH);
    t.set_color_format(HdrColorFormat::Rgba16f);
    t.resize(kW, kH);
    EXPECT_EQ(texture_format(t.color_texture()), GL_RGBA16F);

    // Setting the format it already has keeps the allocation.
    const std::uint32_t tex = t.color_texture();
    t.set_color_format(HdrColorFormat::Rgba16f);
    t.resize(kW, kH);
    EXPECT_EQ(t.color_texture(), tex);

    const int samples = msaa_samples();
    if (samples >= 2) {
        renderer::HdrMsaaTarget ms;
        ms.resize(kW, kH, samples);
        ASSERT_TRUE(ms.valid());
        ASSERT_EQ(msaa_color_format(ms), GL_RGBA16F);
        ms.set_color_format(HdrColorFormat::R11g11b10f);
        ms.resize(kW, kH, samples);
        ASSERT_TRUE(ms.valid());
        EXPECT_EQ(msaa_color_format(ms), GL_R11F_G11F_B10F);
        ms.set_color_format(HdrColorFormat::Rgba16f);
        ms.resize(kW, kH, samples);
        ASSERT_TRUE(ms.valid());
        EXPECT_EQ(msaa_color_format(ms), GL_RGBA16F);
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// hdr_msaa_target.cc's resolve is a colour+depth blit into g_hdr_target: the
// two share a format, and R11 into R11 must still move the colour.
TEST_F(HdrFormat, MsaaResolveSameFormatSucceeds) {
    const int samples = msaa_samples();
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrMsaaTarget ms;
    ms.set_color_format(HdrColorFormat::R11g11b10f);
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());
    renderer::HdrTarget dst;
    dst.set_color_format(HdrColorFormat::R11g11b10f);
    dst.resize(kW, kH);
    // This must really be an R11 -> R11 blit, not two RGBA16F defaults.
    ASSERT_EQ(msaa_color_format(ms), GL_R11F_G11F_B10F);
    ASSERT_EQ(texture_format(dst.color_texture()), GL_R11F_G11F_B10F);

    dst.bind();
    glClearColor(1.0f, 0.0f, 0.0f, 1.0f);   // destination starts red
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    ms.bind();
    glClearColor(0.25f, 0.5f, 3.0f, 1.0f);  // HDR blue: > 1 must survive
    glClearDepth(0.5);
    glDepthMask(GL_TRUE);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    ms.resolve_to(dst);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float px[3] = {0, 0, 0};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGB, GL_FLOAT, px);
    // 11/10-bit floats: 6/5 mantissa bits, so ~1-3% relative error.
    EXPECT_NEAR(px[0], 0.25f, 0.01f);
    EXPECT_NEAR(px[1], 0.50f, 0.02f);
    EXPECT_NEAR(px[2], 3.0f, 0.1f);
    float depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &depth);
    EXPECT_NEAR(depth, 0.5f, 1e-5f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// Why the nonfinite probe needs RGBA16F: R11F_G11F_B10F has no alpha (the
// probe's cause code reads back as 1) and is unsigned (negatives, and so -Inf,
// clamp to 0). NaN and +Inf still survive. RGBA16F keeps all of it.
//
// Written with a CLEAR, a GPU-side write like the scene's draws. Not with
// glTexSubImage2D: this Mac's CPU upload conversion turns NaN into 0 for R11F,
// which says nothing about what a rendered NaN does.
TEST_F(HdrFormat, R11KeepsNaNAndClampsNegatives) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float inf = std::numeric_limits<float>::infinity();

    auto clear_and_read = [&](HdrColorFormat fmt, float r, float g, float b, float a) {
        renderer::HdrTarget t;
        t.set_color_format(fmt);
        t.resize(1, 1);
        t.bind();
        glClearColor(r, g, b, a);
        glClear(GL_COLOR_BUFFER_BIT);
        std::vector<float> out(4, -99.0f);
        glReadPixels(0, 0, 1, 1, GL_RGBA, GL_FLOAT, out.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return out;
    };

    const std::vector<float> r11 =
        clear_and_read(HdrColorFormat::R11g11b10f, nan, -1.0f, inf, 7.0f);
    EXPECT_TRUE(std::isnan(r11[0])) << "NaN survives R11F: " << r11[0];
    EXPECT_EQ(r11[1], 0.0f) << "negative clamps to 0 in unsigned G11F";
    EXPECT_TRUE(std::isinf(r11[2]) && r11[2] > 0.0f) << "+Inf survives: " << r11[2];
    EXPECT_EQ(r11[3], 1.0f) << "no alpha: reads as 1, cause code lost";

    const std::vector<float> neg_inf =
        clear_and_read(HdrColorFormat::R11g11b10f, -inf, 2.0f, 0.5f, 1.0f);
    EXPECT_EQ(neg_inf[0], 0.0f) << "-Inf clamps to 0: the probe cannot see it";
    EXPECT_NEAR(neg_inf[1], 2.0f, 0.05f);

    const std::vector<float> f16 =
        clear_and_read(HdrColorFormat::Rgba16f, nan, -1.0f, -inf, 7.0f);
    EXPECT_TRUE(std::isnan(f16[0]));
    EXPECT_EQ(f16[1], -1.0f);
    EXPECT_TRUE(std::isinf(f16[2]) && f16[2] < 0.0f);
    EXPECT_EQ(f16[3], 7.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The bloom chain has no alpha reader, so it is always R11F_G11F_B10F.
TEST_F(HdrFormat, BloomChainIsR11) {
    renderer::HdrTarget hdr;
    hdr.set_color_format(HdrColorFormat::R11g11b10f);
    hdr.resize(kW, kW);
    hdr.bind();
    glClearColor(4.0f, 4.0f, 4.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    renderer::BloomPass bloom;
    const std::uint32_t mip0 = bloom.render(hdr.color_texture(), kW, kW);
    ASSERT_NE(mip0, 0u);
    EXPECT_EQ(texture_format(mip0), GL_R11F_G11F_B10F);
    EXPECT_EQ(texture_format(bloom.coarsest_texture()), GL_R11F_G11F_B10F);

    // Still bright after the R11 chain: the pass draws into it fine.
    std::vector<float> px(static_cast<std::size_t>(kW / 2) * (kW / 2) * 4, 0.0f);
    glBindTexture(GL_TEXTURE_2D, mip0);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, px.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    const std::size_t centre = (static_cast<std::size_t>(kW / 4) * (kW / 2) + kW / 4) * 4;
    EXPECT_GT(px[centre], 0.1f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
