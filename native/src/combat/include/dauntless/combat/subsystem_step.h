#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "dauntless/combat/damage.h"
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
// (subsystem_is_offline throws), or python_pieces names SHIELD (a
// test-facing hook). A script that patches ShieldSubsystem's methods is
// NOT honoured (spec §3 "Mods and patches (Part A)": BC's per-tick update
// was internal C++ that ignored such patches). Then:
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
// longer native-ready (its handler dropped it, replaced a watcher, ...)
// or python_pieces now names SHIELD,
// the rest of the loop is EVENT{SHIELD_WATCHER_TAIL, code = first index}:
// Python runs the Python loop's remaining lines on that same generator.
//
// THE POWER PIECE (Task 4): PowerSubsystem.Update (engine/appc/
// subsystems.py) with its consumer pump, bit for bit, on the plant the
// ship's `_power_subsystem` names. The ship's row ref decides as the
// shield's does: -1 (None) is no call; kRefUnrepresentable, a since-freed
// row or a row whose power_kind is not a plant's is RUN_PYTHON. A live
// plant is native unless something the piece will read is one the mirror
// cannot answer -- then RUN_PYTHON with NOTHING written (power_ready):
// its `_property` unrepresentable or not power_props_ok; its battery
// watchers not power_watch_ok; its `_parent_ship` (whose
// `_powered_consumers` the pump walks) not a live ShipClass row; a
// consumer not a live row of a known power_kind (a tractor system's
// children not all live tractor beams); the interval's `_is_offline`
// question or condition percentage unanswerable; or python_pieces names
// POWER. A script patching PowerSubsystem's, a consumer's or a property's
// methods is not honoured (spec §3 "Mods and patches (Part A)"), and
// neither is a consumer class's own GetPowerWanted: the wanted total is
// the attach-order sum of `_power_wanted`, which is what
// PowerSubsystem._sum_wanted's _BASE_GET_POWER_WANTED guard reads for
// every consumer class the engine has. Then, in Python's order:
//   breach: IsDestroyed() and not _breach_fired -> _breach_fired = True,
//           then EVENT{BREACH}: Python runs plant._trigger_breach() (its
//           targetable gate and death_check.note_breach), and the next
//           next() resumes after it;
//   no property: done (no interval, no pump, no watchers);
//   interval = interval + dt; at >= POWER_INTERVAL: elapsed = interval,
//           interval = 0 (RESET, not subtracted), dispensed = 0; unless
//           offline the recharge (PowerOutput * condPct * elapsed) fills
//           main up to MainBatteryLimit, spills to backup up to
//           BackupBatteryLimit, discards the rest; the conduit budgets,
//           UNCONDITIONALLY: main = min(main battery, MainConduitCapacity *
//           condPct * elapsed), backup = min(backup battery,
//           BackupConduitCapacity * elapsed); available = their sum;
//   the pump, when the parent ship has consumers: each consumer in attach
//           order, by its power_kind (PoweredSubsystem._update_power, the
//           tractor's _wants_power, CloakingSubsystem._update_power):
//           not wanting power zeroes its four draw fields (the cloak also
//           snapshots the backup battery into _backup_reserve); a free
//           consumer (normal*dt <= 0) is 0/0/1/1; DRAWS_DIRECT_FROM_MAIN
//           steals normal*dt from the main battery (StealPower) and the
//           cloak CLOAK_RESERVE_DRAIN_PER_SECOND*dt from the backup
//           (StealPowerFromReserve), NEITHER counted in _power_dispensed;
//           every other consumer draws normal*dt*slider through _draw by
//           its POWER_MODE (0 main first, 1 backup first, anything else
//           -- PSM_DIRECT_MAIN (3) included -- the final else, backup
//           only), counted in _power_dispensed; then _power_wanted_total
//           is the attach-order sum. Nothing in the pump posts an event;
//   the battery watchers, main then backup, each fed `battery / limit`
//           (0 when the limit is not > 0; both limits read BEFORE the main
//           watcher's update, the backup battery read after it), as the
//           shield watchers are: no check crossed writes the value, any
//           check crossed is EVENT{BATTERY_WATCHER, code = 0 main / 1
//           backup, a = the value}, and Python calls that watcher's
//           `_update(a)`. The next next() resumes with the backup watcher.
// A resume on a plant whose row is gone or no longer native-ready, or with
// python_pieces now naming POWER, hands the rest of the piece to Python on
// that same plant: EVENT{POWER_TAIL, code 0 (everything after the breach;
// b = dt), code 1 (the backup watcher's line; a = the backup limit read
// before the main watcher)}.
// Every native run of the piece also drops the plant's power draw program
// (PASSIVE_POWER_DROP): it described draws the native pump has since
// changed, and the Python path rebuilds one from a full pump.
//
// THE CLOAK PIECE (Task 5): CloakingSubsystem.Update (engine/appc/
// subsystems.py), bit for bit, on the cloak the ship's `_cloaking_subsystem`
// names (decided as the shield's ref is; a live row whose power_kind is not
// a cloak's is RUN_PYTHON). Its offline test is IsDisabled() or
// IsDestroyed() only (not _is_offline). Then, in Python's order:
//   offline: trying to cloak (CLOAKING or CLOAKED) -> EVENT{FORCE_DECLOAK},
//           else nothing;
//   trying to cloak, CLOAK_RESERVE_DRAIN_PER_SECOND > 0 and _backup_reserve
//           (the power piece's snapshot, this tick's) <= MIN_RESERVE_TO_
//           HOLD_CLOAK -> EVENT{FORCE_DECLOAK};
//   CLOAKING or DECLOAKING: _transition_elapsed += dt; at >= its
//           _transition_duration the state snaps (CLOAKED / DECLOAKED) and
//           the clock resets to 0, both written, then EVENT{CLOAK_DONE,
//           code 1 cloaked / 0 decloaked}.
// FORCE_DECLOAK writes nothing first: Python calls the cloak's own
// _force_decloak(), which snaps the state, resets the clock, logs and fires
// ET_DECLOAK_COMPLETED when it was CLOAKED. CLOAK_DONE's state is written
// first, as Update writes it before _fire: Python then calls _fire with the
// completion event. Either EVENT is the piece's last line.
//
// THE REPAIR PIECE (Task 5): RepairSubsystem.Update (engine/appc/
// subsystems.py; its _repair_walk and _repair_worked), bit for bit, on the
// bay the ship's `_repair_subsystem` names (decided as the shield's ref is;
// a live row that is not is_repair_bay is RUN_PYTHON). Its gates are the
// bay's own condition > 0 only (not _is_offline, dying or radiation).
//   dt <= 0, an empty queue, the bay's condition <= 0: done. Its
//           `_property` -1 is no teams: done; unrepresentable, stale or not
//           repair_props_ok: RUN_PYTHON. NumRepairTeams <= 0 or
//           MaxRepairPoints <= 0: done;
//   THE WALK, over the queue as the mirror holds it now, from the cursor
//           (Python's list iterator: the next index of the list as it is):
//           stop when it is past the end or the worked list holds `teams`;
//           a member whose condition is <= 0 is added to
//           _cannot_complete_notified (written) and is EVENT{REPAIR_CANNOT,
//           code = the bay, sub = the member} the first time, and skipped;
//           any other member leaves the notified set (written) and is
//           worked. The next next() resumes the walk at the next index,
//           re-reading the queue (a handler may have changed it: Review
//           Focus 5). A member, or the bay, with no live row, or
//           python_pieces naming REPAIR, at its turn: EVENT{REPAIR_TAIL,
//           code = the bay, a = 0}: Python runs the walk from that index on
//           (`_repair_walk`, the state from combat_subsys_repair_state);
//   none worked: done. Else raw = (points * bayCondPct) * dt, per_item =
//           raw / len(worked); per item gain = per_item / complexity
//           (complexity <= 0 is 1.0), and ShipSubsystem.Repair(gain): gain
//           <= 0 is nothing, else the condition write
//           min(GetMaxCondition(), condition + gain) through damage.h's
//           set_condition (its writes and effect-queue entries in `dmg`,
//           the same as SetCondition's native chain makes; called
//           directly, WITHOUT combat_dmg_set_condition's dmg_guard_state /
//           dmg_fast_patched checks: by Part A a patched damage function or
//           an instance patch on the item is not honoured here);
//           completed when the condition is then >= GetMaxCondition().
//           Anything in it the
//           mirror cannot answer (a set_condition fallback, a max
//           condition it cannot read, a row gone) undoes every write of the
//           items worked so far and is EVENT{REPAIR_TAIL, code = the bay,
//           a = 1}: Python runs `_repair_worked` on the same items;
//   the completions, in order: EVENT{REPAIR_DONE, code = the bay, sub = the
//           item, a = its index}: Python discards it from the queue and
//           fires ET_REPAIR_COMPLETED (Update's last loop, one item per
//           record). Each item's row was live when the first was returned
//           (the driver pins them all then).
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
// Task 3 made the SHIELD piece native (THE SHIELD PIECE), Task 4 the POWER
// piece (THE POWER PIECE), Task 5 the CLOAK and REPAIR pieces (THE CLOAK
// PIECE, THE REPAIR PIECE); ARTICULATION is still RUN_PYTHON. Task 6 makes
// it native for rigless ships; Task 8 deletes the Python stage.

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
//   BREACH               plant sub's _trigger_breach() (THE POWER PIECE)
//   BATTERY_WATCHER      plant sub's battery watcher `code` (0 main, 1
//                        backup) ._update(a)
//   POWER_TAIL           the rest of plant sub's Update in Python: code 0
//                        everything after the breach (b = dt), code 1 the
//                        backup watcher's line (a = the backup limit)
//   FORCE_DECLOAK        cloak sub's _force_decloak() (THE CLOAK PIECE)
//   CLOAK_DONE           cloak sub's _fire(ET_CLOAK_COMPLETED) (code 1) or
//                        _fire(ET_DECLOAK_COMPLETED) (code 0)
//   REPAIR_CANNOT        bay `code`'s ET_REPAIR_CANNOT_BE_COMPLETED for its
//                        member sub (THE REPAIR PIECE)
//   REPAIR_DONE          bay `code`'s completion of item sub (index a):
//                        queue discard, then ET_REPAIR_COMPLETED
//   REPAIR_TAIL          the rest of bay `code`'s Update in Python: a 0 the
//                        walk from the cursor, a 1 the worked items' repair
//                        (b = dt)
enum class SubsystemEvent : int32_t {
    SHIELD_WATCHER = 0,
    SHIELD_WATCHER_TAIL = 1,
    BREACH = 2,
    BATTERY_WATCHER = 3,
    POWER_TAIL = 4,
    FORCE_DECLOAK = 5,
    CLOAK_DONE = 6,
    REPAIR_CANNOT = 7,
    REPAIR_DONE = 8,
    REPAIR_TAIL = 9,
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
// (in place for the three lists, as the Python piece writes them); the
// power piece's (THE POWER PIECE):
//   AVAILABLE_POWER .. POWER_WANTED_TOTAL, POWER_WANTED .. BACKUP_RESERVE
//                 sub.__dict__["<the attribute>"] = value (a float)
//   BREACH_FIRED  sub.__dict__["_breach_fired"] = True
//   BATTERY_WATCH sub.__dict__["_main_battery_watcher" (index 0) /
//                    "_backup_battery_watcher" (1)].__dict__["_value"]
//                    = value
//   PASSIVE_POWER_DROP
//                 sub.__dict__["_passive_power"] = None, when it holds
//                    anything else (the power draw program, dropped)
// the cloak's and the bay's (THE CLOAK PIECE, THE REPAIR PIECE):
//   TRANSITION_ELAPSED sub.__dict__["_transition_elapsed"] = value
//   CLOAK_STATE   sub.__dict__["_cloak_state"] = int(value)
//   REPAIR_NOTIFIED sub.__dict__["_cannot_complete_notified"].add(ref)
//                    (index 1) / .discard(ref) (index 0), `ref` a member's
//                    Subsystem handle (the set's key, subsystems.
//                    _notify_key)
enum class SubsystemWriteKind : int32_t {
    CHARGE_ACCUM = 0,
    RAMP,
    FACE,
    SHIELD_WATCH,
    AVAILABLE_POWER,       // _available_power
    MAIN_BATTERY,          // _main_battery_power
    BACKUP_BATTERY,        // _backup_battery_power
    MAIN_CONDUIT,          // _main_conduit_current
    BACKUP_CONDUIT,        // _backup_conduit_current
    INTERVAL_ELAPSED,      // _interval_elapsed
    POWER_DISPENSED,       // _power_dispensed
    POWER_WANTED_TOTAL,    // _power_wanted_total
    POWER_WANTED,          // a consumer's _power_wanted
    POWER_RECEIVED,        // _power_received
    EFFICIENCY,            // _efficiency
    POWER_FACTOR,          // _power_factor
    BACKUP_RESERVE,        // the cloak's _backup_reserve
    BREACH_FIRED,
    BATTERY_WATCH,
    PASSIVE_POWER_DROP,
    TRANSITION_ELAPSED,
    CLOAK_STATE,
    REPAIR_NOTIFIED,
    kCount
};

struct SubsystemWrite {
    int64_t sub = -1;
    SubsystemWriteKind what = SubsystemWriteKind::CHARGE_ACCUM;
    int32_t index = 0;
    double value = 0.0;
    int64_t ref = -1;   // REPAIR_NOTIFIED's member handle
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

// THE ARTICULATION PIECE (Task 6): articulation.tick_ship's `_rigless_key`
// early-out, decided here. tick_ship records `_rigless_gen` = the
// articulated-part generation + 1 on a ship it finds rigless (its first call
// still runs in Python: it caches the leaf and the key); the piece is
// skipped, with no record, iff that equals Global ARTICULATION_GEN + 1 (the
// generation, re-pushed on every bump) and python_pieces does not name
// ARTICULATION, the ship's row is live. Anything else (rigged, never
// ticked, generation moved, row gone) is RUN_PYTHON{ship, ARTICULATION}.

// A bit per piece (SubsystemSession::python_pieces): 1 << SubsystemPiece.
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
    // watcher (Task 3), the plant's breach or main battery watcher (Task 4:
    // the pump itself posts nothing, so no consumer position is needed);
    // Task 5: one repair-queue item -- and the next next() resumes inside
    // that piece: its sub-piece position and partial state are kept here
    // (the shield's and the plant's below), never re-derived.
    size_t ship_pos = 0;
    int32_t piece = 0;
    bool done = false;               // DONE was returned
    // Pieces Python runs for every ship: piece_bit()s. A test-facing hook
    // (native_subsystems.python_pieces), never set in production.
    uint32_t python_pieces = 0;
    // The shield piece's sub-piece position: 0 not begun; 1 inside the
    // watcher loop of generator `shield`, next watcher `watcher` (THE
    // WATCHERS: an EVENT stopped it there).
    int32_t shield_phase = 0;
    int32_t shield_watcher = 0;
    int64_t shield = -1;
    // The power piece's sub-piece position (THE POWER PIECE): 0 not begun;
    // 1 after plant `power`'s BREACH (next: the rest of Update); 2 after
    // its main battery watcher's EVENT (next: the backup watcher, fed
    // against `power_backup_cap`, the backup limit Python read before the
    // main watcher's update).
    int32_t power_phase = 0;
    int64_t power = -1;
    double power_backup_cap = 0.0;
    // The repair piece's sub-piece position (THE REPAIR PIECE): 0 not
    // begun; 1 inside the walk of bay `repair` (a REPAIR_CANNOT stopped
    // it; next: queue index `repair_index`); 2 reporting completions (next:
    // repair_completed[repair_done]); 3 over. Update's locals: the teams
    // and points read before the walk, the items worked and completed.
    int32_t repair_phase = 0;
    int64_t repair = -1;
    size_t repair_index = 0;
    int64_t repair_teams = 0;
    double repair_points = 0.0;
    std::vector<int64_t> repair_worked, repair_completed;
    size_t repair_done = 0;
    std::vector<SubsystemWrite> writes;  // THE WRITE LOG (last next())
    // The repair piece's condition writes (damage.h set_condition): their
    // Python writes and effect-queue entries, cleared by next() on entry
    // and applied by the binding after THE WRITE LOG.
    DamageOut dmg;
};

namespace subsystems {

// One stage over `ship_handles` (roster order; -1: a ship with no row) for
// a tick of `dt`. `python_pieces`: piece_bit()s Python runs for every
// ship (a test-facing hook). Reads which handles are live; writes nothing.
SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt, uint32_t python_pieces = 0);

// The next record (THE RECORDS). Throws std::logic_error after DONE.
SubsystemRecord next(SubsystemSession& s, Mirror& m);

}  // namespace subsystems

}  // namespace dauntless::combat
