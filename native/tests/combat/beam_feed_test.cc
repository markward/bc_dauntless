// The native beam descriptor feed (beam_feed.h) on hand-built mirror rows:
// the Python builders' order, `or` defaults, frame shifts, endpoint tiers and
// fallbacks. The native-vs-Python differential over real instances runs from
// tests/host/test_native_beam_feed.py (phase 6 follow-up 1, Task 4).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>

#include "dauntless/combat/beam_feed.h"
#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();
constexpr double kMut = 3.0, kPhaserB = 0.6, kTractorB = 0.5,
                 kTractorEnd = 1.25;

// The trace host: instance {1, 1} sits at `at` and its trace returns `hit`
// (instance-relative, as the binding's), any other id is stale.
struct FakeHost {
    Vec3 at{0.0, 0.0, 0.0};
    std::optional<TraceHit> hit;
    int calls = 0;
    // The last trace's arguments, as the binding receives them.
    float origin[3] = {0.0f, 0.0f, 0.0f};
    float max_dist = 0.0f;
    TraceHooks hooks() {
        TraceHooks h;
        h.translation = [this](InstanceId id) -> std::optional<Vec3> {
            if (id.index != 1 || id.generation != 1) return std::nullopt;
            return at;
        };
        h.trace = [this](InstanceId id, const float* o, const float*,
                         float md) -> std::optional<TraceHit> {
            ++calls;
            origin[0] = o[0];
            origin[1] = o[1];
            origin[2] = o[2];
            max_dist = md;
            if (id.index != 1 || id.generation != 1)
                throw StaleInstance("ray_trace_mesh: invalid InstanceId");
            return hit;
        };
        return h;
    }
};

struct World {
    TransformStore store;
    Mirror m{store};
    FakeHost host;
    int64_t set = -1;  // the viewed set, frame 1 at the origin
    int64_t next_id = 1;
    BeamFeedCtx ctx;

    World() {
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
        set = add_set(1, {0.0, 0.0, 0.0});
        ctx.view = set;
        ctx.width_mutator = kMut;
        ctx.phaser_brightness = kPhaserB;
        ctx.tractor_brightness = kTractorB;
        ctx.tractor_end_width_scale = kTractorEnd;
    }
    int64_t add_set(int64_t frame_id, Vec3 anchor) {
        const int64_t s = m.register_row(Kind::Set);
        ctx.frames[s] = BeamFrame{frame_id, anchor};
        return s;
    }
    // A ShipClass in `in_set` (the viewed set by default), no shields.
    int64_t ship(double x, double y, double z, int64_t in_set = -1) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_i(h, Field::has_real_get_shields, 1);
        m.set_i(h, Field::has_cloak_getter, 1);
        m.set_ref(h, Field::_containing_set, in_set == -1 ? set : in_set);
        m.set_f(h, Field::o_radius, 5.0);
        m.set_f(h, Field::_scale, 1.0);
        return h;
    }
    int64_t system(int64_t ship_h, bool tractor = false) {
        const int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::has_parent_ship_getter, 1);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_ref(ship_h,
                  tractor ? Field::_tractor_beam_system : Field::_phaser_system,
                  s);
        return s;
    }
    // A point emitter (Length 0) at the ship's origin, aimed at `target`,
    // with every beam visual set to a non-default value.
    int64_t bank(int64_t sys, int64_t target, bool firing = true,
                 double width = 0.4) {
        const int64_t b = m.register_row(Kind::Subsystem);
        m.set_i(b, Field::has_parent_ship_getter, 1);
        m.set_ref(b, Field::_parent_subsystem, sys);
        m.set_fv(b, Field::_position, {0.0, 0.0, 0.0});
        m.set_fv(b, Field::_direction, {0.0, 1.0, 0.0});
        m.set_fv(b, Field::_up, {0.0, 0.0, 1.0});
        m.set_fv(b, Field::_right, {1.0, 0.0, 0.0});
        m.set_f(b, Field::_length, 0.0);
        m.set_i(b, Field::_firing, firing ? 1 : 0);
        m.set_ref(b, Field::_target, target);
        m.set_f(b, Field::_length_texture_tile_per_unit, 0.1);
        m.set_f(b, Field::_phaser_width, width);
        m.set_f(b, Field::_main_radius, 0.2);
        m.set_f(b, Field::_core_scale, 0.65);
        m.set_f(b, Field::_taper_radius, 0.03);
        m.set_f(b, Field::_taper_ratio, 0.4);
        m.set_f(b, Field::_taper_min_length, 7.0);
        m.set_f(b, Field::_taper_max_length, 40.0);
        m.set_f(b, Field::_perimeter_tile, 2.0);
        m.set_f(b, Field::_texture_speed, 0.5);
        m.set_i(b, Field::_num_sides, 8);
        m.set_fv(b, Field::_outer_shell_color, {1.0, 0.5, 0.25, 0.9});
        m.set_fv(b, Field::_inner_core_color, {0.2, 0.4, 0.6, 1.0});
        auto kids = m.get_ids(sys, Field::_children);
        kids.push_back(b);
        m.set_ids(sys, Field::_children, kids);
        return b;
    }
    // Live shields on `target`, with a unit hull box (bubble radius sqrt 3).
    void shields(int64_t target) {
        const int64_t sh = m.register_row(Kind::Subsystem);
        m.set_ref(target, Field::_shield_subsystem, sh);
        m.set_i(sh, Field::has_shields, 1);
        m.set_i(sh, Field::_is_on, 1);
        m.set_fv(target, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
        m.set_fv(target, Field::_shield_hull_box_half, {1.0, 1.0, 1.0});
        m.set_i(target, Field::hull_box_set, 1);
    }

    std::vector<BeamOut> phasers, tractors;
    void run(const std::vector<int64_t>& ships) {
        ctx.hooks = host.hooks();
        build_beam_feed(m, ships, ctx, phasers, tractors);
    }
};

