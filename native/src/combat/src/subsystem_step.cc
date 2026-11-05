// The subsystem stage session (subsystem_step.h).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/subsystem_step.h"

#include <stdexcept>

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

namespace subsystems {

namespace {

constexpr int32_t kPieces = static_cast<int32_t>(SubsystemPiece::kCount);

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
        // Every piece is Python's (Task 2); a ship with no row, or one that
        // lost it, stays Python's once pieces are native.
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
