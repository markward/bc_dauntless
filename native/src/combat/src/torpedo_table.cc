#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/torpedo_table.h"

#include <stdexcept>
#include <string>

namespace dauntless::combat {

namespace {

constexpr const char* kNames[] = {
    "_age", "_ttl", "_guidance_lifetime", "_guidance_initial",
    "_max_angular_accel", "_velocity", "_target_offset",
    "_last_seen_target_pos", "_last_target_vel", "_target_ship",
    "_source_ship", "_containing_set", "_mount_key",
    "_damage", "_damage_radius_factor",
};
static_assert(sizeof(kNames) / sizeof(kNames[0]) ==
              static_cast<size_t>(TorpField::kCount));

uint32_t bit(TorpField f) { return 1u << static_cast<uint32_t>(f); }

[[noreturn]] void bad(const char* what, TorpField f) {
    throw std::invalid_argument(std::string("torpedo table: ") + what +
                                " (field " + torp_field_name(f) + ")");
}

}  // namespace

const char* torp_field_name(TorpField f) {
    auto i = static_cast<int32_t>(f);
    if (i < 0 || i >= static_cast<int32_t>(TorpField::kCount))
        throw std::invalid_argument("torpedo table: unknown field " +
                                    std::to_string(i));
    return kNames[i];
}

int64_t TorpedoTable::add(int64_t xform_index, int64_t xform_gen) {
    TorpedoRow row;
    row.handle = next_++;
    row.xform_index = xform_index;
    row.xform_gen = xform_gen;
    index_.emplace(row.handle, rows_.size());
    rows_.push_back(row);
    return row.handle;
}

bool TorpedoTable::drop(int64_t h) {
    auto it = index_.find(h);
    if (it == index_.end()) return false;
    rows_[it->second].alive = false;
    index_.erase(it);
    ++dead_;
    // As TorpedoScan::remove: compact once tombstones are numerous and the
    // majority, so fire-and-expire churn is amortised O(1) per removal.
    if (dead_ > 64 && dead_ * 2 > rows_.size()) compact();
    return true;
}

void TorpedoTable::clear() {
    rows_.clear();
    index_.clear();
    dead_ = 0;
}

void TorpedoTable::compact() {
    std::size_t out = 0;
    for (std::size_t i = 0; i < rows_.size(); ++i) {
        if (!rows_[i].alive) continue;
        if (out != i) rows_[out] = rows_[i];
        index_[rows_[out].handle] = out;
        ++out;
    }
    rows_.resize(out);
    dead_ = 0;
}

TorpedoRow* TorpedoTable::find(int64_t h) {
    auto it = index_.find(h);
    return it == index_.end() ? nullptr : &rows_[it->second];
}

const TorpedoRow* TorpedoTable::find(int64_t h) const {
    auto it = index_.find(h);
    return it == index_.end() ? nullptr : &rows_[it->second];
}

TorpedoRow& TorpedoTable::checked(int64_t h) {
    TorpedoRow* r = find(h);
    if (!r)
        throw std::invalid_argument("torpedo table: stale or unknown handle " +
                                    std::to_string(h));
    return *r;
}

std::vector<int64_t> TorpedoTable::handles() const {
    std::vector<int64_t> out;
    out.reserve(index_.size());
    for (const TorpedoRow& r : rows_)
        if (r.alive) out.push_back(r.handle);
    return out;
}

void TorpedoTable::set_f(int64_t h, TorpField f, double v) {
    TorpedoRow& r = checked(h);
    switch (f) {
        case TorpField::_age: r.age = v; break;
        case TorpField::_ttl: r.ttl = v; break;
        case TorpField::_guidance_lifetime: r.guidance_lifetime = v; break;
        case TorpField::_guidance_initial: r.guidance_initial = v; break;
        case TorpField::_max_angular_accel: r.max_angular_accel = v; break;
        case TorpField::_damage: r.damage = v; break;
        case TorpField::_damage_radius_factor: r.damage_radius_factor = v; break;
        default: bad("not a double field", f);
    }
    r.unrepresentable &= ~bit(f);
}

void TorpedoTable::set_v(int64_t h, TorpField f, bool is_set, const Vec3& v) {
    TorpedoRow& r = checked(h);
    switch (f) {
        case TorpField::_velocity:
            if (!is_set) bad("the velocity is never unset", f);
            r.vel = v;
            break;
        case TorpField::_target_offset:
            r.target_offset_set = is_set;
            r.target_offset = is_set ? v : Vec3{0, 0, 0};
            break;
        case TorpField::_last_seen_target_pos:
            r.last_seen_set = is_set;
            r.last_seen = is_set ? v : Vec3{0, 0, 0};
            break;
        case TorpField::_last_target_vel:
            r.last_tvel_set = is_set;
            r.last_tvel = is_set ? v : Vec3{0, 0, 0};
            break;
        default: bad("not a 3-vector field", f);
    }
    r.unrepresentable &= ~bit(f);
}

void TorpedoTable::set_ref(int64_t h, TorpField f, int64_t ref) {
    TorpedoRow& r = checked(h);
    switch (f) {
        case TorpField::_target_ship: r.target = ref; break;
        case TorpField::_source_ship: r.source = ref; break;
        case TorpField::_containing_set: r.cset = ref; break;
        default: bad("not a ref field", f);
    }
    r.unrepresentable &= ~bit(f);
}

void TorpedoTable::set_mount(int64_t h, bool attributed, int64_t sub,
                             const Vec3& off) {
    TorpedoRow& r = checked(h);
    r.mount_attributed = attributed;
    r.mount_sub = sub;
    r.mount_offset = off;
    r.unrepresentable &= ~bit(TorpField::_mount_key);
}

void TorpedoTable::set_unrepresentable(int64_t h, TorpField f) {
    torp_field_name(f);  // range check
    checked(h).unrepresentable |= bit(f);
}

}  // namespace dauntless::combat
