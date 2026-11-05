// The subsystem stage session (subsystem_step.h) on hand-built mirror rows:
// its walk order, its pieces, and THE SKIPS (a piece the mirror cannot run,
// a row freed mid-walk). The Python side is
// tests/unit/test_native_subsystems_*.py and the goldens.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
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
constexpr double kHalf = 0.5;  // exact against the 1.0 s power interval

struct World {
    TransformStore store;
    Mirror m{store};

    // A ship whose four subsystems the mirror cannot name
    // (kRefUnrepresentable): each of its SHIELD, POWER, CLOAK and REPAIR
    // pieces is a REF skip, and its walk is ARTICULATION's RUN_PYTHON alone
    // (the walk-order tests below).
    int64_t ship() {
        const int64_t h = bare_ship();
        m.set_ref(h, Field::_shield_subsystem, kRefUnrepresentable);
        m.set_ref(h, Field::_power_subsystem, kRefUnrepresentable);
        m.set_ref(h, Field::_cloaking_subsystem, kRefUnrepresentable);
        m.set_ref(h, Field::_repair_subsystem, kRefUnrepresentable);
        return h;
    }

    // A ship with no subsystems at all (every ref None: no call); shield()
    // gives it a generator. Its walk ends with ARTICULATION's RUN_PYTHON.
    int64_t bare_ship() {
        auto [xi, xg] = store.alloc();
        return m.register_row(Kind::Object, xi, xg);
    }

    // A ShipClass row with no shield generator and no plant yet: plant()
    // gives it one, consumer() its consumers.
    int64_t power_ship() {
        auto [xi, xg] = store.alloc();
        const int64_t h = m.register_row(Kind::Object, xi, xg);
        m.set_i(h, Field::is_ship_class, 1);
        return h;
    }

    // A ShipClass row with no shield generator, plant, cloak or bay (all
    // None: no call); cloak() and bay() give it the last two. Its walk
    // ends with ARTICULATION's RUN_PYTHON.
    int64_t stage_ship() {
        auto [xi, xg] = store.alloc();
        const int64_t h = m.register_row(Kind::Object, xi, xg);
        m.set_i(h, Field::is_ship_class, 1);
        return h;
    }

    // A healthy leaf subsystem: condition 1000 of 1000, disabled at half.
    int64_t healthy() {
        const int64_t h = m.register_row(Kind::Subsystem);
        m.set_f(h, Field::_max_condition, 1000.0);
        m.set_f(h, Field::_condition, 1000.0);
        m.set_f(h, Field::_disabled_percentage, 0.5);
        m.set_f(h, Field::_repair_complexity, 1.0);
        return h;
    }

    // A healthy cloak on `ship` in `state` (0 DECLOAKED, 1 CLOAKING, 2
    // CLOAKED, 3 DECLOAKING), its clock at `elapsed` of `duration`, the
    // stock 1000/s drain and a full reserve; MIN_RESERVE_TO_HOLD_CLOAK 0.
    int64_t cloak(int64_t ship, int64_t state, double elapsed,
                  double duration) {
        const int64_t h = healthy();
        m.set_i(h, Field::power_kind, 2);
        m.set_i(h, Field::_cloak_state, state);
        m.set_f(h, Field::_transition_elapsed, elapsed);
        m.set_f(h, Field::_transition_duration, duration);
        m.set_f(h, Field::CLOAK_RESERVE_DRAIN_PER_SECOND, 1000.0);
        m.set_f(h, Field::_backup_reserve, 5000.0);
        m.set_global_f(Global::MIN_RESERVE_TO_HOLD_CLOAK, 0.0);
        m.set_ref(ship, Field::_cloaking_subsystem, h);
        return h;
    }

    // A RepairSubsystemProperty read through its data bag.
    int64_t repair_prop(double points, int64_t teams) {
        const int64_t p = m.register_row(Kind::Property);
        m.set_f(p, Field::MaxRepairPoints, points);
        m.set_i(p, Field::NumRepairTeams, teams);
        m.set_i(p, Field::repair_props_ok, 1);
        return p;
    }

    // A repair bay on `ship`, at half condition (its percentage 0.5).
    int64_t bay(int64_t ship, int64_t prop) {
        const int64_t h = healthy();
        m.set_i(h, Field::is_repair_bay, 1);
        m.set_f(h, Field::_condition, 500.0);
        m.set_ref(h, Field::_property, prop);
        m.set_ref(ship, Field::_repair_subsystem, h);
        return h;
    }

