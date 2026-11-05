#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/write_log.h"

// K0, the native charging kernel (native weapon state, Task 4).
//
// One tick of host_loop._advance_weapons in the per-tick model
// (passive_weapons.step_every_weapon for every ship): each ship in list
// order, its groups phaser -> pulse -> tractor -> torpedo, each group's
// weapons by index, every weapon stepped -- `UpdateCharge` for phaser banks
// and pulse cannons, `UpdateReload` (+ `ReloadTorpedo`) for torpedo tubes.
// The passive awake list is never consulted (spec 2026-11-02-native-weapon-
// state-design.md §4.3: stepping an at-rest weapon is a no-op, so the
// per-tick model IS the reference). docs/reference/engine/native-combat/
// weapon-state-map.md (WSM) §1.2-1.6 is the Python line by line; §6 D1-D11
// the determinism rules every step keeps (operand order, py_min/py_max in
// Python's argument order, NaN and -0.0 as Python).
//
// THE PURE STEPS. step_energy / step_pulse / step_tube read the mirror and
// return the step's writes, in Python's order, and the effect it ends with
// (K0Step::record: DEPLETE_STOP, RELOADED, WATCH or DONE) -- or a hand-back
// reason, decided BEFORE anything is written (the whole step is computed
// first, so a question the mirror cannot answer half-way through discards
// the step). pulse_watch is the pulse cannon's last line
// (`_charge_watcher._update(GetChargePercentage())`), run on the mirror
// AFTER the step's writes landed.
//
// THE SESSION. begin(ships, dt, now, ...) snapshots each ship's weapon
// handles (the four group refs on the ship's Object row, then each group's
// `_children`, raw: an index keeps its place); next() runs the walk to the
// first thing only Python may do and returns it. Since combat fire events
// (spec 2026-11-02-combat-fire-events §4.3) that is only:
//   RUN_PYTHON    a ship or one weapon K0 does not stand in for (K0Reason):
//                 Python steps it (`step_every_weapon(ship, dt)` for a ship;
//                 `UpdateCharge(dt)` / `UpdateReload(dt)` for a weapon).
//   DONE          the walk is over (its writes ride it); end() closes.
// The walk stops AT a record, so no later weapon is stepped before Python has
// run (plan ruling P1); the next next() reads the LIVE mirror again (a
// handler's writes push to it). DEPLETE_STOP, RELOADED and WATCH are never
// returned (their numbers are kept): what Python ran for them is logged
// writes plus effect-queue entries (THE EFFECT QUEUE, below).
//
// THE EFFECT QUEUE (spec 2026-11-02-combat-fire-events §4.1-4.3). The three
// effects that only report or present are field writes plus a K0Entry, in
// walk order, delivered by Python (engine/appc/effect_queue.py) at the tick
// boundary or the session's end, never mid-walk:
//   a firing bank ran dry   `_charge_level`, `_depleted = True`, then
//       `self.StopFiring()`'s writes (stop_firing.h: a phaser bank's
//       `_firing = False; _beam_on_countdown = 0.0`, a pulse cannon's
//       `_firing = False; _target = None; _target_offset = None`), then, for
//       a phaser bank, LOOP_STOP(bank) (the mixin's loop sound; a pulse
//       cannon has none). A pulse cannon's watcher line follows at once.
//   a tube loaded a round   every slot write, `_reload_timers[oldest] =
//       -1.0`, `_num_ready`, then TORPEDO_RELOAD(tube) (`_broadcast_reload`)
//   a watcher line          the watcher's `_value = GetChargePercentage()`
//       committed as a logged write (Watcher; the mirror's `_watch_value`
//       follows it), then, when the watcher has checks (`_watch_checks >
//       0`), WATCH(weapon, old, new) with old the mirrored `_watch_value`:
//       delivery fires the checks crossed between them (ruling E3: the
//       handler reads the committed value). A watcher the weapon does not
//       own (`_watch_checks` -1, WATCH_ALWAYS) runs its own `_update`: the
//       cannon is handed back whole (reason `watcher`) before any write.
//       A native WATCH names the WEAPON: delivery finds its watcher then
//       (`weapon._charge_watcher`), where Python's WATCH names the watcher
//       object it was produced by -- the two differ only if a handler
//       replaces the cannon's watcher between production and delivery.
// Each entry rides the next record with the writes (K0Record::entries, a
// view of the session's log like `writes`; its `at` places it after the
// writes logged before it); the binding appends them to the combat effect
// queue (combat_effect_queue.h, which this library does not link) once the
// record's writes are applied. A throw drops the call's entries with its
// writes. Python's own producers (a RUN_PYTHON weapon's StopFiring,
// ReloadTorpedo, `_update`) append the same kinds inside the session's
// deferral (native_combat.run_k0), so one emission order holds.
//
// THE WRITE LOG. Every write is made in the mirror and logged (K0Write: the
// step's K0FieldWrite on its handle): `_charge_level`, `_beam_on_countdown`,
// `_cooldown_remaining` (Float), `_depleted`, `_firing` (Flag, a bool),
// `_num_ready` (Int), a stop's `_target = None` (Ref) and `_target_offset =
// None` (Null), slot elements (Slot on `_reload_timers` /
// `_reload_advanced_at`, in place) and the watcher value (Watcher:
// `_charge_watcher._value`; the watcher is not mirrored, its value is, as
// the weapon row's `_watch_value`). Plain data: no string, no
// variant (the host's applier maps the Field to its interned name). Each
// record carries the writes made since the previous record, as a VIEW of
// the session's log: valid until the next next(), whose first act is to
// clear it (the log keeps its storage across calls and sessions, so a
// steady fight logs without allocating). A throw from next() (a protocol
// error, or the weapon check throwing) undoes the writes it made but never
// returned, in the mirror, and restores the session and the counters to
// the state before the call. A slot list's undo is one snapshot per (tube,
// list) per step, taken before its first element write.
//
// HAND-BACKS (RUN_PYTHON, counted by reason):
//   per ship (decided at begin; a = the ship, group = index = -1):
//     no_row             the ship handle is -1 or names no Object row
//     not_weapon_system  not a ShipClass row, or a group ref that is
//                        unrepresentable (-2), gone, or not a weapon system
//     audit / override / any reason the caller passes in `ship_handback`
//   per weapon (decided at its turn, before any write of that weapon; a =
//   the weapon handle, -2 when the mirror cannot name it):
//     stale_row          the handle's row is gone (dropped mid-walk)
//     unknown_kind       a row of no weapon kind (Python dispatches by
//                        isinstance; only it can tell)
//     override           the weapon check answered true
//     slot_heal          a tube whose slot list lengths disagree with
//                        `_max_ready` (`_ensure_slots` rebinds them)
//     power_level        a phaser bank's power level whose discharge entry is
//                        not one of the pushed 0..2 (WSM §1.3 4a)
//     parent             a parent the mirror cannot stand in for: -2, gone,
//                        not a weapon system, or (a firing phaser bank) not
//                        a PhaserSystem
//     unrepresentable    anything else the mirror cannot answer (an
//                        unnamed child, a property or ammo row it cannot
//                        name)
//     watcher            a pulse cannon whose charge watcher it does not own
//                        (`_watch_checks` WATCH_ALWAYS: a subclass with its
//                        own `_update`, another weapon's watcher)

