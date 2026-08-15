// native/tests/renderer/bloom_pass_test.cc
//
// GL fixture tests for renderer::BloomPass. These tests verify that the bloom
// pass spreads energy spatially (bright input → non-zero output outside source)
// and that a fully black input produces no bloom.
//
// Tests are skipped automatically when no GL context is available (headless CI).

#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/bloom_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>

namespace {

class BloomPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "bloom-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL: " << e.what();
        }
    }
};

// Helper: read back the full bloom texture (mip0, half-res 32x32 for a 64x64
// input) into a float RGBA buffer using glGetTexImage.
static std::vector<float> readback_texture(std::uint32_t tex, int w, int h) {
    std::vector<float> buf(static_cast<std::size_t>(w) * h * 4, 0.0f);
    glBindTexture(GL_TEXTURE_2D, tex);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, buf.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    return buf;
}

// ── Test 1: bright input square spreads energy beyond its bounds ────────────
// Set up a 64x64 HDR target cleared to black, then use scissor to paint a
// bright (4,4,4) square in the middle (pixels 28–35 in each axis). Run bloom.
// Assert that (a) the bright-center texel in mip0 (32x32) is clearly bright,
// and (b) a texel just outside the bright square receives real upsample energy.
TEST_F(BloomPassTest, SpreadsEnergyFromBrightTexel) {
    renderer::HdrTarget hdr;
    hdr.resize(64, 64);
    hdr.bind();

    // Clear full surface to black.
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Paint a bright 8x8 square at (28,28)→(35,35).
    glEnable(GL_SCISSOR_TEST);
    glScissor(28, 28, 8, 8);
    glClearColor(4.0f, 4.0f, 4.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);

    // Restore default framebuffer state for the bloom pass.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    renderer::BloomPass bloom;
    // Threshold = 0.5 so the bright square (4.0) passes, black (0.0) does not.
    bloom.set_threshold(0.5f);
    std::uint32_t bloom_tex = bloom.render(hdr.color_texture(), 64, 64);

    EXPECT_NE(bloom_tex, 0u);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Bloom mip0 is 32x32 (half-res). Read it back.
    // Buffer layout: row-major, index = (y*32 + x) * 4 for RGBA floats.
    auto buf = readback_texture(bloom_tex, 32, 32);

    // The bright source square covers mip0 pixels ~(14,14)-(17,17).
    //
    // Sanity: the bright-center texel must be clearly above the threshold.
    float center_r = buf[(15 * 32 + 15) * 4];
    EXPECT_GT(center_r, 1.0f)
        << "Bloom center texel (15,15) should be bright; got " << center_r;

    // Energy-spread: texel (13,13) is just outside the bright square.
    // The tent-upsample kernel reaches it with real energy (~0.81 measured),
    // well above any bilinear-bleed noise. Use 0.1 as the threshold — stable
    // and meaningful.
    float spread_r = buf[(13 * 32 + 13) * 4];
    EXPECT_GT(spread_r, 0.1f)
        << "Bloom energy expected at mip0 (13,13) just outside bright square; "
        << "got " << spread_r;

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ── Test 2: bloom still produces energy when Pipeline's cull state is active ──
// The Pipeline enables GL_CULL_FACE with CW front faces. Every fullscreen draw
// in BloomPass::render winds CCW → culled as a back face → fully black bloom.
// Disable+restore in BloomPass::render must protect against this.
TEST_F(BloomPassTest, ProducesEnergyWhenBackfaceCullingEnabled) {
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CW);

    renderer::HdrTarget hdr;
    hdr.resize(64, 64);
    hdr.bind();
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_SCISSOR_TEST); glScissor(28,28,8,8);
    glClearColor(4,4,4,1); glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);

    renderer::BloomPass bloom;
    std::uint32_t tex = bloom.render(hdr.color_texture(), 64, 64);
    ASSERT_NE(tex, 0u);

    // Read mip0 (32x32) center; with culling the fullscreen passes would all
    // be culled and the result fully black.
    std::vector<float> buf(32*32*4, -1.0f);
    glBindTexture(GL_TEXTURE_2D, tex);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, buf.data());
    float center_r = buf[(15*32+15)*4];
    EXPECT_GT(center_r, 0.5f);   // would be 0 if culled

    glDisable(GL_CULL_FACE);
}

