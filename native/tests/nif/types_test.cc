#include <gtest/gtest.h>
#include <nif/types.h>

TEST(Types, Vec3DefaultIsZero) {
    nif::Vec3 v{};
    EXPECT_FLOAT_EQ(v.x, 0.0f);
    EXPECT_FLOAT_EQ(v.y, 0.0f);
    EXPECT_FLOAT_EQ(v.z, 0.0f);
}

TEST(Types, Mat3x3RowMajorOrdering) {
    nif::Mat3x3 m{ .m = {1,2,3,  4,5,6,  7,8,9} };
    EXPECT_FLOAT_EQ(m.m[0], 1.0f);
    EXPECT_FLOAT_EQ(m.m[4], 5.0f);
    EXPECT_FLOAT_EQ(m.m[8], 9.0f);
}

TEST(Types, BlockIdNullSentinel) {
    nif::BlockId id = -1;
    EXPECT_EQ(id, nif::kNullBlockId);
}