    // A queued subsystem at `cond` of 1000 (its threshold state as the
    // state machine left it), `complexity` its GetRepairComplexity.
    int64_t item(double cond, double complexity = 1.0) {
        const int64_t h = healthy();
        m.set_f(h, Field::_condition, cond);
        m.set_f(h, Field::_repair_complexity, complexity);
        m.set_i(h, Field::_in_repair_queue, 1);
        m.set_i(h, Field::_threshold_state,
                cond <= 0.0 ? 2 : (cond <= 500.0 ? 1 : 0));
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

// The ship position of every record up to DONE, which must come last;
// each must be ARTICULATION's RUN_PYTHON.
std::vector<int64_t> walk(SubsystemSession& s, Mirror& m) {
    std::vector<int64_t> out;
    for (int guard = 0; guard < 1000; ++guard) {
        const SubsystemRecord r = subsystems::next(s, m);
        if (r.type == SubsystemRecordType::DONE) {
            EXPECT_EQ(r.code, static_cast<int64_t>(s.skips.size()));
            return out;
        }
        EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(static_cast<SubsystemPiece>(r.kind),
                  SubsystemPiece::ARTICULATION);
        out.push_back(r.ship_pos);
    }
    ADD_FAILURE() << "the session never returned DONE";
    return out;
}

constexpr SubsystemPiece kSkippable[] = {
    SubsystemPiece::SHIELD, SubsystemPiece::POWER, SubsystemPiece::CLOAK,
    SubsystemPiece::REPAIR};

// The session's skips from `from` on are `ship_pos`'s four pieces, `why`.
void expect_four_skips(const SubsystemSession& s, size_t from,
                       int64_t ship_pos, SubsystemSkip why) {
    ASSERT_GE(s.skips.size(), from + 4);
    for (size_t k = 0; k < 4; ++k) {
        const SubsystemSkipRecord& r = s.skips[from + k];
        EXPECT_EQ(r.ship_pos, ship_pos) << k;
        EXPECT_EQ(r.piece, kSkippable[k]) << k;
        EXPECT_EQ(r.why, why) << k;
    }
}

}  // namespace

TEST(SubsystemStep, UnnamedSubsystemsAreSkippedShipThenPiece) {
    World w;
    subsystems::reset_skip_counts();
    const std::vector<int64_t> ships = {w.ship(), w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    EXPECT_EQ(s.dt, kDt);
    // Each record names its ship's handle too: only ARTICULATION comes back.
    std::vector<SubsystemRecord> records;
    for (;;) {
        const SubsystemRecord r = subsystems::next(s, w.m);
        if (r.type == SubsystemRecordType::DONE) {
            EXPECT_EQ(r.code, 12);      // the session's skips
            break;
        }
        records.push_back(r);
        ASSERT_LT(records.size(), 100u);
    }
    ASSERT_EQ(records.size(), 3u);
    for (size_t k = 0; k < records.size(); ++k) {
        EXPECT_EQ(records[k].type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(records[k].ship_pos, static_cast<int64_t>(k));
        EXPECT_EQ(static_cast<SubsystemPiece>(records[k].kind),
                  SubsystemPiece::ARTICULATION);
        EXPECT_EQ(records[k].ship, ships[k]);
    }
    // THE SKIPS: in walk order, each with the ref it could not name.
    ASSERT_EQ(s.skips.size(), 12u);
    for (int64_t i = 0; i < 3; ++i)
        expect_four_skips(s, static_cast<size_t>(4 * i), i, SubsystemSkip::REF);
    EXPECT_EQ(s.skips[0].sub, kRefUnrepresentable);
    // ... and counted process-wide, per (piece, reason).
    for (SubsystemPiece p : kSkippable)
        EXPECT_EQ(subsystems::skip_count(p, SubsystemSkip::REF), 3u);
    EXPECT_EQ(subsystems::skip_count(SubsystemPiece::SHIELD,
                                     SubsystemSkip::NO_ROW), 0u);
    subsystems::reset_skip_counts();
    EXPECT_EQ(subsystems::skip_count(SubsystemPiece::SHIELD,
                                     SubsystemSkip::REF), 0u);
    // DONE is the end: asking again is a protocol error.
    EXPECT_THROW(subsystems::next(s, w.m), std::logic_error);
}

TEST(SubsystemStep, AFreedRowSkipsTheRestOfThatShip) {
    // A row freed mid-walk while its object lives on (native_combat._drop):
    // there is no Python stage to hand its pieces to, so they are skipped
    // (LOST_ROW, ruling R8-2); its ARTICULATION, whose Python is kept, still
    // comes back.
    World w;
    const std::vector<int64_t> ships = {w.bare_ship(), w.bare_ship(),
                                        w.bare_ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const SubsystemRecord first = subsystems::next(s, w.m);
    ASSERT_EQ(first.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(first.ship_pos, 0);
    // A handler run for that record dropped the second ship's row.
    w.m.unregister_row(ships[1]);
    EXPECT_EQ(walk(s, w.m), (std::vector<int64_t>{1, 2}));
    ASSERT_EQ(s.skips.size(), 4u);
    expect_four_skips(s, 0, 1, SubsystemSkip::LOST_ROW);
    EXPECT_EQ(s.lost_row[1], 1);
}

TEST(SubsystemStep, FreedBetweenPiecesSkipsTheRestOfThatShip) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t ps = w.plant(
        ship, w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0), 500.0,
        500.0, 0.0);
    w.m.set_f(ps, Field::_condition, 0.0);      // a breach is due
    const std::vector<int64_t> ships = {ship, w.bare_ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const SubsystemRecord breach = subsystems::next(s, w.m);
    ASSERT_EQ(breach.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(breach.ship_pos, 0);
    // The BREACH handler cannot drop rows (it queues a deferred entry);
    // were the plant's row gone, the rest of the piece is a skip
    // (POST_BREACH_UNREADY), never a throw out of the stage.
    w.m.unregister_row(ps);
    EXPECT_EQ(walk(s, w.m), (std::vector<int64_t>{0, 1}));
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].piece, SubsystemPiece::POWER);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::POST_BREACH_UNREADY);
    EXPECT_EQ(s.skips[0].sub, ps);

    // Between pieces: ship 0's POWER piece ended with an EVENT; its handler
    // dropped the ship's row. CLOAK and REPAIR are skipped, LOST_ROW; a new
    // row reusing the slot does not revive it.
    World v;
    const int64_t ship0 = v.power_ship();
    const int64_t p0 = v.plant(
        ship0, v.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0), 510.0,
        500.0, 0.0);
    v.m.set_floats(p0, Field::power_watch_values, {0.51, 0.5});
    v.m.set_floats(p0, Field::power_watch_checks, {1.0, 0.5, 2.0, 0.0});
    v.m.set_f(p0, Field::_main_conduit_current, 1000.0);
    v.consumer(ship0, 0, 60.0);
    const std::vector<int64_t> both = {ship0, v.bare_ship()};
    SubsystemSession t = subsystems::begin(v.m, both, kHalf);
    ASSERT_EQ(subsystems::next(t, v.m).type, SubsystemRecordType::EVENT);
    v.m.unregister_row(ship0);
    v.bare_ship();
    EXPECT_EQ(walk(t, v.m), (std::vector<int64_t>{0, 1}));
    ASSERT_EQ(t.skips.size(), 2u);
    EXPECT_EQ(t.skips[0].piece, SubsystemPiece::CLOAK);
    EXPECT_EQ(t.skips[1].piece, SubsystemPiece::REPAIR);
    for (const SubsystemSkipRecord& k : t.skips) {
        EXPECT_EQ(k.why, SubsystemSkip::LOST_ROW);
        EXPECT_EQ(k.ship_pos, 0);
    }
    EXPECT_EQ(t.lost_row[0], 1);
    EXPECT_EQ(t.lost_row[1], 0);
}

TEST(SubsystemStep, AShipWithNoRowIsSkipped) {
    // A ship the mirror has no row for (-1 or a handle already stale at
    // begin): its four pieces are NO_ROW skips; ARTICULATION comes back.
    World w;
    const int64_t gone = w.ship();
    w.m.unregister_row(gone);
    const std::vector<int64_t> ships = {-1, gone};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    EXPECT_EQ(walk(s, w.m), (std::vector<int64_t>{0, 1}));
    ASSERT_EQ(s.skips.size(), 8u);
    expect_four_skips(s, 0, 0, SubsystemSkip::NO_ROW);
    expect_four_skips(s, 4, 1, SubsystemSkip::NO_ROW);
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
        // The shield piece is native; then ARTICULATION, Python's.
        ASSERT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(static_cast<SubsystemPiece>(r.kind),
                  SubsystemPiece::ARTICULATION);
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
    // Face 3 already held 0.0: that write is identical, so not logged.
    EXPECT_EQ(faces, 5u);
    EXPECT_EQ(watchers, 7u);
    size_t ramps = 0;   // a first ramp is always logged, faces 1 and 3 too
    for (const SubsystemWrite& x : s.writes)
        ramps += x.what == SubsystemWriteKind::RAMP;
    EXPECT_EQ(ramps, 6u);
    const std::vector<double> v =
        w.m.get_floats(sh, Field::shield_watch_values);
    for (int f = 0; f < 7; ++f) EXPECT_EQ(v[f], 0.0) << f;

    // Already all zero, every face ramped once: nothing but the accumulator
    // and the ramp of the four faces whose fraction moves (faces 1 and 3 are
    // set and already read 0.0: identical).
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession again = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(again, w.m);
    ASSERT_EQ(again.writes.size(), 1u + 4u);
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
    EXPECT_EQ(static_cast<SubsystemPiece>(next.kind),
              SubsystemPiece::ARTICULATION);
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
              static_cast<int32_t>(SubsystemPiece::ARTICULATION));
}

