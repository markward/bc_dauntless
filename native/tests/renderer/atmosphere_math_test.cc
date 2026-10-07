// native/tests/renderer/atmosphere_math_test.cc
#include <renderer/atmosphere_math.h>
#include <renderer/frame.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <algorithm>
#include <cmath>
#include <iostream>
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

// Rayleigh is chromatic (sigma * beta_r per channel, beta_r = color / max
// channel) and Mie is grey (sigma * mie in every channel); sun_tau is their
// sum per channel. Each channel must match a 256-step reference within 5%.
TEST(SunTau, MatchesA256StepReferenceWithin5Percent) {
    const auto s = shell();
    pa::Params p = params();
    p.color = glm::vec3(0.2f, 0.5f, 1.0f);
    p.mie = 0.3f;
    const glm::vec3 x(0, 102.0f, 0), L = glm::normalize(glm::vec3(1, 0.3f, 0));
    // Reference: 256 midpoint samples to the shell exit.
    const pa::Span out = pa::air_span(s, x, L, kInf);
    ASSERT_TRUE(out.hit);
    const float len = out.t1;
    double od = 0.0;
    for (int i = 0; i < 256; ++i) {
        const float t = (i + 0.5f) * len / 256.0f;
        od += pa::rho(s, x + L * t) * (len / 256.0f);
    }
    const glm::vec3 tau = pa::sun_tau(s, p, x, L);
    for (int c = 0; c < 3; ++c) {
        const double ref = od * pa::sigma(s, p) * (p.color[c] / 1.0 + p.mie);
        EXPECT_NEAR(tau[c], ref, 0.05 * ref) << "channel " << c;
    }
}

TEST(SunTau, BlockedByThePlanet) {
    const glm::vec3 tau = pa::sun_tau(shell(), params(), {0, 101.0f, 0}, {0, -1, 0});
    for (int c = 0; c < 3; ++c) EXPECT_GE(tau[c], pa::kOpaqueTau) << "channel " << c;
}

TEST(BetaRayleigh, NormalisesToTheStrongestChannelAndGuardsZero) {
    pa::Params p = params();
    p.color = glm::vec3(0.1f, 0.25f, 0.5f);
    const glm::vec3 b = pa::beta_rayleigh(p);
    EXPECT_NEAR(b.r, 0.2f, 1e-6f);
    EXPECT_NEAR(b.g, 0.5f, 1e-6f);
    EXPECT_NEAR(b.b, 1.0f, 1e-6f);
    p.color = glm::vec3(0.0f);
    const glm::vec3 z = pa::beta_rayleigh(p);
    EXPECT_EQ(z, glm::vec3(0.0f));
}

// Optical depth (max channel) of a straight ray through the shell, 256 steps.
static float ray_tau(const pa::Shell& s, const pa::Params& p, glm::vec3 o, glm::vec3 d) {
    const pa::Span sp = pa::air_span(s, o, d, kInf);
    if (!sp.hit) return 0.0f;
    double od = 0.0;
    const float ds = (sp.t1 - sp.t0) / 256.0f;
    for (int i = 0; i < 256; ++i) od += pa::rho(s, o + d * (sp.t0 + (i + 0.5f) * ds)) * ds;
    return static_cast<float>(od * pa::sigma(s, p));
}

TEST(Rayleigh, BlueColourMakesShortPathsBluer) {
    const auto s = shell();
    pa::Params p{glm::vec3(0.2f, 0.5f, 1.0f), 0.06f, 1.0f, 0.0f};
    // Short: a ray along +Z through the thin upper shell (height 105.5), sun
    // overhead and behind the camera -- low optical depth both ways.
    const glm::vec3 so(0, 105.5f, -500), sd(0, 0, 1);
    const glm::vec3 ssun = glm::normalize(glm::vec3(0, 1, -1));
    // Long: a grazing ray just above the surface (height 100.3) on the
    // terminator, the sun on the horizon (+X): long view AND sun paths.
    const glm::vec3 lo(0, 100.3f, -500), ld(0, 0, 1);
    const glm::vec3 lsun(1, 0, 0);
    ASSERT_LE(ray_tau(s, p, so, sd), 0.3f);
    ASSERT_GE(ray_tau(s, p, lo, ld), 3.0f);

    const glm::vec3 sh = pa::in_scatter(s, p, so, sd, kInf, ssun);
    const glm::vec3 lg = pa::in_scatter(s, p, lo, ld, kInf, lsun);
    ASSERT_GT(sh.b, 0.0f);
    ASSERT_GT(lg.b, 0.0f);
    const float short_rb = sh.r / sh.b;
    const float long_rb = lg.r / lg.b;
    std::cerr << "[atmosphere] Rayleigh r/b short=" << short_rb << " long=" << long_rb
              << " (tau short=" << ray_tau(s, p, so, sd) << " long=" << ray_tau(s, p, lo, ld)
              << ")\n";
    EXPECT_GT(sh.b, sh.r) << "short path is not blue";
    EXPECT_GT(long_rb, 2.0f * short_rb) << "long path does not redden";
}

