// The native fire gates (fire_gates.h) on hand-built mirror rows: exact
// boundaries and the fallbacks. The native-vs-Python differential runs from
// tests/unit/test_native_fire_gates.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t ship = -1, system = -1, bank = -1, tube = -1, tsys = -1, ammo = -1;

    World() {
        m.set_global_f(Global::PULSE_COST_SCALE_0, 0.5);
        m.set_global_f(Global::PULSE_COST_SCALE_1, 1.0);
        m.set_global_f(Global::PULSE_COST_SCALE_2, 2.0);
        ship = m.register_row(Kind::Object, -1, -1, 1);
        m.set_i(ship, Field::has_real_is_dead, 1);
        m.set_i(ship, Field::has_sensor_getter, 1);
        m.set_f(ship, Field::_life_time, 1.0e9);

        system = sys_row(1);  // a phaser system
        bank = leaf(system, 5);
        m.set_f(bank, Field::_charge_level, 5.0);
        m.set_f(bank, Field::_max_condition, 100.0);
        m.set_f(bank, Field::_condition, 100.0);
        m.set_f(bank, Field::_min_firing_charge, 1.0);

        tsys = sys_row(4);
        tube = leaf(tsys, 8);
        m.set_i(tube, Field::_num_ready, 1);
        m.set_i(tube, Field::_skew_fire, 0);
        m.set_f(tube, Field::_max_condition, 100.0);
        m.set_f(tube, Field::_condition, 100.0);
        m.set_f(tsys, Field::_last_system_fire_time, 10.0);
        ammo = m.register_row(Kind::Ammo);
        m.set_i(ammo, Field::_unlimited, 1);
        m.set_ids(tsys, Field::_ammo_by_slot, {0, ammo});
    }
    int64_t sys_row(int64_t kind) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::weapon_kind, kind);
        m.set_i(s, Field::_is_on, 1);
        m.set_ref(s, Field::_parent_ship, ship);
        m.set_i(s, Field::has_parent_ship_getter, 1);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        return s;
    }
    int64_t leaf(int64_t parent, int64_t kind) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::weapon_kind, kind);
        m.set_ref(s, Field::_parent_subsystem, parent);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        return s;
    }
};

}  // namespace

TEST(FireGates, BankFiresWhenEverythingIsHealthy) {
    World w;
    const CanFireResult r = can_fire(w.m, w.bank, 0.0);
    EXPECT_TRUE(r.ok);
    EXPECT_FALSE(r.clear_depleted);
}

TEST(FireGates, DepletedLatchIsReportedNotWritten) {
    World w;
    w.m.set_i(w.bank, Field::_depleted, 1);
    w.m.set_f(w.bank, Field::_charge_level, 0.5);  // below MinFiringCharge
    CanFireResult r = can_fire(w.m, w.bank, 0.0);
    EXPECT_FALSE(r.ok);
    EXPECT_FALSE(r.clear_depleted);
    w.m.set_f(w.bank, Field::_charge_level, 1.0);  // == min: restarts
    r = can_fire(w.m, w.bank, 0.0);
    EXPECT_TRUE(r.ok);
    EXPECT_TRUE(r.clear_depleted);
    EXPECT_EQ(w.m.get_i(w.bank, Field::_depleted), 1);  // never written
}

TEST(FireGates, ParentOffRefusesBeforeTheLatch) {
    World w;
    w.m.set_i(w.bank, Field::_depleted, 1);
    w.m.set_i(w.system, Field::_is_on, 0);
    const CanFireResult r = can_fire(w.m, w.bank, 0.0);
    EXPECT_FALSE(r.ok);
    EXPECT_FALSE(r.clear_depleted);
}

TEST(FireGates, StubIsDeadFallsBack) {
    World w;
    w.m.set_i(w.ship, Field::has_real_is_dead, 0);
    EXPECT_THROW(can_fire(w.m, w.bank, 0.0), std::invalid_argument);
    EXPECT_THROW(ship_dead(w.m, w.ship), std::invalid_argument);
    EXPECT_FALSE(ship_dead(w.m, -1));
}

