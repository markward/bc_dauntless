// native/src/host/combat_effect_queue.cc -- see combat_effect_queue.h.
#include "combat_effect_queue.h"

#include <cassert>
#include <cstring>

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
    case EffectKind::TRACTOR_STARTED: return "TRACTOR_STARTED";
    case EffectKind::TRACTOR_STOPPED: return "TRACTOR_STOPPED";
    case EffectKind::COND_WATCH: return "COND_WATCH";
    case EffectKind::SUBSYS_EVENT: return "SUBSYS_EVENT";
    case EffectKind::REPAIR_ADD: return "REPAIR_ADD";
    case EffectKind::ZERO_CROSS: return "ZERO_CROSS";
    case EffectKind::SPLASH: return "SPLASH";
    case EffectKind::HIT_PRESENT: return "HIT_PRESENT";
    case EffectKind::WEAPON_HIT: return "WEAPON_HIT";
    case EffectKind::kCount: break;
    }
    return nullptr;
}

const char* effect_kind_operands(EffectKind k) {
    switch (k) {
    case EffectKind::COND_WATCH: return "RIDD";
    case EffectKind::SUBSYS_EVENT: return "RI";
    case EffectKind::REPAIR_ADD: return "R";
    case EffectKind::ZERO_CROSS: return "RRBH";
    case EffectKind::SPLASH: return "R";
    case EffectKind::HIT_PRESENT:
        //      ship source has_instances point(3) has_normal normal(3)
        return "RHB" "DDD" "B" "DDD"
        //      damage subsystem absorbed(3) transition weapon radius
               "D" "R" "DDD" "I" "I" "D"
        //      persist_decal allow_structural_wear has_shield_point
        //      shield_point_is_point shield_point(3)
               "B" "B" "B" "B" "DDD"
        //      has_tangent tangent(3) has_decal_radius decal_radius
        //      decal_dent single_impact has_shield_radius shield_radius
               "B" "DDD" "B" "D" "D" "B" "B" "D";
    case EffectKind::WEAPON_HIT:
        //      ship source damage hit_point(3) has_normal normal(3) radius
        //      subsystem weapon_type is_hull_hit
        return "RHD" "DDD" "B" "DDD" "D" "R" "I" "B";
    default: return nullptr;
    }
}

namespace {

constexpr EffectCode kCodes[] = {
    {"WATCH_CONDITION", static_cast<int>(CondWatch::CONDITION)},
    {"WATCH_COMBINED", static_cast<int>(CondWatch::COMBINED)},
    {"SUBSYS_DESTROYED", static_cast<int>(SubsysEvent::DESTROYED)},
    {"SUBSYS_DISABLED", static_cast<int>(SubsysEvent::DISABLED)},
    {"SUBSYS_OPERATIONAL", static_cast<int>(SubsysEvent::OPERATIONAL)},
    {"TRANSITION_NONE", static_cast<int>(HitTransition::NONE)},
    {"TRANSITION_DISABLED", static_cast<int>(HitTransition::DISABLED)},
    {"TRANSITION_DESTROYED", static_cast<int>(HitTransition::DESTROYED)},
    {"HIT_WEAPON_NONE", static_cast<int>(HitWeapon::NONE)},
    {"HIT_WEAPON_PHASER", static_cast<int>(HitWeapon::PHASER)},
    {"HIT_WEAPON_TORPEDO", static_cast<int>(HitWeapon::TORPEDO)},
    {"HIT_WEAPON_TRACTOR", static_cast<int>(HitWeapon::TRACTOR)},
    {"HIT_WEAPON_COLLISION", static_cast<int>(HitWeapon::COLLISION)},
    {"WEAPON_HIT_NON_WEAPON", static_cast<int>(WeaponHitType::NON_WEAPON)},
    {"WEAPON_HIT_PHASER", static_cast<int>(WeaponHitType::PHASER)},
    {"WEAPON_HIT_TORPEDO", static_cast<int>(WeaponHitType::TORPEDO)},
    {"WEAPON_HIT_TRACTOR_BEAM", static_cast<int>(WeaponHitType::TRACTOR_BEAM)},
};

}  // namespace

std::span<const EffectCode> effect_codes() { return kCodes; }

bool effect_operands_match(EffectKind k, std::span<const EffectOperand> ops) {
    const char* layout = effect_kind_operands(k);
    if (layout == nullptr) return true;
    if (std::strlen(layout) != ops.size()) return false;
    using T = EffectOperand::Type;
    for (std::size_t i = 0; i < ops.size(); ++i) {
        const EffectOperand& o = ops[i];
        bool ok = false;
        switch (layout[i]) {
        case 'R': ok = o.type == T::Handle || o.type == T::Object; break;
        case 'H':
            ok = o.type == T::Object || (o.type == T::Handle && o.handle == -1);
            break;
        case 'D': ok = o.type == T::Number; break;
        case 'I': ok = o.type == T::Int; break;
        case 'B': ok = o.type == T::Bool; break;
        }
        if (!ok) return false;
    }
    return true;
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
        } else if (const auto* n = std::get_if<EffectInt>(&op)) {
            o.type = EffectOperand::Type::Int;
            o.integer = n->value;
        } else if (const auto* f = std::get_if<EffectBool>(&op)) {
            o.type = EffectOperand::Type::Bool;
            o.boolean = f->value;
        } else {
            o.type = EffectOperand::Type::Object;
            o.object = std::get<OwnedObject>(op).object;
        }
    }
    assert(effect_operands_match(
        kind, std::span<const EffectOperand>(e.ops.data(), e.count)));
    entries_.push_back(e);
}

void EffectQueue::append_native_entry(const EffectEntry& e) {
    assert(e.count >= 0 && e.count <= EffectEntry::kMaxOperands);
    assert(effect_operands_match(
        e.kind, std::span<const EffectOperand>(e.ops.data(), e.count)));
    entries_.push_back(e);
    entries_.back().native = true;
}

void EffectQueue::append_objects(EffectKind kind, std::span<void* const> objs) {
    assert(objs.size() <= EffectEntry::kMaxOperands);
    assert(effect_kind_operands(kind) == nullptr ||
           std::strlen(effect_kind_operands(kind)) == objs.size());
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
            o.object = acquire(object);   // replaces the handle (a union)
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
