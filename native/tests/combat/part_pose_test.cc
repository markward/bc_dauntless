// The posed-parts arithmetic (part_pose.h) and the posed mount / target
// offset geometry (weapon_geometry.h) on hand-built mirror rows. The
// native-vs-Python differential runs from
// tests/unit/test_native_part_pose_geometry.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <limits>

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

// An ownerless subsystem (no ship to climb to) read against an explicit posed
// ship is no current slot of that ship: part_stale, not a pass.
TEST(PartPose, OwnerlessSubsystemWithShipArgReadsStale) {
    World w;
    const int64_t a = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.m.register_row(Kind::Subsystem);
    w.m.set_fv(bank, Field::_position, {1.0, 2.0, 3.0});
    w.pose(a, {translate(1.0, 0.0, 0.0)});
    w.slot(bank, 0);
    const std::string why = throw_message(
        [&] { subsystem_world_position(w.m, bank, a, false); });
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
    // No mount on a posed target: a plain body point (fire control native
    // only, M5) -- the box rule is out of aiming.
    EXPECT_EQ(target_offset_world(w.m, target, off, kNoMount)[0], 1.0);
    // A mount the mirror cannot name.
    EXPECT_THROW(target_offset_world(w.m, target, off, kRefUnrepresentable),
                 std::invalid_argument);
    // An offset that is not the mount's own point (within 1e-5 or not):
    // a plain body point too (M8.5), no slot read.
    EXPECT_EQ(target_offset_world(w.m, target, {1.0, 2.0, 3.5}, mount)[0],
              1.0);
    EXPECT_EQ(target_offset_world(w.m, target, {1.0 + 1e-6, 2.0, 3.0},
                                  mount)[0], 1.0 + 1e-6);
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

// ── authored_mount_subsystem (K1 _RESOLVE's mount, MAP §3.4 / R3) ───────────
//
// part_severance.authored_mount_subsystem: the FIRST subsystem in
// combat._iter_subsystems order (the pushed mount_order) with
// abs(mount[i] - point[i]) <= 1e-5 on every axis; else None (kNoMount).
// kMountUnknown when the mirror cannot tell.

namespace {

// A ShipClass row with the given subsystems pushed as its mount order.
struct MountWorld : World {
    int64_t target = ship(0.0, 0.0, 0.0);
    MountWorld() { m.set_i(target, Field::is_ship_class, 1); }
    void order(const std::vector<int64_t>& subs) {
        m.set_mount_order(target, subs);
    }
    int64_t ask(const Vec3& offset) const {
        return authored_mount_subsystem(m, *m.object(target), offset);
    }
};

}  // namespace

TEST(PartPose, AuthoredMountIsTheFirstInOrder) {
    MountWorld w;
    const int64_t parent = w.bank(w.target, 1.0, 2.0, 3.0);
    const int64_t child = w.bank(w.target, 1.0, 2.0, 3.0);
    const int64_t other = w.bank(w.target, 4.0, 5.0, 6.0);
    w.order({parent, child, other});
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), parent);
    EXPECT_EQ(w.ask({4.0, 5.0, 6.0}), other);
    EXPECT_EQ(w.ask({7.0, 8.0, 9.0}), kNoMount);
    w.order({child, parent, other});
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), child);
    // Read live: a moved _position moves the answer.
    w.m.set_fv(child, Field::_position, {9.0, 9.0, 9.0});
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), parent);
    EXPECT_EQ(w.ask({9.0, 9.0, 9.0}), child);
    // A ship with no mounted subsystem: None.
    w.order({});
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), kNoMount);
}

TEST(PartPose, AuthoredMountToleranceIsPerAxisAndInclusive) {
    MountWorld w;
    const int64_t at_zero = w.bank(w.target, 0.0, 0.0, 0.0);
    w.order({at_zero});
    // abs(0 - -1e-5) is exactly 1e-5: `<=` matches.
    EXPECT_EQ(w.ask({-1e-5, 0.0, 0.0}), at_zero);
    EXPECT_EQ(w.ask({0.0, 1e-5, 0.0}), at_zero);
    EXPECT_EQ(w.ask({0.0, 0.0, std::nextafter(1e-5, 1.0)}), kNoMount);
    // 0.9e-5 on every axis is 1.56e-5 away: per axis, not a distance.
    EXPECT_EQ(w.ask({0.9e-5, -0.9e-5, 0.9e-5}), at_zero);
    EXPECT_EQ(w.ask({1.1e-5, 0.0, 0.0}), kNoMount);
    EXPECT_EQ(w.ask({-0.0, -0.0, -0.0}), at_zero);
}

TEST(PartPose, AuthoredMountNaNNeverMatches) {
    MountWorld w;
    const double nan = std::nan("");
    const double inf = INFINITY;
    const int64_t a = w.bank(w.target, 1.0, 2.0, 3.0);
    const int64_t odd = w.bank(w.target, nan, 0.0, inf);
    w.order({odd, a});
    EXPECT_EQ(w.ask({nan, 2.0, 3.0}), kNoMount);
    EXPECT_EQ(w.ask({1.0, 2.0, nan}), kNoMount);
    EXPECT_EQ(w.ask({nan, 0.0, inf}), kNoMount);   // inf - inf is NaN
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), a);
}

TEST(PartPose, AuthoredMountUnknownWhenTheMirrorCannotTell) {
    MountWorld w;
    const int64_t a = w.bank(w.target, 1.0, 2.0, 3.0);
    const int64_t b = w.bank(w.target, 4.0, 5.0, 6.0);
    // An unnamed subsystem reached before a match might have matched.
    w.order({a, kRefUnrepresentable, b});
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), a);
    EXPECT_EQ(w.ask({4.0, 5.0, 6.0}), kMountUnknown);
    EXPECT_EQ(w.ask({7.0, 8.0, 9.0}), kMountUnknown);
    // A since-freed entry: the same.
    const int64_t gone = w.bank(w.target, 7.0, 8.0, 9.0);
    w.order({a, gone, b});
    w.m.unregister_row(gone);
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), a);
    EXPECT_EQ(w.ask({4.0, 5.0, 6.0}), kMountUnknown);
    // Not a ShipClass: its mount order is never pushed, so empty says
    // nothing.
    w.order({});
    w.m.set_i(w.target, Field::is_ship_class, 0);
    EXPECT_EQ(w.ask({1.0, 2.0, 3.0}), kMountUnknown);
    EXPECT_NE(kMountUnknown, kNoMount);
}

// No mount on a posed target is a plain body point (fire control native
// only, M5): the box rule is out of aiming, so no slot is read and the
// offset is used as is -- signed zeros and NaN through.
TEST(PartPose, NoMountOnPosedTargetIsPlainPoint) {
    const double kNan = std::numeric_limits<double>::quiet_NaN();
    World w;
    const int64_t target = w.ship(-0.0, -0.0, -0.0);
    w.pose(target, {translate(1.0, 0.0, 0.0)});
    EXPECT_TRUE(all_negative_zero(
        target_offset_world(w.m, target, {-0.0, -0.0, -0.0}, kNoMount)));
    EXPECT_EQ(target_offset_world(w.m, target, {1.0, 2.0, 3.0}, kNoMount)[0],
              1.0);
    EXPECT_TRUE(std::isnan(
        target_offset_world(w.m, target, {kNan, 2.0, 3.0}, kNoMount)[0]));
    // A stale part generation is never read for it.
    w.m.set_part_gen(w.m.part_gen() + 1);
    EXPECT_EQ(target_offset_world(w.m, target, {1.0, 2.0, 3.0}, kNoMount)[0],
              1.0);
}
