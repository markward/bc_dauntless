#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/write_log.h"

// K1, the native fire-control kernel (phase 1b, Task 4).
//
// A resumable walk of host_loop._pump_held_weapons and of
// WeaponSystem.update_weapons / try_fire_weapon (with each kind's CanFire and
// the decision half of its Fire) over the Mirror. docs/reference/engine/
// native-combat/k1-fire-control-map.md (K1M) section 1 is the call graph;
// k1_fire_control.cc names every cursor state after the Python line it stands
// for. The CURRENT Python is the truth (engine/host_loop.py,
// engine/appc/weapon_subsystems.py).
//
// ONE RECORD PER CALL. next() runs the walk until the first thing only
// Python may do -- an effect (StopFiring, a Fire effect, a FIRE_FAILED post,
// a dumb fire), a whole system Python must run, or a question the mirror
// cannot answer any more -- and returns it. The next next() resumes from the
// cursor and reads the LIVE mirror again, so no decision outlives a Python
// effect (plan ruling P1).
//
// THE WALK START (round trips, spec 2026-11-01 §4.1). update_weapons'
// `offset = self._live_held_offset()` is computed HERE, from the mirror
// (k1_live_held_offset), when the walk starts: no record. Python needs the
// offset OBJECT (ruling P5) only once something of the walk reaches it, so
// the walk is tagged: the FIRST record a walk returns carries walk_first,
// walk (the session's walk number) and walk_system, and every logged
// `_target_offset = <the walk's offset>` names its walk (K1WalkOffset).
// The driver fetches the object, and pins the walk, at whichever of the two
// reaches it first (native_combat._K1Walk.materialise). A walk that returns
// no record and logs no such write runs no Python at all; its writes ride
// the next record (or DONE).
//
// The WALK CHECK (set_walk_check) runs at every walk start, before any
// offset: when it answers true the walk starts the old way -- a WALK_START
// record, answered by set_offset (Python's own _live_held_offset) or
// skip_walk (an instance-patched method: Python runs the walk whole). The
// bindings install the check: an instance attribute shadowing a method K1
// stands in for (system, child, or the ship's is_using_target_offset /
// GetTargetOffsetTG), or a ship class whose offset methods are not the
// stock ShipClass's. With no check installed every walk starts natively.
// The kernel itself is plain C++, but the bindings' check is not: no Python
// bytecode runs in it, CPython lookups do (instance dicts, MRO entries, the
// registry's weak references), with the GIL held and no GC-tracked
// allocation -- an instance dict not yet materialised is never built, the
// walk goes back to Python instead (host_bindings.cc, k1_built_dict). So
// next() needs the GIL while the check is installed (workstream I).
//
// THE WRITE LOG. No Python bytecode runs inside next(). The writes the Python
// decision path makes (fire timers, the `_depleted` clear, cleared targets,
// the pulse stamps, the cursor and group bookkeeping, the pruned target list)
// are made in the mirror and logged, in the Python's order; every record
// carries the writes made since the previous record as its LAST element, and
// Python applies them before it acts on the record.
//
// Two effects are pure field writes and are logged too, with no record
// (round trips, spec 2026-11-01 §4.2-4.3): a Fire on a beam ALREADY firing
// (`_firing = True; _target = target; _target_offset = <the walk's offset
// object>`, _EnergyWeaponFireMixin._fire_effect with was_firing), and a
// StopFiring on a bank that is NOT firing (its class's writes: energy bank
// `_firing = False; _beam_on_countdown = 0.0`; tube `_firing = False`;
// pulse `_firing = False; _target = None; _target_offset = None`). The
// was-not-firing beam edge (sound, ET_WEAPON_FIRED) and a firing bank's
// stop (its loop sound) stay FIRE and BANK_STOP records. `_firing` is a
// WakeField: the driver's quiet setter still wakes a sleeping bank.
//
// PINNING (the Python driver's contract; Task 5's run_k1). Python's walk
// holds strong references in its locals (the system, `target`, the retry
// snapshot); the kernel holds only handles. So for as long as a session's
// walk runs, the driver must keep alive the walked system, its children,
// every `_target_list` entry (as of the walk's first record and of each
// later record) and every handle a record names, and map a handle back
// through that pin set (a session handle -> object map) rather than through
// the weak registry. Otherwise a row freed mid-walk (weakref.finalize ->
// unregister) leaves a handle an ASK cannot name. Pinning at the first
// record, not at the walk start, is enough: no Python runs between the two.
//
// A THROW from next() (a protocol error, or the walked system's row gone)
// undoes the field writes it made but never returned, in the mirror, and
// restores the session -- cursor, pending answer -- to the state before the
// call. The mirror's fields then still equal Python, so abandon() is safe.
// Caveat: can_detect's memo and lock-break latch writes (the pump's
// _target_undetectable gate) are not undone. That is safe because the
// pre-scan makes every gate after can_detect answerable, so no throw can
// follow a can_detect in the same call. The guarantee covers the kernel's
// side only: once a record is returned its writes are in the mirror, so
// Python must apply every one of them. native_combat.apply_writes does,
// even when one raises (the walk offset's materialise runs Python's
// _live_held_offset): it applies the rest in order, then re-raises.
//
// PROTOCOL INVARIANT: THE WALKED SYSTEM'S ROW OUTLIVES ITS WALK. An effect's
// event handler may make objects unrepresentable (native_combat._drop: a
// value the mirror cannot encode). A dropped TARGET or BANK row is followed:
// a bank's `_target = None` is logged for Python without a mirror write (no
// row), and every question the row would have answered is ASKed (fire,
// reseed, group_step, is_dumb). A dropped WALKED SYSTEM row is not: the rest
// of update_weapons reads the system's own fields at every step, and Python
// cannot resume update_weapons mid-loop (re-running it would replay the
// effects already made), so next() throws, run_k1 abandons the session and
// re-raises (naming this invariant). Python would have carried on; native
// raises instead. Only a value the mirror cannot encode drops a row (a
// non-number in a number field, a malformed vector); no stock or SDK path
// is known to store one on a weapon system.
//
// SESSIONS form a stack: an effect's event handler may StartFiring, which
// begins (and finishes) a nested one-system session before the outer one
// resumes.
//
// FALLBACK, two stages (plan rulings P2 and H):
//   1. Before the first record or write for a system the kernel pre-scans
//      everything that system's walk can read (prescan() in the .cc). Any row
//      it cannot represent, a leaf of a POSED ship whose part slot is not
//      current (part_stale), and every throw from the pump's gates, makes the
//      system RUN_PYTHON, with no write made for it. A posed firing ship and
//      a posed target are otherwise walked natively: the mounts and a posed
//      target's offset aim (`_RESOLVE`) come from the pushed pose tables and
//      part slots (part_pose.h, weapon_geometry.h).
//   2. After the first record, a native evaluation that cannot answer (state a
//      Python effect or handler changed) becomes an ASK: Python answers the
//      one question on live objects (combat_k1_answer) and the walk goes on.
//      The queries (args -> the Python Task 5 runs -> the answer):
//        can_fire   (bank)              bank.CanFire()                -> bool
//        fire       (sys, bank, target) before = sys._fired_counter(bank);
//                                       r = bank.Fire(target, offset);
//                                       sys._weapon_did_fire(bank, r, before)
//                                                                     -> bool
//                   whenever the Fire's decision cannot be made natively,
//                   counted by why in Counts::fire_ask_why: part_stale (a
//                   slot that went stale mid-walk), mount_unknown / no_mount
//                   / offset_off_mount (a posed target's offset), other
//                   otherwise. The pre-scan never hands a system back for
//                   those three: they are counted here only.
//        retry      (sys, bank)         try_fire_weapon's retry loop over
//                                       list(sys._target_list)        -> bool
//        is_dead    (obj)               hasattr(obj, "IsDead") and
//                                       obj.IsDead()                  -> bool
//        is_member  (bank, group)       bank.IsMemberOfGroup(group)   -> bool
//        is_dumb    (bank)              bank.IsDumbFire() (the bank's row
//                                       was dropped; GetNumTargets() == 0
//                                       already held)                 -> bool
//        group_step (sys, idx, group,   one pass of update_weapons' delta
//                    target)            loop body for GetWeapon(idx): 0
//                                       skipped, 1 fired, 2 failed (Python
//                                       did ClearTarget and FireDumb) -> int
//        reseed     (sys)               sys._reseed_all_fire_timers() -> None
//      `offset` is the walk's own offset object (materialised by the driver
//      before the ASK's Python runs); handles are -1 for None.

