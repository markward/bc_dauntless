// The native beam geometry (beam_geometry.h) on hand-built mirror rows: exact
// answers for the map's edges. The native-vs-Python differential runs from
// tests/unit/test_native_beam_geometry.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/sensor_state.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t next_id = 1;

    World() {
        m.set_global_f(Global::BEAM_DWELL_FLUSH_S, 0.5);
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
    }
    int64_t ship(double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::is_ship_class, 1);
        return h;
    }
    // A phaser bank on `ship_h`: forward +Y, up +Z, a free width.
    int64_t bank(int64_t ship_h, double length) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_fv(s, Field::_direction, {0.0, 1.0, 0.0});
        m.set_fv(s, Field::_up, {0.0, 0.0, 1.0});
        m.set_f(s, Field::_length, length);
        m.set_f(s, Field::_arc_width_lo, -3.0);
        m.set_f(s, Field::_arc_width_hi, 3.0);
        return s;
    }
};

}  // namespace

TEST(BeamGeometry, StripZeroProjectionsEmitStraightAhead) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 2.0);
    // The target is the centre: both projections 0, yaw +0, emit = forward*L.
    const Vec3 p = strip_emit_position(w.m, bank, {0.0, 0.0, 0.0}, false);
    EXPECT_EQ(p[0], 0.0);
    EXPECT_EQ(p[1], 2.0);
    EXPECT_EQ(p[2], 0.0);
}

TEST(BeamGeometry, StripReversedWidthAlwaysYieldsLo) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0);
    w.m.set_f(bank, Field::_arc_width_lo, 1.0);
    w.m.set_f(bank, Field::_arc_width_hi, -1.0);
    // Unsorted max(lo, min(hi, yaw)) = lo whatever the yaw. Sorting would
    // give a yaw of 0.5 here, and a different point.
    const Vec3 a = strip_emit_position(w.m, bank, {0.0, 100.0, 0.0}, false);
    const Vec3 b = strip_emit_position(w.m, bank, {100.0, 0.0, 0.0}, false);
    EXPECT_EQ(a, b);
    EXPECT_EQ(a[0], std::sin(1.0));  // right = (1, 0, 0), yaw = lo = 1
}

TEST(BeamGeometry, StripLengthZeroOrNegativeReturnsCentre) {
    World w;
    const int64_t ship = w.ship(5.0, 6.0, 7.0);
    const int64_t bank = w.bank(ship, 0.0);
    EXPECT_EQ(strip_emit_position(w.m, bank, {1.0, 2.0, 3.0}, false),
              (Vec3{5.0, 6.0, 7.0}));
    w.m.set_f(bank, Field::_length, -2.0);
    EXPECT_EQ(strip_emit_position(w.m, bank, {1.0, 2.0, 3.0}, false),
              (Vec3{5.0, 6.0, 7.0}));
    // NaN passes `length <= 0.0` and continues: the point is NaN.
    w.m.set_f(bank, Field::_length, kNan);
    EXPECT_TRUE(std::isnan(
        strip_emit_position(w.m, bank, {1.0, 2.0, 3.0}, false)[1]));
}

TEST(BeamGeometry, StripMemoisesTheCentreLikeTheStepMemo) {
    // use_memo (step_memo.active()): the centre is _emitter_world_position,
    // memoised by (bank, None) as subsystems._mounts is, so inside a step a
    // ship moved after the first call still emits from the OLD centre (as
    // the Python does); without the memo, or once it is cleared, the new.
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 2.0);
    const Vec3 first = strip_emit_position(w.m, bank, {0.0, 100.0, 0.0}, true);
    EXPECT_EQ(first, (Vec3{0.0, 2.0, 0.0}));
    EXPECT_EQ(w.m.sensor_state().mounts.count({bank, -1}), 1u);
    const auto* row = w.m.object(ship);
    w.store.set_position(static_cast<uint32_t>(row->xform_index),
                         static_cast<uint32_t>(row->xform_gen), 10.0, 0.0,
                         0.0);
    EXPECT_EQ(strip_emit_position(w.m, bank, {0.0, 100.0, 0.0}, true), first);
    // Live: the centre 10 GU along +x (and so another yaw).
    const Vec3 live = strip_emit_position(w.m, bank, {0.0, 100.0, 0.0}, false);
    EXPECT_GT(live[0], 9.0);
    memo_clear(w.m);
    EXPECT_EQ(strip_emit_position(w.m, bank, {0.0, 100.0, 0.0}, true), live);
}

