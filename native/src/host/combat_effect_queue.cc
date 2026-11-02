// native/src/host/combat_effect_queue.cc -- see combat_effect_queue.h.
#include "combat_effect_queue.h"

#include <cassert>

namespace dauntless::host {

const char* effect_kind_name(EffectKind k) {
    switch (k) {
    case EffectKind::FIRE_SOUND: return "FIRE_SOUND";
    case EffectKind::LOOP_STOP: return "LOOP_STOP";
    case EffectKind::WEAPON_FIRED: return "WEAPON_FIRED";
    case EffectKind::WEAPON_FIRE_FAILED: return "WEAPON_FIRE_FAILED";
    case EffectKind::TORPEDO_FIRED: return "TORPEDO_FIRED";
    case EffectKind::AMMO_CONSUMED: return "AMMO_CONSUMED";
    case EffectKind::TORPEDO_RELOAD: return "TORPEDO_RELOAD";
    case EffectKind::WATCH: return "WATCH";
    case EffectKind::SPAWN: return "SPAWN";
    case EffectKind::kCount: break;
    }
    return nullptr;
}

void EffectQueue::append_native_list(EffectKind kind,
                                     std::initializer_list<NativeOperand> ops) {
    append_native_span(kind, std::span<const NativeOperand>(ops.begin(),
                                                            ops.size()));
}

void EffectQueue::append_native_span(EffectKind kind,
                                     std::span<const NativeOperand> ops) {
    assert(ops.size() <= EffectEntry::kMaxOperands);
    EffectEntry e;
    e.kind = kind;
    e.native = true;
    for (const NativeOperand& op : ops) {
        EffectOperand& o = e.ops[e.count++];
        if (const auto* h = std::get_if<std::int64_t>(&op)) {
            o.type = EffectOperand::Type::Handle;
            o.handle = *h;
        } else if (const auto* d = std::get_if<double>(&op)) {
            o.type = EffectOperand::Type::Number;
            o.number = *d;
        } else {
            o.type = EffectOperand::Type::Object;
            o.object = std::get<OwnedObject>(op).object;
        }
    }
    entries_.push_back(e);
}

void EffectQueue::append_objects(EffectKind kind, std::span<void* const> objs) {
    assert(objs.size() <= EffectEntry::kMaxOperands);
    EffectEntry e;
    e.kind = kind;
    for (void* obj : objs) {
        EffectOperand& o = e.ops[e.count++];
        o.type = EffectOperand::Type::Object;
        o.object = obj;
    }
    entries_.push_back(e);
}

void EffectQueue::clear() {
    // Detach first: a release may run arbitrary code (a Python finaliser)
    // that must not see half-dropped entries.
    std::vector<EffectEntry> dropped;
    dropped.swap(entries_);
    if (release_ == nullptr) return;
    for (const EffectEntry& e : dropped)
        for (int i = 0; i < e.count; ++i)
            if (e.ops[i].type == EffectOperand::Type::Object)
                release_(e.ops[i].object);
}

std::size_t EffectQueue::rebind(std::int64_t handle, void* object,
                                void* (*acquire)(void*)) {
    if (handle == -1) return 0;  // None names no row
    std::size_t n = 0;
    for (EffectEntry& e : entries_) {
        if (!e.native) continue;
        for (int i = 0; i < e.count; ++i) {
            EffectOperand& o = e.ops[i];
            if (o.type != EffectOperand::Type::Handle || o.handle != handle)
                continue;
            o.type = EffectOperand::Type::Object;
            o.object = acquire(object);
            o.handle = -1;
            ++n;
        }
    }
    return n;
}

std::vector<EffectEntry> EffectQueue::take() {
    std::vector<EffectEntry> out;
    out.swap(entries_);
    return out;
}

EffectQueue& effect_queue() {
    static EffectQueue* q = new EffectQueue();
    return *q;
}

}  // namespace dauntless::host