TEST(ShieldStep, NoShieldIsNoRecordAndUnreadyIsSkipped) {
    World w;
    const int64_t none = w.bare_ship();
    const int64_t foreign = w.bare_ship();
    const int64_t sh = w.shield(foreign);
    w.m.set_i(sh, Field::shield_watch_ok, 0);   // a watcher not adopted
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    const std::vector<int64_t> ships = {none, foreign};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    EXPECT_EQ(walk(s, w.m), (std::vector<int64_t>{0, 1}));
    EXPECT_TRUE(s.writes.empty());
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].ship_pos, 1);
    EXPECT_EQ(s.skips[0].piece, SubsystemPiece::SHIELD);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::SHIELD_UNREADY);
    EXPECT_EQ(s.skips[0].sub, sh);
    EXPECT_EQ(w.m.get_f(sh, Field::_charge_accum), 0.49);
    // A face list not six long is not ready either.
    w.m.set_i(sh, Field::shield_watch_ok, 1);
    w.m.set_floats(sh, Field::_current_shields, {5.0});
    SubsystemSession t = subsystems::begin(w.m, std::vector{foreign}, kDt);
    walk(t, w.m);
    ASSERT_EQ(t.skips.size(), 1u);
    EXPECT_EQ(t.skips[0].why, SubsystemSkip::SHIELD_UNREADY);
    // A generator the mirror cannot name, or one freed: REF.
    w.m.set_ref(foreign, Field::_shield_subsystem, kRefUnrepresentable);
    SubsystemSession u = subsystems::begin(w.m, std::vector{foreign}, kDt);
    walk(u, w.m);
    ASSERT_EQ(u.skips.size(), 1u);
    EXPECT_EQ(u.skips[0].why, SubsystemSkip::REF);
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
    EXPECT_EQ(r.kind, static_cast<int32_t>(SubsystemPiece::ARTICULATION));
    EXPECT_TRUE(s.writes.empty());
    EXPECT_EQ(w.m.get_f(sh, Field::_charge_accum), 0.49);
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].piece, SubsystemPiece::SHIELD);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::OFFLINE);
}

// ── The power piece (subsystem_step.h THE POWER PIECE) ───────────────────
// Ticks of 0.5 s against the 1.0 s interval keep every sum exact: a clock
// at 0.5 reaches the interval with elapsed exactly 1.0.

namespace {

// One stage over `ship` (no shield generator): runs the POWER piece and
// returns the first record after it (ARTICULATION's RUN_PYTHON when it ran
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
    EXPECT_EQ(static_cast<SubsystemPiece>(r.kind),
              SubsystemPiece::ARTICULATION);
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
    EXPECT_EQ(static_cast<SubsystemPiece>(r.kind),
              SubsystemPiece::ARTICULATION);
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
    // The snapshot is unchanged (100.0 again): identical, so not logged.
    EXPECT_FALSE(logged(t, SubsystemWriteKind::BACKUP_RESERVE, cloak));
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
    EXPECT_EQ(static_cast<SubsystemPiece>(n.kind),
              SubsystemPiece::ARTICULATION);
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
              SubsystemPiece::ARTICULATION);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);
    // Latched: never again.
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(subsystems::next(t, w.m).kind,
              static_cast<int32_t>(SubsystemPiece::ARTICULATION));
}

TEST(PowerStep, AnUnreadyPlantIsSkippedWithNothingWritten) {
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(100.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.5);
    w.consumer(ship, 0, 60.0);
    // Each unready reason in turn: skipped, nothing written, counted under
    // its reason (a healthy plant: no breach due).
    const auto skipped = [&](SubsystemSkip why) {
        SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
        EXPECT_EQ(walk(s, w.m), std::vector<int64_t>{0});
        EXPECT_TRUE(s.writes.empty());
        ASSERT_EQ(s.skips.size(), 1u);
        EXPECT_EQ(s.skips[0].piece, SubsystemPiece::POWER);
        EXPECT_EQ(s.skips[0].why, why);
        EXPECT_EQ(s.skips[0].sub, ps);
        EXPECT_EQ(w.m.get_i(ps, Field::_breach_fired), 0);
        EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.5);
    };
    // A property whose values are not all read through its data bag.
    w.m.set_i(prop, Field::power_props_ok, 0);
    skipped(SubsystemSkip::PROPERTY);
    w.m.set_i(prop, Field::power_props_ok, 1);
    // Battery watchers not adopted.
    w.m.set_i(ps, Field::power_watch_ok, 0);
    skipped(SubsystemSkip::BATTERY_WATCH);
    w.m.set_i(ps, Field::power_watch_ok, 1);
    // A parent ship that is not a ShipClass row.
    w.m.set_i(ship, Field::is_ship_class, 0);
    skipped(SubsystemSkip::PARENT_SHIP);
    w.m.set_i(ship, Field::is_ship_class, 1);
    // The interval's offline question unanswerable: a healthy plant (so
    // IsDisabled / IsDestroyed do not answer it first) whose parent
    // subsystem the mirror cannot name.
    w.m.set_ref(ps, Field::_parent_subsystem, kRefUnrepresentable);
    skipped(SubsystemSkip::OFFLINE);
    w.m.set_ref(ps, Field::_parent_subsystem, -1);
    // A plant the mirror cannot name, or a row that is not a plant: REF.
    w.m.set_i(ps, Field::power_kind, 0);
    skipped(SubsystemSkip::REF);
    w.m.set_i(ps, Field::power_kind, 3);
    // No plant at all: no call, no record, no skip.
    w.m.set_ref(ship, Field::_power_subsystem, -1);
    SubsystemSession none = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(walk(none, w.m), std::vector<int64_t>{0});
    EXPECT_TRUE(none.skips.empty());
}

