// native/tests/renderer/far_math_test.cc
// Far tier spec §1 (ladder) and the power-law size distribution.
#include <gtest/gtest.h>
#include <renderer/far_math.h>
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>

namespace far = renderer::far;

namespace {
const far::Kind kAll[] = {far::Kind::Explicit, far::Kind::ExplicitNoImpostor};
float sum(const far::TierWeights& w) { return w.mesh + w.impostor + w.speck; }
}

TEST(FarMath, ExplicitWeightsSumToOneAboveFloor) {
    const far::TierDials d;
    for (float p : {0.25f, 0.3f, 1.0f, 1.5f, 1.75f, 2.0f, 5.0f, 12.0f, 14.0f, 16.0f, 100.0f}) {
        EXPECT_NEAR(sum(far::tier_weights(p, far::Kind::Explicit, d)), 1.0f, 1e-6f) << p;
        EXPECT_NEAR(sum(far::tier_weights(p, far::Kind::ExplicitNoImpostor, d)), 1.0f, 1e-6f) << p;
    }
}

TEST(FarMath, NothingBelowFloor) {
    const far::TierDials d;
    for (far::Kind k : kAll)
        EXPECT_EQ(sum(far::tier_weights(0.2499f, k, d)), 0.0f);
}

TEST(FarMath, ExplicitLadderAtTheThresholds) {
    const far::TierDials d;
    auto w = far::tier_weights(16.0f, far::Kind::Explicit, d);
    EXPECT_EQ(w.mesh, 1.0f); EXPECT_EQ(w.impostor, 0.0f);
    w = far::tier_weights(14.0f, far::Kind::Explicit, d);
    EXPECT_NEAR(w.mesh, 0.5f, 1e-6f); EXPECT_NEAR(w.impostor, 0.5f, 1e-6f);
    w = far::tier_weights(12.0f, far::Kind::Explicit, d);
    EXPECT_EQ(w.mesh, 0.0f); EXPECT_EQ(w.impostor, 1.0f);
    w = far::tier_weights(1.75f, far::Kind::Explicit, d);
    EXPECT_NEAR(w.impostor, 0.5f, 1e-6f); EXPECT_NEAR(w.speck, 0.5f, 1e-6f);
    w = far::tier_weights(1.5f, far::Kind::Explicit, d);
    EXPECT_EQ(w.impostor, 0.0f); EXPECT_EQ(w.speck, 1.0f);
    w = far::tier_weights(0.25f, far::Kind::Explicit, d);
    EXPECT_EQ(w.speck, 1.0f);
}

TEST(FarMath, NoImpostorKeepsMeshToSpeckBand) {
    const far::TierDials d;
    auto w = far::tier_weights(5.0f, far::Kind::ExplicitNoImpostor, d);
    EXPECT_EQ(w.mesh, 1.0f); EXPECT_EQ(w.impostor, 0.0f);
    w = far::tier_weights(1.75f, far::Kind::ExplicitNoImpostor, d);
    EXPECT_NEAR(w.mesh, 0.5f, 1e-6f); EXPECT_NEAR(w.speck, 0.5f, 1e-6f);
}

// A zero-width band (imp_hi == imp_lo and/or speck_hi == speck_lo, reachable
// live by stepping the dev dials) must be a hard step, never 0/0 NaN.
TEST(FarMath, ZeroWidthBandIsAHardStepNotNaN) {
    far::TierDials d;
    d.imp_hi = 12.0f; d.imp_lo = 12.0f;
    d.speck_hi = 1.5f; d.speck_lo = 1.5f;
    for (float p : {11.0f, 12.0f, 1.5f, 1.0f}) {
        const auto w = far::tier_weights(p, far::Kind::Explicit, d);
        EXPECT_TRUE(std::isfinite(w.mesh)) << p;
        EXPECT_TRUE(std::isfinite(w.impostor)) << p;
        EXPECT_TRUE(std::isfinite(w.speck)) << p;
        EXPECT_NEAR(sum(w), 1.0f, 1e-6f) << p;
    }
    // At p == hi/lo exactly, the step should already read as "at or above".
    auto w = far::tier_weights(12.0f, far::Kind::Explicit, d);
    EXPECT_EQ(w.mesh, 1.0f);
    w = far::tier_weights(1.5f, far::Kind::Explicit, d);
    EXPECT_EQ(w.speck, 0.0f);  // 1.5 >= speck_hi==speck_lo => not speck (g == 1)
}

// Spec §1 distance table: 1080p, 35 deg vertical FOV => k ~= 1713.
TEST(FarMath, PixelsPerGuMatchesTheSpecTable) {
    const glm::mat4 proj = glm::perspective(glm::radians(35.0f), 16.0f / 9.0f, 1.0f, 1.8e6f);
    const float k = far::pixels_per_gu(proj, 1080.0f);
    EXPECT_NEAR(k, 1712.7f, 1.0f);
    // r 2 GU: mesh until ~214 GU (16 px), speck from ~2284 GU (1.5 px), gone ~13700 GU.
    EXPECT_NEAR(2.0f * k / 16.0f, 214.0f, 1.0f);
    EXPECT_NEAR(2.0f * k / 1.5f, 2284.0f, 2.0f);
    EXPECT_NEAR(2.0f * k / 0.25f, 13702.0f, 10.0f);
    // The 360 px viewscreen RTT divides every distance by 3.
    EXPECT_NEAR(far::pixels_per_gu(proj, 360.0f) * 3.0f, k, 1e-2f);
}

TEST(FarMath, LambertSpherePhase) {
    EXPECT_NEAR(far::lambert_sphere_phase(1.0f), 2.0f / 3.0f, 1e-5f);
    EXPECT_NEAR(far::lambert_sphere_phase(-1.0f), 0.0f, 1e-5f);
    EXPECT_GT(far::lambert_sphere_phase(0.0f), 0.0f);
    EXPECT_LT(far::lambert_sphere_phase(0.0f), 2.0f / 3.0f);
}

TEST(FarMath, PowerLawCdf) {
    const far::PowerLaw pl{0.05f, 0.7f, 2.5f};
    EXPECT_EQ(far::power_law_cdf(pl, 0.01f), 0.0f);
    EXPECT_EQ(far::power_law_cdf(pl, 0.7f), 1.0f);
    EXPECT_GT(far::power_law_cdf(pl, 0.1f), 0.5f);   // steep: most rocks are small
}

// q == 1 takes power_law_cdf's own log branch (int_pow with e == -1):
// CDF(r) = ln(r/r_min) / ln(r_max/r_min). Check it against the closed form
// directly, and that it stays continuous against q slightly off 1.
TEST(FarMath, PowerLawCdfLogBranchAtQEqualsOne) {
    const far::PowerLaw pl{0.1f, 1.0f, 1.0f};
    for (float r : {0.15f, 0.3f, 0.5f, 0.9f}) {
        const float analytic = static_cast<float>(std::log(r / pl.r_min) /
                                                    std::log(pl.r_max / pl.r_min));
        EXPECT_NEAR(far::power_law_cdf(pl, r), analytic, 1e-5f) << r;
    }
    EXPECT_NEAR(far::power_law_cdf(pl, 0.5f),
                far::power_law_cdf({0.1f, 1.0f, 1.0001f}, 0.5f), 1e-3f);
}
