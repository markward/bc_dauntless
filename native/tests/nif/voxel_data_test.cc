// native/tests/nif/voxel_data_test.cc
//
// Confirms that the NiBinaryVoxelData header fields parse to the
// cleanroom-confirmed values for the Galaxy ship vox file.
// See docs/engine/nif-voxel-format.md.
#include <gtest/gtest.h>
#include <nif/block.h>
#include <nif/file.h>

#include <filesystem>

TEST(VoxelDataHeader, GalaxyHeaderDecodesToConfirmedValues) {
    std::filesystem::path p =
        std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p))
        GTEST_SKIP() << "BC asset absent: " << p;

    auto f = nif::load(p);
    const nif::NiBinaryVoxelData* vd = nullptr;
    for (const auto& b : f.blocks)
        if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
    ASSERT_NE(vd, nullptr);

    // Confirmed Galaxy values (cleanroom + 84-file corpus decode):
    EXPECT_EQ(vd->dim_x, 31);
    EXPECT_EQ(vd->dim_y, 43);
    EXPECT_EQ(vd->dim_z, 10);
    EXPECT_FLOAT_EQ(vd->cell_size, 15.0f);
    EXPECT_NEAR(vd->aabb_min[0], -232.5f,  1e-2);
    EXPECT_NEAR(vd->aabb_min[1], -322.5f,  1e-2);
    EXPECT_NEAR(vd->aabb_min[2],  -75.003f, 1e-2);
    EXPECT_NEAR(vd->aabb_max[0],  232.5f,  1e-2);
    EXPECT_NEAR(vd->aabb_max[1],  322.5f,  1e-2);
    EXPECT_NEAR(vd->aabb_max[2],   74.997f, 1e-2);
    // raw_voxel_payload captures the full payload (fillField + planes + bytes2 +
    // trailer). The fillField is decoded by the voxel module (see decode_test.cc);
    // this NIF-level test just confirms the raw payload is captured correctly.
    EXPECT_GT(vd->raw_voxel_payload.size(), 0u);
}