TEST(PowerStep, AnUnreadyConsumerIsSkippedAloneAndThePlantStillRuns) {
    // A consumer the pump cannot run is passed over and counted (CONSUMER,
    // that consumer only); the plant still recharges, sets its budgets,
    // feeds every other consumer and its watchers.
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(100.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.5);
    const int64_t ok = w.consumer(ship, 0, 60.0);
    std::vector<int64_t> list = w.m.get_ids(ship, Field::_powered_consumers);
    list.insert(list.begin(), kRefUnrepresentable);   // first in the order
    w.m.set_ids(ship, Field::_powered_consumers, list);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(walk(s, w.m), std::vector<int64_t>{0});
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].piece, SubsystemPiece::POWER);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::CONSUMER);
    EXPECT_EQ(s.skips[0].sub, kRefUnrepresentable);
    // 0.5 + 0.5 reaches the interval: recharged 100 into main, the clock
    // reset; the ready consumer drew its 30 (60/s x 0.5 s) from main.
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_main_battery_power), 570.0);
    EXPECT_EQ(w.m.get_f(ok, Field::_power_received), 30.0);
    EXPECT_EQ(w.m.get_f(ps, Field::_power_wanted_total), 30.0);
    EXPECT_EQ(w.m.get_floats(ps, Field::power_watch_values),
              (std::vector<double>{0.57, 0.5}));
}

TEST(PowerStep, ADestroyedPlantWithAnUnreadyConsumerStillBreaches) {
    // The breach check runs before readiness: an unready consumer cannot
    // keep a destroyed plant from latching its breach.
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.0);
    w.m.set_f(ps, Field::_condition, 0.0);      // destroyed
    w.m.set_ids(ship, Field::_powered_consumers, {kRefUnrepresentable});
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = subsystems::next(s, w.m);
    ASSERT_EQ(r.type, SubsystemRecordType::EVENT);
    EXPECT_EQ(static_cast<SubsystemEvent>(r.kind), SubsystemEvent::BREACH);
    EXPECT_EQ(w.m.get_i(ps, Field::_breach_fired), 1);
    EXPECT_EQ(walk(s, w.m), std::vector<int64_t>{0});
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::CONSUMER);
    // And a plant otherwise unready (its property) still breaches; the rest
    // of its tick is then that reason's skip.
    World v;
    const int64_t ship2 = v.power_ship();
    const int64_t prop2 = v.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps2 = v.plant(ship2, prop2, 500.0, 500.0, 0.0);
    v.m.set_f(ps2, Field::_condition, 0.0);
    v.m.set_i(prop2, Field::power_props_ok, 0);
    SubsystemSession t = subsystems::begin(v.m, std::vector{ship2}, kHalf);
    ASSERT_EQ(static_cast<SubsystemEvent>(subsystems::next(t, v.m).kind),
              SubsystemEvent::BREACH);
    walk(t, v.m);
    ASSERT_EQ(t.skips.size(), 1u);
    EXPECT_EQ(t.skips[0].why, SubsystemSkip::PROPERTY);
    EXPECT_EQ(v.m.get_f(ps2, Field::_interval_elapsed), 0.0);
}

TEST(PowerStep, APlantNoLongerReadyAfterItsBreachIsSkipped) {
    // Ready before the breach, unready after its handler (a property it
    // swapped): a POST_BREACH_UNREADY skip, counted; never a throw.
    World w;
    subsystems::reset_skip_counts();
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    const int64_t ps = w.plant(ship, prop, 500.0, 500.0, 0.0);
    w.m.set_f(ps, Field::_condition, 0.0);
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_EQ(static_cast<SubsystemEvent>(subsystems::next(s, w.m).kind),
              SubsystemEvent::BREACH);
    w.m.set_i(prop, Field::power_props_ok, 0);
    EXPECT_EQ(walk(s, w.m), std::vector<int64_t>{0});
    ASSERT_EQ(s.skips.size(), 1u);
    EXPECT_EQ(s.skips[0].why, SubsystemSkip::POST_BREACH_UNREADY);
    EXPECT_EQ(subsystems::skip_count(SubsystemPiece::POWER,
                                     SubsystemSkip::POST_BREACH_UNREADY), 1u);
    EXPECT_EQ(w.m.get_f(ps, Field::_interval_elapsed), 0.0);
}

// ── The cloak piece (Task 5; subsystem_step.h THE CLOAK PIECE) ───────────

namespace {

// The records of one stage over `ship`, to DONE; `writes` (when given)
// collects every next()'s write log.
std::vector<SubsystemRecord> stage(World& w, int64_t ship, double dt,
                                   std::vector<SubsystemWrite>* writes =
                                       nullptr) {
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, dt);
    std::vector<SubsystemRecord> out;
    for (int guard = 0; guard < 1000; ++guard) {
        const SubsystemRecord r = subsystems::next(s, w.m);
        if (writes != nullptr)
            writes->insert(writes->end(), s.writes.begin(), s.writes.end());
        if (r.type == SubsystemRecordType::DONE) return out;
        out.push_back(r);
    }
    ADD_FAILURE() << "the session never returned DONE";
    return out;
}

bool is_articulation(const SubsystemRecord& r) {
    return r.type == SubsystemRecordType::RUN_PYTHON &&
           static_cast<SubsystemPiece>(r.kind) == SubsystemPiece::ARTICULATION;
}

bool is_event(const SubsystemRecord& r, SubsystemEvent e) {
    return r.type == SubsystemRecordType::EVENT &&
           static_cast<SubsystemEvent>(r.kind) == e;
}

}  // namespace

TEST(CloakStep, CompletesAtDuration) {
    World w;
    const int64_t ship = w.stage_ship();
    const int64_t cl = w.cloak(ship, 1, 0.0, 1.0);
    // 0.5 s ticks against a 1.0 s transition: exact sums.
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_TRUE(is_articulation(subsystems::next(s, w.m)));
    EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), 0.5);
    EXPECT_EQ(w.m.get_i(cl, Field::_cloak_state), 1);
    ASSERT_EQ(s.writes.size(), 1u);
    EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::TRANSITION_ELAPSED);
    EXPECT_EQ(s.writes[0].value, 0.5);

    // At the duration: the state snaps and the clock resets, written in
    // Update's order, BEFORE the completion event Python fires.
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = subsystems::next(t, w.m);
    ASSERT_TRUE(is_event(r, SubsystemEvent::CLOAK_DONE));
    EXPECT_EQ(r.code, 1);          // cloaked
    EXPECT_EQ(r.sub, cl);
    EXPECT_EQ(w.m.get_i(cl, Field::_cloak_state), 2);
    EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), 0.0);
    ASSERT_EQ(t.writes.size(), 3u);
    EXPECT_EQ(t.writes[0].what, SubsystemWriteKind::TRANSITION_ELAPSED);
    EXPECT_EQ(t.writes[0].value, 1.0);
    EXPECT_EQ(t.writes[1].what, SubsystemWriteKind::CLOAK_STATE);
    EXPECT_EQ(t.writes[1].value, 2.0);
    EXPECT_EQ(t.writes[2].what, SubsystemWriteKind::TRANSITION_ELAPSED);
    EXPECT_EQ(t.writes[2].value, 0.0);
    // The event is the piece's last line: the walk goes on.
    EXPECT_TRUE(is_articulation(subsystems::next(t, w.m)));

    // CLOAKED holds: nothing moves.
    std::vector<SubsystemWrite> u;
    const auto held = stage(w, ship, kHalf, &u);
    ASSERT_EQ(held.size(), 1u);
    EXPECT_TRUE(is_articulation(held[0]));
    EXPECT_TRUE(u.empty());

    // DECLOAKING completes to DECLOAKED.
    w.m.set_i(cl, Field::_cloak_state, 3);
    w.m.set_f(cl, Field::_transition_elapsed, 0.75);
    const auto done = stage(w, ship, kHalf);
    ASSERT_EQ(done.size(), 2u);
    ASSERT_TRUE(is_event(done[0], SubsystemEvent::CLOAK_DONE));
    EXPECT_EQ(done[0].code, 0);    // decloaked
    EXPECT_EQ(w.m.get_i(cl, Field::_cloak_state), 0);

    // At 1/60 s against the stock 4.5 s: the tick Python's own
    // `e += 1/60` first reaches 4.5 on (the same additions here).
    w.m.set_i(cl, Field::_cloak_state, 1);
    w.m.set_f(cl, Field::_transition_elapsed, 0.0);
    w.m.set_f(cl, Field::_transition_duration, 4.5);
    double e = 0.0;
    int want = 0;
    while (true) {
        ++want;
        e = e + kDt;
        if (!(e < 4.5)) break;
    }
    int tick = 0;
    for (; tick < 1000; ++tick) {
        const auto recs = stage(w, ship, kDt);
        if (is_event(recs[0], SubsystemEvent::CLOAK_DONE)) break;
    }
    EXPECT_EQ(tick + 1, want);
}

