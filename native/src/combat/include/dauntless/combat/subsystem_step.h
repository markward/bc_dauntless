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
// The subsystem stage (engine/core/loop.py's _update_ship_subsystems, driven
// by engine/appc/native_subsystems.py) walks each ship in roster order and
// runs, per ship, five pieces in this order: the shield generator's regen,
// the power plant's tick (with the consumer pump), the cloak's transition,
// the repair bay's tick, and articulation.tick_ship. This session walks that
// (ship, piece) grid in the K0 session's shape (k0_charging.h): begin
// snapshots the ship list, next runs the walk to the first thing only Python
// may do -- an SDK event, articulation -- and returns it, and the following
// next resumes exactly after it.
//
// IDENTICAL WRITES ARE SKIPPED. A Python write the mirror missed (an in-place
// mutation with no push) now persists until the native value differs, rather
// than being overwritten each tick; DAUNTLESS_NATIVE_AUDIT=1 is the net.
//
// THE RECORDS.
//   RUN_PYTHON{ship, kind}  Python runs that piece of that ship (`kind` a
//                           SubsystemPiece). Only ARTICULATION is ever
//                           handed back: the other four pieces are native
//                           only (phase 6 Task 8: there is no Python copy
//                           of them), and a piece the mirror cannot run is
//                           SKIPPED (THE SKIPS).
//   EVENT{ship, kind, code, a, b, sub}
//                           an SDK-visible event a native piece must post
//                           before the walk goes on (plan ruling R3: stop
//                           and resume, never batched). `kind` a
//                           SubsystemEvent, indexing the driver's event
//                           table (native_subsystems._EVENT_HANDLERS);
//                           `code`, `a`, `b` its payload; `sub` the
//                           Subsystem handle the event is about (its row is
//                           live when the record is returned).
//   DONE{code}              the walk is over; `code` = the session's skips
//                           (THE SKIPS). Asking again is a protocol error
//                           (std::logic_error).
//
// THE SKIPS (Task 8 rulings R8-1, R8-2, R8-4). A SHIELD, POWER, CLOAK or
// REPAIR piece the mirror cannot run -- a ship with no row (NO_ROW) or a
// row freed mid-walk (LOST_ROW), a subsystem ref the mirror cannot name,
// a row not ready, an offline question it cannot answer -- is not run at
// all: no record, nothing written. Each skip is logged in the session
// (SubsystemSession::skips) and counted per (piece, reason) process-wide
// (skip_count); the driver logs each reason once, and the goldens and the
// audit hold every count at 0. These are defensive: no stock code path
// leads to one (an object the mirror cannot encode, a non-engine class).
// The one per-member skip is the repair walk's QUEUE_MEMBER: an entry the
// mirror cannot name is passed over and the walk goes on.
//
// THE WRITE LOG. A native piece writes the mirror itself and logs, in
// order, each Python attribute the piece writes (the ones the former
// Python piece, deleted in phase 6 Task 8, wrote)
// (SubsystemWrite). next() clears the log on entry; the binding applies it
// into the Python objects (native/src/host/subsystem_write_apply.h) before
// it returns the record, so the Python a record runs -- a RUN_PYTHON piece,
// an EVENT's handlers -- sees every write the walk made before it.
//
// THE SHIELD PIECE (Task 3): the generator's regen (the deleted Python
// ShieldSubsystem.Update's, bit for bit; native only since Task 8), on the
// generator the ship's
// `_shield_subsystem` names. The ship's row ref decides: -1 (None) is no
// call at all; kRefUnrepresentable, or a since-freed row, is a skip (REF);
// a live row is native unless its shield_watch_ok is 0, a face list is not
// six long, or its `_is_offline` question is one the mirror cannot answer
// (subsystem_is_offline throws): then the piece is SKIPPED (THE SKIPS).
// A script that patches ShieldSubsystem's methods is
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
// exactly as the former Python piece did, and the next next() resumes
// with the
// next index. When it resumes on a generator whose row is gone or no
// longer native-ready (its handler dropped it, replaced a watcher, ...),
// the rest of the loop is EVENT{SHIELD_WATCHER_TAIL, code = first index}:
// Python runs the remaining watcher lines (FloatRangeWatcher._update with
// the SDK getters' values) on that same generator.
//
// THE POWER PIECE (Task 4): the plant's tick with its consumer pump (the
// deleted Python PowerSubsystem.Update's, bit for bit), on the plant the
// ship's `_power_subsystem` names. The ship's row ref decides as the
// shield's does: -1 (None) is no call; kRefUnrepresentable, a since-freed
// row or a row whose power_kind is not a plant's is a skip (REF). A live
// plant is native unless something the piece will read is one the mirror
// cannot answer -- then, after the breach (which reads only the plant's
// own row), a skip with nothing else written (power_unready): its
// `_property` unrepresentable or not power_props_ok (PROPERTY); its battery
// watchers not power_watch_ok (BATTERY_WATCH); its `_parent_ship` (whose
// `_powered_consumers` the pump walks) not a live ShipClass row
// (PARENT_SHIP); the interval's `_is_offline` question or condition
// percentage unanswerable (OFFLINE). A consumer not a live row of a known
// power_kind, or a tractor system whose children are not all live tractor
// beams, is passed over by the pump alone (CONSUMER, that consumer only;
// the rest of the plant runs). A script patching PowerSubsystem's, a consumer's or a property's
// methods is not honoured (spec §3 "Mods and patches (Part A)"), and
// neither is a consumer class's own GetPowerWanted: the wanted total is
// the attach-order sum of `_power_wanted` (what the former Python pump's
// guard read for every consumer class the engine has; deleted in phase 6
// Task 8). Then, in order:
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
//           order, by its power_kind (PoweredSubsystem's rules, the
//           tractor's _wants_power, the cloak's; the former Python
//           _update_power methods, deleted in phase 6 Task 8):
//           not wanting power zeroes its four draw fields (the cloak also
//           snapshots the backup battery into _backup_reserve); a free
//           consumer (normal*dt <= 0) is 0/0/1/1; DRAWS_DIRECT_FROM_MAIN
//           steals normal*dt from the main battery (StealPower) and the
//           cloak CLOAK_RESERVE_DRAIN_PER_SECOND*dt from the backup
//           (StealPowerFromReserve), NEITHER counted in _power_dispensed;
//           every other consumer draws normal*dt*slider through the conduits by
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
// The resume after BREACH asks readiness: a plant unready before its
// breach is that reason's skip; one ready then and not now (BREACH's
// handler only reads and queues a deferred entry, so this is defensive) is
// a POST_BREACH_UNREADY skip. A resume at the backup watcher on a plant whose row
// is gone or whose watchers are no longer ready hands that one line to
// Python: EVENT{POWER_TAIL, code 1, a = the backup limit read before the
// main watcher} (the backup watcher's own _update).
//
// THE CLOAK PIECE (Task 5): the cloak's transition (the deleted Python
// CloakingSubsystem.Update's, bit for bit), on the cloak the ship's
// `_cloaking_subsystem`
// names (decided as the shield's ref is; a live row whose power_kind is not
// a cloak's is a skip, REF). Its offline test is IsDisabled() or
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
// first, as BC (and the former Python Update) writes it before the event:
// Python then calls _fire with the
// completion event. Either EVENT is the piece's last line.
//
// THE REPAIR PIECE (Task 5): the bay's repair tick (the deleted Python
// RepairSubsystem.Update's, bit for bit), on the
// bay the ship's `_repair_subsystem` names (decided as the shield's ref is;
// a live row that is not is_repair_bay is a skip, REF). Its gates are the
// bay's own condition > 0 only (not _is_offline, dying or radiation).
//   dt <= 0, an empty queue, the bay's condition <= 0: done. Its
//           `_property` -1 is no teams: done; unrepresentable, stale or not
//           repair_props_ok: a skip (PROPERTY). NumRepairTeams <= 0 or
//           MaxRepairPoints <= 0: done. The bay's condition percentage must
//           be answerable (else a skip, OFFLINE, before any write);
//   THE WALK, over the queue as the mirror holds it now, from the cursor
//           (Python's list iterator: the next index of the list as it is):
//           stop when it is past the end or the worked list holds `teams`;
//           a member whose condition is <= 0 is added to
//           _cannot_complete_notified (written) and is EVENT{REPAIR_CANNOT,
//           code = the bay, sub = the member} the first time, and skipped;
//           any other member leaves the notified set (written) and is
//           worked. The next next() resumes the walk at the next index,
//           re-reading the queue (a handler may have changed it: Review
//           Focus 5). A member with no live row (kRefUnrepresentable or
//           freed) is passed over, counted (a QUEUE_MEMBER skip), and the
//           walk goes on (ruling R8-4); the bay's row gone is a BAY_GONE
//           skip, the rest of the piece with it;
//   none worked: done. Else raw = (points * bayCondPct) * dt (the
//           percentage read again now; unanswerable: an OFFLINE skip),
//           per_item = raw / len(worked); per item gain = per_item / complexity
//           (complexity <= 0 is 1.0), and ShipSubsystem.Repair(gain): gain
//           <= 0 is nothing, else the condition write
//           min(GetMaxCondition(), condition + gain) through damage.h's
//           set_condition (its writes and effect-queue entries in `dmg`,
//           the same as SetCondition's native chain makes; called
//           directly, WITHOUT combat_dmg_set_condition's dmg_guard_state /
//           dmg_fast_patched checks: by Part A a patched damage function or
//           an instance patch on the item is not honoured here);
//           completed when the condition is then >= GetMaxCondition().
//           An item the mirror cannot finish (a set_condition fallback, a
//           max condition it cannot read, its row gone) has ITS writes
//           undone and is EVENT{REPAIR_SET, code = the bay, sub = the item,
//           a = per_item} (ruling R8-3): Python runs that one item's lines
//           -- GetRepairComplexity, the SDK's Repair(per_item / complexity)
//           (its SetCondition), the completion test, reported back with
//           combat_subsys_repair_complete -- and the next next() resumes
//           with the next item. Earlier items keep their native writes;
//   the completions, in order: EVENT{REPAIR_DONE, code = the bay, sub = the
//           item, a = its index}: Python discards it from the queue and
//           fires ET_REPAIR_COMPLETED (the tick's last loop, one item per
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
// pose-table or has_shields push that cannot be represented, ...). From
// then on its row is never read again (`lost_row`; the handle may name a
// reused slot), and its remaining pieces are skipped (THE SKIPS).
//
// A ship whose row was live at begin and is gone at a piece's start has that
// piece skipped (LOST_ROW, ruling R8-2: there is no Python stage to hand it
// to); a ship with no row at begin, NO_ROW. ARTICULATION, whose Python
// (articulation.tick_ship) is kept, is still RUN_PYTHON for both.
//
// Task 3 made the SHIELD piece native (THE SHIELD PIECE), Task 4 the POWER
// piece (THE POWER PIECE), Task 5 the CLOAK and REPAIR pieces (THE CLOAK
// PIECE, THE REPAIR PIECE), Task 6 ARTICULATION's rigless skip; Task 8
// deleted the Python stage: the four pieces are native only.

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
//   POWER_TAIL           plant sub's backup watcher line in Python (code 1;
//                        a = the backup limit)
//   FORCE_DECLOAK        cloak sub's _force_decloak() (THE CLOAK PIECE)
//   CLOAK_DONE           cloak sub's _fire(ET_CLOAK_COMPLETED) (code 1) or
//                        _fire(ET_DECLOAK_COMPLETED) (code 0)
//   REPAIR_CANNOT        bay `code`'s ET_REPAIR_CANNOT_BE_COMPLETED for its
//                        member sub (THE REPAIR PIECE)
//   REPAIR_DONE          bay `code`'s completion of item sub (index a):
//                        queue discard, then ET_REPAIR_COMPLETED
//   REPAIR_SET           worked item sub of bay `code`, repaired in Python
//                        (a = per_item: the item's complexity, the SDK's
//                        Repair and the completion test; THE REPAIR PIECE)
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
    REPAIR_SET = 9,
    kCount
};

