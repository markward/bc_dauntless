// native/tests/voxel/select_breach_voxels_test.cc
//
// Pure (no-GL) tests for voxel::select_breach_voxels — the helper the breach
// pass (Task 9) uses to pick which solid interior voxels fall inside a carve
// sphere and should be splatted as colored cubes.

#include <gtest/gtest.h>

#include <voxel/volume.h>
#include <voxel/voxelize.h>

#include <glm/glm.hpp>

using voxel::VoxelVolume;
using voxel::select_breach_voxels;

namespace {

// A 4x4x4 unit-cell grid at the origin (voxel (i,j,k) centre = i+0.5, etc.),
// every cell solid. Easy to reason about which centres fall in a sphere.
VoxelVolume make_full_4x4x4() {
    VoxelVolume v;
    v.dims = {4, 4, 4};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 1);
    return v;
}

}  // namespace

// A tiny sphere centred on one voxel centre with radius < half-cell selects
// exactly that one voxel, and its returned centre matches.
TEST(SelectBreachVoxels, SingleVoxelInsideTinySphere) {
    VoxelVolume v = make_full_4x4x4();
    const glm::vec3 c{1.5f, 1.5f, 1.5f};  // centre of voxel (1,1,1)
    auto out = select_breach_voxels(v, c, 0.25f);
    ASSERT_EQ(out.size(), 1u);
    EXPECT_NEAR(out[0].x, 1.5f, 1e-5f);
    EXPECT_NEAR(out[0].y, 1.5f, 1e-5f);
    EXPECT_NEAR(out[0].z, 1.5f, 1e-5f);
}

// Every returned centre must actually be within radius of the sphere centre.
TEST(SelectBreachVoxels, AllReturnedCentresWithinRadius) {
    VoxelVolume v = make_full_4x4x4();
    const glm::vec3 c{2.0f, 2.0f, 2.0f};
    const float r = 1.5f;
    auto out = select_breach_voxels(v, c, r);
    ASSERT_FALSE(out.empty());
    for (const auto& e : out) {
        const glm::vec3 p{e.x, e.y, e.z};
        EXPECT_LE(glm::length(p - c), r + 1e-4f)
            << "returned voxel centre lies outside the carve sphere";
    }
}

// Count check: a sphere covering the whole grid returns every solid voxel.
TEST(SelectBreachVoxels, LargeSphereSelectsAllSolids) {
    VoxelVolume v = make_full_4x4x4();
    auto out = select_breach_voxels(v, glm::vec3{2.f, 2.f, 2.f}, 100.f);
    EXPECT_EQ(out.size(), 64u);
}

// Empty voxels are never returned: clear half the grid and confirm the
// returned set contains only solid cells.
TEST(SelectBreachVoxels, SkipsEmptyVoxels) {
    VoxelVolume v = make_full_4x4x4();
    // Zero out the x<2 half.
    for (int z = 0; z < 4; ++z)
        for (int y = 0; y < 4; ++y)
            for (int x = 0; x < 2; ++x)
                v.set(x, y, z, false);
    auto out = select_breach_voxels(v, glm::vec3{2.f, 2.f, 2.f}, 100.f);
    EXPECT_EQ(out.size(), 32u);  // only the x in {2,3} half remains solid
    for (const auto& e : out) {
        EXPECT_GE(e.x, 2.0f) << "returned a voxel from the cleared half";
    }
}

// The seed (w) is the flat occ index of the voxel — distinct per voxel so the
// shader colours each cube differently.
TEST(SelectBreachVoxels, SeedIsFlatIndexAndStable) {
    VoxelVolume v = make_full_4x4x4();
    auto out = select_breach_voxels(v, glm::vec3{2.f, 2.f, 2.f}, 100.f);
    ASSERT_EQ(out.size(), 64u);
    // index(1,1,1) = 1 + 4*(1 + 4*1) = 1 + 4*5 = 21.
    const float expect = static_cast<float>(v.index(1, 1, 1));
    bool found = false;
    for (const auto& e : out) {
        if (std::abs(e.x - 1.5f) < 1e-5f && std::abs(e.y - 1.5f) < 1e-5f &&
            std::abs(e.z - 1.5f) < 1e-5f) {
            EXPECT_NEAR(e.w, expect, 1e-3f);
            found = true;
        }
    }
    EXPECT_TRUE(found);
}

// Degenerate / empty volume returns nothing (no crash, no out-of-range).
TEST(SelectBreachVoxels, EmptyVolumeReturnsNothing) {
    VoxelVolume v;  // dims {0,0,0}, occ empty
    auto out = select_breach_voxels(v, glm::vec3{0.f}, 10.f);
    EXPECT_TRUE(out.empty());
}

// A non-unit origin/cell still yields centres at origin + (i+0.5)*cell.
TEST(SelectBreachVoxels, RespectsOriginAndCell) {
    VoxelVolume v;
    v.dims = {2, 1, 1};
    v.origin = {10.f, 0.f, 0.f};
    v.cell = {4.f, 1.f, 1.f};
    v.occ.assign(2, 1);
    // voxel (0,*,*) centre.x = 10 + 0.5*4 = 12; voxel (1) centre.x = 16.
    auto out = select_breach_voxels(v, glm::vec3{12.f, 0.5f, 0.5f}, 1.0f);
    ASSERT_EQ(out.size(), 1u);
    EXPECT_NEAR(out[0].x, 12.0f, 1e-5f);
}
