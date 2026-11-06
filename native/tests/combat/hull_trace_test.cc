// hull_trace.h: the CPU hull trace (a port of damage_point._Bvh.first_hit).
#include "dauntless/combat/hull_trace.h"

#include <gtest/gtest.h>

namespace cb = dauntless::combat;

namespace {

// One unit square at z = 0 (two triangles) under one leaf.
cb::HullMesh square() {
    cb::HullMesh m;
    m.tris = {0, 0, 0, 1, 0, 0, 0, 1, 0,     // (0,0,0) + e1 (1,0,0), e2 (0,1,0)
              1, 1, 0, -1, 0, 0, 0, -1, 0};  // (1,1,0) + e1 (-1,0,0), e2 (0,-1,0)
    cb::HullBvhNode leaf;
    leaf.lo[0] = leaf.lo[1] = leaf.lo[2] = 0.0;
    leaf.hi[0] = leaf.hi[1] = 1.0;
    leaf.hi[2] = 0.0;
    leaf.tris = {0, 1};
    m.nodes.push_back(leaf);
    return m;
}

}  // namespace

TEST(HullTrace, FirstHitIsTheNearestCrossing) {
    cb::hull_trace_clear();
    const int64_t h = cb::hull_trace_register(square());
    const double o[3] = {0.25, 0.5, 4.0}, d[3] = {0.0, 0.0, -1.0};
    const auto t = cb::hull_trace_first_hit(h, o, d);
    ASSERT_TRUE(t.has_value());
    EXPECT_DOUBLE_EQ(*t, 4.0);
}

TEST(HullTrace, MissesBesideAndBehind) {
    cb::hull_trace_clear();
    const int64_t h = cb::hull_trace_register(square());
    const double beside[3] = {2.0, 0.5, 4.0}, down[3] = {0.0, 0.0, -1.0};
    EXPECT_FALSE(cb::hull_trace_first_hit(h, beside, down).has_value());
    const double up[3] = {0.0, 0.0, 1.0}, above[3] = {0.5, 0.5, 4.0};
    EXPECT_FALSE(cb::hull_trace_first_hit(h, above, up).has_value());
    EXPECT_THROW(cb::hull_trace_first_hit(h + 1, above, up), std::out_of_range);
}
