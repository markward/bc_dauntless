// native/tests/renderer/bridge_pbr_test.cc
//
// CPU twin of bridge.frag's PBR path (spec 2026-10-08-bridge-emitters §9):
// every formula the shader uses is pinned here, so a shader edit that drifts
// from these is a review finding, and the frame tests can assert against
// these values.
#include <cmath>
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

// ── Area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──

namespace {

// Analytic form factor of a rectangle a x b, receiver on the perpendicular
// through one corner at distance h, normal pointing at the rectangle.
float corner_rect_ff(float a, float b, float h) {
    const float A = a / h, B = b / h;
    const float ra = std::sqrt(1.0f + A * A), rb = std::sqrt(1.0f + B * B);
    return (A / ra * std::atan(B / ra) + B / rb * std::atan(A / rb)) /
           (2.0f * renderer::pbr::kPi);
}

// Brute force F = (1/pi) * integral over the quad of cos_r cos_l / r^2 dA.
float quadrature_ff(const glm::vec3& p, const glm::vec3& n, const glm::vec3 c[4], int steps) {
    const glm::vec3 e1 = c[1] - c[0], e2 = c[3] - c[0];
    const glm::vec3 ln = glm::normalize(glm::cross(e1, e2));
    const float dA = glm::length(e1) * glm::length(e2) / static_cast<float>(steps * steps);
    double sum = 0.0;
    for (int i = 0; i < steps; ++i) for (int j = 0; j < steps; ++j) {
        const glm::vec3 x = c[0] + e1 * ((i + 0.5f) / steps) + e2 * ((j + 0.5f) / steps);
        const glm::vec3 d = x - p;
        const float r2 = glm::dot(d, d);
        const glm::vec3 w = d / std::sqrt(r2);
        sum += static_cast<double>(std::max(glm::dot(w, n), 0.0f) *
                                   std::max(glm::dot(-w, ln), 0.0f) / r2 * dA);
    }
    return static_cast<float>(sum / renderer::pbr::kPi);
}

bool finite3(glm::vec3 a) { return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z); }

}  // namespace

TEST(BridgePbrArea, RangeWindowIsTheSpotFalloffWindow) {
    for (float d : {0.0f, 10.0f, 99.0f, 150.0f})
        EXPECT_FLOAT_EQ(renderer::pbr::range_window(d, 120.0f) / (d * d + 1.0f),
                        renderer::pbr::spot_falloff(d, 120.0f));
}

TEST(BridgePbrArea, FormFactorMatchesTheAnalyticCornerRectangle) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};   // emits +z
    EXPECT_NEAR(renderer::pbr::rect_form_factor({0, 0, 1.5f}, {0, 0, -1}, c),
                corner_rect_ff(3.0f, 2.0f, 1.5f), 2e-4f);
}

TEST(BridgePbrArea, FormFactorMatchesQuadratureWhenTheHorizonClips) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};
    const glm::vec3 p(1.0f, 0.5f, 0.4f);
    for (const glm::vec3 n : {glm::vec3(1, 0, 0), glm::normalize(glm::vec3(1, 0, -1)),
                              glm::normalize(glm::vec3(-1, 1, -0.2f)), glm::vec3(0, 0, -1)}) {
        const float f = renderer::pbr::rect_form_factor(p, n, c);
        EXPECT_NEAR(f, quadrature_ff(p, n, c, 600), 4e-3f);
        EXPECT_GT(f, 0.01f);
    }
}

TEST(BridgePbrArea, FormFactorIsOneSided) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};   // emits +z
    EXPECT_EQ(renderer::pbr::rect_form_factor({1, 1, -1}, {0, 0, 1}, c), 0.0f);
}

TEST(BridgePbrArea, CornersWindTowardTheNormal) {
    glm::vec3 c[4];
    renderer::pbr::rect_corners({0, 0, 5}, {2, 0, 0}, {0, -1, 0}, c);   // emits -z
    const glm::vec3 n = glm::normalize(glm::cross(c[1] - c[0], c[3] - c[0]));
    EXPECT_NEAR(n.z, -1.0f, 1e-6f);
}

TEST(BridgePbrArea, RepresentativePointFollowsTheReflectionThenClamps) {
    const glm::vec3 c{0, 0, 10}, u{5, 0, 0}, v{0, -5, 0};               // emits -z
    const glm::vec3 hit = renderer::pbr::rect_representative({2, 1, 0}, {0, 0, 1}, c, u, v);
    EXPECT_NEAR(glm::distance(hit, glm::vec3(2, 1, 10)), 0.0f, 1e-5f);
    const glm::vec3 far = renderer::pbr::rect_representative(
        {0, 0, 0}, glm::normalize(glm::vec3(1, 0, 1)), c, u, v);
    EXPECT_NEAR(glm::distance(far, glm::vec3(5, 0, 10)), 0.0f, 1e-4f);   // clamped to the edge
    // Pointing away from the light: the nearest point.
    const glm::vec3 away = renderer::pbr::rect_representative({2, 1, 0}, {0, 0, -1}, c, u, v);
    EXPECT_NEAR(glm::distance(away, glm::vec3(2, 1, 10)), 0.0f, 1e-5f);
}