namespace dauntless::combat {

// Record kinds, in combat_k1_kinds() order. WALK_START is returned only
// for a walk the walk check hands back (see THE WALK START); every other
// walk start is counted in Counts::logged_walk_start.
enum class K1Kind : int32_t {
    DONE = 0,
    WALK_START,
    STOP_SYSTEM,
    RUN_PYTHON,
    BANK_STOP,
    FIRE,
    FIRE_FAILED,
    FIRE_DUMB,
    ASK,
    kCount
};
const char* k1_kind_name(K1Kind k);

// Why a system went to Python whole (a RUN_PYTHON, or a skip_walk). Counted
// per session type: the pump's and StartFiring's system sessions apart.
enum class K1Why : int32_t {
    SelfManaged = 0,  // a tractor (_pump_self_managed), or not a K1 system
    Overridden,       // the system's or a child's class overrides a K1 method
    InstancePatch,    // Python found an instance-patched method (skip_walk)
    PosedShip,        // retired (posed parts, Task 4): never counted; kept
    PosedTarget,      // for dashboards one release (spec §4.5)
    PartStale,        // a part slot the walk reads is not current
    MountUnknown,     // a posed target's offset mount the mirror can't tell
    NoMount,          // a posed target's offset names no authored mount
                      // and the firing ship's Manual Aim slot does not hold
                      // it (Python's box rule)
    OffsetOffMount,   // a posed target's offset is within 1e-5 of a mount
                      // but not its own point
    StubOrUnplaced,   // no real IsDead, or no valid transform
    PulseShipTarget,  // pulse with no live list entry: ship.GetTarget()
    PulseModule,      // pulse module unresolved or power setting out of range
    AmmoRow,          // a torpedo ammo slot names no live Ammo row
    StaleRow,         // an unnamed (-2) or freed row the walk reads
    UnslottedShip,    // a pump ship with no mirror row (per getter)
    Gate,             // a pump gate the mirror could not answer
    Other,            // child structure, a negative chain group ...
    kCount
};
const char* k1_why_name(K1Why w);

// K1WalkOffset, the marker for "the walk's own offset object" (ruling P5),
// lives in write_log.h (the shared write representation).

// One write-log value. monostate is Python None.
using K1Value = std::variant<std::monostate, bool, int64_t, double,
                             K1WalkOffset, std::vector<int64_t>>;

struct K1Write {
    int64_t handle = -1;
    std::string_view field;  // the Python attribute name (write_log.h)
    K1Value value;
};

// The decision a FIRE record hands to `bank._fire_effect`.
struct K1Decision {
    enum class Shape : int32_t { Beam, Pulse, Tube } shape = Shape::Beam;
    bool was_firing = false;      // Beam: (was_firing,)
    Vec3 world_dir{0, 0, 0};      // Pulse: (world_dir_xyz, target_used)
    int64_t target_used = -1;     // Pulse and Tube: the target Fire used
};

struct K1Record {
    K1Kind kind = K1Kind::DONE;
    // WALK_START / STOP_SYSTEM: a = system.
    // RUN_PYTHON: a = system (or -1/-2 when the pump cannot name it),
    //             b = position in the pump's ship list (-1: a system session),
    //             c = getter index 0..3 (Phaser, Pulse, Tractor, Torpedo; -1).
    // BANK_STOP / FIRE_FAILED / FIRE_DUMB: a = bank.
    // FIRE: a = bank, b = the target Fire was called with (-1 = None).
    int64_t a = -1, b = -1, c = -1;
    K1Decision decision;            // FIRE
    std::string query;              // ASK
    std::vector<int64_t> args;      // ASK
    // The first record a walk returns: its walk number and system (the
    // driver materialises the walk on it). walk_first false: -1, -1.
    bool walk_first = false;
    int64_t walk = -1;
    int64_t walk_system = -1;
    std::vector<K1Write> writes;
};

// update_weapons' `self._live_held_offset()` (WS:1551) on the mirror: the
// ship is a ShipClass row whose is_using_target_offset() holds
// (_use_target_offset and a TGPoint3 _manual_target_offset) -> the manual
// offset (GetTargetOffsetTG's copy); else the system's _held_offset when it
// is a TGPoint3; else nullopt (Python's value is then not a TGPoint3, which
// every reader treats as no offset). `ship` is the system's parent ship
// (-1: none).
std::optional<Vec3> k1_live_held_offset(const Mirror& m, int64_t system,
                                        int64_t ship);

// The walk check (see THE WALK START): (system, its ship or -1) -> true
// when the walk must start the old way (a WALK_START record).
using K1WalkCheck = std::function<bool(int64_t system, int64_t ship)>;

class K1Kernel {
public:
    explicit K1Kernel(Mirror& m);