TEST(BeamGeometry, DwellFlushesOnlyWhenBeamOnAndPastThreshold) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0);
    w.m.set_i(bank, Field::_firing, 1);
    w.m.set_f(bank, Field::_beam_on_countdown, 0.0);
    w.m.set_f(bank, Field::_dwell, 0.5);  // exactly the threshold: no flush
    DwellResult r = accumulate_dwell(w.m, bank, 0.25);
    EXPECT_EQ(r.flushed, 0.0);
    EXPECT_EQ(r.new_dwell, 0.75);
    w.m.set_f(bank, Field::_dwell, std::nextafter(0.5, 1.0));
    r = accumulate_dwell(w.m, bank, 0.25);
    EXPECT_EQ(r.flushed, std::nextafter(0.5, 1.0) + 0.25);
    EXPECT_EQ(r.new_dwell, 0.0);
    // Reports only: the row is untouched.
    EXPECT_EQ(w.m.subsystem(bank)->_dwell, std::nextafter(0.5, 1.0));
}

TEST(BeamGeometry, DwellNanCountdownIsNotBeamOn) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0);
    w.m.set_i(bank, Field::_firing, 1);
    w.m.set_f(bank, Field::_beam_on_countdown, kNan);
    w.m.set_f(bank, Field::_dwell, 0.3);
    const DwellResult r = accumulate_dwell(w.m, bank, 0.1);
    EXPECT_EQ(r.flushed, 0.0);
    EXPECT_EQ(r.new_dwell, 0.3);
    const DwellResult t = take_dwell(w.m, bank);
    EXPECT_EQ(t.flushed, 0.3);
    EXPECT_EQ(t.new_dwell, 0.0);
}

TEST(BeamGeometry, SphereEntryOriginIsADistinctMarker) {
    const Vec3 c{0.0, 0.0, 0.0}, d{1.0, 0.0, 0.0};
    const SphereEntry inside = ray_sphere_entry({1.0, 0.0, 0.0}, d, 10.0, c, 5.0);
    EXPECT_EQ(inside.kind, SphereEntry::Kind::Origin);
    const SphereEntry hit = ray_sphere_entry({-10.0, 0.0, 0.0}, d, 100.0, c, 5.0);
    EXPECT_EQ(hit.kind, SphereEntry::Kind::Point);
    EXPECT_EQ(hit.point[0], -5.0);
    EXPECT_EQ(ray_sphere_entry({10.0, 0.0, 0.0}, d, 100.0, c, 5.0).kind,
              SphereEntry::Kind::None);  // behind
    EXPECT_EQ(ray_sphere_entry({-10.0, 0.0, 0.0}, d, 100.0, c, 0.0).kind,
              SphereEntry::Kind::None);  // radius <= 0
    EXPECT_EQ(ray_sphere_entry({-10.0, 0.0, 0.0}, d, 1.0, c, 5.0).kind,
              SphereEntry::Kind::None);  // beyond the segment
}

TEST(BeamGeometry, WorldRadiusScalesOnlyForAFinitePositiveScale) {
    World w;
    const int64_t s = w.ship(0.0, 0.0, 0.0);
    w.m.set_f(s, Field::o_radius, 4.0);
    w.m.set_f(s, Field::_scale, 2.5);
    EXPECT_EQ(world_radius(w.m, s), 10.0);
    for (double bad : {0.0, -1.0, kNan,
                       std::numeric_limits<double>::infinity()}) {
        w.m.set_f(s, Field::_scale, bad);
        EXPECT_EQ(world_radius(w.m, s), 4.0);
    }
}

TEST(BeamGeometry, ShieldsBlockFallsBackForNonShips) {
    World w;
    const int64_t s = w.ship(0.0, 0.0, 0.0);
    w.m.set_i(s, Field::has_real_get_shields, 1);
    w.m.set_i(s, Field::is_ship_class, 0);
    EXPECT_THROW(shields_block(w.m, s, false, -1), std::invalid_argument);
    w.m.set_i(s, Field::is_ship_class, 1);
    w.m.set_i(s, Field::has_real_get_shields, 0);
    EXPECT_THROW(shields_block(w.m, s, false, -1), std::invalid_argument);
}

TEST(BeamGeometry, ShieldsBlockPredicateOrder) {
    World w;
    const int64_t s = w.ship(0.0, 0.0, 0.0);
    w.m.set_i(s, Field::has_real_get_shields, 1);
    w.m.set_i(s, Field::has_cloak_getter, 1);
    EXPECT_FALSE(shields_block(w.m, s, false, -1));  // no shield subsystem
    const int64_t sh = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(s, Field::_shield_subsystem, sh);
    w.m.set_i(sh, Field::has_shields, 1);
    w.m.set_i(sh, Field::_is_on, 1);
    EXPECT_TRUE(shields_block(w.m, s, false, -1));
    // The dev cheat: down for everyone but the player.
    EXPECT_FALSE(shields_block(w.m, s, true, -1));
    EXPECT_FALSE(shields_block(w.m, s, true, s + 1));
    EXPECT_TRUE(shields_block(w.m, s, true, s));
    // A cloak mid-transition suspends them.
    const int64_t cloak = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(s, Field::_cloaking_subsystem, cloak);
    w.m.set_i(cloak, Field::_cloak_state, 1);
    EXPECT_FALSE(shields_block(w.m, s, false, -1));
    w.m.set_i(cloak, Field::_cloak_state, 2);  // fully cloaked: not suspended
    EXPECT_TRUE(shields_block(w.m, s, false, -1));
    w.m.set_i(sh, Field::_is_on, 0);
    EXPECT_FALSE(shields_block(w.m, s, false, -1));
}

