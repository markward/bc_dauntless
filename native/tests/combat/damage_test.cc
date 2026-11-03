// The native hit and condition chain (damage.h) on hand-built mirror rows:
// the ramp bands, the entries a write and a hit emit, in order, the class
// rules and the fallback's rollback. The native-vs-Python differential is
// tests/integration/test_native_damage_differential.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string_view>
#include <variant>
#include <vector>

#include "dauntless/combat/damage.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr std::array<double, 9> kIdentity{1, 0, 0, 0, 1, 0, 0, 0, 1};

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t ship = -1, hull = -1, sensor = -1, shields = -1, system = -1,
            bank1 = -1, bank2 = -1;

    World() {
        auto [xi, xg] = store.alloc();
        store.set_position(xi, xg, 0.0, 0.0, 0.0);
        store.set_rotation(xi, xg, kIdentity);
        ship = m.register_row(Kind::Object, xi, xg, 1);
        m.set_i(ship, Field::is_ship_class, 1);
        m.set_i(ship, Field::has_real_get_shields, 1);
        m.set_i(ship, Field::has_cloak_getter, 1);
        m.set_i(ship, Field::dmg_ship, 1);
        m.set_i(ship, Field::_hurtable, 1);
        m.set_f(ship, Field::_scale, 1.0);
        m.set_fv(ship, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
        m.set_fv(ship, Field::_shield_hull_box_half, {1.0, 2.0, 0.5});
        m.set_i(ship, Field::hull_box_set, 1);

        hull = subsystem(1000.0, {0, 0, 0}, 0.0);
        m.set_i(hull, Field::_critical, 1);
        m.set_f(hull, Field::_disabled_percentage, 0.5);
        m.set_ref(ship, Field::_hull, hull);
        sensor = subsystem(200.0, {0.0, 1.5, 0.0}, 0.5);
        shields = subsystem(100.0, {0.0, 0.0, -3.0}, 0.0);
        m.set_i(shields, Field::has_shields, 1);
        m.set_i(shields, Field::_is_on, 1);
        m.set_floats(shields, Field::_current_shields,
                     {1000, 1000, 1000, 1000, 1000, 1000});
        m.set_floats(shields, Field::_max_shields,
                     {1000, 1000, 1000, 1000, 1000, 1000});
        m.set_floats(shields, Field::_ramp_fraction, {0, 0, 0, 0, 0, 0});
        m.set_floats(shields, Field::_ramp_set, {0, 0, 0, 0, 0, 0});
        m.set_ref(ship, Field::_shield_subsystem, shields);
        system = subsystem(100.0, {0.0, 0.0, 5.0}, 0.3);
        m.set_i(system, Field::dmg_class, kDmgAggregate);
        bank1 = subsystem(80.0, {0.5, 0.5, 0.3}, 0.3);
        bank2 = subsystem(80.0, {-0.5, 0.5, 0.3}, 0.3);
        for (int64_t b : {bank1, bank2}) {
            m.set_ref(b, Field::_parent_ship, -1);
            m.set_ref(b, Field::_parent_subsystem, system);
        }
        m.set_ids(system, Field::_children, {bank1, bank2});
        m.set_mount_order(ship, {sensor, system, bank1, bank2, shields});
    }

    int64_t subsystem(double max, const Vec3& pos, double radius) {
        int64_t s = m.register_row(Kind::Subsystem);
        m.set_f(s, Field::_max_condition, max);
        m.set_f(s, Field::_condition, max);
        m.set_f(s, Field::_disabled_percentage, 0.25);
        m.set_fv(s, Field::_position, {pos[0], pos[1], pos[2]});
        m.set_f(s, Field::s_radius, radius);
        m.set_ref(s, Field::_parent_ship, ship);
        m.set_i(s, Field::dmg_class, kDmgLeaf);
        return s;
    }

    double cond(int64_t s) const { return m.get_f(s, Field::_condition); }
    double face(int f) const {
        return m.get_floats(shields, Field::_current_shields).at(f);
    }

    HitInput hit(double damage, const Vec3& point) const {
        HitInput in;
        in.ship = ship;
        in.damage = damage;
        in.point = point;
        in.r_hit = 0.15;
        return in;
    }
};

