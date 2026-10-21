#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <array>
#include "renderer/plating_damage.h"
#include "scenegraph/hull_damage.h"

using scenegraph::HullDamageKind;
using scenegraph::HullDamageStore;

namespace {
std::array<float, renderer::plating::kParamCount> zero_params() {
    std::array<float, renderer::plating::kParamCount> p{};
    return p;
}
const glm::vec3 kUp{0, 0, 1};
}  // namespace

TEST(PlatingDamage, EmptyStoreGivesAnEmptyList) {
    HullDamageStore s;
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

TEST(PlatingDamage, SurfaceReachTakesTheReachMultiplier) {
    HullDamageStore s;
    s.add({1, 2, 3}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].w, 4.0f);
    EXPECT_FLOAT_EQ(l.a[0].x, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].w, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].z, 1.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 1.0f);
}

TEST(PlatingDamage, InternalKeepsItsRadiusAndHasNoFacing) {
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 10.0f, HullDamageKind::Internal);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].w, 30.0f);
    EXPECT_FLOAT_EQ(l.b[0].x, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].y, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].z, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].w, 10.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 3.0f);
}

TEST(PlatingDamage, SummedWearTurnsDoubleSidedOn) {
    auto p = zero_params();
    p[16] = 4.5f;
    p[19] = 0.9f;  // threshold 4.5 - 0.675 = 3.825
    HullDamageStore two;
    two.add({0, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    two.add({500, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    EXPECT_TRUE(renderer::plating::build_damage_list(two, p.data()).torn_possible);
    HullDamageStore one;
    one.add({0, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    EXPECT_FALSE(renderer::plating::build_damage_list(one, p.data()).torn_possible);
}

TEST(PlatingDamage, ZeroWearRecordsNeverEnterTheStore) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 50.0f, 0.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 0.0f, HullDamageKind::Internal);
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

TEST(PlatingDamage, SixtyFourRecordsAllReachTheList) {
    HullDamageStore s;
    for (int i = 0; i < 64; ++i)
        s.add({1000.0f * static_cast<float>(i), 0, 0}, kUp, 10.0f, 1.0f,
              HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 64u);
    auto p = zero_params();
    p[7] = 1.0f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 64);
}

// torn_possible's bound is the lowest breach the shader can return:
// breach * (1 - 0.4 * spread) - lumps, less the largest tear-noise lift.
TEST(PlatingDamage, TornPossibleUsesTheToughnessAndLumpFloor) {
    auto p = zero_params();
    p[7] = 0.4f;
    p[16] = 4.5f;
    p[19] = 0.9f;
    p[22] = 0.6f;
    p[23] = 1.0f;
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 2.0f, HullDamageKind::Internal);
    EXPECT_TRUE(renderer::plating::build_damage_list(s, p.data()).torn_possible);
    p[22] = 0.0f;
    p[23] = 0.0f;
    EXPECT_FALSE(renderer::plating::build_damage_list(s, p.data()).torn_possible);
}
