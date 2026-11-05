// The subsystem stage session (subsystem_step.h) on hand-built mirror rows:
// its walk order and its skip of a row freed mid-walk. The native-vs-Python
// per-tick differential is
// tests/integration/test_native_subsystems_differential.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/subsystem_step.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;

struct World {
    TransformStore store;
    Mirror m{store};

    // A ship whose `_shield_subsystem` the mirror cannot name
    // (kRefUnrepresentable): its SHIELD piece is Python's, so every piece
    // of it is a RUN_PYTHON record (the walk-order tests below).
    int64_t ship() {
        const int64_t h = bare_ship();
        m.set_ref(h, Field::_shield_subsystem, kRefUnrepresentable);
        return h;
    }

    // A ship with no shield generator (`_shield_subsystem` None) and a power
    // plant the mirror cannot name (kRefUnrepresentable): its POWER piece
    // is Python's.
    int64_t bare_ship() {
        auto [xi, xg] = store.alloc();
        const int64_t h = m.register_row(Kind::Object, xi, xg);
        m.set_ref(h, Field::_power_subsystem, kRefUnrepresentable);
        return h;
    }

    // A ShipClass row with no shield generator and no plant yet: plant()
    // gives it one, consumer() its consumers.
    int64_t power_ship() {
        auto [xi, xg] = store.alloc();
        const int64_t h = m.register_row(Kind::Object, xi, xg);
        m.set_i(h, Field::is_ship_class, 1);
        return h;
    }

    // A PowerProperty: the five per-tick values, all read through the data
    // bag (power_props_ok), MaxCondition unset.
    int64_t power_prop(double output, double main_limit, double backup_limit,
                       double main_cap, double backup_cap) {
        const int64_t p = m.register_row(Kind::Property);
        m.set_f(p, Field::PowerOutput, output);
        m.set_f(p, Field::MainBatteryLimit, main_limit);
        m.set_f(p, Field::BackupBatteryLimit, backup_limit);
        m.set_f(p, Field::MainConduitCapacity, main_cap);
        m.set_f(p, Field::BackupConduitCapacity, backup_cap);
        m.set_i(p, Field::power_props_ok, 1);
        return p;
    }

    // A native-ready plant on `ship` (its parent ship, whose consumers the
    // pump walks), healthy, interval clock at `interval`, both battery
    // watchers adopted with no checks; the 1.0 s interval pushed. `prop`
    // -1: no property.
    int64_t plant(int64_t ship, int64_t prop, double main, double backup,
                  double interval) {
        const int64_t h = m.register_row(Kind::Subsystem);
        m.set_i(h, Field::power_kind, 3);
        m.set_f(h, Field::_max_condition, 1000.0);
        m.set_f(h, Field::_condition, 1000.0);
        m.set_f(h, Field::_disabled_percentage, 0.5);
        m.set_ref(h, Field::_property, prop);
        m.set_ref(h, Field::_parent_ship, ship);
        m.set_f(h, Field::_main_battery_power, main);
        m.set_f(h, Field::_backup_battery_power, backup);
        m.set_f(h, Field::_interval_elapsed, interval);
        m.set_i(h, Field::power_watch_ok, 1);
        m.set_floats(h, Field::power_watch_values, {1.0, 1.0});
        m.set_floats(h, Field::power_watch_checks, {0.0, 0.0});
        m.set_global_f(Global::POWER_INTERVAL, 1.0);
        m.set_ref(ship, Field::_power_subsystem, h);
        return h;
    }

    // A consumer of `kind` (native_combat._power_kind) appended to `ship`'s
    // consumers: on, `normal` per second, slider 1.0, draw mode `mode`.
    int64_t consumer(int64_t ship, int64_t kind, double normal,
                     int64_t mode = 0) {
        const int64_t h = m.register_row(Kind::Subsystem);
        m.set_i(h, Field::power_kind, kind);
        m.set_i(h, Field::POWER_MODE, mode);
        m.set_i(h, Field::_is_on, 1);
        m.set_f(h, Field::_normal_power, normal);
        m.set_f(h, Field::_power_percentage_wanted, 1.0);
        m.set_f(h, Field::_efficiency, 1.0);
        m.set_f(h, Field::_power_factor, 1.0);
        std::vector<int64_t> list = m.get_ids(ship, Field::_powered_consumers);
        list.push_back(h);
        m.set_ids(ship, Field::_powered_consumers, list);
        return h;
    }

