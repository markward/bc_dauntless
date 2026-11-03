// The native sensor-detection kernel (sensor_detect.h) on hand-built mirror
// rows: each case pins one gate of engine/appc/sensor_detection.py /
// sensor_occlusion.py in its Python order. The differential native-vs-Python
// checks run from Python (Task 6/7); these fail fast in C++ alone.
//
// Expected values computed here must round as the Python does: no
// contraction into fused multiply-adds (the library sources get the same).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

// A hand-built world: rows written the way engine/appc/native_combat.py
// writes them, globals at their Python values.
struct World {
    TransformStore store;
    Mirror m{store};
    int64_t next_id = 100;

    World() {
        m.set_global_f(Global::sensorless_range_gu, 2000.0);
        m.set_global_f(Global::cloak_bubble_cap_gu, 30.0);
        m.set_global_f(Global::overboost_threshold, 1.2);
        m.set_global_f(Global::min_blocker_radius_gu, 2.0);
        m.set_global_f(Global::conceal_cap, 0.19);
        m.set_global_i(Global::dev_mode, 0);
        m.set_global_i(Global::occ_enabled, 1);
        m.set_global_i(Global::enhanced_sensor_contest, 1);
        m.set_global_f(Global::CONCEAL_K, 0.9);
        m.set_global_f(Global::LOCK_BREAK_T, 0.28);
        m.set_global_f(Global::HYSTERESIS, 0.08);
        m.set_global_f(Global::PROFILE_CONCEALMENT_CAP, 0.28 - 0.08 - 0.01);
        m.set_global_f(Global::CLOAK_RANGE_FACTOR, 0.005);
        m.set_global_f(Global::CLOAK_DETECTION_BASE_GU, 5.0);
    }

    // A DamageableObject-like row (no sensor getter): a planet, a nebula.
    int64_t object(double x, double y, double z) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_f(h, Field::_life_time, 1.0e30);
        return h;
    }

    // A ShipClass row with a SensorSubsystem of BaseSensorRange `range`.
    int64_t ship(double x, double y, double z, double range = 100.0) {
        int64_t h = object(x, y, z);
        m.set_i(h, Field::has_sensor_getter, 1);
        m.set_i(h, Field::has_cloak_getter, 1);
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::has_parent_ship_getter, 1);
        m.set_f(s, Field::_condition, 1.0);
        m.set_f(s, Field::_max_condition, 1.0);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        m.set_f(s, Field::_power_factor, 1.0);
        m.set_f(s, Field::_base_sensor_range, range);
        m.set_ref(s, Field::_parent_ship, h);
        m.set_ref(h, Field::_sensor_subsystem, s);
        return h;
    }

    int64_t sensor(int64_t ship) {
        return m.get_ref(ship, Field::_sensor_subsystem);
    }

    int64_t rock(double x, double y, double z, double radius) {
        int64_t h = ship(x, y, z);
        m.set_i(h, Field::is_rock, 1);
        m.set_f(h, Field::o_radius, radius);
        return h;
    }

    void cloak(int64_t ship, int64_t state) {
        int64_t c = m.register_row(Kind::Subsystem);
        m.set_i(c, Field::_cloak_state, state);
        m.set_ref(ship, Field::_cloaking_subsystem, c);
    }

    int64_t nebula(std::vector<Sphere> spheres) {
        int64_t h = object(0.0, 0.0, 0.0);
        m.set_i(h, Field::is_meta_nebula, 1);
        m.set_fv(h, Field::_fbm, {0.02, 1.5, 0.30});
        m.set_spheres(h, std::move(spheres));
        return h;
    }

    int64_t set(const std::vector<int64_t>& ships,
                const std::vector<int64_t>& nebulae = {}) {
        int64_t s = m.register_row(Kind::Set);
        m.set_ids(s, Field::ships, ships);
        m.set_ids(s, Field::nebulae, nebulae);
        for (int64_t o : ships) m.set_ref(o, Field::_containing_set, s);
        for (int64_t o : nebulae) m.set_ref(o, Field::_containing_set, s);
        return s;
    }

    void move(int64_t h, double x, double y, double z) {
        store.set_position(static_cast<uint32_t>(m.get_i(h, Field::xform_index)),
                           static_cast<uint32_t>(m.get_i(h, Field::xform_gen)),
                           x, y, z);
    }

    bool detect(int64_t o, int64_t t, double now = 1.0,
                std::optional<double> conceal = std::nullopt) {
        return can_detect(m, o, t, now, false, std::nullopt, true, conceal);
    }
};

}  // namespace

