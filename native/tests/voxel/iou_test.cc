// native/tests/voxel/iou_test.cc
// TDD tests for voxel::iou on synthetic 4x4x4 volumes with known overlap.
#include <gtest/gtest.h>
#include <voxel/voxelize.h>  // declares iou()
#include <voxel/volume.h>

namespace {

// Build a 4x4x4 volume with all voxels set to `val`.
voxel::VoxelVolume make_vol(std::uint8_t val = 0) {
    voxel::VoxelVolume v;
    v.dims   = glm::ivec3(4, 4, 4);
    v.origin = glm::vec3(0.f);
    v.cell   = glm::vec3(1.f);
    v.occ.assign(4 * 4 * 4, val);
    return v;
}

}  // namespace

// Both volumes are identical and fully solid → IoU = 1.0.
TEST(Iou, IdenticalFullVolumes) {
    auto a = make_vol(1);
    auto b = make_vol(1);
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), 1.0);
}

// Both volumes are empty → IoU = 1.0 (vacuously identical).
TEST(Iou, BothEmpty) {
    auto a = make_vol(0);
    auto b = make_vol(0);
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), 1.0);
}

// Disjoint: a has first half solid, b has second half solid → IoU = 0.0.
TEST(Iou, DisjointVolumes) {
    auto a = make_vol(0);
    auto b = make_vol(0);
    // First 32 voxels solid in a, last 32 solid in b (non-overlapping halves).
    for (int i = 0; i < 32; ++i) a.occ[i] = 1;
    for (int i = 32; i < 64; ++i) b.occ[i] = 1;
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), 0.0);
}

// Half-overlapping: a has first 32 solid, b has voxels 16..47 solid.
// intersection = voxels 16..31 = 16 voxels.
// union = voxels 0..47 = 48 voxels.
// IoU = 16/48 = 1/3.
TEST(Iou, PartialOverlap) {
    auto a = make_vol(0);
    auto b = make_vol(0);
    for (int i = 0; i < 32; ++i) a.occ[i] = 1;
    for (int i = 16; i < 48; ++i) b.occ[i] = 1;
    const double expected = 16.0 / 48.0;
    EXPECT_NEAR(voxel::iou(a, b), expected, 1e-12);
}

// Identical volumes, all solid, but with fill-value bytes (>1) treated as solid.
// BC volumes use 0–127; any nonzero byte should count as solid.
TEST(Iou, NonzeroOccTreatedAsSolid) {
    auto a = make_vol(127);  // max fill value from BC
    auto b = make_vol(64);   // mid fill value
    // Both fully solid → IoU = 1.0.
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), 1.0);
}

// Mismatch: a has all 64 voxels solid, b has none → IoU = 0.0.
TEST(Iou, OneEmptyOneFullIsZero) {
    auto a = make_vol(1);
    auto b = make_vol(0);
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), 0.0);
}

// Symmetry: iou(a,b) == iou(b,a).
TEST(Iou, IsSymmetric) {
    auto a = make_vol(0);
    auto b = make_vol(0);
    // Checker pattern: solid where (i+j+k) is even.
    for (int z = 0; z < 4; ++z)
    for (int y = 0; y < 4; ++y)
    for (int x = 0; x < 4; ++x) {
        std::size_t idx = a.index(x, y, z);
        if ((x + y + z) % 2 == 0) a.occ[idx] = 1;
        else                        b.occ[idx] = 1;
    }
    EXPECT_DOUBLE_EQ(voxel::iou(a, b), voxel::iou(b, a));
}