TEST(BeamGeometry, BubbleEntryAndTheNanPoint) {
    World w;
    const int64_t s = w.ship(0.0, 0.0, 0.0);
    w.m.set_fv(s, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
    w.m.set_fv(s, Field::_shield_hull_box_half, {1.0, 1.0, 1.0});
    w.m.set_i(s, Field::hull_box_set, 1);
    const Vec3 down{0.0, -1.0, 0.0};
    const auto hit = shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0}, down, 1000.0);
    ASSERT_TRUE(hit.has_value());
    EXPECT_NEAR((*hit)[1], std::sqrt(3.0), 1e-12);
    // NaN origin: every compare is False and a NaN POINT comes back.
    const auto nan_pt =
        shield_bubble_entry(w.m, s, {kNan, 100.0, 0.0}, down, 1000.0);
    ASSERT_TRUE(nan_pt.has_value());
    EXPECT_TRUE(std::isnan((*nan_pt)[0]));
    // Inside the bubble, a zero direction, and a short segment: nullopt.
    EXPECT_FALSE(shield_bubble_entry(w.m, s, {0.0, 0.0, 0.0}, down, 1000.0));
    EXPECT_FALSE(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0},
                                     {0.0, 0.0, 0.0}, 1000.0));
    EXPECT_FALSE(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0}, down, 1.0));
    // A degenerate raw half-extent: no box.
    w.m.set_fv(s, Field::_shield_hull_box_half, {1.0, 0.0, 1.0});
    EXPECT_FALSE(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0}, down, 1000.0));
    // No box set at all.
    w.m.set_i(s, Field::hull_box_set, 0);
    EXPECT_FALSE(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0}, down, 1000.0));
}

TEST(BeamGeometry, BubbleZeroSemiAxisByUnderflowFallsBack) {
    // A raw half-extent > 0 passes _hull_box_for, but half * scale * k can
    // underflow to 0: Python's division then raises ZeroDivisionError, so
    // the native answer must fall back (invalid_argument: Python answers).
    World w;
    const int64_t s = w.ship(0.0, 0.0, 0.0);
    w.m.set_fv(s, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
    w.m.set_fv(s, Field::_shield_hull_box_half, {1.0, 1e-300, 1.0});
    w.m.set_i(s, Field::hull_box_set, 1);
    w.m.set_f(s, Field::_scale, 1e-30);
    EXPECT_THROW(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0},
                                     {0.0, -1.0, 0.0}, 1000.0),
                 std::invalid_argument);
    // No underflow at scale 1: an answer.
    w.m.set_f(s, Field::_scale, 1.0);
    EXPECT_NO_THROW(shield_bubble_entry(w.m, s, {0.0, 100.0, 0.0},
                                        {0.0, -1.0, 0.0}, 1000.0));
}

TEST(BeamGeometry, AimPointUsesTheLocksOwnShip) {
    World w;
    const int64_t firer = w.ship(0.0, 0.0, 0.0);
    const int64_t target = w.ship(0.0, 100.0, 0.0);
    const int64_t other = w.ship(500.0, 0.0, 0.0);
    const int64_t lock = w.bank(other, 1.0);
    w.m.set_fv(lock, Field::_position, {1.0, 2.0, 3.0});
    // No lock: the target's centre.
    AimPoint a = phaser_aim_point(w.m, firer, target, false);
    EXPECT_EQ(a.point, (Vec3{0.0, 100.0, 0.0}));
    EXPECT_EQ(a.target_sub, -1);
    // A lock on ANOTHER ship's mount: that mount, not the target's.
    w.m.set_ref(firer, Field::_target_subsystem, lock);
    a = phaser_aim_point(w.m, firer, target, false);
    EXPECT_EQ(a.point, (Vec3{501.0, 2.0, 3.0}));
    EXPECT_EQ(a.target_sub, lock);
    // The pose flag that matters is the lock's ship, not the target's.
    w.m.set_i(target, Field::has_posed_parts, 1);
    EXPECT_NO_THROW(phaser_aim_point(w.m, firer, target, false));
    w.m.set_i(other, Field::has_posed_parts, 1);
    EXPECT_THROW(phaser_aim_point(w.m, firer, target, false),
                 std::invalid_argument);
}
