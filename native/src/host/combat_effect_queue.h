// native/src/host/combat_effect_queue.h
//
// The combat effect queue (spec 2026-11-02-combat-fire-events-design.md
// §4.1-4.2, roadmap decision 6): ONE ordered queue for the weapon events and
// weapon sounds the combat step produces, delivered by Python
// (engine/appc/effect_queue.py) at the tick boundary.
//
// An entry is a kind plus its operands (at most kMaxOperands: a spelled
// HIT_PRESENT is the longest), in one emission order whoever appends it:
//   a kernel  append_native: mirror handles (-1 = None), numbers (a
//             watcher's old / new value), int codes (EffectInt) and flags
//             (EffectBool); no Python call. The binding may
//             hand operands over as object references the queue then
//             owns (OwnedObject: a launch's SPAWN, WEAPON_FIRED and
//             AMMO_CONSUMED objects, held from fire time: K1Held);
//   Python    append_objects (the binding combat_effect_post): object
//             references the queue OWNS until the entry leaves it.
// The lock is held for both (the kernels run under it today).
//
// An abandoned kernel session drops nothing from the queue (ruling F5):
// a kernel's entries reach it only once their record's writes are applied
// (a throwing call drops its own), and Python's follow their effect, so
// every queued entry stands for an effect that already happened.
//
// OWNERSHIP. The queue never touches Python: an object operand is an opaque
// pointer, released through the Release function the owner installed (the
// bindings install Py_DECREF). clear releases what it drops; take hands
// every entry -- and its references -- to the caller.
//
// Python-free on purpose, so it is tested from C++ (native/tests/host).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <span>
#include <variant>
#include <vector>

namespace dauntless::host {

// The entry kinds, in effect_queue.py's order (the binding hands it these
// numbers by name: combat_effect_kinds).
enum class EffectKind : int {
    FIRE_SOUND = 0,      // (bank)                 bank._play_fire_sfx()
    LOOP_STOP,           // (bank)                 stop + clear _loop_handle
    WEAPON_FIRED,        // (weapon, target)       ET_WEAPON_FIRED
    WEAPON_FIRE_FAILED,  // (tube)                 ET_WEAPON_FIRE_FAILED
    TORPEDO_FIRED,       // (tube, torpedo)        ET_TORPEDO_FIRED
    AMMO_CONSUMED,       // (tube)                 ET_TORPEDO_AMMO_CONSUMED
    TORPEDO_RELOAD,      // (tube)                 ET_TORPEDO_RELOAD
    WATCH,               // (watcher | weapon, old, new)  crossed checks
    SPAWN,               // (launcher, kind, ship, set, module, target,
                         //  position xyz, has velocity, velocity xyz,
                         //  has offset, offset xyz, drf, damage
                         //  scale, fired at)
                         // a launch's spawn (effect_queue._spawn; spec
                         // 2026-11-02-combat-launch-deferral §4.1)
    TRACTOR_STARTED,     // (tractor system, ship)  ET_TRACTOR_BEAM_STARTED_
                         //  FIRING, source the system, destination the
                         //  ship (fire control native only, R8)
    TRACTOR_STOPPED,     // (tractor system, ship)  ET_TRACTOR_BEAM_STOPPED_
                         //  FIRING
    // The damage kinds (spec 2026-11-02-native-damage-design.md M2, §4.3):
    // what a condition write and a hit REPORT, in today's synchronous order
    // minus nesting. Unlike the weapon kinds they are queued in both switch
    // states and, outside the tick scope, held for the next BOUNDARY
    // (effect_queue.boundary), never delivered by a session's end. Their
    // operand layouts are FROZEN (effect_kind_operands; effect_queue.py's
    // OPERANDS and *_FIELDS name each operand):
    COND_WATCH,          // RIDD (subsystem, which CondWatch, old, new)
                         //  crossed checks
    SUBSYS_EVENT,        // RI (subsystem, which SubsysEvent)
                         //  ET_SUBSYSTEM_*; DESTROYED also queues its
                         //  internal blast
    REPAIR_ADD,          // R (subsystem)          AddToRepairList
    ZERO_CROSS,          // RRBH (ship, subsystem, crossed, killer)  the
                         //  boundary death check (death_check._check)
    SPLASH,              // R (ship)               its death splash
    HIT_PRESENT,         // 35 operands: hit_feedback.dispatch's inputs,
                         //  points as xyz (effect_queue.HIT_PRESENT_FIELDS)
    WEAPON_HIT,          // 14 operands: the WeaponHitEvent's fields
                         //  (effect_queue.WEAPON_HIT_FIELDS)
    kCount
};
const char* effect_kind_name(EffectKind k);

// A damage kind's operand layout, one letter per operand:
//   R  a mirror handle (-1 None), resolved at delivery; the entry's SUBJECT
//      (its ship, or a subsystem) is one. A rebind may leave an object.
//   H  an object the entry HOLDS (OwnedObject; -1 for None): a hit's
//      source, a death's killer -- never resolved, never skipped
//   D  a double   I  an int code (EffectInt)   B  a flag (EffectBool)
// nullptr for the weapon kinds (their operands are free-form).
const char* effect_kind_operands(EffectKind k);

// The code operands (effect_queue.py's constants of the same names; the
// binding combat_effect_codes() hands Python effect_codes()).
enum class CondWatch : int { CONDITION = 0, COMBINED = 1 };
enum class SubsysEvent : int { DESTROYED = 0, DISABLED = 1, OPERATIONAL = 2 };
// HIT_PRESENT's sub_transition: the primary subsystem's worst new state.
enum class HitTransition : int { NONE = 0, DISABLED = 1, DESTROYED = 2 };
// HIT_PRESENT's weapon_type (apply_hit's string, dispatch's audio, decal
// and shield-flash routing).
enum class HitWeapon : int {
    NONE = 0, PHASER = 1, TORPEDO = 2, TRACTOR = 3, COLLISION = 4 };
// WEAPON_HIT's weapon_type: the WeaponHitEvent id (events.py).
enum class WeaponHitType : int {
    NON_WEAPON = -1, PHASER = 0, TORPEDO = 1, TRACTOR_BEAM = 2 };

struct EffectCode {
    const char* name;
    int value;
};
std::span<const EffectCode> effect_codes();

struct EffectOperand {
    enum class Type : std::uint8_t { Handle, Number, Object, Int, Bool };
    Type type = Type::Handle;
    union {
        std::int64_t handle = -1;   // Handle
        std::int64_t integer;       // Int
        double number;              // Number
        void* object;               // Object: an owned reference while queued
        bool boolean;               // Bool
    };
};

struct EffectEntry {
    static constexpr int kMaxOperands = 35;   // a spelled HIT_PRESENT
    EffectKind kind = EffectKind::FIRE_SOUND;
    bool native = false;      // appended by a kernel (handles, numbers)
    int count = 0;
    std::array<EffectOperand, kMaxOperands> ops{};
};

// Whether `ops` fit `k`'s layout (effect_kind_operands): the count and the
// type of each (R a handle or an object, H an object or the handle -1). A
// kind with no layout matches anything. A kernel's append asserts it.
bool effect_operands_match(EffectKind k, std::span<const EffectOperand> ops);

// A reference the queue takes over in a kernel entry (released as any
// object operand is).
struct OwnedObject {
    void* object = nullptr;
};

// A kernel's int code (a bare std::int64_t is a mirror handle).
struct EffectInt {
    std::int64_t value = 0;
};

// A kernel's flag.
struct EffectBool {
    bool value = false;
};

// A kernel operand: a mirror handle, a number, an owned object, an int code
// or a flag.
using NativeOperand =
    std::variant<std::int64_t, double, OwnedObject, EffectInt, EffectBool>;

class EffectQueue {
public:
    using Release = void (*)(void*);

