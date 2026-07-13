// native/tests/voxel/iou_realdata_test.cc
//
// Real-data IoU regression-floor test: decode Galaxy_vox.nif → ref; gather
// Galaxy.nif hull triangles via collect_hull_triangles_from_nif (GL-free NIF
// walk, same code used by voxel_inspect); voxelize onto the decoded lattice
// via voxelize_into; assert iou(ref, ours) > 0.4.
//
// IoU floor rationale: the decode-vs-voxelize gap (~0.46 measured, range
// ~0.6–0.8 across ships) is an explained boundary-coverage/inset-lattice
// artifact — the decoder produces the (nx-1,ny-1,nz-1) interior-node lattice
// while the voxelizer rasterizes surface triangles and handles boundary cells
// differently. 0.4 is a honest regression floor (well below current ~0.46),
// NOT a "high agreement" claim. See design spec §4 and
// docs/engine/nif-voxel-format.md §5 for context.
//
// Path choice: collect_hull_triangles_from_nif (GL-free NIF walk) rather than
// assets::build_model + collect_hull_triangles, because build_model requires a
// GL context for texture/mesh upload. The NIF walk is the same code path
// voxel_inspect already uses; exposing it as a public library function
// de-duplicates it and makes it testable without a renderer.

#include <gtest/gtest.h>
#include <voxel/voxelize.h>
#include <voxel/volume.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>
#include <cstdio>

namespace {

const nif::NiBinaryVoxelData* find_vox(const nif::File& f) {
    for (const auto& b : f.blocks)
        if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) return q;
    return nullptr;
}

}  // namespace

TEST(IouRealdata, GalaxyDecodeVsVoxelizeFloor) {
    // Locate assets.
    const std::filesystem::path root = OPEN_STBC_PROJECT_ROOT;
    const std::filesystem::path vox_path =
        root / "game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    const std::filesystem::path hull_path =
        root / "game/data/Models/Ships/Galaxy/Galaxy.nif";

    if (!std::filesystem::exists(vox_path))
        GTEST_SKIP() << "BC asset absent: " << vox_path;
    if (!std::filesystem::exists(hull_path))
        GTEST_SKIP() << "BC asset absent: " << hull_path;

    // 1. Decode reference volume from Galaxy_vox.nif.
    auto vf = nif::load(vox_path);
    const auto* vd = find_vox(vf);
    ASSERT_NE(vd, nullptr) << "No NiBinaryVoxelData in Galaxy_vox.nif";
    voxel::VoxelVolume ref = voxel::from_nif_voxel_data(*vd);
    ASSERT_GT(ref.dims.x, 0) << "Decoded volume is degenerate";

    // 2. Gather hull triangles from Galaxy.nif (GL-free NIF walk).
    auto hf = nif::load(hull_path);
    auto tris = voxel::collect_hull_triangles_from_nif(hf);
    ASSERT_FALSE(tris.empty()) << "No triangles found in Galaxy.nif";

    // 3. Voxelize hull onto the decoded reference lattice.
    //    Using the ref dims/origin/cell ensures both volumes are on the same
    //    grid, which is required for a valid iou() comparison.
    voxel::VoxelVolume ours = voxel::voxelize_into(tris, ref.dims, ref.origin, ref.cell);

    // 4. Compute IoU and assert the regression floor.
    double score = voxel::iou(ref, ours);

    std::printf("[IouRealdata] Galaxy decode-vs-voxelize IoU = %.4f  "
                "(floor = 0.4, current baseline ~0.465)\n", score);

    // Floor = 0.4 is a BASELINE regression guard, not a "high agreement" bar.
    // The current measured score is ~0.465. A correct voxelizer should score
    // well above 0.4; if this drops below 0.4, something is grossly broken.
    EXPECT_GT(score, 0.4) << "IoU = " << score
        << " dropped below regression floor (0.4). "
           "Measured ~0.46 expected. Check voxelize_into / from_nif_voxel_data.";
}
