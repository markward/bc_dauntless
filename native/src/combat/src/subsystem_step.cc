// The subsystem stage session (subsystem_step.h).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/subsystem_step.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstring>
#include <stdexcept>

#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"

namespace dauntless::combat {

const char* subsystem_record_type_name(SubsystemRecordType t) {
    switch (t) {
        case SubsystemRecordType::DONE: return "DONE";
        case SubsystemRecordType::RUN_PYTHON: return "RUN_PYTHON";
        case SubsystemRecordType::EVENT: return "EVENT";
        case SubsystemRecordType::kCount: break;
    }
    return "?";
}

const char* subsystem_piece_name(SubsystemPiece p) {
    switch (p) {
        case SubsystemPiece::SHIELD: return "SHIELD";
        case SubsystemPiece::POWER: return "POWER";
        case SubsystemPiece::CLOAK: return "CLOAK";
        case SubsystemPiece::REPAIR: return "REPAIR";
        case SubsystemPiece::ARTICULATION: return "ARTICULATION";
        case SubsystemPiece::kCount: break;
    }
    return "?";
}

const char* subsystem_event_name(SubsystemEvent e) {
    switch (e) {
        case SubsystemEvent::SHIELD_WATCHER: return "SHIELD_WATCHER";
        case SubsystemEvent::SHIELD_WATCHER_TAIL: return "SHIELD_WATCHER_TAIL";
        case SubsystemEvent::BREACH: return "BREACH";
        case SubsystemEvent::BATTERY_WATCHER: return "BATTERY_WATCHER";
        case SubsystemEvent::POWER_TAIL: return "POWER_TAIL";
        case SubsystemEvent::FORCE_DECLOAK: return "FORCE_DECLOAK";
        case SubsystemEvent::CLOAK_DONE: return "CLOAK_DONE";
        case SubsystemEvent::REPAIR_CANNOT: return "REPAIR_CANNOT";
        case SubsystemEvent::REPAIR_DONE: return "REPAIR_DONE";
        case SubsystemEvent::REPAIR_SET: return "REPAIR_SET";
        case SubsystemEvent::kCount: break;
    }
    return "?";
}

const char* subsystem_skip_name(SubsystemSkip k) {
    switch (k) {
        case SubsystemSkip::NO_ROW: return "NO_ROW";
        case SubsystemSkip::LOST_ROW: return "LOST_ROW";
        case SubsystemSkip::REF: return "REF";
        case SubsystemSkip::SHIELD_UNREADY: return "SHIELD_UNREADY";
        case SubsystemSkip::OFFLINE: return "OFFLINE";
        case SubsystemSkip::PROPERTY: return "PROPERTY";
        case SubsystemSkip::BATTERY_WATCH: return "BATTERY_WATCH";
        case SubsystemSkip::PARENT_SHIP: return "PARENT_SHIP";
        case SubsystemSkip::CONSUMER: return "CONSUMER";
        case SubsystemSkip::QUEUE_MEMBER: return "QUEUE_MEMBER";
        case SubsystemSkip::BAY_GONE: return "BAY_GONE";
        case SubsystemSkip::POST_BREACH_UNREADY: return "POST_BREACH_UNREADY";
        case SubsystemSkip::kCount: break;
    }
    return "?";
}

namespace subsystems {

namespace {

constexpr int32_t kPieces = static_cast<int32_t>(SubsystemPiece::kCount);
constexpr size_t kFaces = 6;     // ShieldSubsystem.NUM_SHIELDS
constexpr int32_t kWatchers = 7; // the faces, then the combined watcher

// ── The shield piece (subsystem_step.h THE SHIELD PIECE) ─────────────────

// Where each of `n` watchers' checks start in an encoded checks list
// (shield_watch_checks, power_watch_checks: per watcher its count, then its
// (threshold, code) pairs). False: the list is malformed.
bool check_offsets(const std::vector<double>& c, size_t n_watchers,
                   size_t* at) {
    size_t i = 0;
    for (size_t w = 0; w < n_watchers; ++w) {
        if (i >= c.size()) return false;
        at[w] = i;
        const double n = c[i];
        if (!(n >= 0.0) || n != static_cast<double>(static_cast<size_t>(n)))
            return false;
        i += 1 + 2 * static_cast<size_t>(n);
    }
    return i == c.size();
}

// The generator's rows are what the native piece reads: six faces in each
// list, seven adopted stock watchers with well-formed checks.
bool shield_ready(const SubsystemRow& s, std::array<size_t, kWatchers>& at) {
    return s.shield_watch_ok == 1 && s._max_shields.size() == kFaces &&
           s._current_shields.size() == kFaces &&
           s._charge_per_second.size() == kFaces &&
           s._ramp_fraction.size() == kFaces &&
           s._ramp_set.size() == kFaces &&
           s.shield_watch_values.size() == static_cast<size_t>(kWatchers) &&
           check_offsets(s.shield_watch_checks, kWatchers, at.data());
}

// ShieldSubsystem.GetSingleShieldPercentage(f) for f in 0..5, and
// GetShieldPercentage() for the combined watcher (6). Its two `sum()`s are
// CPython 3.11's: a plain left-to-right double sum from 0 (int 0 + the
// first float is that float, -0.0 reading 0.0, as 0.0 + -0.0 does here).
// CPython 3.12+ sums floats with compensated (Neumaier) summation, which
// this loop does NOT reproduce: moving the engine past 3.11 changes this.
double watched_value(const SubsystemRow& s, int32_t w) {
    if (w < static_cast<int32_t>(kFaces)) {
        const size_t f = static_cast<size_t>(w);
        const double mx = s._max_shields[f];
        if (mx == 0.0) return 0.0;
        if (!s._is_on) return 0.0;
        return s._current_shields[f] / mx;
    }
    double total_max = 0.0;
    for (double x : s._max_shields) total_max += x;
    if (total_max <= 0.0) return 1.0;
    if (!s._is_on) return 0.0;
    double total_cur = 0.0;
    for (double x : s._current_shields) total_cur += x;
    return total_cur / total_max;
}

// FloatRangeWatcher._crossed (float_range_watcher.py); code 1 FRW_ABOVE,
// 2 FRW_BELOW, else either.
bool crossed(double old_v, double new_v, double threshold, double code) {
    const bool downward = old_v >= threshold && threshold > new_v;
    const bool upward = old_v < threshold && threshold <= new_v;
    if (code == 2.0) return downward;
    if (code == 1.0) return upward;
    return downward || upward;
}

bool any_check_crossed(const std::vector<double>& c, size_t at, double old_v,
                       double new_v) {
    const size_t n = static_cast<size_t>(c[at]);
    for (size_t k = 0; k < n; ++k)
        if (crossed(old_v, new_v, c[at + 1 + 2 * k], c[at + 2 + 2 * k]))
            return true;
    return false;
}

uint64_t g_logged = 0;     // writes logged, process-wide (write_stats)

void log(SubsystemSession& s, int64_t sub, SubsystemWriteKind what,
         int32_t index, double v) {
    ++g_logged;
    s.writes.push_back(SubsystemWrite{sub, what, index, v});
}

// THE IDENTICAL WRITES. Python's __dict__ == the mirror for every mirrored
// field (audit_mirror), so a value bit-identical to the mirror's is already
// in Python: neither the mirror write nor the log (a Python store) is made.
// Bits, not ==: -0.0 differs from 0.0, a NaN equals itself.
inline bool same_bits(double a, double b) {
    return std::memcmp(&a, &b, sizeof a) == 0;
}

uint64_t g_identical = 0;  // writes skipped as identical

// A float field `f` of `sub`, now holding `cur`, to become `v`; logged as
// `what`. True when written.
bool put_f(SubsystemSession& s, Mirror& m, int64_t sub, Field f,
           SubsystemWriteKind what, double cur, double v) {
    if (same_bits(cur, v)) {
        ++g_identical;
        return false;
    }
    m.set_f(sub, f, v);
    log(s, sub, what, 0, v);
    return true;
}

// One element of a FloatList field, the same.
bool put_at(SubsystemSession& s, Mirror& m, int64_t sub, Field f,
            SubsystemWriteKind what, size_t index, double cur, double v) {
    if (same_bits(cur, v)) {
        ++g_identical;
        return false;
    }
    m.set_float_at(sub, f, index, v);
    log(s, sub, what, static_cast<int32_t>(index), v);
    return true;
}

SubsystemRecord event(const SubsystemSession& s, size_t i, SubsystemEvent e,
                      int64_t sub, int64_t code, double a, double b = 0.0) {
    SubsystemRecord r;
    r.type = SubsystemRecordType::EVENT;
    r.ship_pos = static_cast<int64_t>(i);
    r.ship = s.ships[i];
    r.kind = static_cast<int32_t>(e);
    r.code = code;
    r.a = a;
    r.b = b;
    r.sub = sub;
    return r;
}

// THE SKIPS, process-wide (skip_count). Main-thread only, as the stage is.
uint64_t g_skips[static_cast<size_t>(SubsystemPiece::kCount)]
                [static_cast<size_t>(SubsystemSkip::kCount)] = {};

// Piece `p` of ship i skipped (THE SKIPS): logged in the session, counted.
// Returns false (the piece is over, no record) for the callers' `return`.
bool skip(SubsystemSession& s, size_t i, SubsystemPiece p, SubsystemSkip why,
          int64_t sub = -1) {
    s.skips.push_back(
        SubsystemSkipRecord{static_cast<int64_t>(i), p, why, sub});
    ++g_skips[static_cast<size_t>(p)][static_cast<size_t>(why)];
    return false;
}

// The ship-level skips at a piece's start: no row at begin, or freed since.
// True when the piece was skipped.
bool ship_skipped(SubsystemSession& s, size_t i, SubsystemPiece p) {
    if (!s.had_row[i]) return !skip(s, i, p, SubsystemSkip::NO_ROW);
    if (s.lost_row[i]) return !skip(s, i, p, SubsystemSkip::LOST_ROW);
    return false;
}

// The watcher loop of generator `sh` from watcher s.shield_watcher on.
// Returns true with `out` set when it stopped for a record (the cursor then
// names the next watcher); false when the loop is over.
bool shield_watchers(SubsystemSession& s, Mirror& m, size_t i,
                     SubsystemRecord& out) {
    const int64_t sh = s.shield;
    while (s.shield_watcher < kWatchers) {
        const int32_t w = s.shield_watcher;
        const SubsystemRow* row = m.subsystem(sh);
        std::array<size_t, kWatchers> at{};
        if (row == nullptr || !shield_ready(*row, at)) {
            // The rest of the loop is Python's, on the same generator.
            out = event(s, i, SubsystemEvent::SHIELD_WATCHER_TAIL, sh, w, 0.0);
            s.shield_watcher = kWatchers;
            return true;
        }
        const double v = watched_value(*row, w);
        const double old_v = row->shield_watch_values[static_cast<size_t>(w)];
        ++s.shield_watcher;
        if (any_check_crossed(row->shield_watch_checks,
                              at[static_cast<size_t>(w)], old_v, v)) {
            out = event(s, i, SubsystemEvent::SHIELD_WATCHER, sh, w, v);
            return true;
        }
        put_at(s, m, sh, Field::shield_watch_values, SubsystemWriteKind::SHIELD_WATCH,
               static_cast<size_t>(w), old_v, v);
    }
    return false;
}

// THE SHIELD PIECE for ship i. Returns true with `out` set when the piece
// stops for a record (an EVENT inside it); false when it is over
// (natively, skipped, or with nothing to do).
bool shield_piece(SubsystemSession& s, Mirror& m, size_t i,
                  SubsystemRecord& out) {
    if (s.shield_phase == 1) {
        if (shield_watchers(s, m, i, out)) return true;
        return false;
    }
    constexpr SubsystemPiece kP = SubsystemPiece::SHIELD;
    if (ship_skipped(s, i, kP)) return false;
    const ObjectRow* o = m.object(s.ships[i]);
    // The ship's raw ref: -1 is `_shield_subsystem is None` (no call), a
    // stale handle a row dropped since (the generator lives on: skipped).
    const int64_t sh = o->_shield_subsystem;
    if (sh == -1) return false;
    const SubsystemRow* row =
        sh == kRefUnrepresentable ? nullptr : m.subsystem(sh);
    if (row == nullptr) return skip(s, i, kP, SubsystemSkip::REF, sh);
    std::array<size_t, kWatchers> at{};
    if (!shield_ready(*row, at))
        return skip(s, i, kP, SubsystemSkip::SHIELD_UNREADY, sh);
    const double period = m.globals().SHIELD_CHARGE_PERIOD_S;
    // self._charge_accum = self._charge_accum + float(dt)
    const double accum = row->_charge_accum + s.dt;
    if (accum < period) {
        put_f(s, m, sh, Field::_charge_accum, SubsystemWriteKind::CHARGE_ACCUM,
              row->_charge_accum, accum);
        return false;
    }
    // _is_offline(self) is asked after the ramp refresh, which none of its
    // inputs read: asked first, so a question the mirror cannot answer
    // skips the whole piece with nothing written.
    bool offline;
    try {
        offline = subsystem_is_offline(m, *row);
    } catch (const std::invalid_argument&) {
        return skip(s, i, kP, SubsystemSkip::OFFLINE, sh);
    }
    const double dt = accum;
    put_f(s, m, sh, Field::_charge_accum, SubsystemWriteKind::CHARGE_ACCUM,
          row->_charge_accum, 0.0);
    for (size_t f = 0; f < kFaces; ++f) {
        const double mx = row->_max_shields[f];
        const double ramp = mx > 0.0 ? row->_current_shields[f] / mx : 0.0;
        // _ramp_set is mirror-only (the applier sets the fraction alone). A
        // face never ramped (_ramp_set 0.0) holds None in Python, which the
        // push encodes as fraction 0.0: its first ramp is ALWAYS logged, so
        // Python's None becomes a float even when the value is 0.0.
        const bool was_set = same_bits(row->_ramp_set[f], 1.0);
        if (!was_set) {
            m.set_float_at(sh, Field::_ramp_set, f, 1.0);
            m.set_float_at(sh, Field::_ramp_fraction, f, ramp);
            log(s, sh, SubsystemWriteKind::RAMP, static_cast<int32_t>(f),
                ramp);
        } else {
            put_at(s, m, sh, Field::_ramp_fraction, SubsystemWriteKind::RAMP,
                   f, row->_ramp_fraction[f], ramp);
        }
    }
    if (offline) {
        bool any = false;
        for (double x : row->_current_shields) any = any || x != 0.0;
        if (!any) return false;
        for (size_t f = 0; f < kFaces; ++f) {
            put_at(s, m, sh, Field::_current_shields, SubsystemWriteKind::FACE,
                   f, row->_current_shields[f], 0.0);
        }
    } else {
        for (size_t f = 0; f < kFaces; ++f) {
            const double mx = row->_max_shields[f];
            if (mx == 0.0) continue;
            double v = row->_current_shields[f] + row->_charge_per_second[f] * dt;
            if (v > mx) v = mx;
            put_at(s, m, sh, Field::_current_shields, SubsystemWriteKind::FACE,
                   f, row->_current_shields[f], v);
        }
    }
    s.shield_phase = 1;
    s.shield_watcher = 0;
    s.shield = sh;
    return shield_watchers(s, m, i, out);
}

// ── The power piece (subsystem_step.h THE POWER PIECE) ───────────────────

constexpr int64_t kPlant = 3;          // native_combat._power_kind
constexpr int64_t kConsumerBase = 0;   // PoweredSubsystem's rules
constexpr int64_t kConsumerTractor = 1;
constexpr int64_t kConsumerCloak = 2;
constexpr int64_t kTractorBeam = 7;    // weapon_kind
constexpr size_t kBatteryWatchers = 2; // main, backup
constexpr int64_t kPsmMainFirst = 0;   // subsystems.PSM_*
constexpr int64_t kPsmBackupFirst = 1;

// The plant's two watchers are adopted stock watchers with well-formed
// checks.
bool battery_watch_ready(const SubsystemRow& p, size_t* at) {
    return p.power_watch_ok == 1 &&
           p.power_watch_values.size() == kBatteryWatchers &&
           check_offsets(p.power_watch_checks, kBatteryWatchers, at);
}

// A consumer the pump can run natively: a live row of a known kind (a
// tractor system's children all live tractor beams, as _any_child_firing
// walks them).
bool consumer_ready(const Mirror& m, int64_t h) {
    if (h < 0) return false;
    const SubsystemRow* c = m.subsystem(h);
    if (c == nullptr) return false;
    if (c->power_kind == kConsumerBase || c->power_kind == kConsumerCloak)
        return true;
    if (c->power_kind != kConsumerTractor) return false;
    for (int64_t ch : c->_children) {
        if (ch < 0) return false;
        const SubsystemRow* b = m.subsystem(ch);
        if (b == nullptr || b->weapon_kind != kTractorBeam) return false;
    }
    return true;
}

// Everything the rest of Update (after the breach) reads is one the mirror
// answers: kCount when it is, else the skip's reason. Asks nothing that
// writes; a throw of the offline question or the condition percentage is
// OFFLINE.
SubsystemSkip power_unready(const Mirror& m, const SubsystemRow& p,
                            double dt) {
    constexpr SubsystemSkip kReady = SubsystemSkip::kCount;
    if (p._property == -1) return kReady;     // the flow is `return`
    if (p._property == kRefUnrepresentable) return SubsystemSkip::PROPERTY;
    const PropertyRow* prop = m.property(p._property);
    if (prop == nullptr || prop->power_props_ok != 1)
        return SubsystemSkip::PROPERTY;
    size_t at[kBatteryWatchers];
    if (!battery_watch_ready(p, at)) return SubsystemSkip::BATTERY_WATCH;
    // GetParentShip(): `_parent_ship` itself (a ref of -1 would climb).
    if (p._parent_ship < 0) return SubsystemSkip::PARENT_SHIP;
    const ObjectRow* ship = m.object(p._parent_ship);
    if (ship == nullptr || !ship->is_ship_class)
        return SubsystemSkip::PARENT_SHIP;
    // A consumer the pump cannot run is not the plant's readiness: the pump
    // passes over that one consumer (a CONSUMER skip, power_flow).
    if (p._interval_elapsed + dt >= m.globals().POWER_INTERVAL) {
        try {
            (void)subsystem_is_offline(m, p);
            (void)condition_percentage(m, p);
        } catch (const std::invalid_argument&) {
            return SubsystemSkip::OFFLINE;
        }
    }
    return kReady;
}

// The plant's pools and budgets while the piece runs; `wrote_*`: the
// piece assigns that attribute this tick (only those are logged: the
// former Python plant's assignments, deleted in phase 6 Task 8).
struct Plant {
    double main, backup, main_conduit, backup_conduit, available, dispensed;
    bool wrote_main = false, wrote_backup = false, wrote_budgets = false,
         wrote_dispensed = false;
};

// One pool's conduit draw: min of three, Python's fold (the former
// PowerSubsystem._draw_main / _draw_backup, deleted in phase 6 Task 8).
double draw_main(Plant& p, double amount) {
    const double take = py_min(py_min(amount, p.main_conduit), p.main);
    if (take <= 0.0) return 0.0;
    p.main_conduit -= take;
    p.main -= take;
    p.wrote_main = p.wrote_budgets = true;
    return take;
}
double draw_backup(Plant& p, double amount) {
    const double take = py_min(py_min(amount, p.backup_conduit), p.backup);
    if (take <= 0.0) return 0.0;
    p.backup_conduit -= take;
    p.backup -= take;
    p.wrote_backup = p.wrote_budgets = true;
    return take;
}

// A conduit draw by POWER_MODE (the former PowerSubsystem._draw, deleted in
// phase 6 Task 8; `amount` > 0 here, as every caller guards).
double draw(Plant& p, double amount, int64_t mode) {
    if (amount <= 0.0) return 0.0;
    double got = 0.0;
    if (mode == kPsmMainFirst) {
        double take = amount;
        if (take > p.main_conduit) take = p.main_conduit;
        if (take > p.main) take = p.main;
        if (take > 0.0) {
            p.main_conduit -= take;
            p.main -= take;
            p.wrote_main = p.wrote_budgets = true;
            got = take;
        }
        const double rest = amount - got;
        if (rest > 0.0) {
            take = rest;
            if (take > p.backup_conduit) take = p.backup_conduit;
            if (take > p.backup) take = p.backup;
            if (take > 0.0) {
                p.backup_conduit -= take;
                p.backup -= take;
                p.wrote_backup = p.wrote_budgets = true;
                got += take;
            }
        }
    } else if (mode == kPsmBackupFirst) {
        got += draw_backup(p, amount);
        got += draw_main(p, amount - got);
    } else {  // PSM_BACKUP_ONLY, and PSM_DIRECT_MAIN (3): the final else
        got += draw_backup(p, amount);
    }
    p.dispensed += got;
    p.wrote_dispensed = true;
    return got;
}

void write_consumer(SubsystemSession& s, Mirror& m, int64_t c, double wanted,
                    double received, double eff, double factor) {
    const SubsystemRow& r = *m.subsystem(c);
    const double w0 = r._power_wanted, r0 = r._power_received,
                 e0 = r._efficiency, f0 = r._power_factor;
    put_f(s, m, c, Field::_power_wanted, SubsystemWriteKind::POWER_WANTED, w0,
          wanted);
    put_f(s, m, c, Field::_power_received, SubsystemWriteKind::POWER_RECEIVED,
          r0, received);
    put_f(s, m, c, Field::_efficiency, SubsystemWriteKind::EFFICIENCY, e0,
          eff);
    put_f(s, m, c, Field::_power_factor, SubsystemWriteKind::POWER_FACTOR, f0,
          factor);
}

// One consumer's per-tick draw by its power_kind (the former
// _update_power rules, deleted in phase 6 Task 8).
void update_power(SubsystemSession& s, Mirror& m, int64_t h, Plant& p) {
    const double dt = s.dt;
    if (dt <= 0.0) return;
    // Every input is read before this consumer's own row is written (the
    // rows never move: a write reallocates nothing).
    const SubsystemRow& c = *m.subsystem(h);
    if (c.power_kind == kConsumerCloak) {
        // The cloak's rules (draws from the reserve while IsTryingToCloak:
        // its _wants_power).
        const bool wants = c._cloak_state == 1 || c._cloak_state == 2;
        if (!wants) {
            write_consumer(s, m, h, 0.0, 0.0, 0.0, 0.0);
        } else {
            const double base = c.CLOAK_RESERVE_DRAIN_PER_SECOND * dt;
            double received = 0.0;
            if (base > 0.0) {
                // StealPowerFromReserve: take = min(amount, backup).
                received = py_min(base, p.backup);
                p.backup -= received;
                p.wrote_backup = true;
            }
            const double eff = base > 0.0 ? received / base : 1.0;
            write_consumer(s, m, h, base, received, eff, eff);
        }
        put_f(s, m, h, Field::_backup_reserve,
              SubsystemWriteKind::BACKUP_RESERVE, c._backup_reserve, p.backup);
        return;
    }
    // PoweredSubsystem's rules; the tractor's _wants_power also needs
    // a firing child (IsOn() and _any_child_firing()).
    bool wants = c._is_on != 0;
    if (wants && c.power_kind == kConsumerTractor) {
        bool firing = false;
        for (int64_t ch : c._children)
            if (m.subsystem(ch)->_firing) {
                firing = true;
                break;
            }
        wants = firing;
    }
    if (!wants) {
        write_consumer(s, m, h, 0.0, 0.0, 0.0, 0.0);
        return;
    }
    const double base = c._normal_power * dt;
    if (base <= 0.0) {  // a free consumer: full function
        write_consumer(s, m, h, 0.0, 0.0, 1.0, 1.0);
        return;
    }
    if (c.DRAWS_DIRECT_FROM_MAIN) {
        // StealPower(base): take = min(amount, main); not dispensed.
        const double wanted = base * c._power_percentage_wanted;
        const double received = py_min(base, p.main);
        p.main -= received;
        p.wrote_main = true;
        write_consumer(s, m, h, wanted, received, received / base,
                       received / base);
        return;
    }
    const double wanted = base * c._power_percentage_wanted;
    const double received =
        wanted > 0.0 ? draw(p, wanted, c.POWER_MODE) : 0.0;
    write_consumer(s, m, h, wanted, received,
                   wanted > 0.0 ? received / wanted : 1.0, received / base);
}

// The battery watcher `w` (0 main, 1 backup) of plant `ph` fed `v`: no check
// crossed writes it (false); a crossing returns its EVENT (true).
bool battery_watcher(SubsystemSession& s, Mirror& m, size_t i, int64_t ph,
                     size_t w, double v, SubsystemRecord& out) {
    const SubsystemRow& p = *m.subsystem(ph);
    size_t at[kBatteryWatchers];
    // Its result is safe to ignore: every caller checked battery_watch_ready
    // (which runs this same check_offsets) earlier in the same next(), with
    // no Python in between, so the checks list cannot have changed.
    check_offsets(p.power_watch_checks, kBatteryWatchers, at);
    if (any_check_crossed(p.power_watch_checks, at[w],
                          p.power_watch_values[w], v)) {
        out = event(s, i, SubsystemEvent::BATTERY_WATCHER, ph,
                    static_cast<int64_t>(w), v);
        return true;
    }
    put_at(s, m, ph, Field::power_watch_values,
           SubsystemWriteKind::BATTERY_WATCH, w, p.power_watch_values[w], v);
    return false;
}

// The backup watcher's line, its limit read before the main watcher. The
// piece is over after it (phase 3), whatever it returns.
bool backup_watcher(SubsystemSession& s, Mirror& m, size_t i,
                    SubsystemRecord& out) {
    const int64_t ph = s.power;
    s.power_phase = 3;
    const SubsystemRow* p = m.subsystem(ph);
    size_t at[kBatteryWatchers];
    const double cap = s.power_backup_cap;
    if (p == nullptr || !battery_watch_ready(*p, at)) {
        out = event(s, i, SubsystemEvent::POWER_TAIL, ph, 1, cap);
        return true;
    }
    const double v = cap > 0.0 ? p->_backup_battery_power / cap : 0.0;
    return battery_watcher(s, m, i, ph, 1, v, out);
}

// The plant's tick after the breach, on a ready plant `ph`. True with `out`
// set when it stops for a record.
bool power_flow(SubsystemSession& s, Mirror& m, size_t i,
                SubsystemRecord& out) {
    const int64_t ph = s.power;
    const SubsystemRow& row = *m.subsystem(ph);
    if (row._property == -1) return false;  // `if prop is None: return`
    const PropertyRow& prop = *m.property(row._property);
    const double dt = s.dt;
    Plant p{row._main_battery_power,    row._backup_battery_power,
            row._main_conduit_current,  row._backup_conduit_current,
            row._available_power,       row._power_dispensed};
    double interval = row._interval_elapsed + dt;
    if (interval >= m.globals().POWER_INTERVAL) {
        const double elapsed = interval;
        interval = 0.0;     // reset, not subtracted
        p.dispensed = 0.0;
        p.wrote_dispensed = true;
        const double cond = condition_percentage(m, row);
        if (!subsystem_is_offline(m, row)) {
            // The recharge: GetPowerOutput() * elapsed, main first, spill to
            // backup, discard the rest.
            const double amount = (prop.PowerOutput * cond) * elapsed;
            const double main_cap = prop.MainBatteryLimit;
            const double backup_cap = prop.BackupBatteryLimit;
            double room = main_cap - p.main;
            const double take = py_min(amount, py_max(room, 0.0));
            p.main += take;
            const double spill = amount - take;
            room = backup_cap - p.backup;
            p.backup += py_min(spill, py_max(room, 0.0));
            p.wrote_main = p.wrote_backup = true;
        }
        const double main_max = (prop.MainConduitCapacity * cond) * elapsed;
        const double backup_max = prop.BackupConduitCapacity * elapsed;
        p.main_conduit = py_min(p.main, main_max);
        p.backup_conduit = py_min(p.backup, backup_max);
        p.available = p.main_conduit + p.backup_conduit;
        p.wrote_budgets = true;
    }
    // The pump: the parent ship's consumers, in attach order. A consumer
    // the pump cannot run (its row unnamed or freed, an unknown kind, a
    // tractor's beams unreadable) is passed over and counted -- a CONSUMER
    // skip, that consumer only, as the repair walk's QUEUE_MEMBER -- and
    // left out of the wanted total; every other consumer still draws.
    const std::vector<int64_t>& consumers =
        m.object(row._parent_ship)->_powered_consumers;
    bool wrote_total = false;
    double total = 0.0;
    if (!consumers.empty()) {
        std::vector<int64_t> ready;
        ready.reserve(consumers.size());
        for (int64_t c : consumers) {
            if (consumer_ready(m, c)) {
                ready.push_back(c);
            } else {
                skip(s, i, SubsystemPiece::POWER, SubsystemSkip::CONSUMER, c);
            }
        }
        for (int64_t c : ready) update_power(s, m, c, p);
        for (int64_t c : ready) total += m.subsystem(c)->_power_wanted;
        wrote_total = true;
    }
    const SubsystemRow& pr = *m.subsystem(ph);
    put_f(s, m, ph, Field::_interval_elapsed,
          SubsystemWriteKind::INTERVAL_ELAPSED, pr._interval_elapsed, interval);
    if (p.wrote_dispensed)
        put_f(s, m, ph, Field::_power_dispensed,
              SubsystemWriteKind::POWER_DISPENSED, pr._power_dispensed,
              p.dispensed);
    if (p.wrote_main)
        put_f(s, m, ph, Field::_main_battery_power,
              SubsystemWriteKind::MAIN_BATTERY, pr._main_battery_power, p.main);
    if (p.wrote_backup)
        put_f(s, m, ph, Field::_backup_battery_power,
              SubsystemWriteKind::BACKUP_BATTERY, pr._backup_battery_power,
              p.backup);
    if (p.wrote_budgets) {
        put_f(s, m, ph, Field::_main_conduit_current,
              SubsystemWriteKind::MAIN_CONDUIT, pr._main_conduit_current,
              p.main_conduit);
        put_f(s, m, ph, Field::_backup_conduit_current,
              SubsystemWriteKind::BACKUP_CONDUIT, pr._backup_conduit_current,
              p.backup_conduit);
        put_f(s, m, ph, Field::_available_power,
              SubsystemWriteKind::AVAILABLE_POWER, pr._available_power,
              p.available);
    }
    if (wrote_total)
        put_f(s, m, ph, Field::_power_wanted_total,
              SubsystemWriteKind::POWER_WANTED_TOTAL, pr._power_wanted_total,
              total);
    // The watchers: both limits read now, the backup battery after the main
    // watcher's update.
    const double main_cap = prop.MainBatteryLimit;
    s.power_backup_cap = prop.BackupBatteryLimit;
    const double v = main_cap > 0.0 ? p.main / main_cap : 0.0;
    s.power_phase = 2;
    if (battery_watcher(s, m, i, ph, 0, v, out)) return true;
    return backup_watcher(s, m, i, out);
}

// THE POWER PIECE for ship i (as shield_piece).
bool power_piece(SubsystemSession& s, Mirror& m, size_t i,
                 SubsystemRecord& out) {
    constexpr SubsystemPiece kP = SubsystemPiece::POWER;
    if (s.power_phase == 1) {
        // Resumed after the breach's handler (_trigger_breach: it reads and
        // queues a deferred effect-queue entry). The readiness asked now: a
        // plant unready before its breach is that reason's skip; one ready
        // then and not now (a handler changed what the piece reads) is a
        // POST_BREACH_UNREADY skip -- counted, never a throw (R8-1).
        const SubsystemRow* row = m.subsystem(s.power);
        const SubsystemSkip why =
            row == nullptr ? SubsystemSkip::POST_BREACH_UNREADY
                           : power_unready(m, *row, s.dt);
        if (why != SubsystemSkip::kCount)
            return skip(s, i, kP,
                        s.power_ready_before ? SubsystemSkip::POST_BREACH_UNREADY
                                             : why,
                        s.power);
        return power_flow(s, m, i, out);
    }
    if (s.power_phase == 2) return backup_watcher(s, m, i, out);
    if (s.power_phase == 3) return false;   // over (its last EVENT ran)
    if (ship_skipped(s, i, kP)) return false;
    const ObjectRow* o = m.object(s.ships[i]);
    const int64_t ph = o->_power_subsystem;
    if (ph == -1) return false;     // GetPowerSubsystem() is None: no call
    const SubsystemRow* row =
        ph == kRefUnrepresentable ? nullptr : m.subsystem(ph);
    if (row == nullptr || row->power_kind != kPlant)
        return skip(s, i, kP, SubsystemSkip::REF, ph);
    const SubsystemSkip why = power_unready(m, *row, s.dt);
    s.power = ph;
    // The breach first (Update's first line): it reads only the plant's
    // own row, so an unready rest of the plant cannot keep a destroyed one
    // from latching it.
    if (subsystem_is_destroyed(*row) && !row->_breach_fired) {
        m.set_i(ph, Field::_breach_fired, 1);
        log(s, ph, SubsystemWriteKind::BREACH_FIRED, 0, 1.0);
        s.power_phase = 1;
        s.power_ready_before = why == SubsystemSkip::kCount;
        out = event(s, i, SubsystemEvent::BREACH, ph, 0, 0.0);
        return true;
    }
    if (why != SubsystemSkip::kCount) return skip(s, i, kP, why, ph);
    return power_flow(s, m, i, out);
}

// ── The cloak piece (subsystem_step.h THE CLOAK PIECE) ───────────────────

constexpr int64_t kDecloaked = 0, kCloaking = 1, kCloaked = 2,
                  kDecloaking = 3;   // CloakingSubsystem.CLOAK_*

// THE CLOAK PIECE for ship i. Returns true with `out` set when it stops for
// a record (its last line's EVENT); false when it is over.
bool cloak_piece(SubsystemSession& s, Mirror& m, size_t i,
                 SubsystemRecord& out) {
    constexpr SubsystemPiece kP = SubsystemPiece::CLOAK;
    if (ship_skipped(s, i, kP)) return false;
    const int64_t ch = m.object(s.ships[i])->_cloaking_subsystem;
    if (ch == -1) return false;     // GetCloakingSubsystem() is None
    const SubsystemRow* row =
        ch == kRefUnrepresentable ? nullptr : m.subsystem(ch);
    if (row == nullptr || row->power_kind != kConsumerCloak)
        return skip(s, i, kP, SubsystemSkip::REF, ch);
    const int64_t state = row->_cloak_state;
    const bool trying = state == kCloaking || state == kCloaked;
    // offline = IsDisabled() or IsDestroyed(): _force_decloak, a no-op
    // unless trying to cloak.
    if (subsystem_is_disabled(*row) || subsystem_is_destroyed(*row)) {
        if (!trying) return false;
        out = event(s, i, SubsystemEvent::FORCE_DECLOAK, ch, 0, 0.0);
        return true;
    }
    if (trying && row->CLOAK_RESERVE_DRAIN_PER_SECOND > 0.0 &&
        row->_backup_reserve <= m.globals().MIN_RESERVE_TO_HOLD_CLOAK) {
        out = event(s, i, SubsystemEvent::FORCE_DECLOAK, ch, 0, 0.0);
        return true;
    }
    if (state != kCloaking && state != kDecloaking) return false;
    // self._transition_elapsed += float(dt)
    const double elapsed = row->_transition_elapsed + s.dt;
    put_f(s, m, ch, Field::_transition_elapsed,
          SubsystemWriteKind::TRANSITION_ELAPSED, row->_transition_elapsed,
          elapsed);
    if (elapsed < row->_transition_duration) return false;
    const int64_t done = state == kCloaking ? kCloaked : kDecloaked;
    m.set_i(ch, Field::_cloak_state, done);
    log(s, ch, SubsystemWriteKind::CLOAK_STATE, 0, static_cast<double>(done));
    put_f(s, m, ch, Field::_transition_elapsed,
          SubsystemWriteKind::TRANSITION_ELAPSED, row->_transition_elapsed,
          0.0);
    out = event(s, i, SubsystemEvent::CLOAK_DONE, ch,
                done == kCloaked ? 1 : 0, 0.0);
    return true;
}

// ── The repair piece (subsystem_step.h THE REPAIR PIECE) ─────────────────

constexpr SubsystemPiece kRepair = SubsystemPiece::REPAIR;

bool notified(const SubsystemRow& bay, int64_t h) {
    const std::vector<int64_t>& n = bay._cannot_complete_notified;
    return std::binary_search(n.begin(), n.end(), h);
}

// `h` into (add) or out of the bay's notified set: the mirror (set_ids
// keeps it sorted and unique) and the log.
void set_notified(SubsystemSession& s, Mirror& m, int64_t bay, int64_t h,
                  bool add) {
    std::vector<int64_t> n = m.subsystem(bay)->_cannot_complete_notified;
    if (add) {
        n.push_back(h);
    } else {
        n.erase(std::remove(n.begin(), n.end(), h), n.end());
    }
    m.set_ids(bay, Field::_cannot_complete_notified, n);
    SubsystemWrite w{bay, SubsystemWriteKind::REPAIR_NOTIFIED, add ? 1 : 0,
                     0.0, h};
    s.writes.push_back(w);
}

// The piece skipped from here on (THE SKIPS): over, nothing further written.
bool repair_skip(SubsystemSession& s, size_t i, SubsystemSkip why,
                 int64_t sub) {
    s.repair_phase = 3;
    return skip(s, i, kRepair, why, sub);
}

// The completions from s.repair_done on, one EVENT each.
bool repair_completions(SubsystemSession& s, size_t i, SubsystemRecord& out) {
    if (s.repair_done >= s.repair_completed.size()) {
        s.repair_phase = 3;
        return false;
    }
    const size_t k = s.repair_done++;
    out = event(s, i, SubsystemEvent::REPAIR_DONE, s.repair_completed[k],
                s.repair, static_cast<double>(k));
    s.repair_phase = 2;
    return true;
}

// The worked items from s.repair_item on (the repair tick's per-item
// loop), each
// given s.repair_per_item. Each gain is damage.h's set_condition, called
// directly: not combat_dmg_set_condition, so neither its dmg_guard_state
// nor its dmg_fast_patched check runs (spec §3 Part A: a patched damage
// function, or an instance patch on the item, is not honoured by the
// native stage). An item the mirror cannot finish has its own writes
// undone and is handed to Python by itself (REPAIR_SET, ruling R8-3).
bool repair_items(SubsystemSession& s, Mirror& m, size_t i,
                  SubsystemRecord& out) {
    s.repair_phase = 4;
    while (s.repair_item < s.repair_worked.size()) {
        const int64_t h = s.repair_worked[s.repair_item++];
        const size_t writes0 = s.dmg.writes.size(),
                     entries0 = s.dmg.entries.size(),
                     undo0 = s.dmg.undo.size();
        try {
            const SubsystemRow* it = m.subsystem(h);
            if (it == nullptr)
                throw std::invalid_argument("a worked item's row is gone");
            double complexity = it->_repair_complexity;
            if (complexity <= 0.0) complexity = 1.0;
            // sub.Repair(per_item / complexity): ShipSubsystem.Repair.
            const double points = s.repair_per_item / complexity;
            if (!(points <= 0.0)) {
                const double mx = subsystem_max_condition(m, *it);
                set_condition(m, h, py_min(mx, it->_condition + points), -1,
                              -1, s.dmg);
            }
            it = m.subsystem(h);
            if (it->_condition >= subsystem_max_condition(m, *it))
                s.repair_completed.push_back(h);
        } catch (const std::invalid_argument&) {
            undo_damage(m, s.dmg.undo, undo0);
            s.dmg.undo.resize(undo0);
            s.dmg.writes.resize(writes0);
            s.dmg.entries.resize(entries0);
            out = event(s, i, SubsystemEvent::REPAIR_SET, h, s.repair,
                        s.repair_per_item);
            return true;
        }
    }
    s.repair_done = 0;
    return repair_completions(s, i, out);
}

// The repair tick after the walk: the per-item share, then the
// items.
bool repair_worked(SubsystemSession& s, Mirror& m, size_t i,
                   SubsystemRecord& out) {
    const SubsystemRow* bay = m.subsystem(s.repair);
    if (bay == nullptr)
        return repair_skip(s, i, SubsystemSkip::BAY_GONE, s.repair);
    double pct;
    try {
        pct = condition_percentage(m, *bay);
    } catch (const std::invalid_argument&) {
        return repair_skip(s, i, SubsystemSkip::OFFLINE, s.repair);
    }
    // raw = points * self.GetConditionPercentage() * float(dt)
    const double raw = s.repair_points * pct * s.dt;
    s.repair_per_item = raw / static_cast<double>(s.repair_worked.size());
    s.repair_completed.clear();
    s.repair_item = 0;
    return repair_items(s, m, i, out);
}

// THE WALK from s.repair_index on.
bool repair_walk(SubsystemSession& s, Mirror& m, size_t i,
                 SubsystemRecord& out) {
    const int64_t bh = s.repair;
    for (;;) {
        const SubsystemRow* bay = m.subsystem(bh);
        if (bay == nullptr)
            return repair_skip(s, i, SubsystemSkip::BAY_GONE, bh);
        // `for sub in self._queue`: the list as it is now, at the index the
        // iterator holds.
        if (s.repair_index >= bay->_queue.size()) break;
        if (static_cast<int64_t>(s.repair_worked.size()) >= s.repair_teams)
            break;
        const int64_t h = bay->_queue[s.repair_index];
        const SubsystemRow* it =
            h < 0 ? nullptr : m.subsystem(h);
        ++s.repair_index;
        if (it == nullptr) {
            // A member the mirror cannot name: passed over (ruling R8-4).
            skip(s, i, kRepair, SubsystemSkip::QUEUE_MEMBER, h);
            continue;
        }
        if (it->_condition <= 0.0) {
            if (!notified(*bay, h)) {
                set_notified(s, m, bh, h, true);
                s.repair_phase = 1;
                out = event(s, i, SubsystemEvent::REPAIR_CANNOT, h, bh, 0.0);
                return true;
            }
            continue;
        }
        if (notified(*bay, h)) set_notified(s, m, bh, h, false);
        s.repair_worked.push_back(h);
    }
    if (s.repair_worked.empty()) {
        s.repair_phase = 3;
        return false;
    }
    return repair_worked(s, m, i, out);
}

// THE REPAIR PIECE for ship i (as shield_piece).
bool repair_piece(SubsystemSession& s, Mirror& m, size_t i,
                  SubsystemRecord& out) {
    if (s.repair_phase == 1) return repair_walk(s, m, i, out);
    if (s.repair_phase == 4) return repair_items(s, m, i, out);
    if (s.repair_phase == 2) return repair_completions(s, i, out);
    if (s.repair_phase == 3) return false;
    if (ship_skipped(s, i, kRepair)) return false;
    const int64_t bh = m.object(s.ships[i])->_repair_subsystem;
    if (bh == -1) return false;     // GetRepairSubsystem() is None
    const SubsystemRow* bay =
        bh == kRefUnrepresentable ? nullptr : m.subsystem(bh);
    if (bay == nullptr || bay->is_repair_bay != 1)
        return skip(s, i, kRepair, SubsystemSkip::REF, bh);
    // `if dt is None or dt <= 0.0 or not self._queue: return`
    if (s.dt <= 0.0 || bay->_queue.empty()) return false;
    if (bay->_condition <= 0.0) return false;
    // GetNumRepairTeams() / GetMaxRepairPoints(): 0 / 0.0 with no property.
    if (bay->_property == -1) return false;
    const PropertyRow* prop = bay->_property == kRefUnrepresentable
                                  ? nullptr
                                  : m.property(bay->_property);
    if (prop == nullptr || prop->repair_props_ok != 1)
        return skip(s, i, kRepair, SubsystemSkip::PROPERTY, bh);
    const int64_t teams = prop->NumRepairTeams;
    const double points = prop->MaxRepairPoints;
    if (teams <= 0 || points <= 0.0) return false;
    // The percentage the gains need, answerable before any write (it is
    // read again after the walk, as BC's tick reads it there).
    try {
        (void)condition_percentage(m, *bay);
    } catch (const std::invalid_argument&) {
        return skip(s, i, kRepair, SubsystemSkip::OFFLINE, bh);
    }
    s.repair = bh;
    s.repair_teams = teams;
    s.repair_points = points;
    s.repair_index = 0;
    s.repair_worked.clear();
    s.repair_completed.clear();
    s.repair_item = 0;
    s.repair_per_item = 0.0;
    s.repair_done = 0;
    s.repair_phase = 1;
    return repair_walk(s, m, i, out);
}

void end_piece(SubsystemSession& s) {
    ++s.piece;
    s.shield_phase = 0;
    s.shield_watcher = 0;
    s.shield = -1;
    s.power_phase = 0;
    s.power = -1;
    s.power_backup_cap = 0.0;
    s.power_ready_before = false;
    // repair_worked / repair_completed are kept: REPAIR_DONE's handlers read
    // them (combat_subsys_repair_state) after the record that ended the
    // piece.
    s.repair_phase = 0;
}

}  // namespace

SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt) {
    SubsystemSession s;
    s.ships.assign(ship_handles.begin(), ship_handles.end());
    s.had_row.reserve(s.ships.size());
    for (int64_t h : s.ships)
        s.had_row.push_back(h >= 0 && m.valid(h) ? 1 : 0);
    s.lost_row.assign(s.ships.size(), 0);
    s.dt = dt;
    return s;
}

SubsystemRecord next(SubsystemSession& s, Mirror& m) {
    if (s.done)
        throw std::logic_error(
            "subsystem stage: next() after the session returned DONE");
    s.writes.clear();
    s.dmg.clear();
    while (s.ship_pos < s.ships.size()) {
        const size_t i = s.ship_pos;
        const int64_t h = s.ships[i];
        if (s.piece >= kPieces) {
            ++s.ship_pos;
            s.piece = 0;
            continue;
        }
        // FREED ROWS: live at begin, gone now -- the rest of this ship's
        // pieces are skipped (LOST_ROW), and its row (the handle may name a
        // reused slot) is never read again.
        if (s.had_row[i] && !s.lost_row[i] && !m.valid(h)) s.lost_row[i] = 1;
        if (s.piece < static_cast<int32_t>(SubsystemPiece::ARTICULATION)) {
            SubsystemRecord r;
            bool stopped;
            switch (static_cast<SubsystemPiece>(s.piece)) {
                case SubsystemPiece::SHIELD:
                    stopped = shield_piece(s, m, i, r);
                    break;
                case SubsystemPiece::POWER:
                    stopped = power_piece(s, m, i, r);
                    break;
                case SubsystemPiece::CLOAK:
                    // Every record of the cloak piece is its last line.
                    stopped = cloak_piece(s, m, i, r);
                    if (stopped) end_piece(s);
                    break;
                default:
                    stopped = repair_piece(s, m, i, r);
                    break;
            }
            // An EVENT stops inside a piece (the cursor stays on it, its
            // sub-piece position kept; phase 3 once its last line ran).
            if (!stopped) {
                end_piece(s);
                continue;
            }
            return r;
        }
        // ARTICULATION (THE ARTICULATION PIECE): tick_ship's `_rigless_key`
        // early-out, decided here. A ship tick_ship has found rigless at the
        // current articulated-part generation does nothing; every other ship
        // (rigged, never ticked, generation bumped since, row gone) is
        // Python's: articulation.tick_ship is kept.
        if (s.had_row[i] && !s.lost_row[i] && m.valid(h)) {
            const int64_t g = m.object(h)->_rigless_gen;
            if (g != 0 && g == m.globals().ARTICULATION_GEN + 1) {
                end_piece(s);
                continue;
            }
        }
        SubsystemRecord r;
        r.type = SubsystemRecordType::RUN_PYTHON;
        r.ship_pos = static_cast<int64_t>(i);
        r.ship = h;
        r.kind = s.piece;
        ++s.piece;      // resume exactly after this record
        return r;
    }
    s.done = true;
    SubsystemRecord done;
    done.code = static_cast<int64_t>(s.skips.size());
    return done;
}

void repair_complete(SubsystemSession& s, int64_t h) {
    if (s.repair_phase != 4 || s.repair_item == 0 ||
        s.repair_worked[s.repair_item - 1] != h)
        throw std::logic_error(
            "subsystem stage: repair_complete for an item the session did "
            "not hand to Python (REPAIR_SET)");
    s.repair_completed.push_back(h);
}

uint64_t skip_count(SubsystemPiece p, SubsystemSkip why) {
    return g_skips[static_cast<size_t>(p)][static_cast<size_t>(why)];
}

SubsystemWriteStats write_stats() { return {g_logged, g_identical}; }

void reset_write_stats() { g_logged = g_identical = 0; }

void reset_skip_counts() {
    for (auto& row : g_skips)
        for (auto& n : row) n = 0;
}

}  // namespace subsystems

}  // namespace dauntless::combat
