#include <gtest/gtest.h>
#include <scenegraph/hull_carve.h>
using scenegraph::HullCarveField;

TEST(HullCarveField, AddMergeEvict) {
    HullCarveField f;
    EXPECT_EQ(f.count(), 0u);
    f.add({0,0,0}, 2.0f);
    EXPECT_EQ(f.count(), 1u);
    // Within kMergeFactor*radius (0.5*2=1.0): merges, grows radius, no new slot.
    f.add({0.5f,0,0}, 3.0f);
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(f.slots()[0].radius, 3.0f);   // grew to the wider re-hit
    // Far apart: new slot.
    f.add({100,0,0}, 2.0f);
    EXPECT_EQ(f.count(), 2u);
}

TEST(HullCarveField, EvictsWhenFull) {
    HullCarveField f;
    for (std::size_t i = 0; i < HullCarveField::kMaxCarves; ++i)
        f.add({float(i)*1000.f, 0, 0}, 5.0f);   // all far apart, all radius 5
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);
    f.add({999000.f, 0, 0}, 50.0f);             // far away, large -> evicts a slot
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);  // still capped, not grown
}

#include <scenegraph/instance.h>
TEST(Instance, HasCarveField) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.carve.count(), 0u);
    inst.carve.add({1,2,3}, 4.0f);
    EXPECT_EQ(inst.carve.count(), 1u);
}