namespace dauntless::combat {

// Record kinds, in combat_k0_kinds() order. Only DONE and RUN_PYTHON are
// returned (THE EFFECT QUEUE); DEPLETE_STOP, RELOADED and WATCH name a pure
// step's effect (K0Step::record) and keep their numbers.
enum class K0Kind : int32_t {
    DONE = 0,
    DEPLETE_STOP,
    RELOADED,
    WATCH,
    RUN_PYTHON,
    // A holding tractor beam's stop (TractorBeam.UpdateCharge: its parent
    // off or starved; fire control native only, M4), never returned: its
    // writes, then the beam's LOOP_STOP.
    HOLD_STOP,
    kCount
};
const char* k0_kind_name(K0Kind k);

// The effect-queue entries K0 appends (THE EFFECT QUEUE): the kinds of the
// same names in native/src/host/combat_effect_queue.h, which the combat
// library does not link; the binding maps them.
enum class K0Effect : int32_t {
    LOOP_STOP = 0,   // (bank)
    TORPEDO_RELOAD,  // (tube)
    WATCH,           // (weapon, old, new): the weapon's charge watcher
    kCount
};
const char* k0_effect_name(K0Effect e);

// One entry, in walk order. `at`: how many of the carrying record's writes
// were logged before it.
struct K0Entry {
    K0Effect kind = K0Effect::LOOP_STOP;
    int64_t a = -1;
    double old_value = 0.0, new_value = 0.0;  // WATCH
    size_t at = 0;
};

enum class K0Reason : int32_t {
    NoRow = 0,
    NotWeaponSystem,
    StaleRow,
    SlotHeal,
    Override,
    Audit,
    PowerLevel,
    Parent,
    Unrepresentable,
    UnknownKind,
    Watcher,
    kCount
};
// The Python counter key: "no_row", "not_weapon_system",
// "stale_row", "slot_heal", "override", "audit", "power_level", "parent",
// "unrepresentable", "unknown_kind", "watcher".
const char* k0_reason_name(K0Reason r);

// One write a pure step makes, before the session logs it. Ref: a handle
// (-1 None; a StopFiring's `_target = None`), applied through the field's
// kind as K1's ref writes are. Null: a plain None (`_target_offset = None`).
// Watcher: the charge watcher's `_value`; in the mirror, `_watch_value`.
struct K0FieldWrite {
    enum class Type : int32_t { Float, Flag, Int, Slot, Watcher, Ref, Null };
    Type type = Type::Float;
    Field field = Field::kCount;  // Slot: the list field; Watcher:
                                  // _watch_value (the mirror's copy)
    int64_t index = -1;           // Slot
    double d = 0.0;               // Float, Slot, Watcher
    int64_t i = 0;                // Flag (0/1), Int, Ref (the handle)
};

struct K0Step {
    // Set: Python steps this weapon; `writes` is empty and `record` DONE.
    std::optional<K0Reason> handback;
    // DONE: no effect but the writes; else the effect the step ends with,
    // which the session queues (THE EFFECT QUEUE): DEPLETE_STOP (the stop's
    // writes are in `writes`; `loop_stop`: a LOOP_STOP follows them),
    // RELOADED (TORPEDO_RELOAD), WATCH (WATCH, watch_old -> watch_new).
    K0Kind record = K0Kind::DONE;
    bool loop_stop = false;
    double watch_old = 0.0, watch_new = 0.0;
    std::vector<K0FieldWrite> writes;
};

// _EnergyWeaponFireMixin.UpdateCharge (WS:957) on a phaser bank (its
// `_discharge_rate_per_second` is PhaserBank's table lookup) or, reached
// through PulseWeapon.UpdateCharge, a pulse cannon (the mixin's
// `_normal_discharge_rate`), or an idle tractor beam (TractorBeam's
// `super().UpdateCharge(dt)`; a firing one hands back `tractor`). `weapon`
// must be a live row of kind 5, 6 or 7.
K0Step step_energy(const Mirror& m, int64_t weapon, double dt);

// PulseWeapon.UpdateCharge (WS:2970) up to, not including, the watcher
// line: the cooldown, then the mixin. `weapon`: a live kind-6 row.
K0Step step_pulse(const Mirror& m, int64_t weapon, double dt);

// The watcher line on the mirror as it is now: the WatcherWrite of
// GetChargePercentage() (WS:2841: 0.0 if `_max_charge <= 0.0` else
// `_charge_level / _max_charge`), and WATCH (from the mirrored
// `_watch_value` to it) when the watcher has checks. A row gone or a
// watcher not owned (`_watch_checks` < 0) hands back (stale_row, watcher).
K0Step pulse_watch(const Mirror& m, int64_t weapon);

// TorpedoTube.UpdateReload (WS:3589) and the ReloadTorpedo it calls
// (WS:3652). `now` is the session's game clock. `tube`: a live kind-8 row.
K0Step step_tube(const Mirror& m, int64_t tube, double now);

// Install (or, with an empty function, remove) the weapon check: (weapon
// handle) -> true when Python must step that weapon (an override of a method
// K0 stands in for, on the class or the instance; Task 5's guard). Called
// once per weapon K0 would step natively, at its turn.
using K0WeaponCheck = std::function<bool(int64_t weapon)>;

// One logged write: a pure step's write, made on `handle`.
struct K0Write {
    int64_t handle = -1;
    K0FieldWrite w;
};

struct K0Record {
    K0Kind kind = K0Kind::DONE;  // RUN_PYTHON or DONE (THE EFFECT QUEUE)
    // RUN_PYTHON: the weapon (-2: the mirror cannot name it), or the ship
    // for a whole-ship one.
    int64_t a = -1;
    // Where in the walk: the position in begin's ship list, the group (0
    // phaser, 1 pulse, 2 tractor, 3 torpedo) and GetWeapon(index) in it as
    // snapshotted at begin. A whole-ship RUN_PYTHON: group = index = -1.
    // DONE: all -1.
    int64_t ship_pos = -1;
    int32_t group = -1;
    int64_t index = -1;
    std::optional<K0Reason> reason;  // RUN_PYTHON
    // The writes since the previous record, in order: a view of the
    // session's log, valid until its next next() (THE WRITE LOG).
    std::span<const K0Write> writes;
    // The queue entries since the previous record, in walk order, viewed
    // the same way (THE EFFECT QUEUE).
    std::span<const K0Entry> entries;
};

class K0Session {
public:
    explicit K0Session(Mirror& m);
    ~K0Session();
    K0Session(const K0Session&) = delete;
    K0Session& operator=(const K0Session&) = delete;

