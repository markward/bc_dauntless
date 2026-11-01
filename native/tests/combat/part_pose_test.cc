// The posed-parts arithmetic (part_pose.h) and the posed mount / target
// offset geometry (weapon_geometry.h) on hand-built mirror rows. The
// native-vs-Python differential runs from
// tests/unit/test_native_part_pose_geometry.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/weapon_geometry.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t next_id = 1;

    int64_t ship(double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        return m.register_row(Kind::Object, i, g, next_id++);
    }
    void rotate(int64_t ship_h, const std::array<double, 9>& r) {
        const ObjectRow* o = m.object(ship_h);
        store.set_rotation(static_cast<uint32_t>(o->xform_index),
                           static_cast<uint32_t>(o->xform_gen), r);
    }
    int64_t bank(int64_t ship_h, double px, double py, double pz) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_fv(s, Field::_position, {px, py, pz});
        return s;
    }
    // A posed ship: flag 1 and the given table.
    void pose(int64_t ship_h, std::vector<PartPose> table) {
        m.set_i(ship_h, Field::has_posed_parts, 1);
        m.set_part_poses(ship_h, std::move(table));
    }
    // A slot resolved at the current generation.
    void slot(int64_t sub_h, int32_t slot) {
        m.set_part_slot(sub_h, slot, m.part_gen());
    }
};

PartPose translate(double x, double y, double z) {
    PartPose p;
    p.t[0] = x;
    p.t[1] = y;
    p.t[2] = z;
    p.identity = false;
    return p;
}

// Rotation about +Z by 90 degrees, row-major: (x, y, z) -> (-y, x, z).
constexpr std::array<double, 9> kRotZ90{0, -1, 0, 1, 0, 0, 0, 0, 1};

bool all_negative_zero(const Vec3& v) {
    return v[0] == 0.0 && v[1] == 0.0 && v[2] == 0.0 && std::signbit(v[0]) &&
           std::signbit(v[1]) && std::signbit(v[2]);
}

template <typename F>
std::string throw_message(F&& f) {
    try {
        f();
    } catch (const std::invalid_argument& e) {
        return e.what();
    }
    return "";
}

}  // namespace

// ── apply_part_pose (P1/P2) ─────────────────────────────────────────────────

TEST(PartPose, ApplyIsRotateThenTranslate) {
    PartPose p = translate(10.0, 20.0, 30.0);
    const double r[9] = {0, -1, 0, 1, 0, 0, 0, 0, 1};
    for (int i = 0; i < 9; ++i) p.r[i] = r[i];
    const Vec3 got = apply_part_pose(p, {1.0, 2.0, 3.0});
    EXPECT_EQ(got[0], 8.0);    // -2 + 10
    EXPECT_EQ(got[1], 21.0);   //  1 + 20
    EXPECT_EQ(got[2], 33.0);   //  3 + 30
}

TEST(PartPose, IdentityBranchKeepsSignedZero) {
    PartPose p;   // identity bit set
    const Vec3 nz{-0.0, -0.0, -0.0};
    EXPECT_TRUE(all_negative_zero(apply_part_pose(p, nz)));
    // Within is_identity's 1e-9 but not exactly identity: the point itself,
    // not the point moved by 5e-10.
    p.t[0] = 5e-10;
    p.r[4] = 1.0 + 5e-10;
    const Vec3 got = apply_part_pose(p, {1.0, 2.0, 3.0});
    EXPECT_EQ(got[0], 1.0);
    EXPECT_EQ(got[1], 2.0);
    EXPECT_EQ(got[2], 3.0);

    // Through the mount: ship at -0, unrotated, part at identity.
    World w;
    const int64_t ship = w.ship(-0.0, -0.0, -0.0);
    const int64_t bank = w.bank(ship, -0.0, -0.0, -0.0);
    w.pose(ship, {PartPose{}, translate(1.0, 0.0, 0.0)});
    w.slot(bank, 0);
    EXPECT_TRUE(all_negative_zero(subsystem_world_position(w.m, bank, -1,
                                                           false)));
}

