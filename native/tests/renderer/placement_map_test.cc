#include <gtest/gtest.h>
#include <renderer/placement_map.h>

TEST(PlacementMap, ResolvesKnownStations) {
    auto db_tac = renderer::placement_for_location("DBTactical");
    ASSERT_TRUE(db_tac.has_value());
    EXPECT_EQ(db_tac->nif_path, "data/animations/db_stand_t_l.nif");
    EXPECT_FALSE(db_tac->hidden);

    auto eb_helm = renderer::placement_for_location("EBHelm");
    ASSERT_TRUE(eb_helm.has_value());
    EXPECT_EQ(eb_helm->nif_path, "data/animations/EB_stand_h_m.nif");
}

TEST(PlacementMap, StagingLocationsAreHidden) {
    auto staging = renderer::placement_for_location("DBL1S");
    ASSERT_TRUE(staging.has_value());
    EXPECT_TRUE(staging->hidden);
}

TEST(PlacementMap, UnknownReturnsNullopt) {
    EXPECT_FALSE(renderer::placement_for_location("Nowhere").has_value());
}
