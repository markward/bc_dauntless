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

// A regression test for the anisotropic-dims clamp bug. The original flat 512
// clamp was correct only for isotropic grids and could silently reintroduce the
// pinhole bug for anisotropic dims like 49x67x17 (Galaxy hull). The clamp must
// be derived from the grid to ensure every axis is sampled at 0.5 cells or finer.
TEST(VoxelizeResolution, AnisotropicDimsStaySolidUnderClamp) {
    // Strongly anisotropic grid: 40 cells in X, 300 in Y, 10 in Z.
    // Each axis has the same extent (1000) but vastly different cell sizes:
    // cell.x = 1000/38 ~ 26.3, cell.y = 1000/298 ~ 3.36, cell.z = 1000/8 = 125.
    // The Y axis has the smallest cells and is the bottleneck.
    //
    // A large box (1000^3) has edges that span the full extent. The longest edge
    // needs unclamped N = ceil(1732 / 1.68) ~ 1031 samples. A flat 512 clamp
    // would cause under-sampling in Y (spacing ~1.95 > allowed ~1.68). The
    // dynamic clamp 2*max(38, 298, 8) = 596 prevents this.
    const glm::ivec3 dims(40, 300, 10);
    const glm::vec3 origin(0.f);
    const glm::vec3 cell(1000.f / (dims.x - 2), 1000.f / (dims.y - 2), 1000.f / (dims.z - 2));

    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(1000.0f));

    const voxel::VoxelVolume v = voxel::voxelize_into(tris, dims, origin, cell);
    const double frac = static_cast<double>(v.solid_count())
                      / (static_cast<double>(dims.x) * dims.y * dims.z);

    // With the dynamic clamp, solid fraction should be > 0.5.
    // With a flat 512 clamp, this would collapse to ~0.02.
    EXPECT_GT(frac, 0.5)
        << "anisotropic grid collapsed (fraction " << frac
        << " with dims " << dims.x << "x" << dims.y << "x" << dims.z << ")";
}

// Regression test for degenerate dims. When dims_i <= 2, the dynamic clamp
// computation max_samples = max(2*(dims_i-2), ...) would underflow to <= 0
// without a floor, causing N to become 0 (NaN in u = 0/0) or negative (loop
// skips silently). The floor ensures N >= 1 unconditionally.
TEST(VoxelizeResolution, DegenerateDims2x2x2DoesNotCrash) {
    const glm::ivec3 dims(2, 2, 2);
    const glm::vec3 origin(0.f);
    const glm::vec3 cell(100.f, 100.f, 100.f);

    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    // Call should not crash, produce NaN, or silently skip triangles.
    const voxel::VoxelVolume v = voxel::voxelize_into(tris, dims, origin, cell);

    // Occupancy vector should have correct size.
    EXPECT_EQ(v.occ.size(), static_cast<std::size_t>(dims.x * dims.y * dims.z));

    // All occupancy values must be 0 or 1 (no garbage from NaN).
    for (std::uint8_t occ_val : v.occ) {
        EXPECT_TRUE(occ_val == 0 || occ_val == 1)
            << "found non-binary occupancy value: " << static_cast<int>(occ_val);
    }
}

// Regression test for even more degenerate dims: 1x1x1.
// Without a floor on the clamp, max_samples = 2*(1-2) = -2, and N would
// underflow to negative, silently skipping all triangles.
TEST(VoxelizeResolution, DegenerateDims1x1x1DoesNotCrash) {
    const glm::ivec3 dims(1, 1, 1);
    const glm::vec3 origin(0.f);
    const glm::vec3 cell(100.f, 100.f, 100.f);

    const std::vector<voxel::Tri> tris =
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f));

    // Call should not crash or silently fail.
    const voxel::VoxelVolume v = voxel::voxelize_into(tris, dims, origin, cell);

    // Occupancy vector should have correct size.
    EXPECT_EQ(v.occ.size(), static_cast<std::size_t>(dims.x * dims.y * dims.z));

    // All occupancy values must be 0 or 1 (no garbage).
    for (std::uint8_t occ_val : v.occ) {
        EXPECT_TRUE(occ_val == 0 || occ_val == 1)
            << "found non-binary occupancy value: " << static_cast<int>(occ_val);
    }
}
