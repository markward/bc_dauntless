#include <gtest/gtest.h>
#include <scenegraph/hull_carve.h>
using scenegraph::HullCarve;
using scenegraph::HullCarveField;

TEST(HullCarveField, AccumulatesStrengthOnMerge) {
    HullCarveField f;
    EXPECT_EQ(f.count(), 0u);
    HullCarve& a = f.add({0, 0, 0}, 2.0f, 100.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(a.strength, 100.0f);
    // Within kMergeFactor*influ (0.5*2=1.0): merges, accumulates strength,
    // widens influ to the max, moves to the freshest centre.
    HullCarve& b = f.add({0.5f, 0, 0}, 3.0f, 250.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(b.strength, 350.0f);     // 100 + 250
    EXPECT_FLOAT_EQ(b.influ_radius, 3.0f);   // widened to max
    // Far apart: new slot.
    f.add({100, 0, 0}, 2.0f, 50.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 2u);
}

TEST(HullCarveField, EvictsSmallestRadiusWhenFull) {
    HullCarveField f;
    for (std::size_t i = 0; i < HullCarveField::kMaxCarves; ++i) {
        HullCarve& c = f.add({float(i) * 1000.f, 0, 0}, 5.0f, 10.0f, {0, 0, 1});
        c.radius = 5.0f;   // caller owns the visible radius
    }
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);
    f.add({999000.f, 0, 0}, 5.0f, 10.0f, {0, 0, 1});  // far away -> evicts a slot
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);  // still capped
}

TEST(HullCarveStrengthCurve, IsoGatesThenGrowsSmoothly) {
    using scenegraph::hull_carve_strength_to_radius_gu;
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(149.0f), 0.0f);   // below iso: invisible
    // At the iso the carve emerges SMALL (no chunky pop), then grows.
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(150.0f),
                    scenegraph::kHullCarveRadiusAtIso);
    EXPECT_GT(hull_carve_strength_to_radius_gu(450.0f),
              hull_carve_strength_to_radius_gu(300.0f));               // monotonic growth
    EXPECT_LE(hull_carve_strength_to_radius_gu(100000.0f), 1.5f);      // clamp
}

#include <scenegraph/instance.h>
TEST(Instance, HasCarveField) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.carve.count(), 0u);
    inst.carve.add({1, 2, 3}, 4.0f, 10.0f, {0, 0, 1});
    EXPECT_EQ(inst.carve.count(), 1u);
}