const char* subsystem_record_type_name(SubsystemRecordType t);
const char* subsystem_piece_name(SubsystemPiece p);
const char* subsystem_event_name(SubsystemEvent e);

// Why a piece was skipped (THE SKIPS; combat_subsys_kinds() names them).
enum class SubsystemSkip : int32_t {
    NO_ROW = 0,       // the ship had no row at begin
    LOST_ROW,         // the ship's row was freed mid-walk
    REF,              // the piece's subsystem unnamed, freed or of another kind
    SHIELD_UNREADY,   // the generator's lists or watchers not native-ready
    OFFLINE,          // an offline / condition question the mirror can't answer
    PROPERTY,         // the subsystem's property unnamed, freed or not *_ok
    BATTERY_WATCH,    // the plant's battery watchers not native-ready
    PARENT_SHIP,      // the plant's parent ship not a live ShipClass row
    CONSUMER,         // a consumer the pump cannot run (that consumer)
    QUEUE_MEMBER,     // a repair-queue entry unnamed or freed (that member)
    BAY_GONE,         // the repair bay's row freed mid-piece
    POST_BREACH_UNREADY,  // a plant no longer ready after its BREACH
    kCount
};

const char* subsystem_skip_name(SubsystemSkip k);

// One skip: the ship's position, the piece, why, and the subsystem it was
// about (-1 when none).
struct SubsystemSkipRecord {
    int64_t ship_pos = -1;
    SubsystemPiece piece = SubsystemPiece::SHIELD;
    SubsystemSkip why = SubsystemSkip::NO_ROW;
    int64_t sub = -1;
};

