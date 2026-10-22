#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include <atomic>
#include <chrono>
#include <future>
#include <memory>

#include "renderer/part_severance_check.h"
#include "renderer/part_severance_jobs.h"
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
    EXPECT_EQ(r[0].parts, 1u << 1);
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

// A rigged hull at REST carries no node overrides (identity poses are erased),
// so the overrides check alone cannot see the rig: Instance::rigged gates it
// too (a rigged ship's parts leave through part_severance, never by structure).
TEST(PartSeverance, RiggedInstanceAtRestNeverStructureSevers) {
    scenegraph::Instance inst;
    inst.rigged = true;
    ASSERT_TRUE(inst.node_overrides.empty());
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
    // The reference geometry is already cut, but the check floods only once
    // some voxel breaks: break one unlabelled voxel far from both parts.
    ref.vol.set(19, 5, 5, true);
    DamageList far_break;
    far_break.count = 1;
    far_break.a[0] = glm::vec4(19.5f, 5.5f, 5.5f, 0.5f);
    far_break.b[0] = glm::vec4(0, 0, 0, 2e9f);
    far_break.c[0] = glm::vec4(3, 0, 0, 0);
    auto expect = renderer::find_severed_parts(ref, far_break, 1e9f, 0);
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

// ── split_severed_parts: the parent hides the parts, a chunk draws only them ──
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
    EXPECT_EQ(r[0].piece.parts, 1u << 1);
    EXPECT_EQ(r[0].total_voxels, 360 + 1 + 216) << "every solid voxel of the hull";
    EXPECT_EQ(world.get(parent)->severed_parts, 1u << 1);
    EXPECT_EQ(world.get(parent)->shown_parts, 0u);
    const auto* chunk = world.get(r[0].chunk);
    ASSERT_NE(chunk, nullptr);
    EXPECT_EQ(chunk->shown_parts, 1u << 1);
    EXPECT_EQ(chunk->severed_parts, 0u);
    EXPECT_EQ(chunk->model_handle, world.get(parent)->model_handle);
    EXPECT_EQ(chunk->world, world.get(parent)->world);
    EXPECT_TRUE(chunk->rim_eligible);
    EXPECT_FLOAT_EQ(chunk->rim_strength, 0.4f);
    EXPECT_EQ(chunk->comm_set_id, 3u);
    EXPECT_EQ(chunk->hull_damage.count(), 1) << "the chunk keeps the parent's records";
}

// Phase 4, Task 5: a severed chunk is dead -- no window glow, whatever the
// parent's self-illumination was (blown_parent's is 0.5).
TEST(PartSeverance, SeveredChunkIsDark) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    const auto r = renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f);
    ASSERT_EQ(r.size(), 1u);
    ASSERT_NE(world.get(r[0].chunk), nullptr);
    EXPECT_EQ(world.get(r[0].chunk)->emissive_scale, 0.0f) << "the chunk still glows";
    EXPECT_EQ(world.get(parent)->emissive_scale, 0.5f) << "the parent lost its glow";
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
    // Rigged and at rest: no overrides, still never by structure.
    const auto at_rest = blown_parent(world);
    world.get(at_rest)->rigged = true;
    EXPECT_TRUE(renderer::split_severed_parts(world, at_rest, s, bridge_hit(10.f), 6.f).empty());
    EXPECT_EQ(world.get(at_rest)->severed_parts, 0u);
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
    // The saucer blast lands on the store too, so the second check runs.
    world.get(parent)->hull_damage.add(glm::vec3(0.f, 3.f, 3.f), glm::vec3(0.f), 7.f, 1000.f,
                                       scenegraph::HullDamageKind::Internal);
    renderer::SeveranceStats st;
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_and_saucer_hit(), 6.f, &st)
                    .empty());
    EXPECT_EQ(st.checks, 1) << "the second check was skipped: vacuous";
    EXPECT_EQ(world.get(parent)->severed_parts, 1u << 1);
}