TEST(SensorDetect, OfflineSensorsRangeZero) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t s = w.sensor(o);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0);
    // condition / max scales the range; power multiplies it.
    w.m.set_f(s, Field::_condition, 0.5);
    w.m.set_f(s, Field::_power_factor, 0.5);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0 * 0.5 * 0.5);
    // IsDisabled: condition <= DisabledPercentage * _max_condition.
    w.m.set_f(s, Field::_condition, 0.25);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_f(s, Field::_condition, 1.0);
    w.m.set_f(s, Field::_power_factor, 1.0);
    // IsDestroyed: the flag.
    w.m.set_i(s, Field::_destroyed, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(s, Field::_destroyed, 0);
    // Radiation on the sensor itself, then on its parent system.
    w.m.set_i(s, Field::_radiation_out, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(s, Field::_radiation_out, 0);
    int64_t parent = w.m.register_row(Kind::Subsystem);
    w.m.set_ref(s, Field::_parent_subsystem, parent);
    w.m.set_i(parent, Field::_radiation_out, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(parent, Field::_radiation_out, 0);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0);
    // The parent ship out of action: dying, a finite life time, dead.
    w.m.set_i(o, Field::_dying, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(o, Field::_dying, 0);
    w.m.set_f(o, Field::_life_time, 5.0);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_f(o, Field::_life_time, 1.0e30);
    w.m.set_i(o, Field::_dead, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(o, Field::_dead, 0);
    // A child with no _parent_ship climbs to its system's ship.
    w.m.set_ref(s, Field::_parent_ship, -1);
    w.m.set_ref(parent, Field::_parent_ship, o);
    w.m.set_i(o, Field::_dead, 1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 0.0);
    w.m.set_i(o, Field::_dead, 0);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0);
    // An offline observer detects nothing, however close.
    int64_t t = w.ship(1, 0, 0);
    w.set({o, t});
    w.m.set_i(s, Field::_destroyed, 1);
    EXPECT_FALSE(w.detect(o, t));
}

TEST(SensorDetect, ConditionUsesPropertyMaxCondition) {
    // GetConditionPercentage reads the shared template's max; IsDisabled
    // reads _max_condition (CDM §9.9).
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t s = w.sensor(o);
    int64_t p = w.m.register_row(Kind::Property);
    w.m.set_ref(s, Field::_property, p);
    w.m.set_f(s, Field::_condition, 50.0);
    w.m.set_f(s, Field::_max_condition, 100.0);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0 * (50.0 / 100.0));
    w.m.set_i(p, Field::MaxCondition_set, 1);
    w.m.set_f(p, Field::MaxCondition, 400.0);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0 * (50.0 / 400.0));
    w.m.set_f(p, Field::MaxCondition, 0.0);  // not > 0: _max_condition
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0 * 0.5);
    // A NaN condition: min(1.0, NaN) is 1.0.
    w.m.set_f(p, Field::MaxCondition, 400.0);
    w.m.set_f(s, Field::_condition, kNaN);
    EXPECT_EQ(effective_sensor_range(w.m, o), 100.0);
}

TEST(SensorDetect, SensorlessObserverUsesDial) {
    World w;
    int64_t planet = w.object(0, 0, 0);  // no GetSensorSubsystem
    EXPECT_EQ(effective_sensor_range(w.m, planet), 2000.0);
    int64_t o = w.ship(0, 0, 0, 100.0);
    w.m.set_ref(o, Field::_sensor_subsystem, -1);  // None
    EXPECT_EQ(effective_sensor_range(w.m, o), 2000.0);
    int64_t o2 = w.ship(0, 0, 0, 0.0);              // base <= 0.0
    EXPECT_EQ(effective_sensor_range(w.m, o2), 2000.0);
    w.m.set_global_f(Global::sensorless_range_gu, 1234.5);
    EXPECT_EQ(effective_sensor_range(w.m, o2), 1234.5);
    // A NaN base is not <= 0.0: it reaches the multiply.
    w.m.set_f(w.sensor(o2), Field::_base_sensor_range, kNaN);
    EXPECT_TRUE(std::isnan(effective_sensor_range(w.m, o2)));
}

