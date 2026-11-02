#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/write_log.h"

// The native hit and condition chain (native damage, spec docs/superpowers/
// specs/2026-11-02-native-damage-design.md §4.2; damage-map.md §2-§3 is the
// line-by-line walk, §7 the bit-exactness hazards H1-H15). Each function is
// a port of the Python of the same name (damage.cc names the source):
//
//   apply_hit      combat._apply_hit: the shield face (the hull-box rule),
//                  the absorption ramp (ShieldSubsystem.ApplyDamage), the hull
//                  and every overlapping subsystem (_splash_weight, mount
//                  order), the immunity flags and the dev cheats, then the
//                  hit's HIT_PRESENT and WEAPON_HIT;
//   damage_system  DamageableObject.DamageSystem;
//   set_condition  ShipSubsystem._set_condition: the condition write, the
//                  condition watchers (COND_WATCH), the threshold state
//                  machine (SUBSYS_EVENT), the repair enqueue (REPAIR_ADD)
//                  and death_check.note_write (ZERO_CROSS).
//
// NO PYTHON. They read and write the Mirror only (and its TransformStore),
// so a kernel may call them without the GIL. What a Python object must be
// told is returned in a DamageOut:
//   writes   the Python attribute writes, in order, in the kernels' write-log
//            form (write_log.h): `_condition`, `_threshold_state` (plain
//            stores), a condition watcher's `_value` (WatcherWrite on
//            "_combined_watcher" / "_condition_watcher") and a face
//            (SlotWrite on "_current_shields"). The mirror already holds
//            every value;
//   entries  the damage kinds' effect-queue entries (combat_effect_queue.h,
//            THE FROZEN ENTRY CONTRACT, effect_queue.py OPERANDS), in the
//            Python reference's emission order: per condition write
//            COND_WATCH (combined, then condition), SUBSYS_EVENT,
//            REPAIR_ADD, ZERO_CROSS; per hit the hull's, then each
//            overlapping subsystem's in mount order, then HIT_PRESENT and
//            WEAPON_HIT. An R operand is a mirror handle (-1 None); an H
//            operand is `Held`: EVERY H operand of one call names that
//            call's source / killer (its handle, -1 None, kRefUnrepresentable
//            an object the mirror cannot name), which the caller turns into
//            the object the entry holds (the bindings: the Python object it
//            was handed, or a kernel's pre-resolved one, K1Held).
//
// FALLBACK. Like the geometry (weapon_geometry.h), a call throws
// std::invalid_argument when it cannot answer exactly as the Python would: a
// ref it reaches is unrepresentable or gone, a class the chain hands to
// Python (dmg_class DMG_PYTHON, dmg_ship 0), a condition watcher it cannot
// stand in for (-1), a face list that is not six long, a posed mount whose
// slot is stale, a zero hull-box axis (Python's ZeroDivisionError). Before
// throwing it RESTORES every mirror value it wrote and truncates `out` to
// what it held at entry, so the caller runs the Python reference on an
// untouched world.

