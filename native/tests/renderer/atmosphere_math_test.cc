// native/tests/renderer/atmosphere_math_test.cc
#include <renderer/atmosphere_math.h>
#include <renderer/frame.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <cmath>
#include <limits>

namespace pa = renderer::planet_atmo;
static const float kInf = std::numeric_limits<float>::infinity();
static pa::Shell shell() { return {glm::vec3(0.0f), 100.0f, 106.0f}; }
static pa::Params params() { return {glm::vec3(1.0f), 0.06f, 1.4f}; }

TEST(AirSpan, MissesEntirely) {
    auto s = pa::air_span(shell(), {0, -500, 200}, {0, 1, 0}, kInf);
    EXPECT_FALSE(s.hit);
}

TEST(AirSpan, GrazesShellOnly) {
    // Ray at height 103 (between planet and top): passes through air, never the planet.
    auto s = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    const float half = std::sqrt(106.0f * 106.0f - 103.0f * 103.0f);
    EXPECT_NEAR(s.t0, 500.0f - half, 1e-2f);
    EXPECT_NEAR(s.t1, 500.0f + half, 1e-2f);
}

TEST(AirSpan, EndsAtThePlanetSurface) {
    auto s = pa::air_span(shell(), {-500, 0, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_NEAR(s.t0, 500.0f - 106.0f, 1e-3f);
    EXPECT_NEAR(s.t1, 500.0f - 100.0f, 1e-3f);
}

TEST(AirSpan, CameraInsideShellStartsAtTheCamera) {
    auto s = pa::air_span(shell(), {0, 103, 0}, {1, 0, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t0, 0.0f);
    EXPECT_NEAR(s.t1, std::sqrt(106.0f * 106.0f - 103.0f * 103.0f), 1e-2f);
}

TEST(AirSpan, CameraInsideShellLookingDownEndsAtSurface) {
    auto s = pa::air_span(shell(), {0, 103, 0}, {0, -1, 0}, kInf);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t0, 0.0f);
    EXPECT_NEAR(s.t1, 3.0f, 1e-3f);
}

TEST(AirSpan, OpaqueDepthClipsTheSpan) {
    auto s = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, 480.0f);
    ASSERT_TRUE(s.hit);
    EXPECT_FLOAT_EQ(s.t1, 480.0f);
    auto none = pa::air_span(shell(), {-500, 103, 0}, {1, 0, 0}, 100.0f);
    EXPECT_FALSE(none.hit);   // the opaque surface is before the shell
}

TEST(AirSpan, Tangent) {
    auto s = pa::air_span(shell(), {-500, 106, 0}, {1, 0, 0}, kInf);
    if (s.hit) EXPECT_NEAR(s.t1 - s.t0, 0.0f, 0.5f);
}

TEST(SunTau, MatchesA256StepReferenceWithin5Percent) {
    const auto s = shell(); const auto p = params();
    const glm::vec3 x(0, 102.0f, 0), L = glm::normalize(glm::vec3(1, 0.3f, 0));
    // Reference: 256 midpoint samples to the shell exit.
    const pa::Span out = pa::air_span(s, x, L, kInf);
    ASSERT_TRUE(out.hit);
    const float len = out.t1;
    double ref = 0.0;
    for (int i = 0; i < 256; ++i) {
        const float t = (i + 0.5f) * len / 256.0f;
        ref += pa::rho(s, x + L * t) * (len / 256.0f);
    }
    ref *= pa::sigma(s, p);
    EXPECT_NEAR(pa::sun_tau(s, p, x, L), ref, 0.05 * ref);
}

TEST(SunTau, BlockedByThePlanet) {
    EXPECT_GE(pa::sun_tau(shell(), params(), {0, 101.0f, 0}, {0, -1, 0}), pa::kOpaqueTau);
}

TEST(InScatter, NightSideIsDark) {
    // Both rays run along +Z through the shell at height 103 (shell air only,
    // |z| <= sqrt(106^2-103^2) ~ 25, never the planet).
    // Lit: the ray sits on the +Y side and the sun is +Y -- every sample sees the sun.
    const auto lit = pa::in_scatter(shell(), params(), {0, 103, -500}, {0, 0, 1}, kInf, {0, 1, 0});
    // Dark: the ray sits on the +X side and the sun is -X -- every sample's sun
    // ray crosses the planet (|y|,|z| < 100), so it is in shadow.
    const auto dark = pa::in_scatter(shell(), params(), {103, 0, -500}, {0, 0, 1}, kInf, {-1, 0, 0});
    EXPECT_GT(lit.r, 0.0f);
    EXPECT_LT(dark.r, 1e-6f);
}

TEST(InScatter, FiniteForDegenerateInputs) {
    for (glm::vec3 o : {glm::vec3(0), glm::vec3(0, 100, 0), glm::vec3(0, 106, 0)}) {
        const auto v = pa::in_scatter(shell(), params(), o, {0, 1, 0}, kInf, {1, 0, 0});
        EXPECT_TRUE(std::isfinite(v.r) && std::isfinite(v.g) && std::isfinite(v.b));
    }
    const auto z = pa::in_scatter({glm::vec3(0), 100.0f, 100.0f}, params(), {0, 0, -500}, {0, 0, 1}, kInf, {1, 0, 0});
    EXPECT_TRUE(std::isfinite(z.r));
}

TEST(Phase, ForwardScatterIsStrongerThanSide) {
    EXPECT_GT(pa::phase(1.0f), pa::phase(0.0f));
    EXPECT_GT(pa::phase(0.0f), 0.0f);
}

TEST(SunDir, PointsFromPlanetToNearestSun) {
    std::vector<renderer::SunDescriptor> suns(2);
    suns[0].position = {1000, 0, 0};
    suns[1].position = {0, 50000, 0};
    const glm::vec3 d = pa::sun_dir_for({0, 0, 0}, suns, {0, 0, 1});
    EXPECT_NEAR(d.x, 1.0f, 1e-5f);
}

TEST(SunDir, NoSunsUsesFallback) {
    const glm::vec3 d = pa::sun_dir_for({0, 0, 0}, {}, {0, 0, 2});
    EXPECT_NEAR(d.z, 1.0f, 1e-5f);
    const glm::vec3 z = pa::sun_dir_for({0, 0, 0}, {}, {0, 0, 0});
    EXPECT_TRUE(std::isfinite(z.x) && glm::length(z) > 0.99f);
}