std::vector<DamageKind> kinds(const DamageOut& out) {
    std::vector<DamageKind> k;
    for (const DamageEntry& e : out.entries) k.push_back(e.kind);
    return k;
}

using K = DamageKind;

}  // namespace

// ── The ramp (ShieldSubsystem.ApplyDamage) ──────────────────────────────────

TEST(Damage, NoRampYetReadsTheFaceLiveAndAbsorbsAtFullCharge) {
    World w;
    DamageOut out;
    apply_hit(w.m, w.hit(300.0, {0.0, 2.0, 0.0}), {}, out);
    EXPECT_EQ(w.face(0), 700.0);              // frac 1.0 >= 0.6: b = 0
    EXPECT_EQ(w.cond(w.hull), 1000.0);
    EXPECT_EQ(kinds(out), (std::vector<K>{K::HIT_PRESENT, K::WEAPON_HIT}));
}

TEST(Damage, TheLinearBandPassesAShareThrough) {
    World w;
    w.m.set_float_at(w.shields, Field::_current_shields, 0, 450.0);
    w.m.set_float_at(w.shields, Field::_ramp_fraction, 0, 0.45);
    w.m.set_float_at(w.shields, Field::_ramp_set, 0, 1.0);
    DamageOut out;
    apply_hit(w.m, w.hit(100.0, {0.0, 2.0, 0.0}), {}, out);
    const double b = 0.6 * (1.0 - 2.0 * (0.45 - 0.1));
    EXPECT_EQ(w.face(0), 450.0 - (1.0 - b) * 100.0);
    EXPECT_EQ(w.cond(w.hull), 1000.0 - b * 100.0);
}

TEST(Damage, AtOrBelowATenthTheFaceIsBypassed) {
    World w;
    w.m.set_float_at(w.shields, Field::_current_shields, 1, 50.0);
    w.m.set_float_at(w.shields, Field::_ramp_fraction, 1, 0.05);
    w.m.set_float_at(w.shields, Field::_ramp_set, 1, 1.0);
    DamageOut out;
    apply_hit(w.m, w.hit(80.0, {0.0, -2.0, 0.0}), {}, out);
    EXPECT_EQ(w.face(1), 50.0);
    EXPECT_EQ(w.cond(w.hull), 920.0);
}

TEST(Damage, AnOverdrawEmptiesTheFaceAndBleedsTheRest) {
    World w;
    w.m.set_float_at(w.shields, Field::_current_shields, 0, 400.0);
    w.m.set_float_at(w.shields, Field::_ramp_fraction, 0, 0.4);
    w.m.set_float_at(w.shields, Field::_ramp_set, 0, 1.0);
    DamageOut out;
    apply_hit(w.m, w.hit(900.0, {0.0, 2.0, 0.0}), {}, out);
    const double b = 0.6 * (1.0 - 2.0 * (0.4 - 0.1));
    const double nw = 400.0 - (1.0 - b) * 900.0;
    EXPECT_EQ(w.face(0), 0.0);
    EXPECT_EQ(w.cond(w.hull), 1000.0 - (b * 900.0 - nw));
}

TEST(Damage, TheFaceIsTheHullBoxsDominantAxis) {
    World w;
    // Normalised by the half-extents (1, 2, 0.5): z wins at (0.3, 0.3, 0.3)
    // although x and y are as long.
    EXPECT_EQ(shield_face(w.m, w.ship, {0.3, 0.3, 0.3}), 2);
    EXPECT_EQ(shield_face(w.m, w.ship, {0.3, 0.3, -0.3}), 3);
    EXPECT_EQ(shield_face(w.m, w.ship, {0.0, -1.0, 0.0}), 1);
    EXPECT_EQ(shield_face(w.m, w.ship, {-0.9, 0.1, 0.0}), 4);
    EXPECT_EQ(shield_face(w.m, w.ship, {0.9, 0.1, 0.0}), 5);
    // A tie of y with x goes to y (y -> z -> x).
    EXPECT_EQ(shield_face(w.m, w.ship, {1.0, 2.0, 0.0}), 0);
}

