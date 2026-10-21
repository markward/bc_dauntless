#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include "renderer/part_severance_check.h"
#include "renderer/plating_damage.h"
#include "scenegraph/instance.h"

using renderer::plating::DamageList;

namespace {
// Big part 0: x 0..9 (10x6x6). Bridge: x 10 (1x1x1 at y=2,z=2). Small part 1:
// x 11..16 (6x6x6 = 216 voxels). Cells are 1 unit, origin 0.
voxel::StructureSegmentation make_seg(int small_x1 = 16) {
    voxel::StructureSegmentation s;
    s.vol.dims = {20, 6, 6};
    s.vol.origin = {0, 0, 0};
    s.vol.cell = {1, 1, 1};
    const std::size_t n = 20u * 6u * 6u;
    s.vol.occ.assign(n, 0);
    s.label.assign(n, -1);
    s.depth.assign(n, 0.f);
    s.parts.resize(2);
    for (int z = 0; z < 6; ++z)
        for (int y = 0; y < 6; ++y)
            for (int x = 0; x < 20; ++x) {
                int lab = -1;
                if (x <= 9) lab = 0;
                else if (x == 10 && y == 2 && z == 2) lab = 0;
                else if (x >= 11 && x <= small_x1) lab = 1;
                if (lab < 0) continue;
                s.vol.set(x, y, z, true);
                s.label[s.vol.index(x, y, z)] = static_cast<std::int16_t>(lab);
            }
    return s;
}
DamageList bridge_hit(float wear) {
    DamageList l;
    l.count = 1;
    l.a[0] = glm::vec4(10.5f, 2.5f, 2.5f, 1.2f);
    l.b[0] = glm::vec4(0, 0, 0, wear);
    l.c[0] = glm::vec4(3, 0, 0, 0);
    return l;
}
}  // namespace

TEST(PartSeverance, IntactShipSeversNothing) {
    auto s = make_seg();
    DamageList none;
    EXPECT_TRUE(renderer::find_severed_parts(s, none, 6.f, 0).empty());
}

TEST(PartSeverance, BlownBridgeSeversTheSmallerPart) {
    auto s = make_seg();
    auto r = renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0].part, 1);
    EXPECT_EQ(r[0].voxels, 216);
    EXPECT_FLOAT_EQ(r[0].min_body.x, 11.f);
    EXPECT_FLOAT_EQ(r[0].max_body.x, 17.f);
    EXPECT_FLOAT_EQ(r[0].min_body.y, 0.f);
    EXPECT_FLOAT_EQ(r[0].max_body.z, 6.f);
    EXPECT_NEAR(r[0].centroid_body.x, 14.f, 1e-4);
}

TEST(PartSeverance, WeakHitLeavesBridgeStanding) {
    auto s = make_seg();
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(2.f), 6.f, 0).empty());
}

TEST(PartSeverance, AlreadySeveredPartIsNotReported) {
    auto s = make_seg();
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 1u << 1).empty());
}

TEST(PartSeverance, TinyPartBelowMinimumNeverSevers) {
    auto s = make_seg(12);  // x 11..12 = 2*36 = 72 voxels; shrink further below
    // Make the small part 3x3x... below 64: relabel everything but 40 voxels away.
    int kept = 0;
    for (std::size_t i = 0; i < s.label.size(); ++i)
        if (s.label[i] == 1 && ++kept > 40) { s.label[i] = -1; s.vol.occ[i] = 0; }
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0).empty());
}

TEST(PartSeverance, ArticulatedInstanceNeverStructureSevers) {
    scenegraph::Instance inst;
    EXPECT_TRUE(renderer::can_structure_sever(inst));
    inst.node_overrides[3] = glm::mat4(1.f);
    EXPECT_FALSE(renderer::can_structure_sever(inst));
}