// One logged write (THE WRITE LOG): Subsystem row `sub`'s Python attribute
//   CHARGE_ACCUM  sub.__dict__["_charge_accum"] = value
//   RAMP          sub.__dict__["_ramp_fraction"][index] = value
//   FACE          sub.__dict__["_current_shields"][index] = value
//   SHIELD_WATCH  sub.__dict__["_shield_watchers"][index]
//                    .__dict__["_value"] = value
// (in place for the three lists, as the former Python piece wrote them);
// the
// power piece's (THE POWER PIECE):
//   AVAILABLE_POWER .. POWER_WANTED_TOTAL, POWER_WANTED .. BACKUP_RESERVE
//                 sub.__dict__["<the attribute>"] = value (a float)
//   BREACH_FIRED  sub.__dict__["_breach_fired"] = True
//   BATTERY_WATCH sub.__dict__["_main_battery_watcher" (index 0) /
//                    "_backup_battery_watcher" (1)].__dict__["_value"]
//                    = value
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
// generation, re-pushed on every bump) and the ship's row is live.
// Anything else (rigged, never ticked, generation moved, row gone) is
// RUN_PYTHON{ship, ARTICULATION}.

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
    // THE SKIPS of this session, in walk order.
    std::vector<SubsystemSkipRecord> skips;
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
    // Phase 1: whether the plant was ready when its BREACH was returned
    // (unready after it then is POST_BREACH_UNREADY).
    bool power_ready_before = false;
    // The repair piece's sub-piece position (THE REPAIR PIECE): 0 not
    // begun; 1 inside the walk of bay `repair` (a REPAIR_CANNOT stopped
    // it; next: queue index `repair_index`); 4 repairing the worked items
    // (a REPAIR_SET stopped it; next: repair_worked[repair_item], each
    // given `repair_per_item`); 2 reporting completions (next:
    // repair_completed[repair_done]); 3 over. The tick's locals: the teams
    // and points read before the walk, the items worked and completed.
    int32_t repair_phase = 0;
    int64_t repair = -1;
    size_t repair_index = 0;
    int64_t repair_teams = 0;
    double repair_points = 0.0;
    std::vector<int64_t> repair_worked, repair_completed;
    size_t repair_item = 0;
    double repair_per_item = 0.0;
    size_t repair_done = 0;
    std::vector<SubsystemWrite> writes;  // THE WRITE LOG (last next())
    // The repair piece's condition writes (damage.h set_condition): their
    // Python writes and effect-queue entries, cleared by next() on entry
    // and applied by the binding after THE WRITE LOG.
    DamageOut dmg;
};