// A part the draw cannot hide still joins the hull: an intact pylon numbered
// past kMaxHideableParts keeps the part beyond it attached. Some voxel must
// break or find_severed_parts returns before the flood (and the test could
// never fail): a far, SOLID but unlabelled voxel is blown, which joins no
// part and cuts nothing.
TEST(PartSeverance, SplitKeepsAnUnhideablePartInTheConnectivity) {
    auto s = make_seg();
    s.parts.resize(renderer::kMaxHideableParts + 1);
    s.label[s.vol.index(10, 2, 2)] = static_cast<std::int16_t>(renderer::kMaxHideableParts);
    s.vol.set(19, 5, 5, true);                                // solid, label -1
    ASSERT_EQ(s.label[s.vol.index(19, 5, 5)], -1);
    DamageList far;
    far.count = 1;
    far.a[0] = glm::vec4(19.5f, 5.5f, 5.5f, 0.6f);
    far.b[0] = glm::vec4(0, 0, 0, 100.f);
    far.c[0] = glm::vec4(3, 0, 0, 0);
    const std::uint32_t unhideable = ~((1u << renderer::kMaxHideableParts) - 1u);
    renderer::SeveranceStats st;
    ASSERT_TRUE(renderer::find_severed_parts(s, far, 6.f, unhideable, 0, &st).empty());
    ASSERT_EQ(st.floods, 1) << "nothing broke: the flood never ran, the test is vacuous";
    scenegraph::World world;
    const auto parent = blown_parent(world);
    world.get(parent)->hull_damage = scenegraph::HullDamageStore{};
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, far, 6.f).empty());
    EXPECT_EQ(world.get(parent)->severed_parts, 0u);
}

TEST(PartSeverance, AChunkNeverSevers) {
    auto s = make_seg();
    scenegraph::World world;
    const auto chunk = blown_parent(world);
    world.get(chunk)->shown_parts = 1u << 0;
    EXPECT_TRUE(renderer::split_severed_parts(world, chunk, s, bridge_hit(10.f), 6.f).empty());
    EXPECT_EQ(world.get(chunk)->severed_parts, 0u);
}

// ── Ruling 4: a cut-off assembly leaves as ONE piece ─────────────────────
namespace {
// Body (part 0, x 0..9) -- bridge (x 10, one voxel) -- A (part 1, x 11..16)
// -- B (part 2, x 17..22): A and B touch face to face.
voxel::StructureSegmentation make_chain() {
    voxel::StructureSegmentation s;
    s.vol.dims = {30, 6, 6};
    s.vol.origin = {0, 0, 0};
    s.vol.cell = {1, 1, 1};
    const std::size_t n = 30u * 6u * 6u;
    s.vol.occ.assign(n, 0);
    s.label.assign(n, -1);
    s.depth.assign(n, 0.f);
    s.parts.resize(3);
    for (int z = 0; z < 6; ++z)
        for (int y = 0; y < 6; ++y)
            for (int x = 0; x < 30; ++x) {
                int lab = -1;
                if (x <= 9) lab = 0;
                else if (x == 10 && y == 2 && z == 2) lab = 0;
                else if (x >= 11 && x <= 16) lab = 1;
                else if (x >= 17 && x <= 22) lab = 2;
                if (lab < 0) continue;
                s.vol.set(x, y, z, true);
                s.label[s.vol.index(x, y, z)] = static_cast<std::int16_t>(lab);
            }
    return s;
}
// Body (part 0, x 0..9) welded face to face to part 1 (x 10..19).
voxel::StructureSegmentation make_welded() {
    voxel::StructureSegmentation s = make_seg(19);
    for (int z = 0; z < 6; ++z)
        for (int y = 0; y < 6; ++y) {
            s.vol.set(10, y, z, true);
            s.label[s.vol.index(10, y, z)] = 1;
        }
    return s;
}
// Blows exactly the 6x6 slab at x (one record per voxel, reach 0.6 < 1 cell).
DamageList slab_cut(int x) {
    DamageList l;
    for (int z = 0; z < 6; ++z)
        for (int y = 0; y < 6; ++y) {
            const int k = l.count++;
            l.a[k] = glm::vec4(x + 0.5f, y + 0.5f, z + 0.5f, 0.6f);
            l.b[k] = glm::vec4(0, 0, 0, 100.f);
            l.c[k] = glm::vec4(3, 0, 0, 0);
        }
    return l;
}
}  // namespace