TEST(FireGates, NanConditionReadsAsFullHealth) {
    // GetConditionPercentage: min(1.0, NaN) is 1.0, so a NaN condition clears
    // a threshold that a condition of 0 does not.
    World w;
    w.m.set_f(w.bank, Field::_disabled_percentage, 0.5);
    w.m.set_f(w.bank, Field::_condition, 0.0);
    EXPECT_FALSE(can_fire(w.m, w.bank, 0.0).ok);
    w.m.set_f(w.bank, Field::_condition,
              std::numeric_limits<double>::quiet_NaN());
    EXPECT_TRUE(can_fire(w.m, w.bank, 0.0).ok);
}

TEST(FireGates, TubeStaggerIsExclusiveAndSkewExempt) {
    World w;
    EXPECT_FALSE(can_fire(w.m, w.tube, 10.5).ok);  // 10.5 - 10.0 == 0.5
    EXPECT_TRUE(can_fire(w.m, w.tube, std::nextafter(10.5, 100.0)).ok);
    w.m.set_i(w.tube, Field::_skew_fire, 1);
    EXPECT_TRUE(can_fire(w.m, w.tube, 10.5).ok);
}

TEST(FireGates, TubeAmmoGate) {
    World w;
    w.m.set_i(w.tube, Field::_skew_fire, 1);
    w.m.set_i(w.ammo, Field::_unlimited, 0);
    w.m.set_i(w.ammo, Field::_available, 0);
    EXPECT_FALSE(can_fire(w.m, w.tube, 50.0).ok);
    w.m.set_i(w.ammo, Field::_available, 1);
    EXPECT_TRUE(can_fire(w.m, w.tube, 50.0).ok);
}

TEST(FireGates, TubeNoneAmmoSlotIsNotExhausted) {
    // A slot holding None (-1): GetCurrentAmmoType() is None, and Python's
    // _ammo_exhausted reads that as "no ammo configured" -- never gated.
    World w;
    w.m.set_i(w.tube, Field::_skew_fire, 1);
    w.m.set_ids(w.tsys, Field::_ammo_by_slot, {0, -1});
    const CanFireResult r = can_fire(w.m, w.tube, 50.0);
    EXPECT_TRUE(r.ok);
}

TEST(FireGates, PulseCooldownThenAffordability) {
    World w;
    const int64_t psys = w.sys_row(2);
    const int64_t c = w.leaf(psys, 6);
    w.m.set_f(c, Field::_max_condition, 100.0);
    w.m.set_f(c, Field::_condition, 100.0);
    w.m.set_i(c, Field::_power_setting, 1);
    w.m.set_f(c, Field::_normal_discharge_rate, 1.0);
    const double edge = 1.0 - 1e-9;
    w.m.set_f(c, Field::_charge_level, edge);
    EXPECT_TRUE(can_fire(w.m, c, 0.0).ok);
    w.m.set_f(c, Field::_charge_level, std::nextafter(edge, 0.0));
    EXPECT_FALSE(can_fire(w.m, c, 0.0).ok);
    w.m.set_f(c, Field::_charge_level, 5.0);
    w.m.set_f(c, Field::_cooldown_remaining, 0.1);
    EXPECT_FALSE(can_fire(w.m, c, 0.0).ok);
    w.m.set_i(c, Field::_power_setting, 7);
    w.m.set_f(c, Field::_cooldown_remaining, 0.0);
    EXPECT_THROW(can_fire(w.m, c, 0.0), std::invalid_argument);
}

TEST(FireGates, NonLeafKindFallsBack) {
    World w;
    EXPECT_THROW(can_fire(w.m, w.system, 0.0), std::invalid_argument);
}

TEST(FireGates, WeaponSystemOfflineAggregatesChildren) {
    World w;
    w.m.set_ids(w.system, Field::_children, {w.bank});
    EXPECT_FALSE(weapon_system_offline(w.m, w.system));
    w.m.set_f(w.bank, Field::_condition, 0.0);  // the only child: disabled
    EXPECT_TRUE(weapon_system_offline(w.m, w.system));
    w.m.set_f(w.bank, Field::_condition, 100.0);
    w.m.set_i(w.ship, Field::_dying, 1);
    EXPECT_TRUE(weapon_system_offline(w.m, w.system));
}
