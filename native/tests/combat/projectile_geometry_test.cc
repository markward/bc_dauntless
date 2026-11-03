// The native projectile geometry (projectile_geometry.h) on hand-built mirror
// rows: exact answers for the map's edges (k3-k4-map.md A3). The
// native-vs-Python differential runs from
// tests/unit/test_native_projectile_geometry.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/projectile_geometry.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/step_scan.h"
#include "dauntless/combat/torpedo_table.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();
using St = GuideResult::Status;

struct World {
    TransformStore store;
    Mirror m{store};
    StepScan scan;
    int64_t next_id = 1;

    World() {
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
        m.set_global_f(Global::LEAD_ACCEL_K, 0.5);
    }
    int64_t set() { return m.register_row(Kind::Set); }
    int64_t ship(int64_t in_set, double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_ref(h, Field::_containing_set, in_set);
        m.set_f(h, Field::o_radius, 2.0);
        return h;
    }
    // A torpedo row at (x, y, z) flying `v`, homing on `target` from no
    // source (so _target_visible is True without a can_detect).
    int64_t torp(int64_t in_set, int64_t target, const Vec3& pos,
                 const Vec3& v) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, pos[0], pos[1], pos[2]);
        auto& t = m.torpedoes();
        const int64_t h = t.add(i, g);
        t.set_f(h, TorpField::_age, 0.0);
        t.set_f(h, TorpField::_ttl, 60.0);
        t.set_f(h, TorpField::_guidance_lifetime, 4.0);
        t.set_f(h, TorpField::_guidance_initial, 4.0);
        t.set_f(h, TorpField::_max_angular_accel, 0.125);
        t.set_v(h, TorpField::_velocity, true, v);
        m.set_torpedo_ref(h, TorpField::_containing_set, in_set);
        m.set_torpedo_ref(h, TorpField::_target_ship, target);
        m.set_torpedo_ref(h, TorpField::_source_ship, -1);
        return h;
    }
    const TorpedoRow& row(int64_t h) { return *m.torpedoes().find(h); }
    GuideResult guide(int64_t h, double dt = 1.0 / 60.0) {
        return guide_torpedo(m, row(h), dt, scan, false, {});
    }
    void frames(int64_t s) { scan.frames.push_back({s, 0, {0.0, 0.0, 0.0}}); }
};

}  // namespace

// A8: NaN anywhere is no hit; the boundary is inclusive.
TEST(ProjectileGeometry, SphereHitNanAndBoundary) {
    EXPECT_TRUE(sphere_hit({3.0, 4.0, 0.0}, {0.0, 0.0, 0.0}, 5.0));
    EXPECT_FALSE(sphere_hit({3.0, 4.0, 0.0}, {0.0, 0.0, 0.0}, 4.999));
    EXPECT_FALSE(sphere_hit({kNan, 0.0, 0.0}, {0.0, 0.0, 0.0}, 5.0));
    EXPECT_FALSE(sphere_hit({0.0, 0.0, 0.0}, {0.0, 0.0, 0.0}, kNan));
    // r * r: a negative radius still squares positive.
    EXPECT_TRUE(sphere_hit({3.0, 4.0, 0.0}, {0.0, 0.0, 0.0}, -5.0));
}

// A3: the segment is cur - prev, not v * dt (they round differently).
TEST(ProjectileGeometry, AdvanceSegmentIsCurMinusPrev) {
    const Advance a =
        advance_torpedo({1e16, 0.0, 0.0}, {3.0, 0.0, 0.0}, 1.0, 0.0, 60.0);
    EXPECT_FALSE(a.expired);
    EXPECT_EQ(a.cur[0], 1e16 + 3.0);
    EXPECT_EQ(a.seg[0], (1e16 + 3.0) - 1e16);  // 4.0, not 3.0
    EXPECT_NE(a.seg[0], 3.0);
    EXPECT_EQ(a.seg_len, std::sqrt(a.seg[0] * a.seg[0]));
    ASSERT_TRUE(a.aim_unit.has_value());
    EXPECT_EQ((*a.aim_unit)[0], 1.0);
}