    // A native-ready shield generator on `ship`: every face max 100,
    // current 5, 2/s, generator on and healthy, seven watchers adopted with
    // no checks (shield_watch_ok 1), the 0.5 s cadence pushed.
    int64_t shield(int64_t ship) {
        const int64_t h = m.register_row(Kind::Subsystem);
        m.set_floats(h, Field::_max_shields, std::vector<double>(6, 100.0));
        m.set_floats(h, Field::_current_shields, std::vector<double>(6, 5.0));
        m.set_floats(h, Field::_charge_per_second, std::vector<double>(6, 2.0));
        m.set_floats(h, Field::_ramp_fraction, std::vector<double>(6, 0.0));
        m.set_floats(h, Field::_ramp_set, std::vector<double>(6, 0.0));
        m.set_f(h, Field::_max_condition, 1000.0);
        m.set_f(h, Field::_condition, 1000.0);
        m.set_f(h, Field::_disabled_percentage, 0.5);
        m.set_i(h, Field::_is_on, 1);
        m.set_i(h, Field::shield_watch_ok, 1);
        m.set_floats(h, Field::shield_watch_values,
                     std::vector<double>(7, 0.05));
        m.set_floats(h, Field::shield_watch_checks,
                     std::vector<double>(7, 0.0));
        m.set_global_f(Global::SHIELD_CHARGE_PERIOD_S, 0.5);
        m.set_ref(ship, Field::_shield_subsystem, h);
        return h;
    }
};

// Runs the session to DONE, applying nothing; the records, in order.
std::vector<SubsystemRecord> drain(SubsystemSession& s, Mirror& m) {
    std::vector<SubsystemRecord> out;
    for (int guard = 0; guard < 1000; ++guard) {
        const SubsystemRecord r = subsystems::next(s, m);
        if (r.type == SubsystemRecordType::DONE) return out;
        out.push_back(r);
    }
    ADD_FAILURE() << "the session never returned DONE";
    return out;
}

// (ship_pos, piece) of every record up to DONE, which must come last.
std::vector<std::pair<int64_t, SubsystemPiece>> walk(
        SubsystemSession& s, Mirror& m) {
    std::vector<std::pair<int64_t, SubsystemPiece>> out;
    for (int guard = 0; guard < 1000; ++guard) {
        const SubsystemRecord r = subsystems::next(s, m);
        if (r.type == SubsystemRecordType::DONE) return out;
        EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
        out.emplace_back(r.ship_pos, static_cast<SubsystemPiece>(r.kind));
    }
    ADD_FAILURE() << "the session never returned DONE";
    return out;
}

constexpr SubsystemPiece kOrder[] = {
    SubsystemPiece::SHIELD, SubsystemPiece::POWER, SubsystemPiece::CLOAK,
    SubsystemPiece::REPAIR, SubsystemPiece::ARTICULATION};

}  // namespace

