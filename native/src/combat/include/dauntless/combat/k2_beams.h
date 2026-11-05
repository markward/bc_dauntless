#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/damage.h"
#include "dauntless/combat/k1_fire_control.h"
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
// only Python may do -- an effect (a damage pulse; a StopFiring the kernel
// cannot log), a whole ship Python must run, or a question the mirror cannot
// answer -- and returns it.
// The next next() resumes from the cursor and reads the LIVE mirror again, so
// no decision outlives a Python effect. There is no epoch check.
//
// THE WRITE LOG (rulings A and P7). The decision path writes the bank's
// `_dwell` (take_dwell / accumulate_dwell). The kernel makes it in the
// mirror and logs it, in the Python's order; every record carries the
// writes made since the previous record as its LAST element, and Python
// applies them (without pushing) before it acts on the record. An idle
// bank's take_dwell writing +0.0 over a +0.0 dwell is ELIDED (a plain float
// attribute: no side effect to preserve). A write's value is K1's
// (K1Value: None, bool, int, float, a handle list), applied by the same
// driver (native_combat.apply_writes, its quiet setters).
//
// THE OFFLINE STOP (round trips, spec 2026-11-01 §4.5). `sys_.StopFiring()`
// on an offline or off system whose banks are all PhaserBanks (live rows)
// is logged, with no SYSTEM_STOP record, in
// WeaponSystem.StopFiring's order (WS:1572): the system's `_fire_held =
// False`, `_held_target = None`, `_held_offset = None`, `_target_list = []`
// (a NEW list each time: Python's StopFiring builds one, and AddTarget
// appends in place), `_last_group_fired = -1`; then, in GetWeapon order,
// each bank's _EnergyWeaponFireMixin.StopFiring (WS:920, stop_firing.h):
// `_firing = False`, `_beam_on_countdown = 0.0`, and, for a bank that was
// FIRING, its loop sound's LOOP_STOP entry right after its own writes (THE
// EFFECT QUEUE; a firing bank kept the record before combat fire events).
// Never elided when equal: `_firing` is a WakeField (the driver's quiet
// setter wakes a sleeping bank) and the list is replaced. A child that is
// not such a bank, or a row gone, keeps the SYSTEM_STOP record.
//
// THE EFFECT QUEUE (spec 2026-11-02-combat-fire-events §4.1-4.3). The
// walk's `bank.StopFiring()` on its FIRING bank -- a target None or dead,
// undetectable, in another set, or the arc fail's (after its take_dwell) --
// is logged the same way (stop_firing.h's writes) with its LOOP_STOP(bank)
// entry after them, and the walk goes on (to the next bank; after the arc
// fail, to the partial pulse's trace). The entries are K1Entry (K1's type,
// `at` = the writes logged before it) riding the next record
// (K2Record::entries); the binding appends them to the combat effect queue
// (combat_effect_queue.h, which this library does not link) once that
// record's writes are applied, delivered by Python at the tick boundary or
// the session's end. They roll back with their writes: a throw, a ship
// handed to Python whole (run_python) or a bank handed back (bank_step)
// drops the ones its undone writes made.
//
// RESTING CONTACTS (spec 2026-11-02 §4.3). A contact whose Python is
// presentation only -- `flush_dwell <= 0.0`, _phaser_contact's beam_contact
// branch: no damage, no event, no RNG -- never comes back on a record. The
// kernel appends it to the session's queue (rests()), in walk order, as a
// K2Rest: the contact plus every value its presentation could otherwise
// read after later Python changed it, taken at contact time -- the
// system's `_power_level` (indexing PHASER_INTENSITY_SCALE), the loop's
// shields_block answer ALWAYS carried (an ASK's too, marked
// `shields_asked`; with no aim unit the loop never evaluated it, so the
// kernel does, natively, for the entry, and leaves it unknown if that
// would need an ASK), the target's instance id (ctx.iids) and its set's
// view offset (ctx.view_offsets). The driver drains the queue once, after
// DONE and before end() (combat_k2_drain, take_rests()), so a rest is
// presented after every later record's Python of the step: presentation
// has no order inside a tick (spec 2026-11-02 §5, Q1); game state keeps
// its exact order. The drain presents a rest itself -- beam_contact's
// shield splash, through the shield pass -- when its shields answer is
// True and its iid and view offset are known (`view_known`), and returns
// every other one, in queue order, for Python's beam_contact (spec
// 2026-11-02 §4.4); beam_contact, _mesh_xyz, host_io.shield_hit and
// weapon_splash_radius are deliberately not watched (ruling Q5: a patch of
// them is not obeyed for a native splash; native_combat.py, WHAT K2 STANDS
// IN FOR). begin(), end() and abandon() clear the queue: an
// abandoned step presents nothing it queued.
//
// THE DAMAGE PULSE (native damage, spec 2026-11-02-native-damage §3 goal 2;
// Task 4). A contact with `flush_dwell > 0.0` is _phaser_contact's damage
// branch, applied IN THE WALK when the context's `pulse.ok` holds and its
// target is in `pulse.clean` (the driver's scan found no instance
// attribute on it or its subsystems shadowing a method the hit stands in
// for): the damage is `_phaser_damage_for_tick(bank._max_damage,
// bank._max_damage_distance, dist, flush_dwell) *
// PHASER_INTENSITY_SCALE[level]` (level the system's mirrored
// `_power_level`, indexed as Python indexes a 3-tuple), and when it is > 0
// the hit is damage.h's apply_hit(target, damage, impact point, source =
// the ship, the normal, R_hit = the bank's DamageRadiusFactor if > 0 else
// `pulse.default_radius`, damage_hull = level != `pulse.pp_low`, shield
// point = the bubble entry, the phaser codes, `pulse.has_instances`) with
// `pulse.dc`. The step memo is cleared before and after it (combat.
// apply_hit's step_memo.forget, DM H13: memo_clear here; the Python tables
// are the driver's, at the next record). Its writes and entries ride the
// next record as a K2Hit, placed among the record's own writes and entries
// where they were made; the binding applies and appends them in that order
// (the Held operands: the ship). The mirror holds the result at once, so
// the next bank on the same target reads it (ruling P1). A damage of 0
// (or NaN) does nothing, as Python's `if damage > 0`. The kernel never
// decides a death (M5): a pulse that zeroes a critical subsystem leaves
// the target alive for the rest of the step. The pulse is rolled back with
// its walk: a throw, or its ship handed to Python whole (it never is once
// a pulse landed: the ship's body has started, as after a resting contact)
// undoes its writes (DamageOut::undo) and drops its entries.
// Anything else -- `pulse.ok` false (the driver found a function or class
// the hit stands in for replaced, or a player the mirror cannot name), a
// target not scanned clean, a level Python would raise on, or damage.h
// falling back -- keeps the CONTACT record, counted by why (K2PulseWhy):
// Python then runs _phaser_contact itself.
//
// RECORDS (K2Kind, in combat_k2_kinds() order). The Python layouts, as the
// binding builds them (handles are mirror handles, -1 = None; xyz = a
// 3-tuple of floats). Every record ends (..., writes).
//   0 DONE        (DONE, writes)
//        -> then combat_k2_drain(): the queued rests it did not present
//        itself (RESTING CONTACTS), each
//   (bank, target, ship, system, emitter_xyz, target_pos_xyz, dist,
//    aim_unit_xyz | None, impact_xyz, normal_xyz | None, tier,
//    bubble_xyz | None, shields_block (True / False / None), flush_dwell,
//    level, iid | None, view_offset_xyz | None)
//        (shields_block None: unknown, beam_contact evaluates its own;
//        view_offset None: no shift, or no entry for the set).
//   1 SYSTEM_STOP (SYSTEM_STOP, system, writes) -> sys_.StopFiring()
//        only for a stop THE OFFLINE STOP cannot log (a child that is not
//        a live stock phaser bank).
//   2 BANK_STOP   (BANK_STOP, bank, writes)   -> bank.StopFiring()
//        only for a firing bank's stop the kernel cannot log (its row gone:
//        a fallback the pre-scan makes unreachable; THE EFFECT QUEUE).
//   3 CONTACT     (CONTACT, bank, target, ship, system, emitter_xyz,
//                  target_pos_xyz, dist, aim_unit_xyz | None, impact_xyz,
//                  normal_xyz | None, tier, bubble_xyz | None,
//                  shields_block (True / False / None), flush_dwell,
//                  writes)
//        tier is "mesh", "sphere", "fallback" (the impact point IS
//        target_pos) or "origin" (the impact point IS emitter_pos), so Python
//        rebuilds Python's object identity. shields_block is None when the
//        loop did not evaluate it (aim_unit None) or Python answered it (an
//        ASK; K2Contact::shields_asked). Python: _phaser_contact, i.e.
//        combat.apply_hit(...) if the damage is > 0. Only a damage pulse
//        the kernel could not apply comes back as a CONTACT record (THE
//        DAMAGE PULSE); a resting contact is queued (RESTING CONTACTS
//        above).
//   4 RUN_PYTHON  (RUN_PYTHON, ship, ship_pos, writes)
//        -> the loop body for ships_list[ship_pos], in Python, whole.
//   5 ASK         (ASK, query, *args, writes)
//        -> reply combat_k2_answer.
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
//            posed target whose mount the mirror cannot tell (a pick no
//            mount claims is a plain body point, fire control native only
//            M5, answered natively). A lock on a posed ship
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
// PROTOCOL INVARIANT. Once a record for a BANK has been delivered (an ASK),
// the bank cannot be handed to Python (part of its body has run). The only
// Python run between that record and the bank's CONTACT is an ASK answer,
// which drops no mirror row, and the pre-scan made every remaining read
// nameable (a logged stop is not a record: a bank whose stop was logged
// can still be handed back, the stop rolled back with it); if one still
// fails, next() throws std::logic_error (the session is restored, see below)
// and run_k2 must abandon and re-raise naming this invariant. The part slots
// the bank's GEOMETRY reads were checked current at its start, and the only
// Python between that check and GEOMETRY is ASK answers (is_dead,
// can_detect, aim_point). run_k2 re-resolves the step's ships whenever an
// answer moved the part-map generation, before handing it back
// (native_combat._heal_part_slots, never dropping a row), so GEOMETRY reads
// freshly stamped slots by construction; a stale one here stays a
// last-resort guard (reachable only if Python's own part resolution raises,
// when Python's step would raise on that mount too).
//
// PINNING (the Python driver's contract; Task 5's run_k2). Python's loop
// holds strong references in its locals (`ship`, `sys_`, `bank`, `target`);
// the kernel holds only handles. The driver pins LAZILY: the step's ship list
// keeps the ships alive, and before any NON-PURE Python runs (Python that can
// drop the last other reference to an object: a StopFiring, a contact's
// effects, a whole ship's step) the record that triggers it names -- and the
// driver resolves and pins (_K2Walk.obj, pin_bank) -- the objects Python's
// locals would hold at that point:
//   - SYSTEM_STOP (a fallback): the system, before its StopFiring;
//   - a drained resting contact: the bank, the target, the ship and the
//     system, when the driver presents it -- by handle through the pin set
//     and the weak registry (_K2Walk.live): an entry naming an object freed
//     or unregistered between its queueing and the drain is skipped (its
//     presentation would have run before then);
//   - BANK_STOP (a fallback): the bank, its `_target` and its system
//     (pin_bank), before the bank's StopFiring (a logged stop runs no
//     Python: nothing to pin);
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
// session -- cursor, pending answer, queue -- to the state before the call.
// The mirror's logged fields then still equal Python, so abandon() is
// safe. Caveat: can_detect's memo and lock-break latch writes and the mount
// memo are not undone: they are the writes Python's own calls make at the
// same point (sensor_detect.h, weapon_geometry.h). Once a record is
// returned its writes are in the mirror and their undo is gone, so the
// binding applies them all before it returns the record, and applying a
// write must not fail part-way (apply_writes' quiet setters: plain fields
// on pinned rows, and the `_firing` WakeField). A raise in the record's own
// effect, or in a drained rest's presentation, comes after all of the
// step's writes were applied.
// abandon() itself only ends the session: it undoes nothing.
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
// k2_phasers; Task 5, phase 6 A3). The kernel computes, from the mirror,
// what host_loop's loop body and the functions and methods it calls would
// answer. A module function or stock-class method replaced since is NOT
// obeyed (spec Part A: a stage never falls back to Python because a method
// was patched; the snapshot compare of _K2_FUNCTIONS and the stock classes
// is deleted). The driver runs the WHOLE `cb.phasers` step in Python (no
// session) only for representability:
//   - a K2 session is already open;
//   - `ship_instances` is neither None nor a TrackedInstances (a test's
//     plain dict);
//   - the native audit is on (DAUNTLESS_NATIVE_AUDIT=1, below);
//   - a ship's (or a bank's target's) class K2 never saw, flagged "whole"
//     by the class flags below.
// THE CLASS FLAGS read a class's role (native_combat._K2_ROLES) when it is
// not the stock class (a walked ship's phaser system or bank of another
// class, or a class K2 never saw). The role's names, as
//   - a STOCK CLASS resolves them (native_combat._K2_ROLES; every
//     SUBSYSTEM role -- the first five -- also watches the subsystem names
//     GetWorldLocation, GetPosition, _climb_to_ship; the override guard
//     test parses this list):
//       PhaserBank: IsFiring, IsBeamOn, take_dwell, accumulate_dwell,
//         _strip_emit_position, _emitter_world_position, GetLength,
//         GetDirection, GetUp, GetArcWidthAngles, GetArcHeightAngles,
//         IsDisabled, IsDestroyed, GetMaxDamage, GetMaxDamageDistance,
//         GetDamageRadiusFactor;
//       PhaserSystem: GetNumWeapons, GetWeapon, GetNumChildSubsystems,
//         GetChildSubsystem, IsOn, IsDisabled, IsDestroyed, GetPowerLevel,
//         PP_LOW;
//       ShieldSubsystem: HasShields, IsOn, IsDisabled, IsDestroyed;
//       CloakingSubsystem: IsCloaking, IsDecloaking;
//       ShipSubsystem: the subsystem names;
//       ShipClass: IsDead, GetWorldLocation, GetWorldRotation,
//         GetContainingSet, GetScale, GetRadius, GetBaseRadius,
//         GetShields, GetPhaserSystem, GetTargetSubsystem, is_using_target_offset,
//         GetTargetOffsetTG, GetCloakingSubsystem;
//       ObjectClass: IsDead, GetWorldLocation, GetWorldRotation,
//         GetContainingSet, GetScale, GetRadius, GetBaseRadius,
//         GetShields;
//   - any class with a row (of those) resolving a name of its role to a
//     method defined outside the engine package (a mod's subclass, a
//     test's) or to
//     anything other than what it resolved to when the driver first saw it
//     is flagged: a bank or phaser system class overriding only its own
//     (non-subsystem) names sends only its ship to Python; any other sends
//     the whole step ("whole").
// The audit: the kernel's own can_detect would bypass sensor_detection's
// per-call audit.
// It lists a ship in `python_ships` (RUN_PYTHON "overridden") when its bank
// or system class overrides one of its own names, or it has an INSTANCE
// attribute shadowing a method the loop calls on it by name:
//   the ship: GetPhaserSystem, GetTargetSubsystem, is_using_target_offset,
//     GetTargetOffsetTG, GetShields, IsDead, GetWorldLocation,
//     GetWorldRotation;
//   its phaser system: GetNumWeapons, GetWeapon, IsOn, IsDisabled,
//     IsDestroyed, StopFiring, GetPowerLevel, PP_LOW;
//   a bank: IsFiring, IsBeamOn, take_dwell, accumulate_dwell,
//     _strip_emit_position, _emitter_world_position, GetLength, StopFiring,
//     GetMaxDamage, GetMaxDamageDistance, GetDamageRadiusFactor.
// (GetMaxDamage, GetMaxDamageDistance, GetDamageRadiusFactor, PP_LOW: THE
// DAMAGE PULSE reads the bank's and system's mirrored values.)
// (GetPowerLevel: a resting contact carries the system's mirrored
// `_power_level`, RESTING CONTACTS. StopFiring: THE OFFLINE STOP and the
// walk's logged bank stops stand in for it. K1's class-override guard,
// which K2 shared, is deleted with fire control's Python copy (fire control
// native only, M8.7): a class overriding StopFiring is not obeyed.)
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
    Overridden,         // the driver listed the ship (context python_ships)
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

