#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/write_log.h"

// K1, the native fire-control kernel: fire control's ONE copy of its rules
// (spec docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md;
// fire control's Python copy is deleted, M3).
//
// A walk of host_loop._pump_held_weapons and of a weapon system's per-tick
// update (BC's WeaponSystem update: the target prune, the walk offset, the
// group and round-robin walk, try-fire with each kind's CanFire and Fire)
// over the Mirror. k1_fire_control.cc names every cursor state after the
// Python line it was ported from (the Python as it stood at 9c3db5ec6,
// engine/appc/weapon_subsystems.py WeaponSystem.update_weapons /
// try_fire_weapon; docs/reference/engine/native-combat/k1-fire-control-map.md).
//
// ONE CALL PER SESSION. No Python runs inside a session: next() runs the
// session to its end and returns its one record, DONE, carrying every write
// the session made (THE WRITE LOG) and every queue entry it produced (THE
// EFFECT QUEUE). Python applies the writes and appends the entries; the
// entries are delivered at the tick boundary or the session's end.
//
// THE WALK OFFSET. A walk's offset (BC's live held offset: the firing ship's
// Manual Aim pick while it has one, else the system's _held_offset) is
// computed here, from the mirror (k1_live_held_offset), when the walk starts.
// Every logged `_target_offset = <the walk's offset>` names its walk
// (K1WalkOffset), and the driver makes ONE object per walk for all of them
// (ruling P5; native_combat._K1Walk.materialise, M8.8): the system's own
// `_held_offset` object when the walk's offset came from it, else a new
// TGPoint3 of the manual pick this kernel recorded for the walk
// (walk_manual_offset).
//
// THE WRITE LOG. The writes the decision path makes (fire timers, the
// `_depleted` clear, cleared targets, the pulse stamps, the cursor and group
// bookkeeping, the pruned target list) are made in the mirror and logged, in
// the walk's order; the record carries them as its LAST element and Python
// applies them, in order, with no push (the mirror already holds them).
// Effects that are pure field writes are logged the same way: a Fire on a
// beam ALREADY firing (`_firing = True; _target = target; _target_offset =
// <the walk's offset object>`, each stamp logged only when it changes
// something in Python -- phase 6 A3: `_firing` already True, `_target` the
// same live handle, or the bank already holding the walk's held-offset
// OBJECT (THE OFFSET SOURCE, mirror.h) is not logged; Manual Aim's new
// TGPoint3 always is), and a StopFiring on a bank that is NOT firing
// (its class's writes: energy bank `_firing = False; _beam_on_countdown =
// 0.0`; tube `_firing = False`; pulse `_firing = False; _target = None;
// _target_offset = None`). `_firing` is a WakeField: the driver's quiet
// setter still wakes a sleeping bank.
//
// THE EFFECT QUEUE (spec 2026-11-02-combat-fire-events §4.1-4.3). Effects
// that are field writes plus a sound or an event are logged writes and a
// K1Entry, in walk order, delivered by Python (engine/appc/effect_queue.py)
// at the tick boundary or at the session's end, never mid-walk:
//   a beam's was-not-firing edge   `_firing = True; _target = target;
//       _target_offset = <the walk's offset>; _beam_on_countdown =
//       BEAM_ON_DELAY_S (pushed from Python); _dwell = 0.0`, then
//       FIRE_SOUND(bank), WEAPON_FIRED(bank, target)
//   a tube's failed aim            WEAPON_FIRE_FAILED(tube)
//   a FIRING bank's StopFiring     its class's writes as above, then, for a
//       PhaserBank, LOOP_STOP(bank)
//   the pump's system stop         WeaponSystem.StopFiring's `_fire_held =
//       False; _held_target = None; _held_offset = None; _target_list = [];
//       _last_group_fired = -1`, then each child's StopFiring in order.
// Each entry's `at` places it after the writes logged before it; the binding
// appends them to the combat effect queue (combat_effect_queue.h, which this
// library does not link) as it hands the record back. A throw drops the
// session's entries with its writes. An abandoned session drops nothing
// already in the queue (ruling F5).
//
// LAUNCHES AT THE BOUNDARY (spec 2026-11-02-combat-launch-deferral §4.1).
// A tube's launch -- a Fire on a tube, or the dumb fire (Weapon.FireDumb:
// the warp-in hold, then Fire(None, None)) -- is logged in its order:
//     `_target = target; _target_offset = <the walk's offset>` (None, None
//     on the dumb path); `_firing = True`; `_num_ready -= 1`;
//     `_last_fire_time = now`; the system's `_last_system_fire_time = now`;
//     the first loaded slot's cooldown (`_reload_timers[i] = 0.0;
//     _reload_advanced_at[i] = now`, slot writes); the ammo type's
//     AddAvailable(-1) for a finite magazine (`_available = max(0,
//     min(_available - 1, _max_torpedoes))`)
// then SPAWN(tube, K1Spawn) -- the fire-time record the spawn needs, every
// value computed here at fire time so a pose that moves later in the step
// cannot move the launch -- WEAPON_FIRED(tube, target), AMMO_CONSUMED(tube),
// and last `_firing = False`. The delivery of SPAWN (effect_queue.py) builds
// the torpedo from the record (weapon_subsystems.spawn_launch: Create,
// register, ET_TORPEDO_ENTERED_SET, the launch sound) and posts its
// ET_TORPEDO_FIRED, so the delivered order is BC's: the spawn, ENTERED_SET,
// TORPEDO_FIRED, WEAPON_FIRED, AMMO_CONSUMED. With no ammo type the launch
// is the hardpoint's slot-0 script's (M8.2). A launch the kernel cannot
// make -- no module (Unresolved), the type's launch not cached (Uncached:
// THE P6 WINDOW, or a GetLaunchSpeed that raises), anything else the mirror
// cannot say (Other: slot lists out of step with MaxReady, an unnamed set)
// -- does not fire (NO FIRE: K1NoFire::Launch, its why in launch_why). Its
// module's Create runs at the delivery (rulings L1, L6).
//
// A cannon's launch -- a Fire on a PulseWeapon -- is, in its order:
// SPAWN(cannon, K1Spawn) (the mount, unit(the decision's led world_dir) x
// the cannon's P6 launch speed + the ship's velocity, the target the shot
// used if alive, the walk's offset, GetDamageRadiusFactor(),
// GetDamageScale() from the pushed table, and the target as fired_at), then
// `_charge_level = max(0.0, _charge_level - shot cost)` and
// `_cooldown_remaining = GetCooldownTime()`. No WEAPON_FIRED entry: the
// delivery posts its ET_WEAPON_FIRED once the bolt exists (M4). The SPAWN's
// module is the cannon's own (the one its P6 params were read from, held by
// the bindings per row); a module re-imported since is re-read at the next
// K1 entry (native_combat._refresh_stale_launches, M8.3).
//
// THE P6 WINDOW. A cannon's launch speed and module are read when its
// params are pushed (SetProperty, a mission swap's refresh); an ammo type's
// when it is pushed (its creation, SetTorpedoScript, the refresh), and a
// torpedo property's slot-0 script's likewise. Between a projectile-cache
// reset (a mission swap) and the next K1 entry every row keeps the launch
// it holds and the kernel launches from it -- no no-fire (M8.3).
//
// NO FIRE (fire control native only, R2, R3; K1NoFire). Whatever the mirror
// cannot answer is "does not fire that tick", counted by why
// (Counts::no_fire) and reported once per why (K1Record::no_fire_new; the
// driver logs one line per why per session):
//   - found before a system's walk writes anything (the pre-scan in the
//     .cc: a row it cannot represent, a leaf of a POSED ship whose part slot
//     is not current -- part_stale, retried at every entry, M8.4 --, a pump
//     gate the mirror cannot answer): the system is skipped. In the pump the
//     pre-scan is two halves around the stop gates: what the gates and
//     their StopFiring read (gate_prescan) before them, what only the walk
//     reads (walk_prescan) after them, so a system a gate stops -- its held
//     target died, it went offline -- is stopped even when its walk could
//     not be read (host_loop._pump_held_system's order);
//   - found in the walk before its first shot (a CanFire, a Fire decision or
//     a launch the mirror cannot make, a mid-walk read): the walk's writes
//     and entries are rolled back (k1_roll_back) and the walk ends, as if it
//     had not walked;
//   - found after a shot: what happened is kept and the walk ends -- except
//     single fire's reseed (a child the mirror cannot name: the reseed is
//     skipped, the walk goes on) and the retry loop (an entry the mirror
//     cannot read, or whose IsDead it cannot answer, is treated as gone).
// The SDK routes' no-fires are the same: a Fire that cannot be decided or
// launched returns False with its writes rolled back.
//
// A THROW from next() (a protocol error: logic_error) undoes the field
// writes the session made, in the mirror, and restores the session to the
// state before the call. The mirror's fields then still equal Python, so
// abandon() is safe. Caveat: can_detect's memo and lock-break latch writes
// (the pump's undetectable gate) are not undone; the pre-scan makes every
// gate after can_detect answerable, so no no-fire follows one either.
//
// THE TRACTOR WALK (fire control native only, M4, R8). A TractorBeamSystem
// is K1's whole (the KRM §3.1 model,
// docs/reference/engine/native-combat/k1-retirement-map.md):
//   the pump (getter 2, `_fire_held` set): held target None: nothing; the
//       system off: the sync only; offline or the target dead: the system's
//       StopFiring; else every firing projector out of range
//       (TRACTOR_MAX_RANGE_GU, same set) or out of arc stops (intent kept);
//       out of range: the sync; one still firing: the sync; else the engage
//       at the walk's offset and the sync
//   begin_tractor -- StartFiring after its gates and its intent writes
//       (Python's, native_combat.k1_tractor_start): the range check, the
//       engage at StartFiring's offset, then the sync
//   the engage     single fire: from `_next_emitter_index % n`, the first
//       in-arc projector whose CanFire holds fires (the beam's Fire: its
//       decision and its effect, logged as a beam's edge or sustain but with
//       no WEAPON_FIRED) and the cursor moves past it; multi fire: every
//       in-arc projector whose CanFire holds
//   StopFiring     `_engage_state = None`, WeaponSystem.StopFiring's writes
//       (each projector's the mixin's stop, stop_firing.h), then the sync
//   the sync       on an IsFiring() edge with a parent ship, `_was_firing =
//       now` and a TRACTOR_STARTED / TRACTOR_STOPPED (system, ship) entry:
//       delivered at the boundary as ET_TRACTOR_BEAM_STARTED_FIRING /
//       _STOPPED_FIRING (ruling R8)
// A projector's `_firing` applies through its NativeThawParentWakeField
// setter, so the power thaw stays Python's. A tractor walk the mirror cannot
// read (an unnamed row, a target with no real IsDead) is rolled back whole:
// K1NoFire::TractorRow.
//
// THE SDK ROUTES (fire control native only, M8.1, M8.6). The SDK's own
// weapon calls outside any walk are one-weapon sessions on the same rules:
//   begin_dumb   Weapon.FireDumb(0, 1) on a tube (AI/Preprocessors.py:458):
//       the warp-in hold, the tube's Fire decision with no target, the
//       launch (LAUNCHES AT THE BOUNDARY)
//   begin_fire   weapon.Fire(target, offset): decide, then the walk's own
//       effect of it (a beam's sustain or edge -- a TractorBeam's without
//       its WEAPON_FIRED --, a tube's or a cannon's launch, a tube's
//       WEAPON_FIRE_FAILED). The offset is the session's walk 1 (its object
//       is Fire's offset, as begin_tractor's). A cannon's `ship.GetTarget()`
//       fallback is the session's ship_target (Python reads it: SDK state
//       the mirror does not hold). result(): 1 fired, 0 not (a no-fire
//       included: never Python's)
//   sdk_can_fire weapon.CanFire(): fire_gates can_fire, `_depleted`'s clear
//       reported for Python's setter to make
//
// PINNING. The kernel holds only handles. The driver keeps every object a
// write may name alive until the session's record is applied (its pin set,
// then the registry: native_combat._K1Walk). No Python runs inside a
// session, so no row can be freed or dropped mid-walk.
//
// SESSIONS form a stack: an effect's event handler, delivered at a
// session's end, may StartFiring, which begins (and finishes) a nested
// one-system session.