// A6: age >= ttl expires (the boundary included); a NaN age never does.
// A5: seg_len <= 1e-9 has no aim.
TEST(ProjectileGeometry, AdvanceTtlAndAim) {
    EXPECT_TRUE(advance_torpedo({0, 0, 0}, {1, 0, 0}, 0.5, 59.5, 60.0).expired);
    EXPECT_FALSE(
        advance_torpedo({0, 0, 0}, {1, 0, 0}, 0.25, 59.5, 60.0).expired);
    EXPECT_FALSE(advance_torpedo({0, 0, 0}, {1, 0, 0}, 0.5, kNan, 0.0).expired);
    const Advance still =
        advance_torpedo({1, 2, 3}, {0, 0, 0}, 1.0 / 60.0, 0.0, 60.0);
    EXPECT_FALSE(still.expired);
    EXPECT_EQ(still.seg_len, 0.0);
    EXPECT_FALSE(still.aim_unit.has_value());
    const Advance nan =
        advance_torpedo({1, 2, 3}, {kNan, 0, 0}, 1.0 / 60.0, 0.0, 60.0);
    EXPECT_TRUE(std::isnan(nan.seg_len));
    EXPECT_FALSE(nan.aim_unit.has_value());
}

// B1: without a box, radius * (1 + S); with one, max(radius, |c| + max
// semi-axis * S), |c| through py_pow.
TEST(ProjectileGeometry, BubbleBound) {
    World w;
    const int64_t s = w.set();
    const int64_t ship = w.ship(s, 0, 0, 0);
    const double k = std::sqrt(3.0);
    EXPECT_EQ(bubble_bound_radius(w.m, ship), 2.0 * (1.0 + k));
    w.m.set_fv(ship, Field::_shield_hull_box_center, {1.0, 2.0, 2.0});
    w.m.set_fv(ship, Field::_shield_hull_box_half, {3.0, 1.0, 5.0});
    w.m.set_i(ship, Field::hull_box_set, 1);
    EXPECT_EQ(bubble_bound_radius(w.m, ship), py_pow(9.0, 0.5) + 5.0 * k);
    // A degenerate raw extent: no box.
    w.m.set_fv(ship, Field::_shield_hull_box_half, {3.0, 0.0, 5.0});
    EXPECT_EQ(bubble_bound_radius(w.m, ship), 2.0 * (1.0 + k));
    // A NaN radius with no box stays NaN.
    w.m.set_f(ship, Field::o_radius, kNan);
    EXPECT_TRUE(std::isnan(bubble_bound_radius(w.m, ship)));
    // A stale row: Python's caller never got here (the row dropped).
    w.m.unregister_row(ship);
    EXPECT_THROW(bubble_bound_radius(w.m, ship), std::invalid_argument);
}

// B1 on a row that is not a ShipClass: world_radius's DebrisChunk rule is
// not mirrored, so the bound is Python's.
TEST(ProjectileGeometry, BubbleBoundRefusesNonShip) {
    World w;
    const int64_t ship = w.ship(w.set(), 0, 0, 0);
    w.m.set_i(ship, Field::is_ship_class, 0);
    EXPECT_THROW(bubble_bound_radius(w.m, ship), std::invalid_argument);
}