// One write-log entry: `handle.field = value` -- a bank's "_dwell", or an
// offline stop's fields (THE OFFLINE STOP). The value is K1's encoding.
struct K2Write {
    int64_t handle = -1;
    std::string_view field;  // a static name (write_log.h)
    K1Value value;
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
    bool shields_asked = false;  // shields_block came from an ASK answer
    double flush_dwell = 0.0;
};

// Why a damage pulse came back as a CONTACT record (THE DAMAGE PULSE).
enum class K2PulseWhy : int32_t {
    not_ok = 0,   // the context's pulse.ok is false
    unscanned,    // the target is not in pulse.clean
    level,        // the power level is not an index of the 3-tuple
    fallback,     // damage.h fell back (the mirror is as it was)
    python,       // the bank is in pulse.python_banks (K3: the driver's own)
    kCount
};
const char* k2_pulse_why_name(K2PulseWhy w);

// A damage pulse applied in the walk (THE DAMAGE PULSE): its writes and
// entries, placed after the record's first `at_write` writes and
// `at_entry` entries. `source` is the Held operands' handle (the ship);
// `bank`, `target` and the trace's `tier` describe the contact
// (combat_k2_last_hits).
struct K2Hit {
    size_t at_write = 0, at_entry = 0;
    int64_t source = -1, bank = -1, target = -1;
    ResolvedHit::Tier tier = ResolvedHit::Tier::Fallback;
    DamageOut out;
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
    // The queue entries produced since the previous record, in walk order
    // (THE EFFECT QUEUE): K1's entry type, LOOP_STOP only.
    std::vector<K1Entry> entries;
    // The damage pulses applied since the previous record, in walk order
    // (THE DAMAGE PULSE).
    std::vector<K2Hit> hits;
};

