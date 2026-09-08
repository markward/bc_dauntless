// native/tests/voxel/voxelize_resolution_test.cc
//
// The resolution-collapse regression. surface_voxelize used a FIXED 153
// barycentric samples per triangle regardless of cell size, so as cells shrank
// the rasterized shell developed pinholes and solidify()'s flood fill (seeded
// from every border voxel) poured through them and ate the interior. Measured
// on stock hulls 2026-09-08: solid fraction fell from ~13% at 48^3 to ~2% at
// 128^3, scaling as n^2 -- the signature of a surface-only result.
//
// A solid box exactly fills its own bounding grid minus voxelize_tris's
// one-cell margin, so the true fraction is ((n-2)/n)^3: 0.67 at n=16 rising to
// 0.95 at n=128. A collapsed volume reads ~0.05 and falls as n rises.
#include <gtest/gtest.h>

#include <voxel/voxelize.h>

#include <vector>

namespace {

// A CLOSED axis-aligned box as 12 triangles. Closed matters: the whole point is
// that the flood fill must not find a way in.
std::vector<voxel::Tri> box_tris(glm::vec3 lo, glm::vec3 hi) {
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z},
    };
    const int q[6][4] = {
        {0, 1, 2, 3},  // -Z
        {4, 5, 6, 7},  // +Z
        {0, 1, 5, 4},  // -Y
        {3, 2, 6, 7},  // +Y
        {0, 3, 7, 4},  // -X
        {1, 2, 6, 5},  // +X
    };
    std::vector<voxel::Tri> t;
    for (const auto& f : q) {
        t.push_back({c[f[0]], c[f[1]], c[f[2]]});
        t.push_back({c[f[0]], c[f[2]], c[f[3]]});
    }
    return t;
}

}  // namespace

TEST(VoxelizeResolution, SolidBoxStaysSolidAsResolutionRises) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    for (int n : {16, 32, 64, 128}) {
        const voxel::VoxelVolume v = voxel::voxelize_tris(tris, glm::ivec3(n));
        const double frac = static_cast<double>(v.solid_count())
                          / (static_cast<double>(n) * n * n);
        // True value is ((n-2)/n)^3 >= 0.67. A collapsed volume reads ~0.05.
        EXPECT_GT(frac, 0.5)
            << "resolution " << n << " collapsed to a shell (fraction " << frac << ")";
    }
}

TEST(VoxelizeResolution, SolidFractionRisesWithResolutionRatherThanFalling) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    const voxel::VoxelVolume coarse = voxel::voxelize_tris(tris, glm::ivec3(16));
    const voxel::VoxelVolume fine   = voxel::voxelize_tris(tris, glm::ivec3(128));

    const double fc = static_cast<double>(coarse.solid_count()) / (16.0 * 16 * 16);
    const double ff = static_cast<double>(fine.solid_count()) / (128.0 * 128 * 128);

    // The margin is a smaller fraction of a finer grid, so the true fraction
    // RISES. The bug made it fall by an order of magnitude.
    EXPECT_GT(ff, fc) << "fine=" << ff << " coarse=" << fc;
}

// A thin plate is the case a fixed sample count fails first: its triangles are
// large relative to the cell, so samples straddle whole cells.
TEST(VoxelizeResolution, ThinPlateIsNotPerforated) {
    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(200.0f, 200.0f, 8.0f));
    const voxel::VoxelVolume v = voxel::voxelize_tris(tris, glm::ivec3(96));
    const double frac = static_cast<double>(v.solid_count()) / (96.0 * 96 * 96);
    // voxelize_tris fits the lattice to the AABB PER AXIS (cell =
    // extent/(dims-2)), so the plate's 8-unit Z becomes 96 very thin cells and
    // the plate fills its own grid minus the margin: ~((96-2)/96)^3 = 0.94.
    // The point of the case is the ASPECT RATIO -- the Z cells are 25x smaller
    // than the X/Y cells, so a sampler tuned to one axis perforates the others.
    EXPECT_GT(frac, 0.5) << "thin plate perforated (fraction " << frac << ")";
}