TEST(PartSeverance, ACutOffAssemblyLeavesAsOnePiece) {
    auto s = make_chain();
    const auto r = renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0);
    ASSERT_EQ(r.size(), 1u) << "A and B came off together: one piece";
    EXPECT_EQ(r[0].parts, (1u << 1) | (1u << 2));
    EXPECT_EQ(r[0].voxels, 432);
    EXPECT_FLOAT_EQ(r[0].min_body.x, 11.f);
    EXPECT_FLOAT_EQ(r[0].max_body.x, 23.f);
    EXPECT_NEAR(r[0].centroid_body.x, 17.f, 1e-4);
}

// A piece's size, centroid and bounds are its MEMBER parts' voxels only: a
// part riding in the same component that does not leave (here B, already
// severed -- as an unhideable part is) is not part of what the chunk draws.
TEST(PartSeverance, PieceExtentCountsOnlyItsMemberParts) {
    auto s = make_chain();
    const auto r = renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 1u << 2);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0].parts, 1u << 1);
    EXPECT_EQ(r[0].voxels, 216) << "B's voxels counted in A's piece";
    EXPECT_FLOAT_EQ(r[0].min_body.x, 11.f);
    EXPECT_FLOAT_EQ(r[0].max_body.x, 17.f);
    EXPECT_NEAR(r[0].centroid_body.x, 14.f, 1e-4);
}

TEST(PartSeverance, SplitInstancesOneChunkPerAssembly) {
    auto s = make_chain();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    const auto r = renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0].piece.parts, (1u << 1) | (1u << 2));
    EXPECT_EQ(world.get(parent)->severed_parts, (1u << 1) | (1u << 2));
    EXPECT_EQ(world.get(r[0].chunk)->shown_parts, (1u << 1) | (1u << 2));
}

TEST(PartSeverance, APartCutMidwayGoesWithTheSideHoldingMostOfIt) {
    auto s = make_welded();
    // Cut at x 13: part 1 keeps x 10..12 (108) on the body, x 14..19 (216) off.
    auto r = renderer::find_severed_parts(s, slab_cut(13), 6.f, 0);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(r[0].parts, 1u << 1);
    EXPECT_EQ(r[0].voxels, 216) << "the piece is the cut-off side";
    EXPECT_FLOAT_EQ(r[0].min_body.x, 14.f);
    // Cut at x 16: most of part 1 (x 10..15) stays; the stub x 17..19 holds
    // no part's majority, so nothing leaves.
    EXPECT_TRUE(renderer::find_severed_parts(s, slab_cut(16), 6.f, 0).empty());
}

// ── I4: the check costs nothing when nothing can have changed ────────────
TEST(PartSeverance, NoFloodWhenNoVoxelReachesDeckBreak) {
    auto s = make_seg();
    renderer::SeveranceStats st;
    EXPECT_TRUE(renderer::find_severed_parts(s, DamageList{}, 6.f, 0, 0, &st).empty());
    EXPECT_TRUE(renderer::find_severed_parts(s, bridge_hit(2.f), 6.f, 0, 0, &st).empty());
    EXPECT_EQ(st.floods, 0) << "no voxel broke: nothing to flood";
    EXPECT_EQ(renderer::find_severed_parts(s, bridge_hit(10.f), 6.f, 0, 0, &st).size(), 1u);
    EXPECT_EQ(st.floods, 1);
}

TEST(PartSeverance, SplitSkipsAnUnchangedHull) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    renderer::SeveranceStats st;
    // A store that blows nothing through: checked once, then skipped.
    world.get(parent)->hull_damage = scenegraph::HullDamageStore{};
    world.get(parent)->hull_damage.add(glm::vec3(3.f), glm::vec3(0.f), 1.f, 1.f,
                                       scenegraph::HullDamageKind::Internal);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(2.f), 6.f, &st).empty());
    EXPECT_EQ(st.checks, 1);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(2.f), 6.f, &st).empty());
    EXPECT_EQ(st.checks, 1) << "same revision, same severed parts: skipped";
    // New damage (the store revision moves): checked again, and it severs.
    world.get(parent)->hull_damage.add(glm::vec3(10.5f, 2.5f, 2.5f), glm::vec3(0.f), 1.2f, 10.f,
                                       scenegraph::HullDamageKind::Internal);
    EXPECT_EQ(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f, &st).size(),
              1u);
    EXPECT_EQ(st.checks, 2);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f, &st).empty());
    EXPECT_EQ(st.checks, 2) << "the split's own severed bits are part of the stamp";
    // severed_parts changed from outside, or the deck break dial moved: re-check.
    world.get(parent)->severed_parts = 0;
    EXPECT_EQ(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f, &st).size(),
              1u);
    EXPECT_EQ(st.checks, 3);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 7.f, &st).empty());
    EXPECT_EQ(st.checks, 4);
}