TEST(SubsystemStep, AllPythonOrderIsShipThenKind) {
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    EXPECT_EQ(s.dt, kDt);

    std::vector<std::pair<int64_t, SubsystemPiece>> want;
    for (int64_t i = 0; i < 3; ++i)
        for (SubsystemPiece p : kOrder) want.emplace_back(i, p);

    // Each record names its ship's handle too.
    std::vector<SubsystemRecord> records;
    for (;;) {
        const SubsystemRecord r = subsystems::next(s, w.m);
        if (r.type == SubsystemRecordType::DONE) break;
        records.push_back(r);
        ASSERT_LT(records.size(), 100u);
    }
    ASSERT_EQ(records.size(), 15u);
    for (size_t k = 0; k < records.size(); ++k) {
        EXPECT_EQ(records[k].type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(records[k].ship_pos, want[k].first) << k;
        EXPECT_EQ(static_cast<SubsystemPiece>(records[k].kind),
                  want[k].second) << k;
        EXPECT_EQ(records[k].ship,
                  ships[static_cast<size_t>(want[k].first)]) << k;
    }
    // DONE is the end: asking again is a protocol error.
    EXPECT_THROW(subsystems::next(s, w.m), std::logic_error);
}

TEST(SubsystemStep, FreedRowHandsTheRestToPython) {
    // A row freed mid-walk while its object lives on (native_combat._drop):
    // the Python stage still runs every piece of that ship, so the session
    // hands them all back, in order, and never skips it.
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const SubsystemRecord first = subsystems::next(s, w.m);
    ASSERT_EQ(first.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(first.ship_pos, 0);
    // A handler run for that record dropped the second ship's row.
    w.m.unregister_row(ships[1]);
    const auto rest = walk(s, w.m);
    ASSERT_EQ(rest.size(), 4u + 5u + 5u);
    for (size_t k = 0; k < rest.size(); ++k) {
        EXPECT_EQ(rest[k].first, static_cast<int64_t>((k + 1) / 5)) << k;
        EXPECT_EQ(rest[k].second, kOrder[(k + 1) % 5]) << k;
    }
}

TEST(SubsystemStep, FreedBetweenPiecesHandsTheRestOfThatShipToPython) {
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    for (int k = 0; k < 2; ++k)
        ASSERT_EQ(subsystems::next(s, w.m).ship_pos, 0);
    w.m.unregister_row(ships[0]);       // its POWER handler dropped it
    // A new row may reuse the slot: the lost row stays Python's.
    w.ship();
    const auto rest = walk(s, w.m);
    ASSERT_EQ(rest.size(), 3u + 5u);
    for (size_t k = 0; k < 3; ++k) {
        EXPECT_EQ(rest[k].first, 0);
        EXPECT_EQ(rest[k].second, kOrder[k + 2]);
    }
    for (size_t k = 0; k < 5; ++k) EXPECT_EQ(rest[3 + k].first, 1);
    EXPECT_EQ(s.lost_row[0], 1);
    EXPECT_EQ(s.lost_row[1], 0);
}

TEST(SubsystemStep, AShipWithNoRowIsStillPythons) {
    // A ship the mirror has no row for (-1 or a handle already stale at
    // begin) is not a freed row: the Python stage updates it, so every piece
    // is handed back.
    World w;
    const int64_t gone = w.ship();
    w.m.unregister_row(gone);
    const std::vector<int64_t> ships = {-1, gone};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const auto all = walk(s, w.m);
    ASSERT_EQ(all.size(), 10u);
    for (size_t k = 0; k < all.size(); ++k) {
        EXPECT_EQ(all[k].first, static_cast<int64_t>(k / 5));
        EXPECT_EQ(all[k].second, kOrder[k % 5]);
    }
}

TEST(SubsystemStep, AnEmptyListIsDone) {
    World w;
    SubsystemSession s = subsystems::begin(w.m, {}, kDt);
    EXPECT_EQ(subsystems::next(s, w.m).type, SubsystemRecordType::DONE);
}

// ── The shield piece (Task 3; subsystem_step.h THE SHIELD PIECE) ──────────

TEST(ShieldStep, ChargesOnTheThirtiethOrThirtyFirstTick) {
    // Python, `a = 0.0; a = a + 1.0/60` until `a >= 0.5`: it first holds on
    // tick 31, with a == 0x1.0888888888888p-1 (computed in CPython 3.11 and
    // stored here, not re-derived). The face then gets 5 + 2 * a.
    constexpr int kChargeTick = 31;
    constexpr double kAccum = 0x1.0888888888888p-1;
    constexpr double kFace = 0x1.8222222222222p+2;  // 5.0 + 2.0 * kAccum
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    double accum = 0.0;
    for (int tick = 1; tick <= kChargeTick; ++tick) {
        SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
        const SubsystemRecord r = subsystems::next(s, w.m);
        // The shield piece is native; the rest of the ship is Python's.
        ASSERT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(static_cast<SubsystemPiece>(r.kind), SubsystemPiece::POWER);
        accum = accum + kDt;
        if (tick < kChargeTick) {
            ASSERT_LT(accum, 0.5) << tick;
            EXPECT_EQ(w.m.get_f(sh, Field::_charge_accum), accum) << tick;
            EXPECT_EQ(w.m.get_floats(sh, Field::_current_shields)[0], 5.0);
            ASSERT_EQ(s.writes.size(), 1u) << tick;
            EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::CHARGE_ACCUM);
            EXPECT_EQ(s.writes[0].value, accum);
            continue;
        }
        EXPECT_EQ(accum, kAccum);
        EXPECT_EQ(w.m.get_f(sh, Field::_charge_accum), 0.0);
        for (int f = 0; f < 6; ++f) {
            EXPECT_EQ(w.m.get_floats(sh, Field::_current_shields)[f], kFace);
            EXPECT_EQ(w.m.get_floats(sh, Field::_ramp_fraction)[f], 0.05);
            EXPECT_EQ(w.m.get_floats(sh, Field::_ramp_set)[f], 1.0);
        }
        // Every watcher took its value (no checks: written, no event):
        // faces kFace / 100, the combined one the sums' ratio.
        const std::vector<double> v =
            w.m.get_floats(sh, Field::shield_watch_values);
        for (int f = 0; f < 6; ++f) EXPECT_EQ(v[f], kFace / 100.0);
        double tc = 0.0, tm = 0.0;
        for (int f = 0; f < 6; ++f) {
            tc += kFace;
            tm += 100.0;
        }
        EXPECT_EQ(v[6], tc / tm);
        // The log, in the Python piece's order: accum, 6 ramps, 6 faces,
        // 7 watchers.
        ASSERT_EQ(s.writes.size(), 1u + 6u + 6u + 7u);
        EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::CHARGE_ACCUM);
        EXPECT_EQ(s.writes[0].value, 0.0);
        for (int k = 0; k < 6; ++k) {
            EXPECT_EQ(s.writes[1 + k].what, SubsystemWriteKind::RAMP);
            EXPECT_EQ(s.writes[7 + k].what, SubsystemWriteKind::FACE);
            EXPECT_EQ(s.writes[7 + k].value, kFace);
        }
        for (int k = 0; k < 7; ++k) {
            EXPECT_EQ(s.writes[13 + k].what, SubsystemWriteKind::SHIELD_WATCH);
            EXPECT_EQ(s.writes[13 + k].index, k);
            EXPECT_EQ(s.writes[13 + k].sub, sh);
        }
    }
}