// A resting contact queued for the drain (RESTING CONTACTS), with what its
// presentation would otherwise read later, as it was at contact time.
struct K2Rest {
    K2Contact contact;  // shields_block: the answer, ASKed or native; nullopt
                        // only when no aim unit and the mirror cannot answer
    int64_t level = 0;  // the system's `_power_level` (GetPowerLevel)
    std::optional<InstanceId> iid;  // ctx.iids[target]: nullopt when absent
                                    // or not an InstanceId
    bool view_known = false;  // the target's set has a view_offsets entry
    std::optional<Vec3> view_offset;  // that entry (nullopt: None, no shift)
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

// What a damage pulse reads that the mirror does not hold (THE DAMAGE
// PULSE), sent by the driver at begin.
struct K2PulseCtx {
    // The pulse may be applied in the walk this step.
    bool ok = false;
    // The player (always) and the three cheats (damage.h).
    DamageContext dc;
    // host_loop.PHASER_INTENSITY_SCALE (a 3-tuple), combat.
    // PHASER_DEFAULT_DAMAGE_RADIUS and PhaserSystem.PP_LOW.
    std::array<double, 3> intensity{0.0, 0.0, 0.0};
    double default_radius = 0.0;
    int64_t pp_low = 0;
    // The phaser's codes: HIT_PRESENT's weapon (effect_queue's HitWeapon)
    // and WEAPON_HIT's (WeaponHitEvent.PHASER).
    int64_t hit_weapon = 0, weapon_hit_type = 0;
    // ship_instances is not None.
    bool has_instances = false;
    // Targets the driver scanned clean (Object handles).
    std::unordered_set<int64_t> clean;
    // K2: banks (Subsystem handles) whose instance dict shadows a name the
    // pulse reads from the mirror (GetMaxDamage, GetMaxDamageDistance,
    // GetDamageRadiusFactor): their pulses are Python's. Unused by K3.
    std::unordered_set<int64_t> python_banks;
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
    // THE DAMAGE PULSE.
    K2PulseCtx pulse;
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