TEST(CloakStep, ReserveOutForcesDecloak) {
    World w;
    const int64_t ship = w.stage_ship();
    const int64_t cl = w.cloak(ship, 2, 0.0, 4.5);
    // CLOAKED with the reserve dry: FORCE_DECLOAK, NOTHING written first
    // (Python's _force_decloak snaps the state itself).
    w.m.set_f(cl, Field::_backup_reserve, 0.0);
    std::vector<SubsystemWrite> s;
    auto recs = stage(w, ship, kDt, &s);
    ASSERT_EQ(recs.size(), 2u);
    ASSERT_TRUE(is_event(recs[0], SubsystemEvent::FORCE_DECLOAK));
    EXPECT_EQ(recs[0].sub, cl);
    EXPECT_TRUE(s.empty());
    EXPECT_EQ(w.m.get_i(cl, Field::_cloak_state), 2);
    EXPECT_TRUE(is_articulation(recs[1]));
    // CLOAKING too.
    w.m.set_i(cl, Field::_cloak_state, 1);
    EXPECT_TRUE(is_event(stage(w, ship, kDt)[0],
                         SubsystemEvent::FORCE_DECLOAK));
    // A free cloak (no drain) is never starved: the clock runs.
    w.m.set_f(cl, Field::CLOAK_RESERVE_DRAIN_PER_SECOND, 0.0);
    EXPECT_TRUE(is_articulation(stage(w, ship, kDt)[0]));
    EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), kDt);
    // Not trying to cloak (DECLOAKING): the dry reserve is no matter.
    w.m.set_f(cl, Field::CLOAK_RESERVE_DRAIN_PER_SECOND, 1000.0);
    w.m.set_i(cl, Field::_cloak_state, 3);
    w.m.set_f(cl, Field::_transition_elapsed, 0.0);
    EXPECT_TRUE(is_articulation(stage(w, ship, kDt)[0]));
    EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), kDt);

    // Disabled (IsDisabled: condition <= half of max): CLOAKING is forced
    // off; DECLOAKING and DECLOAKED do nothing at all, the clock included.
    w.m.set_f(cl, Field::_backup_reserve, 5000.0);
    w.m.set_f(cl, Field::_condition, 400.0);
    w.m.set_i(cl, Field::_cloak_state, 1);
    EXPECT_TRUE(is_event(stage(w, ship, kDt)[0],
                         SubsystemEvent::FORCE_DECLOAK));
    for (int64_t st : {0, 3}) {
        w.m.set_i(cl, Field::_cloak_state, st);
        w.m.set_f(cl, Field::_transition_elapsed, 0.25);
        std::vector<SubsystemWrite> q;
        EXPECT_TRUE(is_articulation(stage(w, ship, kDt, &q)[0]));
        EXPECT_TRUE(q.empty());
        EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), 0.25);
    }
    // Destroyed (the explicit flag) is offline too.
    w.m.set_f(cl, Field::_condition, 1000.0);
    w.m.set_i(cl, Field::_destroyed, 1);
    w.m.set_i(cl, Field::_cloak_state, 2);
    EXPECT_TRUE(is_event(stage(w, ship, kDt)[0],
                         SubsystemEvent::FORCE_DECLOAK));
    // A radiation outage is NOT the cloak's offline test (asymmetric
    // gates): the transition runs.
    w.m.set_i(cl, Field::_destroyed, 0);
    w.m.set_i(cl, Field::_radiation_out, 1);
    w.m.set_i(cl, Field::_cloak_state, 1);
    w.m.set_f(cl, Field::_transition_elapsed, 0.0);
    EXPECT_TRUE(is_articulation(stage(w, ship, kDt)[0]));
    EXPECT_EQ(w.m.get_f(cl, Field::_transition_elapsed), kDt);

    // A cloak the mirror cannot name, or a row that is not a cloak's: a
    // REF skip. No cloak: no call, no record, no skip.
    for (int64_t ref : {kRefUnrepresentable, cl}) {
        w.m.set_ref(ship, Field::_cloaking_subsystem, ref);
        if (ref == cl) w.m.set_i(cl, Field::power_kind, 0);
        SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kDt);
        EXPECT_EQ(walk(s, w.m), std::vector<int64_t>{0});
        ASSERT_EQ(s.skips.size(), 1u);
        EXPECT_EQ(s.skips[0].piece, SubsystemPiece::CLOAK);
        EXPECT_EQ(s.skips[0].why, SubsystemSkip::REF);
    }
    w.m.set_ref(ship, Field::_cloaking_subsystem, -1);
    SubsystemSession none = subsystems::begin(w.m, std::vector{ship}, kDt);
    EXPECT_EQ(walk(none, w.m), std::vector<int64_t>{0});
    EXPECT_TRUE(none.skips.empty());
}

// ── The repair piece (Task 5; subsystem_step.h THE REPAIR PIECE) ─────────

namespace {

double cond(World& w, int64_t h) { return w.m.get_f(h, Field::_condition); }

}  // namespace