namespace dauntless::combat {

// The damage kinds a native call emits, in effect_queue.py's order (the
// host appends them under combat_effect_queue.h's EffectKind of the same
// names; SPLASH is never emitted natively: ship_death.begin appends it).
enum class DamageKind : uint8_t {
    COND_WATCH = 0,
    SUBSYS_EVENT,
    REPAIR_ADD,
    ZERO_CROSS,
    HIT_PRESENT,
    WEAPON_HIT,
    kCount
};

// The code operands, effect_queue.py's constants (combat_effect_queue.h's
// CondWatch, SubsysEvent and HitTransition: the bindings check they agree).
constexpr int64_t kWatchCondition = 0, kWatchCombined = 1;
constexpr int64_t kSubsysDestroyed = 0, kSubsysDisabled = 1,
                  kSubsysOperational = 2;
constexpr int64_t kTransitionNone = 0, kTransitionDisabled = 1,
                  kTransitionDestroyed = 2;

// dmg_class (native_combat.DMG_*).
constexpr int64_t kDmgPython = -1, kDmgLeaf = 0, kDmgAggregate = 1;
// cond_watch_checks / comb_watch_checks for no watcher / an unowned one.
constexpr int64_t kWatchNone = -2, kWatchForeign = -1;

struct DamageOperand {
    // Handle: an R operand (a mirror handle, -1 None). Held: an H operand
    // (see above). Number / Int / Bool: D / I / B.
    enum class Type : uint8_t { Handle, Held, Number, Int, Bool };
    Type type = Type::Handle;
    union {
        int64_t handle = -1;  // Handle, Held
        double number;        // Number
        int64_t integer;      // Int
        bool boolean;         // Bool
    };
};

struct DamageEntry {
    static constexpr int kMaxOperands = 35;  // a spelled HIT_PRESENT
    DamageKind kind = DamageKind::COND_WATCH;
    int count = 0;
    std::array<DamageOperand, kMaxOperands> ops{};
};

// The value one write replaced (DamageOut::undo): a kernel that applies a
// hit in its walk (K2's pulse) undoes it with undo_damage when it rolls the
// walk back (k2_beams.h, THE DAMAGE PULSE). `face`: a slot of
// `_current_shields` (`index`); else `d` (an F field) or `i`.
struct DamageUndo {
    int64_t h = -1;
    Field f = Field::_condition;
    bool face = false;
    size_t index = 0;
    double d = 0.0;
    int64_t i = 0;
};

struct DamageOut {
    std::vector<LoggedWrite> writes;
    std::vector<DamageEntry> entries;
    // One per write, in write order: what it replaced. A fallback truncates
    // it with the rest.
    std::vector<DamageUndo> undo;
    void clear() {
        writes.clear();
        entries.clear();
        undo.clear();
    }
};

// Restore what undo[from..] replaced, newest first (the writes' own order
// reversed).
void undo_damage(Mirror& m, const std::vector<DamageUndo>& undo,
                 size_t from = 0);

// What apply_hit reads that is not mirrored state: dev_combat_cheats'
// three getters (god_mode_active, double_player_weapons_active,
// disable_npc_shields_active) and the current player (-1 none).
struct DamageContext {
    int64_t player = -1;
    bool god_mode = false;
    bool double_damage = false;
    bool npc_shields_off = false;
};

// combat._apply_hit's arguments, as hit_present_operands encodes them: the
// optional points behind presence flags, the weapon type as its two codes.
struct HitInput {
    int64_t ship = -1;      // an Object handle
    int64_t source = -1;    // see Held above
    double damage = 0.0;    // float(damage), before the 2x cheat
    Vec3 point{0, 0, 0};    // hit_point
    bool has_normal = false;
    Vec3 normal{0, 0, 0};
    double r_hit = 0.0;     // weapon_splash_radius, or the splash_radius
    bool damage_hull = true;
    bool bypass_shields = false;
    bool has_shield_point = false;
    bool shield_point_is_point = false;  // shield_point IS hit_point (H14)
    Vec3 shield_point{0, 0, 0};
    bool has_tangent = false;
    Vec3 tangent{0, 0, 0};
    bool has_decal_radius = false;
    double decal_radius = 0.0;
    double decal_dent = 0.0;
    bool single_impact = false;
    bool has_shield_radius = false;
    double shield_radius = 0.0;
    int64_t hit_weapon = 0;        // HitWeapon (HIT_PRESENT's weapon_type)
    int64_t weapon_hit_type = -1;  // WeaponHitType (WEAPON_HIT's)
    bool has_instances = false;    // apply_hit was given a ship_instances
};

void apply_hit(Mirror& m, const HitInput& in, const DamageContext& ctx,
               DamageOut& out);

// DamageableObject.DamageSystem(subsystem, amount, source): `ship` the
// receiver (whom the write is charged to), `killer` the source (Held).
void damage_system(Mirror& m, int64_t ship, int64_t subsystem, double amount,
                   int64_t killer, DamageOut& out);

// ShipSubsystem._set_condition(value, killer, ship): `ship` -1 for None
// (the owning ship is charged), `killer` the Held operand.
void set_condition(Mirror& m, int64_t subsystem, double value,
                   int64_t killer, int64_t ship, DamageOut& out);

// combat._shield_face_from_hit_point (the hull-box rule, DM H5): the face
// index (ShieldSubsystem.FRONT_SHIELDS .. RIGHT_SHIELDS) `point` belongs to.
// Exposed for the tests (damage_test.cc).
int shield_face(const Mirror& m, int64_t ship, const Vec3& point);

}  // namespace dauntless::combat
