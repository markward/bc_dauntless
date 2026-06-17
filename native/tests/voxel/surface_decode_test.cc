#include <gtest/gtest.h>
#include <voxel/voxelize.h>
#include <voxel/volume.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>
#include <cmath>

static const nif::NiBinaryVoxelData* find_vox(const nif::File& f) {
    const nif::NiBinaryVoxelData* vd = nullptr;
    for (auto& b : f.blocks)
        if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
    return vd;
}

TEST(SurfaceDecode, GalaxyPaletteAndBytes2) {
    auto p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
             / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "asset absent";
    auto f = nif::load(p);
    const auto* vd = find_vox(f);
    ASSERT_NE(vd, nullptr);

    voxel::SurfaceData s = voxel::from_nif_surface(*vd);

    EXPECT_EQ(s.planes.size(), 3002u);                        // §11 golden
    for (auto& pl : s.planes) {                               // all unit normals §5
        float m = std::sqrt(pl.x * pl.x + pl.y * pl.y + pl.z * pl.z);
        EXPECT_NEAR(m, 1.0f, 1e-2f);
    }
    EXPECT_EQ(s.bytes2.size(), 94444u);                       // §11 golden numBytes2
    EXPECT_EQ(s.trailer[3], 4u * 10u);                        // = 4*nz §8 (nz=10)
    EXPECT_EQ(s.trailer[4], 0u);                              // reserved §8
}

TEST(SurfaceDecode, ShuttleDegenerateReturnsEmpty) {
    auto p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)/"game/data/Models/Ships/Shuttle/Shuttle_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "asset absent";
    auto f = nif::load(p);
    const auto* vd = find_vox(f); ASSERT_NE(vd,nullptr);
    voxel::SurfaceData s = voxel::from_nif_surface(*vd);  // dims (2,2,1) -> degenerate
    EXPECT_TRUE(s.planes.empty());   // no crash, empty result
}