TEST(SensorDetect, CloakedTargetBubbleUsesPyMin) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(9.5, 0, 0);
    w.set({o, t});
    EXPECT_FALSE(is_hidden_by_cloak(w.m, t));
    w.cloak(t, 1);  // CLOAKING: still fully visible
    EXPECT_FALSE(is_hidden_by_cloak(w.m, t));
    EXPECT_TRUE(w.detect(o, t));
    w.cloak(t, 2);  // CLOAKED
    EXPECT_TRUE(is_hidden_by_cloak(w.m, t));
    // bubble = min(cap, 5.0 + 1000 * 0.005) = 10.0
    EXPECT_TRUE(w.detect(o, t));
    w.move(t, 10.5, 0, 0);
    EXPECT_FALSE(w.detect(o, t));
    // The cap wins once the percentage term passes it.
    w.m.set_f(w.sensor(o), Field::_base_sensor_range, 100000.0);
    w.move(t, 29.9, 0, 0);
    EXPECT_TRUE(w.detect(o, t));
    w.move(t, 30.1, 0, 0);
    EXPECT_FALSE(w.detect(o, t));
    // NaN range: min(cap, NaN) is the cap (Python's min keeps its first).
    w.m.set_f(w.sensor(o), Field::_base_sensor_range, kNaN);
    w.move(t, 29.9, 0, 0);
    EXPECT_TRUE(w.detect(o, t));
    // With the contest off a cloaked target is never detected.
    w.m.set_global_i(Global::enhanced_sensor_contest, 0);
    EXPECT_FALSE(w.detect(o, t));
    // A target with no cloak getter is never cloaked.
    int64_t planet = w.object(1, 0, 0);
    EXPECT_FALSE(is_hidden_by_cloak(w.m, planet));
}

TEST(SensorDetect, ZeroRangeWritesNoLatch) {
    World w;
    int64_t o = w.ship(0, 0, 0);
    int64_t t = w.ship(1, 0, 0);
    w.set({o, t});
    w.m.set_i(w.sensor(o), Field::_destroyed, 1);
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_FALSE(latched(w.m, o, t));
    w.m.set_i(w.sensor(o), Field::_destroyed, 0);
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_TRUE(latched(w.m, o, t));
}

TEST(SensorDetect, OcclusionReturnsBeforeLatch) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(100, 0, 0);
    int64_t r = w.rock(50, 0, 0, 5.0);
    w.set({o, t, r});
    EXPECT_TRUE(occ_blocked(w.m, o, t, 1.0));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_FALSE(latched(w.m, o, t));
    // Occlusion off (dev toggle): the nebula gate is reached and latches.
    w.m.set_global_i(Global::occ_enabled, 0);
    EXPECT_FALSE(occ_blocked(w.m, o, t, 1.0));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_TRUE(latched(w.m, o, t));
}

TEST(SensorDetect, LatchHysteresisBand) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(1, 0, 0);
    w.set({o, t});
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.25));   // below LOCK_BREAK_T: no latch
    EXPECT_FALSE(latched(w.m, o, t));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.28));  // >= LOCK_BREAK_T breaks
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.25));  // latched: needs < 0.2
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.2));   // 0.28 - 0.08 == 0.2 exactly
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.19));   // releases
    EXPECT_FALSE(latched(w.m, o, t));
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.25));
    // NaN concealment: `conceal >= thresh` is False, so it unlatches.
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_FALSE(w.detect(o, t, 1.0, kNaN));  // NaN range: dist <= NaN False
    EXPECT_FALSE(latched(w.m, o, t));
    // Concealment shrinks the range: r * (1.0 - 0.9 * conceal).
    w.move(t, 1000.0 * (1.0 - 0.9 * 0.1) - 0.001, 0, 0);
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.1));
    w.move(t, 1000.0 * (1.0 - 0.9 * 0.1) + 0.001, 0, 0);
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.1));
    // latch_reset clears every pair.
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    latch_reset(w.m);
    EXPECT_FALSE(latched(w.m, o, t));
}

TEST(SensorDetect, ApplyConcealmentFalseSkipsTheNebulaGate) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(1, 0, 0);
    w.set({o, t});
    EXPECT_TRUE(can_detect(w.m, o, t, 1.0, false, std::nullopt, false, 0.9));
    EXPECT_FALSE(latched(w.m, o, t));
    // A caller-supplied squared distance replaces the positions.
    EXPECT_FALSE(
        can_detect(w.m, o, t, 1.0, false, 1000.0 * 1000.0 + 1.0, false));
    EXPECT_TRUE(can_detect(w.m, o, t, 1.0, false, 1000.0 * 1000.0, false));
}

