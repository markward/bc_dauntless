// SPIKE (damage redesign): structure-part detection on synthetic solids.
#include <gtest/gtest.h>

#include <cmath>
#include <vector>

#include <voxel/structure_parts.h>

namespace {

// Closed box mesh, outward-wound, 12 triangles.
void add_box(std::vector<voxel::Tri>& out, glm::vec3 lo, glm::vec3 hi) {
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z}};
    const int f[12][3] = {{0, 2, 1}, {0, 3, 2}, {4, 5, 6}, {4, 6, 7}, {0, 1, 5}, {0, 5, 4},
                          {2, 3, 7}, {2, 7, 6}, {1, 2, 6}, {1, 6, 5}, {0, 4, 7}, {0, 7, 3}};
    for (const auto& t : f) out.push_back({c[t[0]], c[t[1]], c[t[2]]});
}

}  // namespace

TEST(StructureParts, SolidDepthIsDistanceToTheNearestEmptyCell) {
    voxel::VoxelVolume v;
    v.dims = {7, 7, 7};
    v.cell = glm::vec3(1.0f);
    v.occ.assign(7 * 7 * 7, 0);
    for (int z = 1; z < 6; ++z)
        for (int y = 1; y < 6; ++y)
            for (int x = 1; x < 6; ++x) v.set(x, y, z, true);
    const auto d = voxel::solid_depth(v);
    EXPECT_FLOAT_EQ(d[v.index(1, 3, 3)], 1.0f);
    EXPECT_FLOAT_EQ(d[v.index(3, 3, 3)], 3.0f);
    EXPECT_FLOAT_EQ(d[v.index(0, 0, 0)], 0.0f);
}

TEST(StructureParts, FlatSlabIsADiscAndLongBarIsACylinder) {
    std::vector<voxel::Tri> tris;
    add_box(tris, {-100, -100, -8}, {100, 100, 8});      // saucer-like slab
    add_box(tris, {-12, -300, -60}, {12, -140, -36});    // separate nacelle-like bar
    const auto seg = voxel::detect_structure_parts(tris);
    ASSERT_EQ(seg.parts.size(), 2u);
    const voxel::StructurePart* disc = nullptr;
    const voxel::StructurePart* cyl = nullptr;
    for (const auto& p : seg.parts) {
        if (p.kind == voxel::PartKind::Disc) disc = &p;
        if (p.kind == voxel::PartKind::Cylinder) cyl = &p;
    }
    ASSERT_NE(disc, nullptr);
    ASSERT_NE(cyl, nullptr);
    EXPECT_GT(std::fabs(disc->axis[0].z), 0.95f);        // disc normal = thin axis
    EXPECT_GT(std::fabs(cyl->axis[0].y), 0.95f);         // cylinder axis = long axis
    EXPECT_NEAR(cyl->centre.y, -220.0f, 8.0f);
}