// ── M2 / M3 ──────────────────────────────────────────────────────────────
TEST(PartSeverance, AChunkKeepsTheParentsScorchMarks) {
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    world.get(parent)->decals.add(glm::vec3(14.f, 3.f, 6.f), glm::vec3(0, 0, 1), 0.5f, 1.f,
                                  scenegraph::WeaponClass::Scorch, 0.f);
    world.get(parent)->decals.add(glm::vec3(2.f, 3.f, 6.f), glm::vec3(0, 0, 1), 0.5f, 1.f,
                                  scenegraph::WeaponClass::Scorch, 0.f);
    const auto r = renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_EQ(world.get(r[0].chunk)->decals.count(), 2u) << "the piece keeps its scorch";
}

TEST(PartSeverance, ASkinnedModelNeverSevers) {
    // The draw cannot hide parts on a skinned model (draws_skinned bypasses
    // part hiding), so it must never lose one.
    auto s = make_seg();
    scenegraph::World world;
    const auto parent = blown_parent(world);
    EXPECT_TRUE(renderer::split_severed_parts(world, parent, s, bridge_hit(10.f), 6.f, nullptr,
                                              /*skinned=*/true)
                    .empty());
    EXPECT_EQ(world.get(parent)->severed_parts, 0u);
}

// ── M1: the structure part at a body point (subsystem kill by label) ─────
TEST(PartSeverance, StructurePartAtReadsTheVoxelLabel) {
    const auto s = make_seg();
    EXPECT_EQ(renderer::structure_part_at(s, glm::vec3(5.5f, 3.f, 3.f)), 0);
    EXPECT_EQ(renderer::structure_part_at(s, glm::vec3(14.f, 3.f, 3.f)), 1);
    EXPECT_EQ(renderer::structure_part_at(s, glm::vec3(18.5f, 3.f, 3.f)), -1) << "empty voxel";
    EXPECT_EQ(renderer::structure_part_at(s, glm::vec3(25.f, 3.f, 3.f)), -1) << "past the grid";
    EXPECT_EQ(renderer::structure_part_at(s, glm::vec3(-0.5f, 3.f, 3.f)), -1) << "before it";
    EXPECT_EQ(renderer::structure_part_at(voxel::StructureSegmentation{}, glm::vec3(0.f)), -1);
}

// ── Ruling 10: the check runs on a worker (part_severance_jobs.h) ─────────
namespace {
int live_instances(const scenegraph::World& world) {
    int n = 0;
    world.for_each_visible([&](const scenegraph::Instance&) { ++n; });
    return n;
}
renderer::SeveranceJobs::DamageFn fixed_damage(DamageList l) {
    return [l](const scenegraph::Instance&) { return l; };
}
}  // namespace

