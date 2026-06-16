#include <gtest/gtest.h>
#include <cmath>
#include <assets/crushability_bake.h>

using assets::crushability_from_thickness;

TEST(CrushabilityMapping, ThinIsHighThickIsLow) {
    // ref = 4.0: thickness 0 -> 1, thickness >= ref -> 0, linear between.
    EXPECT_FLOAT_EQ(crushability_from_thickness(0.0f, 4.0f), 1.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(4.0f, 4.0f), 0.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 4.0f), 0.75f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(2.0f, 4.0f), 0.5f);
}

TEST(CrushabilityMapping, ClampsAndHandlesDegenerateRef) {
    EXPECT_FLOAT_EQ(crushability_from_thickness(10.0f, 4.0f), 0.0f);  // beyond ref -> clamp 0
    EXPECT_FLOAT_EQ(crushability_from_thickness(-1.0f, 4.0f), 1.0f);  // negative -> clamp 1
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 0.0f), 0.0f);   // ref<=0 -> 0 (uncrushable)
}