    explicit EffectQueue(Release release = nullptr) : release_(release) {}
    EffectQueue(const EffectQueue&) = delete;
    EffectQueue& operator=(const EffectQueue&) = delete;
    ~EffectQueue() { clear(); }

    void set_release(Release release) { release_ = release; }

    // A kernel's entry: handles (std::int64_t), numbers (double), owned
    // objects, int codes (EffectInt) and flags (EffectBool).
    template <class... Ops>
    void append_native(EffectKind kind, Ops... ops) {
        static_assert(sizeof...(Ops) <= EffectEntry::kMaxOperands);
        append_native_list(kind, {NativeOperand(ops)...});
    }
    void append_native_list(EffectKind kind,
                            std::initializer_list<NativeOperand> ops);
    // Any number of operands up to kMaxOperands (a SPAWN).
    void append_native_span(EffectKind kind,
                            std::span<const NativeOperand> ops);
    // A kernel's entry built in place (`e.kind`, `e.count`, `e.ops`, each
    // operand typed as append_native_span would type it): appended with
    // `native` set. The same entry as the span's, without building a
    // NativeOperand per operand (the native damage entries' hot path).
    void append_native_entry(const EffectEntry& e);

    // Python's entry: each pointer a reference the queue now owns (at most
    // kMaxOperands).
    void append_objects(EffectKind kind, std::span<void* const> objs);

    // Every entry, in order; the queue is empty after. The caller owns the
    // object references.
    std::vector<EffectEntry> take();
    // Drop every entry (released).
    void clear();

    // A row about to be unregistered (native_combat._drop: a value the
    // mirror cannot hold) while kernel entries naming it wait: every pending
    // NATIVE operand equal to `handle` becomes `object`, the queue taking
    // one reference per operand through `acquire(object)` (released as any
    // object operand is). -1 (None) is never a row. Returns how many
    // operands were replaced. A row freed instead (the object is gone) has
    // nothing to rebind to: its entries are skipped at delivery.
    std::size_t rebind(std::int64_t handle, void* object,
                       void* (*acquire)(void*));

    std::size_t size() const { return entries_.size(); }
    bool empty() const { return entries_.empty(); }

private:
    Release release_;
    std::vector<EffectEntry> entries_;
};

// The process-wide queue (never destroyed: it may own Python references at
// exit, when releasing them would be too late).
EffectQueue& effect_queue();

}  // namespace dauntless::host
