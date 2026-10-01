// native/tests/renderer/far_math_test.cc
// Far tier spec §1 (ladder) and §2 (haze integral).
#include <gtest/gtest.h>
#include <renderer/far_math.h>
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>

namespace far = renderer::far;

namespace {
const far::Kind kAll[] = {far::Kind::Explicit, far::Kind::ExplicitNoImpostor,
                          far::Kind::ProceduralMajor, far::Kind::ProceduralMinor};
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

TEST(FarMath, ProceduralRocksHaveNoMesh) {
    const far::TierDials d;
    for (float p : {0.3f, 1.0f, 1.75f, 5.0f, 14.0f, 40.0f}) {
        EXPECT_EQ(far::tier_weights(p, far::Kind::ProceduralMajor, d).mesh, 0.0f);
        EXPECT_EQ(far::tier_weights(p, far::Kind::ProceduralMinor, d).mesh, 0.0f);
        EXPECT_EQ(far::tier_weights(p, far::Kind::ProceduralMinor, d).impostor, 0.0f);
    }
    // Procedural major impostor fades IN over imp_hi..imp_lo (no mesh to hand to).
    EXPECT_NEAR(far::tier_weights(14.0f, far::Kind::ProceduralMajor, d).impostor, 0.5f, 1e-6f);
    EXPECT_EQ(far::tier_weights(16.0f, far::Kind::ProceduralMajor, d).impostor, 0.0f);
    // Procedural minor speck fades OUT over speck_lo..speck_hi.
    EXPECT_EQ(far::tier_weights(1.0f, far::Kind::ProceduralMinor, d).speck, 1.0f);
    EXPECT_NEAR(far::tier_weights(1.75f, far::Kind::ProceduralMinor, d).speck, 0.5f, 1e-6f);
    EXPECT_EQ(far::tier_weights(2.0f, far::Kind::ProceduralMinor, d).speck, 0.0f);
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

// Closed form vs numeric (midpoint rule, 200k steps) of int pi r^2 f(r) dr.
TEST(FarMath, CrossSectionBelowMatchesNumericIntegration) {
    const far::PowerLaw pl{0.05f, 0.7f, 2.5f};
    auto numeric = [&](float cut) {
        const double hi = std::min<double>(cut, pl.r_max);
        if (hi <= pl.r_min) return 0.0;
        const double e = 1.0 - pl.q;
        const double C = e / (std::pow(pl.r_max, e) - std::pow(pl.r_min, e));
        const int n = 200000;
        double acc = 0.0, dr = (hi - pl.r_min) / n;
        for (int i = 0; i < n; ++i) {
            const double r = pl.r_min + (i + 0.5) * dr;
            acc += M_PI * r * r * C * std::pow(r, -pl.q) * dr;
        }
        return acc;
    };
    for (float cut : {0.04f, 0.05f, 0.1f, 0.3f, 0.7f, 2.0f})
        EXPECT_NEAR(far::cross_section_below(pl, cut), numeric(cut), 1e-6) << cut;
    // Spec-derived constant used for the haze_gain default (Task 9): 0.0659 GU^2.
    EXPECT_NEAR(far::mean_cross_section(pl), 0.06586f, 2e-4f);
    // q == 3 (log branch) and q == 1 stay finite and continuous.
    EXPECT_NEAR(far::cross_section_below({0.1f, 1.0f, 3.0f}, 1.0f),
                far::cross_section_below({0.1f, 1.0f, 3.0001f}, 1.0f), 1e-4f);
}

TEST(FarMath, PowerLawCdf) {
    const far::PowerLaw pl{0.05f, 0.7f, 2.5f};
    EXPECT_EQ(far::power_law_cdf(pl, 0.01f), 0.0f);
    EXPECT_EQ(far::power_law_cdf(pl, 0.7f), 1.0f);
    EXPECT_GT(far::power_law_cdf(pl, 0.1f), 0.5f);   // steep: most rocks are small
}