TEST(RepairStep, SplitsPointsAcrossWorkedItems) {
    World w;
    const int64_t ship = w.stage_ship();
    const int64_t bay = w.bay(ship, w.repair_prop(60.0, 2));
    const int64_t a = w.item(100.0);
    const int64_t gone = w.item(0.0);           // destroyed: skipped
    const int64_t c = w.item(200.0, 2.0);       // twice as hard
    const int64_t d = w.item(300.0);            // no team left for it
    w.m.set_ids(bay, Field::_queue, {a, gone, c, d});
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    // The destroyed member is told once, mid-walk.
    const SubsystemRecord r = subsystems::next(s, w.m);
    ASSERT_TRUE(is_event(r, SubsystemEvent::REPAIR_CANNOT));
    EXPECT_EQ(r.code, bay);
    EXPECT_EQ(r.sub, gone);
    ASSERT_EQ(s.writes.size(), 1u);
    EXPECT_EQ(s.writes[0].what, SubsystemWriteKind::REPAIR_NOTIFIED);
    EXPECT_EQ(s.writes[0].index, 1);
    EXPECT_EQ(s.writes[0].ref, gone);
    EXPECT_EQ(w.m.get_ids(bay, Field::_cannot_complete_notified),
              std::vector<int64_t>{gone});
    EXPECT_EQ(cond(w, a), 100.0);               // nothing repaired yet
    // raw = 60 * 0.5 * 0.5 = 15 over the two worked: 7.5 each, c's halved.
    EXPECT_TRUE(is_articulation(subsystems::next(s, w.m)));
    EXPECT_EQ(cond(w, a), 107.5);
    EXPECT_EQ(cond(w, c), 203.75);
    EXPECT_EQ(cond(w, d), 300.0);
    EXPECT_EQ(cond(w, gone), 0.0);
    // The condition writes are set_condition's (damage.h), in item order.
    ASSERT_EQ(s.dmg.writes.size(), 2u);
    EXPECT_EQ(s.dmg.writes[0].handle, a);
    EXPECT_EQ(s.dmg.writes[1].handle, c);
    EXPECT_TRUE(s.dmg.entries.empty());   // no threshold crossed, queued

    // Told once: the next tick only repairs.
    std::vector<SubsystemWrite> t;
    const auto again = stage(w, ship, kHalf, &t);
    ASSERT_EQ(again.size(), 1u);
    EXPECT_TRUE(t.empty());
    EXPECT_EQ(cond(w, a), 115.0);

    // Brought back from destroyed (a script's SetCondition): it leaves the
    // notified set the first time the walk works it.
    w.m.set_f(gone, Field::_condition, 50.0);
    w.m.set_ids(bay, Field::_queue, {gone});
    std::vector<SubsystemWrite> u;
    stage(w, ship, kHalf, &u);
    ASSERT_EQ(u.size(), 1u);
    EXPECT_EQ(u[0].what, SubsystemWriteKind::REPAIR_NOTIFIED);
    EXPECT_EQ(u[0].index, 0);
    EXPECT_EQ(u[0].ref, gone);
    EXPECT_TRUE(w.m.get_ids(bay, Field::_cannot_complete_notified).empty());
    EXPECT_EQ(cond(w, gone), 65.0);             // the whole 15 on one item

    // Completion: clamped to max, then REPAIR_DONE (Python discards it and
    // fires ET_REPAIR_COMPLETED); the threshold machine's OPERATIONAL is an
    // effect-queue entry, as SetCondition's native chain queues it.
    const int64_t e = w.item(499.0);
    const int64_t f = w.item(990.0);
    w.m.set_ids(bay, Field::_queue, {e, f});
    w.m.set_f(bay, Field::_condition, 1000.0);  // raw 30: 15 each
    w.m.set_f(w.m.get_ref(bay, Field::_property), Field::MaxRepairPoints,
              60.0);
    SubsystemSession v = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord done = subsystems::next(v, w.m);
    ASSERT_TRUE(is_event(done, SubsystemEvent::REPAIR_DONE));
    EXPECT_EQ(done.code, bay);
    EXPECT_EQ(done.sub, f);
    EXPECT_EQ(done.a, 0.0);
    EXPECT_EQ(cond(w, f), 1000.0);
    EXPECT_EQ(cond(w, e), 514.0);
    ASSERT_EQ(v.dmg.entries.size(), 1u);        // e: disabled -> operational
    EXPECT_EQ(v.dmg.entries[0].kind, DamageKind::SUBSYS_EVENT);
    EXPECT_TRUE(is_articulation(subsystems::next(v, w.m)));

    // Complexity <= 0 is 1.0; a property not read through its data bag is
    // a PROPERTY skip with nothing written, a bay row that is not a bay's a
    // REF skip; no teams or points is no work.
    const int64_t g = w.item(100.0, 0.0);
    w.m.set_ids(bay, Field::_queue, {g});
    stage(w, ship, kHalf);
    EXPECT_EQ(cond(w, g), 130.0);
    const int64_t prop = w.m.get_ref(bay, Field::_property);
    w.m.set_i(prop, Field::repair_props_ok, 0);
    SubsystemSession p = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(walk(p, w.m), std::vector<int64_t>{0});
    EXPECT_TRUE(p.writes.empty());
    ASSERT_EQ(p.skips.size(), 1u);
    EXPECT_EQ(p.skips[0].piece, SubsystemPiece::REPAIR);
    EXPECT_EQ(p.skips[0].why, SubsystemSkip::PROPERTY);
    EXPECT_EQ(cond(w, g), 130.0);
    w.m.set_i(prop, Field::repair_props_ok, 1);
    w.m.set_i(bay, Field::is_repair_bay, 0);
    SubsystemSession q = subsystems::begin(w.m, std::vector{ship}, kHalf);
    walk(q, w.m);
    ASSERT_EQ(q.skips.size(), 1u);
    EXPECT_EQ(q.skips[0].why, SubsystemSkip::REF);
    w.m.set_i(bay, Field::is_repair_bay, 1);
    w.m.set_i(prop, Field::NumRepairTeams, 0);
    EXPECT_TRUE(is_articulation(stage(w, ship, kHalf)[0]));
    EXPECT_EQ(cond(w, g), 130.0);
    w.m.set_ref(bay, Field::_property, -1);     // no property: no teams
    EXPECT_TRUE(is_articulation(stage(w, ship, kHalf)[0]));
}