    // _advance_weapons(ships, dt) for one tick. `ships`: Object handles in
    // list order (-1: a ship with no row). `now`: the game clock every tube
    // of this step reads (weapon_subsystems._game_time(), WSM D5).
    // `ship_handback`: empty, or one entry per ship; a set entry hands that
    // ship to Python whole with that reason (the caller's decisions: audit,
    // a ship-level override ...). Throws std::logic_error when a session is
    // open, std::invalid_argument for a `ship_handback` of the wrong length.
    void begin(std::vector<int64_t> ships, double dt, double now,
               std::vector<std::optional<K0Reason>> ship_handback = {});

    // The next record. Throws std::logic_error when no session is open, it
    // already returned DONE, or the previous record is being delivered.
    K0Record next();

    // THE DELIVERY. A record's `writes` view the session's log, which the
    // next next() clears; the caller applying them runs Python (wake hooks,
    // setters) that could call next() again. The caller marks the delivery,
    // and a next() inside it throws std::logic_error with the log and the
    // cursor untouched, so the delivery finishes on the writes it was given.
    void set_delivering(bool on) { delivering_ = on; }
    bool delivering() const { return delivering_; }

    // Close the session, which must have returned DONE.
    void end();
    // Close it whatever its state (the Python loop driving it unwound).
    void abandon();
    bool open() const;