TEST(SensorDetect, ProfileTermClippedByCap) {
    World w;
    const double fc = 0.392642591908;
    // A point where math.dist and a naive sqrt differ by one ulp (checked in
    // CPython 3.11.15), so the profile radius must come from dist3.
    const double tx = -30.9, ty = -253.4, tz = 43.8;
    int64_t t = w.ship(tx, ty, tz);
    int64_t s = w.set({t});
    int64_t p = w.m.register_row(Kind::Profile);
    // Unmapped: local only (no nebula: 0.0).
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.0);
    // sensors 1.0 everywhere: 0.3926... clipped to the 0.19 cap.
    w.m.set_profile_rows(p, {{0.0, 1.0}}, fc);
    w.m.set_frame(s, p, {100.0, 0.0, 0.0}, {0.0, 0.0, 0.0});
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.28 - 0.08 - 0.01);
    // Under --developer the conceal_cap dial is the cap.
    w.m.set_global_i(Global::dev_mode, 1);
    w.m.set_global_f(Global::conceal_cap, 0.25);
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.25);
    w.m.set_global_i(Global::dev_mode, 0);
    // Below the cap: the term itself, sensors(r) * full_concealment, with r
    // from math.dist (dist3) of the anchored position to the star.
    w.m.set_profile_rows(p, {{0.0, 0.0}, {1000.0, 1.0}}, fc);
    const double pos[3] = {tx + 100.0, ty + 0.0, tz + 0.0};
    const double star[3] = {0.0, 0.0, 0.0};
    const double r = dist3(pos, star);
    const double term = (0.0 + (1.0 - 0.0) * ((r - 0.0) / 1000.0)) * fc;
    const double naive = std::sqrt(pos[0] * pos[0] + pos[1] * pos[1] +
                                   pos[2] * pos[2]);
    ASSERT_NE((0.0 + (1.0 - 0.0) * ((naive - 0.0) / 1000.0)) * fc, term);
    EXPECT_EQ(concealment_at(w.m, t, 1.0), term);
    // A denser local nebula wins the max.
    int64_t neb = w.nebula({{10.0, 20.0, 30.0, 500.0}});
    w.m.set_ids(s, Field::nebulae, {neb});
    const double seed[3] = {10.0 * 0.013 + 11.7, 20.0 * 0.013 + 23.1,
                            30.0 * 0.013 + 47.3};
    const Sphere sp[1] = {{10.0, 20.0, 30.0, 500.0}};
    const double local =
        density(tx, ty, tz, sp, 1, seed, 0.02, 1.5, 0.30, 7.0 * 0.01);
    ASSERT_GT(local, term);
    EXPECT_EQ(concealment_at(w.m, t, 7.0), local);
    // A seed GetSeed already cached is used instead of the derived one.
    w.m.set_fv(neb, Field::_seed, {1.0, 2.0, 3.0});
    const double seed2[3] = {1.0, 2.0, 3.0};
    EXPECT_EQ(concealment_at(w.m, t, 7.0),
              py_max(density(tx, ty, tz, sp, 1, seed2, 0.02, 1.5, 0.30,
                             7.0 * 0.01),
                     term));
    // A plain (non-Meta) nebula is skipped by MetaNebula_Cast.
    w.m.set_i(neb, Field::is_meta_nebula, 0);
    EXPECT_EQ(concealment_at(w.m, t, 7.0), term);
    // NaN term: min(NaN, cap) is NaN, max(local, NaN) keeps local.
    w.m.set_profile_rows(p, {{0.0, kNaN}}, fc);
    EXPECT_EQ(concealment_at(w.m, t, 7.0), 0.0);
}

TEST(SensorDetect, BeyondRangeNeedsBoostKnownAndNotJammed) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(500, 0, 0);
    int64_t s = w.set({o, t});
    int64_t os = w.sensor(o);
    EXPECT_FALSE(w.detect(o, t));
    EXPECT_FALSE(in_reach(w.m, o, t));
    // Known (BC's sensor memory): IsObjectKnown by obj_id.
    w.m.set_ids(os, Field::_known_objects, {w.m.get_i(t, Field::obj_id)});
    EXPECT_TRUE(w.detect(o, t));
    EXPECT_TRUE(in_reach(w.m, o, t));
    w.m.set_ids(os, Field::_known_objects, {});
    // Over-boost: strictly above the threshold.
    w.m.set_f(os, Field::_power_factor, 1.2);
    EXPECT_FALSE(w.detect(o, t));
    w.m.set_f(os, Field::_power_factor, 1.3);
    EXPECT_TRUE(w.detect(o, t));
    // Jammed: the observer OR the target inside a MetaNebula of the
    // observer's set (inclusive sphere test).
    int64_t neb = w.nebula({{500.0, 0.0, 0.0, 10.0}});
    w.m.set_ids(s, Field::nebulae, {neb});
    EXPECT_TRUE(jammed(w.m, o, t));
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.0));
    w.m.set_spheres(neb, {{0.0, 0.0, 0.0, 0.0}});  // observer ON the surface
    EXPECT_TRUE(jammed(w.m, o, t));
    w.m.set_spheres(neb, {{1000.0, 0.0, 0.0, 10.0}});
    EXPECT_FALSE(jammed(w.m, o, t));
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.0));
    // A fully cloaked target gets no beyond-range way in.
    w.cloak(t, 2);
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.0));
    EXPECT_FALSE(in_reach(w.m, o, t));
    w.m.set_ref(t, Field::_cloaking_subsystem, -1);
    // Another set: no way in.
    int64_t other = w.ship(500, 0, 0);
    w.set({other});
    EXPECT_FALSE(w.detect(o, other, 1.0, 0.0));
    EXPECT_FALSE(jammed(w.m, other, o));  // no nebulae in other's set
}