// A ship at the origin firing one bank at a ship 50 GU ahead (+y).
struct Scene {
    int64_t ship, sys, target, bank;
};
Scene scene(World& w) {
    Scene s;
    s.ship = w.ship(0.0, 0.0, 0.0);
    s.sys = w.system(s.ship);
    s.target = w.ship(0.0, 50.0, 0.0);
    s.bank = w.bank(s.sys, s.target);
    return s;
}

}  // namespace

TEST(BeamFeed, OnePhaserBankYieldsOuterThenInner) {
    World w;
    const Scene s = scene(w);
    w.run({s.ship, s.target});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_TRUE(w.tractors.empty());
    const BeamOut& o = w.phasers[0];
    const BeamOut& i = w.phasers[1];
    EXPECT_EQ(o.emitter, (Vec3{0.0, 0.0, 0.0}));
    EXPECT_EQ(o.target, (Vec3{0.0, 50.0, 0.0}));
    EXPECT_EQ(o.width, 0.4 * kMut);
    EXPECT_EQ(i.width, 0.2 * 0.65 * kMut);  // (main * core) * mut
    // The grouping is pinned: these values round differently the other way.
    ASSERT_NE(0.2 * 0.65 * kMut, 0.2 * (0.65 * kMut));
    EXPECT_EQ(o.color, (std::array<double, 4>{1.0 * kPhaserB, 0.5 * kPhaserB,
                                              0.25 * kPhaserB, 0.9}));
    EXPECT_EQ(i.color, (std::array<double, 4>{0.2 * kPhaserB, 0.4 * kPhaserB,
                                              0.6 * kPhaserB, 0.35}));
    for (const BeamOut* d : {&o, &i}) {
        EXPECT_EQ(d->u_tiles, py_max(1.0, 50.0 * 0.1));
        EXPECT_EQ(d->num_sides, 8);
        EXPECT_EQ(d->taper_radius, 0.03 * kMut);
        EXPECT_EQ(d->taper_ratio, 0.4);
        EXPECT_EQ(d->taper_min_length, 7.0);
        EXPECT_EQ(d->taper_max_length, 40.0);
        EXPECT_EQ(d->perimeter_tile, 2.0);
        EXPECT_EQ(d->texture_speed, 0.5);
        EXPECT_EQ(d->end_width_scale, 1.0);
    }
}

