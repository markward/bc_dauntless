#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <array>
#include "renderer/plating_damage.h"
#include "scenegraph/hull_damage.h"

using scenegraph::HullDamageKind;
using scenegraph::HullDamageStore;

namespace {
std::array<float, renderer::plating::kParamCount> zero_params() {
    std::array<float, renderer::plating::kParamCount> p{};
    return p;
}
const glm::vec3 kUp{0, 0, 1};
}  // namespace

TEST(PlatingDamage, EmptyStoreGivesAnEmptyList) {
    HullDamageStore s;
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

TEST(PlatingDamage, SurfaceReachTakesTheReachMultiplier) {
    HullDamageStore s;
    s.add({1, 2, 3}, kUp, 10.0f, 1.0f, HullDamageKind::Surface);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].w, 4.0f);
    EXPECT_FLOAT_EQ(l.a[0].x, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].w, 1.0f);
    EXPECT_FLOAT_EQ(l.b[0].z, 1.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 1.0f);
}

TEST(PlatingDamage, InternalKeepsItsRadiusAndHasNoFacing) {
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 10.0f, HullDamageKind::Internal);
    auto p = zero_params();
    p[7] = 0.4f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 1);
    EXPECT_FLOAT_EQ(l.a[0].w, 30.0f);
    EXPECT_FLOAT_EQ(l.b[0].x, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].y, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].z, 0.0f);
    EXPECT_FLOAT_EQ(l.b[0].w, 10.0f);
    EXPECT_FLOAT_EQ(l.c[0].x, 3.0f);
}

TEST(PlatingDamage, SummedWearTurnsDoubleSidedOn) {
    auto p = zero_params();
    p[16] = 4.5f;
    p[19] = 0.9f;  // threshold 4.5 - 0.675 = 3.825
    HullDamageStore two;
    two.add({0, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    two.add({500, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    EXPECT_TRUE(renderer::plating::build_damage_list(two, p.data()).torn_possible);
    HullDamageStore one;
    one.add({0, 0, 0}, {0, 0, 0}, 10.0f, 2.5f, HullDamageKind::Internal);
    EXPECT_FALSE(renderer::plating::build_damage_list(one, p.data()).torn_possible);
}

TEST(PlatingDamage, ZeroWearRecordsNeverEnterTheStore) {
    HullDamageStore s;
    s.add({0, 0, 0}, kUp, 50.0f, 0.0f, HullDamageKind::Surface);
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 0.0f, HullDamageKind::Internal);
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 0);
    EXPECT_FALSE(l.torn_possible);
}

TEST(PlatingDamage, SixtyFourRecordsAllReachTheList) {
    HullDamageStore s;
    for (int i = 0; i < 64; ++i)
        s.add({1000.0f * static_cast<float>(i), 0, 0}, kUp, 10.0f, 1.0f,
              HullDamageKind::Surface);
    ASSERT_EQ(s.count(), 64u);
    auto p = zero_params();
    p[7] = 1.0f;
    const auto l = renderer::plating::build_damage_list(s, p.data());
    EXPECT_EQ(l.count, 64);
}

// torn_possible's bound is the lowest breach the shader can return:
// breach * (1 - 0.4 * spread) - lumps, less the largest tear-noise lift.
TEST(PlatingDamage, TornPossibleUsesTheToughnessAndLumpFloor) {
    auto p = zero_params();
    p[7] = 0.4f;
    p[16] = 4.5f;
    p[19] = 0.9f;
    p[22] = 0.6f;
    p[23] = 1.0f;
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 30.0f, 2.0f, HullDamageKind::Internal);
    EXPECT_TRUE(renderer::plating::build_damage_list(s, p.data()).torn_possible);
    p[22] = 0.0f;
    p[23] = 0.0f;
    EXPECT_FALSE(renderer::plating::build_damage_list(s, p.data()).torn_possible);
}

// ---- Phase 2 Task 3: records near each mesh, the deck-break subset. -------

// A record enters a mesh's subset when its sphere grown by the margin
// (a.w + margin) touches the mesh's body-frame box.
TEST(PlatingDamage, RecordsNearSelectsOnlyTouchingSpheres) {
    HullDamageStore s;
    s.add({5, 0, 0}, {0, 0, 0}, 3.0f, 1.0f, HullDamageKind::Internal);    // 5 - 1 <= 3 + 1
    s.add({10, 0, 0}, {0, 0, 0}, 3.0f, 1.0f, HullDamageKind::Internal);   // 10 - 1 > 3 + 1
    auto p = zero_params();
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 2);
    renderer::Aabb box;
    box.center = glm::vec3(0.0f);
    box.half_extents = glm::vec3(1.0f);
    std::array<std::uint8_t, renderer::plating::kMaxDamage> idx{};
    const int n = renderer::plating::records_near(l, box, 1.0f, idx);
    ASSERT_EQ(n, 1);
    EXPECT_EQ(idx[0], 0);
}