// ── Test 3: fully black input produces zero bloom ───────────────────────────
TEST_F(BloomPassTest, BlackInputProducesNoBloom) {
    renderer::HdrTarget hdr;
    hdr.resize(64, 64);
    hdr.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    renderer::BloomPass bloom;
    bloom.set_threshold(0.1f);  // low threshold; still nothing above black
    std::uint32_t bloom_tex = bloom.render(hdr.color_texture(), 64, 64);

    EXPECT_NE(bloom_tex, 0u);

    // mip0 = 32x32
    auto buf = readback_texture(bloom_tex, 32, 32);

    // All texels should be (near-)zero.
    for (std::size_t i = 0; i < buf.size(); i += 4) {
        EXPECT_LT(buf[i],     0.01f) << "R channel non-zero at index " << i;
        EXPECT_LT(buf[i + 1], 0.01f) << "G channel non-zero at index " << i;
        EXPECT_LT(buf[i + 2], 0.01f) << "B channel non-zero at index " << i;
    }

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ── Test 4: a single non-finite texel must NOT poison the bloom chain ───────
//
// Regression test for the HDR black-square bug.
//
// Before bloom_prefilter.frag sanitised its input, ONE bad texel produced a
// hard-edged black rectangle tens of pixels across, for a single frame, at an
// unpredictable position:
//   * prefilter computed max(b - thr, 0) / max(b, 1e-5); with b == +Inf that is
//     Inf/Inf == NaN;
//   * NaN survives every weighted sum in bloom_down/bloom_up, and bilinear
//     filtering spreads it over whole texels rather than fading it, so it
//     climbs the mip chain growing a couple of texels per level;
//   * resolve.frag adds the bloom then clamps, and max(NaN, 0.0) is 0.0 on
//     IEEE-maxNum hardware -- so the block comes out pure black.
//
// The source is RGBA32F so NaN/Inf are stored bit-exactly (a render-target
// write of a too-large FINITE value may saturate instead of yielding +Inf,
// which is a separate hardware question and must not be tangled up here).
//
// Assert on the whole output: not one texel of mip0 may be non-finite.
TEST_F(BloomPassTest, NonFiniteInputDoesNotPoisonTheChain) {
    const float kNaN = std::numeric_limits<float>::quiet_NaN();
    const float kInf = std::numeric_limits<float>::infinity();

    std::uint32_t tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    std::vector<float> img(64 * 64 * 4, 0.25f);
    // One NaN texel and one +Inf texel, far apart.
    for (int c = 0; c < 3; ++c) {
        img[((20 * 64) + 20) * 4 + c] = kNaN;
        img[((44 * 64) + 44) * 4 + c] = kInf;
    }
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, 64, 64, 0,
                 GL_RGBA, GL_FLOAT, img.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);

    renderer::BloomPass bloom;
    bloom.set_threshold(0.1f);
    std::uint32_t bloom_tex = bloom.render(tex, 64, 64);
    ASSERT_NE(bloom_tex, 0u);

    auto buf = readback_texture(bloom_tex, 32, 32);   // mip0 = 32x32
    int non_finite = 0;
    for (std::size_t i = 0; i < buf.size(); ++i) {
        if (!std::isfinite(buf[i])) ++non_finite;
    }
    EXPECT_EQ(non_finite, 0)
        << non_finite << " of " << buf.size()
        << " bloom components are NaN/Inf -- the prefilter is letting "
           "non-finite values into the mip chain again";

    glDeleteTextures(1, &tex);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
