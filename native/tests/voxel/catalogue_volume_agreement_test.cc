// End-to-end agreement between a COMMITTED catalogue rock's damage volume and
// its render mesh: the volume.dvox sidecar, remapped to the BC frame at a stock
// asteroid scale by SourceVolumeCache, must cover the same space as the lod0
// mesh voxelised independently onto that same lattice. Guards the glTF-frame
// sidecar vs the loader's axis map / metre->model-unit conversion / load
// scale drifting apart (spec docs/superpowers/specs/2026-09-30-rock-catalogue-design.md).
//
// The catalogue is a PROJECT asset (native/assets/rocks), not BC content, so it
// is found through OPEN_STBC_PROJECT_ROOT and never skips.
#include <gtest/gtest.h>

#include <assets/hull_source.h>
#include <voxel/dvox.h>
#include <voxel/source_cache.h>
#include <voxel/volume.h>
#include <voxel/voxelize.h>

#include <filesystem>

namespace {

namespace fs = std::filesystem;

// engine/rocks/catalogue.py: STOCK_RADIUS_MU / (bound_radius_m 100 * 1/1.75).
constexpr float kModelUnitsPerMetre = 1.0f / 1.75f;
constexpr float kBoundRadiusM = 100.0f;

float stock_scale(float stock_radius_mu) {
    return stock_radius_mu / (kBoundRadiusM * kModelUnitsPerMetre);
}

fs::path rock_dir(const char* id) {
    return fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/rocks" / id;
}

void expect_volume_matches_mesh(const char* id, float stock_radius_mu) {
    const fs::path lod0 = rock_dir(id) / "lod0.gltf";
    ASSERT_TRUE(fs::exists(lod0)) << lod0;
    ASSERT_TRUE(fs::exists(rock_dir(id) / "volume.dvox"));

    const float scale = stock_scale(stock_radius_mu);
    const std::string source = assets::hull_source_string(lod0, scale);

    voxel::SourceVolumeCache cache;
    const voxel::VoxelVolume& vol = cache.get_for_hull(source);

    // It is the sidecar (same lattice dims as the committed .dvox), not a
    // voxelised fallback.
    voxel::VoxelVolume sidecar;
    ASSERT_TRUE(voxel::read_dvox(rock_dir(id) / "volume.dvox", sidecar));
    const voxel::VoxelVolume expected_remap =
        voxel::remap_gltf_volume_to_bc(sidecar, scale);
    ASSERT_EQ(vol.dims, expected_remap.dims);

    const auto tris = voxel::collect_hull_triangles_from_source(source);
    ASSERT_FALSE(tris.empty());
    const voxel::VoxelVolume mesh_vol =
        voxel::voxelize_into(tris, vol.dims, vol.origin, vol.cell);

    EXPECT_GE(voxel::iou(vol, mesh_vol), 0.9)
        << id << " at stock radius " << stock_radius_mu << " MU (" << source << ")";
}

}  // namespace

TEST(CatalogueVolumeAgreement, SilicateMajorAtAsteroid1Scale) {
    expect_volume_matches_mesh("majors/silicate_01", 22.451f);
}

TEST(CatalogueVolumeAgreement, SilicateMajorAtAsteroid3Scale) {
    expect_volume_matches_mesh("majors/silicate_03", 481.157f);
}
