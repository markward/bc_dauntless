// native/tests/renderer/nebula_atmosphere_test.cc
#include <gtest/gtest.h>
#include <renderer/nebula_atmosphere.h>
#include <cmath>

using namespace renderer::atmosphere;

namespace {
RadialProfile constant(float n, float k) {
    RadialProfile p;
    p.r = {0.0f, 1.0e7f};
    p.nebula = {n, n};
    p.k_sys = k;
    p.star_radius = 100.0f;
    p.cloud_rgb = glm::vec3(1.0f);
    p.star_rgb = glm::vec3(1.0f);
    return p;
}
}  // namespace

TEST(NebulaAtmosphere, DensityInterpolatesAndPersists) {
    RadialProfile p;
    p.r = {0.0f, 100.0f, 200.0f};
    p.nebula = {0.0f, 1.0f, 0.5f};
    EXPECT_FLOAT_EQ(density(p, 50.0f), 0.5f);
    EXPECT_FLOAT_EQ(density(p, 150.0f), 0.75f);
    EXPECT_FLOAT_EQ(density(p, 5000.0f), 0.5f);
}

TEST(NebulaAtmosphere, TauStarMatchesClosedForm) {
    const auto p = constant(0.5f, 1.0e-4f);
    EXPECT_NEAR(tau_star(p, 1100.0f), 1.0e-4f * 0.5f * 1000.0f, 1e-6f);
    EXPECT_FLOAT_EQ(tau_star(p, 50.0f), 0.0f);
}

TEST(NebulaAtmosphere, HgIsNormalised) {
    double sum = 0.0;
    const int n = 20000;
    for (int i = 0; i < n; ++i) {
        const float c = -1.0f + 2.0f * (i + 0.5f) / n;
        sum += hg(0.6f, c) * (2.0f / n) * 2.0 * M_PI;
    }
    EXPECT_NEAR(sum, 1.0, 1e-3);
}

TEST(NebulaAtmosphere, ConstantDensityTransmittanceIsClosedForm) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    // outward ray from r0 = 1000 straight out (mu = 1) for 50,000 GU
    const Segment s = reference_march(p, look, 1000.0f, 1.0f, 50000.0f, 2048);
    EXPECT_NEAR(s.transmittance.x, std::exp(-2.0e-5f * 50000.0f), 1e-3f);
}

TEST(NebulaAtmosphere, TransmittanceIsMonotonicAlongARay) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    float prev = 1.0f;
    for (float d : {1000.0f, 5000.0f, 20000.0f, 80000.0f}) {
        const float t = reference_march(p, look, 5000.0f, 0.3f, d, 1024).transmittance.x;
        EXPECT_LE(t, prev + 1e-6f);
        prev = t;
    }
}

TEST(NebulaAtmosphere, InwardRayStopsAtTheStar) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    // from r0 = 1100 straight in: only 1000 GU of cloud before the star surface
    const Segment s = reference_march(p, look, 1100.0f, -1.0f, INFINITY, 2048);
    EXPECT_NEAR(s.transmittance.x, std::exp(-2.0e-5f * 1000.0f), 1e-3f);
}

TEST(NebulaAtmosphere, FloorIntegratesFinitelyToTheFarPlane) {
    const auto p = constant(0.05f, 2.0e-5f);
    LookParams look;
    const Segment s = reference_march(p, look, 330000.0f, 1.0f, INFINITY, 4096);
    EXPECT_TRUE(std::isfinite(s.transmittance.x));
    EXPECT_GT(s.transmittance.x, 0.0f);
}

TEST(NebulaAtmosphere, ZeroRadiusIsFinite) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    const Segment s = reference_march(p, look, 0.0f, 0.0f, 10000.0f, 256);
    EXPECT_TRUE(std::isfinite(s.transmittance.x));
    EXPECT_TRUE(std::isfinite(s.inscatter.x));
}

TEST(NebulaAtmosphere, NearPlusFarEqualsWholeRay) {
    RadialProfile p;
    p.r = {0.0f, 60000.0f, 120000.0f, 240000.0f};
    p.nebula = {0.0f, 0.0f, 1.0f, 0.05f};
    p.k_sys = 2.0e-5f; p.star_radius = 2000.0f;
    p.cloud_rgb = glm::vec3(0.6f, 0.35f, 0.7f); p.star_rgb = glm::vec3(1.0f);
    LookParams look;
    const float r0 = 300000.0f, mu = -0.9f, near = 30000.0f;
    const Segment whole = reference_march(p, look, r0, mu, INFINITY, 8192);
    const Segment n = reference_march(p, look, r0, mu, near, 2048);
    // end point of the near segment, in the ray's plane
    const float x = std::sqrt(1.0f - mu * mu) * near, y = r0 + mu * near;
    const float r_end = std::sqrt(x * x + y * y);
    const float mu_end = (x * std::sqrt(1.0f - mu * mu) + y * mu) / r_end;
    const Segment f = reference_march(p, look, r_end, mu_end, INFINITY, 8192);
    const Segment c = compose(n, f);
    EXPECT_NEAR(c.transmittance.x, whole.transmittance.x, 2e-3f);
    EXPECT_NEAR(c.inscatter.x, whole.inscatter.x, 2e-2f * std::max(1e-3f, whole.inscatter.x));
}

