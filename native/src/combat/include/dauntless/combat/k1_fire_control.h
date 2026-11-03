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
// Python may do -- an effect (a tube's or a cannon's Fire effect, a dumb
// fire, a StopFiring the kernel cannot log), a whole system Python must
// run, or a question the mirror cannot answer any more -- and returns it.
// The next next() resumes from the cursor and reads the LIVE mirror again,
// so no decision outlives a Python effect (plan ruling P1).
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
// The WALK CHECK runs at every walk start, before any offset: when it
// answers true the walk starts the old way -- a WALK_START record, answered
// by set_offset (Python's own _live_held_offset) or skip_walk (an
// instance-patched method: Python runs the walk whole). It is the session's
// own (begin_pump / begin_system), else the kernel's (set_walk_check); with
// neither every walk starts natively. The bindings give each session one: a
// lookup in that session's verdict sets -- an instance attribute shadowing
// a method K1 stands in for (system, child, or the ship's
// is_using_target_offset / GetTargetOffsetTG), or a ship class whose offset
// methods are not the stock ShipClass's -- so the kernel's compute makes no
// CPython call (spec 2026-11-02-combat-launch-deferral §4.2). The bindings
// scan the live objects into the sets before each next() of the session
// (top_walk_check), so a verdict is as current as the last Python run
// between records, as when the check ran in here
// (host_bindings.cc, THE K1 WALK CHECK). Sessions nest, so the sets are per
// session. next() itself still runs with the GIL held (workstream I: the
// mirror rows' lifetime, test_native_k1_holds_gil.py).
//
// THE WRITE LOG. No Python bytecode runs inside next(). The writes the Python
// decision path makes (fire timers, the `_depleted` clear, cleared targets,
// the pulse stamps, the cursor and group bookkeeping, the pruned target list)
// are made in the mirror and logged, in the Python's order; every record
// carries the writes made since the previous record as its LAST element, and
// Python applies them before it acts on the record.
//
// Effects that are pure field writes are logged too, with no record (round
// trips, spec 2026-11-01 §4.2-4.3): a Fire on a beam ALREADY firing
// (`_firing = True; _target = target; _target_offset = <the walk's offset
// object>`, _EnergyWeaponFireMixin._fire_effect with was_firing), and a
// StopFiring on a bank that is NOT firing (its class's writes: energy bank
// `_firing = False; _beam_on_countdown = 0.0`; tube `_firing = False`;
// pulse `_firing = False; _target = None; _target_offset = None`). `_firing`
// is a WakeField: the driver's quiet setter still wakes a sleeping bank.
//
// THE EFFECT QUEUE (spec 2026-11-02-combat-fire-events §4.1-4.3). Effects
// that are field writes plus a sound or an event no longer return a record
// either: the writes are logged and the sound or event is a K1Entry, in
// walk order, delivered by Python (engine/appc/effect_queue.py) at the tick
// boundary or at the session's end, never mid-walk:
//   a beam's was-not-firing edge   `_firing = True; _target = target;
//       _target_offset = <the walk's offset>; _beam_on_countdown =
//       BEAM_ON_DELAY_S (pushed from Python); _dwell = 0.0`, then
//       FIRE_SOUND(bank), WEAPON_FIRED(bank, target)  (the mixin's
//       _fire_effect, then PhaserBank._fire_effect's post)
//   a tube's failed aim            WEAPON_FIRE_FAILED(tube)
//   a FIRING bank's StopFiring     its class's writes as above, then, for a
//       PhaserBank, LOOP_STOP(bank)
//   the pump's sys_.StopFiring()   WeaponSystem.StopFiring's `_fire_held =
//       False; _held_target = None; _held_offset = None; _target_list = [];
//       _last_group_fired = -1`, then each child's StopFiring in order. The
//       stop runs before any walk, so the walk check is asked first: true
//       keeps the STOP_SYSTEM record. Its names cover a StopFiring patched
//       on the system's instance (native_combat._K1_SYSTEM_PATCHES) or on
//       a child's (_K1_LEAF_PATCHES); a class override is k1_overridden,
//       which the pre-scan hands back whole before any gate.
// Each entry rides the next record with the writes (K1Record::entries; its
// `at` places it after the writes logged before it); the binding appends
// them to the combat effect queue (combat_effect_queue.h, which this
// library does not link) as it hands the record back. A throw drops the
// entries of the call with its writes. An abandoned session drops nothing
// from the queue (ruling F5): every entry there stands for an effect that
// already happened, and is delivered as usual.
//
// LAUNCHES AT THE BOUNDARY (spec 2026-11-02-combat-launch-deferral §4.1).
// A tube's launch -- a Fire on a tube decided natively, or the dumb fire
// (Weapon.FireDumb: `_dewarp_blocks_fire`, then Fire(None, None)) -- is no
// record either. Its Python, TorpedoTube._fire_effect through
// _spawn_torpedo, is logged in its order:
//     `_target = target; _target_offset = <the walk's offset>` (None, None
//     on the dumb path); `_firing = True`; `_num_ready -= 1`;
//     `_last_fire_time = now`; the system's `_last_system_fire_time = now`;
//     _start_slot_cooldown(now)'s first loaded slot (`_reload_timers[i] =
//     0.0; _reload_advanced_at[i] = now`, slot writes); the ammo type's
//     AddAvailable(-1) for a finite magazine (`_available = max(0,
//     min(_available - 1, _max_torpedoes))`)
// then SPAWN(tube, K1Spawn) -- the fire-time record the spawn needs, every
// value computed here at fire time so a pose that moves later in the step
// (a tractor) cannot move the launch -- WEAPON_FIRED(tube, target),
// AMMO_CONSUMED(tube), and last `_firing = False`. The delivery of SPAWN
// (effect_queue.py) builds the torpedo from the record through the shared
// spawn path (weapon_subsystems._new_projectile / _launch_projectile:
// Create, register, ET_TORPEDO_ENTERED_SET, the launch sound) and posts its
// ET_TORPEDO_FIRED, so the delivered order is BC's: the spawn, ENTERED_SET,
// TORPEDO_FIRED, WEAPON_FIRED, AMMO_CONSUMED. A launch the kernel cannot
// make is the FIRE (FIRE_DUMB) record as before, with no launch write,
// counted by K1LaunchWhy: no ammo type or no module (Unresolved), the
// type's launch not cached (Uncached: read when the type is loaded, so
// only inside THE P6 WINDOW or for a GetLaunchSpeed that raises; Python's
// launch then caches it), a function the launch stands in for patched
// (Patched), anything else the mirror cannot say (Other: slot lists out of
// step with MaxReady, an unnamed set). Whatever the module's Create does, it
// runs at the delivery (rulings L1, L6: an impure script draws there). The
// Python of a handed-back record, running inside the deferral, appends its
// own SPAWN too (effect_queue E4; weapon_subsystems._defer_spawn), so every
// launch in the scope spawns at the boundary in emission order. A dumb fire
// Python would refuse (the ship arriving, CanFire false) is decided
// natively too.
//
// A cannon's launch (Task 3) -- a Fire on a PulseWeapon decided natively --
// is no record either. PulseWeapon._fire_effect inside the deferral is, in
// its order: SPAWN(cannon, K1Spawn) (_defer_spawn: the mount, unit(the
// decision's led world_dir) x the cannon's P6 launch speed + the ship's
// velocity, the target the shot used if alive, the walk's offset and its
// bake, GetDamageRadiusFactor(), GetDamageScale() from the pushed table,
// and the target as fired_at), then `_charge_level = max(0.0,
// _charge_level - _shot_cost())` and `_cooldown_remaining =
// GetCooldownTime()`. No WEAPON_FIRED entry: the delivery scales the
// bolt's damage after register and posts its ET_WEAPON_FIRED once the bolt
// exists (M4), so the delivered order is the spawn, ENTERED_SET,
// WEAPON_FIRED. The SPAWN's module is the cannon's own (the one its P6
// params were read from, held by the bindings per row); while any such
// module is not the one sys.modules holds -- PulseWeapon._fire_decide
// imports its script at every shot -- the bindings set
// K1_PULSE_MODULE_STALE and every cannon launch is a FIRE record
// (Unresolved), as is one with a launch function patched (Patched) or a
// row it cannot read (Other).
//
// WHAT A LAUNCH OBEYS (ruling L8). The instance-level patch scan (THE WALK
// START's verdict sets, native_combat._K1_LEAF_PATCHES) covers the ENTRY
// POINTS only -- Fire, _fire_decide, _fire_effect, StopFiring, CanFire,
// FireDumb, _spawn_torpedo -- "the cheap subset tests and tools patch", as
// K0's ruling W9. The deeper getters a native launch stands in for are
// guarded at CLASS level only (_K1_LEAF_METHODS -> k1_overridden: a class
// or base override hands the system to Python): a tube's
// GetDamageRadiusFactor, GetDirection, GetRight, _emitter_world_position,
// _start_slot_cooldown, _ensure_slots; a cannon's GetDamageScale,
// GetCooldownTime, GetDamageRadiusFactor, _emitter_world_position,
// _shot_cost, _climb_to_ship. One of those patched on an INSTANCE is not
// obeyed by a native launch (roadmap decision 2: runtime patching of
// engine internals is not a supported mod surface). Others it stands in for
// with NO guard, class or instance, read from the mirror instead: the ammo
// type's AddAvailable and GetTorpedoScript, the system's
// GetCurrentAmmoType, the firing ship's GetVelocityTG, GetWorldRotation and
// GetContainingSet, and the target's IsDead; an override of any of those
// is not obeyed by a native launch either. The module-level launch
// functions are the launch check's (K1LaunchWhy::Patched).
//
// THE P6 WINDOW. A cannon's launch speed and module are read when its
// params are pushed (SetProperty, a mission swap's refresh); an ammo
// type's when it is pushed (its creation, SetTorpedoScript, the refresh:
// native_combat.push_ammo_launch, launch deferral Task 5). A
// SetModuleName on a cannon's property after SetProperty is never
// re-pushed, so the cached module and launch params stay the old ones; and
// a projectile-cache reset (_reset_projectile_module_cache) made by Python
// run in the middle of a K1 session leaves a cannon's old ones, and its
// ammo types uncached (each launch handed back, Uncached), until the next
// K1 entry refreshes them. The lead solve's params have the same window.
//
// Records left: FIRE for a launch the kernel cannot make (a tube's or a
// cannon's, counted by K1LaunchWhy), FIRE_DUMB likewise, ASK, RUN_PYTHON,
// a handed-back WALK_START, BANK_STOP / STOP_SYSTEM only for a row gone or
// a stop the walk check hands back, DONE. FIRE_FAILED is never returned.
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
//                   slot that went stale mid-walk), mount_unknown (a posed
//                   target's offset), other otherwise. The pre-scan never
//                   hands a system back for those two: they are counted
//                   here only.
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
// walk start is counted in Counts::logged_walk_start. FIRE_FAILED is no
// longer returned (an entry: THE EFFECT QUEUE); its number is kept.
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