    // The resting contacts queued for the drain this session, in walk
    // order (empty when no session is open). take_rests() hands them over
    // and leaves the queue empty (combat_k2_drain); it throws
    // std::logic_error while the session has not returned DONE.
    const std::vector<K2Rest>& rests() const;
    std::vector<K2Rest> take_rests();

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
        // Round trips (spec 2026-11-01 §4.4-4.5): resting contacts queued
        // for the drain (no record of their own) and offline stops logged
        // (no SYSTEM_STOP record).
        int64_t batched_contacts = 0, logged_system_stop = 0;
        // Combat fire events (THE EFFECT QUEUE): of the logged system
        // stops, those that stopped a firing bank, and firing banks'
        // StopFirings logged instead of a BANK_STOP record; the queue
        // entries produced, by K1Effect (LOOP_STOP only).
        int64_t logged_firing_system_stop = 0, logged_bank_stop = 0;
        std::array<int64_t, static_cast<size_t>(K1Effect::kCount)> entries{};
        // THE DAMAGE PULSE: pulses applied in the walk (counted when made:
        // a throw or a hand-back that undoes one can overcount), and those
        // kept as a CONTACT record, by why.
        int64_t native_pulses = 0;
        std::array<int64_t, static_cast<size_t>(K2PulseWhy::kCount)>
            pulse_why{};
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }
    // The damage pulses the records returned since the last call carried
    // (the driver forgets the step memo's Python tables when it is > 0).
    int64_t take_hits() { return std::exchange(hits_returned_, 0); }

    struct Session;  // the cursor (k2_beams.cc)

private:
    Mirror& m_;
    K2Context ctx_;
    std::unique_ptr<Session> session_;
    Counts counts_;
    int64_t hits_returned_ = 0;

public:
    ~K2Kernel();
    K2Kernel(const K2Kernel&) = delete;
    K2Kernel& operator=(const K2Kernel&) = delete;
};

// The process-wide kernel over mirror().
K2Kernel& k2_kernel();

}  // namespace dauntless::combat
