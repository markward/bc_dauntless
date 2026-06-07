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

// ── Test 2: fully black input produces zero bloom ───────────────────────────
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

}  // namespace
