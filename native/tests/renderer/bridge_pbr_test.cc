// native/tests/renderer/bridge_pbr_test.cc
//
// CPU twin of bridge.frag's PBR path (spec 2026-10-08-bridge-emitters §9):
// every formula the shader uses is pinned here, so a shader edit that drifts
// from these is a review finding, and the frame tests can assert against
// these values.
#include <gtest/gtest.h>
#include <renderer/bridge_pbr.h>
#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bloom_pass.h>

using namespace renderer;

TEST(BridgePbr, EncodeDecodeRoundTrip) {
    const glm::vec3 c{0.1f, 0.5f, 0.9f};
    const glm::vec3 r = pbr::encode(pbr::decode(c));
    EXPECT_NEAR(r.x, c.x, 1e-5f); EXPECT_NEAR(r.y, c.y, 1e-5f); EXPECT_NEAR(r.z, c.z, 1e-5f);
}

TEST(BridgePbr, GgxNdfPeaksAtNormalAndNarrowsWhenSmooth) {
    EXPECT_GT(pbr::D_ggx(1.0f, 0.2f), pbr::D_ggx(1.0f, 0.8f));
    EXPECT_GT(pbr::D_ggx(1.0f, 0.2f), pbr::D_ggx(0.9f, 0.2f));
}

TEST(BridgePbr, FresnelIsF0HeadOnAndOneAtGrazing) {
    const glm::vec3 f0{0.04f};
    EXPECT_NEAR(pbr::F_schlick(1.0f, f0).x, 0.04f, 1e-6f);
    EXPECT_NEAR(pbr::F_schlick(0.0f, f0).x, 1.0f, 1e-6f);
}

TEST(BridgePbr, MetalTakesItsF0FromTheAlbedo) {
    const glm::vec3 a{0.9f, 0.5f, 0.1f};
    EXPECT_EQ(pbr::f0_for(a, 1.0f), a);
    EXPECT_EQ(pbr::f0_for(a, 0.0f), glm::vec3(0.04f));
}

TEST(BridgePbr, SpotFalloffIsWindowedInverseSquare) {
    EXPECT_FLOAT_EQ(pbr::spot_falloff(0.0f, 100.0f), 1.0f);
    EXPECT_FLOAT_EQ(pbr::spot_falloff(100.0f, 100.0f), 0.0f);
    EXPECT_FLOAT_EQ(pbr::spot_falloff(150.0f, 100.0f), 0.0f);
    EXPECT_GT(pbr::spot_falloff(10.0f, 100.0f), pbr::spot_falloff(20.0f, 100.0f));
}

TEST(BridgePbr, SpotConeIsOneInsideZeroOutside) {
    const float ci = std::cos(glm::radians(30.0f)), co = std::cos(glm::radians(60.0f));
    EXPECT_FLOAT_EQ(pbr::spot_cone(1.0f, co, ci), 1.0f);
    EXPECT_FLOAT_EQ(pbr::spot_cone(std::cos(glm::radians(70.0f)), co, ci), 0.0f);
    const float mid = pbr::spot_cone(std::cos(glm::radians(45.0f)), co, ci);
    EXPECT_GT(mid, 0.0f); EXPECT_LT(mid, 1.0f);
}

TEST(BridgePbr, DiffuseNeverReachesBloomEvenWithPbr) {
    for (float d = 0.0f; d < 50.0f; d += 0.25f) {
        const glm::vec3 out = pbr::combine(glm::vec3(d), glm::vec3(0.0f), kBridgeLighting.diffuse_max);
        EXPECT_LT(std::max(out.x, std::max(out.y, out.z)), kBloomThreshold) << d;
    }
}

TEST(BridgePbr, SpecularAddsOnTopUncapped) {
    const glm::vec3 base = pbr::combine(glm::vec3(0.5f), glm::vec3(0.0f), kBridgeLighting.diffuse_max);
    const glm::vec3 lit = pbr::combine(glm::vec3(0.5f), glm::vec3(4.0f), kBridgeLighting.diffuse_max);
    EXPECT_GT(lit.x, base.x);
    EXPECT_GT(lit.x, kBloomThreshold);
}

TEST(BridgePbr, SpecularOcclusionIsOneWhenOpenAndFallsInCreases) {
    EXPECT_NEAR(pbr::specular_occlusion(1.0f, 1.0f, 0.5f), 1.0f, 1e-5f);
    EXPECT_LT(pbr::specular_occlusion(0.5f, 0.2f, 0.5f), 0.5f);
}

TEST(BridgePbr, BoxProjectionPointsAtTheWallThePixelSees) {
    // Probe at the origin, box ±100. A pixel at x=+90 looking +x hits the
    // wall at x=+100: the corrected direction from the probe is ~+x.
    const glm::vec3 d = pbr::box_project({90, 0, 0}, {1, 0, 0}, {-100, -100, -100},
                                         {100, 100, 100}, {0, 0, 0});
    EXPECT_NEAR(d.x, 1.0f, 1e-4f);
    // A pixel at y=+90 looking +x hits (100, 90, 0): from the probe that is
    // up-and-right, not +x — the parallax correction this exists for.
    const glm::vec3 e = pbr::box_project({0, 90, 0}, {1, 0, 0}, {-100, -100, -100},
                                         {100, 100, 100}, {0, 0, 0});
    EXPECT_GT(e.y, 0.5f);
}