// G12: no offset, shifted only by a non-zero offset (-0.0 counts as zero).
TEST(ProjectileGeometry, SteerPointNoOffsetShift) {
    World w;
    const int64_t s = w.set();
    const int64_t t = w.ship(s, 1.0, 2.0, 3.0);
    EXPECT_EQ(steer_point_native(w.m, t, std::nullopt, -1, {-0.0, 0.0, -0.0}),
              (Vec3{1.0, 2.0, 3.0}));
    EXPECT_EQ(steer_point_native(w.m, t, std::nullopt, -1, {10.0, 0.0, 0.0}),
              (Vec3{11.0, 2.0, 3.0}));
    // An offset on a posed target that no mount claims is a plain body
    // point (fire control native only, M5); a mount the mirror cannot name
    // is Python's.
    w.m.set_i(t, Field::has_posed_parts, 1);
    EXPECT_EQ(steer_point_native(w.m, t, Vec3{0.0, 1.0, 0.0}, -1,
                                 {0.0, 0.0, 0.0}),
              (Vec3{1.0, 3.0, 3.0}));
    EXPECT_EQ(steer_point_native(w.m, t, std::nullopt, -1, {0.0, 0.0, 0.0}),
              (Vec3{1.0, 2.0, 3.0}));
    w.m.set_i(t, Field::has_posed_parts, 0);
    EXPECT_THROW(steer_point_native(w.m, t, Vec3{0.0, 1.0, 0.0},
                                     kRefUnrepresentable, {0.0, 0.0, 0.0}),
                 std::invalid_argument);
}

// A picked spot on a posed target (fire control native only, M5): pos +
// R·(scale·offset), no part pose -- an identity is a branch, so signed
// zeros survive (an identity pose multiplied would turn -0.0 into 0.0).
TEST(ProjectileGeometry, SteerPointPickedSpotIsPlainPoint) {
    World w;
    const int64_t s = w.set();
    const int64_t t = w.ship(s, -0.0, -0.0, -0.0);
    w.m.set_i(t, Field::has_posed_parts, 1);
    const Vec3 p = steer_point_native(w.m, t, Vec3{-0.0, -0.0, -0.0}, -1,
                                      {0.0, 0.0, 0.0});
    for (int i = 0; i < 3; ++i) EXPECT_TRUE(std::signbit(p[i])) << i;
    EXPECT_EQ(steer_point_native(w.m, t, Vec3{0.5, -2.0, 3.0}, -1,
                                 {10.0, 0.0, 0.0}),
              (Vec3{10.5, -2.0, 3.0}));
    // A mount the mirror cannot name is still Python's.
    EXPECT_THROW(steer_point_native(w.m, t, Vec3{0.0, 1.0, 0.0},
                                    kRefUnrepresentable, {0.0, 0.0, 0.0}),
                 std::invalid_argument);
}

// No target: nothing at all. A set with no frame entry: ask for it first.
TEST(ProjectileGeometry, GuideNoTargetAndMissingFrame) {
    World w;
    const int64_t a = w.set(), b = w.set();
    const int64_t tgt = w.ship(b, 0.0, 100.0, 0.0);
    const int64_t none = w.torp(a, -1, {0, 0, 0}, {0, 10, 0});
    GuideResult r = w.guide(none);
    EXPECT_EQ(r.status, St::done);
    EXPECT_EQ(r.n_writes, 0);
    const int64_t h = w.torp(a, tgt, {0, 0, 0}, {0, 10, 0});
    r = w.guide(h);
    ASSERT_EQ(r.status, St::need_frame);
    EXPECT_EQ(r.frame_set, a);
    w.frames(a);
    r = w.guide(h);
    ASSERT_EQ(r.status, St::need_frame);
    EXPECT_EQ(r.frame_set, b);
    // Same key, same anchors: offset zero, guided.
    w.frames(b);
    r = w.guide(h);
    ASSERT_EQ(r.status, St::done);
    EXPECT_EQ(r.n_writes, 3);
}

// _target_visible's compare (projectiles.py:1052): a source or target set
// with no frame entry is NOT a frame ASK -- Python's offset_between raise
// there is swallowed into True -- but the whole _guide, handed to Python.
TEST(ProjectileGeometry, GuideSourceFrameMissingIsWholeGuide) {
    World w;
    const int64_t a = w.set(), c = w.set();
    w.frames(a);
    const int64_t tgt = w.ship(a, 0.0, 100.0, 0.0);
    const int64_t src = w.ship(c, 0.0, -5.0, 0.0);
    const int64_t h = w.torp(a, tgt, {0, 0, 0}, {0, 10, 0});
    w.m.set_torpedo_ref(h, TorpField::_source_ship, src);
    const GuideResult r = w.guide(h);
    ASSERT_EQ(r.status, St::need_guide);
    EXPECT_STREQ(r.why, "source or target frame");
    EXPECT_EQ(r.n_writes, 0);
}