namespace dauntless::combat {

// Record kinds, in combat_k1_kinds() order: a session's one record (ONE CALL
// PER SESSION).
enum class K1Kind : int32_t {
    DONE = 0,
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
    TRACTOR_STARTED,     // (tractor system, its ship)  THE TRACTOR WALK
    TRACTOR_STOPPED,     // (tractor system, its ship)
    kCount
};
const char* k1_effect_name(K1Effect e);

// Why a walk did not fire that tick (NO FIRE; fire control native only, R2,
// R3), in combat_k1_counts' k1_no_fire. At most 64 (Counts::no_fire_reported).
enum class K1NoFire : int32_t {
    TractorRow = 0,   // a tractor walk the mirror cannot read (THE TRACTOR WALK)
    StaleRow,         // an unnamed (-2) or freed row the walk reads
    StubOrUnplaced,   // no real IsDead, or no valid transform
    PulseShipTarget,  // a pulse system with no live target-list entry
    PulseModule,      // a pulse module unresolved or power setting out of range
    AmmoRow,          // a torpedo ammo slot names no live Ammo row
    PartStale,        // a posed ship's part slot is not current (M8.4)
    UnslottedShip,    // a pump ship with no mirror row
    Gate,             // a pump gate the mirror could not answer
    Structure,        // child structure, a negative chain group ...
    NotK1System,      // a held system of no K1 kind (a plain WeaponSystem)
    CanFire,          // a weapon's CanFire the mirror could not answer
    Decision,         // a Fire decision the mirror could not make
    Launch,           // a launch the kernel cannot make (by K1LaunchWhy)
    Walk,             // a mid-walk read the mirror could not answer
    Reseed,           // single fire's reseed, a child unnamed: skipped
    Retry,            // a retry entry the mirror cannot read: treated as gone
    IsDead,           // a retry entry whose IsDead it cannot answer: gone
    kCount
};
const char* k1_no_fire_name(K1NoFire w);

// A launch's fire-time record (LAUNCHES AT THE BOUNDARY): what the spawn
// reads, read here when the launch is decided. Handles are -1 for None.
struct K1Spawn {
    enum class Kind : int32_t { Tube = 0, Pulse = 1, Dumb = 2 };
    Kind kind = Kind::Tube;
    int64_t ship = -1;    // the launcher's ship: the torpedo's source
    int64_t set = -1;     // the ship's containing set (register joins it)
    // The row whose launch module the SPAWN carries (the bindings'
    // k1_launch_modules): a tube's ammo type (or its system's property: the
    // slot-0 launch, M8.2), a cannon itself.
    int64_t ammo = -1;
    int64_t target = -1;  // the launcher's target, if alive
    Vec3 position{0, 0, 0};  // the launcher's world mount
    // unit(dir) * launch speed + ship velocity; false when the direction
    // has no length (the torpedo's velocity is then left alone).
    bool has_velocity = false;
    Vec3 velocity{0, 0, 0};
    // SetTargetOffset(the launcher's offset): with a target and a TGPoint3
    // offset, the offset (steered at as it is: no bake, M5).
    bool has_offset = false;
    Vec3 offset{0, 0, 0};
    double drf_override = 0.0;  // the launcher's GetDamageRadiusFactor()
    // A cannon's (a tube's are 1.0 and -1): the power setting's
    // GetDamageScale() at fire time, applied after register, and the target
    // the shot used, its ET_WEAPON_FIRED's pointer (posted by the delivery,
    // after the bolt exists: M4).
    double damage_scale = 1.0;
    int64_t fired_at = -1;
};

// One entry, in walk order. `at`: how many of the carrying record's writes
// were logged before it (the entry follows them).
struct K1Entry {
    K1Effect kind = K1Effect::FIRE_SOUND;
    int64_t a = -1, b = -1;
    size_t at = 0;
    std::optional<K1Spawn> spawn;  // SPAWN
};

// Why a launch could not be made (LAUNCHES AT THE BOUNDARY), in
// combat_k1_counts' k1_launch_reasons: the detail of K1NoFire::Launch.
enum class K1LaunchWhy : int32_t {
    Unresolved = 0,  // no ammo type and no slot-0 script, no script, no module
    Uncached,        // the type's launch is not cached yet
    Other,           // the mirror is inconsistent: slot lists out of step
                     // with MaxReady, an unnamed set, a row the plan cannot
                     // read
    kCount
};
const char* k1_launch_why_name(K1LaunchWhy w);

// K1WalkOffset, the marker for "the walk's own offset object" (ruling P5),
// lives in write_log.h (the shared write representation).

// One write-log value. monostate is Python None. A SlotWrite is a tube's
// in-place slot write (`_reload_timers[i] = v`, write_log.h): the launch's
// slot cooldown.
using K1Value = std::variant<std::monostate, bool, int64_t, double,
                             K1WalkOffset, std::vector<int64_t>, SlotWrite>;

struct K1Write {
    int64_t handle = -1;
    std::string_view field;  // the Python attribute name (write_log.h)
    K1Value value;
};

// A Fire decision (the walk's own, never returned).
struct K1Decision {
    enum class Shape : int32_t { Beam, Pulse, Tube } shape = Shape::Beam;
    bool was_firing = false;      // Beam
    Vec3 world_dir{0, 0, 0};      // Pulse: the led direction
    int64_t target_used = -1;     // Pulse and Tube: the target Fire used
};

struct K1Record {
    K1Kind kind = K1Kind::DONE;
    std::vector<K1Write> writes;
    // The queue entries the session produced, in walk order.
    std::vector<K1Entry> entries;
    // The K1NoFire whys counted for the first time since reset_counts
    // (bit i: K1NoFire i): the driver logs each once.
    uint64_t no_fire_new = 0;
};

// The firing ship's live Manual Aim pick (ShipClass.GetTargetOffsetTG's
// manual branch, is_using_target_offset: a ShipClass row with
// _use_target_offset and a TGPoint3 _manual_target_offset), else nullopt.
// `ship` -1: none.
std::optional<Vec3> k1_manual_offset(const Mirror& m, int64_t ship);

// The walk offset on the mirror: k1_manual_offset(ship) when it has one,
// else the system's _held_offset when it is a TGPoint3, else nullopt (the
// object is then not a TGPoint3, which every reader treats as no offset).
// `ship` is the system's parent ship (-1: none).
std::optional<Vec3> k1_live_held_offset(const Mirror& m, int64_t system,
                                        int64_t ship);

class K1Kernel {
public:
    explicit K1Kernel(Mirror& m);