    // _pump_held_weapons(ships_list, dt). `ships` are Object handles in list
    // order, -1 for a ship with no row (it RUN_PYTHONs every getter). `now` is
    // weapon_subsystems._game_time() (the Utopia game time, 0.0 if it raises;
    // also the occlusion clock), `drift_now` native_combat.now() (the nebula
    // drift clock). `use_memo` is step_memo.active().
    void begin_pump(std::vector<int64_t> ships, double dt, double now,
                    bool use_memo, double drift_now);
    // WeaponSystem.StartFiring's immediate update_weapons(dt) on one system.
    void begin_system(int64_t system, double dt, double now, bool use_memo,
                      double drift_now);

    // The next record of the top session. Throws std::logic_error when no
    // session is open, a WALK_START has no offset yet or an ASK no answer.
    K1Record next();

    // Install (or, with an empty function, remove) the walk check.
    void set_walk_check(K1WalkCheck check) { walk_check_ = std::move(check); }

    // The reply to WALK_START: the walk's `_live_held_offset()` as xyz when it
    // is a TGPoint3, nullopt otherwise.
    void set_offset(std::optional<Vec3> xyz);
    // The reply to an ASK: an int (bools as 0/1), or nullopt for None.
    void answer(std::optional<int64_t> v);
    // The other reply to WALK_START: Python found the walked system or a
    // child instance-patched (Fire, CanFire ...) and ran the system's
    // update_weapons itself. The kernel writes nothing more for it and goes
    // on to the next system (counted as K1Why::InstancePatch). Throws
    // std::logic_error unless the top session awaits a WALK_START reply.
    void skip_walk();