TEST(PartPose, DetachedReadsRest) {
    PartPose p = translate(10.0, 0.0, 0.0);
    p.detached = true;
    const Vec3 got = apply_part_pose(p, {1.0, 2.0, 3.0});
    EXPECT_EQ(got[0], 1.0);

    World w;
    const int64_t ship = w.ship(100.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    w.pose(ship, {p});
    w.slot(bank, 0);
    const Vec3 mount = subsystem_world_position(w.m, bank, -1, false);
    EXPECT_EQ(mount[0], 101.0);
    EXPECT_EQ(mount[1], 2.0);
    EXPECT_EQ(mount[2], 3.0);
}

// ── The slot ────────────────────────────────────────────────────────────────

TEST(PartPose, SlotStates) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    const ObjectRow& o = *w.m.object(ship);
    const SubsystemRow& s = *w.m.subsystem(bank);
    Vec3 out{7.0, 7.0, 7.0};

    // Unposed: no slot is read, whatever it holds.
    w.m.set_part_slot(bank, 5, w.m.part_gen());
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::none);
    EXPECT_EQ(out[0], 1.0);

    // Posed, the table empty while the slot keeps an old index: stale.
    w.m.set_i(ship, Field::has_posed_parts, 1);
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::stale);

    w.pose(ship, {translate(1.0, 0.0, 0.0)});
    // Never resolved (-1, 0) reads stale, not "no part".
    w.m.set_part_slot(bank, -1, 0);
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::stale);
    // Resolved to no part: the point itself.
    w.slot(bank, -1);
    out = {7.0, 7.0, 7.0};
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::none);
    EXPECT_EQ(out[0], 1.0);
    // Past the table: stale.
    w.slot(bank, 1);
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::stale);
    // In the table: the pose.
    w.slot(bank, 0);
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::ok);
    EXPECT_EQ(out[0], 2.0);
    // The generation moves on: stale.
    w.m.set_part_gen(w.m.part_gen() + 1);
    EXPECT_EQ(posed_local(w.m, o, s, &out), SlotState::stale);
}

TEST(PartPose, StaleSlotFallsBackPartStale) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    w.pose(ship, {translate(1.0, 0.0, 0.0)});
    w.m.set_part_slot(bank, 0, w.m.part_gen() - 1);
    const std::string why = throw_message(
        [&] { subsystem_world_position(w.m, bank, -1, true); });
    EXPECT_NE(why.find("part_stale"), std::string::npos) << why;
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
}