    // _pump_held_weapons(ships_list, dt). `ships` are Object handles in list
    // order, -1 for a ship with no row (a no-fire). `now` is
    // weapon_subsystems._game_time() (the Utopia game time, 0.0 if it raises;
    // also the occlusion clock), `drift_now` native_combat.now() (the nebula
    // drift clock). `use_memo` is step_memo.active().
    void begin_pump(std::vector<int64_t> ships, double dt, double now,
                    bool use_memo, double drift_now);
    // WeaponSystem.StartFiring's immediate update (dt 0) on one system.
    void begin_system(int64_t system, double dt, double now, bool use_memo,
                      double drift_now);
    // TractorBeamSystem.StartFiring's engage (THE TRACTOR WALK) on `system`,
    // its intent already written: `target` (an Object handle, -1 None, -2
    // unnamed: no fire), `offset` the StartFiring offset's xyz when it is a
    // TGPoint3 (the session's walk 1: its object is the offset itself).
    void begin_tractor(int64_t system, int64_t target,
                       std::optional<Vec3> offset, double now, bool use_memo,
                       double drift_now);
    // THE SDK ROUTES. Weapon.FireDumb(0, 1) on `tube`.
    void begin_dumb(int64_t tube, double now, bool use_memo, double drift_now);
    // weapon.Fire(target, offset) on `weapon` (any leaf kind): `target` an
    // Object handle (-1 None, -2 unnamed: no fire), `offset` Fire's offset
    // xyz when it is a TGPoint3; `ship_target` the weapon's ship's
    // GetTarget() (-1 None, -2 unnamed), nullopt when not read.
    void begin_fire(int64_t weapon, int64_t target, std::optional<Vec3> offset,
                    std::optional<int64_t> ship_target, double now,
                    bool use_memo, double drift_now);
    // weapon.CanFire() (fire_gates can_fire, counted). Throws
    // std::invalid_argument when the mirror cannot answer.
    CanFireResult sdk_can_fire(int64_t weapon, double now);
    // The top session's result (begin_fire: see THE SDK ROUTES; 0 for the
    // others), readable once it has returned DONE, before end().
    int64_t result() const;
    // THE WALK OFFSET: the manual pick the top session recorded for its walk
    // `walk` (nullopt: the walk's offset is the system's _held_offset).
    // Throws std::logic_error for a walk the session did not start.
    std::optional<Vec3> walk_manual_offset(int64_t walk) const;