TEST(ShieldStep, ClampsToMaxAndSkipsFacesWithNoMax) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    w.m.set_floats(sh, Field::_max_shields,
                   {100.0, 0.0, 100.0, 100.0, 100.0, 100.0});
    w.m.set_floats(sh, Field::_current_shields,
                   {99.5, 7.0, 5.0, 5.0, 5.0, 5.0});
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(s, w.m);
    const std::vector<double> cur =
        w.m.get_floats(sh, Field::_current_shields);
    EXPECT_EQ(cur[0], 100.0);   // 99.5 + 2 * 0.5066... clamped
    EXPECT_EQ(cur[1], 7.0);     // max 0: never written
    EXPECT_EQ(w.m.get_floats(sh, Field::_ramp_fraction)[1], 0.0);
    size_t faces = 0;
    for (const SubsystemWrite& x : s.writes)
        if (x.what == SubsystemWriteKind::FACE) {
            EXPECT_NE(x.index, 1);
            ++faces;
        }
    EXPECT_EQ(faces, 5u);
}

TEST(ShieldStep, OfflineZeroesAllFaces) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    w.m.set_floats(sh, Field::_max_shields,
                   {100.0, 0.0, 100.0, 100.0, 100.0, 100.0});
    w.m.set_floats(sh, Field::_current_shields,
                   {40.0, 3.0, 5.0, 0.0, 5.0, 5.0});
    // Disabled: condition at or below DisabledPercentage x MaxCondition.
    w.m.set_f(sh, Field::_condition, 500.0);
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(s, w.m);
    // Every face, the max-0 one too, drops to zero; the ramp was refreshed
    // first, from the faces as they were.
    EXPECT_EQ(w.m.get_floats(sh, Field::_current_shields),
              std::vector<double>(6, 0.0));
    EXPECT_EQ(w.m.get_floats(sh, Field::_ramp_fraction)[0], 0.4);
    size_t faces = 0, watchers = 0;
    for (const SubsystemWrite& x : s.writes) {
        faces += x.what == SubsystemWriteKind::FACE;
        watchers += x.what == SubsystemWriteKind::SHIELD_WATCH;
    }
    EXPECT_EQ(faces, 6u);
    EXPECT_EQ(watchers, 7u);
    const std::vector<double> v =
        w.m.get_floats(sh, Field::shield_watch_values);
    for (int f = 0; f < 7; ++f) EXPECT_EQ(v[f], 0.0) << f;

    // Already all zero: nothing but the accumulator and the ramp.
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession again = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(again, w.m);
    ASSERT_EQ(again.writes.size(), 1u + 6u);
    for (size_t k = 1; k < again.writes.size(); ++k)
        EXPECT_EQ(again.writes[k].what, SubsystemWriteKind::RAMP);
}

TEST(ShieldStep, RadiationOutageIsOffline) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    w.m.set_i(sh, Field::_radiation_out, 1);
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(s, w.m);
    EXPECT_EQ(w.m.get_floats(sh, Field::_current_shields),
              std::vector<double>(6, 0.0));
}