// (1) The first poll queues the job and answers pending, touching nothing; a
// later poll applies EXACTLY what the synchronous split does on the same input.
TEST(PartSeveranceAsync, FirstPollIsPendingThenMatchesTheSynchronousSplit) {
    const auto seg = std::make_shared<const voxel::StructureSegmentation>(make_seg());
    scenegraph::World ref_world;
    const auto ref_parent = blown_parent(ref_world);
    const auto ref = renderer::split_severed_parts(ref_world, ref_parent, *seg,
                                                   bridge_hit(10.f), 6.f);
    ASSERT_EQ(ref.size(), 1u);

    scenegraph::World world;
    const auto parent = blown_parent(world);
    renderer::SeveranceJobs jobs;
    renderer::SeveranceStats st;
    const auto first = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f,
                                 false, &st);
    EXPECT_TRUE(first.pending) << "the check ran on the calling thread";
    EXPECT_TRUE(first.split.empty());
    EXPECT_EQ(world.get(parent)->severed_parts, 0u) << "applied before the job landed";
    EXPECT_FALSE(world.get(parent)->part_check.valid);
    EXPECT_EQ(live_instances(world), 1) << "a chunk was made before the job landed";
    EXPECT_TRUE(jobs.has_job(parent));
    EXPECT_EQ(st.checks, 1);

    jobs.wait_for_test(parent);
    const auto got = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f,
                               false, &st);
    EXPECT_FALSE(got.pending);
    EXPECT_FALSE(jobs.has_job(parent));
    ASSERT_EQ(got.split.size(), ref.size());
    const auto& a = got.split[0];
    const auto& b = ref[0];
    EXPECT_EQ(a.piece.parts, b.piece.parts);
    EXPECT_EQ(a.piece.voxels, b.piece.voxels);
    EXPECT_EQ(a.total_voxels, b.total_voxels);
    EXPECT_EQ(a.piece.centroid_body, b.piece.centroid_body);
    EXPECT_EQ(a.piece.min_body, b.piece.min_body);
    EXPECT_EQ(a.piece.max_body, b.piece.max_body);
    EXPECT_EQ(world.get(parent)->severed_parts, ref_world.get(ref_parent)->severed_parts);
    const auto* chunk = world.get(a.chunk);
    const auto* ref_chunk = ref_world.get(b.chunk);
    ASSERT_NE(chunk, nullptr);
    ASSERT_NE(ref_chunk, nullptr);
    EXPECT_EQ(chunk->shown_parts, ref_chunk->shown_parts);
    EXPECT_EQ(chunk->world, ref_chunk->world);
    EXPECT_EQ(chunk->emissive_scale, 0.0f);
    EXPECT_EQ(chunk->hull_damage.count(), ref_chunk->hull_damage.count());
    EXPECT_TRUE(world.get(parent)->part_check.valid);

    // Nothing changed since: no new job (the stamp), and nothing re-reported.
    const auto again = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f,
                                 false, &st);
    EXPECT_FALSE(again.pending);
    EXPECT_TRUE(again.split.empty());
    EXPECT_EQ(st.checks, 1);
}

// (2) A result computed on damage that has since moved is dropped -- nothing
// applied -- and the check re-queued on the current inputs.
TEST(PartSeveranceAsync, AResultIsDroppedWhenTheRevisionMovedMeanwhile) {
    const auto seg = std::make_shared<const voxel::StructureSegmentation>(make_seg());
    scenegraph::World world;
    const auto parent = blown_parent(world);
    renderer::SeveranceJobs jobs;
    renderer::SeveranceStats st;
    ASSERT_TRUE(jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f, false, &st)
                    .pending);
    jobs.wait_for_test(parent);
    world.get(parent)->hull_damage.add(glm::vec3(3.f), glm::vec3(0.f), 1.f, 1.f,
                                       scenegraph::HullDamageKind::Internal);
    const auto stale = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f,
                                 false, &st);
    EXPECT_TRUE(stale.split.empty()) << "a stale result was applied";
    EXPECT_EQ(world.get(parent)->severed_parts, 0u);
    EXPECT_EQ(live_instances(world), 1);
    EXPECT_TRUE(stale.pending) << "the dropped check was not re-queued";
    EXPECT_EQ(st.checks, 2);
    jobs.wait_for_test(parent);
    const auto fresh = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f,
                                 false, &st);
    ASSERT_EQ(fresh.split.size(), 1u) << "the re-queued check on current damage applies";
    EXPECT_EQ(world.get(parent)->severed_parts, 1u << 1);
}

// The severed mask moving meanwhile (another split, or a reset) drops it too.
TEST(PartSeveranceAsync, AResultIsDroppedWhenTheSeveredMaskMovedMeanwhile) {
    const auto seg = std::make_shared<const voxel::StructureSegmentation>(make_chain());
    scenegraph::World world;
    const auto parent = blown_parent(world);
    renderer::SeveranceJobs jobs;
    ASSERT_TRUE(jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f).pending);
    jobs.wait_for_test(parent);
    world.get(parent)->severed_parts = 1u << 2;
    const auto stale = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f);
    EXPECT_TRUE(stale.split.empty()) << "a result on the old mask was applied";
    EXPECT_TRUE(stale.pending);
    jobs.wait_for_test(parent);
    const auto fresh = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f);
    ASSERT_EQ(fresh.split.size(), 1u);
    EXPECT_EQ(fresh.split[0].piece.parts, 1u << 1) << "part 2 already left: A goes alone";
}

