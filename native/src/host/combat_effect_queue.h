// native/src/host/combat_effect_queue.h
//
// The combat effect queue (spec 2026-11-02-combat-fire-events-design.md
// §4.1-4.2, roadmap decision 6): ONE ordered queue for the weapon events and
// weapon sounds the combat step produces, delivered by Python
// (engine/appc/effect_queue.py) at the tick boundary.
//
// An entry is a kind plus up to three operands, in one emission order
// whoever appends it:
//   a kernel  append_native: mirror handles (-1 = None) and numbers (a
//             watcher's old / new value); no Python call;
//   Python    append_objects (the binding combat_effect_post): object
//             references the queue OWNS until the entry leaves it.
// The lock is held for both (the kernels run under it today).
//
// A kernel whose session is abandoned drops the entries it appended in that
// session: mark() at its start, truncate(mark) at the abandon. Every entry
// appended before the mark stays. A mark names the queue's take generation
// too: a take() or clear() that removed entries between mark and truncate (a
// nested flush delivered the session's entries) makes it stale, and a stale
// truncate drops nothing -- counted (stale_truncates), never guessed at.
//
// OWNERSHIP. The queue never touches Python: an object operand is an opaque
// pointer, released through the Release function the owner installed (the
// bindings install Py_DECREF). truncate and clear release what they drop;
// take hands every entry -- and its references -- to the caller.
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
    kCount
};
const char* effect_kind_name(EffectKind k);

struct EffectOperand {
    enum class Type : std::uint8_t { Handle, Number, Object };
    Type type = Type::Handle;
    std::int64_t handle = -1;
    double number = 0.0;
    void* object = nullptr;   // an owned reference while queued
};

struct EffectEntry {
    static constexpr int kMaxOperands = 3;
    EffectKind kind = EffectKind::FIRE_SOUND;
    bool native = false;      // appended by a kernel (handles, numbers)
    int count = 0;
    std::array<EffectOperand, kMaxOperands> ops{};
};

// A kernel operand: a mirror handle or a number.
using NativeOperand = std::variant<std::int64_t, double>;

// Where a kernel session started (mark()).
struct EffectMark {
    std::uint64_t generation = 0;   // takes + clears before it
    std::size_t index = 0;          // the queue's length then
};

class EffectQueue {
public:
    using Release = void (*)(void*);

    explicit EffectQueue(Release release = nullptr) : release_(release) {}
    EffectQueue(const EffectQueue&) = delete;
    EffectQueue& operator=(const EffectQueue&) = delete;
    ~EffectQueue() { clear(); }

    void set_release(Release release) { release_ = release; }

    // A kernel's entry: handles (std::int64_t) and numbers (double).
    template <class... Ops>
    void append_native(EffectKind kind, Ops... ops) {
        static_assert(sizeof...(Ops) <= EffectEntry::kMaxOperands);
        append_native_list(kind, {NativeOperand(ops)...});
    }
    void append_native_list(EffectKind kind,
                            std::initializer_list<NativeOperand> ops);

    // Python's entry: each pointer a reference the queue now owns (at most
    // kMaxOperands).
    void append_objects(EffectKind kind, std::span<void* const> objs);

    EffectMark mark() const { return {generation_, entries_.size()}; }
    // Drop every entry appended at or after `mark` (released); nothing for
    // a stale mark (counted).
    void truncate(EffectMark mark);
    // Every entry, in order; the queue is empty after. The caller owns the
    // object references.
    std::vector<EffectEntry> take();
    // Drop every entry (released).
    void clear();

    // Truncates that named a stale mark, since the last reset_counts().
    std::uint64_t stale_truncates() const { return stale_truncates_; }
    void reset_counts() { stale_truncates_ = 0; }

    std::size_t size() const { return entries_.size(); }
    bool empty() const { return entries_.empty(); }

private:
    void drop_from(std::size_t index);

    Release release_;
    std::vector<EffectEntry> entries_;
    std::uint64_t generation_ = 0;
    std::uint64_t stale_truncates_ = 0;
};

// The process-wide queue (never destroyed: it may own Python references at
// exit, when releasing them would be too late).
EffectQueue& effect_queue();

}  // namespace dauntless::host
