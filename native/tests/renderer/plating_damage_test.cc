#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <array>
#include "renderer/plating_damage.h"
#include "scenegraph/damage_decals.h"

using scenegraph::DamageDecalRing;
using scenegraph::WeaponClass;

namespace {
std::array<float, renderer::plating::kParamCount> zero_params() {
    std::array<float, renderer::plating::kParamCount> p{};
    return p;
}
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

TEST(PlatingDamage, InternalWithZeroWearIsSkipped) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 30.0f, 1.0f, WeaponClass::Internal, 0.0f,
             glm::vec3(0.0f), 0.0f);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(ring, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

// DamageDecalRing::tick only clears `active`: an aged-out slot keeps its
// point, radius and class. Only the live records may enter.
TEST(PlatingDamage, InactiveSlotsNeverEnterTheList) {
    auto p = zero_params();
    p[7] = 0.4f;
    p[16] = 4.5f;
    p[19] = 0.9f;

    // Through the ring: a HeatGlow aged out next to a live Scorch.
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, WeaponClass::HeatGlow, 0.0f);
    ring.add({100, 0, 0}, {0, 0, 1}, 50.0f, 1.0f, WeaponClass::Scorch, 0.0f);
    ring.tick(DamageDecalRing::kHeatGlowLifetime + 1.0f);
    ASSERT_EQ(ring.count(), 1u);
    const auto l = renderer::plating::build_damage_list(ring, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].x, 100.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 1.0f);

    // Stale Scorch / Internal data in inactive slots (the ring API cannot
    // make one, so build the slots directly): nothing enters, and their wear
    // does not count toward a tear.
    std::array<scenegraph::DamageDecal, 2> slots{};
    slots[0].weapon_class = WeaponClass::Scorch;
    slots[0].radius = 50.0f;
    slots[0].wear = 3.0f;
    slots[0].active = false;
    slots[1].weapon_class = WeaponClass::Internal;
    slots[1].radius = 30.0f;
    slots[1].wear = 10.0f;
    slots[1].active = false;
    const auto stale = renderer::plating::build_damage_list(slots.data(), slots.size(),
                                                            p.data());
    EXPECT_EQ(stale.count, 0);
    EXPECT_FALSE(stale.torn_possible);
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
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 30.0f, 1.0f, WeaponClass::Internal, 0.0f,
             glm::vec3(0.0f), 2.0f);
    EXPECT_TRUE(renderer::plating::build_damage_list(ring, p.data()).torn_possible);
    p[22] = 0.0f;
    p[23] = 0.0f;
    EXPECT_FALSE(renderer::plating::build_damage_list(ring, p.data()).torn_possible);
}
