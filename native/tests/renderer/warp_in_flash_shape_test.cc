// CPU twin of shaders/warp_in_flash.frag (warp-in spec 6.3): core flares
// early, ring grows, streak is one-sided along forward and retracts, and all
// three are gone at end of life. The last test pins the shader's mirrored
// constants so CPU and GLSL cannot drift.
#include <gtest/gtest.h>
#include <renderer/warp_in_flash_shape.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

using namespace renderer;

namespace {

std::string read_shader(const char* rel) {
    const auto p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT) / "native" /
                   "src" / "renderer" / "shaders" / rel;
    std::ifstream f(p);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

float ring_peak_r(float t, const WarpInFlashParams& p) {
    float best_r = 0.0f;
    float best_v = -1.0f;
    for (int i = 0; i <= 400; ++i) {
        const float r = 4.0f * static_cast<float>(i) / 400.0f;
        const float v = warp_in_ring(r, t, p);
        if (v > best_v) { best_v = v; best_r = r; }
    }
    return best_r;
}

}  // namespace

TEST(WarpInFlashShape, CorePeaksEarly) {
    const WarpInFlashParams p;
    EXPECT_GT(warp_in_core(0.0f, 0.08f, p), warp_in_core(0.0f, 0.5f, p));
    EXPECT_GT(warp_in_core(0.0f, 0.08f, p), 0.0f);
}

TEST(WarpInFlashShape, RingRadiusGrows) {
    const WarpInFlashParams p;
    EXPECT_GT(warp_in_ring(ring_peak_r(0.3f, p), 0.3f, p), 0.0f);
    EXPECT_LT(ring_peak_r(0.3f, p), ring_peak_r(0.6f, p));
}

TEST(WarpInFlashShape, StreakIsOneSidedAndForward) {
    const WarpInFlashParams p;
    EXPECT_EQ(warp_in_streak(-1.0f, 0.0f, 0.45f, p), 0.0f);
    EXPECT_GT(warp_in_streak(2.0f, 0.0f, 0.45f, p), 0.0f);
}

TEST(WarpInFlashShape, StreakRetractsByEnd) {
    const WarpInFlashParams p;
    EXPECT_EQ(warp_in_streak(0.5f, 0.0f, 0.95f, p), 0.0f);
}

TEST(WarpInFlashShape, AllZeroAtEndOfLife) {
    const WarpInFlashParams p;
    EXPECT_EQ(warp_in_core(0.0f, 1.0f, p), 0.0f);
    EXPECT_EQ(warp_in_ring(p.ring_radii, 1.0f, p), 0.0f);
    EXPECT_EQ(warp_in_streak(0.1f, 0.0f, 1.0f, p), 0.0f);
}

TEST(WarpInFlashShape, ShaderMirrorsConstants) {
    const std::string frag = read_shader("warp_in_flash.frag");
    ASSERT_FALSE(frag.empty());
    // Anchored on ';' so a drifted 0.95 cannot pass as 0.9. kRingRise and
    // kStreakEnd are the DEFAULTS of the timing params (the shader's own
    // copies document them; the live values arrive as uniforms).
    for (const char* decl : {"kCoreRise = 0.08;", "kCoreFalloff = 3.0;",
                             "kRingRise = 0.05;", "kRingBand = 0.12;",
                             "kStreakEnd = 0.9;", "kStreakThickness = 0.08;"}) {
        EXPECT_NE(frag.find(decl), std::string::npos) << decl;
    }
}

TEST(WarpInFlashShape, TimingParamsDefaultToTheConstants) {
    const WarpInFlashParams p;
    EXPECT_EQ(p.streak_end, kStreakEnd);
    EXPECT_EQ(p.ring_rise, kRingRise);
}

TEST(WarpInFlashShape, StreakEndParamMovesTheRetraction) {
    WarpInFlashParams early;
    early.streak_end = 0.5f;
    const WarpInFlashParams dflt;
    EXPECT_GT(warp_in_streak(0.5f, 0.0f, 0.6f, dflt), 0.0f);
    EXPECT_EQ(warp_in_streak(0.5f, 0.0f, 0.6f, early), 0.0f);
}

TEST(WarpInFlashShape, RingRiseParamSlowsTheFadeIn) {
    WarpInFlashParams slow;
    slow.ring_rise = 0.3f;
    const WarpInFlashParams dflt;
    const float t = 0.05f;
    const float r = dflt.ring_radii * t;   // on the ring's current radius
    EXPECT_LT(warp_in_ring(r, t, slow), warp_in_ring(r, t, dflt));
}
