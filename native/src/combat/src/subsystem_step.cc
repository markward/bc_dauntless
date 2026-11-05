// The subsystem stage session (subsystem_step.h).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/subsystem_step.h"

#include <array>
#include <cstddef>
#include <stdexcept>

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

// ShipSubsystem.IsDisabled (subsystems.py): reads _max_condition.
bool is_disabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}

// ShipSubsystem.IsDestroyed.
bool is_destroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

// subsystems._is_offline(sub). Throws std::invalid_argument where the
// mirror cannot answer (is_offline_after_condition).
bool is_offline(const Mirror& m, const SubsystemRow& s) {
    if (is_disabled(s) || is_destroyed(s)) return true;
    return is_offline_after_condition(m, s);
}

// Where each watcher's checks start in shield_watch_checks (its count
// there, then its (threshold, code) pairs). False: the list is malformed.
bool check_offsets(const SubsystemRow& s,
                   std::array<size_t, kWatchers>& at) {
    const std::vector<double>& c = s.shield_watch_checks;
    size_t i = 0;
    for (int32_t w = 0; w < kWatchers; ++w) {
        if (i >= c.size()) return false;
        at[static_cast<size_t>(w)] = i;
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
           check_offsets(s, at);
}

// ShieldSubsystem.GetSingleShieldPercentage(f) for f in 0..5, and
// GetShieldPercentage() for the combined watcher (6): `sum` is Python's
// left-to-right float sum from 0.
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

bool any_check_crossed(const SubsystemRow& s, size_t at, double old_v,
                       double new_v) {
    const std::vector<double>& c = s.shield_watch_checks;
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

SubsystemRecord python_piece(const SubsystemSession& s, size_t i) {
    SubsystemRecord r;
    r.type = SubsystemRecordType::RUN_PYTHON;
    r.ship_pos = static_cast<int64_t>(i);
    r.ship = s.ships[i];
    r.kind = static_cast<int32_t>(SubsystemPiece::SHIELD);
    return r;
}

SubsystemRecord event(const SubsystemSession& s, size_t i, SubsystemEvent e,
                      int64_t sub, int64_t code, double a) {
    SubsystemRecord r;
    r.type = SubsystemRecordType::EVENT;
    r.ship_pos = static_cast<int64_t>(i);
    r.ship = s.ships[i];
    r.kind = static_cast<int32_t>(e);
    r.code = code;
    r.a = a;
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
        if (any_check_crossed(*row, at[static_cast<size_t>(w)], old_v, v)) {
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
        (s.python_pieces & piece_bit(SubsystemPiece::SHIELD)) ||
        (!s.forced.empty() &&
         (s.forced[i] & piece_bit(SubsystemPiece::SHIELD)));
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
        offline = is_offline(m, *row);
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

void end_piece(SubsystemSession& s) {
    ++s.piece;
    s.shield_phase = 0;
    s.shield_watcher = 0;
    s.shield = -1;
}

}  // namespace

SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt, uint32_t python_pieces,
                       std::span<const uint8_t> forced) {
    SubsystemSession s;
    s.ships.assign(ship_handles.begin(), ship_handles.end());
    s.had_row.reserve(s.ships.size());
    for (int64_t h : s.ships)
        s.had_row.push_back(h >= 0 && m.valid(h) ? 1 : 0);
    s.lost_row.assign(s.ships.size(), 0);
    s.dt = dt;
    s.python_pieces = python_pieces;
    if (!forced.empty()) {
        if (forced.size() != s.ships.size())
            throw std::invalid_argument(
                "subsystem stage: one forced mask per ship");
        s.forced.assign(forced.begin(), forced.end());
    }
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
        // The other pieces are Python's (Tasks 4-6 make them native); a
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