TEST(NebulaAtmosphere, FiniteSegmentStopsAtHull) {
    const auto p = constant(1.0f, 2.0e-5f);
    LookParams look;
    const Segment a = reference_march(p, look, 5000.0f, 1.0f, INFINITY, 4096);
    const Segment b = reference_march(p, look, 45000.0f, 1.0f, INFINITY, 4096);
    const Segment direct = reference_march(p, look, 5000.0f, 1.0f, 40000.0f, 4096);
    const Segment seg = finite(a, b);
    EXPECT_NEAR(seg.transmittance.x, direct.transmittance.x, 2e-3f);
}

TEST(NebulaAtmosphere, TableMatchesReferenceAtCellCentres) {
    const auto p = constant(0.5f, 2.0e-5f);
    LookParams look;
    const Table t = build_table(p, look);
    ASSERT_EQ(static_cast<int>(t.transmittance.size()), kTableR * kTableMu);
    const int i = 40, j = 100;
    const float r = radius_of_u(static_cast<float>(i) / (kTableR - 1), look.far_gu);
    const float mu = -1.0f + 2.0f * j / (kTableMu - 1);
    const Segment ref = reference_march(p, look, r, mu, INFINITY, 512);
    EXPECT_NEAR(t.transmittance[j * kTableR + i].x, ref.transmittance.x, 1e-5f);
}

TEST(NebulaAtmosphere, UOfRadiusInvertsRadiusOfU) {
    const float far = 1.8e6f;
    for (float u : {0.0f, 0.01f, 0.25f, 0.5f, 0.9f, 1.0f}) {
        EXPECT_NEAR(u_of_radius(radius_of_u(u, far), far), u, 1e-5f) << "u=" << u;
    }
    EXPECT_FLOAT_EQ(u_of_radius(2.0f * far, far), 1.0f);   // clamps past far
    EXPECT_FLOAT_EQ(u_of_radius(-5.0f, far), 0.0f);        // and below zero
}

TEST(NebulaAtmosphere, RadialTexelsSampleDensityAndTauStar) {
    RadialProfile p;
    p.r = {0.0f, 60000.0f, 120000.0f, 240000.0f};
    p.nebula = {0.0f, 0.0f, 1.0f, 0.05f};
    p.k_sys = 2.0e-5f;
    p.star_radius = 2000.0f;
    const LookParams look;
    const auto tex = build_radial_texels(p, look);
    ASSERT_EQ(static_cast<int>(tex.size()), kRadialTexels);
    for (int i : {0, 400, 1000, 2000, kRadialTexels - 1}) {
        const float r = radius_of_u(static_cast<float>(i) / (kRadialTexels - 1), look.far_gu);
        EXPECT_FLOAT_EQ(tex[i].x, density(p, r)) << "i=" << i;
        EXPECT_FLOAT_EQ(tex[i].y, tau_star(p, r)) << "i=" << i;
    }
    // a texel inside the populated band really is non-trivial
    const int mid = static_cast<int>(u_of_radius(120000.0f, look.far_gu) * (kRadialTexels - 1));
    EXPECT_GT(tex[mid].x, 0.5f);
    EXPECT_GT(tex[mid].y, 0.0f);
}

// The far-field table goes to the GPU as OPTICAL DEPTH, not transmittance:
// real system transmittances reach ~1e-16, which neither a half float nor a
// division by a floored T survives. tau = -ln(T), clamped to <= 87.
TEST(NebulaAtmosphere, TauFromTableRoundTripsAndClampsZero) {
    Table t;
    t.transmittance = {glm::vec3(1.0f), glm::vec3(0.5f, 0.25f, 1e-16f),
                       glm::vec3(0.0f), glm::vec3(1e-30f, 1e-38f, 0.9f)};
    t.inscatter.assign(t.transmittance.size(), glm::vec3(0.0f));
    const auto tau = tau_from_table(t);
    ASSERT_EQ(tau.size(), t.transmittance.size());
    EXPECT_FLOAT_EQ(tau[0].x, 0.0f);
    for (size_t i : {size_t(0), size_t(1)}) {
        for (int c = 0; c < 3; ++c) {
            const float T = t.transmittance[i][c];
            EXPECT_NEAR(std::exp(-tau[i][c]) / T, 1.0f, 1e-5f) << i << "," << c;
        }
    }
    for (int c = 0; c < 3; ++c) EXPECT_FLOAT_EQ(tau[2][c], 87.0f);   // T = 0
    EXPECT_FLOAT_EQ(tau[3].y, 87.0f);                                // 1e-38 -> clamp
    EXPECT_NEAR(tau[3].x, -std::log(1e-30f), 1e-3f);
    for (const auto& v : tau)
        for (int c = 0; c < 3; ++c) {
            EXPECT_TRUE(std::isfinite(v[c]));
            EXPECT_GE(v[c], 0.0f);
            EXPECT_LE(v[c], 87.0f);
        }
}
