// impulse_fractions (impulse.h) on hand-built mirror rows. The native-vs-
// Python differential runs from tests/unit/test_native_impulse_fractions.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>

#include "dauntless/combat/impulse.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t ship = -1, ies = -1;

    World() {
        ship = m.register_row(Kind::Object, -1, -1, 1);
        m.set_i(ship, Field::has_real_is_dead, 1);
        m.set_i(ship, Field::has_sensor_getter, 1);
        m.set_f(ship, Field::_life_time, 1.0e9);
        ies = sub(true);
        m.set_f(ies, Field::_power_percentage_wanted, 1.0);
    }
    int64_t sub(bool with_ship_getter) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::_is_on, 1);
        m.set_f(s, Field::_max_condition, 100.0);
        m.set_f(s, Field::_condition, 100.0);
        if (with_ship_getter) {
            m.set_i(s, Field::has_parent_ship_getter, 1);
            m.set_ref(s, Field::_parent_ship, ship);
        }
        return s;
    }
    int64_t pod(double cond = 100.0) {
        int64_t p = sub(false);
        m.set_f(p, Field::_condition, cond);
        m.set_ref(p, Field::_parent_subsystem, ies);
        return p;
    }
    void kids(std::vector<int64_t> v) { m.set_ids(ies, Field::_children, v); }
};

}  // namespace

TEST(ImpulseFractions, NoIes) {
    World w;
    const ImpulseFractions f = impulse_fractions(w.m, -1);
    EXPECT_EQ(f.online, 1.0);
    EXPECT_EQ(f.output, 1.0);
}

TEST(ImpulseFractions, NoPods) {
    World w;
    w.m.set_f(w.ies, Field::_power_percentage_wanted, 0.5);
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.online, 1.0);
    EXPECT_EQ(f.output, 0.5);
}

TEST(ImpulseFractions, OfflineMasterZero) {
    World w;
    w.kids({w.pod()});
    w.m.set_i(w.ies, Field::_destroyed, 1);
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.online, 0.0);
    EXPECT_EQ(f.output, 0.0);
}

TEST(ImpulseFractions, DisabledPodForfeitsShare) {
    World w;
    int64_t a = w.pod(100.0), b = w.pod(100.0);
    w.m.set_f(b, Field::_disabled_percentage, 0.5);
    w.m.set_f(b, Field::_condition, 40.0);  // disabled: <= 50
    w.kids({a, b});
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.online, 0.5);
    EXPECT_EQ(f.output, 0.5);  // (1.0 + nothing from b) / 2
}

TEST(ImpulseFractions, SwitchedOffKeepsOnline) {
    World w;
    w.kids({w.pod(), w.pod()});
    w.m.set_i(w.ies, Field::_is_on, 0);
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.online, 1.0);
    EXPECT_EQ(f.output, 0.0);
}

TEST(ImpulseFractions, ClampBeforeSlider) {
    World w;
    w.kids({w.pod()});
    w.m.set_f(w.ies, Field::_power_percentage_wanted, 1.25);
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.output, 1.25);
}

TEST(ImpulseFractions, DyingShipZero) {
    World w;
    w.kids({w.pod()});
    w.m.set_i(w.ship, Field::_dying, 1);
    const ImpulseFractions f = impulse_fractions(w.m, w.ies);
    EXPECT_EQ(f.online, 0.0);
    EXPECT_EQ(f.output, 0.0);
}

TEST(ImpulseFractions, UnrepresentableThrows) {
    World w;
    w.m.set_ref(w.ies, Field::_parent_ship, kRefUnrepresentable);
    EXPECT_THROW(impulse_fractions(w.m, w.ies), std::invalid_argument);
    EXPECT_THROW(impulse_fractions(w.m, kRefUnrepresentable),
                 std::invalid_argument);
}
