#include <gtest/gtest.h>
#include <voxel/source_cache.h>
#include <voxel/dvox.h>
#include <assets/hull_source.h>
#include <filesystem>
#include "support/content_root.h"
#include "gltf_fixture.h"

TEST(SourceCache, DerivesVoxSiblingPath) {
    namespace fs = std::filesystem;
    EXPECT_EQ(voxel::vox_sibling_path("data/Models/Ships/Galaxy/Galaxy.nif"),
              fs::path("data/Models/Ships/Galaxy/Galaxy_vox.nif"));
    EXPECT_EQ(voxel::vox_sibling_path("a/b/Foo.NIF"),
              fs::path("a/b/Foo_vox.NIF"));   // preserve original extension case
}

TEST(SourceCache, GalaxyDecodesFromVoxSibling) {
    namespace fs = std::filesystem;
    fs::path hull = test_support::game_root() / "data/Models/Ships/Galaxy/Galaxy.nif";
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
    fs::path hull = test_support::game_root() / "data/Models/Ships/Galaxy/Galaxy.nif";
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

TEST(SourceVolumeCache, VoxelisesGltfWhenNoSidecar) {
    auto p = write_cube_fixture(tmpdir("svc_nosidecar"), 1.75f, nullptr);   // half-extent 1 model unit
    voxel::SourceVolumeCache c;
    const auto& v = c.get_for_hull(p);
    ASSERT_FALSE(v.occ.empty());
    EXPECT_EQ(v.dims, glm::ivec3(48, 48, 48));
    EXPECT_GT(v.solid_count(), 0u);
}

TEST(SourceVolumeCache, PrefersExtrasSidecar) {
    auto d = tmpdir("svc_sidecar");
    voxel::VoxelVolume g; g.dims = {2,2,2}; g.origin = {-1,-1,-1}; g.cell = {1,1,1}; g.occ.assign(8, 1);
    fs::create_directories(d); ASSERT_TRUE(voxel::write_dvox(d / "volume.dvox", g));
    auto p = write_cube_fixture(d, 1.0f, {{"dauntless_volume", "volume.dvox"}});
    voxel::SourceVolumeCache c;
    EXPECT_EQ(c.get_for_hull(p).dims, glm::ivec3(2, 2, 2));  // sidecar, not the 48^3 fallback
}

TEST(SourceVolumeCache, DistinctScalesDistinctVolumes) {
    auto p = write_cube_fixture(tmpdir("svc_scale"), 1.75f, nullptr);
    voxel::SourceVolumeCache c;
    const auto& a = c.get_for_hull(assets::hull_source_string(p, 1.0f));
    const auto& b = c.get_for_hull(assets::hull_source_string(p, 2.0f));
    EXPECT_NEAR(b.cell.x, 2.0f * a.cell.x, 1e-4f);
}
