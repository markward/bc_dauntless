#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/mirror.h"

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
// a dumb fire), a whole system Python must run, the walk's offset, or a
// question the mirror cannot answer any more -- and returns it. The next
// next() resumes from the cursor and reads the LIVE mirror again, so no
// decision outlives a Python effect (plan ruling P1).
//
// THE WRITE LOG. The kernel never touches Python. The writes the Python
// decision path makes (fire timers, the `_depleted` clear, cleared targets,
// the pulse stamps, the cursor and group bookkeeping, the pruned target list)
// are made in the mirror and logged, in the Python's order; every record
// carries the writes made since the previous record as its LAST element, and
// Python applies them before it acts on the record.
//
// PINNING (the Python driver's contract; Task 5's run_k1). Python's walk
// holds strong references in its locals (the system, `target`, the retry
// snapshot); the kernel holds only handles. So for as long as a session's
// walk runs, the driver must keep alive the walked system, its children,
// every `_target_list` entry (as of WALK_START and of each later record) and
// every handle a record names, and map a handle back through that pin set
// (a session handle -> object map) rather than through the weak registry.
// Otherwise a row freed mid-walk (weakref.finalize -> unregister) leaves a
// handle an ASK cannot name.
//
// A THROW from next() (a protocol error, or the walked system's row gone)
// changes nothing: the writes it made but never returned are undone in the
// mirror, and the session -- cursor, pending answer -- is restored to the
// state before the call. The mirror then still equals Python, so abandon()
// is safe.
//
// SESSIONS form a stack: an effect's event handler may StartFiring, which
// begins (and finishes) a nested one-system session before the outer one
// resumes.
//
// FALLBACK, two stages (plan rulings P2 and H):
//   1. Before the first record or write for a system the kernel pre-scans
//      everything that system's walk can read (prescan() in the .cc). Any row
//      it cannot represent, and every throw from the pump's gates, makes the
//      system RUN_PYTHON, with no write made for it.
//   2. After the first record, a native evaluation that cannot answer (state a
//      Python effect or handler changed) becomes an ASK: Python answers the
//      one question on live objects (combat_k1_answer) and the walk goes on.
//      The queries (args -> the Python Task 5 runs -> the answer):
//        can_fire   (bank)              bank.CanFire()                -> bool
//        fire       (sys, bank, target) before = sys._fired_counter(bank);
//                                       r = bank.Fire(target, offset);
//                                       sys._weapon_did_fire(bank, r, before)
//                                                                     -> bool
//        retry      (sys, bank)         try_fire_weapon's retry loop over
//                                       list(sys._target_list)        -> bool
//        is_dead    (obj)               hasattr(obj, "IsDead") and
//                                       obj.IsDead()                  -> bool
//        is_member  (bank, group)       bank.IsMemberOfGroup(group)   -> bool
//        group_step (sys, idx, group,   one pass of update_weapons' delta
//                    target)            loop body for GetWeapon(idx): 0
//                                       skipped, 1 fired, 2 failed (Python
//                                       did ClearTarget and FireDumb) -> int
//        reseed     (sys)               sys._reseed_all_fire_timers() -> None
//      `offset` is the walk's own offset object (from WALK_START); handles
//      are -1 for None.

namespace dauntless::combat {

// Record kinds, in combat_k1_kinds() order.
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

// One write-log value. monostate is Python None; a string is the marker
// "walk_offset" (the walk's own offset object, ruling P5).
using K1Value = std::variant<std::monostate, bool, int64_t, double,
                             std::string, std::vector<int64_t>>;

struct K1Write {
    int64_t handle = -1;
    std::string field;  // the Python attribute name
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
    std::vector<K1Write> writes;
};

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

    // The reply to WALK_START: the walk's `_live_held_offset()` as xyz when it
    // is a TGPoint3, nullopt otherwise.
    void set_offset(std::optional<Vec3> xyz);
    // The reply to an ASK: an int (bools as 0/1), or nullopt for None.
    void answer(std::optional<int64_t> v);

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
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    // Opaque per-session cursor (k1_fire_control.cc).
    struct Session;

private:
    Mirror& m_;
    std::vector<std::unique_ptr<Session>> sessions_;
    Counts counts_;

public:
    ~K1Kernel();
    K1Kernel(const K1Kernel&) = delete;
    K1Kernel& operator=(const K1Kernel&) = delete;
};

// The process-wide kernel over mirror().
K1Kernel& k1_kernel();

}  // namespace dauntless::combat
