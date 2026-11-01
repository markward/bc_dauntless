#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <variant>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/mirror.h"

// K2, the native phaser beam kernel (native combat phase 2, Task 4).
//
// A resumable walk of host_loop._advance_combat_step's `cb.phasers` loop
// (engine/host_loop.py, the `with frame_profiler.scope("cb.phasers")` block)
// over the Mirror. docs/reference/engine/native-combat/k2-beams-map.md (K2M)
// section 1.1 is the loop; k2_beams.cc names every cursor state after the
// Python line it stands for. The CURRENT Python is the truth. Every float is
// made by beam_geometry / beam_trace / weapon_geometry / fire_gates /
// sensor_detect, the Python-exact ports of phases 1a, 1b and Tasks 2-3.
//
// ONE RECORD PER CALL (ruling P1). next() runs the walk until the first thing
// only Python may do -- an effect (a StopFiring, a beam contact), a whole ship
// Python must run, or a question the mirror cannot answer -- and returns it.
// The next next() resumes from the cursor and reads the LIVE mirror again, so
// no decision outlives a Python effect. There is no epoch check.
//
// THE WRITE LOG (rulings A and P7). The only write the decision path makes is
// the bank's `_dwell` (take_dwell / accumulate_dwell). The kernel makes it in
// the mirror and logs it, in the Python's order; every record carries the
// writes made since the previous record as its LAST element, and Python
// applies them (without pushing) before it acts on the record. An idle
// bank's take_dwell writing +0.0 over a +0.0 dwell is ELIDED (a plain float
// attribute: no side effect to preserve). `_beam_on_countdown` is only read.
//
// RECORDS (K2Kind, in combat_k2_kinds() order). The Python layouts, as the
// binding builds them (handles are mirror handles, -1 = None; xyz = a
// 3-tuple of floats):
//   0 DONE        (DONE, writes)
//   1 SYSTEM_STOP (SYSTEM_STOP, system, writes)       -> sys_.StopFiring()
//   2 BANK_STOP   (BANK_STOP, bank, writes)           -> bank.StopFiring()
//   3 CONTACT     (CONTACT, bank, target, ship, system, emitter_xyz,
//                  target_pos_xyz, dist, aim_unit_xyz | None, impact_xyz,
//                  normal_xyz | None, tier, bubble_xyz | None,
//                  shields_block (True / False / None), flush_dwell, writes)
//        tier is "mesh", "sphere", "fallback" (the impact point IS
//        target_pos) or "origin" (the impact point IS emitter_pos), so Python
//        rebuilds Python's object identity. shields_block is None when the
//        loop did not evaluate it (aim_unit None): beam_contact then
//        evaluates its own. Python: hit_feedback.beam_contact(...) if
//        flush_dwell <= 0.0, else combat.apply_hit(...) if the damage is > 0
//        (the damage arithmetic, PHASER_INTENSITY_SCALE[level],
//        weapon_splash_radius and damage_hull stay Python).
//   4 RUN_PYTHON  (RUN_PYTHON, ship, ship_pos, writes)
//        -> the loop body for ships_list[ship_pos], in Python, whole.
//   5 ASK         (ASK, query, *args, writes) -> reply combat_k2_answer.
//
// FALLBACK, two stages (ruling H):
//   1. Before the FIRST RECORD for a ship the kernel pre-scans it (prescan()
//      in the .cc): the ship row (a ShipClass, placed, its set nameable; on
//      a posed ship every bank's part slot current, and a lock's slot on its
//      own posed ship current -- else part_stale), the phaser system row (a
//      phaser system, no class override), every child (a live, unoverridden
//      PhaserBank of this ship) and every child's `_target` (None or a
//      placed Object with a nameable set). The same checks run again for
//      each bank before ITS first record (a bank_step past the ship's). Anything else -- and any throw before the ship's first record,
//      its undelivered writes rolled back -- is RUN_PYTHON, counted by why.
//   2. After it, a native evaluation that cannot answer becomes an ASK:
//      Python answers the one question on live objects and the walk goes on.
//      The queries (args -> the EXACT Python Task 5 must run -> the answer):
//        is_dead      (target)         bool(hasattr(target, "IsDead") and
//                                      target.IsDead())             -> bool
//            when target has no real IsDead (has_real_is_dead == 0).
//        can_detect   (ship, target)   native_combat._counts["fallbacks"]
//                                      += 1; sensor_detection.
//                                      _py_can_detect(ship, target) -> bool
//            when the native can_detect raised (exactly the Python's own
//            fallback after its native call raised ValueError).
//        aim_point    (ship, target)   p, sub = host_loop._phaser_aim_point(
//                                      ship, target)
//                                      -> ((p.x, p.y, p.z), sub is not None)
//            when the lock's row is unnameable, or a Manual Aim pick on a
//            posed target that the ship's Manual Aim slot does not hold
//            current (Task 4b; Python's box rule). A lock on a posed ship
//            is the kernel's (its mount through the pushed part slot; a
//            stale slot sends the ship to Python first, part_stale). With a
//            lock the arc aim reuses p:
//            Python calls the same pure GetWorldLocation twice.
//        shields_block (target)        bool(combat.shields_block(target))
//                                                                    -> bool
//            when target is not a ShipClass with a real GetShields, or its
//            shield / cloak ref is unnameable.
//        bubble       (target, emitter_xyz, aim_unit_xyz, max_dist)
//                                      p = combat.shield_bubble_entry(
//                                      target, TGPoint3(*emitter_xyz),
//                                      TGPoint3(*aim_unit_xyz), max_dist)
//                                      -> (p.x, p.y, p.z) or None
//            when target is not a ShipClass, or the native bubble raised (a
//            zero semi-axis: the Python raises ZeroDivisionError).
//        resolve_hit  (target, emitter_xyz, dir_xyz, max_dist, fallback_xyz)
//                                      E = TGPoint3(*emitter_xyz);
//                                      F = TGPoint3(*fallback_xyz);
//                                      p, n = combat._resolve_hit_point(
//                                        ship_instances=ship_instances,
//                                        ship=target, ray_origin=E,
//                                        ray_direction=TGPoint3(*dir_xyz),
//                                        max_dist=max_dist,
//                                        fallback_point=F)
//                                      -> ((p.x, p.y, p.z), (n.x, n.y, n.z)
//                                         or None, tier): tier "origin" if
//                                         p is E, "fallback" if p is F,
//                                         "mesh" if n is not None, else
//                                         "sphere"
//            when the target's set has no entry in the context's view-offset
//            table (a direction and an instance being present).
//        bank_step    (ship, system, i) the loop body for
//                                      `bank = sys_.GetWeapon(i)` (from
//                                      `if bank is None: continue` to the
//                                      end of the iteration), in Python
//                                      -> None
//            when, after the ship's first record, bank i can no longer be
//            walked natively (an effect's handler dropped or swapped a row:
//            the system, the ship, the bank or its target). Nothing has been
//            delivered for bank i (its undelivered writes are rolled back).
//      An int64 handle is -1 for None.
//
// PROTOCOL INVARIANT. Once a record for a BANK has been delivered (an ASK or
// the arc-fail BANK_STOP), the bank cannot be handed to Python (part of its
// body has run). The only Python run between that record and the bank's
// CONTACT is an ASK answer or StopFiring, neither of which drops a mirror
// row, and the pre-scan made every remaining read nameable; if one still
// fails, next() throws std::logic_error (the session is restored, see below)
// and run_k2 must abandon and re-raise naming this invariant. The part slots
// the bank's GEOMETRY reads were checked current at its start; the ASKs
// before GEOMETRY (is_dead, can_detect, aim_point) never bump the part-map
// generation (no model or box is learned without a render instance id,
// which none of them passes), so a slot cannot go stale in between.
//
// PINNING (the Python driver's contract; Task 5's run_k2). Python's loop
// holds strong references in its locals (`ship`, `sys_`, `bank`, `target`);
// the kernel holds only handles. The driver pins LAZILY: the step's ship list
// keeps the ships alive, and before any NON-PURE Python runs (Python that can
// drop the last other reference to an object: a StopFiring, a contact's
// effects, a whole ship's step) the record that triggers it names -- and the
// driver resolves and pins (_K2Walk.obj, pin_bank) -- the objects Python's
// locals would hold at that point:
//   - SYSTEM_STOP: the system, before its StopFiring;
//   - BANK_STOP: the bank, its `_target` and its system (pin_bank), before
//     the bank's StopFiring;
//   - CONTACT: the bank, the target, the ship and the system, before the
//     contact's effects;
//   - the bank_step ASK: the ship and the system, before _phaser_step_bank;
//   - RUN_PYTHON names its ship by list index (the list holds it).
// The other ASKs (is_dead, can_detect, aim_point, shields_block, bubble,
// resolve_hit) run only pure Python: nothing they run can free a row, so they
// pin only what they name. A handle is mapped back through that pin set, then
// the weak registry. A NEW record kind (or ASK) that runs non-pure Python
// must name every object Python's locals would hold there, or a row freed
// mid-walk (weakref.finalize -> unregister) leaves a handle a later record
// or ASK cannot name.
//
// A THROW from next() (a protocol error, or the invariant above) undoes the
// field writes it made but never returned, in the mirror, and restores the
// session -- cursor, pending answer -- to the state before the call. The
// mirror's `_dwell` fields then still equal Python, so abandon() is safe.
// Caveat: can_detect's memo and lock-break latch writes and the mount memo
// are not undone: they are the writes Python's own calls make at the same
// point (sensor_detect.h, weapon_geometry.h). The guarantee covers the
// kernel's side only: once a record is returned its writes are in the
// mirror, so Python applying them must not fail part-way (a plain float on
// a pinned bank).
//
// THE CONTEXT (K2Context): per-step Python state that is not mirrored. Set
// whole at begin and partly by set_context (combat_k2_set_ctx), which the
// driver re-sends after an effect whenever the player, the cheat flag, the
// viewing set or `ship_instances.version` changed. The one exception is
// `iids`: it outlives the session, and the driver sends it (at begin or
// set_context) only when its key -- the map, its version, the drop epoch --
// changed since it last did (a begin without it keeps the table).
//
// WHAT THE DRIVER CHECKS BEFORE begin (engine/appc/native_combat.py,
// k2_phasers; Task 5). The kernel computes, from the mirror, what these
// Python functions and methods would answer, so a replaced one must send the
// step back to Python. The driver runs the WHOLE `cb.phasers` step in Python
// (no session) when:
//   - a K2 session is already open;
//   - `ship_instances` is neither None nor a TrackedInstances (a test's
//     plain dict);
//   - a MODULE FUNCTION is not the object snapshotted when host_loop defined
//     the loop (native_combat._K2_FUNCTIONS):
//       host_io.ray_trace_mesh;
//       combat._resolve_hit_point, ray_sphere_entry, shields_block,
//         shield_bubble_entry, cloak_shields_suspended, _hull_box_for,
//         _body_frame_delta;
//       collisions.world_radius;
//       host_loop._phaser_aim_point, _phaser_step_ship, _phaser_step_bank,
//         and its own imports can_detect, _same_set, _emitter_in_arc,
//         _resolve_bank_aim_world, _is_offline;
//       frames.view_offset, shifted, containing_set;
//       subsystems.subsystem_world_position, target_offset_world,
//         _is_offline;
//       weapon_subsystems._resolve_bank_aim_world, _emitter_in_arc,
//         _same_set;
//       sensor_detection.can_detect;
//     or host_io._h is neither None nor the bindings it snapshotted;
//   - a STOCK CLASS resolves one of its role's names to anything but its
//     snapshot (native_combat._K2_ROLES; every SUBSYSTEM role -- the
//     first five -- also watches the subsystem names GetWorldLocation,
//     GetPosition, _climb_to_ship; the override guard test parses this
//     list):
//       PhaserBank: IsFiring, IsBeamOn, take_dwell, accumulate_dwell,
//         _strip_emit_position, _emitter_world_position, GetLength,
//         GetDirection, GetUp, GetArcWidthAngles, GetArcHeightAngles,
//         IsDisabled, IsDestroyed;
//       PhaserSystem: GetNumWeapons, GetWeapon, GetNumChildSubsystems,
//         GetChildSubsystem, IsOn, IsDisabled, IsDestroyed;
//       ShieldSubsystem: HasShields, IsOn, IsDisabled, IsDestroyed;
//       CloakingSubsystem: IsCloaking, IsDecloaking;
//       ShipSubsystem: the subsystem names;
//       ShipClass: IsDead, GetWorldLocation, GetWorldRotation,
//         GetContainingSet, GetScale, GetRadius, GetShields,
//         GetPhaserSystem, GetTargetSubsystem, is_using_target_offset,
//         GetTargetOffsetTG, GetCloakingSubsystem;
//       ObjectClass: IsDead, GetWorldLocation, GetWorldRotation,
//         GetContainingSet, GetScale, GetRadius, GetShields;
//   - any class with a row resolves a name of its role to a method defined
//     outside the engine package (a mod's subclass, a test's patch) or to
//     anything other than what it resolved to when the driver first saw it
//     -- unless it is a bank or phaser system class overriding only its own
//     (non-subsystem) names, which sends only its ship to Python;
//   - the native audit is on (DAUNTLESS_NATIVE_AUDIT=1): the kernel's own
//     can_detect would bypass sensor_detection's per-call audit.
// It lists a ship in `python_ships` (RUN_PYTHON "overridden") when its bank
// or system class overrides one of its own names, or it has an INSTANCE
// attribute shadowing a method the loop calls on it by name:
//   the ship: GetPhaserSystem, GetTargetSubsystem, is_using_target_offset,
//     GetTargetOffsetTG, GetShields, IsDead, GetWorldLocation,
//     GetWorldRotation;
//   its phaser system: GetNumWeapons, GetWeapon, IsOn, IsDisabled,
//     IsDestroyed;
//   a bank: IsFiring, IsBeamOn, take_dwell, accumulate_dwell,
//     _strip_emit_position, _emitter_world_position, GetLength.
// It also lists the ship when the ship's own class, or the class of a bank's
// `_target`, is one K2 never saw (no object of that class ever registered or
// was reclassified), and runs the whole step in Python when that class is
// flagged "whole" (native_combat._k2_unseen). The check is PER CLASS, not per
// row: it catches a `__class__` swapped in under a row only while no object
// of the new class has been seen. Once one has, a row whose object's class
// was swapped to that class WITHOUT reclassify keeps its old class flags,
// undetected. Code that swaps a class under a row must call reclassify (the
// rocks do: engine/rocks/rock.py).
// An instance attribute on a TARGET is not looked for. No ENGINE class may
// override a stood-in name unless the kernel ports it: the static guard
// tests/unit/test_native_k2_override_guard.py lists the ported ones.