    // Pops the top session, which must have returned DONE.
    void end();
    // Pops the top session whatever its state (an exception unwound the
    // Python loop driving it).
    void abandon();
    size_t depth() const { return sessions_.size(); }
    // The top session has an ASK answered but not yet consumed by next().
    bool answer_pending() const;
    void clear();

    struct Counts {
        int64_t records = 0, python_systems = 0, asks = 0;
        // python_systems by K1Why: pump sessions, StartFiring sessions.
        std::array<int64_t, static_cast<size_t>(K1Why::kCount)> pump_why{},
            system_why{};
        // ASK fire hand-backs (a Fire decision the mirror could not make) by
        // why: PartStale, MountUnknown, NoMount, OffsetOffMount; Other for
        // the rest.
        std::array<int64_t, static_cast<size_t>(K1Why::kCount)> fire_ask_why{};
        // Posed parts walked natively: systems whose ship is posed, and Fire
        // decisions aimed at a posed target's offset.
        int64_t posed_walks = 0, posed_target_aims = 0;
        // Walks started with no WALK_START record (k1_logged.walk_start).
        int64_t logged_walk_start = 0;
        // Records not returned because their Python is pure field writes,
        // logged instead (round trips Task 2): a Fire on a beam already
        // firing (k1_logged.beam_sustain) and a StopFiring on a bank that
        // is not firing (k1_logged.idle_bank_stop).
        int64_t logged_beam_sustain = 0, logged_idle_bank_stop = 0;
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    // Opaque per-session cursor (k1_fire_control.cc).
    struct Session;

private:
    Mirror& m_;
    std::vector<std::unique_ptr<Session>> sessions_;
    Counts counts_;
    K1WalkCheck walk_check_;

public:
    ~K1Kernel();
    K1Kernel(const K1Kernel&) = delete;
    K1Kernel& operator=(const K1Kernel&) = delete;
};

// The process-wide kernel over mirror().
K1Kernel& k1_kernel();

}  // namespace dauntless::combat
