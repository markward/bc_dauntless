#include <gtest/gtest.h>
#include <renderer/planet_detail_noise.h>
#include <cmath>

using namespace renderer::planet_detail;

TEST(PlanetDetailNoise, Pcg3dIsDeterministicAndMixes) {
    EXPECT_EQ(pcg3d({1u, 2u, 3u}), pcg3d({1u, 2u, 3u}));
    EXPECT_NE(pcg3d({1u, 2u, 3u}), pcg3d({1u, 2u, 4u}));
}

TEST(PlanetDetailNoise, AnalyticGradientMatchesCentralDifference) {
    for (int i = 0; i < 50; ++i) {
        glm::vec3 x(0.37f * i, 1.3f - 0.11f * i, 5.0f + 0.07f * i);
        glm::vec4 n = noised(x, 99u);
        const float e = 1e-3f;
        for (int k = 0; k < 3; ++k) {
            glm::vec3 d(0.0f); d[k] = e;
            float fd = (noised(x + d, 99u).x - noised(x - d, 99u).x) / (2 * e);
            EXPECT_NEAR(n[k + 1], fd, 2e-2f) << i << " axis " << k;
        }
    }
}

TEST(PlanetDetailNoise, FieldGradientMatchesCentralDifferenceForEveryType) {
    // R3: the gas field deliberately ignores the domain-warp Jacobian, so its
    // gradient cannot match a central difference. Only check finiteness there.
    for (int t = 1; t <= 5; ++t) {
        auto ty = static_cast<SurfaceType>(t);
        TypeParams p = default_params(ty);
        glm::vec3 x(812.0f, -3401.0f, 1203.0f);
        FieldSample s = field(ty, p, x, 7u, 1.0f, 4);
        if (ty == SurfaceType::Gas) {
            ASSERT_TRUE(std::isfinite(s.grad.x) && std::isfinite(s.grad.y) && std::isfinite(s.grad.z));
            continue;
        }
        const float e = 1e-3f * p.base_wavelength_gu;
        for (int k = 0; k < 3; ++k) {
            glm::vec3 d(0.0f); d[k] = e;
            float fd = (field(ty, p, x + d, 7u, 1.0f, 4).h - field(ty, p, x - d, 7u, 1.0f, 4).h)
                       / (2 * e / p.base_wavelength_gu);
            EXPECT_NEAR(s.grad[k], fd, 0.05f + 0.05f * std::fabs(fd)) << "type " << t << " axis " << k;
        }
    }
}

TEST(PlanetDetailNoise, FieldsFiniteAndBounded) {
    for (int t = 1; t <= 5; ++t) {
        auto ty = static_cast<SurfaceType>(t);
        TypeParams p = default_params(ty);
        for (int i = 0; i < 400; ++i) {
            glm::vec3 x(std::sin(i * 1.7f) * 3600.0f, std::cos(i * 0.3f) * 3600.0f, (i - 200) * 9.0f);
            FieldSample s = field(ty, p, x, 1u, 1.0f, p.max_octaves);
            ASSERT_TRUE(std::isfinite(s.h) && std::isfinite(s.a));
            ASSERT_TRUE(std::isfinite(s.grad.x) && std::isfinite(s.grad.y) && std::isfinite(s.grad.z));
            EXPECT_LE(std::fabs(s.h), 2.0f);
            EXPECT_GE(s.a, 0.0f); EXPECT_LE(s.a, 1.0f);
        }
    }
}

TEST(PlanetDetailNoise, SeedChangesTheField) {
    TypeParams p = default_params(SurfaceType::Rocky);
    glm::vec3 x(100.0f, 200.0f, 300.0f);
    EXPECT_NE(field(SurfaceType::Rocky, p, x, 1u, 1.0f, 6).h,
              field(SurfaceType::Rocky, p, x, 2u, 1.0f, 6).h);
}

TEST(PlanetDetailNoise, OctavesForTexel) {
    TypeParams p = default_params(SurfaceType::Rocky);   // 40 GU base, max 9
    // R1: floor(log2(40 / (2*0.1))) + 1 = floor(log2(200)) + 1 = 7 + 1 = 8.
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 0.1f), 8);
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 1.6f), 4);      // 40/3.2 = 12.5 -> floor(log2)=3, +1
    EXPECT_EQ(octaves_for_texel(p, 1.0f, 100.0f), 1);
}

