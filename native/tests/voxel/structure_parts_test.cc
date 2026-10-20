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

// Label of the voxel containing body point `p`, or -1 outside the grid.
int label_at(const voxel::StructureSegmentation& seg, const glm::vec3& p) {
    const glm::ivec3 c = glm::ivec3(glm::floor((p - seg.vol.origin) / seg.vol.cell));
    if (glm::any(glm::lessThan(c, glm::ivec3(0))) ||
        glm::any(glm::greaterThanEqual(c, seg.vol.dims)))
        return -1;
    return seg.label[seg.vol.index(c.x, c.y, c.z)];
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

TEST(StructureParts, PartsComeBackLargestFirst) {
    // Built so detection's own order is the WRONG one: regions are numbered
    // from the deepest core voxels, and the small cube (60 mu, ~6 cells
    // deep) is far deeper than the big thin slab (12 mu thick). Unsorted, the
    // cube comes back first (2028 vs 6406 voxels, mutation-checked with the
    // sort removed), so only the sort makes the slab part 0.
    std::vector<voxel::Tri> tris;
    add_box(tris, {-100, 150, 40}, {100, 350, 52});      // big thin slab
    add_box(tris, {-30, -300, -60}, {30, -240, 0});      // small deep cube
    const auto seg = voxel::detect_structure_parts(tris);
    ASSERT_GE(seg.parts.size(), 2u);
    for (size_t i = 1; i < seg.parts.size(); ++i)
        EXPECT_GE(seg.parts[i - 1].voxels, seg.parts[i].voxels);
    for (std::int16_t l : seg.label) {
        if (l >= 0) { EXPECT_LT(l, static_cast<int>(seg.parts.size())); }
    }
    // Labels follow the sort: the voxel at the slab's centre carries part 0,
    // the largest, whose fitted centre is the slab's; the voxel at the cube's
    // centre carries the part whose fitted centre is the cube's.
    const glm::vec3 slab_centre(0.0f, 250.0f, 46.0f);
    const glm::vec3 cube_centre(0.0f, -270.0f, -30.0f);
    const int slab_label = label_at(seg, slab_centre);
    const int cube_label = label_at(seg, cube_centre);
    EXPECT_EQ(slab_label, 0);
    ASSERT_GE(slab_label, 0);
    ASSERT_GE(cube_label, 0);
    EXPECT_NE(cube_label, slab_label);
    EXPECT_LT(glm::length(seg.parts[slab_label].centre - slab_centre), 10.0f);
    EXPECT_LT(glm::length(seg.parts[cube_label].centre - cube_centre), 10.0f);
}
