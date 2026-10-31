// The native weapon geometry (weapon_geometry.h) on hand-built mirror rows:
// the mount memo's key and its clearing, and a few exact answers. The
// native-vs-Python differential runs from tests/unit/test_native_weapon_geometry.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/sensor_detect.h"
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
    int64_t bank(int64_t ship_h, double px, double py, double pz) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_ref(s, Field::_parent_ship, ship_h);
        m.set_fv(s, Field::_position, {px, py, pz});
        return s;
    }
};

}  // namespace

TEST(WeaponGeometry, MountPositionIsShipPlusRotatedLocal) {
    World w;
    const int64_t ship = w.ship(10.0, 20.0, 30.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    const Vec3 p = subsystem_world_position(w.m, bank, -1, false);
    EXPECT_EQ(p[0], 11.0);
    EXPECT_EQ(p[1], 22.0);
    EXPECT_EQ(p[2], 33.0);
}

TEST(WeaponGeometry, PosedShipFallsBack) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 2.0, 3.0);
    w.m.set_i(ship, Field::has_posed_parts, 1);
    EXPECT_THROW(subsystem_world_position(w.m, bank, -1, true),
                 std::invalid_argument);
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
}

TEST(WeaponGeometry, MountMemoKeyIncludesShipArg) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 0.0, 0.0);
    // The same sub under ship_arg none and ship_arg ship: two entries.
    subsystem_world_position(w.m, bank, -1, true);
    EXPECT_EQ(w.m.sensor_state().mounts.size(), 1u);
    subsystem_world_position(w.m, bank, ship, true);
    EXPECT_EQ(w.m.sensor_state().mounts.size(), 2u);
    subsystem_world_position(w.m, bank, ship, true);   // a hit: no third
    EXPECT_EQ(w.m.sensor_state().mounts.size(), 2u);
}

TEST(WeaponGeometry, MountMemoReusesUntilCleared) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 0.0, 0.0);
    const Vec3 first = subsystem_world_position(w.m, bank, -1, true);
    auto [i, g] = std::pair<uint32_t, uint32_t>{
        static_cast<uint32_t>(w.m.object(ship)->xform_index),
        static_cast<uint32_t>(w.m.object(ship)->xform_gen)};
    w.store.set_position(i, g, 100.0, 0.0, 0.0);
    // Stale on purpose, as the Python inside a step.
    EXPECT_EQ(subsystem_world_position(w.m, bank, -1, true)[0], first[0]);
    // Not memoised when the session has no memo.
    EXPECT_EQ(subsystem_world_position(w.m, bank, -1, false)[0], 101.0);
    memo_clear(w.m);
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
    EXPECT_EQ(subsystem_world_position(w.m, bank, -1, true)[0], 101.0);
}

TEST(WeaponGeometry, MountMemoIsDroppedWithItsRows) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 0.0, 0.0);
    subsystem_world_position(w.m, bank, ship, true);
    subsystem_world_position(w.m, bank, -1, true);
    w.m.unregister_row(ship);
    EXPECT_EQ(w.m.sensor_state().mounts.size(), 1u);
    w.m.unregister_row(bank);
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
}

TEST(WeaponGeometry, MemoClearedByMirrorClear) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0);
    const int64_t bank = w.bank(ship, 1.0, 0.0, 0.0);
    subsystem_world_position(w.m, bank, -1, true);
    w.m.clear();
    EXPECT_TRUE(w.m.sensor_state().mounts.empty());
}
