#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "scenegraph/hull_damage.h"

using scenegraph::HullDamageKind;
using scenegraph::HullDamageRecord;
using scenegraph::HullDamageStore;

namespace {
const glm::vec3 kUp{0, 0, 1};
float total_wear(const HullDamageStore& s) {
    float t = 0;
    for (const auto& r : s.records()) if (r.active) t += r.wear;
    return t;
}
}  // namespace

TEST(HullDamageStore, ZeroWearOrReachIsIgnored) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 0.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, kUp, 0.0f, 1.0f, HullDamageKind::Surface);
    EXPECT_EQ(s.count(), 0u);
    EXPECT_EQ(s.revision(), 0u);
}

TEST(HullDamageStore, NearbySameKindMerges) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({1, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 1u);
    for (const auto& r : s.records()) if (r.active) {
        EXPECT_FLOAT_EQ(r.wear, 2.0f);
        EXPECT_NEAR(r.centre_body.x, 0.5f, 1e-5f);
        EXPECT_NEAR(r.reach, 10.5f, 1e-4f);
    }
}

TEST(HullDamageStore, KindsNeverMerge) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, {0, 0, 0}, 10.0f, 1.0f, HullDamageKind::Internal);
    EXPECT_EQ(s.count(), 2u);
}

TEST(HullDamageStore, SweepDoesNotGrowOneRecordOverTheHull) {
    HullDamageStore s;
    for (int i = 0; i < 40; ++i)
        s.add({4.0f * i, 0, 0}, kUp, 10.0f, 0.1f, HullDamageKind::Surface);
    EXPECT_GT(s.count(), 1u);
    for (const auto& r : s.records()) if (r.active) EXPECT_LE(r.reach, 15.0f);
}

TEST(HullDamageStore, FullStoreMergesNearestPairNeverEvicts) {
    HullDamageStore s;
    for (int i = 0; i < 64; ++i)
        s.add({100.0f * i, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 64u);
    s.add({1.0e5f, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    EXPECT_EQ(s.count(), 64u);
    EXPECT_FLOAT_EQ(total_wear(s), 65.0f);
}

TEST(HullDamageStore, InternalHolesSurviveTwoHundredHits) {
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 10.0f, HullDamageKind::Internal);
    for (int i = 0; i < 200; ++i) {
        float x = 400.0f * (1 + i % 15), y = 400.0f * (1 + i / 15);
        s.add({x, y, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    }
    bool found = false;
    for (const auto& r : s.records())
        if (r.active && r.kind == HullDamageKind::Internal && r.wear >= 10.0f &&
            glm::length(r.centre_body) < 1.0f) found = true;
    EXPECT_TRUE(found);
}

TEST(HullDamageStore, RevisionCountsChanges) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({500, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    EXPECT_EQ(s.revision(), 2u);
}