namespace dauntless::combat {

// Record kinds, in combat_k2_kinds() order.
enum class K2Kind : int32_t {
    DONE = 0,
    SYSTEM_STOP,
    BANK_STOP,
    CONTACT,
    RUN_PYTHON,
    ASK,
    kCount
};
const char* k2_kind_name(K2Kind k);

// Why a ship went to Python whole (RUN_PYTHON).
enum class K2Why : int32_t {
    UnslottedShip = 0,  // the ship has no mirror row
    NotShipClass,       // not a ShipClass (GetPhaserSystem is a stub)
    Overridden,         // the system or a bank overrides a K1 method, or the
                        // driver listed the ship (context python_ships)
    PosedShip,          // retired (posed parts, Task 4): never counted;
                        // kept for dashboards one release (spec §4.5)
    PartStale,          // a part slot the walk reads is not current (a
                        // posed ship's bank mount, or its lock's mount)
    StaleRow,           // an unnamed (-2) or freed row the walk reads
    StubOrUnplaced,     // an invalid transform
    Gate,               // the system gate could not be answered
    Other,              // structure: not a phaser system / bank, a bank of
                        // another ship, an unexpected throw
    kCount
};
const char* k2_why_name(K2Why w);

// ASK queries; names as in the header comment above.
enum class K2Query : int32_t {
    is_dead = 0,
    can_detect,
    aim_point,
    shields_block,
    bubble,
    resolve_hit,
    bank_step,
    kCount
};
const char* k2_query_name(K2Query q);

// One write-log entry: `handle.field = value` (field is always "_dwell").
struct K2Write {
    int64_t handle = -1;
    std::string field;
    double value = 0.0;
};

// An ASK argument: None, a handle / index, a float, or a point.
using K2Arg = std::variant<std::monostate, int64_t, double, Vec3>;

struct K2Contact {
    int64_t bank = -1, target = -1, ship = -1, system = -1;
    Vec3 emitter{0, 0, 0}, target_pos{0, 0, 0};
    double dist = 0.0;
    std::optional<Vec3> aim_unit;
    ResolvedHit hit;
    std::optional<Vec3> bubble;
    std::optional<bool> shields_block;  // nullopt: not evaluated (no aim_unit)
    double flush_dwell = 0.0;
};

struct K2Record {
    K2Kind kind = K2Kind::DONE;
    // SYSTEM_STOP: a = system. BANK_STOP: a = bank.
    // RUN_PYTHON: a = ship handle (-1 when it has no row), b = ship_pos.
    int64_t a = -1, b = -1;
    K2Contact contact;           // CONTACT
    K2Query query = K2Query::kCount;  // ASK
    std::vector<K2Arg> args;     // ASK
    std::vector<K2Write> writes;
};

// The reply to an ASK. Which fields are read depends on the query:
//   is_dead / can_detect / shields_block: flag;
//   aim_point: point, flag (= the locked subsystem was not None);
//   bubble: none (Python None) or point;
//   resolve_hit: point, normal, tier;
//   bank_step: nothing.
struct K2Answer {
    bool flag = false;
    bool none = false;
    Vec3 point{0, 0, 0};
    std::optional<Vec3> normal;
    ResolvedHit::Tier tier = ResolvedHit::Tier::Fallback;
};

struct K2Context {
    // dev_combat_cheats.disable_npc_shields_active()
    bool npc_shields_off = false;
    // App.Game_GetCurrentGame().GetPlayer()'s Object handle (-1 None; any
    // other value never equals a target, as an unregistered player).
    int64_t player = -1;
    // frames.view_offset(set) by Set handle: nullopt = None (no shift). A
    // target whose set has no entry makes the trace ASK resolve_hit.
    std::unordered_map<int64_t, std::optional<Vec3>> view_offsets;
    // ship_instances by target Object handle. Absent (or None) is "no
    // instance": the fallback point. `bad` is a value that is not an
    // InstanceId (pybind would raise inside _resolve_hit_point's try): the
    // sphere tier, as a stale id.
    struct Iid {
        bool bad = false;
        InstanceId id{};
    };
    std::unordered_map<int64_t, Iid> iids;
    // The trace: installed_trace_hooks(), or empty when host_io._h is None.
    TraceHooks hooks;
    // Ships the driver hands to Python whole (a class override it found).
    std::unordered_set<int64_t> python_ships;
};

class K2Kernel {
public:
    explicit K2Kernel(Mirror& m);