TEST(SensorDetect, ProbeWalkOneLevel) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(1000, 0, 0);
    int64_t probe = w.ship(950, 0, 0, 100.0);
    int64_t far_probe = w.ship(500, 0, 0, 100.0);
    int64_t s = w.set({o, t, probe, far_probe});
    auto id = [&](int64_t h) { return w.m.get_i(h, Field::obj_id); };
    EXPECT_FALSE(w.detect(o, t));
    // An id that resolves to no registered object is skipped.
    w.m.set_ids(w.sensor(o), Field::_probe_ids, {987654, id(probe)});
    EXPECT_TRUE(w.detect(o, t));
    EXPECT_TRUE(in_reach(w.m, o, t));
    // The probe obeys the caller's concealment: it latches its OWN pair.
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_TRUE(latched(w.m, probe, t));
    latch_reset(w.m);
    // One level only: the far probe's own probe is not walked.
    w.m.set_ids(w.sensor(o), Field::_probe_ids, {id(far_probe)});
    w.m.set_ids(w.sensor(far_probe), Field::_probe_ids, {id(probe)});
    EXPECT_TRUE(w.detect(far_probe, t));  // its own walk reaches
    EXPECT_FALSE(w.detect(o, t));
    EXPECT_FALSE(in_reach(w.m, o, t));
    // A probe in another set is skipped.
    w.m.set_ids(w.sensor(o), Field::_probe_ids, {id(probe)});
    int64_t s2 = w.set({probe});
    w.m.set_ids(s, Field::ships, {o, t, far_probe});
    EXPECT_FALSE(w.detect(o, t));
    (void)s2;
    // A rock on the observer's line falls through to the probe walk.
    w.m.set_ref(probe, Field::_containing_set, s);
    int64_t r = w.rock(300, 0, 0, 5.0);
    w.m.set_ids(s, Field::ships, {o, t, far_probe, probe, r});
    w.m.set_ref(r, Field::_containing_set, s);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 2.0));
    EXPECT_TRUE(w.detect(o, t, 2.0));
}

TEST(SensorDetect, MemoOnlyWhenRequested) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(50, 0, 0);
    w.set({o, t});
    EXPECT_TRUE(can_detect(w.m, o, t, 1.0, true));
    w.move(t, 500, 0, 0);
    EXPECT_TRUE(can_detect(w.m, o, t, 1.0, true));    // the memo answers
    EXPECT_FALSE(can_detect(w.m, o, t, 1.0, false));  // not asked: computed
    // Any optional argument bypasses the memo.
    EXPECT_FALSE(can_detect(w.m, o, t, 1.0, true, std::nullopt, true, 0.0));
    EXPECT_FALSE(can_detect(w.m, o, t, 1.0, true, 250000.0 + 1.0));
    EXPECT_FALSE(can_detect(w.m, o, t, 1.0, true, std::nullopt, false));
    // A memo lookup with no stored answer stores this one.
    EXPECT_FALSE(can_detect(w.m, t, o, 1.0, true));
    w.move(t, 50, 0, 0);
    EXPECT_FALSE(can_detect(w.m, t, o, 1.0, true));
    memo_clear(w.m);
    EXPECT_TRUE(can_detect(w.m, o, t, 1.0, true));
    EXPECT_TRUE(can_detect(w.m, t, o, 1.0, true));
}