TEST(Damage, ANanHalfExtentKeepsTheBoxAsPythonDoes) {
    // _hull_box_for rejects only `hx <= 0.0`: a NaN half-extent keeps the
    // box, its x delta NaN, and every compare with it false -> face 5. The
    // raw-axis rule would read (0, 1, 0) as face 0.
    World w;
    w.m.set_fv(w.ship, Field::_shield_hull_box_half,
               {std::nan(""), 2.0, 0.5});
    EXPECT_EQ(shield_face(w.m, w.ship, {0.0, 1.0, 0.0}), 5);
    w.m.set_fv(w.ship, Field::_shield_hull_box_half, {0.0, 2.0, 0.5});
    EXPECT_EQ(shield_face(w.m, w.ship, {0.0, 1.0, 0.0}), 0);
}

// ── The condition chain ─────────────────────────────────────────────────────

TEST(Damage, AWriteEmitsWatchersThenTheEventThenTheRepair) {
    World w;
    w.m.set_i(w.sensor, Field::comb_watch_checks, 1);
    w.m.set_f(w.sensor, Field::comb_watch_value, 1.0);
    w.m.set_i(w.sensor, Field::cond_watch_checks, 0);   // a watcher, no checks
    w.m.set_f(w.sensor, Field::cond_watch_value, 1.0);
    DamageOut out;
    set_condition(w.m, w.sensor, 40.0, -1, -1, out);    // 20%: disabled
    EXPECT_EQ(kinds(out), (std::vector<K>{K::COND_WATCH, K::SUBSYS_EVENT,
                                          K::REPAIR_ADD}));
    const DamageEntry& watch = out.entries[0];
    EXPECT_EQ(watch.ops[1].integer, 1);                 // WATCH_COMBINED
    EXPECT_EQ(watch.ops[2].number, 1.0);
    EXPECT_EQ(watch.ops[3].number, 0.2);
    EXPECT_EQ(out.entries[1].ops[1].integer, 1);        // SUBSYS_DISABLED
    EXPECT_EQ(w.m.get_f(w.sensor, Field::cond_watch_value), 0.2);
    EXPECT_EQ(w.m.get_i(w.sensor, Field::_threshold_state), 1);
    std::vector<std::string_view> fields;
    for (const LoggedWrite& lw : out.writes) fields.push_back(lw.field);
    EXPECT_EQ(fields, (std::vector<std::string_view>{
                          "_condition", "_combined_watcher",
                          "_condition_watcher", "_threshold_state"}));
}

TEST(Damage, AQueuedSubsystemEmitsNoRepair) {
    World w;
    w.m.set_i(w.sensor, Field::_in_repair_queue, 1);
    DamageOut out;
    set_condition(w.m, w.sensor, 150.0, -1, -1, out);
    EXPECT_TRUE(out.entries.empty());
}

TEST(Damage, ACriticalSubsystemAtZeroReportsItsCrossingOnce) {
    World w;
    DamageOut out;
    damage_system(w.m, w.ship, w.hull, 5000.0, 77, out);
    ASSERT_EQ(kinds(out), (std::vector<K>{K::SUBSYS_EVENT, K::REPAIR_ADD,
                                          K::ZERO_CROSS}));
    const DamageEntry& zc = out.entries[2];
    EXPECT_EQ(zc.ops[0].handle, w.ship);
    EXPECT_EQ(zc.ops[1].handle, w.hull);
    EXPECT_TRUE(zc.ops[2].boolean);                     // crossed
    EXPECT_EQ(zc.ops[3].type, DamageOperand::Type::Held);
    EXPECT_EQ(zc.ops[3].handle, 77);
    out.clear();
    w.m.set_i(w.hull, Field::_in_repair_queue, 1);
    set_condition(w.m, w.hull, 0.0, -1, -1, out);       // still at 0
    ASSERT_EQ(kinds(out), (std::vector<K>{K::ZERO_CROSS}));
    EXPECT_FALSE(out.entries[0].ops[2].boolean);        // critical, not crossed
}

