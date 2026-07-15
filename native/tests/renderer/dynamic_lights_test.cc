#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

#include "renderer/dynamic_lights.h"
#include "renderer/frame.h"

using renderer::DynamicLightDescriptor;
using renderer::dynamic_light_attenuation;
using renderer::kMaxDynamicLightsPerDraw;
using renderer::segment_distance;
using renderer::select_dynamic_lights;

// ─────────────────────────────────────────────────────────────────────────
// segment_distance
// ─────────────────────────────────────────────────────────────────────────

TEST(SegmentDistance, DegenerateSegmentEqualsPointDistanceForSeveralPoints) {
    const glm::vec3 a(1.0f, 2.0f, 3.0f);
    const glm::vec3 b = a;  // degenerate: a == b
    EXPECT_NEAR(segment_distance(a, b, glm::vec3(1.0f, 2.0f, 3.0f)), 0.0f, 1e-5f);
    EXPECT_NEAR(segment_distance(a, b, glm::vec3(4.0f, 2.0f, 3.0f)), 3.0f, 1e-5f);
    EXPECT_NEAR(segment_distance(a, b, glm::vec3(1.0f, 5.0f, 3.0f)), 3.0f, 1e-5f);
    // 3-4-5 offset from the degenerate point.
    EXPECT_NEAR(segment_distance(a, b, glm::vec3(4.0f, 6.0f, 3.0f)), 5.0f, 1e-5f);
}

TEST(SegmentDistance, InteriorProjection) {
    // Segment along +X from 0 to 10; p projects to the midpoint with a
    // perpendicular offset of 3.
    const glm::vec3 a(0.0f, 0.0f, 0.0f);
    const glm::vec3 b(10.0f, 0.0f, 0.0f);
    const glm::vec3 p(5.0f, 3.0f, 0.0f);
    EXPECT_NEAR(segment_distance(a, b, p), 3.0f, 1e-5f);
}

TEST(SegmentDistance, ClampsToStartEndpoint) {
    // Projection parameter h < 0 -> clamp to a; p is offset (5,4) from a.
    const glm::vec3 a(0.0f, 0.0f, 0.0f);
    const glm::vec3 b(10.0f, 0.0f, 0.0f);
    const glm::vec3 p(-5.0f, 4.0f, 0.0f);
    const float expected = std::sqrt(25.0f + 16.0f);  // sqrt(41)
    EXPECT_NEAR(segment_distance(a, b, p), expected, 1e-4f);
}

TEST(SegmentDistance, ClampsToEndEndpoint) {
    // Projection parameter h > 1 -> clamp to b; p is offset (5,4) from b.
    const glm::vec3 a(0.0f, 0.0f, 0.0f);
    const glm::vec3 b(10.0f, 0.0f, 0.0f);
    const glm::vec3 p(15.0f, 4.0f, 0.0f);
    const float expected = std::sqrt(25.0f + 16.0f);  // sqrt(41)
    EXPECT_NEAR(segment_distance(a, b, p), expected, 1e-4f);
}

TEST(SegmentDistance, PerpendicularOffsetInterior) {
    // Vertical segment along +Y from 0 to 10; p projects to the midpoint
    // (0,5,0) with a perpendicular offset forming a 3-4-5 triangle.
    const glm::vec3 a(0.0f, 0.0f, 0.0f);
    const glm::vec3 b(0.0f, 10.0f, 0.0f);
    const glm::vec3 p(3.0f, 5.0f, 4.0f);
    EXPECT_NEAR(segment_distance(a, b, p), 5.0f, 1e-4f);
}

// ─────────────────────────────────────────────────────────────────────────
// dynamic_light_attenuation
// ─────────────────────────────────────────────────────────────────────────

TEST(DynamicLightAttenuation, AtDistanceZeroReturnsOne) {
    // w = clamp(1 - 0, 0, 1) = 1; result = 1*1 / (0 + 1) = 1.
    EXPECT_NEAR(dynamic_light_attenuation(0.0f, 10.0f), 1.0f, 1e-5f);
}