TEST(RepairStep, CannotCompleteYieldsMidWalkAndResumes) {
    World w;
    const int64_t ship = w.stage_ship();
    const int64_t bay = w.bay(ship, w.repair_prop(60.0, 2));
    const int64_t x = w.item(0.0);
    const int64_t y = w.item(100.0);
    const int64_t z = w.item(200.0);
    w.m.set_ids(bay, Field::_queue, {x, y, z});
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_TRUE(is_event(subsystems::next(s, w.m),
                         SubsystemEvent::REPAIR_CANNOT));
    // The handler removed x from the queue: Python's list iterator goes on
    // at index 1 of the list as it is NOW, so y is passed over this tick.
    w.m.set_ids(bay, Field::_queue, {y, z});
    EXPECT_TRUE(is_articulation(subsystems::next(s, w.m)));
    EXPECT_EQ(cond(w, y), 100.0);
    EXPECT_EQ(cond(w, z), 215.0);               // the whole 15

    // A handler that puts a fresh item at the head: the walk re-reads the
    // queue, meets x again at index 1 (told already: skipped, no event).
    const int64_t x2 = w.item(0.0);
    const int64_t head = w.item(300.0);
    w.m.set_ids(bay, Field::_queue, {x2, x, y, z});
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = subsystems::next(t, w.m);
    ASSERT_TRUE(is_event(r, SubsystemEvent::REPAIR_CANNOT));
    EXPECT_EQ(r.sub, x2);
    w.m.set_ids(bay, Field::_queue, {head, x2, x, y, z});
    EXPECT_TRUE(is_articulation(subsystems::next(t, w.m)));
    // index 1 on: x2 (told), x (told), y, z -- teams 2: y and z.
    EXPECT_EQ(cond(w, head), 300.0);
    EXPECT_EQ(cond(w, y), 107.5);
    EXPECT_EQ(cond(w, z), 222.5);

    // A handler that dropped the member at the cursor's row: that member
    // is passed over (a QUEUE_MEMBER skip, ruling R8-4) and the walk goes
    // on natively -- z takes the whole 15.
    const int64_t x3 = w.item(0.0);
    w.m.set_ids(bay, Field::_queue, {x3, y, z});
    SubsystemSession u = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_TRUE(is_event(subsystems::next(u, w.m),
                         SubsystemEvent::REPAIR_CANNOT));
    w.m.unregister_row(y);
    EXPECT_TRUE(is_articulation(subsystems::next(u, w.m)));
    EXPECT_EQ(cond(w, z), 237.5);
    ASSERT_EQ(u.skips.size(), 1u);
    EXPECT_EQ(u.skips[0].piece, SubsystemPiece::REPAIR);
    EXPECT_EQ(u.skips[0].why, SubsystemSkip::QUEUE_MEMBER);
    EXPECT_EQ(u.skips[0].sub, y);
    // An entry the mirror cannot name at all is passed over the same way.
    w.m.set_ids(bay, Field::_queue, {kRefUnrepresentable, z});
    SubsystemSession u2 = subsystems::begin(w.m, std::vector{ship}, kHalf);
    EXPECT_EQ(walk(u2, w.m), std::vector<int64_t>{0});
    EXPECT_EQ(cond(w, z), 252.5);
    ASSERT_EQ(u2.skips.size(), 1u);
    EXPECT_EQ(u2.skips[0].why, SubsystemSkip::QUEUE_MEMBER);

    // A handler that dropped the bay's row: the rest of the piece is a
    // BAY_GONE skip; nothing is repaired.
    const int64_t x4 = w.item(0.0);
    w.m.set_ids(bay, Field::_queue, {z, x4});
    SubsystemSession v = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_TRUE(is_event(subsystems::next(v, w.m),
                         SubsystemEvent::REPAIR_CANNOT));
    w.m.unregister_row(bay);
    EXPECT_TRUE(is_articulation(subsystems::next(v, w.m)));
    ASSERT_EQ(v.skips.size(), 1u);
    EXPECT_EQ(v.skips[0].why, SubsystemSkip::BAY_GONE);
    EXPECT_EQ(v.skips[0].sub, bay);
    EXPECT_EQ(cond(w, z), 252.5);
}

TEST(RepairStep, AnItemTheMirrorCannotRepairIsHandedOverAlone) {
    World w;
    const int64_t ship = w.stage_ship();
    const int64_t bay = w.bay(ship, w.repair_prop(60.0, 3));
    const int64_t a = w.item(100.0);
    const int64_t b = w.item(200.0);
    const int64_t c = w.item(300.0);
    // b holds a condition watcher the native chain cannot stand in for:
    // its set_condition falls back, after a's was made.
    w.m.set_i(b, Field::cond_watch_checks, -1);
    w.m.set_ids(bay, Field::_queue, {a, b, c});
    SubsystemSession s = subsystems::begin(w.m, std::vector{ship}, kHalf);
    const SubsystemRecord r = subsystems::next(s, w.m);
    // raw 15 over three: 5 each. a is repaired natively (its write kept,
    // applied before Python runs b); b alone is Python's (ruling R8-3).
    ASSERT_TRUE(is_event(r, SubsystemEvent::REPAIR_SET));
    EXPECT_EQ(r.code, bay);
    EXPECT_EQ(r.sub, b);
    EXPECT_EQ(r.a, 5.0);
    EXPECT_EQ(cond(w, a), 105.0);
    EXPECT_EQ(cond(w, b), 200.0);
    ASSERT_EQ(s.dmg.writes.size(), 1u);
    EXPECT_EQ(s.dmg.writes[0].handle, a);
    // Python repaired b and found it complete (a script's max); the walk
    // resumes at c, natively.
    w.m.set_f(b, Field::_condition, 1000.0);
    subsystems::repair_complete(s, b);
    EXPECT_THROW(subsystems::repair_complete(s, a), std::logic_error);
    const SubsystemRecord done = subsystems::next(s, w.m);
    ASSERT_TRUE(is_event(done, SubsystemEvent::REPAIR_DONE));
    EXPECT_EQ(done.sub, b);
    EXPECT_EQ(cond(w, c), 305.0);
    ASSERT_EQ(s.dmg.writes.size(), 1u);
    EXPECT_EQ(s.dmg.writes[0].handle, c);
    EXPECT_TRUE(is_articulation(subsystems::next(s, w.m)));
    EXPECT_TRUE(s.skips.empty());

    // An item whose row a handler dropped is handed over by itself too.
    const int64_t d = w.item(400.0);
    const int64_t x = w.item(0.0);
    w.m.set_i(b, Field::cond_watch_checks, 0);
    w.m.set_ids(bay, Field::_queue, {d, x, c});
    w.m.set_i(w.m.get_ref(bay, Field::_property), Field::NumRepairTeams, 2);
    SubsystemSession t = subsystems::begin(w.m, std::vector{ship}, kHalf);
    ASSERT_TRUE(is_event(subsystems::next(t, w.m),
                         SubsystemEvent::REPAIR_CANNOT));
    w.m.unregister_row(d);      // the handler dropped a worked item's row
    const SubsystemRecord set = subsystems::next(t, w.m);
    ASSERT_TRUE(is_event(set, SubsystemEvent::REPAIR_SET));
    EXPECT_EQ(set.sub, d);
    EXPECT_EQ(set.a, 7.5);
    EXPECT_TRUE(is_articulation(subsystems::next(t, w.m)));
    EXPECT_EQ(cond(w, c), 312.5);

    // The bay's property freed: a PROPERTY skip, before any write (the
    // same read the condition percentage would need).
    w.m.set_ids(bay, Field::_queue, {c});
    const int64_t rp = w.m.get_ref(bay, Field::_property);
    w.m.set_i(rp, Field::MaxCondition_set, 1);
    w.m.unregister_row(rp);
    SubsystemSession u = subsystems::begin(w.m, std::vector{ship}, kHalf);
    walk(u, w.m);
    ASSERT_EQ(u.skips.size(), 1u);
    EXPECT_EQ(u.skips[0].why, SubsystemSkip::PROPERTY);
}