// Kept: record i when the summed wear of every record whose sphere overlaps
// i's (i included) reaches deck break less the largest tear-noise lift,
// params[24] - 1.25 * params[19]. Here 6 - 1.125 = 4.875.
TEST(PlatingDamage, DeckBreakSubsetDropsIsolatedLightRecords) {
    auto p = zero_params();
    p[24] = 6.0f;
    p[19] = 0.9f;
    HullDamageStore s;
    s.add({0, 0, 0}, {0, 0, 0}, 5.0f, 10.0f, HullDamageKind::Internal);
    s.add({100, 0, 0}, {0, 0, 0}, 5.0f, 1.0f, HullDamageKind::Internal);
    const auto l = renderer::plating::build_damage_list(s, p.data());
    ASSERT_EQ(l.count, 2);
    const auto db = renderer::plating::deck_break_subset(l, p.data());
    ASSERT_EQ(db.count, 1);
    EXPECT_EQ(db.idx[0], 0);

    HullDamageStore pair;
    pair.add({0, 0, 0}, {0, 0, 0}, 5.0f, 3.0f, HullDamageKind::Internal);
    pair.add({6, 0, 0}, {0, 0, 0}, 5.0f, 3.0f, HullDamageKind::Internal);
    const auto lp = renderer::plating::build_damage_list(pair, p.data());
    const auto dp = renderer::plating::deck_break_subset(lp, p.data());
    ASSERT_EQ(dp.count, 2);
    EXPECT_EQ(dp.idx[0], 0);
    EXPECT_EQ(dp.idx[1], 1);
}

// ── Molten rims (layered damage phase 4 §2.3) ──────────────────────────────
// The kMaxRims freshest events with 0 <= age < kRimLife, freshest first, in
// the rest frame of their node, with age and life.
TEST(PlatingDamage, RimListKeepsTheFourFreshestHotEvents) {
    scenegraph::BreachEventRing ring;
    const float now = 100.0f;
    // Ages 0.5, 2.9, 3.0 (cold), 0.1, 1.0, 2.0, -1 (not born yet), 10 (cold).
    const float ages[] = {0.5f, 2.9f, scenegraph::kRimLife, 0.1f, 1.0f, 2.0f, -1.0f, 10.0f};
    for (int i = 0; i < 8; ++i)
        ring.push({float(i), 0, 0}, 1.0f + i, kUp, now - ages[i], 1u + i, i - 1,
                  glm::vec3(float(i), 50.0f, 0.0f));
    const auto r = renderer::plating::build_rim_list(ring, now);
    ASSERT_EQ(r.count, renderer::plating::kMaxRims);
    const int want[] = {3, 0, 4, 5};   // ages 0.1, 0.5, 1.0, 2.0
    for (int k = 0; k < r.count; ++k) {
        const int i = want[k];
        EXPECT_EQ(r.a[k], glm::vec4(float(i), 50.0f, 0.0f, 1.0f + i)) << k << ": rest centre";
        EXPECT_NEAR(r.b[k].x, ages[i], 1e-4f) << k;
        EXPECT_EQ(r.b[k].y, scenegraph::kRimLife) << k;
        EXPECT_EQ(r.node[k], i - 1) << k;
    }
    scenegraph::BreachEventRing cold;
    cold.push({0, 0, 0}, 1.0f, kUp, now - scenegraph::kRimLife - 1.0f, 1u);
    EXPECT_EQ(renderer::plating::build_rim_list(cold, now).count, 0);
}

TEST(PlatingDamage, RimsInFrameKeepOnlyTheMeshOwnersRims) {
    scenegraph::BreachEventRing ring;
    ring.push({0, 0, 0}, 1.0f, kUp, 10.0f, 1u, -1);
    ring.push({1, 0, 0}, 1.0f, kUp, 10.0f, 2u, 2);   // node 2, posed owner 1
    const auto all = renderer::plating::build_rim_list(ring, 10.0f);
    ASSERT_EQ(all.count, 2);
    const std::vector<int> owners{-1, 1, 1};
    const auto body = renderer::plating::rims_in_frame(all, owners, -1);
    ASSERT_EQ(body.count, 1);
    EXPECT_EQ(body.node[0], -1);
    const auto part = renderer::plating::rims_in_frame(all, owners, 1);
    ASSERT_EQ(part.count, 1);
    EXPECT_EQ(part.node[0], 2);
    EXPECT_EQ(renderer::plating::rims_in_frame(all, {}, -1).count, 2) << "nothing posed";
}