TEST(PlanetDetailNoise, GnomonicRoundTrip) {
    Anchor a = make_anchor(glm::normalize(glm::vec3(0.3f, 0.5f, 0.8f)), 3600.0f);
    for (glm::vec2 xy : {glm::vec2(0, 0), glm::vec2(120.5f, -40.0f), glm::vec2(-1700.0f, 900.0f)}) {
        glm::vec3 p = from_plane(a, xy);
        EXPECT_NEAR(glm::length(p), 3600.0f, 1e-2f);
        glm::vec2 back = to_plane(a, p);
        EXPECT_NEAR(back.x, xy.x, 1e-4f * 3600.0f);
        EXPECT_NEAR(back.y, xy.y, 1e-4f * 3600.0f);
    }
}

TEST(PlanetDetailNoise, AnchorAtPoleIsOrthonormal) {
    for (glm::vec3 d : {glm::vec3(0, 0, 1), glm::vec3(0, 0, -1), glm::vec3(1e-5f, 0, 1)}) {
        Anchor a = make_anchor(glm::normalize(d), 140.0f);
        EXPECT_NEAR(glm::length(a.E), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::length(a.N), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.A, a.E), 0.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.A, a.N), 0.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(a.E, a.N), 0.0f, 1e-5f);
    }
}

TEST(PlanetDetailNoise, ShapeHashTracksBakedFieldsOnly) {
    TypeParams p = default_params(SurfaceType::Rocky);
    TypeParams q = p; q.bump = 9.0f; q.roughness = 0.9f;
    EXPECT_EQ(shape_hash(p), shape_hash(q));
    q.base_wavelength_gu = 41.0f;
    EXPECT_NE(shape_hash(p), shape_hash(q));
}

// R4 guards: each is a no-op at default params but keeps degenerate dial or
// geometry input finite.

TEST(PlanetDetailNoise, IceCrackWidthZeroStaysFinite) {
    // At q == 0 the crack noise is exactly 0, so an unguarded
    // smoothstep(0, 0, 0) divides 0 by 0.
    TypeParams p = default_params(SurfaceType::Ice);
    p.crack_width = 0.0f;
    FieldSample s = field(SurfaceType::Ice, p, glm::vec3(0.0f), 7u, 1.0f, 4);
    ASSERT_TRUE(std::isfinite(s.a));
    EXPECT_FLOAT_EQ(s.a, 1.0f);
    p.crack_width = -0.5f;
    EXPECT_TRUE(std::isfinite(field(SurfaceType::Ice, p, glm::vec3(0.0f), 7u, 1.0f, 4).a));
}

TEST(PlanetDetailNoise, MaxOctavesBelowOneClampsToOneOctave) {
    TypeParams zero = default_params(SurfaceType::Rocky);
    zero.max_octaves = 0;
    TypeParams one = zero;
    one.max_octaves = 1;
    glm::vec3 x(812.0f, -3401.0f, 1203.0f);
    FieldSample a = field(SurfaceType::Rocky, zero, x, 7u, 1.0f, 4);
    FieldSample b = field(SurfaceType::Rocky, one, x, 7u, 1.0f, 4);
    EXPECT_FLOAT_EQ(a.h, b.h);
    EXPECT_NE(a.h, 0.0f);
    EXPECT_EQ(octaves_for_texel(zero, 1.0f, 0.1f), 1);
}

TEST(PlanetDetailNoise, ToPlaneOfPointOnHorizonStaysFinite) {
    Anchor a = make_anchor(glm::vec3(0.0f, 0.0f, 1.0f), 3600.0f);
    glm::vec2 xy = to_plane(a, glm::vec3(3600.0f, 0.0f, 0.0f));   // dot(p, A) == 0 exactly
    EXPECT_TRUE(std::isfinite(xy.x) && std::isfinite(xy.y));
}

TEST(PlanetDetailNoise, AnchorOfZeroDirectionFallsBackToPlusZ) {
    Anchor a = make_anchor(glm::vec3(0.0f), 140.0f);
    EXPECT_EQ(a.A, glm::vec3(0.0f, 0.0f, 1.0f));
    EXPECT_NEAR(glm::length(a.E), 1.0f, 1e-5f);
    EXPECT_NEAR(glm::length(a.N), 1.0f, 1e-5f);
    EXPECT_NEAR(glm::dot(a.A, a.E), 0.0f, 1e-5f);
    EXPECT_NEAR(glm::dot(a.E, a.N), 0.0f, 1e-5f);
}