TEST(ShieldStep, CrossingYieldsAnEvent) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    // Face 2 at 0.45 with a check at 0.5 (code 1: upward); the regen takes
    // it to 0.4501..., no crossing. At 0.499 it crosses.
    std::vector<double> checks(7, 0.0);
    checks[2] = 1.0;
    checks.insert(checks.begin() + 3, {0.5, 1.0});
    w.m.set_floats(sh, Field::shield_watch_checks, checks);
    w.m.set_floats(sh, Field::_current_shields,
                   {5.0, 5.0, 49.9, 5.0, 5.0, 5.0});
    std::vector<double> vals(7, 0.05);
    vals[2] = 0.499;
    w.m.set_floats(sh, Field::shield_watch_values, vals);
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    const SubsystemRecord r = subsystems::next(s, w.m);
    ASSERT_EQ(r.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(r.kind),
              SubsystemEvent::SHIELD_WATCHER);
    EXPECT_EQ(r.code, 2);
    EXPECT_EQ(r.sub, sh);
    const double face2 = w.m.get_floats(sh, Field::_current_shields)[2];
    EXPECT_EQ(r.a, face2 / 100.0);
    EXPECT_GE(r.a, 0.5);
    // Watchers 0 and 1 were written before it; 2 is left to Python's
    // _update (its old value stays until Python commits and pushes it).
    size_t watchers = 0;
    for (const SubsystemWrite& x : s.writes)
        watchers += x.what == SubsystemWriteKind::SHIELD_WATCH;
    EXPECT_EQ(watchers, 2u);
    EXPECT_EQ(w.m.get_floats(sh, Field::shield_watch_values)[2], 0.499);

    // The handler (Python) turned the generator off: the watchers after it
    // read the generator off, from the mirror as it is now.
    w.m.set_i(sh, Field::_is_on, 0);
    const SubsystemRecord next = subsystems::next(s, w.m);
    ASSERT_EQ(next.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(static_cast<SubsystemPiece>(next.kind), SubsystemPiece::POWER);
    ASSERT_EQ(s.writes.size(), 4u);     // watchers 3..6, nothing else
    for (int k = 0; k < 4; ++k) {
        EXPECT_EQ(s.writes[k].what, SubsystemWriteKind::SHIELD_WATCH);
        EXPECT_EQ(s.writes[k].index, 3 + k);
        EXPECT_EQ(s.writes[k].value, 0.0);
    }
}

TEST(ShieldStep, CheckDirectionsAndUncrossedChecksWrite) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    // Face 0: a downward-only check (code 2) the upward move cannot fire;
    // face 1: an upward check above the new value.
    std::vector<double> checks = {1.0, 0.06, 2.0, 1.0, 0.9, 1.0,
                                  0.0, 0.0, 0.0, 0.0, 0.0};
    w.m.set_floats(sh, Field::shield_watch_checks, checks);
    w.m.set_floats(sh, Field::shield_watch_values,
                   std::vector<double>(7, 0.05));
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    const SubsystemRecord r = subsystems::next(s, w.m);
    EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
    size_t watchers = 0;
    for (const SubsystemWrite& x : s.writes)
        watchers += x.what == SubsystemWriteKind::SHIELD_WATCH;
    EXPECT_EQ(watchers, 7u);

    // Downward through 0.06 now fires the code-2 check.
    w.m.set_floats(sh, Field::_current_shields, std::vector<double>(6, 1.0));
    w.m.set_floats(sh, Field::shield_watch_values,
                   std::vector<double>(7, 0.07));
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    w.m.set_floats(sh, Field::_charge_per_second, std::vector<double>(6, 0.0));
    SubsystemSession down = subsystems::begin(w.m, std::vector{ship}, kDt);
    const SubsystemRecord d = subsystems::next(down, w.m);
    ASSERT_EQ(d.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(d.code, 0);
    EXPECT_EQ(d.a, 0.01);
}

TEST(ShieldStep, ARowGoneMidLoopHandsTheTailToPython) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    std::vector<double> checks(7, 0.0);
    checks[0] = 1.0;
    checks.insert(checks.begin() + 1, {0.06, 3.0});
    w.m.set_floats(sh, Field::shield_watch_checks, checks);
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    const SubsystemRecord r = subsystems::next(s, w.m);
    ASSERT_EQ(r.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(r.code, 0);
    // Its handler dropped the generator's row (native_combat._drop).
    w.m.unregister_row(sh);
    const SubsystemRecord t = subsystems::next(s, w.m);
    ASSERT_EQ(t.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(t.kind),
              SubsystemEvent::SHIELD_WATCHER_TAIL);
    EXPECT_EQ(t.code, 1);
    EXPECT_EQ(t.sub, sh);
    EXPECT_TRUE(t.ship == ship);
    EXPECT_EQ(subsystems::next(s, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::POWER));
}

TEST(ShieldStep, NoShieldIsNoRecordAndUnreadyIsPythons) {
    World w;
    const int64_t none = w.bare_ship();
    const int64_t foreign = w.bare_ship();
    const int64_t sh = w.shield(foreign);
    w.m.set_i(sh, Field::shield_watch_ok, 0);   // a watcher not adopted
    const std::vector<int64_t> ships = {none, foreign};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const auto all = drain(s, w.m);
    ASSERT_EQ(all.size(), 4u + 5u);
    EXPECT_EQ(all[0].kind, static_cast<int32_t>(SubsystemPiece::POWER));
    EXPECT_EQ(all[4].ship_pos, 1);
    EXPECT_EQ(all[4].kind, static_cast<int32_t>(SubsystemPiece::SHIELD));
    EXPECT_TRUE(s.writes.empty());

    // python_pieces (the test-facing hook): every ship's SHIELD is Python's.
    const int64_t ready = w.bare_ship();
    w.shield(ready);
    SubsystemSession p = subsystems::begin(
        w.m, std::vector{ready}, kDt, piece_bit(SubsystemPiece::SHIELD));
    EXPECT_EQ(subsystems::next(p, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::SHIELD));
    EXPECT_TRUE(p.writes.empty());
}