TEST(BeamFeed, PhasersBeforeTractorsInShipThenBankOrder) {
    World w;
    const int64_t a = w.ship(0.0, 0.0, 0.0);
    const int64_t b = w.ship(10.0, 0.0, 0.0);
    const int64_t t = w.ship(0.0, 50.0, 0.0);
    const int64_t pa = w.system(a);
    w.bank(pa, t, true, 1.0);
    w.bank(pa, t, false, 2.0);  // not firing: skipped
    w.bank(pa, t, true, 3.0);
    const int64_t ta = w.system(a, /*tractor=*/true);
    w.bank(ta, t, true, 4.0);
    const int64_t pb = w.system(b);
    w.bank(pb, t, true, 5.0);
    w.run({a, b, t});
    ASSERT_EQ(w.phasers.size(), 6u);
    const double want[] = {1.0, 3.0, 5.0};
    for (int k = 0; k < 3; ++k) {
        EXPECT_EQ(w.phasers[2 * k].width, want[k] * kMut) << k;
        EXPECT_EQ(w.phasers[2 * k + 1].width, 0.2 * 0.65 * kMut) << k;
    }
    EXPECT_EQ(w.phasers[4].emitter, (Vec3{10.0, 0.0, 0.0}));
    ASSERT_EQ(w.tractors.size(), 2u);
    EXPECT_EQ(w.tractors[0].width, 4.0 * kMut);
}

TEST(BeamFeed, TractorPairCarriesEndWidthScale) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t t = w.ship(0.0, 50.0, 0.0);
    w.bank(w.system(ship, /*tractor=*/true), t);
    w.run({ship, t});
    EXPECT_TRUE(w.phasers.empty());
    ASSERT_EQ(w.tractors.size(), 2u);
    for (const BeamOut& d : w.tractors) EXPECT_EQ(d.end_width_scale, kTractorEnd);
    EXPECT_EQ(w.tractors[0].color,
              (std::array<double, 4>{1.0 * kTractorB, 0.5 * kTractorB,
                                     0.25 * kTractorB, 0.9}));
    EXPECT_EQ(w.tractors[1].color,
              (std::array<double, 4>{0.2 * kTractorB, 0.4 * kTractorB,
                                     0.6 * kTractorB, 0.35}));
}

TEST(BeamFeed, OrDefaultsMatchPython) {
    World w;
    const Scene s = scene(w);
    // `x or d`: -0.0 and 0.0 are falsy, NaN is truthy.
    w.m.set_f(s.bank, Field::_core_scale, -0.0);
    w.m.set_f(s.bank, Field::_taper_ratio, kNan);
    // int(6.7) == 6 happens in the push (NativeField(int)); 6 is kept.
    w.m.set_i(s.bank, Field::_num_sides, 6);
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.phasers[1].width, 0.2 * 0.5 * kMut);
    EXPECT_TRUE(std::isnan(w.phasers[0].taper_ratio));
    EXPECT_EQ(w.phasers[0].num_sides, 6);

    // Every visual zero: each `or` default.
    for (const Field f :
         {Field::_phaser_width, Field::_main_radius, Field::_core_scale,
          Field::_taper_radius, Field::_taper_ratio, Field::_taper_min_length,
          Field::_taper_max_length, Field::_perimeter_tile,
          Field::_texture_speed})
        w.m.set_f(s.bank, f, 0.0);
    w.m.set_i(s.bank, Field::_num_sides, 0);
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    const BeamOut& o = w.phasers[0];
    EXPECT_EQ(o.width, 0.30 * kMut);
    EXPECT_EQ(w.phasers[1].width, 0.15 * 0.50 * kMut);
    EXPECT_EQ(o.num_sides, 6);
    EXPECT_EQ(o.taper_radius, 0.01 * kMut);
    EXPECT_EQ(o.taper_ratio, 0.25);
    EXPECT_EQ(o.taper_min_length, 5.0);
    EXPECT_EQ(o.taper_max_length, 30.0);
    EXPECT_EQ(o.perimeter_tile, 1.0);
    EXPECT_EQ(o.texture_speed, 0.0);
}