TEST(SensorDetect, OcclusionCacheFrozenWithinOneGameTime) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(100, 0, 0);
    int64_t r = w.rock(50, 0, 0, 5.0);
    int64_t s = w.set({o, t, r});
    EXPECT_TRUE(occ_blocked(w.m, o, t, 1.0));
    EXPECT_FALSE(w.detect(o, t, 1.0));
    // The rock moves off the line: the same game time keeps the answer.
    w.move(r, 50, 100, 0);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 1.0));
    // A new pair at the same time sees the FROZEN rock position.
    EXPECT_TRUE(occ_blocked(w.m, t, o, 1.0));
    // A non-rock joining the set rebuilds the rock list (len(ships)), but
    // the pair cache key (now, tick, len(rocks)) is unchanged: still cached.
    int64_t extra = w.ship(0, 500, 0);
    w.m.set_ids(s, Field::ships, {o, t, r, extra});
    w.m.set_ref(extra, Field::_containing_set, s);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 1.0));
    EXPECT_FALSE(occ_blocked(w.m, o, extra, 1.0));  // rebuilt list: off line
    // A new game time recomputes.
    EXPECT_FALSE(occ_blocked(w.m, o, t, 2.0));
    EXPECT_TRUE(w.detect(o, t, 2.0));
    // begin_tick folds the sensor manager's tick time into both keys.
    w.move(r, 50, 0, 0);
    EXPECT_FALSE(occ_blocked(w.m, o, t, 2.0));
    occ_begin_tick(w.m, 2.0);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 2.0));
    // occ_reset drops the caches.
    w.move(r, 50, 100, 0);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 2.0));
    occ_reset(w.m);
    EXPECT_FALSE(occ_blocked(w.m, o, t, 2.0));
}

TEST(SensorDetect, OcclusionRockRulesFollowPython) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(100, 0, 0);
    int64_t r = w.rock(50, 0, 0, 1.5);
    w.set({o, t, r});
    // Below min_blocker_radius_gu: not a major rock.
    EXPECT_FALSE(occ_blocked(w.m, o, t, 1.0));
    // effective_radius: base x scale.
    w.m.set_f(r, Field::_scale, 2.0);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 2.0));
    // base <= 0: the hull's radius; no hull: 0.0.
    w.m.set_f(r, Field::o_radius, 0.0);
    EXPECT_FALSE(occ_blocked(w.m, o, t, 3.0));
    int64_t hull = w.m.register_row(Kind::Subsystem);
    w.m.set_f(hull, Field::s_radius, 3.0);
    w.m.set_ref(r, Field::_hull, hull);
    EXPECT_TRUE(occ_blocked(w.m, o, t, 4.0));
    // A ship inside the rock's sphere is beside it, not behind it.
    w.move(o, 49, 0, 0);
    EXPECT_FALSE(occ_blocked(w.m, o, t, 5.0));
    w.move(o, 0, 0, 0);
    // The rock never occludes itself.
    EXPECT_FALSE(occ_blocked(w.m, o, r, 6.0));
    // An observer in no set is never blocked.
    int64_t loose = w.ship(0, 0, 0);
    EXPECT_FALSE(occ_blocked(w.m, loose, t, 6.0));
}