TEST(BridgePbr, PrefilterMipSpansTheChain) {
    EXPECT_FLOAT_EQ(pbr::prefilter_mip(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(pbr::prefilter_mip(1.0f), float(kBridgeProbeMips - 1));
}

TEST(BridgePbr, CombineMatchesHandComputedValues) {
    // Hand-computed values from the formula to detect swapped encode/decode.
    // encode(x) = pow(x, 1/2.2), decode(x) = pow(x, 2.2)

    // decode(0.5) = 0.5^2.2 ≈ 0.217638
    const glm::vec3 decoded_half = pbr::decode(glm::vec3(0.5f));
    EXPECT_NEAR(decoded_half.x, 0.217638f, 1e-4f);

    // encode(0.5) = 0.5^(1/2.2) ≈ 0.729740
    const glm::vec3 encoded_half = pbr::encode(glm::vec3(0.5f));
    EXPECT_NEAR(encoded_half.x, 0.729740f, 1e-4f);

    // Case (a): combine(vec3(0.25), vec3(0), 0.88)
    // encode(0.25) ≈ 0.532495, below knee 0.616 → result is identity ≈ 0.5325
    const glm::vec3 result_a = pbr::combine(glm::vec3(0.25f), glm::vec3(0.0f), 0.88f);
    EXPECT_NEAR(result_a.x, 0.532495f, 1e-4f);
    EXPECT_NEAR(result_a.y, 0.532495f, 1e-4f);
    EXPECT_NEAR(result_a.z, 0.532495f, 1e-4f);

    // Case (b): combine(vec3(0.25), vec3(0.5), 0.88)
    // d = encode(0.25) ≈ 0.532495
    // ds = encode(0.75) ≈ 0.877424
    // diffuse ceiling applies to d (below knee 0.616), then spec delta added:
    // 0.532495 + (0.877424 - 0.532495) ≈ 0.877424
    const glm::vec3 result_b = pbr::combine(glm::vec3(0.25f), glm::vec3(0.5f), 0.88f);
    EXPECT_NEAR(result_b.x, 0.877424f, 1e-4f);
    EXPECT_NEAR(result_b.y, 0.877424f, 1e-4f);
    EXPECT_NEAR(result_b.z, 0.877424f, 1e-4f);
}

TEST(BridgePbr, SpecularOcclusionClampsPowBase) {
    // n_dot_v = -0.5, ao = 0.1 → base = -0.4 before clamp
    // After clamp to max(0, -0.4) = 0: pow(0, ...) = 0
    const float result = pbr::specular_occlusion(-0.5f, 0.1f, 0.5f);
    EXPECT_TRUE(std::isfinite(result));
    EXPECT_GE(result, 0.0f);
    EXPECT_LE(result, 1.0f);
}

// Final-review fix wave, finding 2: the AMBIENT diffuse weight uses the
// roughness-aware Schlick (Lagarde), so a rough dielectric is not darkened
// at grazing angles -- the default material (rough 1, metal 0) must not
// re-light the room when PBR is switched on.
TEST(BridgePbr, RoughFresnelIsF0AtEveryAngleForAFullyRoughDielectric) {
    const glm::vec3 f0{0.04f};
    for (float c = 0.0f; c <= 1.0f; c += 0.05f) {
        const glm::vec3 f = pbr::F_schlick_rough(c, f0, 1.0f);
        EXPECT_NEAR(f.x, 0.04f, 1e-6f) << c;
        EXPECT_NEAR(f.z, 0.04f, 1e-6f) << c;
    }
}

TEST(BridgePbr, RoughFresnelAtRoughnessZeroIsPlainSchlick) {
    const glm::vec3 f0s[] = {glm::vec3(0.04f), glm::vec3(0.9f, 0.5f, 0.1f)};
    for (const glm::vec3& f0 : f0s)
        for (float c = 0.0f; c <= 1.0f; c += 0.05f) {
            const glm::vec3 a = pbr::F_schlick_rough(c, f0, 0.0f);
            const glm::vec3 b = pbr::F_schlick(c, f0);
            for (int i = 0; i < 3; ++i) EXPECT_NEAR(a[i], b[i], 1e-6f) << c << " " << i;
        }
}

TEST(BridgePbr, RoughFresnelNeverBelowF0AndRisesLessWhenRough) {
    const glm::vec3 f0{0.04f};
    EXPECT_NEAR(pbr::F_schlick_rough(1.0f, f0, 0.5f).x, 0.04f, 1e-6f);   // head-on: F0
    const float smooth = pbr::F_schlick_rough(0.1f, f0, 0.1f).x;
    const float mid = pbr::F_schlick_rough(0.1f, f0, 0.5f).x;
    EXPECT_GT(smooth, mid);
    EXPECT_GE(mid, 0.04f);
}
