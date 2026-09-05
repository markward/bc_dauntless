#include <gtest/gtest.h>
#include "dauntless/transform_store.h"

using dauntless::TransformStore;

TEST(TransformStoreTest, NewSlotIsIdentityAtOrigin) {
    TransformStore s;
    auto [i, g] = s.alloc();
    auto p = s.position(i, g);
    EXPECT_DOUBLE_EQ(p[0], 0.0);
    EXPECT_DOUBLE_EQ(p[1], 0.0);
    EXPECT_DOUBLE_EQ(p[2], 0.0);
    auto r = s.rotation(i, g);
    EXPECT_DOUBLE_EQ(r[0], 1.0);
    EXPECT_DOUBLE_EQ(r[4], 1.0);
    EXPECT_DOUBLE_EQ(r[8], 1.0);
}

TEST(TransformStoreTest, ReusedIndexGetsNewGeneration) {
    TransformStore s;
    auto [i1, g1] = s.alloc();
    s.free(i1, g1);
    auto [i2, g2] = s.alloc();
    EXPECT_EQ(i2, i1);
    EXPECT_NE(g2, g1);
    EXPECT_FALSE(s.valid(i1, g1));
    EXPECT_TRUE(s.valid(i2, g2));
}

TEST(TransformStoreTest, GrowthPreservesExistingSlots) {
    TransformStore s;
    std::vector<std::pair<std::uint32_t, std::uint32_t>> handles;
    for (int n = 0; n < 500; ++n) {
        auto h = s.alloc();
        s.set_position(h.first, h.second,
                       static_cast<double>(n), 0.0, 0.0);
        handles.push_back(h);
    }
    for (int n = 0; n < 500; ++n) {
        auto p = s.position(handles[n].first, handles[n].second);
        EXPECT_DOUBLE_EQ(p[0], static_cast<double>(n));
    }
}

TEST(TransformStoreTest, RotationColReadsColumns) {
    TransformStore s;
    auto [i, g] = s.alloc();
    const std::array<double, 9> m{1, 2, 3, 4, 5, 6, 7, 8, 9};
    s.set_rotation(i, g, m);
    auto c1 = s.rotation_col(i, g, 1);
    EXPECT_DOUBLE_EQ(c1[0], 2.0);
    EXPECT_DOUBLE_EQ(c1[1], 5.0);
    EXPECT_DOUBLE_EQ(c1[2], 8.0);
}

TEST(TransformStoreTest, FreeListIsReused) {
    TransformStore s;
    for (int n = 0; n < 1000; ++n) {
        auto h = s.alloc();
        s.free(h.first, h.second);
    }
    EXPECT_EQ(s.live_count(), 0u);
    EXPECT_LE(s.capacity(), 4u);
}

TEST(TransformStoreTest, RecycledSlotDoesNotInheritPriorTransform) {
    TransformStore s;
    auto [i1, g1] = s.alloc();
    s.set_position(i1, g1, 42.0, -7.0, 3.5);
    const std::array<double, 9> distinctive{2, 0, 0, 0, 2, 0, 0, 0, 2};
    s.set_rotation(i1, g1, distinctive);
    s.free(i1, g1);

    auto [i2, g2] = s.alloc();
    ASSERT_EQ(i2, i1);
    auto p = s.position(i2, g2);
    EXPECT_DOUBLE_EQ(p[0], 0.0);
    EXPECT_DOUBLE_EQ(p[1], 0.0);
    EXPECT_DOUBLE_EQ(p[2], 0.0);
    auto r = s.rotation(i2, g2);
    EXPECT_DOUBLE_EQ(r[0], 1.0);
    EXPECT_DOUBLE_EQ(r[1], 0.0);
    EXPECT_DOUBLE_EQ(r[4], 1.0);
    EXPECT_DOUBLE_EQ(r[8], 1.0);
    s.free(i2, g2);
}

TEST(TransformStoreTest, RotationColOutOfRangeThrows) {
    TransformStore s;
    auto [i, g] = s.alloc();
    EXPECT_THROW(s.rotation_col(i, g, -1), std::out_of_range);
    EXPECT_THROW(s.rotation_col(i, g, 3), std::out_of_range);
    s.free(i, g);
}