TEST(SensorDetect, UnrepresentableRefsFallBack) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(10, 0, 0);
    int64_t s = w.set({o, t});
    // -2 is never read as None.
    w.m.set_ref(o, Field::_sensor_subsystem, kRefUnrepresentable);
    EXPECT_THROW(effective_sensor_range(w.m, o), std::invalid_argument);
    EXPECT_THROW(w.detect(o, t), std::invalid_argument);
    w.m.set_ref(o, Field::_sensor_subsystem, -1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 2000.0);
    w.m.set_ref(t, Field::_cloaking_subsystem, kRefUnrepresentable);
    EXPECT_THROW(is_hidden_by_cloak(w.m, t), std::invalid_argument);
    w.m.set_ref(t, Field::_cloaking_subsystem, -1);
    // A -2 or freed entry in a set list is reached by the rock walk.
    w.m.set_ids(s, Field::ships, {o, t, kRefUnrepresentable});
    EXPECT_THROW(occ_blocked(w.m, o, t, 1.0), std::invalid_argument);
    int64_t gone = w.ship(0, 0, 0);
    w.m.unregister_row(gone);
    w.m.set_ids(s, Field::ships, {o, t, gone});
    EXPECT_THROW(occ_blocked(w.m, o, t, 2.0), std::invalid_argument);
    w.m.set_ids(s, Field::ships, {o, t});
    EXPECT_FALSE(occ_blocked(w.m, o, t, 3.0));
    // ...and the nebula walk.
    w.m.set_ids(s, Field::nebulae, {kRefUnrepresentable});
    EXPECT_THROW(concealment_at(w.m, t, 1.0), std::invalid_argument);
    EXPECT_THROW(jammed(w.m, o, t), std::invalid_argument);
    // A plain Nebula would answer IsObjectInNebula with a stub: Python.
    int64_t plain = w.object(0, 0, 0);
    w.m.set_ids(s, Field::nebulae, {plain});
    EXPECT_THROW(jammed(w.m, o, t), std::invalid_argument);
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.0);  // MetaNebula_Cast skips it
    w.m.set_ids(s, Field::nebulae, {});
    // A set whose frame could not be resolved.
    w.m.set_frame(s, kRefUnrepresentable, {0, 0, 0}, {0, 0, 0});
    EXPECT_THROW(concealment_at(w.m, t, 1.0), std::invalid_argument);
    w.m.set_frame(s, -1, {0, 0, 0}, {0, 0, 0});
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.0);
    // An object in an unrepresentable set.
    w.m.set_ref(t, Field::_containing_set, kRefUnrepresentable);
    EXPECT_THROW(concealment_at(w.m, t, 1.0), std::invalid_argument);
    w.m.set_ref(t, Field::_containing_set, -1);
    EXPECT_EQ(concealment_at(w.m, t, 1.0), 0.0);
    // A parent ship the mirror cannot prove has IsDying/IsDead.
    int64_t planet = w.object(0, 0, 0);
    w.m.set_ref(o, Field::_sensor_subsystem, w.m.register_row(Kind::Subsystem));
    int64_t sub = w.m.get_ref(o, Field::_sensor_subsystem);
    w.m.set_i(sub, Field::has_parent_ship_getter, 1);
    w.m.set_f(sub, Field::_condition, 1.0);
    w.m.set_f(sub, Field::_max_condition, 1.0);
    w.m.set_f(sub, Field::_base_sensor_range, 10.0);
    w.m.set_f(sub, Field::_power_factor, 1.0);
    w.m.set_ref(sub, Field::_parent_ship, planet);
    EXPECT_THROW(effective_sensor_range(w.m, o), std::invalid_argument);
    w.m.set_ref(sub, Field::_property, kRefUnrepresentable);
    w.m.set_ref(sub, Field::_parent_ship, o);
    EXPECT_THROW(effective_sensor_range(w.m, o), std::invalid_argument);
    w.m.set_ref(sub, Field::_property, -1);
    EXPECT_EQ(effective_sensor_range(w.m, o), 10.0);
    // A transform freed under a live row.
    w.store.free(static_cast<uint32_t>(w.m.get_i(t, Field::xform_index)),
                 static_cast<uint32_t>(w.m.get_i(t, Field::xform_gen)));
    EXPECT_THROW(w.detect(o, t), std::invalid_argument);
}

TEST(SensorDetect, UnregisterDropsLatchAndMemo) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(10, 0, 0);
    int64_t u = w.ship(20, 0, 0);
    int64_t s = w.set({o, t, u});
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.5));
    EXPECT_FALSE(w.detect(o, u, 1.0, 0.5));
    EXPECT_TRUE(can_detect(w.m, t, u, 1.0, true));
    EXPECT_EQ(w.m.sensor_state().latch.size(), 2u);
    EXPECT_EQ(w.m.sensor_state().memo.size(), 1u);
    w.m.unregister_row(t);
    EXPECT_EQ(w.m.sensor_state().latch.size(), 1u);
    EXPECT_TRUE(latched(w.m, o, u));
    EXPECT_TRUE(w.m.sensor_state().memo.empty());
    // An unregistered set drops its occlusion caches (WeakKeyDictionary).
    EXPECT_EQ(w.m.sensor_state().rock_cache.count(s), 1u);
    w.m.unregister_row(s);
    EXPECT_EQ(w.m.sensor_state().rock_cache.count(s), 0u);
    // clear() resets every piece of native-owned state.
    occ_begin_tick(w.m, 3.0);
    w.m.clear();
    EXPECT_TRUE(w.m.sensor_state().latch.empty());
    EXPECT_FALSE(w.m.sensor_state().tick_time_set);
    EXPECT_TRUE(w.m.sensor_state().rock_cache.empty());
    EXPECT_TRUE(w.m.sensor_state().pair_cache.empty());
    EXPECT_FALSE(w.m.sensor_state().walking_probes);
}

TEST(SensorDetect, ProbeGuardResetOnThrow) {
    World w;
    int64_t o = w.ship(0, 0, 0, 100.0);
    int64_t t = w.ship(1000, 0, 0);
    int64_t probe = w.ship(950, 0, 0, 100.0);
    w.set({o, t, probe});
    w.m.set_ids(w.sensor(o), Field::_probe_ids,
                {w.m.get_i(probe, Field::obj_id)});
    w.m.set_ref(probe, Field::_sensor_subsystem, kRefUnrepresentable);
    EXPECT_THROW(w.detect(o, t), std::invalid_argument);
    EXPECT_FALSE(w.m.sensor_state().walking_probes);
}