// (3) A destroyed instance's job never applies and never crashes: polled for
// the dead id, forgotten while still running, or outliving the queue itself.
TEST(PartSeveranceAsync, ADestroyedInstancesJobNeverApplies) {
    const auto seg = std::make_shared<const voxel::StructureSegmentation>(make_seg());
    scenegraph::World world;
    const auto parent = blown_parent(world);
    renderer::SeveranceJobs jobs;
    ASSERT_TRUE(jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f).pending);
    jobs.wait_for_test(parent);
    world.destroy_instance(parent);
    const auto dead = jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f);
    EXPECT_FALSE(dead.pending);
    EXPECT_TRUE(dead.split.empty());
    EXPECT_FALSE(jobs.has_job(parent));
    EXPECT_EQ(live_instances(world), 0) << "a chunk was made for a dead hull";
    // A recycled slot (same index, new generation) is another instance.
    const auto next = blown_parent(world);
    EXPECT_FALSE(jobs.has_job(next));
}

TEST(PartSeveranceAsync, AForgottenRunningJobFinishesOnItsOwnInputs) {
    std::promise<void> gate;
    std::shared_future<void> open = gate.get_future().share();
    std::atomic<int> ran{0};
    scenegraph::World world;
    const auto parent = blown_parent(world);
    {
        renderer::SeveranceJobs jobs;
        jobs.set_before_run_for_test([open, &ran] {
            open.wait_for(std::chrono::seconds(10));   // never hangs the suite
            ++ran;
        });
        {
            auto seg = std::make_shared<const voxel::StructureSegmentation>(make_seg());
            ASSERT_TRUE(
                jobs.poll(world, parent, seg, fixed_damage(bridge_hit(10.f)), 6.f).pending);
        }   // the caller's segmentation reference is gone; the job holds its own
        world.destroy_instance(parent);
        jobs.forget(parent);   // must not wait for the running job
        EXPECT_EQ(ran.load(), 0) << "forget waited for the job";
        EXPECT_FALSE(jobs.has_job(parent));
        EXPECT_EQ(jobs.outstanding(), 1u) << "the running job is still owned";
        // A second, still-running job dropped by clear() (a world reset).
        const auto other = blown_parent(world);
        ASSERT_TRUE(jobs.poll(world, other, std::make_shared<const voxel::StructureSegmentation>(
                                                     make_seg()),
                              fixed_damage(bridge_hit(10.f)), 6.f)
                        .pending);
        jobs.clear();
        EXPECT_EQ(ran.load(), 0) << "clear waited for the job";
        EXPECT_FALSE(jobs.has_job(other));
        gate.set_value();
    }   // the queue waits for both to finish
    EXPECT_EQ(ran.load(), 2);
    EXPECT_EQ(live_instances(world), 1) << "a forgotten job applied";
}

// The same gates as the synchronous split: these never queue a job.
TEST(PartSeveranceAsync, NeverQueuesForHullsThatCannotSever) {
    const auto seg = std::make_shared<const voxel::StructureSegmentation>(make_seg());
    scenegraph::World world;
    renderer::SeveranceJobs jobs;
    const auto rock = blown_parent(world);
    world.get(rock)->surface_is_rock = true;
    const auto rigged = blown_parent(world);
    world.get(rigged)->rigged = true;
    const auto chunk = blown_parent(world);
    world.get(chunk)->shown_parts = 1u;
    const auto skinned = blown_parent(world);
    for (const auto id : {rock, rigged, chunk}) {
        const auto r = jobs.poll(world, id, seg, fixed_damage(bridge_hit(10.f)), 6.f);
        EXPECT_FALSE(r.pending);
        EXPECT_FALSE(jobs.has_job(id));
    }
    EXPECT_FALSE(
        jobs.poll(world, skinned, seg, fixed_damage(bridge_hit(10.f)), 6.f, true).pending);
    EXPECT_FALSE(jobs.poll(world, skinned, nullptr, fixed_damage(bridge_hit(10.f)), 6.f).pending)
        << "no segmentation yet: nothing to run";
    EXPECT_EQ(jobs.outstanding(), 0u);
}