TEST(ShieldStep, AnUnanswerableOfflineQuestionWritesNothing) {
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    // A parent ship the mirror cannot prove is a ShipClass: _out_of_action
    // is Python's (is_offline_after_condition throws).
    w.m.set_i(sh, Field::has_parent_ship_getter, 1);
    w.m.set_ref(sh, Field::_parent_ship, ship);
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
    const SubsystemRecord r = subsystems::next(s, w.m);
    EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(r.kind, static_cast<int32_t>(SubsystemPiece::SHIELD));
    EXPECT_TRUE(s.writes.empty());
    EXPECT_EQ(w.m.get_f(sh, Field::_charge_accum), 0.49);
}

// ── The power piece (subsystem_step.h THE POWER PIECE) ───────────────────
// Ticks of 0.5 s against the 1.0 s interval keep every sum exact: a clock
// at 0.5 reaches the interval with elapsed exactly 1.0.

namespace {

constexpr double kHalf = 0.5;

// One stage over `ship` (no shield generator): runs the POWER piece and
// returns the first record after it (CLOAK's RUN_PYTHON when it ran
// natively to the end).
SubsystemRecord after_power(World& w, SubsystemSession& s) {
    return subsystems::next(s, w.m);
}

bool logged(const SubsystemSession& s, SubsystemWriteKind k, int64_t sub) {
    for (const SubsystemWrite& x : s.writes)
        if (x.what == k && x.sub == sub) return true;
    return false;
}

}  // namespace

TEST(PowerStep, IntervalResetNotSubtract) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(100.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.75);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = after_power(w, s);
    ASSERT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(static_cast<SubsystemPiece>(r.kind), SubsystemPiece::CLOAK);
    // 0.75 + 0.5 = 1.25 >= 1.0: elapsed 1.25, the clock RESET to 0 (a
    // subtract would leave 0.25).
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.0);
    // Recharge 100 * 1.0 * 1.25 into main; budgets min(battery, cap*1.25).
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 625.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_battery_power), 500.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_conduit_current), 625.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_conduit_current), 500.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_available_power), 1125.0);
    EXPECT_TRUE(logged(s, SubsystemWriteKind::INTERVAL_ELAPSED, ps));
    EXPECT_TRUE(logged(s, SubsystemWriteKind::AVAILABLE_POWER, ps));
    // Both watchers took their fractions, 625/1000 and 500/1000.
    EXPECT_EQ(w.m.get_floats(ps, Field::power_watch_values),
              (std::vector<double>{0.625, 0.5}));

    // The next tick is inside the interval: only the clock moves.
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, t);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 625.0);
    EXPECT_FALSE(logged(t, SubsystemWriteKind::AVAILABLE_POWER, ps));
}

TEST(PowerStep, MainSpillsToBackup) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(300.0, 1000.0, 200.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 900.0, 150.0, 0.5);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, s);
    // 300 generated: 100 fills main, 50 of the 200 spilled fills backup,
    // the other 150 is discarded.
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 1000.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_battery_power), 200.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_available_power), 1200.0);
}

TEST(PowerStep, OfflineSkipsTheRechargeNotTheBudgets) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(300.0, 1000.0, 1000.0, 1000.0, 50.0);
    const int64_t ps = w.plant(ship, prop, 900.0, 150.0, 0.5);
    w.m.set_f(ps, Field::_condition, 400.0);    // disabled: <= 0.5 * 1000
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, s);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 900.0);
    // main budget health-scaled: min(900, 1000 * 0.4 * 1.0); backup not.
    EXPECT_EQ(w.m.get_f(ps, Field::_main_conduit_current), 400.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_conduit_current), 50.0);
}

TEST(PowerStep, NoPropertySkipsPump) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t ps = w.plant(ship, -1, 500.0, 500.0, 0.5);
    const int64_t c = w.consumer(ship, 0, 60.0);
    w.m.set_f(c, Field::_power_wanted, 7.0);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = after_power(w, s);
    EXPECT_EQ(static_cast<SubsystemPiece>(r.kind), SubsystemPiece::CLOAK);
    // Update returned at `prop is None`: no clock, no pump, no watchers.
    EXPECT_TRUE(s.writes.empty());
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);
    EXPECT_EQ(w.m.get_f(c, Field::_power_wanted), 7.0);
    EXPECT_EQ(w.m.get_floats(ps, Field::power_watch_values),
              (std::vector<double>{1.0, 1.0}));
}

