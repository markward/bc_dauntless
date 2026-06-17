#include <gtest/gtest.h>
#include <voxel/plane_index.h>
#include <voxel/voxelize.h>
#include <voxel/volume.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>

static const nif::NiBinaryVoxelData* find_vox(const nif::File& f) {
    const nif::NiBinaryVoxelData* vd=nullptr;
    for (auto& b: f.blocks) if (auto* q=std::get_if<nif::NiBinaryVoxelData>(&b)) vd=q;
    return vd;
}
// BLOCKED: the bytes2 head-tree descent (cell -> first leaf-record) is unresolved
// pending cleanroom round 3 — see docs/.../bytes2-tree-descent-notes.md. The anchor
// values below are the verified gate (planeIndex = leaf field 2 @ tail offset 7750);
// un-skip once build_plane_index resolves the head tree.
TEST(PlaneIndex, DISABLED_GalaxyAnchors) {
    auto p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)/"game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "asset absent";
    auto f = nif::load(p);
    const auto* vd = find_vox(f); ASSERT_NE(vd,nullptr);
    voxel::SurfaceData s = voxel::from_nif_surface(*vd);
    voxel::PlaneIndexMap m = voxel::build_plane_index(s.bytes2, glm::ivec3(vd->dim_x, vd->dim_y, vd->dim_z), s.trailer);
    EXPECT_EQ(m.first_plane(13,4,0), 2247);
    EXPECT_EQ(m.first_plane(13,5,1), 417);
    EXPECT_EQ(m.first_plane(7,2,0),  270);
    EXPECT_EQ(m.first_plane(22,2,0), 280);
}