// The effect-queue entries K1 appends (THE EFFECT QUEUE): the kinds of the
// same names in native/src/host/combat_effect_queue.h, which the combat
// library does not link; the binding maps them.
enum class K1Effect : int32_t {
    FIRE_SOUND = 0,      // (bank)
    LOOP_STOP,           // (bank)
    WEAPON_FIRED,        // (bank, target or -1)
    WEAPON_FIRE_FAILED,  // (tube)
    SPAWN,               // (launcher) + K1Entry::spawn
    AMMO_CONSUMED,       // (tube)
    kCount
};
const char* k1_effect_name(K1Effect e);

// A launch's fire-time record (LAUNCHES AT THE BOUNDARY): what
// weapon_subsystems._spawn_projectile reads live, read here when the
// launch is decided. Handles are -1 for None.
struct K1Spawn {
    enum class Kind : int32_t { Tube = 0, Pulse = 1, Dumb = 2 };
    Kind kind = Kind::Tube;
    int64_t ship = -1;    // emitter._climb_to_ship(): the torpedo's source
    int64_t set = -1;     // the ship's containing set (register joins it)
    // The row whose launch module the SPAWN carries (the bindings'
    // k1_launch_modules): a tube's ammo type, a cannon itself.
    int64_t ammo = -1;
    int64_t target = -1;  // _target_ship: the launcher's target, if alive
    Vec3 position{0, 0, 0};  // emitter._emitter_world_position()
    // unit(dir) * launch speed + ship velocity; false when the direction
    // has no length (Python then leaves the torpedo's velocity alone).
    bool has_velocity = false;
    Vec3 velocity{0, 0, 0};
    // SetTargetOffset(the launcher's offset): with a target and a TGPoint3
    // offset, the offset (steered at as it is: no bake, M5).
    bool has_offset = false;
    Vec3 offset{0, 0, 0};
    double drf_override = 0.0;  // the launcher's GetDamageRadiusFactor()
    // A cannon's (a tube's are 1.0 and -1): the power setting's
    // GetDamageScale() at fire time, applied after register as Python
    // does, and the target the shot used, its ET_WEAPON_FIRED's pointer
    // (posted by the delivery, after the bolt exists: M4).
    double damage_scale = 1.0;
    int64_t fired_at = -1;
};

