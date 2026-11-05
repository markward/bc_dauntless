// The subsystem stage session (subsystem_step.h).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/subsystem_step.h"

#include <array>
#include <cstddef>
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
        case SubsystemEvent::kCount: break;
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

void log(SubsystemSession& s, int64_t sub, SubsystemWriteKind what,
         int32_t index, double v) {
    s.writes.push_back(SubsystemWrite{sub, what, index, v});
}

SubsystemRecord python_piece(const SubsystemSession& s, size_t i,
                             SubsystemPiece p = SubsystemPiece::SHIELD) {
    SubsystemRecord r;
    r.type = SubsystemRecordType::RUN_PYTHON;
    r.ship_pos = static_cast<int64_t>(i);
    r.ship = s.ships[i];
    r.kind = static_cast<int32_t>(p);
    return r;
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
        if (row == nullptr || !shield_ready(*row, at) ||
            (s.python_pieces & piece_bit(SubsystemPiece::SHIELD))) {
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
        m.set_float_at(sh, Field::shield_watch_values, static_cast<size_t>(w),
                       v);
        log(s, sh, SubsystemWriteKind::SHIELD_WATCH, w, v);
    }
    return false;
}

// THE SHIELD PIECE for ship i. Returns true with `out` set when the piece
// stops for a record (RUN_PYTHON, or an EVENT inside it); false when it
// is over (natively, or with nothing to do).
bool shield_piece(SubsystemSession& s, Mirror& m, size_t i,
                  SubsystemRecord& out) {
    if (s.shield_phase == 1) {
        if (shield_watchers(s, m, i, out)) return true;
        return false;
    }
    const bool python =
        !s.had_row[i] || s.lost_row[i] ||
        (s.python_pieces & piece_bit(SubsystemPiece::SHIELD));
    if (python) {
        out = python_piece(s, i);
        return true;
    }
    const ObjectRow* o = m.object(s.ships[i]);
    // The ship's raw ref: -1 is `_shield_subsystem is None` (no call), a
    // stale handle a row dropped since (the generator lives on: Python's).
    const int64_t sh = o->_shield_subsystem;
    if (sh == -1) return false;
    const SubsystemRow* row =
        sh == kRefUnrepresentable ? nullptr : m.subsystem(sh);
    std::array<size_t, kWatchers> at{};
    if (row == nullptr || !shield_ready(*row, at)) {
        out = python_piece(s, i);
        return true;
    }
    const double period = m.globals().SHIELD_CHARGE_PERIOD_S;
    // self._charge_accum = self._charge_accum + float(dt)
    const double accum = row->_charge_accum + s.dt;
    if (accum < period) {
        m.set_f(sh, Field::_charge_accum, accum);
        log(s, sh, SubsystemWriteKind::CHARGE_ACCUM, 0, accum);
        return false;
    }
    // _is_offline(self) is asked after the ramp refresh, which none of its
    // inputs read: asked first, so a question the mirror cannot answer
    // hands the whole piece back with nothing written.
    bool offline;
    try {
        offline = subsystem_is_offline(m, *row);
    } catch (const std::invalid_argument&) {
        out = python_piece(s, i);
        return true;
    }
    const double dt = accum;
    m.set_f(sh, Field::_charge_accum, 0.0);
    log(s, sh, SubsystemWriteKind::CHARGE_ACCUM, 0, 0.0);
    for (size_t f = 0; f < kFaces; ++f) {
        const double mx = row->_max_shields[f];
        const double ramp = mx > 0.0 ? row->_current_shields[f] / mx : 0.0;
        m.set_float_at(sh, Field::_ramp_fraction, f, ramp);
        m.set_float_at(sh, Field::_ramp_set, f, 1.0);
        log(s, sh, SubsystemWriteKind::RAMP, static_cast<int32_t>(f), ramp);
    }
    if (offline) {
        bool any = false;
        for (double x : row->_current_shields) any = any || x != 0.0;
        if (!any) return false;
        for (size_t f = 0; f < kFaces; ++f) {
            m.set_float_at(sh, Field::_current_shields, f, 0.0);
            log(s, sh, SubsystemWriteKind::FACE, static_cast<int32_t>(f),
                0.0);
        }
    } else {
        for (size_t f = 0; f < kFaces; ++f) {
            const double mx = row->_max_shields[f];
            if (mx == 0.0) continue;
            double v = row->_current_shields[f] + row->_charge_per_second[f] * dt;
            if (v > mx) v = mx;
            m.set_float_at(sh, Field::_current_shields, f, v);
            log(s, sh, SubsystemWriteKind::FACE, static_cast<int32_t>(f), v);
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
// answers. Asks nothing that writes; a throw of the offline question or the
// condition percentage is "not ready".
bool power_flow_ready(const Mirror& m, const SubsystemRow& p, double dt) {
    if (p._property == -1) return true;     // the flow is `return`
    if (p._property == kRefUnrepresentable) return false;
    const PropertyRow* prop = m.property(p._property);
    if (prop == nullptr || prop->power_props_ok != 1) return false;
    size_t at[kBatteryWatchers];
    if (!battery_watch_ready(p, at)) return false;
    // GetParentShip(): `_parent_ship` itself (a ref of -1 climbs: Python's).
    if (p._parent_ship < 0) return false;
    const ObjectRow* ship = m.object(p._parent_ship);
    if (ship == nullptr || !ship->is_ship_class) return false;
    for (int64_t c : ship->_powered_consumers)
        if (!consumer_ready(m, c)) return false;
    if (p._interval_elapsed + dt >= m.globals().POWER_INTERVAL) {
        try {
            (void)subsystem_is_offline(m, p);
            (void)condition_percentage(m, p);
        } catch (const std::invalid_argument&) {
            return false;
        }
    }
    return true;
}

// The plant's pools and budgets while the piece runs; `wrote_*`: the
// Python piece assigned that attribute this tick (only those are logged).
struct Plant {
    double main, backup, main_conduit, backup_conduit, available, dispensed;
    bool wrote_main = false, wrote_backup = false, wrote_budgets = false,
         wrote_dispensed = false;
};

// PowerSubsystem._draw_main / _draw_backup (min of three, Python's fold).
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

// PowerSubsystem._draw (`amount` > 0 here, as every caller guards).
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
    m.set_f(c, Field::_power_wanted, wanted);
    m.set_f(c, Field::_power_received, received);
    m.set_f(c, Field::_efficiency, eff);
    m.set_f(c, Field::_power_factor, factor);
    log(s, c, SubsystemWriteKind::POWER_WANTED, 0, wanted);
    log(s, c, SubsystemWriteKind::POWER_RECEIVED, 0, received);
    log(s, c, SubsystemWriteKind::EFFICIENCY, 0, eff);
    log(s, c, SubsystemWriteKind::POWER_FACTOR, 0, factor);
}

// One consumer's _update_power(dt, plant) by its power_kind.
void update_power(SubsystemSession& s, Mirror& m, int64_t h, Plant& p) {
    const double dt = s.dt;
    if (dt <= 0.0) return;
    // Every input is read before this consumer's own row is written (the
    // rows never move: a write reallocates nothing).
    const SubsystemRow& c = *m.subsystem(h);
    if (c.power_kind == kConsumerCloak) {
        // CloakingSubsystem._update_power; _wants_power is IsTryingToCloak.
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
        m.set_f(h, Field::_backup_reserve, p.backup);
        log(s, h, SubsystemWriteKind::BACKUP_RESERVE, 0, p.backup);
        return;
    }
    // PoweredSubsystem._update_power; the tractor's _wants_power also needs
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
    check_offsets(p.power_watch_checks, kBatteryWatchers, at);
    if (any_check_crossed(p.power_watch_checks, at[w],
                          p.power_watch_values[w], v)) {
        out = event(s, i, SubsystemEvent::BATTERY_WATCHER, ph,
                    static_cast<int64_t>(w), v);
        return true;
    }
    m.set_float_at(ph, Field::power_watch_values, w, v);
    log(s, ph, SubsystemWriteKind::BATTERY_WATCH, static_cast<int32_t>(w), v);
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
    if (p == nullptr || !battery_watch_ready(*p, at) ||
        (s.python_pieces & piece_bit(SubsystemPiece::POWER))) {
        out = event(s, i, SubsystemEvent::POWER_TAIL, ph, 1, cap);
        return true;
    }
    const double v = cap > 0.0 ? p->_backup_battery_power / cap : 0.0;
    return battery_watcher(s, m, i, ph, 1, v, out);
}

// Update's lines after the breach, on a ready plant `ph`. True with `out`
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
            // _add_power_to_batteries(GetPowerOutput() * elapsed)
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
    // The pump (PowerSubsystem._pump_consumers): the parent ship's list.
    const std::vector<int64_t>& consumers =
        m.object(row._parent_ship)->_powered_consumers;
    bool wrote_total = false;
    double total = 0.0;
    if (!consumers.empty()) {
        for (int64_t c : consumers) update_power(s, m, c, p);
        for (int64_t c : consumers) total += m.subsystem(c)->_power_wanted;
        wrote_total = true;
    }
    m.set_f(ph, Field::_interval_elapsed, interval);
    log(s, ph, SubsystemWriteKind::INTERVAL_ELAPSED, 0, interval);
    if (p.wrote_dispensed) {
        m.set_f(ph, Field::_power_dispensed, p.dispensed);
        log(s, ph, SubsystemWriteKind::POWER_DISPENSED, 0, p.dispensed);
    }
    if (p.wrote_main) {
        m.set_f(ph, Field::_main_battery_power, p.main);
        log(s, ph, SubsystemWriteKind::MAIN_BATTERY, 0, p.main);
    }
    if (p.wrote_backup) {
        m.set_f(ph, Field::_backup_battery_power, p.backup);
        log(s, ph, SubsystemWriteKind::BACKUP_BATTERY, 0, p.backup);
    }
    if (p.wrote_budgets) {
        m.set_f(ph, Field::_main_conduit_current, p.main_conduit);
        m.set_f(ph, Field::_backup_conduit_current, p.backup_conduit);
        m.set_f(ph, Field::_available_power, p.available);
        log(s, ph, SubsystemWriteKind::MAIN_CONDUIT, 0, p.main_conduit);
        log(s, ph, SubsystemWriteKind::BACKUP_CONDUIT, 0, p.backup_conduit);
        log(s, ph, SubsystemWriteKind::AVAILABLE_POWER, 0, p.available);
    }
    if (wrote_total) {
        m.set_f(ph, Field::_power_wanted_total, total);
        log(s, ph, SubsystemWriteKind::POWER_WANTED_TOTAL, 0, total);
    }
    log(s, ph, SubsystemWriteKind::PASSIVE_POWER_DROP, 0, 0.0);
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
    const bool hooked =
        (s.python_pieces & piece_bit(SubsystemPiece::POWER)) != 0;
    if (s.power_phase == 1) {
        // Resumed after the breach's handlers.
        const SubsystemRow* row = m.subsystem(s.power);
        if (row == nullptr || hooked || !power_flow_ready(m, *row, s.dt)) {
            s.power_phase = 3;
            out = event(s, i, SubsystemEvent::POWER_TAIL, s.power, 0, 0.0,
                        s.dt);
            return true;
        }
        return power_flow(s, m, i, out);
    }
    if (s.power_phase == 2) return backup_watcher(s, m, i, out);
    if (s.power_phase == 3) return false;   // over (its last EVENT ran)
    if (!s.had_row[i] || s.lost_row[i] || hooked) {
        out = python_piece(s, i, SubsystemPiece::POWER);
        return true;
    }
    const ObjectRow* o = m.object(s.ships[i]);
    const int64_t ph = o->_power_subsystem;
    if (ph == -1) return false;     // GetPowerSubsystem() is None: no call
    const SubsystemRow* row =
        ph == kRefUnrepresentable ? nullptr : m.subsystem(ph);
    if (row == nullptr || row->power_kind != kPlant ||
        !power_flow_ready(m, *row, s.dt)) {
        out = python_piece(s, i, SubsystemPiece::POWER);
        return true;
    }
    s.power = ph;
    if (subsystem_is_destroyed(*row) && !row->_breach_fired) {
        m.set_i(ph, Field::_breach_fired, 1);
        log(s, ph, SubsystemWriteKind::BREACH_FIRED, 0, 1.0);
        s.power_phase = 1;
        out = event(s, i, SubsystemEvent::BREACH, ph, 0, 0.0);
        return true;
    }
    return power_flow(s, m, i, out);
}

void end_piece(SubsystemSession& s) {
    ++s.piece;
    s.shield_phase = 0;
    s.shield_watcher = 0;
    s.shield = -1;
    s.power_phase = 0;
    s.power = -1;
    s.power_backup_cap = 0.0;
}

}  // namespace

SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt, uint32_t python_pieces) {
    SubsystemSession s;
    s.ships.assign(ship_handles.begin(), ship_handles.end());
    s.had_row.reserve(s.ships.size());
    for (int64_t h : s.ships)
        s.had_row.push_back(h >= 0 && m.valid(h) ? 1 : 0);
    s.lost_row.assign(s.ships.size(), 0);
    s.dt = dt;
    s.python_pieces = python_pieces;
    return s;
}

SubsystemRecord next(SubsystemSession& s, Mirror& m) {
    if (s.done)
        throw std::logic_error(
            "subsystem stage: next() after the session returned DONE");
    s.writes.clear();
    while (s.ship_pos < s.ships.size()) {
        const size_t i = s.ship_pos;
        const int64_t h = s.ships[i];
        if (s.piece >= kPieces) {
            ++s.ship_pos;
            s.piece = 0;
            continue;
        }
        // FREED ROWS: live at begin, gone now -- the rest of this ship is
        // Python's, and its row (the handle may name a reused slot) is
        // never read again.
        if (s.had_row[i] && !s.lost_row[i] && !m.valid(h)) s.lost_row[i] = 1;
        if (s.piece == static_cast<int32_t>(SubsystemPiece::SHIELD)) {
            SubsystemRecord r;
            const bool stopped = shield_piece(s, m, i, r);
            // A RUN_PYTHON is the whole piece; an EVENT stops inside it
            // (the cursor stays on SHIELD, the watcher loop's position kept).
            if (!stopped || r.type == SubsystemRecordType::RUN_PYTHON)
                end_piece(s);
            if (stopped) return r;
            continue;
        }
        if (s.piece == static_cast<int32_t>(SubsystemPiece::POWER)) {
            SubsystemRecord r;
            const bool stopped = power_piece(s, m, i, r);
            // As the shield's: an EVENT stops inside the piece (the next
            // next() resumes there, phase 3 once its last line ran).
            if (!stopped || r.type == SubsystemRecordType::RUN_PYTHON)
                end_piece(s);
            if (stopped) return r;
            continue;
        }
        // The other pieces are Python's (Tasks 5-6 make them native); a
        // ship with no row, or one that lost it, stays Python's.
        SubsystemRecord r;
        r.type = SubsystemRecordType::RUN_PYTHON;
        r.ship_pos = static_cast<int64_t>(i);
        r.ship = h;
        r.kind = s.piece;
        ++s.piece;      // resume exactly after this record
        return r;
    }
    s.done = true;
    return SubsystemRecord{};
}

}  // namespace subsystems

}  // namespace dauntless::combat
