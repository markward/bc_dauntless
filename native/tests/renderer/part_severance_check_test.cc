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

// ── split_severed_parts: the parent hides the part, a chunk draws only it ──
namespace {
// A parent instance whose store blows the bridge (make_seg) through.
scenegraph::InstanceId blown_parent(scenegraph::World& world) {
    const auto id = world.create_instance(scenegraph::ModelHandle{0x10});
    auto* inst = world.get(id);
    inst->world = glm::mat4(2.0f);
    inst->world[3] = glm::vec4(5.f, 6.f, 7.f, 1.f);
    inst->rim_eligible = true;
    inst->rim_strength = 0.4f;
    inst->emissive_scale = 0.5f;
    inst->comm_set_id = 3;
    inst->hull_damage.add(glm::vec3(10.5f, 2.5f, 2.5f), glm::vec3(0.f), 1.2f, 10.f,
                          scenegraph::HullDamageKind::Internal);
    return id;
}
}  // namespace

TEST(PartSeverance, SplitHidesThePartOnTheParentAndInstancesAChunk) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    const auto r = renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0].part.part, 1);
    EXPECT_EQ(r[0].total_voxels, 360 + 1 + 216) << "every solid voxel of the hull";
    EXPECT_EQ(world.get(parent)->severed_parts, 1u << 1);
    EXPECT_EQ(world.get(parent)->only_part, -1);
    const auto* chunk = world.get(r[0].chunk);
    ASSERT_NE(chunk, nullptr);
    EXPECT_EQ(chunk->only_part, 1);
    EXPECT_EQ(chunk->severed_parts, 0u);
    EXPECT_EQ(chunk->model_handle, world.get(parent)->model_handle);
    EXPECT_EQ(chunk->world, world.get(parent)->world);
    EXPECT_TRUE(chunk->rim_eligible);
    EXPECT_FLOAT_EQ(chunk->rim_strength, 0.4f);
    EXPECT_FLOAT_EQ(chunk->emissive_scale, 0.5f);
    EXPECT_EQ(chunk->comm_set_id, 3u);
    EXPECT_EQ(chunk->hull_damage.count(), 1) << "the chunk keeps the parent's records";
}

TEST(PartSeverance, SplitReportsAPartOnce) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    ASSERT_EQ(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f).size(), 1u);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f).empty());
}

TEST(PartSeverance, SplitNeverSeversRocksOrArticulatedHulls) {
    auto s = make_seg();
    scenegraph::World world;
    const auto rock = blown_parent(world);
    world.get(rock)->surface_is_rock = true;
    EXPECT_TRUE(renderer::split_severed_parts(world, rock, s, bridge_hit(10.f), 6.f).empty());
    EXPECT_EQ(world.get(rock)->severed_parts, 0u);
    const auto rigged = blown_parent(world);
    world.get(rigged)->node_overrides[2] = glm::mat4(1.f);
    EXPECT_TRUE(renderer::split_severed_parts(world, rigged, s, bridge_hit(10.f), 6.f).empty());
    EXPECT_TRUE(renderer::split_severed_parts(world, scenegraph::InstanceId{}, s,
                                              bridge_hit(10.f), 6.f).empty());
}

TEST(PartSeverance, SplitNeverSeversAPartTheDrawCannotHide) {
    auto s = make_seg();
    s.parts.resize(renderer::kMaxHideableParts + 1);
    for (auto& lab : s.label)
        if (lab == 1) lab = static_cast<std::int16_t>(renderer::kMaxHideableParts);
    scenegraph::World world;
    const auto parent = blown_parent(world);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f).empty());
}

// ── A part that has left never carries the flood (fix round 1, I1) ────────
namespace {
// bridge_hit plus a blast that kills x 0..5 of part 0 (216 of its 361
// voxels), leaving part 0 fewer survivors than the lost part 1 (216).
DamageList bridge_and_saucer_hit() {
    DamageList l = bridge_hit(10.f);
    l.count = 2;
    l.a[1] = glm::vec4(0.f, 3.f, 3.f, 7.f);
    l.b[1] = glm::vec4(0, 0, 0, 1000.f);
    l.c[1] = glm::vec4(3, 0, 0, 0);
    return l;
}
int alive_in_part(const voxel::StructureSegmentation& s, const DamageList& l, int part) {
    const auto w = renderer::interior_wear_field(s.vol, l);
    int n = 0;
    for (std::size_t i = 0; i < w.size(); ++i)
        if (s.vol.occ[i] && s.label[i] == part && w[i] < 6.f) ++n;
    return n;
}
}  // namespace

TEST(PartSeverance, AGonePartIsNeverTheMainBody) {
    auto s = make_seg();
    const DamageList l = bridge_and_saucer_hit();
    ASSERT_LT(alive_in_part(s, l, 0), alive_in_part(s, l, 1))
        << "precondition: the lost part has more survivors than the hull";
    EXPECT_TRUE(renderer::find_severed_parts(s, l, 6.f, 1u << 1, 1u << 1).empty());
}

TEST(PartSeverance, SplitAfterALossNeverSeversTheRemainingHull) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    ASSERT_EQ(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f).size(), 1u);
    EXPECT_TRUE(
        renderer::split_severed_parts(world, parent, s, bridge_and_saucer_hit(), 6.f).empty());
    EXPECT_EQ(world.get(parent)->severed_parts, 1u << 1);
}

// A part the draw cannot hide still joins the hull: an intact pylon numbered
// past kMaxHideableParts keeps the part beyond it attached.
TEST(PartSeverance, SplitKeepsAnUnhideablePartInTheConnectivity) {
    auto s = make_seg();
    s.parts.resize(renderer::kMaxHideableParts + 1);
    s.label[s.vol.index(10, 2, 2)] = static_cast<std::int16_t>(renderer::kMaxHideableParts);
    scenegraph::World world;
    const auto parent = blown_parent(world);
    world.get(parent)->hull_damage = scenegraph::HullDamageStore{};
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, DamageList{}, 6.f).empty());
}

TEST(PartSeverance, AChunkNeverSevers) {
    auto s = make_seg();
    scenegraph::World world;
    const auto chunk = blown_parent(world);
    world.get(chunk)->only_part = 0;
    EXPECT_TRUE(renderer::split_severed_parts(world, chunk, s, bridge_hit(10.f), 6.f).empty());
    EXPECT_EQ(world.get(chunk)->severed_parts, 0u);
}