TEST(BeamFeed, ZeroShiftKeepsNegativeZero) {
    World w;
    // A -0.0 mount: R . (-0, -0, -0) is -0 per axis and -0 + -0 stays -0.
    const int64_t ship = w.ship(-0.0, 0.0, 0.0);
    const int64_t t = w.ship(-0.0, 50.0, 0.0);
    const int64_t b = w.bank(w.system(ship), t);
    w.m.set_fv(b, Field::_position, {-0.0, -0.0, -0.0});
    w.run({ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_TRUE(std::signbit(w.phasers[0].emitter[0]));
    EXPECT_TRUE(std::signbit(w.phasers[0].target[0]));
    // An explicit -0.0 origin is still `== _ZERO`: untouched.
    w.ctx.origin = {-0.0, 0.0, -0.0};
    w.run({ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_TRUE(std::signbit(w.phasers[0].emitter[0]));
}

TEST(BeamFeed, RenderOriginIsSubtracted) {
    World w;
    const Scene s = scene(w);
    w.ctx.origin = {10.0, 20.0, 30.0};
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    for (const BeamOut& d : w.phasers) {
        EXPECT_EQ(d.emitter, (Vec3{-10.0, -20.0, -30.0}));
        EXPECT_EQ(d.target, (Vec3{-10.0, 30.0, -30.0}));
    }
}

TEST(BeamFeed, CrossRegionPairMeetsInTheTargetsSet) {
    World w;
    // Three regions of one system (frame 7): the ship's at 0, the target's
    // at +1000 x, the viewed one at +200 x.
    const int64_t s1 = w.add_set(7, {0.0, 0.0, 0.0});
    const int64_t s2 = w.add_set(7, {1000.0, 0.0, 0.0});
    const int64_t s3 = w.add_set(7, {200.0, 0.0, 0.0});
    w.ctx.view = s3;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, s1);
    const int64_t t = w.ship(-990.0, 50.0, 0.0, s2);  // (10, 50, 0) in s1
    w.bank(w.system(ship), t);
    w.run({ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    const BeamOut& o = w.phasers[0];
    // The emitter from s1 into s3: 0 - 200; the target from s2: 1000 - 200.
    EXPECT_EQ(o.emitter, (Vec3{-200.0, 0.0, 0.0}));
    EXPECT_EQ(o.target, (Vec3{-190.0, 50.0, 0.0}));
    // The length is measured in the target's set: (10, 50, 0).
    EXPECT_EQ(o.u_tiles, py_max(1.0, py_pow(10.0 * 10.0 + 50.0 * 50.0, 0.5) * 0.1));
}

TEST(BeamFeed, OtherFrameTargetDrawsNothing) {
    World w;
    const int64_t other = w.add_set(2, {0.0, 0.0, 0.0});
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t t = w.ship(0.0, 50.0, 0.0, other);
    w.bank(w.system(ship), t);
    w.bank(w.system(ship, true), t);
    // A lock the mirror cannot name makes the aim point throw: the None
    // to_ship returns [] BEFORE the aim point, so nothing throws here.
    w.m.set_ref(ship, Field::_target_subsystem, kRefUnrepresentable);
    w.run({ship});
    EXPECT_TRUE(w.phasers.empty());
    EXPECT_TRUE(w.tractors.empty());
    // Same frame: the aim point is reached, and throws.
    w.m.set_ref(t, Field::_containing_set, w.set);
    EXPECT_THROW(w.run({ship}), std::invalid_argument);
}

TEST(BeamFeed, ShipOutOfViewDrawsNothing) {
    World w;
    const Scene s = scene(w);
    w.ctx.view = w.add_set(2, {0.0, 0.0, 0.0});  // another frame viewed
    w.run({s.ship});
    EXPECT_TRUE(w.phasers.empty());
    w.ctx.view = -1;  // nothing viewed
    w.run({s.ship});
    EXPECT_TRUE(w.phasers.empty());
    // A ship in no set is in no frame.
    w.ctx.view = w.set;
    w.m.set_ref(s.ship, Field::_containing_set, -1);
    w.run({s.ship});
    EXPECT_TRUE(w.phasers.empty());
}

TEST(BeamFeed, NoTargetDrawsNothing) {
    World w;
    const Scene s = scene(w);
    w.m.set_ref(s.bank, Field::_target, -1);
    w.run({s.ship});
    EXPECT_TRUE(w.phasers.empty());
}

TEST(BeamFeed, ShieldsUpEndsOnTheBubble) {
    World w;
    const Scene s = scene(w);
    w.shields(s.target);
    w.host.hit = TraceHit{{0.0f, -1.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 49.0f};
    w.host.at = {0.0, 50.0, 0.0};
    w.ctx.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    const auto entry = shield_bubble_entry(w.m, s.target, {0.0, 0.0, 0.0},
                                           {0.0, 1.0, 0.0}, 50.0 * 1.5);
    ASSERT_TRUE(entry.has_value());
    EXPECT_EQ(w.phasers[0].target, *entry);
    EXPECT_EQ(w.host.calls, 0);  // the bubble stops it before the trace
    EXPECT_EQ(w.phasers[0].u_tiles, py_max(1.0, (*entry)[1] * 0.1));
}

TEST(BeamFeed, ShieldsDownEndsOnTheHullTrace) {
    World w;
    const Scene s = scene(w);
    // Instance-relative hit 2 GU short of the target's centre.
    w.host.at = {0.0, 50.0, 0.0};
    w.host.hit = TraceHit{{0.0f, -2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    w.ctx.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.host.calls, 1);
    EXPECT_EQ(w.phasers[0].target, (Vec3{0.0, 48.0, 0.0}));
    EXPECT_EQ(w.phasers[1].target, (Vec3{0.0, 48.0, 0.0}));
    // A trace miss: the bounding sphere (radius 5) entry.
    w.host.hit.reset();
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    const SphereEntry e = ray_sphere_entry({0.0, 0.0, 0.0}, {0.0, 1.0, 0.0},
                                           50.0 * 1.5, {0.0, 50.0, 0.0}, 5.0);
    ASSERT_EQ(e.kind, SphereEntry::Kind::Point);
    EXPECT_EQ(w.phasers[0].target, e.point);
    EXPECT_NEAR(e.point[1], 45.0, 1e-9);
}

TEST(BeamFeed, HullTraceShiftsIntoTheViewAndBack) {
    World w;
    // One frame (7): the ship's region at 0, the target's at +1000 x, the
    // viewed one at +200 x. view_offset(target's set) = 1000 - 200 = 800;
    // the ship's set would give -200.
    const int64_t sa = w.add_set(7, {0.0, 0.0, 0.0});
    const int64_t sb = w.add_set(7, {1000.0, 0.0, 0.0});
    const int64_t sv = w.add_set(7, {200.0, 0.0, 0.0});
    w.ctx.view = sv;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, sa);
    const int64_t t = w.ship(-990.0, 50.0, 0.0, sb);
    w.bank(w.system(ship), t);
    // The target's instance in VIEW space: (-990 + 800, 50, 0).
    w.host.at = {-190.0, 50.0, 0.0};
    w.host.hit = TraceHit{{0.0f, -2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    w.ctx.iids[t] = K2Context::Iid{false, {1, 1}};
    w.run({ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    ASSERT_EQ(w.host.calls, 1);
    // emitter_t (-1000, 0, 0) in the target's set, +800 into the view
    // (-200, 0, 0), minus the instance translation: (-10, -50, 0).
    EXPECT_EQ(w.host.origin[0], -10.0f);
    EXPECT_EQ(w.host.origin[1], -50.0f);
    EXPECT_EQ(w.host.origin[2], 0.0f);
    // max_dist = raw_length * 1.5, narrowed as pybind narrows it.
    const double raw = py_pow(10.0 * 10.0 + 50.0 * 50.0, 0.5);
    EXPECT_EQ(w.host.max_dist, narrow_like_pybind(raw * 1.5));
    // The hit (-190, 48, 0) in view, -800 back into the target's set
    // (-990, 48, 0), then +800 into the view by _beam_pair_in_view. Not
    // shifting back would draw it at (610, 48, 0).
    EXPECT_EQ(w.phasers[0].target, (Vec3{-190.0, 48.0, 0.0}));
    EXPECT_EQ(w.phasers[0].emitter, (Vec3{-200.0, 0.0, 0.0}));
    // The length is the target's set's: (10, 48, 0) from emitter_t.
    EXPECT_EQ(w.phasers[0].u_tiles,
              py_max(1.0, py_pow(10.0 * 10.0 + 48.0 * 48.0, 0.5) * 0.1));
}

TEST(BeamFeed, HullTraceMaxDistIsRawLengthTimesOnePointFive) {
    World w;
    const Scene s = scene(w);
    w.host.at = {0.0, 50.0, 0.0};
    w.host.hit = TraceHit{{0.0f, -2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    w.ctx.iids[s.target] = K2Context::Iid{false, {1, 1}};
    w.run({s.ship});
    ASSERT_EQ(w.host.calls, 1);
    EXPECT_EQ(w.host.max_dist, narrow_like_pybind(50.0 * 1.5));
    // Same set as the view: no shift, so the origin is (0,0,0) - at.
    EXPECT_EQ(w.host.origin[1], -50.0f);
}

TEST(BeamFeed, BadIidTakesTheSphereTierWithoutATrace) {
    World w;
    const Scene s = scene(w);
    w.host.at = {0.0, 50.0, 0.0};
    w.host.hit = TraceHit{{0.0f, -2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    // Not an InstanceId: host_io raises inside _resolve_hit_point's try.
    w.ctx.iids[s.target] = K2Context::Iid{true, {1, 1}};
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.host.calls, 0);
    const SphereEntry e = ray_sphere_entry({0.0, 0.0, 0.0}, {0.0, 1.0, 0.0},
                                           50.0 * 1.5, {0.0, 50.0, 0.0}, 5.0);
    ASSERT_EQ(e.kind, SphereEntry::Kind::Point);
    EXPECT_EQ(w.phasers[0].target, e.point);
}

TEST(BeamFeed, CrossRegionStripBankAimsAtTheShiftedTarget) {
    World w;
    const int64_t sa = w.add_set(7, {0.0, 0.0, 0.0});
    const int64_t sb = w.add_set(7, {1000.0, 0.0, 0.0});
    w.ctx.view = sa;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, sa);
    const int64_t t = w.ship(-990.0, 50.0, 0.0, sb);  // (10, 50, 0) in sa
    const int64_t b = w.bank(w.system(ship), t);
    w.m.set_f(b, Field::_length, 2.0);
    w.m.set_f(b, Field::_arc_width_lo, -3.0);
    w.m.set_f(b, Field::_arc_width_hi, 3.0);
    // The strip point for the target in the SHIP's coordinates ...
    const Vec3 want = strip_emit_position(w.m, b, {10.0, 50.0, 0.0}, false);
    // ... which the unshifted target-local point would not give.
    ASSERT_NE(want, strip_emit_position(w.m, b, {-990.0, 50.0, 0.0}, false));
    w.run({ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.phasers[0].emitter, want);  // view == the ship's set
    EXPECT_EQ(w.phasers[0].target, (Vec3{10.0, 50.0, 0.0}));
}

TEST(BeamFeed, NoInstanceEndsOnTheAimPoint) {
    World w;
    const Scene s = scene(w);
    w.host.hit = TraceHit{{0.0f, -2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 48.0f};
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.host.calls, 0);
    EXPECT_EQ(w.phasers[0].target, (Vec3{0.0, 50.0, 0.0}));
}

TEST(BeamFeed, UTilesIsAtLeastOne) {
    World w;
    const Scene s = scene(w);
    w.m.set_f(s.bank, Field::_length_texture_tile_per_unit, 0.0);
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.phasers[0].u_tiles, 1.0);
    w.m.set_f(s.bank, Field::_length_texture_tile_per_unit, 0.001);
    w.run({s.ship});
    EXPECT_EQ(w.phasers[0].u_tiles, 1.0);  // max(1.0, 0.05)
    w.m.set_f(s.bank, Field::_length_texture_tile_per_unit, kNan);
    w.run({s.ship});
    EXPECT_EQ(w.phasers[0].u_tiles, 1.0);  // NaN > 0 is False
    // A tiny length (no aim unit): the target point, max(1.0, ~0).
    w.m.set_f(s.bank, Field::_length_texture_tile_per_unit, 2.0);
    const auto* row = w.m.object(s.target);
    w.store.set_position(static_cast<uint32_t>(row->xform_index),
                         static_cast<uint32_t>(row->xform_gen), 0.0, 1e-7, 0.0);
    w.run({s.ship});
    ASSERT_EQ(w.phasers.size(), 2u);
    EXPECT_EQ(w.phasers[0].u_tiles, 1.0);
    EXPECT_EQ(w.phasers[0].target, (Vec3{0.0, 1e-7, 0.0}));
}

TEST(BeamFeed, MissingFrameEntryThrows) {
    World w;
    const Scene s = scene(w);
    const int64_t unlisted = w.m.register_row(Kind::Set);  // no ctx.frames
    w.m.set_ref(s.ship, Field::_containing_set, unlisted);
    w.m.set_ref(s.target, Field::_containing_set, unlisted);
    EXPECT_THROW(w.run({s.ship}), std::invalid_argument);
}

TEST(BeamFeed, UnsetColourThrows) {
    World w;
    const Scene s = scene(w);
    w.m.set_fv(s.bank, Field::_inner_core_color, {});
    EXPECT_THROW(w.run({s.ship}), std::invalid_argument);
    w.m.set_fv(s.bank, Field::_inner_core_color, {0.2, 0.4, 0.6, 1.0});
    w.m.set_fv(s.bank, Field::_outer_shell_color, {});
    EXPECT_THROW(w.run({s.ship}), std::invalid_argument);
}

TEST(BeamFeed, NoRowShipThrows) {
    World w;
    const Scene s = scene(w);
    EXPECT_THROW(w.run({s.ship, -1}), std::invalid_argument);
}
