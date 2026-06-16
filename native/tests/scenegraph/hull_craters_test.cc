#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "scenegraph/hull_craters.h"
#include "scenegraph/instance.h"

using scenegraph::HullCrater;
using scenegraph::HullCraterField;

namespace {
const HullCrater* first_active(const HullCraterField& f) {
    for (const auto& c : f.slots()) if (c.active) return &c;
    return nullptr;
}
}  // namespace

TEST(HullCraterField, AddCreatesOneActiveCrater) {
    HullCraterField f;
    f.add(/*point*/{1, 2, 3}, /*dir*/{0, 0, -1}, /*normal*/{0, 0, 1},
          /*radius*/0.2f, /*depth*/0.3f);
    EXPECT_EQ(f.count(), 1u);
    const HullCrater* c = first_active(f);
    ASSERT_NE(c, nullptr);
    EXPECT_FLOAT_EQ(c->point_body.x, 1.0f);
    EXPECT_FLOAT_EQ(c->impact_dir_body.z, -1.0f);
    EXPECT_FLOAT_EQ(c->normal_body.z, 1.0f);
    EXPECT_FLOAT_EQ(c->radius, 0.2f);
    EXPECT_FLOAT_EQ(c->depth, 0.3f);
}

TEST(HullCraterField, DepthClampsToMaxAndFloorsAtZero) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 999.0f);
    EXPECT_FLOAT_EQ(first_active(f)->depth, HullCraterField::kMaxDepth);

    HullCraterField g;
    g.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, -5.0f);
    EXPECT_FLOAT_EQ(first_active(g)->depth, 0.0f);
}

TEST(HullCraterField, CoLocatedHitDeepensExistingCrater) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    // 0.05 < 0.5 * 0.2 = 0.1 -> merges into the first crater.
    f.add({0.05f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.4f);
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(first_active(f)->depth, 0.7f);  // 0.3 + 0.4
}

TEST(HullCraterField, AccumulatedDepthClampsToMax) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 40.0f);
    f.add({0.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 40.0f);  // 80 -> caps at kMaxDepth
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(first_active(f)->depth, HullCraterField::kMaxDepth);
}

TEST(HullCraterField, MergeGrowsRadiusAndRefreshesDirection) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    f.add({0.0f, 0, 0}, {1, 0, 0}, {0, 1, 0}, 0.5f, 0.1f);  // bigger radius, new dir/normal
    const HullCrater* c = first_active(f);
    EXPECT_FLOAT_EQ(c->radius, 0.5f);             // grew to max
    EXPECT_FLOAT_EQ(c->impact_dir_body.x, 1.0f);  // freshest direction
    EXPECT_FLOAT_EQ(c->normal_body.y, 1.0f);      // freshest normal
    EXPECT_GT(c->seq, 1u);  // merge refreshed age (seq advanced past the first add)
}

TEST(HullCraterField, DistantHitAllocatesSecondCrater) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    f.add({5, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);  // far -> separate
    EXPECT_EQ(f.count(), 2u);
}

TEST(HullCraterField, FullFieldEvictsShallowestCrater) {
    HullCraterField f;
    // Fill all slots with distinct, far-apart, deep craters (depth 0.5).
    for (std::size_t i = 0; i < HullCraterField::kMaxCraters; ++i) {
        f.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, -1}, {0, 0, 1},
              0.2f, 0.5f);
    }
    EXPECT_EQ(f.count(), HullCraterField::kMaxCraters);

    // Field is full; all existing craters are depth 0.5. A new, far-apart,
    // DEEPER crater (0.9) must evict the shallowest existing one. Count stays
    // at capacity and a 0.9-deep crater now exists.
    f.add({999.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.9f);
    EXPECT_EQ(f.count(), HullCraterField::kMaxCraters);

    bool found_deep = false;
    for (const auto& c : f.slots()) {
        if (c.active && c.depth > 0.8f) found_deep = true;
    }
    EXPECT_TRUE(found_deep);  // the new deep crater displaced a shallow one
}

TEST(HullCraterField, EvictionPrefersShallowOverOld) {
    HullCraterField f;
    // One shallow OLD crater first (smallest seq), then fill the rest deep.
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.1f);  // shallow, oldest
    for (std::size_t i = 1; i < HullCraterField::kMaxCraters; ++i) {
        f.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, -1}, {0, 0, 1},
              0.2f, 0.6f);  // deep
    }
    // Field full. A new far crater must evict the shallow (0.1) one, not a deep
    // one — depth dominates, so the deep-but-older craters are safe.
    f.add({999.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.6f);

    bool shallow_gone = true;
    for (const auto& c : f.slots()) {
        if (c.active && c.depth < 0.2f) shallow_gone = false;
    }
    EXPECT_TRUE(shallow_gone);  // shallow crater was the eviction victim
}

TEST(Instance, HasEmptyCraterFieldByDefault) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.craters.count(), 0u);
}