TEST(Damage, AWeaponSystemIsDisabledOnlyWhenEveryBankIs) {
    World w;
    DamageOut out;
    set_condition(w.m, w.bank1, 0.0, -1, -1, out);
    EXPECT_EQ(w.m.get_i(w.system, Field::_threshold_state), 0);
    out.clear();
    set_condition(w.m, w.system, 10.0, -1, -1, out);    // its own write
    EXPECT_EQ(w.m.get_i(w.system, Field::_threshold_state), 0);  // bank2 up
    set_condition(w.m, w.bank2, 0.0, -1, -1, out);
    out.clear();
    set_condition(w.m, w.system, 9.0, -1, -1, out);
    EXPECT_EQ(w.m.get_i(w.system, Field::_threshold_state), 2);
}

// ── The hit ─────────────────────────────────────────────────────────────────

TEST(Damage, OverlapsAreDamagedInMountOrderAndTheFirstOfATieIsPrimary) {
    World w;
    HitInput in = w.hit(60.0, {0.0, 0.5, 0.3});
    in.bypass_shields = true;
    in.r_hit = 0.6;
    DamageOut out;
    apply_hit(w.m, in, {}, out);
    EXPECT_EQ(w.cond(w.hull), 940.0);
    EXPECT_EQ(w.cond(w.sensor), 140.0);
    EXPECT_EQ(w.cond(w.bank1), 20.0);
    EXPECT_EQ(w.cond(w.bank2), 20.0);
    EXPECT_EQ(w.cond(w.system), 100.0);                 // out of reach
    const DamageEntry& present = out.entries[out.entries.size() - 2];
    ASSERT_EQ(present.kind, K::HIT_PRESENT);
    EXPECT_EQ(present.count, 35);
    EXPECT_EQ(present.ops[11].handle, w.bank1);         // the tie's first
    EXPECT_EQ(present.ops[13].number, 180.0);           // three offered 60
    EXPECT_EQ(out.entries.back().kind, K::WEAPON_HIT);
    EXPECT_EQ(out.entries.back().count, 14);
    EXPECT_TRUE(out.entries.back().ops[13].boolean);    // a hull hit
}

TEST(Damage, AnUnhurtableShipTakesNothingAndStillReportsTheHit) {
    World w;
    w.m.set_i(w.ship, Field::_hurtable, 0);
    DamageOut out;
    apply_hit(w.m, w.hit(300.0, {0.0, 2.0, 0.0}), {}, out);
    EXPECT_EQ(w.face(0), 1000.0);
    EXPECT_TRUE(out.writes.empty());
    ASSERT_EQ(kinds(out), (std::vector<K>{K::HIT_PRESENT, K::WEAPON_HIT}));
    EXPECT_FALSE(out.entries[0].ops[18].boolean);       // persist_decal
    EXPECT_EQ(out.entries[0].ops[12].number, 300.0);    // absorbed, as shown
}

TEST(Damage, TheCheatsActOnThePlayerOnly) {
    World w;
    DamageContext ctx;
    ctx.player = w.ship;
    ctx.god_mode = true;
    DamageOut out;
    apply_hit(w.m, w.hit(300.0, {0.0, 2.0, 0.0}), ctx, out);
    EXPECT_EQ(w.face(0), 1000.0);                       // god mode
    ctx.god_mode = false;
    ctx.double_damage = true;
    HitInput in = w.hit(100.0, {0.0, 2.0, 0.0});
    in.source = w.ship;                                 // the player fires
    apply_hit(w.m, in, ctx, out);
    EXPECT_EQ(w.face(0), 800.0);
    ctx.double_damage = false;
    ctx.npc_shields_off = true;
    ctx.player = -1;                                    // the ship is an NPC
    apply_hit(w.m, w.hit(50.0, {0.0, 2.0, 0.0}), ctx, out);
    EXPECT_EQ(w.face(0), 800.0);
    EXPECT_EQ(w.cond(w.hull), 950.0);
}