// ── The articulation piece (Task 6; subsystem_step.h THE ARTICULATION PIECE)

TEST(ArticulationStep, RiglessShipsAreSkipped) {
    World w;
    const int64_t rigged = w.stage_ship();
    const int64_t rigless = w.stage_ship();
    const int64_t unknown = w.stage_ship();
    w.m.set_global_i(Global::ARTICULATION_GEN, 4);
    w.m.set_i(rigless, Field::_rigless_gen, 5);   // found rigless at gen 4
    // `rigged` and `unknown`: tick_ship has not found them rigless (0).
    const auto recs = stage(w, rigged, kHalf);
    ASSERT_EQ(recs.size(), 1u);
    EXPECT_TRUE(is_articulation(recs[0]));
    EXPECT_TRUE(stage(w, rigless, kHalf).empty());
    const auto u = stage(w, unknown, kHalf);
    ASSERT_EQ(u.size(), 1u);
    EXPECT_TRUE(is_articulation(u[0]));
    // A generation bump wakes the rigless ship: its key is stale.
    w.m.set_global_i(Global::ARTICULATION_GEN, 5);
    const auto after = stage(w, rigless, kHalf);
    ASSERT_EQ(after.size(), 1u);
    EXPECT_TRUE(is_articulation(after[0]));
}

TEST(ArticulationStep, ANoRowShipStillTicksInPython) {
    // articulation.tick_ship is kept: a ship with no row (or a lost one)
    // still gets its RUN_PYTHON, while its other four pieces are skipped.
    World w;
    SubsystemSession s = subsystems::begin(w.m, std::vector<int64_t>{-1},
                                           kHalf);
    EXPECT_TRUE(is_articulation(subsystems::next(s, w.m)));
    EXPECT_EQ(s.skips.size(), 4u);
}

// THE IDENTICAL WRITES (subsystem_step.cc put_f/put_at).
namespace {

int consumer_writes(const SubsystemSession& s, int64_t c) {
    int n = 0;
    for (const SubsystemWrite& x : s.writes)
        if (x.sub == c && (x.what == SubsystemWriteKind::POWER_WANTED ||
                           x.what == SubsystemWriteKind::POWER_RECEIVED ||
                           x.what == SubsystemWriteKind::EFFICIENCY ||
                           x.what == SubsystemWriteKind::POWER_FACTOR))
            ++n;
    return n;
}

}  // namespace

TEST(SubsystemStep, SteadyPowerLogsNoWritesOnTheSecondTick) {
    subsystems::reset_write_stats();
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    w.plant(ship, prop, 500.0, 500.0, 0.0);
    const int64_t c = w.consumer(ship, 0, 60.0);
    SubsystemSession a = subsystems::begin(w.m, std::vector{ship}, 0.25);
    after_power(w, a);
    EXPECT_GT(consumer_writes(a, c), 0);   // the first tick changes them
    SubsystemSession b = subsystems::begin(w.m, std::vector{ship}, 0.25);
    after_power(w, b);
    EXPECT_EQ(consumer_writes(b, c), 0);
    EXPECT_GE(subsystems::write_stats().identical, 4u);
}

TEST(SubsystemStep, AChangedValueIsStillWritten) {
    subsystems::reset_write_stats();
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    w.plant(ship, prop, 500.0, 500.0, 0.0);
    const int64_t c = w.consumer(ship, 0, 60.0);
    SubsystemSession a = subsystems::begin(w.m, std::vector{ship}, 0.25);
    after_power(w, a);
    w.m.set_f(c, Field::_normal_power, 120.0);   // wants more: 30, not 15
    SubsystemSession b = subsystems::begin(w.m, std::vector{ship}, 0.25);
    after_power(w, b);
    EXPECT_GT(consumer_writes(b, c), 0);
    EXPECT_EQ(w.m.get_f(c, Field::_power_wanted), 30.0);
}

TEST(SubsystemStep, NegativeZeroIsNotIdenticalToZero) {
    subsystems::reset_write_stats();
    // A consumer that wants nothing (off) writes 0.0 to every field; a row
    // holding -0.0 there is NOT identical, so Python is told.
    subsystems::reset_write_stats();
    World w;
    const int64_t ship = w.power_ship();
    const int64_t prop = w.power_prop(0.0, 1000.0, 1000.0, 1000.0, 1000.0);
    w.plant(ship, prop, 500.0, 500.0, 0.0);
    const int64_t c = w.consumer(ship, 0, 60.0);
    w.m.set_i(c, Field::_is_on, 0);
    w.m.set_f(c, Field::_power_wanted, 0.0);
    w.m.set_f(c, Field::_power_received, -0.0);
    w.m.set_f(c, Field::_efficiency, 0.0);
    w.m.set_f(c, Field::_power_factor, 0.0);
    SubsystemSession a = subsystems::begin(w.m, std::vector{ship}, 0.25);
    after_power(w, a);
    bool received = false;
    for (const SubsystemWrite& x : a.writes)
        if (x.sub == c && x.what == SubsystemWriteKind::POWER_RECEIVED)
            received = true;
    EXPECT_TRUE(received);
    EXPECT_FALSE(std::signbit(w.m.get_f(c, Field::_power_received)));
}

TEST(SubsystemStep, ANeverRampedFaceAtZeroLogsItsFirstRamp) {
    // Python's _ramp_fraction[f] starts None; the push encodes that as
    // fraction 0.0 with _ramp_set 0.0. A first ramp of 0.0 must still be
    // logged (None -> 0.0 float), then later identical ramps are skipped.
    subsystems::reset_write_stats();
    World w;
    const int64_t ship = w.bare_ship();
    const int64_t sh = w.shield(ship);
    w.m.set_floats(sh, Field::_current_shields, std::vector<double>(6, 0.0));
    w.m.set_floats(sh, Field::_charge_per_second, std::vector<double>(6, 0.0));
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    auto ramps = [](const SubsystemSession& s) {
        int n = 0;
        for (const SubsystemWrite& x : s.writes)
            n += x.what == SubsystemWriteKind::RAMP;
        return n;
    };
    SubsystemSession a = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(a, w.m);
    EXPECT_EQ(ramps(a), 6);
    EXPECT_EQ(w.m.get_floats(sh, Field::_ramp_set),
              std::vector<double>(6, 1.0));
    w.m.set_f(sh, Field::_charge_accum, 0.49);
    SubsystemSession b = subsystems::begin(w.m, std::vector{ship}, kDt);
    subsystems::next(b, w.m);
    EXPECT_EQ(ramps(b), 0);
}
