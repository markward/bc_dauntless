#include <gtest/gtest.h>
#include <voxel/volume.h>

using voxel::VoxelVolume;

TEST(VoxelVolume, IndexRoundTripAndSetGet) {
    VoxelVolume v;
    v.dims = {4, 3, 2};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 3 * 2, 0);

    EXPECT_EQ(v.index(0, 0, 0), 0u);
    EXPECT_EQ(v.index(3, 2, 1), 4u * 3u * 2u - 1u);  // last voxel

    EXPECT_FALSE(v.solid(2, 1, 1));
    v.set(2, 1, 1, true);
    EXPECT_TRUE(v.solid(2, 1, 1));
    EXPECT_EQ(v.solid_count(), 1u);
}