namespace subsystems {

// One stage over `ship_handles` (roster order; -1: a ship with no row) for
// a tick of `dt`. Reads which handles are live; writes nothing.
SubsystemSession begin(const Mirror& m, std::span<const int64_t> ship_handles,
                       double dt);

// The next record (THE RECORDS). Throws std::logic_error after DONE.
SubsystemRecord next(SubsystemSession& s, Mirror& m);

// REPAIR_SET's answer: Python found item `h` completed (THE REPAIR PIECE);
// it joins the completions in item order. A protocol error (logic_error)
// unless the session is repairing items and `h` is the item just handed.
void repair_complete(SubsystemSession& s, int64_t h);

// THE SKIPS, process-wide: how many of (piece, reason) since the last
// reset_skip_counts().
uint64_t skip_count(SubsystemPiece p, SubsystemSkip why);
void reset_skip_counts();

// THE IDENTICAL WRITES, process-wide: every write the stage logged for the
// applier, and every write it skipped because the mirror (so Python) already
// held the value bit for bit. Zeroed by reset_write_stats().
struct SubsystemWriteStats {
    uint64_t logged;
    uint64_t identical;
};
SubsystemWriteStats write_stats();
void reset_write_stats();

}  // namespace subsystems

}  // namespace dauntless::combat
