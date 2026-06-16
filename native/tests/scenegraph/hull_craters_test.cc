#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "scenegraph/hull_craters.h"

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