// G5: the dist < 1e-6 return keeps the two writes made before it.
TEST(ProjectileGeometry, GuideDistReturnKeepsEarlierWrites) {
    World w;
    const int64_t s = w.set();
    const int64_t tgt = w.ship(s, 5.0, 6.0, 7.0);
    const int64_t h = w.torp(s, tgt, {5.0, 6.0, 7.0}, {0, 10, 0});
    const GuideResult r = w.guide(h);
    ASSERT_EQ(r.status, St::done);
    ASSERT_EQ(r.n_writes, 2);
    EXPECT_EQ(r.writes[0].field, GuideField::last_seen);
    EXPECT_EQ(r.writes[0].value, (Vec3{5.0, 6.0, 7.0}));
    EXPECT_EQ(r.writes[1].field, GuideField::last_tvel);
    EXPECT_EQ(r.writes[1].value, (Vec3{0.0, 0.0, 0.0}));
}

// G1: speed < 1e-6 returns before anything; a NaN speed continues.
TEST(ProjectileGeometry, GuideSpeedGate) {
    World w;
    const int64_t s = w.set();
    w.frames(s);
    const int64_t tgt = w.ship(s, 0.0, 100.0, 0.0);
    const int64_t slow = w.torp(s, tgt, {0, 0, 0}, {0, 1e-7, 0});
    EXPECT_EQ(w.guide(slow).n_writes, 0);
    const int64_t nan = w.torp(s, tgt, {0, 0, 0}, {kNan, 1, 0});
    const GuideResult r = w.guide(nan);
    ASSERT_EQ(r.status, St::done);
    ASSERT_EQ(r.n_writes, 3);
    EXPECT_TRUE(std::isnan(r.writes[2].value[0]));
}

// Dead target: ballistic; a target with no real IsDead (a stub records
// telemetry) or a stale one: Python's whole _guide.
TEST(ProjectileGeometry, GuideDeadAndUnvouchedTargets) {
    World w;
    const int64_t s = w.set();
    w.frames(s);
    const int64_t tgt = w.ship(s, 0.0, 100.0, 0.0);
    const int64_t h = w.torp(s, tgt, {0, 0, 0}, {0, 10, 0});
    w.m.set_i(tgt, Field::_dead, 1);
    EXPECT_EQ(w.guide(h).status, St::done);
    EXPECT_EQ(w.guide(h).n_writes, 0);
    w.m.set_i(tgt, Field::_dead, 0);
    w.m.set_i(tgt, Field::has_real_is_dead, 0);
    EXPECT_EQ(w.guide(h).status, St::need_guide);
    w.m.set_i(tgt, Field::has_real_is_dead, 1);
    // An unrepresentable row field the guide reads.
    w.m.torpedoes().set_unrepresentable(h, TorpField::_last_target_vel);
    EXPECT_EQ(w.guide(h).status, St::need_guide);
    w.m.torpedoes().set_v(h, TorpField::_last_target_vel, false, {});
    EXPECT_EQ(w.guide(h).status, St::done);
    // The target's row dropped: the torpedo's ref reads -2.
    w.m.unregister_row(tgt);
    EXPECT_EQ(w.guide(h).status, St::need_guide);
}

