#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
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
// return the step's writes, in Python's order, and its record -- or a
// hand-back reason, decided BEFORE anything is written (the whole step is
// computed first, so a question the mirror cannot answer half-way through
// discards the step). pulse_watch is the pulse cannon's last line
// (`_charge_watcher._update(GetChargePercentage())`), run on the mirror
// AFTER the step's writes landed.
//
// THE SESSION. begin(ships, dt, now, ...) snapshots each ship's weapon
// handles (the four group refs on the ship's Object row, then each group's
// `_children`, raw: an index keeps its place); next() runs the walk to the
// first thing only Python may do and returns it:
//   DEPLETE_STOP  a firing bank ran dry: `_charge_level` and `_depleted =
//                 True` are logged before it; Python runs `bank.StopFiring()`
//                 (the kernel writes no `_firing` / `_beam_on_countdown` for
//                 that stop). A pulse cannon's watcher line still follows on
//                 the next next().
//   RELOADED      a tube loaded a round: every slot write, then
//                 `_reload_timers[oldest] = -1.0`, then `_num_ready`, logged
//                 before it; Python runs `tube._broadcast_reload()`.
//   WATCH         a pulse cannon whose watcher has checks (`_watch_checks >
//                 0`), after its step's writes: Python runs
//                 `weapon._charge_watcher._update(weapon.GetChargePercentage())`.
//                 With no checks the kernel logs the watcher's `_value`
//                 instead (a WatcherWrite) and goes on.
//   RUN_PYTHON    a ship or one weapon K0 does not stand in for (K0Reason):
//                 Python steps it (`step_every_weapon(ship, dt)` for a ship;
//                 `UpdateCharge(dt)` / `UpdateReload(dt)` for a weapon).
//   DONE          the walk is over (its writes ride it); end() closes.
// The walk stops AT a record, so no later weapon is stepped before Python has
// run (plan ruling P1); the next next() reads the LIVE mirror again (a
// handler's writes push to it).
//
// THE WRITE LOG. Every write is made in the mirror and logged (LoggedWrite,
// write_log.h): `_charge_level`, `_beam_on_countdown`, `_cooldown_remaining`
// (float), `_depleted` (bool), `_num_ready` (int), slot elements
// (SlotWrite on `_reload_timers` / `_reload_advanced_at`, in place) and the
// watcher value (WatcherWrite on `_charge_watcher`, logged only: the watcher
// is not mirrored). Each record carries the writes made since the previous
// record. A throw from next() (a protocol error, or the weapon check
// throwing) undoes the writes it made but never returned, in the mirror, and
// restores the session and the counters to the state before the call.
//
// HAND-BACKS (RUN_PYTHON, counted by reason):
//   per ship (decided at begin; a = the ship, group = index = -1):
//     no_row             the ship handle is -1 or names no Object row
//     not_weapon_system  not a ShipClass row, or a group ref that is
//                        unrepresentable (-2), gone, or not a weapon system
//     audit / override / any reason the caller passes in `ship_handback`
//   per weapon (decided at its turn, before any write of that weapon; a =
//   the weapon handle, -2 when the mirror cannot name it):
//     tractor            a tractor beam that is firing (holding); an idle
//                        one (`_firing` false) takes the mixin's energy
//                        step, which is TractorBeam.UpdateCharge's
//                        `super().UpdateCharge(dt)` (ruling W6)
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

namespace dauntless::combat {

enum class K0Kind : int32_t {
    DONE = 0,
    DEPLETE_STOP,
    RELOADED,
    WATCH,
    RUN_PYTHON,
    kCount
};
const char* k0_kind_name(K0Kind k);

enum class K0Reason : int32_t {
    Tractor = 0,
    NoRow,
    NotWeaponSystem,
    StaleRow,
    SlotHeal,
    Override,
    Audit,
    PowerLevel,
    Parent,
    Unrepresentable,
    UnknownKind,
    kCount
};
// The Python counter key: "tractor", "no_row", "not_weapon_system",
// "stale_row", "slot_heal", "override", "audit", "power_level", "parent",
// "unrepresentable", "unknown_kind".
const char* k0_reason_name(K0Reason r);

// One write a pure step makes, before the session logs it.
struct K0FieldWrite {
    enum class Type : int32_t { Float, Flag, Int, Slot, Watcher };
    Type type = Type::Float;
    Field field = Field::kCount;  // Slot: the list field; Watcher: unused
    int64_t index = -1;           // Slot
    double d = 0.0;               // Float, Slot, Watcher
    int64_t i = 0;                // Flag (0/1), Int
};

struct K0Step {
    // Set: Python steps this weapon; `writes` is empty and `record` DONE.
    std::optional<K0Reason> handback;
    // DONE: no record (the walk goes on); else DEPLETE_STOP / RELOADED /
    // WATCH.
    K0Kind record = K0Kind::DONE;
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

// The watcher line on the mirror as it is now: WATCH when the watcher has
// checks (or the row is gone: Python then computes the value itself), else
// the WatcherWrite of GetChargePercentage() (WS:2841: 0.0 if `_max_charge
// <= 0.0` else `_charge_level / _max_charge`).
K0Step pulse_watch(const Mirror& m, int64_t weapon);

// TorpedoTube.UpdateReload (WS:3589) and the ReloadTorpedo it calls
// (WS:3652). `now` is the session's game clock. `tube`: a live kind-8 row.
K0Step step_tube(const Mirror& m, int64_t tube, double now);

// Install (or, with an empty function, remove) the weapon check: (weapon
// handle) -> true when Python must step that weapon (an override of a method
// K0 stands in for, on the class or the instance; Task 5's guard). Called
// once per weapon K0 would step natively, at its turn.
using K0WeaponCheck = std::function<bool(int64_t weapon)>;

struct K0Record {
    K0Kind kind = K0Kind::DONE;
    // DEPLETE_STOP / RELOADED / WATCH: the weapon. RUN_PYTHON: the weapon
    // (-2: the mirror cannot name it), or the ship for a whole-ship one.
    int64_t a = -1;
    // Where in the walk: the position in begin's ship list, the group (0
    // phaser, 1 pulse, 2 tractor, 3 torpedo) and GetWeapon(index) in it as
    // snapshotted at begin. A whole-ship RUN_PYTHON: group = index = -1.
    // DONE: all -1.
    int64_t ship_pos = -1;
    int32_t group = -1;
    int64_t index = -1;
    std::optional<K0Reason> reason;  // RUN_PYTHON
    std::vector<LoggedWrite> writes;
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

    // The next record. Throws std::logic_error when no session is open or it
    // already returned DONE.
    K0Record next();

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
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    // Opaque cursor (k0_charging.cc).
    struct State;

private:
    Mirror& m_;
    std::unique_ptr<State> s_;  // null when no session is open
    Counts counts_;
    K0WeaponCheck check_;
};

// The process-wide session over mirror().
K0Session& k0_session();

}  // namespace dauntless::combat
