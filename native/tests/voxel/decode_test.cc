#include <gtest/gtest.h>
#include <voxel/voxelize.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>

static const nif::NiBinaryVoxelData* find_vox(const nif::File& f) {
    const nif::NiBinaryVoxelData* vd = nullptr;
    for (const auto& b : f.blocks)
        if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
    return vd;
}

TEST(DecodeFillField, GalaxyMatchesGoldenStats) {
    std::filesystem::path p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "BC asset absent";
    auto f = nif::load(p);
    const auto* vd = find_vox(f);
    ASSERT_NE(vd, nullptr);

    voxel::VoxelVolume v = voxel::from_nif_voxel_data(*vd);
    // Golden values verified against the cleanroom decoder on Galaxy:
    EXPECT_EQ(v.dims.x, 30);
    EXPECT_EQ(v.dims.y, 42);
    EXPECT_EQ(v.dims.z, 9);
    ASSERT_EQ(v.occ.size(), std::size_t(30) * 42 * 9);   // N = 11340
    std::uint8_t mx = 0; std::size_t nonzero = 0, solid127 = 0;
    for (auto b : v.occ) { mx = std::max(mx, b); nonzero += (b > 0); solid127 += (b == 127); }
    EXPECT_EQ((int)mx, 127);
    EXPECT_EQ(nonzero, 2787u);
    EXPECT_EQ(solid127, 1584u);
    EXPECT_EQ((int)v.occ[37], 88);   // first nonzero node, flat idx 37
}

TEST(DecodeFillField, ShuttleDegenerateIsEmpty) {
    std::filesystem::path p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Shuttle/Shuttle_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "BC asset absent";
    auto f = nif::load(p);
    const auto* vd = find_vox(f);
    ASSERT_NE(vd, nullptr);
    voxel::VoxelVolume v = voxel::from_nif_voxel_data(*vd);   // dims (2,2,1) -> nz-1=0 -> empty
    EXPECT_EQ(v.occ.size(), 0u);   // N==0, degenerate empty grid, no crash
}
