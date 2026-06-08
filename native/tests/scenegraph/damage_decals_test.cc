#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "scenegraph/damage_decals.h"

using scenegraph::DamageDecal;
using scenegraph::DamageDecalRing;
using scenegraph::WeaponClass;

namespace {
const DamageDecal* first_active(const DamageDecalRing& ring) {
    for (const auto& d : ring.slots()) if (d.active) return &d;
    return nullptr;
}
}  // namespace

TEST(DamageDecalRing, AddCreatesOneActiveDecal) {
    DamageDecalRing ring;
    ring.add({1, 2, 3}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::Scorch, 10.0f);
    EXPECT_EQ(ring.count(), 1u);
    const DamageDecal* d = first_active(ring);
    ASSERT_NE(d, nullptr);
    EXPECT_FLOAT_EQ(d->point_body.x, 1.0f);
    EXPECT_FLOAT_EQ(d->intensity, 0.5f);
    EXPECT_EQ(d->weapon_class, WeaponClass::Scorch);
}

TEST(DamageDecalRing, IntensityClampsToOne) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 5.0f, WeaponClass::Scorch, 0.0f);
    EXPECT_FLOAT_EQ(first_active(ring)->intensity, 1.0f);
}

TEST(DamageDecalRing, CoLocatedSameClassHitsMergeNotAllocate) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    // 0.05 < 0.5 * 0.2 = 0.1 -> merges
    ring.add({0.05f, 0, 0}, {0, 0, 1}, 0.2f, 0.3f, WeaponClass::Scorch, 1.0f);
    EXPECT_EQ(ring.count(), 1u);
    const DamageDecal* d = first_active(ring);
    EXPECT_FLOAT_EQ(d->intensity, 0.7f);   // 0.4 + 0.3
    EXPECT_FLOAT_EQ(d->birth_time, 1.0f);  // ember re-ignited
}

TEST(DamageDecalRing, DistantHitAllocatesSecondSlot) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    ring.add({5, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, DifferentClassDoesNotMerge) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    ring.add({0.01f, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::HeatGlow, 0.0f);
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, FullRingEvictsOldest) {
    DamageDecalRing ring;
    // Fill all 24 slots with spatially-distinct scorch decals.
    for (int i = 0; i < 24; ++i) {
        ring.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.4f, WeaponClass::Scorch, static_cast<float>(i));
    }
    EXPECT_EQ(ring.count(), 24u);
    // One more distinct hit evicts slot seq=1 (the first, at x=0).
    ring.add({999.0f, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 100.0f);
    EXPECT_EQ(ring.count(), 24u);
    for (const auto& d : ring.slots()) {
        if (d.active) EXPECT_NE(d.point_body.x, 0.0f);  // x=0 was evicted
    }
}

TEST(DamageDecalRing, MergeRefreshesFifoAgeSoReinforcedScarSurvives) {
    DamageDecalRing ring;
    // Fill all 24 slots; x=0 is the oldest (seq=1), x=10 the next-oldest.
    for (int i = 0; i < 24; ++i) {
        ring.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.4f, WeaponClass::Scorch, static_cast<float>(i));
    }
    // Reinforce the oldest decal (x=0) — a merge that refreshes its FIFO age.
    ring.add({0.0f, 0, 0}, {0, 0, 1}, 0.2f, 0.3f, WeaponClass::Scorch, 50.0f);
    EXPECT_EQ(ring.count(), 24u);  // merged, not allocated
    // A new distinct hit now evicts the next-oldest (x=10), not the refreshed x=0.
    ring.add({999.0f, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 60.0f);
    bool has_x0 = false, has_x10 = false;
    for (const auto& d : ring.slots()) {
        if (!d.active) continue;
        if (d.point_body.x == 0.0f) has_x0 = true;
        if (d.point_body.x == 10.0f) has_x10 = true;
    }
    EXPECT_TRUE(has_x0);    // refreshed by the merge — survives eviction
    EXPECT_FALSE(has_x10);  // now the oldest — evicted instead
}

TEST(DamageDecalRing, TickReclaimsColdHeatGlowButKeepsScorch) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.9f, WeaponClass::HeatGlow, 0.0f);
    ring.add({5, 0, 0}, {0, 0, 1}, 0.2f, 0.9f, WeaponClass::Scorch, 0.0f);
    ring.tick(1.0f);              // within 3 s lifetime
    EXPECT_EQ(ring.count(), 2u);
    ring.tick(3.5f);             // past 3 s — glow reclaimed, scorch stays
    EXPECT_EQ(ring.count(), 1u);
    EXPECT_EQ(first_active(ring)->weapon_class, WeaponClass::Scorch);
}

TEST(WorldToBody, InvertsTranslationAndRotation) {
    glm::mat4 ship = glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0));
    ship = glm::rotate(ship, glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::vec3 world_pt(10, 1, 0);             // ship origin + 1 along world-Y
    glm::vec3 body = scenegraph::world_to_body(ship, world_pt);
    // World-Y maps back to +X in body after undoing the +90 deg Z rotation.
    EXPECT_NEAR(body.x, 1.0f, 1e-4f);
    EXPECT_NEAR(body.y, 0.0f, 1e-4f);
    EXPECT_NEAR(body.z, 0.0f, 1e-4f);
}

TEST(WorldDirToBody, NormalisesResult) {
    glm::mat4 ship = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f),
                                 glm::vec3(0, 0, 1));
    glm::vec3 body = scenegraph::world_dir_to_body(ship, glm::vec3(0, 2, 0));
    EXPECT_NEAR(glm::length(body), 1.0f, 1e-4f);
    // Direction must be correct, not just unit length: world +Y maps to
    // body +X after undoing the +90 deg Z rotation. (A hardcoded unit
    // return would pass the length check alone.)
    EXPECT_NEAR(body.x, 1.0f, 1e-4f);
    EXPECT_NEAR(body.y, 0.0f, 1e-4f);
    EXPECT_NEAR(body.z, 0.0f, 1e-4f);
}

TEST(DamageDecalRing, HeatGlowDoesNotMergeSoEachGlowCoolsIndependently) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::HeatGlow, 0.0f);
    // Co-located: would merge if it were Scorch, but HeatGlow must allocate a
    // separate slot so each transient glow ages and cools on its own.
    ring.add({0.01f, 0, 0}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::HeatGlow, 1.0f);
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, ScorchSurvivesHeatGlowFlooding) {
    DamageDecalRing ring;
    // One persistent Scorch, the oldest decal (seq=1).
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 1.0f, WeaponClass::Scorch, 0.0f);
    // Flood with far more distinct HeatGlow decals than free slots remain.
    for (int i = 0; i < 40; ++i) {
        ring.add({static_cast<float>(i + 1) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.5f, WeaponClass::HeatGlow, static_cast<float>(i));
    }
    EXPECT_EQ(ring.count(), 24u);
    // Eviction must prefer the transient HeatGlow; the oldest-overall Scorch
    // survives the phaser flood.
    bool scorch_present = false;
    for (const auto& d : ring.slots()) {
        if (d.active && d.weapon_class == WeaponClass::Scorch) scorch_present = true;
    }
    EXPECT_TRUE(scorch_present) << "phaser flooding evicted the persistent scorch";
}
