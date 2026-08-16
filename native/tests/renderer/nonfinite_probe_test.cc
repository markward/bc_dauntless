// native/tests/renderer/nonfinite_probe_test.cc
//
// GL fixture tests for renderer::NonfiniteProbe — the developer diagnostic that
// finds NaN/Inf texels in the HDR target.
//
// A detector whose silence has never been shown to mean anything is worse than
// no detector, because it converts "we found nothing" into false confidence.
// These tests pin down both halves: it fires on NaN and Inf, and it stays quiet
// on finite input — including finite input far larger than anything the scene
// should produce, so nobody can mistake it for a brightness threshold.
//
// The source texture is RGBA32F, not the RGBA16F the real HDR target uses. That
// is deliberate: fp32 stores NaN/Inf bit-exactly with no conversion step, so
// these tests measure the probe and nothing else. (Whether a *render-target
// write* of a too-large finite value saturates or yields +Inf is a separate,
// hardware-dependent question — it is what made the original bug so slippery —
// and it must not be tangled up in the probe's own test.)
//
// Skipped automatically when no GL context is available (headless CI).

#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/window.h>

#include <limits>
#include <memory>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

class NonfiniteProbeTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::uint32_t tex = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "nfprobe-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL: " << e.what();
        }
        glGenTextures(1, &tex);
        glBindTexture(GL_TEXTURE_2D, tex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, kW, kH, 0,
                     GL_RGBA, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D, 0);
    }

    void TearDown() override {
        if (tex) glDeleteTextures(1, &tex);
    }

    /// Upload a full RGBA32F image where every texel is `fill`, optionally
    /// overwriting the texel at (px, py) with `poison`.
    void upload(float fill, int px = -1, int py = -1, float poison = 0.0f,
                float alpha = 1.0f) {
        std::vector<float> img(static_cast<std::size_t>(kW) * kH * 4, fill);
        if (px >= 0 && py >= 0) {
            const std::size_t o = (static_cast<std::size_t>(py) * kW + px) * 4;
            img[o + 0] = poison;
            img[o + 1] = poison;
            img[o + 2] = poison;
            img[o + 3] = alpha;
        }
        glBindTexture(GL_TEXTURE_2D, tex);
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, kW, kH, GL_RGBA, GL_FLOAT,
                        img.data());
        glBindTexture(GL_TEXTURE_2D, 0);
    }
};

// ── Quiet on ordinary finite input ─────────────────────────────────────────
TEST_F(NonfiniteProbeTest, FiniteInputDoesNotTrip) {
    upload(0.5f);
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    EXPECT_FALSE(r.any);
    EXPECT_EQ(r.flagged_cells, 0);
}

// ── Quiet on ENORMOUS finite input ─────────────────────────────────────────
// The probe must test finiteness, not magnitude. If this ever starts failing,
// someone has turned it into a brightness threshold and every bright effect in
// the game will be reported as a false positive.
TEST_F(NonfiniteProbeTest, HugeFiniteInputDoesNotTrip) {
    upload(1e30f);
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    EXPECT_FALSE(r.any);
}

// ── Fires on a SINGLE NaN texel ────────────────────────────────────────────
// One texel out of 4096. The seed of the real bug is exactly this small, which
// is why the reduction inspects every texel instead of sampling.
TEST_F(NonfiniteProbeTest, SingleNaNTexelTrips) {
    upload(0.5f, 40, 24, std::numeric_limits<float>::quiet_NaN());
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    ASSERT_TRUE(r.any);
    EXPECT_EQ(r.flagged_cells, 1);
}

// ── Fires on a SINGLE +Inf texel ───────────────────────────────────────────
TEST_F(NonfiniteProbeTest, SingleInfTexelTrips) {
    upload(0.5f, 40, 24, std::numeric_limits<float>::infinity());
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    ASSERT_TRUE(r.any);
    EXPECT_EQ(r.flagged_cells, 1);
}