// Task 6, ruling R7: ONE latch. Python's _set_latched writes the native
// latch for a registered pair, and the kernel reads what it wrote.
TEST(SensorDetect, SetLatchedIsTheOneLatch) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(1, 0, 0);
    int64_t gone = w.ship(2, 0, 0);
    w.set({o, t, gone});
    set_latched(w.m, o, t, true);
    EXPECT_TRUE(latched(w.m, o, t));
    EXPECT_FALSE(latched(w.m, t, o));           // per ordered pair
    EXPECT_FALSE(w.detect(o, t, 1.0, 0.25));    // in the band, latched
    set_latched(w.m, o, t, false);
    EXPECT_FALSE(latched(w.m, o, t));
    EXPECT_TRUE(w.detect(o, t, 1.0, 0.25));     // in the band, fresh
    set_latched(w.m, o, t, false);              // clearing twice: no-op
    EXPECT_FALSE(latched(w.m, o, t));
    // A stale handle writes nothing and falls back to the Python latch.
    w.m.unregister_row(gone);
    EXPECT_THROW(set_latched(w.m, o, gone, true), std::invalid_argument);
    EXPECT_THROW(set_latched(w.m, gone, o, true), std::invalid_argument);
    EXPECT_EQ(w.m.sensor_state().latch.size(), 0u);
    // ...and the read agrees: the pair is not native's.
    EXPECT_THROW(latched(w.m, o, gone), std::invalid_argument);
    EXPECT_THROW(latched(w.m, gone, o), std::invalid_argument);
}

// Task 6: the occlusion cache's clock (sensor_occlusion._now, the Utopia
// game time) is not the nebula drift clock (sensor_detection._game_time).
// can_detect takes both; occ_now absent means `now` (Task 5's callers).
TEST(SensorDetect, OcclusionClockIsSeparateFromTheDriftClock) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t t = w.ship(100, 0, 0);
    int64_t r = w.rock(50, 0, 0, 5.0);
    w.set({o, t, r});
    EXPECT_FALSE(can_detect(w.m, o, t, 0.0, false, std::nullopt, true,
                            std::nullopt, 2.0));
    w.move(r, 50, 100, 0);
    // The same occlusion clock keeps the cached "blocked", whatever `now`.
    EXPECT_FALSE(can_detect(w.m, o, t, 7.0, false, std::nullopt, true,
                            std::nullopt, 2.0));
    // A new occlusion clock recomputes, though `now` is unchanged.
    EXPECT_TRUE(can_detect(w.m, o, t, 7.0, false, std::nullopt, true,
                           std::nullopt, 3.0));
    // Absent, the occlusion clock is `now`.
    w.move(r, 50, 0, 0);
    EXPECT_TRUE(can_detect(w.m, o, t, 3.0, false));     // cached at 3.0
    EXPECT_FALSE(can_detect(w.m, o, t, 4.0, false));
}

// Task 6 fix round 1: the audit snapshots and restores every latch pair
// whose TARGET is the asked target (a native run, probes included, writes
// no other pair); a dropped row hands its pairs to the Python first.
TEST(SensorDetect, LatchSnapshotRestoreAndPairsOf) {
    World w;
    int64_t o = w.ship(0, 0, 0, 1000.0);
    int64_t p = w.ship(5, 0, 0, 1000.0);
    int64_t t = w.ship(1, 0, 0);
    int64_t u = w.ship(2, 0, 0);
    w.set({o, p, t, u});
    set_latched(w.m, p, t, true);
    set_latched(w.m, o, u, true);
    set_latched(w.m, t, u, true);
    EXPECT_EQ(latch_snapshot(w.m, t), (std::vector<int64_t>{p}));
    EXPECT_EQ(latch_snapshot(w.m, o), (std::vector<int64_t>{}));
    // A native run rewrites target t's pairs; the restore puts them back,
    // leaving every other target's pairs alone.
    const std::vector<int64_t> snap = latch_snapshot(w.m, t);
    set_latched(w.m, p, t, false);
    set_latched(w.m, o, t, true);
    latch_restore(w.m, t, snap);
    EXPECT_TRUE(latched(w.m, p, t));
    EXPECT_FALSE(latched(w.m, o, t));
    EXPECT_TRUE(latched(w.m, o, u));
    EXPECT_TRUE(latched(w.m, t, u));
    // Every pair a handle is in, either side, sorted.
    using P = std::pair<int64_t, int64_t>;
    std::vector<P> want{{p, t}, {t, u}};
    std::sort(want.begin(), want.end());
    EXPECT_EQ(latch_pairs_of(w.m, t), want);
    EXPECT_EQ(latch_pairs_of(w.m, o), (std::vector<P>{{o, u}}));
}
