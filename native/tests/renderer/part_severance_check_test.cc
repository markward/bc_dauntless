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

namespace {
// The old O(V x R) reference: per-voxel wear summed over all records.
std::vector<float> reference_wear(const voxel::StructureSegmentation& s, const DamageList& dmg) {
    std::vector<float> w(s.vol.occ.size(), 0.f);
    for (int z = 0; z < s.vol.dims.z; ++z)
        for (int y = 0; y < s.vol.dims.y; ++y)
            for (int x = 0; x < s.vol.dims.x; ++x) {
                const glm::vec3 p = s.vol.origin + (glm::vec3(x, y, z) + 0.5f) * s.vol.cell;
                float acc = 0.f;
                for (int k = 0; k < dmg.count; ++k) {
                    const float R = dmg.a[k].w;
                    if (R <= 0.f) continue;
                    const glm::vec3 dv = p - glm::vec3(dmg.a[k]);
                    const float r2 = glm::dot(dv, dv) / (R * R);
                    if (r2 >= 1.f) continue;
                    const float f = 1.f - r2;
                    acc += dmg.b[k].w * f * f;
                }
                w[s.vol.index(x, y, z)] = acc;
            }
    return w;
}
}  // namespace

TEST(PartSeverance, FarRecordContributesNothing) {
    auto s = make_seg();
    DamageList l = bridge_hit(100.f);
    for (auto c : {glm::vec4(500.f, 500.f, 500.f, 1.2f), glm::vec4(-3.f, 2.5f, 2.5f, 1.2f)}) {
        l.a[0] = c;
        for (float v : renderer::interior_wear_field(s.vol, l)) EXPECT_EQ(v, 0.f);
        EXPECT_TRUE(renderer::find_severed_parts(s, l, 6.f, 0).empty());
    }
}

TEST(PartSeverance, WearFieldMatchesTheFullReference) {
    auto s = make_seg();
    DamageList sets[3];
    sets[0].count = 3;
    sets[0].a[0] = glm::vec4(10.5f, 2.5f, 2.5f, 1.2f);  sets[0].b[0].w = 7.f;
    sets[0].a[1] = glm::vec4(3.f, 1.f, 4.f, 4.f);       sets[0].b[1].w = 3.f;
    sets[0].a[2] = glm::vec4(18.f, 5.f, 5.f, 6.f);      sets[0].b[2].w = 5.f;
    sets[1].count = 3;  // partly outside the grid on every side
    sets[1].a[0] = glm::vec4(-1.f, -1.f, -1.f, 4.f);    sets[1].b[0].w = 2.f;
    sets[1].a[1] = glm::vec4(21.f, 7.f, 6.5f, 5.f);     sets[1].b[1].w = 4.f;
    sets[1].a[2] = glm::vec4(9.f, 3.f, -2.f, 5.f);      sets[1].b[2].w = 1.5f;
    sets[2].count = 2;  // overlapping, one covering the whole grid
    sets[2].a[0] = glm::vec4(10.f, 3.f, 3.f, 50.f);     sets[2].b[0].w = 1.f;
    sets[2].a[1] = glm::vec4(10.5f, 2.5f, 2.5f, 2.f);   sets[2].b[1].w = 6.f;
    for (const auto& l : sets) {
        const auto got = renderer::interior_wear_field(s.vol, l);
        const auto ref = reference_wear(s, l);
        ASSERT_EQ(got.size(), ref.size());
        int nonzero = 0;
        for (std::size_t i = 0; i < got.size(); ++i) {
            EXPECT_FLOAT_EQ(got[i], ref[i]) << i;
            nonzero += ref[i] > 0.f;
        }
        EXPECT_GT(nonzero, 0);
    }
}

TEST(PartSeverance, SeveranceVerdictMatchesReferenceWhereBridgeTrulySevers) {
    auto s = make_seg();
    auto l = bridge_hit(10.f);
    const auto w = reference_wear(s, l);
    auto ref = s;
    for (std::size_t i = 0; i < w.size(); ++i)
        if (w[i] >= 6.f) { ref.vol.occ[i] = 0; ref.label[i] = -1; }
    auto expect = renderer::find_severed_parts(ref, DamageList{}, 1e9f, 0);
    auto got = renderer::find_severed_parts(s, l, 6.f, 0);
    ASSERT_EQ(expect.size(), 1u);
    ASSERT_EQ(got.size(), 1u);
    EXPECT_EQ(expect[0].voxels, got[0].voxels);
}

TEST(PartSeverance, PartiallyCutBridgeDoesNotSever) {
    auto s = make_seg();
    for (int y = 1; y <= 3; ++y)
        for (int z = 1; z <= 3; ++z) {
            s.vol.set(10, y, z, true);
            s.label[s.vol.index(10, y, z)] = 0;
        }
    DamageList l = bridge_hit(10.f);
    l.a[0].w = 0.9f;  // blows the centre plug voxel only
    EXPECT_TRUE(renderer::find_severed_parts(s, l, 6.f, 0).empty());
}

TEST(PartSeverance, PartsBeyondTheMaskNeverSever) {
    auto s = make_seg();
    s.parts.resize(40);
    for (auto& lab : s.label)
        if (lab == 1) lab = 35;
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0).empty());
}

TEST(PartSeverance, MainBodyIsChosenAmongPartsBelowTheMask) {
    auto s = make_seg();
    s.parts.resize(40);
    for (auto& lab : s.label)
        if (lab == 0) lab = 35;  // the big body is beyond the mask
    // Only part 1 (216 voxels) is eligible: it is main, nothing else can sever.
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0).empty());
}