// ── The reported CELL points at the offending texel ─────────────────────────
// Position is the whole value of the probe: it is how you work out which effect
// emitted the poison. A detector that fires in the wrong place is no better
// than one that does not fire.
TEST_F(NonfiniteProbeTest, FlaggedCellLocatesThePoison) {
    constexpr int kPx = 40, kPy = 24;
    upload(0.5f, kPx, kPy, std::numeric_limits<float>::quiet_NaN());

    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    ASSERT_TRUE(r.any);

    // 64x64 source -> 8x8 coarse (8x8 blocks) -> grid at 1 coarse texel/cell,
    // so the flagged grid cell is simply (px/8, py/8). Cells past the 8x8
    // footprint have no source texels and stay clear.
    constexpr int kExpectX = kPx / 8;   // 5
    constexpr int kExpectY = kPy / 8;   // 3

    int found_x = -1, found_y = -1;
    for (int y = 0; y < renderer::NonfiniteProbe::kGridH; ++y) {
        for (int x = 0; x < renderer::NonfiniteProbe::kGridW; ++x) {
            if (r.grid[static_cast<std::size_t>(y) *
                       renderer::NonfiniteProbe::kGridW + x]) {
                found_x = x;
                found_y = y;
            }
        }
    }
    EXPECT_EQ(found_x, kExpectX);
    EXPECT_EQ(found_y, kExpectY);
}

// ── Does not latch ─────────────────────────────────────────────────────────
// The bug is single-frame, so a run on clean input after a dirty one must come
// back clear. A latching probe would report every subsequent frame as a hit and
// make the counters meaningless.
TEST_F(NonfiniteProbeTest, ClearsOnNextCleanFrame) {
    renderer::NonfiniteProbe probe;

    upload(0.5f, 40, 24, std::numeric_limits<float>::quiet_NaN());
    ASSERT_TRUE(probe.run(tex, kW, kH).any);

    upload(0.5f);
    const auto& clean = probe.run(tex, kW, kH);
    EXPECT_FALSE(clean.any);
    EXPECT_EQ(clean.flagged_cells, 0);
}

// ── Cause code rides through in alpha ──────────────────────────────────────
// opaque.frag parks a term code in alpha (u_nan_debug). The probe must carry
// it through two reduction stages and an R8 round-trip without drift -- a
// silently-zeroed or off-by-one code would send the hunt after the wrong term.
TEST_F(NonfiniteProbeTest, CarriesCauseCodeFromAlpha) {
    const float kNaN = std::numeric_limits<float>::quiet_NaN();
    for (int code : {1, 5, 9, 17, 255}) {
        upload(0.5f, 40, 24, kNaN, static_cast<float>(code));
        renderer::NonfiniteProbe probe;
        const auto& r = probe.run(tex, kW, kH);
        ASSERT_TRUE(r.any) << "code " << code;
        EXPECT_EQ(r.max_code, code) << "cause code drifted for " << code;
    }
}

// ── Several causes at once: highest wins, deterministically ────────────────
TEST_F(NonfiniteProbeTest, HighestCauseCodeWins) {
    const float kNaN = std::numeric_limits<float>::quiet_NaN();
    std::vector<float> img(static_cast<std::size_t>(kW) * kH * 4, 0.5f);
    auto poison = [&](int px, int py, float code) {
        const std::size_t o = (static_cast<std::size_t>(py) * kW + px) * 4;
        img[o + 0] = img[o + 1] = img[o + 2] = kNaN;
        img[o + 3] = code;
    };
    poison(8, 8, 5.0f);
    poison(48, 40, 12.0f);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, kW, kH, GL_RGBA, GL_FLOAT, img.data());
    glBindTexture(GL_TEXTURE_2D, 0);

    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    ASSERT_TRUE(r.any);
    EXPECT_EQ(r.flagged_cells, 2);
    EXPECT_EQ(r.max_code, 12);
}

// ── A poisoned ALPHA must not poison the readback ──────────────────────────
// The cause channel can itself go non-finite. clamp() is undefined for NaN, so
// the probe tests alpha explicitly and falls back to 1 ("cause not recorded")
// rather than emitting garbage that would read as a real term.
TEST_F(NonfiniteProbeTest, NonFiniteAlphaFallsBackToUnknown) {
    const float kNaN = std::numeric_limits<float>::quiet_NaN();
    upload(0.5f, 40, 24, kNaN, kNaN);
    renderer::NonfiniteProbe probe;
    const auto& r = probe.run(tex, kW, kH);
    ASSERT_TRUE(r.any);
    EXPECT_EQ(r.max_code, 1);
}

}  // namespace