TEST(DynamicLightAttenuation, AtRadiusReturnsExactlyZero) {
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(10.0f, 10.0f), 0.0f);
}

TEST(DynamicLightAttenuation, BeyondRadiusReturnsZero) {
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(20.0f, 10.0f), 0.0f);
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(10.001f, 10.0f), 0.0f);
}

TEST(DynamicLightAttenuation, HandComputedMidpointValue) {
    // d=5, radius=10: w = 1 - (0.5)^4 = 0.9375; w^2 = 0.87890625;
    // result = 0.87890625 / (25 + 1) = 0.0338040865384615...
    EXPECT_NEAR(dynamic_light_attenuation(5.0f, 10.0f), 0.033804086538f, 1e-6f);
}

TEST(DynamicLightAttenuation, MonotoneDecreasingAcrossRange) {
    const float radius = 10.0f;
    float prev = dynamic_light_attenuation(0.0f, radius);
    for (float d = 1.0f; d <= radius; d += 1.0f) {
        const float cur = dynamic_light_attenuation(d, radius);
        EXPECT_LT(cur, prev) << "not monotone decreasing at d=" << d;
        prev = cur;
    }
}

TEST(DynamicLightAttenuation, NonPositiveRadiusReturnsZero) {
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(0.0f, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(0.0f, -1.0f), 0.0f);
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(5.0f, -1.0f), 0.0f);
}

// ─────────────────────────────────────────────────────────────────────────
// select_dynamic_lights
// ─────────────────────────────────────────────────────────────────────────

namespace {
DynamicLightDescriptor make_point_light(const glm::vec3& pos, float radius,
                                         glm::vec3 color = glm::vec3(1.0f),
                                         float intensity = 1.0f) {
    DynamicLightDescriptor l;
    l.pos_a = pos;
    l.pos_b = pos;  // degenerate segment == point light
    l.color = color;
    l.radius = radius;
    l.intensity = intensity;
    return l;
}
}  // namespace

TEST(SelectDynamicLights, DegenerateSegmentSelectionMatchesHandComputedPoint) {
    // Single light at distance 5 (3-4-5 offset) from an instance centered at
    // the origin, specified as a degenerate segment (pos_a == pos_b).
    std::vector<DynamicLightDescriptor> lights;
    lights.push_back(make_point_light(glm::vec3(3.0f, 4.0f, 0.0f), 10.0f));

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);

    ASSERT_EQ(count, 1);
    EXPECT_FLOAT_EQ(out[0].pos_a.x, 3.0f);
    EXPECT_FLOAT_EQ(out[0].pos_a.y, 4.0f);
    // Hand-computed: d=5, radius=10, color=white (luminance=1), intensity=1
    // -> score == dynamic_light_attenuation(5,10) == 0.033804086538...
    // This is asserted only via the selection outcome (the light IS chosen);
    // the exact attenuation value is separately hand-verified above.
}

TEST(SelectDynamicLights, TopFourOfSixByDistanceAreSelected) {
    // 6 point lights on the +X axis at distances 1..6 from the origin, all
    // with a large shared radius (so the attenuation window stays near 1
    // and score is dominated by 1/(d*d+1), strictly decreasing with
    // distance). Expected top 4 by score: distances 1, 2, 3, 4.
    std::vector<DynamicLightDescriptor> lights;
    for (float d = 1.0f; d <= 6.0f; d += 1.0f) {
        lights.push_back(make_point_light(glm::vec3(d, 0.0f, 0.0f), 50.0f));
    }

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);

    ASSERT_EQ(count, 4);
    std::vector<float> selected_x;
    for (int i = 0; i < count; ++i) selected_x.push_back(out[i].pos_a.x);
    std::sort(selected_x.begin(), selected_x.end());
    const std::vector<float> expected = {1.0f, 2.0f, 3.0f, 4.0f};
    ASSERT_EQ(selected_x.size(), expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
        EXPECT_FLOAT_EQ(selected_x[i], expected[i]);
    }
}

