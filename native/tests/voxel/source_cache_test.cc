#include <gtest/gtest.h>
#include <voxel/source_cache.h>
#include <filesystem>

TEST(SourceCache, DerivesVoxSiblingPath) {
    namespace fs = std::filesystem;
    EXPECT_EQ(voxel::vox_sibling_path("data/Models/Ships/Galaxy/Galaxy.nif"),
              fs::path("data/Models/Ships/Galaxy/Galaxy_vox.nif"));
    EXPECT_EQ(voxel::vox_sibling_path("a/b/Foo.NIF"),
              fs::path("a/b/Foo_vox.NIF"));   // preserve original extension case
}

TEST(SourceCache, GalaxyDecodesFromVoxSibling) {
    namespace fs = std::filesystem;
    fs::path hull = fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!fs::exists(hull)) GTEST_SKIP() << "BC asset absent";
    voxel::SourceVolumeCache cache;
    const voxel::VoxelVolume& v = cache.get_for_hull(hull);
    EXPECT_EQ(v.dims.x, 30);   // decoded interior-node lattice
    EXPECT_EQ(v.dims.y, 42);
    EXPECT_EQ(v.dims.z, 9);
    const voxel::VoxelVolume& v2 = cache.get_for_hull(hull);
    EXPECT_EQ(&v, &v2);        // cached: same object
}

TEST(SourceCache, GalaxyPlanePaletteFromVoxSibling) {
    namespace fs = std::filesystem;
    fs::path hull = fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!fs::exists(hull)) GTEST_SKIP() << "BC asset absent";
    voxel::SourceVolumeCache cache;
    const std::vector<glm::vec4>& planes = cache.planes_for_hull(hull);
    EXPECT_EQ(planes.size(), 3002u);   // Galaxy's decoded plane palette
    const std::vector<glm::vec4>& planes2 = cache.planes_for_hull(hull);
    EXPECT_EQ(&planes, &planes2);      // cached: same object
}

TEST(SourceCache, NoVoxSiblingGivesEmptyPalette) {
    namespace fs = std::filesystem;
    // A path with no *_vox sibling (mod ship): graceful empty palette.
    voxel::SourceVolumeCache cache;
    const std::vector<glm::vec4>& planes =
        cache.planes_for_hull("nonexistent/Mod/ModShip.nif");
    EXPECT_TRUE(planes.empty());
}
