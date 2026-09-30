// native/tests/voxel/dvox_test.cc
#include <voxel/dvox.h>
#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <glm/glm.hpp>

TEST(Dvox, RoundTrip) {
    voxel::VoxelVolume v; v.dims = {3, 4, 5}; v.origin = {-1, -2, -3}; v.cell = {0.5f, 0.25f, 1.0f};
    v.occ.assign(60, 0); v.set(0,0,0,true); v.set(2,3,4,true); v.set(1,2,3,true);
    auto p = std::filesystem::temp_directory_path() / "dvox_rt.dvox";
    ASSERT_TRUE(voxel::write_dvox(p, v));
    voxel::VoxelVolume r; ASSERT_TRUE(voxel::read_dvox(p, r));
    EXPECT_EQ(r.dims, v.dims); EXPECT_EQ(r.origin, v.origin); EXPECT_EQ(r.cell, v.cell);
    EXPECT_EQ(r.solid_count(), 3u);
    EXPECT_TRUE(r.solid(2,3,4)); EXPECT_FALSE(r.solid(1,1,1));
}

TEST(Dvox, RejectsBadMagic) {
    auto p = std::filesystem::temp_directory_path() / "dvox_bad.dvox";
    { std::ofstream(p) << "NOPE"; }
    voxel::VoxelVolume r; EXPECT_FALSE(voxel::read_dvox(p, r));
}

TEST(Dvox, RemapMatchesPointMap) {
    // A single solid cell at glTF index (2,0,1) in a 4x2x3 grid, 1 m cells, origin 0.
    voxel::VoxelVolume g; g.dims = {4, 2, 3}; g.origin = {0,0,0}; g.cell = {1,1,1};
    g.occ.assign(24, 0); g.set(2, 0, 1, true);
    auto b = voxel::remap_gltf_volume_to_bc(g, 2.0f);
    const float k = (1.0f / 1.75f) * 2.0f;
    EXPECT_EQ(b.dims, glm::ivec3(4, 3, 2));                 // (dx, dz, dy)
    EXPECT_NEAR(b.cell.x, k, 1e-6f);
    ASSERT_EQ(b.solid_count(), 1u);
    // Centre of the glTF cell (2.5, 0.5, 1.5) m maps to BC (-2.5, 1.5, 0.5) * k.
    glm::vec3 want = glm::vec3(-2.5f, 1.5f, 0.5f) * k;
    for (int z = 0; z < b.dims.z; ++z) for (int y = 0; y < b.dims.y; ++y) for (int x = 0; x < b.dims.x; ++x)
        if (b.solid(x, y, z)) {
            glm::vec3 c = b.origin + (glm::vec3(x, y, z) + 0.5f) * b.cell;
            EXPECT_NEAR(glm::distance(c, want), 0.0f, 1e-5f);
        }
}