TEST(PowerStep, DirectMainFallsToElseBranch) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.5);
    // PSM_DIRECT_MAIN (3) on a conduit consumer: _draw's final else, i.e.
    // backup only. Then a main-first one, which takes main.
    const int64_t direct = w.consumer(ship, 0, 60.0, 3);
    const int64_t main = w.consumer(ship, 0, 20.0, 0);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, s);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_battery_power), 470.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_conduit_current), 470.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 490.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_conduit_current), 490.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_power_dispensed), 40.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_power_wanted_total), 40.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_power_wanted), 30.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_power_received), 30.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_efficiency), 1.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_power_factor), 1.0);
    EXPECT_EQ(w.m.get_f(main, Field::_power_received), 10.0);

    // A backup-only draw with backup empty starves: main is never touched.
    w.m.set_f(ps, Field::_backup_battery_power, 0.0);
    w.m.set_f(ps, Field::_interval_elapsed, 0.5);
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, t);
    EXPECT_EQ(w.m.get_f(direct, Field::_power_received), 0.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_efficiency), 0.0);
    EXPECT_EQ(w.m.get_f(direct, Field::_power_factor), 0.0);
}

TEST(PowerStep, TractorAndCloakStealsNotDispensed) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 600.0, 0.5);
    // A tractor system holding a beam: a flat StealPower(normal*dt) from
    // main, unscaled by the slider (its wanted IS scaled).
    const int64_t tractor = w.consumer(ship, 1, 100.0);
    w.m.set_i(tractor, Field::DRAWS_DIRECT_FROM_MAIN, 1);
    w.m.set_f(tractor, Field::_power_percentage_wanted, 1.25);
    const int64_t beam = w.m.register_row(Kind::Subsystem);
    w.m.set_i(beam, Field::weapon_kind, 7);
    w.m.set_i(beam, Field::_firing, 1);
    w.m.set_ids(tractor, Field::_children, {beam});
    // A cloak trying to cloak: StealPowerFromReserve(1000 * dt).
    const int64_t cloak = w.consumer(ship, 2, 0.0, 2);
    w.m.set_i(cloak, Field::_cloak_state, 2);
    w.m.set_f(cloak, Field::CLOAK_RESERVE_DRAIN_PER_SECOND, 1000.0);
    // ... and a conduit consumer, the only one dispensed.
    const int64_t sensors = w.consumer(ship, 0, 40.0);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, s);
    EXPECT_EQ(w.m.get_f(tractor, Field::_power_wanted), 62.5);
    EXPECT_EQ(w.m.get_f(tractor, Field::_power_received), 50.0);
    EXPECT_EQ(w.m.get_f(tractor, Field::_efficiency), 1.0);
    EXPECT_EQ(w.m.get_f(cloak, Field::_power_wanted), 500.0);
    EXPECT_EQ(w.m.get_f(cloak, Field::_power_received), 500.0);
    EXPECT_EQ(w.m.get_f(cloak, Field::_backup_reserve), 100.0);
    EXPECT_EQ(w.m.get_f(sensors, Field::_power_received), 20.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 430.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_battery_power), 100.0);
    // The steals bypass the conduits and the dispensed total.
    EXPECT_EQ(w.m.get_f(ps, Field::_main_conduit_current), 480.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_backup_conduit_current), 600.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_power_dispensed), 20.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_power_wanted_total), 582.5);

    // Idle (no beam firing, cloak decloaked): both zeroed, the cloak's
    // reserve snapshot still taken.
    w.m.set_i(beam, Field::_firing, 0);
    w.m.set_i(cloak, Field::_cloak_state, 0);
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    after_power(w, t);
    for (int64_t c : {tractor, cloak}) {
        EXPECT_EQ(w.m.get_f(c, Field::_power_wanted), 0.0);
        EXPECT_EQ(w.m.get_f(c, Field::_power_received), 0.0);
        EXPECT_EQ(w.m.get_f(c, Field::_efficiency), 0.0);
        EXPECT_EQ(w.m.get_f(c, Field::_power_factor), 0.0);
    }
    EXPECT_EQ(w.m.get_f(cloak, Field::_backup_reserve), 100.0);
    EXPECT_TRUE(logged(t, SubsystemWriteKind::BACKUP_RESERVE, cloak));
}