    void set_weapon_check(K0WeaponCheck check) { check_ = std::move(check); }

    struct Counts {
        int64_t steps = 0;  // weapons stepped natively
        std::array<int64_t, static_cast<size_t>(K0Kind::kCount)> records{};
        std::array<int64_t, static_cast<size_t>(K0Reason::kCount)>
            python_reasons{};
        int64_t logged_writes = 0;  // writes returned in records
        // Writes not logged because the mirror already held the value bit
        // for bit (phase 6 A2): only a pulse cannon's watcher line, whose
        // Python value is always a float (FloatRangeWatcher stores
        // float(new_value)) and mirrored on every commit (`_watch_value`).
        // A scalar field is never skipped here: Python may hold an int
        // where the kernel's write would store a float (the applier skips
        // those against Python's own value, combat_write_apply.h).
        int64_t identical_writes = 0;
        // Records not returned because their Python is field writes plus
        // queue entries (THE EFFECT QUEUE): a firing bank drained dry
        // (k0_logged.deplete_stop), a reload (k0_logged.reload), a watcher
        // line with checks (k0_logged.watch).
        int64_t logged_deplete_stop = 0, logged_reload = 0, logged_watch = 0;
        // ... and a holding tractor's stop (k0_logged.hold_stop).
        int64_t logged_hold_stop = 0;
        // The queue entries produced, by K0Effect (k0_entries).
        std::array<int64_t, static_cast<size_t>(K0Effect::kCount)> entries{};
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    // Opaque cursor and log storage (k0_charging.cc).
    struct State;
    struct Log;

private:
    Mirror& m_;
    std::unique_ptr<State> s_;  // null when no session is open
    std::unique_ptr<Log> log_;  // the write log and its undo, reused
    Counts counts_;
    K0WeaponCheck check_;
    bool delivering_ = false;
};

// The process-wide session over mirror().
K0Session& k0_session();

}  // namespace dauntless::combat