TEST(PartPose, UnposedShipIgnoresTheSlot) {
    World w;
    const int64_t ship = w.ship(10.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    w.m.set_part_slot(bank, 3, 0);     // garbage: never read
    const Vec3 p = subsystem_world_position(w.m, bank, -1, false);
    EXPECT_EQ(p[0], 11.0);
}

// A slot is resolved against its OWN ship's table: asked on another posed
// ship it cannot answer.
TEST(PartPose, ForeignShipSlotReadsStale) {
    World w;
    const int64_t a = w.ship(0.0, 0.0, 0.0);
    const int64_t b = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(a, 1.0, 2.0, 3.0);
    w.pose(a, {translate(1.0, 0.0, 0.0)});
    w.pose(b, {translate(5.0, 0.0, 0.0)});
    w.slot(bank, 0);
    EXPECT_EQ(subsystem_world_position(w.m, bank, a, false)[0], 2.0);
    const std::string why = throw_message(
        [&] { subsystem_world_position(w.m, bank, b, false); });
    EXPECT_NE(why.find("part_stale"), std::string::npos) << why;
}

// Unposed, another ship's subsystem is answered as before: no slot is read
// and no owner is checked.
TEST(PartPose, UnposedForeignShipArgAnswers) {
    World w;
    const int64_t a = w.ship(0.0, 0.0, 0.0);
    const int64_t b = w.ship(10.0, 0.0, 0.0);
    const int64_t bank = w.bank(a, 1.0, 2.0, 3.0);
    w.pose(a, {translate(1.0, 0.0, 0.0)});
    w.slot(bank, 0);
    EXPECT_EQ(subsystem_world_position(w.m, bank, b, false)[0], 11.0);
    const int64_t target = w.ship(0.0, 0.0, 0.0);
    EXPECT_EQ(target_offset_world(w.m, target, {1.0, 2.0, 3.0}, bank)[0], 1.0);
}

// ── P3 / P4 ordering ────────────────────────────────────────────────────────

TEST(PartPose, PoseBeforeRotation) {
    World w;
    const int64_t ship = w.ship(100.0, 200.0, 300.0);
    w.rotate(ship, kRotZ90);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    w.pose(ship, {translate(10.0, 0.0, 0.0)});
    w.slot(bank, 0);
    // R . (p + t) = R . (11, 2, 3) = (-2, 11, 3); after R would be (8, 1, 3).
    const Vec3 got = subsystem_world_position(w.m, bank, -1, false);
    EXPECT_EQ(got[0], 98.0);
    EXPECT_EQ(got[1], 211.0);
    EXPECT_EQ(got[2], 303.0);
}

TEST(PartPose, PoseBeforeScale) {
    World w;
    const int64_t target = w.ship(100.0, 0.0, 0.0);
    w.rotate(target, kRotZ90);
    w.m.set_f(target, Field::_scale, 2.0);
    const int64_t mount = w.bank(target, 1.0, 2.0, 3.0);
    w.pose(target, {translate(1.0, 0.0, 0.0)});
    w.slot(mount, 0);
    // R . ((p + t) * s) = R . (4, 4, 6) = (-4, 4, 6); scale first: (3, 4, 6).
    const Vec3 got = target_offset_world(w.m, target, {1.0, 2.0, 3.0}, mount);
    EXPECT_EQ(got[0], 96.0);
    EXPECT_EQ(got[1], 4.0);
    EXPECT_EQ(got[2], 6.0);
}

TEST(PartPose, TargetOffsetMountRules) {
    World w;
    const int64_t target = w.ship(0.0, 0.0, 0.0);
    const int64_t other = w.ship(0.0, 0.0, 0.0);
    const int64_t mount = w.bank(target, 1.0, 2.0, 3.0);
    const int64_t foreign = w.bank(other, 1.0, 2.0, 3.0);
    const Vec3 off{1.0, 2.0, 3.0};

    // Unposed: the offset as is, mount or not.
    EXPECT_EQ(target_offset_world(w.m, target, off, kNoMount)[0], 1.0);
    EXPECT_EQ(target_offset_world(w.m, target, off, mount)[0], 1.0);

    w.pose(target, {translate(1.0, 0.0, 0.0)});
    w.pose(other, {translate(1.0, 0.0, 0.0)});
    w.slot(mount, 0);
    w.slot(foreign, 0);
    EXPECT_EQ(target_offset_world(w.m, target, off, mount)[0], 2.0);
    // No mount on a posed target: Python's box rule -- not ours.
    EXPECT_THROW(target_offset_world(w.m, target, off, kNoMount),
                 std::invalid_argument);
    // A mount the mirror cannot name.
    EXPECT_THROW(target_offset_world(w.m, target, off, kRefUnrepresentable),
                 std::invalid_argument);
    // An offset that is not the mount's own point: Python resolves the part
    // from the offset, the slot from the mount.
    EXPECT_THROW(target_offset_world(w.m, target, {1.0, 2.0, 3.5}, mount),
                 std::invalid_argument);
    // Another ship's subsystem.
    std::string why = throw_message(
        [&] { target_offset_world(w.m, target, off, foreign); });
    EXPECT_NE(why.find("part_stale"), std::string::npos) << why;
    // A stale slot.
    w.m.set_part_gen(w.m.part_gen() + 1);
    why = throw_message([&] { target_offset_world(w.m, target, off, mount); });
    EXPECT_NE(why.find("part_stale"), std::string::npos) << why;
}

// The pose applies to the OFFSET, not to the mount's `_position`: -0.0 and
// 0.0 match by `==`, and Python returns its own `point`.
TEST(PartPose, TargetOffsetIdentityReturnsTheOffsetItself) {
    World w;
    const int64_t target = w.ship(-0.0, -0.0, -0.0);
    const int64_t mount = w.bank(target, 0.0, 0.0, 0.0);
    w.pose(target, {PartPose{}, translate(1.0, 0.0, 0.0)});
    w.slot(mount, 0);
    EXPECT_TRUE(all_negative_zero(
        target_offset_world(w.m, target, {-0.0, -0.0, -0.0}, mount)));
}