// An offset the mirror cannot attribute (a target that is not a ShipClass)
// asks for the steer point; resuming with Python's point finishes _guide
// exactly as the no-ASK path would have.
TEST(ProjectileGeometry, GuideSteerPointAskAndResume) {
    World w;
    const int64_t s = w.set();
    w.frames(s);
    const int64_t tgt = w.ship(s, 30.0, 100.0, 0.0);
    w.m.set_i(tgt, Field::is_ship_class, 0);
    const int64_t h = w.torp(s, tgt, {0, 0, 0}, {0, 10, 0});
    w.m.torpedoes().set_v(h, TorpField::_target_offset, true, {0.0, 1.0, 0.0});
    const GuideResult ask = w.guide(h);
    ASSERT_EQ(ask.status, St::need_steer_point);
    EXPECT_EQ(ask.n_writes, 0);
    EXPECT_EQ(ask.resume.target, tgt);
    // Attributed (no mount subsystem): answered natively.
    w.m.set_torpedo_mount(h, true, -1, {0.0, 1.0, 0.0});
    const GuideResult direct = w.guide(h);
    ASSERT_EQ(direct.status, St::done);
    const Vec3 p = steer_point_native(w.m, tgt, Vec3{0.0, 1.0, 0.0}, -1,
                                       {0.0, 0.0, 0.0});
    const GuideResult resumed =
        guide_torpedo_resume(w.m, w.row(h), 1.0 / 60.0, ask.resume, p);
    ASSERT_EQ(resumed.status, St::done);
    ASSERT_EQ(resumed.n_writes, direct.n_writes);
    for (int i = 0; i < direct.n_writes; ++i) {
        EXPECT_EQ(resumed.writes[i].field, direct.writes[i].field);
        EXPECT_EQ(resumed.writes[i].value, direct.writes[i].value);
    }
    // A mount the mirror cannot name: ask again.
    w.m.set_torpedo_mount(h, true, kRefUnrepresentable, {0.0, 1.0, 0.0});
    EXPECT_EQ(w.guide(h).status, St::need_steer_point);
    // A posed target's picked spot is a plain body point (no pose, no
    // bake): answered natively, the same point as unposed.
    w.m.set_torpedo_mount(h, true, -1, {0.0, 1.0, 0.0});
    w.m.set_i(tgt, Field::has_posed_parts, 1);
    const GuideResult posed = w.guide(h);
    ASSERT_EQ(posed.status, St::done);
    EXPECT_TRUE(posed.posed_steer);
    ASSERT_EQ(posed.n_writes, direct.n_writes);
    for (int i = 0; i < direct.n_writes; ++i)
        EXPECT_EQ(posed.writes[i].value, direct.writes[i].value);
    // A NaN offset never matches its key (Python's != is True).
    w.m.set_i(tgt, Field::has_posed_parts, 0);
    w.m.torpedoes().set_v(h, TorpField::_target_offset, true, {kNan, 1.0, 0.0});
    w.m.set_torpedo_mount(h, true, -1, {kNan, 1.0, 0.0});
    EXPECT_EQ(w.guide(h).status, St::need_steer_point);
}

// The mount attribution (round trips, Task 4): a ShipClass target's mount
// order answers it natively (the first entry within 1e-5 per axis) and the
// result says so; a target that is not a ShipClass (no mount order is ever
// pushed for it) is Python's: ASK, unattributed.
TEST(ProjectileGeometry, GuideAttributesTheMountNatively) {
    World w;
    const int64_t s = w.set();
    w.frames(s);
    const int64_t tgt = w.ship(s, 30.0, 100.0, 0.0);
    const int64_t a = w.m.register_row(Kind::Subsystem);
    w.m.set_fv(a, Field::_position, {0.0, 1.0 - 0.5e-5, 0.0});
    const int64_t b = w.m.register_row(Kind::Subsystem);
    w.m.set_fv(b, Field::_position, {0.0, 1.0, 0.0});
    w.m.set_mount_order(tgt, {a, b});
    const int64_t h = w.torp(s, tgt, {0, 0, 0}, {0, 10, 0});
    w.m.torpedoes().set_v(h, TorpField::_target_offset, true, {0.0, 1.0, 0.0});
    const GuideResult g = w.guide(h);
    ASSERT_EQ(g.status, St::done);
    EXPECT_TRUE(g.attributed);
    EXPECT_EQ(g.mount, a);
    // Already attributed: nothing to attribute.
    w.m.set_torpedo_mount(h, true, a, {0.0, 1.0, 0.0});
    EXPECT_FALSE(w.guide(h).attributed);
    // Not a ShipClass: Python's.
    w.m.set_torpedo_mount(h, false, -1, {0.0, 0.0, 0.0});
    w.m.set_i(tgt, Field::is_ship_class, 0);
    const GuideResult ask = w.guide(h);
    ASSERT_EQ(ask.status, St::need_steer_point);
    EXPECT_EQ(ask.steer_why, SteerWhy::unattributed);
    EXPECT_FALSE(ask.attributed);
}