// A small rectangle far away lights like a spot whose intensity is its
// radiance x area x cos (spec §16.1: intensity is surface brightness).
TEST(BridgePbrArea, ASmallRectLightsLikeASpotOfTheSameOutput) {
    using namespace renderer::pbr;
    const glm::vec3 p{0, 0, 0}, N{0, 0, 1};
    const glm::vec3 c{15, 0, 100}, u{0.5f, 0, 0}, v{0, -0.5f, 0};       // 1 x 1, emits -z
    const glm::vec3 V = glm::normalize(glm::vec3(-15, 0, 100));         // mirror ray hits c
    const glm::vec3 albedo{0.5f}, radiance{3.0f};
    const float rough = 0.5f, metal = 0.0f, range = 1000.0f;
    const glm::vec3 f0 = f0_for(albedo, metal);
    const float n_dot_v = glm::dot(N, V);
    const AreaTerms a = area_light(p, N, V, n_dot_v, albedo, metal, rough, f0, c, u, v,
                                   radiance, range);
    // The spot reference (accumulate_spots' formulas) at the rectangle's centre.
    const float d = glm::length(c - p);
    const glm::vec3 L = (c - p) / d;
    const float n_dot_l = glm::dot(N, L);
    const float cos_l = glm::dot(-L, glm::vec3(0, 0, -1));
    const glm::vec3 I = radiance * 1.0f * cos_l;                       // area 1
    const glm::vec3 H = glm::normalize(L + V);
    const glm::vec3 F = F_schlick(std::max(glm::dot(V, H), 0.0f), f0);
    const glm::vec3 rad = I * spot_falloff(d, range) * n_dot_l;
    const glm::vec3 diffuse = (glm::vec3(1.0f) - F) * (1.0f - metal) * albedo / kPi * rad;
    const glm::vec3 spec = D_ggx(std::max(glm::dot(N, H), 0.0f), rough) *
                           G_smith(n_dot_v, n_dot_l, rough) * F /
                           std::max(4.0f * n_dot_v * n_dot_l, 1e-4f) * rad;
    EXPECT_NEAR(a.diffuse.r / diffuse.r, 1.0f, 0.02f);
    EXPECT_NEAR(a.spec.r / spec.r, 1.0f, 0.05f);
}

TEST(BridgePbrArea, BehindTheLightOrBeyondItsRangeGivesNothing) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 c{0, 0, 10}, u{5, 0, 0}, v{0, 5, 0};                // emits +z: away
    AreaTerms a = area_light({0, 0, 0}, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                             c, u, v, glm::vec3(10.0f), 100.0f);
    EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(a.spec, glm::vec3(0.0f));
    a = area_light({0, 0, 0}, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                   c, u, -v, glm::vec3(10.0f), 9.0f);                    // facing, out of range
    EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(a.spec, glm::vec3(0.0f));
}

TEST(BridgePbrArea, AHugePanelIsBoundedByItsRadiance) {
    using namespace renderer::pbr;
    const glm::vec3 c{0, 0, 10}, u{1e4f, 0, 0}, v{0, -1e4f, 0};         // emits -z
    const glm::vec3 radiance{2.0f}, albedo{1.0f};
    const glm::vec3 N{0, 0, 1}, V{0, 0, 1};
    const AreaTerms metal = area_light({0, 0, 0}, N, V, 1.0f, albedo, 1.0f, 0.3f,
                                       f0_for(albedo, 1.0f), c, u, v, radiance, 1e6f);
    EXPECT_EQ(metal.diffuse, glm::vec3(0.0f));
    EXPECT_LE(metal.spec.r, radiance.r * 1.05f);
    const AreaTerms matte = area_light({0, 0, 0}, N, V, 1.0f, albedo, 0.0f, 1.0f,
                                       f0_for(albedo, 0.0f), c, u, v, radiance, 1e6f);
    EXPECT_NEAR(matte.diffuse.r, 0.96f * radiance.r, 0.05f);            // (1 - F) x albedo x L
}

TEST(BridgePbrArea, AReceiverOnTheLightIsFiniteZero) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 c{0, 0, 0}, u{1, 0, 0}, v{0, 1, 0};                 // emits +z
    for (const glm::vec3 p : {glm::vec3(0, 0, 0), glm::vec3(1, 1, 0), glm::vec3(0.3f, 0, 0)}) {
        const AreaTerms a = area_light(p, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                                       c, u, v, glm::vec3(5.0f), 100.0f);
        EXPECT_TRUE(finite3(a.diffuse) && finite3(a.spec));
        EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
        EXPECT_EQ(a.spec, glm::vec3(0.0f));
    }
}

