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
//   EVENT{ship, kind, code, a, b, sub}
//                           an SDK-visible event a native piece must post
//                           before the walk goes on (plan ruling R3: stop
//                           and resume, never batched). `kind` a
//                           SubsystemEvent, indexing the driver's event
//                           table (native_subsystems._EVENT_HANDLERS);
//                           `code`, `a`, `b` its payload; `sub` the
//                           Subsystem handle the event is about (its row is
//                           live when the record is returned).
//   DONE                    the walk is over. Asking again is a protocol
//                           error (std::logic_error).
//
// THE WRITE LOG. A native piece writes the mirror itself and logs, in
// order, each Python attribute the Python piece would have written
// (SubsystemWrite). next() clears the log on entry; the binding applies it
// into the Python objects (native/src/host/subsystem_write_apply.h) before
// it returns the record, so the Python a record runs -- a RUN_PYTHON piece,
// an EVENT's handlers -- sees every write the walk made before it.
//
// THE SHIELD PIECE (Task 3): ShieldSubsystem.Update (engine/appc/
// subsystems.py), bit for bit, on the generator the ship's
// `_shield_subsystem` names. The ship's row ref decides: -1 (None) is no
// call at all; kRefUnrepresentable, or a since-freed row, is RUN_PYTHON;
// a live row is native unless its shield_watch_ok is 0, a face list is not
// six long, its `_is_offline` question is one the mirror cannot answer
// (is_offline_after_condition throws), or the driver forced the piece to
// Python (python_pieces, forced: an overridden or patched surface). Then:
//   accum = accum + dt; below SHIELD_CHARGE_PERIOD_S: write accum, done.
//   accum = 0; ramp[f] = cur[f]/max[f] (0 where max <= 0, NaN too);
//   offline: if any face is non-zero, every face 0, then the watchers;
//            else done;
//   online:  per face with max != 0, cur = min-by-`>`(cur + cps*dt, max),
//            then the watchers.
// THE WATCHERS: indices 0..5 take GetSingleShieldPercentage(f), 6 takes
// GetShieldPercentage(), each computed from the mirror when its turn comes
// (a handler run for an earlier watcher may have changed this generator).
// A watcher whose new value crosses none of its checks (FloatRangeWatcher.
// _crossed, every check) has the value written; one that crosses any check
// is EVENT{SHIELD_WATCHER, code = index, a = the value}: Python calls that
// watcher's `_update(a)`, which fires the checks and commits the value
// exactly as the Python piece does, and the next next() resumes with the
// next index. When it resumes on a generator whose row is gone or no
// longer native-ready (its handler dropped it, replaced a watcher, ...),
// the rest of the loop is EVENT{SHIELD_WATCHER_TAIL, code = first index}:
// Python runs the Python loop's remaining lines on that same generator.
//
// THE CURSOR. (ship position, piece): the next record is the first cell at
// or after it. Python runs between records (a RUN_PYTHON piece, an EVENT's
// handlers), and what it changes is read again by the next next(): the
// mirror is live, every Native* write pushes to it (plan ruling R1).
//
// FREED ROWS (Review Focus 3). A row can vanish mid-walk while its Python
// object stays alive and in the walk: native_combat._drop(obj) frees it (a
// pose-table or has_shields push that cannot be represented, ...), and the
// Python stage still runs that ship's remaining pieces. So a ship whose row
// was live at begin and is gone at its turn is NOT skipped: from then on its
// remaining pieces, in the normal order, are RUN_PYTHON, and its row is
// never read again (`lost_row`; the handle may name a reused slot). A ship
// with no row at begin (-1, or a handle already stale) is all RUN_PYTHON
// too: the Python stage updates it.
//
// Task 3 made the SHIELD piece native (THE SHIELD PIECE); every other cell
// is still RUN_PYTHON. Tasks 4-6 make the rest native one kind at a time;
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

// What an EVENT record asks Python to do (combat_subsys_kinds() names
// them; native_subsystems._EVENT_HANDLERS has one handler per kind).
//   SHIELD_WATCHER       sub's _shield_watchers[code]._update(a)
//   SHIELD_WATCHER_TAIL  sub's watcher lines from index `code` on, in
//                        Python: faces code..5, then the combined watcher
enum class SubsystemEvent : int32_t {
    SHIELD_WATCHER = 0,
    SHIELD_WATCHER_TAIL = 1,
    kCount
};

const char* subsystem_record_type_name(SubsystemRecordType t);
const char* subsystem_piece_name(SubsystemPiece p);
const char* subsystem_event_name(SubsystemEvent e);

// One logged write (THE WRITE LOG): Subsystem row `sub`'s Python attribute
//   CHARGE_ACCUM  sub.__dict__["_charge_accum"] = value
//   RAMP          sub.__dict__["_ramp_fraction"][index] = value
//   FACE          sub.__dict__["_current_shields"][index] = value
//   SHIELD_WATCH  sub.__dict__["_shield_watchers"][index]
//                    .__dict__["_value"] = value
// (in place for the three lists, as the Python piece writes them).
enum class SubsystemWriteKind : int32_t {
    CHARGE_ACCUM = 0,
    RAMP,
    FACE,
    SHIELD_WATCH,
    kCount
};

struct SubsystemWrite {
    int64_t sub = -1;
    SubsystemWriteKind what = SubsystemWriteKind::CHARGE_ACCUM;
    int32_t index = 0;
    double value = 0.0;
};

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
    // EVENT: the Subsystem handle it is about (-1 otherwise).
    int64_t sub = -1;
};

// A bit per piece (python_pieces, forced): 1 << SubsystemPiece.
constexpr uint32_t piece_bit(SubsystemPiece p) {
    return 1u << static_cast<uint32_t>(p);
}

struct SubsystemSession {
    std::vector<int64_t> ships;      // Object handles, roster order
    std::vector<uint8_t> had_row;    // live at begin (FREED ROWS)
    std::vector<uint8_t> lost_row;   // gone since: the rest is Python's
    double dt = 0.0;
    // THE CURSOR: the next cell to consider, (ship position, piece). A
    // native piece's EVENT is raised PARTWAY through it -- after one shield
    // watcher (Task 3); Tasks 4-5: one consumer of the power pump, one
    // repair-queue item -- and the next next() resumes inside that piece:
    // its sub-piece position and partial state are kept here (the shield's
    // below), never re-derived.
    size_t ship_pos = 0;
    int32_t piece = 0;
    bool done = false;               // DONE was returned
    // Pieces Python runs for every ship (the driver: a patched surface),
    // and per ship (an overridden class or instance). piece_bit()s.
    uint32_t python_pieces = 0;
    std::vector<uint8_t> forced;     // empty, or one mask per ship
    // The shield piece's sub-piece position: 0 not begun; 1 inside the
    // watcher loop of generator `shield`, next watcher `watcher` (THE
    // WATCHERS: an EVENT stopped it there).
    int32_t shield_phase = 0;
    int32_t shield_watcher = 0;
    int64_t shield = -1;
    std::vector<SubsystemWrite> writes;  // THE WRITE LOG (last next())
};

namespace subsystems {

// One stage over `ship_handles` (roster order; -1: a ship with no row) for
// a tick of `dt`. `python_pieces`: piece_bit()s Python runs for every
// ship; `forced`: empty, or one piece mask per ship. Reads which handles
// are live; writes nothing.
SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt, uint32_t python_pieces = 0,
                       std::span<const uint8_t> forced = {});

// The next record (THE RECORDS). Throws std::logic_error after DONE.
SubsystemRecord next(SubsystemSession& s, Mirror& m);

}  // namespace subsystems

}  // namespace dauntless::combat