// G7-G9: a snap within the budget, a slerp outside it; the guidance window
// edge (age == lifetime) leaves a zero budget.
TEST(ProjectileGeometry, GuideTurnBudget) {
    World w;
    const int64_t s = w.set();
    w.frames(s);
    const int64_t tgt = w.ship(s, 100.0, 0.0, 0.0);  // 90 degrees off
    const int64_t h = w.torp(s, tgt, {0, 0, 0}, {0, 10, 0});
    w.m.torpedoes().set_f(h, TorpField::_max_angular_accel, 1000.0);
    GuideResult r = w.guide(h, 0.1);
    ASSERT_EQ(r.n_writes, 3);
    EXPECT_EQ(r.writes[2].value, (Vec3{10.0, 0.0, 0.0}));  // desired * speed
    w.m.torpedoes().set_f(h, TorpField::_max_angular_accel, 0.125);
    r = w.guide(h, 0.1);
    const double max_step = ((4.0 / 4.0) * 0.125) * 0.1;
    const double theta = std::acos(0.0);
    const double st = py_sin(theta);
    const double a = py_sin(theta - max_step) / st;
    const double b = py_sin(max_step) / st;
    EXPECT_EQ(r.writes[2].value,
              (Vec3{(0.0 * a + 1.0 * b) * 10.0, (1.0 * a + 0.0 * b) * 10.0,
                    (0.0 * a + 0.0 * b) * 10.0}));
    w.m.torpedoes().set_f(h, TorpField::_age, 4.0);
    r = w.guide(h, 0.1);
    EXPECT_EQ(r.writes[2].value, (Vec3{0.0 * 10.0, 1.0 * 10.0, 0.0 * 10.0}));
    // Guidance initial NaN reads as 1.0 (`NaN > 1e-9` is False): the budget
    // is (4.0 / 1.0) * 0.125 * 0.1, still a slerp.
    w.m.torpedoes().set_f(h, TorpField::_age, 0.0);
    w.m.torpedoes().set_f(h, TorpField::_guidance_initial, kNan);
    r = w.guide(h, 0.1);
    ASSERT_EQ(r.status, St::done);
    ASSERT_EQ(r.n_writes, 3);
    const double nan_step = ((4.0 / 1.0) * 0.125) * 0.1;
    const double na = py_sin(theta - nan_step) / st;
    const double nb = py_sin(nan_step) / st;
    EXPECT_EQ(r.writes[2].value,
              (Vec3{(0.0 * na + 1.0 * nb) * 10.0, (1.0 * na + 0.0 * nb) * 10.0,
                    (0.0 * na + 0.0 * nb) * 10.0}));
    EXPECT_NE(r.writes[2].value, (Vec3{10.0, 0.0, 0.0}));
    // An infinite lifetime: an infinite budget, so the snap to `desired`.
    w.m.torpedoes().set_f(h, TorpField::_guidance_lifetime, kInf);
    r = w.guide(h, 0.1);
    ASSERT_EQ(r.status, St::done);
    ASSERT_EQ(r.n_writes, 3);
    EXPECT_EQ(r.writes[2].value, (Vec3{10.0, 0.0, 0.0}));
}