// One entry, in walk order. `at`: how many of the carrying record's writes
// were logged before it (the entry follows them in Python's order).
struct K1Entry {
    K1Effect kind = K1Effect::FIRE_SOUND;
    int64_t a = -1, b = -1;
    size_t at = 0;
    std::optional<K1Spawn> spawn;  // SPAWN
};

// Why a launch went to Python as a FIRE / FIRE_DUMB record (LAUNCHES AT THE
// BOUNDARY), in combat_k1_counts' k1_launch_reasons.
enum class K1LaunchWhy : int32_t {
    Unresolved = 0,  // no ammo type, no script or no module; a cannon's
                     // module not sys.modules' (K1_PULSE_MODULE_STALE)
    Uncached,        // the type's launch is not cached yet
    Patched,         // a function the launch stands in for is patched
                     // (native_combat._K1_LAUNCH_FUNCS: a test's spy, a
                     // tool), K1_LAUNCH_PATCHED, re-checked by the bindings
                     // before every next() like the walk check
    Other,           // the mirror is inconsistent: slot lists out of step
                     // with MaxReady (_ensure_slots would rebuild them), an
                     // unnamed set, a row the plan cannot read
    kCount
};
const char* k1_launch_why_name(K1LaunchWhy w);

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

// One write-log value. monostate is Python None. A SlotWrite is a tube's
// in-place slot write (`_reload_timers[i] = v`, write_log.h): the launch's
// _start_slot_cooldown.
using K1Value = std::variant<std::monostate, bool, int64_t, double,
                             K1WalkOffset, std::vector<int64_t>, SlotWrite>;