TEST(SelectDynamicLights, LightExactlyAtRadiusScoresZeroAndIsNeverSelected) {
    std::vector<DynamicLightDescriptor> lights;
    lights.push_back(make_point_light(glm::vec3(5.0f, 0.0f, 0.0f), 5.0f));

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);

    EXPECT_EQ(count, 0);
}

TEST(SelectDynamicLights, ZeroLightsReturnsCountZero) {
    std::vector<DynamicLightDescriptor> lights;
    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);
    EXPECT_EQ(count, 0);
}

TEST(SelectDynamicLights, InstanceRadiusCreditSelectsLightOtherwiseOutOfRange) {
    // Light at distance 10 from center, radius 8: 8 < 10, so a
    // zero-instance-radius query scores it 0 (out of range). With an
    // instance radius of 3, d_eff = max(0, 10 - 3) = 7 < 8, so it scores
    // positive and is selected.
    std::vector<DynamicLightDescriptor> lights;
    lights.push_back(make_point_light(glm::vec3(10.0f, 0.0f, 0.0f), 8.0f));

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out_no_credit{};
    const int count_no_credit =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out_no_credit);
    EXPECT_EQ(count_no_credit, 0);

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out_credit{};
    const int count_credit =
        select_dynamic_lights(lights, glm::vec3(0.0f), 3.0f, out_credit);
    EXPECT_EQ(count_credit, 1);
}

TEST(SelectDynamicLights, EvictionReplacesLowestWhenLaterLightScoresHigher) {
    // Insertion order gives scores [5, 6, 7, 8, 10], with the HIGHEST-scoring
    // light (10) arriving AFTER the fixed-size (K=4) array is already full.
    // All lights sit exactly at the instance center (d=0) with a large shared
    // radius, so dynamic_light_attenuation(0, radius) == 1 (w=1, d²+1=1) and
    // score == intensity * luminance(white) == intensity exactly — letting
    // intensity alone control score, deterministically, with no distance math.
    std::vector<DynamicLightDescriptor> lights;
    for (float score : {5.0f, 6.0f, 7.0f, 8.0f, 10.0f}) {
        lights.push_back(make_point_light(glm::vec3(0.0f), 100.0f,
                                           glm::vec3(1.0f), score));
    }

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);

    ASSERT_EQ(count, 4);
    std::vector<float> selected_intensity;
    for (int i = 0; i < count; ++i) selected_intensity.push_back(out[i].intensity);
    std::sort(selected_intensity.begin(), selected_intensity.end());
    // Top 4 by score are {6, 7, 8, 10} — NOT insertion order's first four
    // {5, 6, 7, 8}, which is what a broken/missing eviction branch would
    // produce (the last, highest-scoring light silently dropped).
    const std::vector<float> expected = {6.0f, 7.0f, 8.0f, 10.0f};
    ASSERT_EQ(selected_intensity.size(), expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
        EXPECT_FLOAT_EQ(selected_intensity[i], expected[i]);
    }
}

TEST(SelectDynamicLights, TenInRangeLightsReturnsExactlyCeilingAndTopK) {
    // 10 point lights on the +X axis at distances 1..10, all with a large
    // shared radius. Expected top 4 by score: distances 1, 2, 3, 4.
    std::vector<DynamicLightDescriptor> lights;
    for (float d = 1.0f; d <= 10.0f; d += 1.0f) {
        lights.push_back(make_point_light(glm::vec3(d, 0.0f, 0.0f), 1000.0f));
    }

    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> out{};
    const int count =
        select_dynamic_lights(lights, glm::vec3(0.0f), 0.0f, out);

    ASSERT_EQ(count, kMaxDynamicLightsPerDraw);
    std::vector<float> selected_x;
    for (int i = 0; i < count; ++i) selected_x.push_back(out[i].pos_a.x);
    std::sort(selected_x.begin(), selected_x.end());
    const std::vector<float> expected = {1.0f, 2.0f, 3.0f, 4.0f};
    ASSERT_EQ(selected_x.size(), expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
        EXPECT_FLOAT_EQ(selected_x[i], expected[i]);
    }
}