TEST(PowerStep, BatteryWatcherCrossingYieldsAnEvent) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 510.0, 500.0, 0.0);
    w.m.set_floats(ps, Field::power_watch_values, {0.51, 0.5});
    // Main: a downward check at 0.5 (code 2); backup: none.
    w.m.set_floats(ps, Field::power_watch_checks, {1.0, 0.5, 2.0, 0.0});
    w.m.set_f(ps, Field::_main_conduit_current, 1000.0);
    w.consumer(ship, 0, 60.0);              // takes 30 from main
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = after_power(w, s);
    ASSERT_EQ(r.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(r.kind),
              SubsystemEvent::BATTERY_WATCHER);
    EXPECT_EQ(r.code, 0);
    EXPECT_EQ(r.sub, ps);
    EXPECT_EQ(r.a, 480.0 / 1000.0);
    // Everything before it is written; the watcher's value is Python's.
    EXPECT_TRUE(logged(s, SubsystemWriteKind::MAIN_BATTERY, ps));
    EXPECT_EQ(w.m.get_floats(ps, Field::power_watch_values)[0], 0.51);
    // The handler halved the backup battery: the backup watcher reads it
    // as it is now.
    w.m.set_f(ps, Field::_backup_battery_power, 250.0);
    const SubsystemRecord n = subsystems::next(s, w.m);
    EXPECT_EQ(static_cast<SubsystemPiece>(n.kind), SubsystemPiece::CLOAK);
    ASSERT_EQ(s.writes.size(), 1u);
    EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::BATTERY_WATCH);
    EXPECT_EQ(s.writes[0].index, 1);
    EXPECT_EQ(s.writes[0].value, 0.25);

    // A row gone between the two: the backup line is Python's (the tail),
    // fed the backup limit read before the main watcher.
    w.m.set_floats(ps, Field::power_watch_values, {0.51, 0.25});
    w.m.set_f(ps, Field::_main_battery_power, 510.0);
    SubsystemSession u = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_EQ(subsystems::next(u, w.m).type, SubsystemRecordType::EVENT);
    w.m.unregister_row(ps);
    const SubsystemRecord tail = subsystems::next(u, w.m);
    ASSERT_EQ(tail.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(tail.kind),
              SubsystemEvent::POWER_TAIL);
    EXPECT_EQ(tail.code, 1);
    EXPECT_EQ(tail.a, 1000.0);
    EXPECT_EQ(tail.sub, ps);
}

TEST(PowerStep, BreachIsAnEventBeforeTheRest) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.0);
    w.m.set_f(ps, Field::_condition, 0.0);      // destroyed
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = after_power(w, s);
    ASSERT_EQ(r.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(r.kind), SubsystemEvent::BREACH);
    EXPECT_EQ(r.sub, ps);
    ASSERT_EQ(s.writes.size(), 1u);
    EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::BREACH_FIRED);
    EXPECT_EQ(w.m.get_i(ps, Field::_breach_fired), 1);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.0);
    // The rest of Update after it.
    EXPECT_EQ(static_cast<SubsystemPiece>(subsystems::next(s, w.m).kind),
              SubsystemPiece::CLOAK);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);
    // Latched: never again.
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(subsystems::next(t, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::CLOAK));
}

TEST(PowerStep, AnUnreadyPlantIsPythonsWithNothingWritten) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(100.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.5);
    w.m.set_f(ps, Field::_condition, 0.0);      // a breach is due
    w.consumer(ship, 0, 60.0);
    std::vector<int64_t> list = w.m.get_ids(ship, Field::_powered_consumers);
    list.push_back(kRefUnrepresentable);        // a consumer with no row
    w.m.set_ids(ship, Field::_powered_consumers, list);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = after_power(w, s);
    EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(static_cast<SubsystemPiece>(r.kind), SubsystemPiece::POWER);
    EXPECT_TRUE(s.writes.empty());
    EXPECT_EQ(w.m.get_i(ps, Field::_breach_fired), 0);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);

    // A property whose values are not all read through its data bag.
    list.pop_back();
    w.m.set_ids(ship, Field::_powered_consumers, list);
    w.m.set_i(prop, Field::power_props_ok, 0);
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(subsystems::next(t, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::POWER));
    EXPECT_TRUE(t.writes.empty());

    // python_pieces (the test-facing hook).
    w.m.set_i(prop, Field::power_props_ok, 1);
    SubsystemSession p = subsystems::begin(
        w.m, std::vector{ship}, kHalf, piece_bit(SubsystemPiece::POWER));
    EXPECT_EQ(subsystems::next(p, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::POWER));
    EXPECT_TRUE(p.writes.empty());
    // No plant at all: no call, no record.
    w.m.set_ref(ship, Field::_power_subsystem, -1);
    SubsystemSession none = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(subsystems::next(none, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::CLOAK));
}
