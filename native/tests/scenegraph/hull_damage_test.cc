#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <limits>
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

TEST(HullDamageStore, FullStoreMergesAPairNeverEvicts) {
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

TEST(HullDamageStore, RevisionChangesOnEveryChangingAdd) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    const auto r1 = s.revision();
    s.add({500, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    const auto r2 = s.revision();
    s.add({500.5f, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);  // merges
    EXPECT_NE(r1, 0u);
    EXPECT_GT(r2, r1);
    EXPECT_GT(s.revision(), r2);
}

TEST(HullDamageStore, RevisionsNeverRepeatAcrossStores) {
    // One process-wide counter: a fresh store reusing an instance's cache key
    // can never present a revision an older store already used.
    HullDamageStore a, b;
    a.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    b.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    EXPECT_NE(a.revision(), b.revision());
    EXPECT_GT(b.revision(), a.revision());
    a.clear();
    EXPECT_GT(a.revision(), b.revision());
}

TEST(HullDamageStore, NonFiniteInputIsIgnored) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float inf = std::numeric_limits<float>::infinity();
    HullDamageStore s;
    s.add({nan, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({0, inf, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, {0, nan, 1}, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, kUp, inf, 1.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, kUp, 10.0f, inf, HullDamageKind::Surface);
    s.add({0, 0, 0}, kUp, nan, 1.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, {inf, 0, 0}, 10.0f, 1.0f, HullDamageKind::Internal);
    EXPECT_EQ(s.count(), 0u);
    EXPECT_EQ(s.revision(), 0u);
}

TEST(HullDamageStore, NearbySameKindMergesWearWeighted) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({4, 0, 0}, kUp, 10.0f, 3.0f, HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 1u);
    for (const auto& r : s.records()) if (r.active) {
        EXPECT_FLOAT_EQ(r.wear, 4.0f);
        EXPECT_NEAR(r.centre_body.x, 3.0f, 1e-5f);   // 0.75 of the 4-unit gap
    }
}

TEST(HullDamageStore, SurfaceNormalsBlendWearWeighted) {
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 1}, 10.0f, 1.0f, HullDamageKind::Surface);
    s.add({1, 0, 0}, {1, 0, 0}, 10.0f, 3.0f, HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 1u);
    const glm::vec3 want = glm::normalize(glm::vec3(3, 0, 1));
    for (const auto& r : s.records()) if (r.active) {
        EXPECT_NEAR(r.normal_body.x, want.x, 1e-5f);
        EXPECT_NEAR(r.normal_body.y, 0.0f, 1e-5f);
        EXPECT_NEAR(r.normal_body.z, want.z, 1e-5f);
    }
}

TEST(HullDamageStore, InternalMergeKeepsZeroNormal) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Internal);
    s.add({1, 0, 0}, {1, 0, 0}, 10.0f, 1.0f, HullDamageKind::Internal);
    ASSERT_EQ(s.count(), 1u);
    for (const auto& r : s.records()) if (r.active) {
        EXPECT_EQ(r.kind, HullDamageKind::Internal);
        EXPECT_FLOAT_EQ(r.wear, 2.0f);
        EXPECT_EQ(r.normal_body, glm::vec3(0.0f));
    }
}

TEST(HullDamageStore, ForcedMergePicksLeastGrowthPair) {
    // Fill the store with 62 small far-apart records plus two pairs:
    //   pair A: two reach-10 records 30 apart  -> merged reach 25, growth 15
    //   pair B: a reach-100 and a reach-1 record 60 apart -> wear-weighted
    //           centroid sits near the big one; merged reach ~100.6, growth ~0.6
    // Pair A has the NEARER centres, pair B the least growth: B must merge.
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);          // A1
    s.add({30, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);         // A2
    s.add({0, 1.0e4f, 0}, kUp, 100.0f, 100.0f, HullDamageKind::Surface);  // B1
    s.add({60, 1.0e4f, 0}, kUp, 1.0f, 1.0f, HullDamageKind::Surface);     // B2 (60 > 0.5*100: no voluntary merge)
    for (int i = 0; i < 60; ++i)
        s.add({1.0e5f + 1.0e4f * i, 0, 0}, kUp, 1.0f, 1.0f, HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 64u);
    s.add({-1.0e5f, 0, 0}, kUp, 1.0f, 1.0f, HullDamageKind::Surface);   // forces a merge
    ASSERT_EQ(s.count(), 64u);
    int a_records = 0, b_records = 0;
    for (const auto& r : s.records()) if (r.active) {
        if (std::abs(r.centre_body.y) < 1.0f && r.centre_body.x >= -1.0f &&
            r.centre_body.x <= 31.0f) ++a_records;
        if (std::abs(r.centre_body.y - 1.0e4f) < 1.0f) ++b_records;
    }
    EXPECT_EQ(a_records, 2) << "the nearest-centre pair must NOT be merged";
    EXPECT_EQ(b_records, 1) << "the least-growth pair must be merged";
}

TEST(HullDamageStore, ClearBumpsRevision) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    const auto before = s.revision();
    s.clear();
    EXPECT_EQ(s.count(), 0u);
    EXPECT_GT(s.revision(), before);
}