// Review fix round 1, finding 1: a zero-area rectangle (u or v collapsed to
// zero) made cross(u,v) zero, so normalize() produced NaN that survived the
// behind/on-it early-out (NaN compares false to <= 0) and propagated into spec.
TEST(BridgePbrArea, AZeroSizeRectGivesFiniteZero) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 c{0, 0, 5}, N{0, 0, 1}, V{0, 0, 1}, p{0, 0, 0};
    const AreaTerms zero_u = area_light(p, N, V, 1.0f, albedo, 0.0f, 0.5f, f0,
                                        c, glm::vec3(0.0f), glm::vec3(0, 5, 0),
                                        glm::vec3(5.0f), 100.0f);
    EXPECT_TRUE(finite3(zero_u.diffuse) && finite3(zero_u.spec));
    EXPECT_EQ(zero_u.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(zero_u.spec, glm::vec3(0.0f));
    const AreaTerms zero_uv = area_light(p, N, V, 1.0f, albedo, 0.0f, 0.5f, f0,
                                         c, glm::vec3(0.0f), glm::vec3(0.0f),
                                         glm::vec3(5.0f), 100.0f);
    EXPECT_TRUE(finite3(zero_uv.diffuse) && finite3(zero_uv.spec));
    EXPECT_EQ(zero_uv.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(zero_uv.spec, glm::vec3(0.0f));
}

// Review fix round 1, finding 2: when the nearest-point direction Ln is
// exactly -V, Ln + V == 0 and normalize() of it is NaN, which fed the
// diffuse Fresnel term. N.V = 0.6 (N = (1,0,0), V = (0.6,0.8,0)); the
// rectangle's normal is V itself and p sits on the normal through the
// rectangle's centre, so the nearest-point direction is exactly -V.
TEST(BridgePbrArea, NearestPointOppositeViewGivesFiniteDiffuse) {
    using namespace renderer::pbr;
    const glm::vec3 N{1, 0, 0}, V{0.6f, 0.8f, 0.0f};
    const glm::vec3 p{3, 4, 0};
    const glm::vec3 c{0, 0, 0}, u{0, 0, 2}, v{1.6f, -1.2f, 0};      // normalize(cross(u,v)) == V
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const AreaTerms a = area_light(p, N, V, glm::dot(N, V), albedo, 0.0f, 0.5f, f0,
                                   c, u, v, glm::vec3(5.0f), 100.0f);
    EXPECT_TRUE(finite3(a.diffuse));
    EXPECT_TRUE(finite3(a.spec));
}

// Spec §16.8: a snapped strip is a chain of rectangles; at a joint
// each neighbour used to put a full highlight (DBridge Map 3: bloom blobs at
// every joint). With the joined ends flagged, the two sum to about the one
// highlight a single rectangle would give.
TEST(BridgePbrArea, JoinedSegmentsGiveOneHighlightAtTheJoint) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f), rad{40.0f};
    const glm::vec3 N{0, 0, 1};
    // A strip 0.5 wide and 40 long, 1 unit above the receiver row, emitting down.
    const glm::vec3 one_c{0, 0, 1}, one_u{20, 0, 0}, v{0, -0.25f, 0};
    const glm::vec3 a_c{-10, 0, 1}, b_c{10, 0, 1}, half_u{10, 0, 0};
    for (float x : {-0.5f, 0.0f, 0.5f}) {
        const glm::vec3 p{x, 0.3f, 0}, V = glm::normalize(glm::vec3(0.0f, 0.6f, 1.0f));
        const float nv = glm::dot(N, V);
        const float single = area_light(p, N, V, nv, albedo, 0.0f, 0.5f, f0, one_c, one_u, v,
                                        rad, 100.0f).spec.r;
        const float split = area_light(p, N, V, nv, albedo, 0.0f, 0.5f, f0, a_c, half_u, v,
                                       rad, 100.0f, 2).spec.r +
                            area_light(p, N, V, nv, albedo, 0.0f, 0.5f, f0, b_c, half_u, v,
                                       rad, 100.0f, 1).spec.r;
        const float unjoined = area_light(p, N, V, nv, albedo, 0.0f, 0.5f, f0, a_c, half_u, v,
                                          rad, 100.0f).spec.r +
                               area_light(p, N, V, nv, albedo, 0.0f, 0.5f, f0, b_c, half_u, v,
                                          rad, 100.0f).spec.r;
        EXPECT_GT(unjoined / single, 1.5f) << "x=" << x;      // the bug this guards
        EXPECT_NEAR(split / single, 1.0f, 0.2f) << "x=" << x;
    }
}

TEST(BridgePbrArea, JoinsNeverTouchTheDiffuse) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 p{9.5f, 0.3f, 0}, N{0, 0, 1}, V = glm::normalize(glm::vec3(0, 0.6f, 1));
    const AreaTerms a = area_light(p, N, V, glm::dot(N, V), albedo, 0.0f, 0.5f, f0,
                                   {0, 0, 1}, {10, 0, 0}, {0, -0.25f, 0}, glm::vec3(40.0f), 100.0f);
    const AreaTerms b = area_light(p, N, V, glm::dot(N, V), albedo, 0.0f, 0.5f, f0,
                                   {0, 0, 1}, {10, 0, 0}, {0, -0.25f, 0}, glm::vec3(40.0f), 100.0f, 3);
    EXPECT_EQ(a.diffuse, b.diffuse);
    EXPECT_LT(b.spec.r, a.spec.r);       // near a joined end the highlight is shared
}
