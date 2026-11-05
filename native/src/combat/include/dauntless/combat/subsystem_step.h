#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "dauntless/combat/mirror.h"

// The subsystem stage, native (phase 6 A1; plan
// docs/superpowers/plans/2026-11-05-phase6-b0-a1-subsystems.md, stage map
// docs/superpowers/plans/2026-11-05-phase6-a1-subsystem-stage-map.md).
//
// engine/core/loop.py's _update_ship_subsystems walks each ship in roster
// order and runs, per ship, five pieces in this order: the shield
// generator's Update, the power plant's Update (with the consumer pump), the
// cloak's Update, the repair bay's Update, and articulation.tick_ship. This
// session walks the same (ship, piece) grid and hands each cell back to
// Python as a record, in the K0 session's shape (k0_charging.h): begin
// snapshots the ship list, next runs the walk to the first thing only Python
// may do and returns it, and the following next resumes exactly after it.
//
// THE RECORDS.
//   RUN_PYTHON{ship, kind}  Python runs that piece of that ship (`kind` a
//                           SubsystemPiece), as the Python loop does: the
//                           piece's getter asked at that moment, its call
//                           made only when it returns a subsystem.
//   EVENT{ship, kind, code, a, b}
//                           an SDK-visible event a native piece must post
//                           before the walk goes on (plan ruling R3: stop
//                           and resume, never batched). `kind` indexes the
//                           driver's event table (native_subsystems.
//                           _EVENT_HANDLERS), `code`, `a` and `b` are its
//                           payload. No piece is native yet (Task 2), so
//                           none is produced: Tasks 3-5 add the kinds.
//   DONE                    the walk is over. Asking again is a protocol
//                           error (std::logic_error).
//
// THE CURSOR. (ship position, piece): the next record is the first cell at
// or after it. Python runs between records (a RUN_PYTHON piece, an EVENT's
// handlers), and what it changes is read again by the next next(): the
// mirror is live, every Native* write pushes to it (plan ruling R1).
//
// FREED ROWS (Review Focus 3). A ship whose row was live at begin and is not
// any more (a handler destroyed it and its row was freed) is skipped from
// that point: no record of it is returned again, and no row of it is read.
// A ship with no row at begin (-1, or a handle already stale) is not one:
// the Python stage updates it, so every piece of it is RUN_PYTHON.
//
// In Task 2 every cell is RUN_PYTHON, so the stage's behaviour is the Python
// loop's by construction. Tasks 3-6 make pieces native one kind at a time;
// Task 8 deletes the Python stage.

namespace dauntless::combat {

// What a record is (combat_subsys_kinds() names them).
enum class SubsystemRecordType : int32_t {
    DONE = 0,
    RUN_PYTHON = 1,
    EVENT = 2,
    kCount
};

// The five pieces of one ship, in the Python loop's order.
enum class SubsystemPiece : int32_t {
    SHIELD = 0,
    POWER = 1,
    CLOAK = 2,
    REPAIR = 3,
    ARTICULATION = 4,
    kCount
};

const char* subsystem_record_type_name(SubsystemRecordType t);
const char* subsystem_piece_name(SubsystemPiece p);

struct SubsystemRecord {
    SubsystemRecordType type = SubsystemRecordType::DONE;
    // RUN_PYTHON / EVENT: the position in begin's ship list and the ship's
    // handle as given there (-1 for a ship with no row). DONE: -1.
    int64_t ship_pos = -1;
    int64_t ship = -1;
    // RUN_PYTHON: a SubsystemPiece. EVENT: the event kind. DONE: -1.
    int32_t kind = -1;
    // EVENT's payload (0 otherwise).
    int64_t code = 0;
    double a = 0.0;
    double b = 0.0;
};

struct SubsystemSession {
    std::vector<int64_t> ships;      // Object handles, roster order
    std::vector<uint8_t> had_row;    // live at begin (FREED ROWS)
    double dt = 0.0;
    // THE CURSOR: the next cell to consider.
    size_t ship_pos = 0;
    int32_t piece = 0;
    bool done = false;               // DONE was returned
};

namespace subsystems {

// One stage over `ship_handles` (roster order; -1: a ship with no row) for
// a tick of `dt`. Reads which handles are live; writes nothing.
SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt);

// The next record (THE RECORDS). Throws std::logic_error after DONE.
SubsystemRecord next(SubsystemSession& s, Mirror& m);

}  // namespace subsystems

}  // namespace dauntless::combat