    // The `cb.phasers` loop over `ships` (Object handles in list order, -1
    // for a ship with no row). `now` is the occlusion clock and `drift_now`
    // the nebula drift clock, exactly as K1 passes them to can_detect
    // (weapon_subsystems._game_time() / native_combat.now()); `use_memo` is
    // step_memo.active(). Throws std::logic_error if a session is open.
    // `keep_iids`: ctx.iids is replaced by the previous context's table (the
    // driver sends the table only when its key changed since it last did).
    void begin(std::vector<int64_t> ships, double dt, double now,
               bool use_memo, double drift_now, K2Context ctx,
               bool keep_iids = false);
    // Replace the context (combat_k2_set_ctx re-sends the changed parts).
    void set_context(K2Context ctx);
    const K2Context& context() const { return ctx_; }

    // The next record. Throws std::logic_error when no session is open, an
    // ASK has no answer, or the protocol invariant breaks.
    K2Record next();
    // The query of the ASK awaiting its answer (kCount: none).
    K2Query awaiting() const;
    // The reply to an ASK.
    void answer(const K2Answer& a);

    // Ends the session, which must have returned DONE.
    void end();
    // Ends the session whatever its state (an exception unwound Python).
    void abandon();
    bool open() const { return static_cast<bool>(session_); }
    void clear();

    struct Counts {
        int64_t records = 0, python_ships = 0, asks = 0;
        std::array<int64_t, static_cast<size_t>(K2Why::kCount)> why{};
        std::array<int64_t, static_cast<size_t>(K2Query::kCount)> queries{};
        // Posed parts walked natively: banks whose strip centre was posed
        // (their ship is posed), and aim points at a lock on a posed ship.
        int64_t posed_banks = 0, posed_lock_aims = 0;
        // Manual Aim picks on a posed target answered natively (Task 4b).
        int64_t posed_manual_aims = 0;
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    struct Session;  // the cursor (k2_beams.cc)

private:
    Mirror& m_;
    K2Context ctx_;
    std::unique_ptr<Session> session_;
    Counts counts_;

public:
    ~K2Kernel();
    K2Kernel(const K2Kernel&) = delete;
    K2Kernel& operator=(const K2Kernel&) = delete;
};

// The process-wide kernel over mirror().
K2Kernel& k2_kernel();

}  // namespace dauntless::combat