struct K1Write {
    int64_t handle = -1;
    std::string_view field;  // the Python attribute name (write_log.h)
    K1Value value;
};

// The decision a FIRE record hands to `bank._fire_effect`.
struct K1Decision {
    enum class Shape : int32_t { Beam, Pulse, Tube } shape = Shape::Beam;
    bool was_firing = false;      // Beam: (was_firing,) -- never returned
                                  // now (edge and sustain are logged)
    Vec3 world_dir{0, 0, 0};      // Pulse: (world_dir_xyz, target_used)
    int64_t target_used = -1;     // Pulse and Tube: the target Fire used
};

struct K1Record {
    K1Kind kind = K1Kind::DONE;
    // WALK_START / STOP_SYSTEM: a = system.
    // RUN_PYTHON: a = system (or -1/-2 when the pump cannot name it),
    //             b = position in the pump's ship list (-1: a system session),
    //             c = getter index 0..3 (Phaser, Pulse, Tractor, Torpedo; -1).
    // BANK_STOP / FIRE_DUMB: a = bank.
    // FIRE: a = bank (a tube or a cannon), b = the target Fire was called
    //       with (-1 = None).
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
    // The queue entries produced since the previous record, in walk order.
    std::vector<K1Entry> entries;
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
// when the walk must start the old way (a WALK_START record). Called inside
// next(): it must not call into Python.
using K1WalkCheck = std::function<bool(int64_t system, int64_t ship)>;

class K1Kernel {
public:
    explicit K1Kernel(Mirror& m);