    // The top session's record (ONE CALL PER SESSION). Throws
    // std::logic_error when no session is open or it already returned DONE.
    K1Record next();

    // Pops the top session, which must have returned DONE.
    void end();
    // Pops the top session whatever its state (an exception unwound the
    // Python driving it).
    void abandon();
    size_t depth() const { return sessions_.size(); }
    void clear();

    struct Counts {
        int64_t records = 0;
        // Posed parts walked natively: systems whose ship is posed, and Fire
        // decisions aimed at a posed target's offset.
        int64_t posed_walks = 0, posed_target_aims = 0;
        // Walks started (k1_logged.walk_start).
        int64_t logged_walk_start = 0;
        // Pure field writes logged (round trips Task 2): a Fire on a beam
        // already firing (k1_logged.beam_sustain) and a StopFiring on a bank
        // that is not firing (k1_logged.idle_bank_stop).
        int64_t logged_beam_sustain = 0, logged_idle_bank_stop = 0;
        // A sustain's stamps not logged because they change nothing in
        // Python (phase 6 A3: `_firing` already True, `_target` the same
        // live handle, `_target_offset` the same held-offset object; THE
        // OFFSET SOURCE, mirror.h), each counted (k1_logged.
        // beam_sustain_skips).
        int64_t logged_beam_sustain_skips = 0;
        // Field writes plus queue entries (spec 2026-11-02-combat-fire-events
        // §4.3): a beam's was-not-firing edge (k1_logged.beam_edge), a
        // failed aim (k1_logged.fire_failed), a firing bank's StopFiring
        // (k1_logged.firing_bank_stop) and the pump's system stop
        // (k1_logged.system_stop).
        int64_t logged_beam_edge = 0, logged_fire_failed = 0,
                logged_firing_bank_stop = 0, logged_system_stop = 0;
        // The queue entries produced, by K1Effect (k1_entries).
        std::array<int64_t, static_cast<size_t>(K1Effect::kCount)> entries{};
        // Launches made as logged writes and a SPAWN entry (LAUNCHES AT THE
        // BOUNDARY): a tube's Fire, a dumb fire; dumb fires refused (the
        // warp-in hold, CanFire false: nothing written).
        int64_t logged_tube_launch = 0, logged_dumb_launch = 0,
                logged_dumb_refused = 0;
        // ... and a cannon's Fire: its drain, cooldown and SPAWN.
        int64_t logged_pulse_launch = 0;
        // THE TRACTOR WALK: the pump's tractor walks, StartFiring's tractor
        // sessions.
        int64_t logged_tractor_walk = 0, logged_tractor_start = 0;
        // THE SDK ROUTES: dumb-fire sessions, Fire sessions decided,
        // CanFire answers.
        int64_t logged_sdk_dumb_fire = 0, logged_sdk_fire = 0,
                logged_sdk_can_fire = 0;
        // NO FIRE, by K1NoFire; the whys already reported in a record
        // (K1Record::no_fire_new), as bits; launches that could not be made,
        // by K1LaunchWhy (each also a K1NoFire::Launch).
        std::array<int64_t, static_cast<size_t>(K1NoFire::kCount)> no_fire{};
        uint64_t no_fire_reported = 0;
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

public:
    ~K1Kernel();
    K1Kernel(const K1Kernel&) = delete;
    K1Kernel& operator=(const K1Kernel&) = delete;
};

// The process-wide kernel over mirror().
K1Kernel& k1_kernel();

}  // namespace dauntless::combat