TEST(Damage, AFallbackRestoresEveryWriteAndKeepsWhatOutHeld) {
    World w;
    DamageOut out;
    set_condition(w.m, w.sensor, 150.0, -1, -1, out);
    const size_t writes = out.writes.size(), entries = out.entries.size();
    // The hull is written first, then the walk meets a row it cannot name.
    w.m.set_mount_order(w.ship, {w.sensor, kRefUnrepresentable});
    HitInput in = w.hit(100.0, {0.0, 1.0, 0.0});
    in.bypass_shields = true;
    EXPECT_THROW(apply_hit(w.m, in, {}, out), std::invalid_argument);
    EXPECT_EQ(w.cond(w.hull), 1000.0);
    EXPECT_EQ(w.cond(w.sensor), 150.0);
    EXPECT_EQ(w.m.get_i(w.hull, Field::_threshold_state), 0);
    EXPECT_EQ(out.writes.size(), writes);
    EXPECT_EQ(out.entries.size(), entries);
    EXPECT_EQ(out.undo.size(), writes);
}

TEST(Damage, UndoDamageRestoresAHitAndOutKeepsOneUndoPerWrite) {
    // K2's pulse is rolled back with its walk (k2_beams.h): the undo log a
    // call leaves in `out` restores every value it wrote, faces included.
    World w;
    w.m.set_float_at(w.shields, Field::_current_shields, 0, 450.0);
    w.m.set_float_at(w.shields, Field::_ramp_fraction, 0, 0.45);
    w.m.set_float_at(w.shields, Field::_ramp_set, 0, 1.0);
    DamageOut out;
    set_condition(w.m, w.sensor, 150.0, -1, -1, out);
    const size_t first = out.undo.size();
    EXPECT_EQ(first, out.writes.size());
    apply_hit(w.m, w.hit(100.0, {0.0, 2.0, 0.0}), {}, out);
    EXPECT_EQ(out.undo.size(), out.writes.size());
    EXPECT_NE(w.face(0), 450.0);
    EXPECT_NE(w.cond(w.hull), 1000.0);
    undo_damage(w.m, out.undo, first);
    EXPECT_EQ(w.face(0), 450.0);
    EXPECT_EQ(w.cond(w.hull), 1000.0);
    EXPECT_EQ(w.m.get_i(w.hull, Field::_threshold_state), 0);
    EXPECT_EQ(w.cond(w.sensor), 150.0);   // before `first`: kept
    undo_damage(w.m, out.undo);
    EXPECT_EQ(w.cond(w.sensor), 200.0);
}

TEST(Damage, AClassThePythonOwnsFallsBack) {
    World w;
    w.m.set_i(w.sensor, Field::dmg_class, kDmgPython);
    DamageOut out;
    EXPECT_THROW(set_condition(w.m, w.sensor, 10.0, -1, -1, out),
                 std::invalid_argument);
    w.m.set_i(w.sensor, Field::dmg_class, kDmgLeaf);
    w.m.set_i(w.sensor, Field::cond_watch_checks, kWatchForeign);
    EXPECT_THROW(set_condition(w.m, w.sensor, 10.0, -1, -1, out),
                 std::invalid_argument);
    EXPECT_EQ(w.cond(w.sensor), 200.0);
    w.m.set_i(w.ship, Field::dmg_ship, 0);
    EXPECT_THROW(apply_hit(w.m, w.hit(1.0, {0, 0, 0}), {}, out),
                 std::invalid_argument);
}

TEST(Damage, ACloakWhoseClassPythonOwnsFallsBack) {
    // shields_block reads the cloak's state for cloak_shields_suspended,
    // which calls the class's IsCloaking / IsDecloaking.
    World w;
    const int64_t cloak = w.subsystem(100.0, {0, 0, 0}, 0.0);
    w.m.set_ref(w.ship, Field::_cloaking_subsystem, cloak);
    DamageOut out;
    apply_hit(w.m, w.hit(1.0, {0.0, 1.0, 0.0}), {}, out);
    w.m.set_i(cloak, Field::dmg_class, kDmgPython);
    const double before = w.face(0);
    DamageOut again;
    EXPECT_THROW(apply_hit(w.m, w.hit(1.0, {0.0, 1.0, 0.0}), {}, again),
                 std::invalid_argument);
    EXPECT_EQ(w.face(0), before);
}