    // _pump_held_weapons(ships_list, dt). `ships` are Object handles in list
    // order, -1 for a ship with no row (it RUN_PYTHONs every getter). `now` is
    // weapon_subsystems._game_time() (the Utopia game time, 0.0 if it raises;
    // also the occlusion clock), `drift_now` native_combat.now() (the nebula
    // drift clock). `use_memo` is step_memo.active(). `check`: the
    // session's own walk check (THE WALK START), asked instead of the
    // kernel's (set_walk_check) for as long as the session is open; empty:
    // the kernel's.
    void begin_pump(std::vector<int64_t> ships, double dt, double now,
                    bool use_memo, double drift_now, K1WalkCheck check = {});
    // WeaponSystem.StartFiring's immediate update_weapons(dt) on one system.
    void begin_system(int64_t system, double dt, double now, bool use_memo,
                      double drift_now, K1WalkCheck check = {});

    // The next record of the top session. Throws std::logic_error when no
    // session is open, a WALK_START has no offset yet or an ASK no answer.
    K1Record next();

    // Install (or, with an empty function, remove) the kernel's walk check,
    // asked by a session begun without its own.
    void set_walk_check(K1WalkCheck check) { walk_check_ = std::move(check); }
    // The top session's own walk check (begin_pump / begin_system), or
    // nullptr (no session, or one begun without): the bindings re-validate
    // the verdicts behind it before each next().
    const K1WalkCheck* top_walk_check() const;

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
        // why: PartStale, MountUnknown; Other for the rest.
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
        // Records not returned because their Python is field writes plus
        // queue entries (spec 2026-11-02-combat-fire-events §4.3): a beam's
        // was-not-firing edge (k1_logged.beam_edge), a FIRE_FAILED
        // (k1_logged.fire_failed), a firing bank's StopFiring
        // (k1_logged.firing_bank_stop) and the pump's sys_.StopFiring()
        // (k1_logged.system_stop).
        int64_t logged_beam_edge = 0, logged_fire_failed = 0,
                logged_firing_bank_stop = 0, logged_system_stop = 0;
        // The queue entries produced, by K1Effect (k1_entries).
        std::array<int64_t, static_cast<size_t>(K1Effect::kCount)> entries{};
        // Launches made as logged writes and a SPAWN entry (LAUNCHES AT THE
        // BOUNDARY): a tube's Fire, a dumb fire; dumb fires Python would
        // refuse (decided natively, nothing written); and the launches
        // handed back as FIRE / FIRE_DUMB records, by why.
        int64_t logged_tube_launch = 0, logged_dumb_launch = 0,
                logged_dumb_refused = 0;
        // ... and a cannon's Fire (Task 3): its drain, cooldown and SPAWN.
        int64_t logged_pulse_launch = 0;
        std::array<int64_t, static_cast<size_t>(K1LaunchWhy::kCount)>
            launch_why{};
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