TEST(Rayleigh, GreyColourIsAchromatic) {
    const pa::Params p{glm::vec3(1.0f), 0.06f, 1.4f, 0.0f};
    const glm::vec3 v = pa::in_scatter(shell(), p, {0, 101.0f, -500}, {0, 0, 1}, kInf,
                                       glm::normalize(glm::vec3(1, 1, 0)));
    ASSERT_GT(v.r, 0.0f);
    EXPECT_NEAR(v.g, v.r, 1e-5f);
    EXPECT_NEAR(v.b, v.r, 1e-5f);
}

TEST(Mie, ForwardLobeBrightensBackLitRim) {
    // The sun is straight behind the planet (+Z, the camera looks +Z); the
    // view grazes the rim at height 103, never crossing the planet.
    pa::Params none{glm::vec3(0.2f, 0.5f, 1.0f), 0.06f, 1.4f, 0.0f};
    pa::Params some = none;
    some.mie = 0.5f;
    const glm::vec3 a = pa::in_scatter(shell(), none, {0, 103, -500}, {0, 0, 1}, kInf, {0, 0, 1});
    const glm::vec3 b = pa::in_scatter(shell(), some, {0, 103, -500}, {0, 0, 1}, kInf, {0, 0, 1});
    EXPECT_GT(std::max({b.r, b.g, b.b}), std::max({a.r, a.g, a.b}));
    EXPECT_GT(b.r, a.r);
}

TEST(Phase, RayleighIsSymmetricAndMieIsForward) {
    EXPECT_NEAR(pa::rayleigh_phase(1.0f), pa::rayleigh_phase(-1.0f), 1e-7f);
    EXPECT_NEAR(pa::rayleigh_phase(0.0f), 3.0f / (16.0f * 3.14159265f), 1e-6f);
    EXPECT_GT(pa::mie_phase(1.0f), 10.0f * pa::mie_phase(0.0f));
    EXPECT_GT(pa::mie_phase(0.0f), 0.0f);
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
    // All-zero colour, no Mie: no scattering at all (and never NaN from the
    // beta_r normalisation's 0/0).
    const pa::Params black{glm::vec3(0.0f), 0.06f, 1.4f, 0.0f};
    for (glm::vec3 o : {glm::vec3(0, 103, -500), glm::vec3(0, 100, 0)}) {
        const auto v = pa::in_scatter(shell(), black, o, {0, 0, 1}, kInf, {0, 1, 0});
        EXPECT_TRUE(std::isfinite(v.r) && std::isfinite(v.g) && std::isfinite(v.b));
        EXPECT_EQ(v, glm::vec3(0.0f));
    }
    // All-zero colour with Mie: grey Mie only, finite.
    const pa::Params mie_only{glm::vec3(0.0f), 0.06f, 1.4f, 0.2f};
    const auto m = pa::in_scatter(shell(), mie_only, {0, 103, -500}, {0, 0, 1}, kInf, {0, 1, 0});
    EXPECT_TRUE(std::isfinite(m.r) && std::isfinite(m.g) && std::isfinite(m.b));
    EXPECT_GT(m.r, 0.0f);
    // Mie with a grey colour, mie = 0 on a non-grey colour: finite.
    const pa::Params no_mie{glm::vec3(0.4f, 0.7f, 1.0f), 0.06f, 1.4f, 0.0f};
    const auto n = pa::in_scatter(shell(), no_mie, {0, 100, 0}, {0, 1, 0}, kInf, {1, 0, 0});
    EXPECT_TRUE(std::isfinite(n.r) && std::isfinite(n.g) && std::isfinite(n.b));
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

// At ~1e6 GU the naive discriminant b^2 - (|oc|^2 - r^2) subtracts two ~1e12
// floats (ulp ~6e4) to get a ~1e5 result; the robust h = oc - b*d form keeps
// the shell span within 1% of the halo band thickness of a double reference.
TEST(AirSpan, FarCameraMatchesDoubleReference) {
    const pa::Shell s{glm::vec3(0.0f), 1800.0f, 1908.0f};
    const double band = s.r_top - s.r_planet;
    const glm::dvec3 eye_d(0.0, 0.0, 1.0e6);
    // Rays through the band at several impact heights (the halo pixels).
    for (double h : {1810.0, 1830.0, 1854.0, 1880.0, 1900.0}) {
        const glm::dvec3 dir_d = glm::normalize(glm::dvec3(h, 0.0, 0.0) - eye_d);
        const glm::vec3 eye = glm::vec3(eye_d);
        const glm::vec3 dir = glm::vec3(dir_d);
        // Double reference along the SAME float ray, so only the solve differs.
        const glm::dvec3 o(eye);
        const glm::dvec3 d = glm::normalize(glm::dvec3(dir));
        const double b = glm::dot(o, d);
        const glm::dvec3 hv = o - b * d;
        const double disc = double(s.r_top) * s.r_top - glm::dot(hv, hv);
        ASSERT_GT(disc, 0.0);
        const double t0 = -b - std::sqrt(disc);
        const double t1 = -b + std::sqrt(disc);
        const auto span = pa::air_span(s, eye, dir, kInf);
        ASSERT_TRUE(span.hit) << "h " << h;
        EXPECT_NEAR(span.t0, t0, 0.01 * band) << "h " << h;
        EXPECT_NEAR(span.t1, t1, 0.01 * band) << "h " << h;
    }
}
