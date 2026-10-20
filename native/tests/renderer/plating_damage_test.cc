#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <array>
#include "renderer/plating_damage.h"
#include "scenegraph/damage_decals.h"

using scenegraph::DamageDecalRing;
using scenegraph::WeaponClass;

namespace {
std::array<float, 24> zero_params() { std::array<float, 24> p{}; return p; }
}  // namespace

TEST(PlatingDamage, HeatGlowAndScuffNeverEnterTheList) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 1.0f, WeaponClass::HeatGlow, 0.0f);
    ring.add({100, 0, 0}, {0, 0, 1}, 5.0f, 1.0f, WeaponClass::Scuff, 0.0f);
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(ring, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

TEST(PlatingDamage, ScorchReachIsRadiusTimesReachParam) {
    DamageDecalRing ring;
    ring.add({1, 2, 3}, {0, 0, 1}, 50.0f, 1.0f, WeaponClass::Scorch, 0.0f);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(ring, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].w, 20.0f);
    EXPECT_FLOAT_EQ(l.a[0].x, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].w, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].z, 1.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 1.0f);
}

TEST(PlatingDamage, InternalKeepsItsRadiusAndHasNoFacing) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 30.0f, 1.0f, WeaponClass::Internal, 0.0f,
             glm::vec3(0.0f), 10.0f);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(ring, p.data());
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
    DamageDecalRing two;
    two.add({0, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, WeaponClass::Internal, 0.0f,
            glm::vec3(0.0f), 2.5f);
    two.add({500, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, WeaponClass::Internal, 0.0f,
            glm::vec3(0.0f), 2.5f);
    EXPECT_TRUE(renderer::plating::build_damage_list(two, p.data()).torn_possible);
    DamageDecalRing one;
    one.add({0, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, WeaponClass::Internal, 0.0f,
            glm::vec3(0.0f), 2.5f);
    EXPECT_FALSE(renderer::plating::build_damage_list(one, p.data()).torn_possible);
}

TEST(PlatingDamage, ZeroWearScorchIsSkipped) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 50.0f, 0.0f, WeaponClass::Scorch, 0.0f);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(ring, p.data());
    EXPECT_EQ(l.count, 0);
}
