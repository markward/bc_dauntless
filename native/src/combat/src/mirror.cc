#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/mirror.h"

#include <algorithm>
#include <string>

namespace dauntless::combat {

namespace {

struct FieldInfo {
    const char* name;
    Kind kind;
    FieldType type;
};

// Indexed by Field.
constexpr FieldInfo kInfo[] = {
    {"xform_index", Kind::Object, FieldType::I},
    {"xform_gen", Kind::Object, FieldType::I},
    {"obj_id", Kind::Object, FieldType::I},
    {"has_sensor_getter", Kind::Object, FieldType::I},
    {"has_cloak_getter", Kind::Object, FieldType::I},
    {"is_rock", Kind::Object, FieldType::I},
    {"is_meta_nebula", Kind::Object, FieldType::I},
    {"_dead", Kind::Object, FieldType::I},
    {"_dying", Kind::Object, FieldType::I},
    {"_life_time", Kind::Object, FieldType::F},
    {"_containing_set", Kind::Object, FieldType::Ref},
    {"_radius", Kind::Object, FieldType::F},
    {"_scale", Kind::Object, FieldType::F},
    {"_sensor_subsystem", Kind::Object, FieldType::Ref},
    {"_cloaking_subsystem", Kind::Object, FieldType::Ref},
    {"_hull", Kind::Object, FieldType::Ref},
    {"_fbm", Kind::Object, FieldType::Vec3},
    {"_seed", Kind::Object, FieldType::Vec3},
    {"spheres", Kind::Object, FieldType::Spheres},
    {"has_posed_parts", Kind::Object, FieldType::I},
    {"has_real_is_dead", Kind::Object, FieldType::I},
    {"_velocity", Kind::Object, FieldType::Vec3},
    {"_phaser_system", Kind::Object, FieldType::Ref},
    {"_pulse_weapon_system", Kind::Object, FieldType::Ref},
    {"_tractor_beam_system", Kind::Object, FieldType::Ref},
    {"_torpedo_system", Kind::Object, FieldType::Ref},
    {"has_parent_ship_getter", Kind::Subsystem, FieldType::I},
    {"_condition", Kind::Subsystem, FieldType::F},
    {"_max_condition", Kind::Subsystem, FieldType::F},
    {"_disabled_percentage", Kind::Subsystem, FieldType::F},
    {"_destroyed", Kind::Subsystem, FieldType::I},
    {"_radiation_out", Kind::Subsystem, FieldType::I},
    {"_radius", Kind::Subsystem, FieldType::F},
    {"_parent_subsystem", Kind::Subsystem, FieldType::Ref},
    {"_parent_ship", Kind::Subsystem, FieldType::Ref},
    {"_property", Kind::Subsystem, FieldType::Ref},
    {"_power_factor", Kind::Subsystem, FieldType::F},
    {"_base_sensor_range", Kind::Subsystem, FieldType::F},
    {"_known_objects", Kind::Subsystem, FieldType::Ids},
    {"_probe_ids", Kind::Subsystem, FieldType::Ids},
    {"_cloak_state", Kind::Subsystem, FieldType::I},
    {"weapon_kind", Kind::Subsystem, FieldType::I},
    {"pump_self_managed", Kind::Subsystem, FieldType::I},
    {"_is_on", Kind::Subsystem, FieldType::I},
    {"_fire_held", Kind::Subsystem, FieldType::I},
    {"_held_target", Kind::Subsystem, FieldType::Ref},
    {"_held_offset", Kind::Subsystem, FieldType::Vec3},
    {"_target_list", Kind::Subsystem, FieldType::Ids},
    {"_force_update", Kind::Subsystem, FieldType::I},
    {"_last_weapon_idx", Kind::Subsystem, FieldType::I},
    {"_last_group_fired", Kind::Subsystem, FieldType::I},
    {"_firing_chain_mode", Kind::Subsystem, FieldType::I},
    {"_group_fire_mode", Kind::Subsystem, FieldType::I},
    {"_single_fire", Kind::Subsystem, FieldType::I},
    {"_children", Kind::Subsystem, FieldType::Ids},
    {"_last_system_fire_time", Kind::Subsystem, FieldType::F},
    {"_selected_slot", Kind::Subsystem, FieldType::I},
    {"_ammo_by_slot", Kind::Subsystem, FieldType::Ids},
    {"_fire_timer", Kind::Subsystem, FieldType::F},
    {"_firing", Kind::Subsystem, FieldType::I},
    {"_charge_level", Kind::Subsystem, FieldType::F},
    {"_max_charge", Kind::Subsystem, FieldType::F},
    {"_min_firing_charge", Kind::Subsystem, FieldType::F},
    {"_depleted", Kind::Subsystem, FieldType::I},
    {"_normal_discharge_rate", Kind::Subsystem, FieldType::F},
    {"_power_setting", Kind::Subsystem, FieldType::I},
    {"_cooldown_remaining", Kind::Subsystem, FieldType::F},
    {"_cooldown_time", Kind::Subsystem, FieldType::F},
    {"_target", Kind::Subsystem, FieldType::Ref},
    {"_target_offset", Kind::Subsystem, FieldType::Vec3},
    {"_num_ready", Kind::Subsystem, FieldType::I},
    {"_max_ready", Kind::Subsystem, FieldType::I},
    {"_last_fire_time", Kind::Subsystem, FieldType::F},
    {"_immediate_delay", Kind::Subsystem, FieldType::F},
    {"_skew_fire", Kind::Subsystem, FieldType::I},
    {"_position", Kind::Subsystem, FieldType::Vec3},
    {"_direction", Kind::Subsystem, FieldType::Vec3},
    {"_up", Kind::Subsystem, FieldType::Vec3},
    {"_right", Kind::Subsystem, FieldType::Vec3},
    {"_arc_width_lo", Kind::Subsystem, FieldType::F},
    {"_arc_width_hi", Kind::Subsystem, FieldType::F},
    {"_arc_height_lo", Kind::Subsystem, FieldType::F},
    {"_arc_height_hi", Kind::Subsystem, FieldType::F},
    {"_arc_set", Kind::Subsystem, FieldType::I},
    {"launch_speed", Kind::Subsystem, FieldType::F},
    {"lifetime", Kind::Subsystem, FieldType::F},
    {"module_ok", Kind::Subsystem, FieldType::I},
    {"MaxCondition", Kind::Property, FieldType::F},
    {"MaxCondition_set", Kind::Property, FieldType::I},
    {"_firing_chains", Kind::Property, FieldType::IdLists},
    {"_groups", Kind::Property, FieldType::I},
    {"ships", Kind::Set, FieldType::Ids},
    {"nebulae", Kind::Set, FieldType::Ids},
    {"mapped", Kind::Set, FieldType::I},
    {"profile", Kind::Set, FieldType::Ref},
    {"anchor", Kind::Set, FieldType::Vec3},
    {"star", Kind::Set, FieldType::Vec3},
    {"rows", Kind::Profile, FieldType::Rows},
    {"full_concealment", Kind::Profile, FieldType::F},
    {"_unlimited", Kind::Ammo, FieldType::I},
    {"_available", Kind::Ammo, FieldType::I},
};
static_assert(sizeof(kInfo) / sizeof(kInfo[0]) ==
              static_cast<size_t>(Field::kCount));

struct GlobalInfo {
    const char* name;
    bool is_int;
    double Globals::*f;
    int64_t Globals::*i;
};

// Indexed by Global.
constexpr GlobalInfo kGlobals[] = {
    {"sensorless_range_gu", false, &Globals::sensorless_range_gu, nullptr},
    {"cloak_bubble_cap_gu", false, &Globals::cloak_bubble_cap_gu, nullptr},
    {"overboost_threshold", false, &Globals::overboost_threshold, nullptr},
    {"min_blocker_radius_gu", false, &Globals::min_blocker_radius_gu, nullptr},
    {"conceal_cap", false, &Globals::conceal_cap, nullptr},
    {"dev_mode", true, nullptr, &Globals::dev_mode},
    {"occ_enabled", true, nullptr, &Globals::occ_enabled},
    {"enhanced_sensor_contest", true, nullptr,
     &Globals::enhanced_sensor_contest},
    {"CONCEAL_K", false, &Globals::CONCEAL_K, nullptr},
    {"LOCK_BREAK_T", false, &Globals::LOCK_BREAK_T, nullptr},
    {"HYSTERESIS", false, &Globals::HYSTERESIS, nullptr},
    {"PROFILE_CONCEALMENT_CAP", false, &Globals::PROFILE_CONCEALMENT_CAP,
     nullptr},
    {"CLOAK_RANGE_FACTOR", false, &Globals::CLOAK_RANGE_FACTOR, nullptr},
    {"CLOAK_DETECTION_BASE_GU", false, &Globals::CLOAK_DETECTION_BASE_GU,
     nullptr},
    {"TORPEDO_CONE_HALF_ANGLE", false, &Globals::TORPEDO_CONE_HALF_ANGLE,
     nullptr},
    {"PULSE_RANGE_GATE_SECONDS", false, &Globals::PULSE_RANGE_GATE_SECONDS,
     nullptr},
    {"PULSE_COST_SCALE_0", false, &Globals::PULSE_COST_SCALE_0, nullptr},
    {"PULSE_COST_SCALE_1", false, &Globals::PULSE_COST_SCALE_1, nullptr},
    {"PULSE_COST_SCALE_2", false, &Globals::PULSE_COST_SCALE_2, nullptr},
};
static_assert(sizeof(kGlobals) / sizeof(kGlobals[0]) ==
              static_cast<size_t>(Global::kCount));

const GlobalInfo& ginfo(Global g) {
    auto i = static_cast<int32_t>(g);
    if (i < 0 || i >= static_cast<int32_t>(Global::kCount))
        throw std::invalid_argument("combat mirror: unknown global " +
                                    std::to_string(i));
    return kGlobals[i];
}

const FieldInfo& info(Field f) {
    auto i = static_cast<int32_t>(f);
    if (i < 0 || i >= static_cast<int32_t>(Field::kCount))
        throw std::invalid_argument("combat mirror: unknown field " +
                                    std::to_string(i));
    return kInfo[i];
}

Kind ref_target_kind(Field f) {
    switch (f) {
        case Field::_containing_set: return Kind::Set;
        case Field::_sensor_subsystem:
        case Field::_cloaking_subsystem:
        case Field::_hull:
        case Field::_parent_subsystem:
        case Field::_phaser_system:
        case Field::_pulse_weapon_system:
        case Field::_tractor_beam_system:
        case Field::_torpedo_system: return Kind::Subsystem;
        case Field::_parent_ship:
        case Field::_held_target:
        case Field::_target: return Kind::Object;
        case Field::_property: return Kind::Property;
        case Field::profile: return Kind::Profile;
        default: return Kind::kCount;
    }
}

bool read_only(Field f) {
    return f == Field::xform_index || f == Field::xform_gen ||
           f == Field::obj_id;
}

// Per-row-type field lookups; the generic overloads find nothing.
template <class R> double* fptr(R&, Field) { return nullptr; }
template <class R> int64_t* iptr(R&, Field) { return nullptr; }
template <class R> int64_t* rptr(R&, Field) { return nullptr; }
template <class R> std::vector<int64_t>* idptr(R&, Field) { return nullptr; }
template <class R> Vec3* vptr(R&, Field) { return nullptr; }

double* fptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_life_time: return &r._life_time;
        case Field::o_radius: return &r._radius;
        case Field::_scale: return &r._scale;
        default: return nullptr;
    }
}
int64_t* iptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::has_posed_parts: return &r.has_posed_parts;
        case Field::has_real_is_dead: return &r.has_real_is_dead;
        case Field::xform_index: return &r.xform_index;
        case Field::xform_gen: return &r.xform_gen;
        case Field::obj_id: return &r.obj_id;
        case Field::has_sensor_getter: return &r.has_sensor_getter;
        case Field::has_cloak_getter: return &r.has_cloak_getter;
        case Field::is_rock: return &r.is_rock;
        case Field::is_meta_nebula: return &r.is_meta_nebula;
        case Field::_dead: return &r._dead;
        case Field::_dying: return &r._dying;
        default: return nullptr;
    }
}
int64_t* rptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_containing_set: return &r._containing_set;
        case Field::_sensor_subsystem: return &r._sensor_subsystem;
        case Field::_cloaking_subsystem: return &r._cloaking_subsystem;
        case Field::_hull: return &r._hull;
        case Field::_phaser_system: return &r._phaser_system;
        case Field::_pulse_weapon_system: return &r._pulse_weapon_system;
        case Field::_tractor_beam_system: return &r._tractor_beam_system;
        case Field::_torpedo_system: return &r._torpedo_system;
        default: return nullptr;
    }
}
Vec3* vptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_velocity: return &r._velocity;
        case Field::_fbm: return &r._fbm;
        case Field::_seed: return &r._seed;
        default: return nullptr;
    }
}

double* fptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_condition: return &r._condition;
        case Field::_max_condition: return &r._max_condition;
        case Field::_disabled_percentage: return &r._disabled_percentage;
        case Field::s_radius: return &r._radius;
        case Field::_power_factor: return &r._power_factor;
        case Field::_base_sensor_range: return &r._base_sensor_range;
        case Field::_last_system_fire_time: return &r._last_system_fire_time;
        case Field::_fire_timer: return &r._fire_timer;
        case Field::_charge_level: return &r._charge_level;
        case Field::_max_charge: return &r._max_charge;
        case Field::_min_firing_charge: return &r._min_firing_charge;
        case Field::_normal_discharge_rate: return &r._normal_discharge_rate;
        case Field::_cooldown_remaining: return &r._cooldown_remaining;
        case Field::_cooldown_time: return &r._cooldown_time;
        case Field::_last_fire_time: return &r._last_fire_time;
        case Field::_immediate_delay: return &r._immediate_delay;
        case Field::_arc_width_lo: return &r._arc_width_lo;
        case Field::_arc_width_hi: return &r._arc_width_hi;
        case Field::_arc_height_lo: return &r._arc_height_lo;
        case Field::_arc_height_hi: return &r._arc_height_hi;
        case Field::launch_speed: return &r.launch_speed;
        case Field::lifetime: return &r.lifetime;
        default: return nullptr;
    }
}
int64_t* iptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::weapon_kind: return &r.weapon_kind;
        case Field::pump_self_managed: return &r.pump_self_managed;
        case Field::_is_on: return &r._is_on;
        case Field::_fire_held: return &r._fire_held;
        case Field::_force_update: return &r._force_update;
        case Field::_last_weapon_idx: return &r._last_weapon_idx;
        case Field::_last_group_fired: return &r._last_group_fired;
        case Field::_firing_chain_mode: return &r._firing_chain_mode;
        case Field::_group_fire_mode: return &r._group_fire_mode;
        case Field::_single_fire: return &r._single_fire;
        case Field::_selected_slot: return &r._selected_slot;
        case Field::_firing: return &r._firing;
        case Field::_depleted: return &r._depleted;
        case Field::_power_setting: return &r._power_setting;
        case Field::_num_ready: return &r._num_ready;
        case Field::_max_ready: return &r._max_ready;
        case Field::_skew_fire: return &r._skew_fire;
        case Field::_arc_set: return &r._arc_set;
        case Field::module_ok: return &r.module_ok;
        case Field::has_parent_ship_getter: return &r.has_parent_ship_getter;
        case Field::_destroyed: return &r._destroyed;
        case Field::_radiation_out: return &r._radiation_out;
        case Field::_cloak_state: return &r._cloak_state;
        default: return nullptr;
    }
}
int64_t* rptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_parent_subsystem: return &r._parent_subsystem;
        case Field::_parent_ship: return &r._parent_ship;
        case Field::_property: return &r._property;
        case Field::_held_target: return &r._held_target;
        case Field::_target: return &r._target;
        default: return nullptr;
    }
}
std::vector<int64_t>* idptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_known_objects: return &r._known_objects;
        case Field::_probe_ids: return &r._probe_ids;
        case Field::_target_list: return &r._target_list;
        case Field::_children: return &r._children;
        case Field::_ammo_by_slot: return &r._ammo_by_slot;
        default: return nullptr;
    }
}
Vec3* vptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_held_offset: return &r._held_offset;
        case Field::_target_offset: return &r._target_offset;
        case Field::_position: return &r._position;
        case Field::_direction: return &r._direction;
        case Field::_up: return &r._up;
        case Field::_right: return &r._right;
        default: return nullptr;
    }
}

double* fptr(PropertyRow& r, Field f) {
    return f == Field::MaxCondition ? &r.MaxCondition : nullptr;
}
int64_t* iptr(PropertyRow& r, Field f) {
    switch (f) {
        case Field::MaxCondition_set: return &r.MaxCondition_set;
        case Field::_groups: return &r._groups;
        default: return nullptr;
    }
}

int64_t* iptr(AmmoRow& r, Field f) {
    switch (f) {
        case Field::_unlimited: return &r._unlimited;
        case Field::_available: return &r._available;
        default: return nullptr;
    }
}

int64_t* iptr(SetRow& r, Field f) {
    return f == Field::mapped ? &r.mapped : nullptr;
}
int64_t* rptr(SetRow& r, Field f) {
    return f == Field::profile ? &r.profile : nullptr;
}
std::vector<int64_t>* idptr(SetRow& r, Field f) {
    switch (f) {
        case Field::ships: return &r.ships;
        case Field::nebulae: return &r.nebulae;
        default: return nullptr;
    }
}
Vec3* vptr(SetRow& r, Field f) {
    switch (f) {
        case Field::anchor: return &r.anchor;
        case Field::star: return &r.star;
        default: return nullptr;
    }
}

double* fptr(ProfileRowSet& r, Field f) {
    return f == Field::full_concealment ? &r.full_concealment : nullptr;
}

[[noreturn]] void bad(const char* what, Field f) {
    throw std::invalid_argument(std::string("combat mirror: ") + what +
                                " (field " + info(f).name + ")");
}

constexpr int64_t kIndexMask = 0xFFFFFFFFLL;
constexpr uint32_t kGenMask = 0x0FFFFFFFu;

int64_t make_handle(uint32_t index, uint32_t gen, Kind kind) {
    return static_cast<int64_t>(index) |
           (static_cast<int64_t>(gen & kGenMask) << 32) |
           (static_cast<int64_t>(kind) << 60);
}

}  // namespace

const char* field_name(Field f) { return info(f).name; }
const char* global_name(Global g) { return ginfo(g).name; }
bool global_is_int(Global g) { return ginfo(g).is_int; }
Global global_by_name(const std::string& name) {
    for (int i = 0; i < static_cast<int>(Global::kCount); ++i)
        if (name == kGlobals[i].name) return static_cast<Global>(i);
    throw std::invalid_argument("combat mirror: unknown global '" + name + "'");
}
Kind field_kind(Field f) { return info(f).kind; }
FieldType field_type(Field f) { return info(f).type; }

Kind Mirror::kind_of(int64_t h) {
    if (h < 0) throw std::invalid_argument("combat mirror: bad handle");
    auto k = static_cast<int32_t>((h >> 60) & 7);
    if (k >= static_cast<int32_t>(Kind::kCount))
        throw std::invalid_argument("combat mirror: bad handle kind");
    return static_cast<Kind>(k);
}

template <class T>
const T* Mirror::find(const Table<T>& t, int64_t h, Kind want) const {
    if (h < 0 || static_cast<Kind>((h >> 60) & 7) != want) return nullptr;
    auto index = static_cast<size_t>(h & kIndexMask);
    if (index >= t.rows.size() || !t.live[index]) return nullptr;
    if ((t.gen[index] & kGenMask) != static_cast<uint32_t>((h >> 32) & kGenMask))
        return nullptr;
    return &t.rows[index];
}

template <class T>
T& Mirror::checked(Table<T>& t, int64_t h, Kind want) {
    const T* p = find(t, h, want);
    if (!p)
        throw std::invalid_argument(
            "combat mirror: stale, freed or wrong-kind handle " +
            std::to_string(h));
    return const_cast<T&>(*p);
}

template <class T>
int64_t Mirror::alloc(Table<T>& t, Kind kind) {
    uint32_t index;
    if (!t.free.empty()) {
        index = t.free.back();
        t.free.pop_back();
        t.rows[index] = T{};
        t.gen[index] += 1;  // bump on reuse as well as on free
        t.live[index] = 1;
    } else {
        index = static_cast<uint32_t>(t.rows.size());
        t.rows.emplace_back();
        t.gen.push_back(0);
        t.live.push_back(1);
    }
    return make_handle(index, t.gen[index], kind);
}

template <class T>
void Mirror::release(Table<T>& t, int64_t h) {
    auto index = static_cast<uint32_t>(h & kIndexMask);
    t.rows[index] = T{};
    t.live[index] = 0;
    t.gen[index] += 1;
    t.free.push_back(index);
}

template <class T>
void Mirror::clear_table(Table<T>& t) {
    t.free.clear();
    for (size_t i = 0; i < t.rows.size(); ++i) {
        if (t.live[i]) {
            t.rows[i] = T{};
            t.live[i] = 0;
            t.gen[i] += 1;
        }
        t.free.push_back(static_cast<uint32_t>(i));
    }
}

template <class Fn>
decltype(auto) Mirror::visit(int64_t h, Kind want, Fn&& fn) {
    switch (want) {
        case Kind::Object: return fn(checked(objects_, h, want));
        case Kind::Subsystem: return fn(checked(subsystems_, h, want));
        case Kind::Property: return fn(checked(properties_, h, want));
        case Kind::Set: return fn(checked(sets_, h, want));
        case Kind::Ammo: return fn(checked(ammo_, h, want));
        default: return fn(checked(profiles_, h, want));
    }
}
template <class Fn>
decltype(auto) Mirror::visit(int64_t h, Kind want, Fn&& fn) const {
    return const_cast<Mirror*>(this)->visit(h, want, std::forward<Fn>(fn));
}

bool Mirror::ref_live(int64_t h, Kind want) const {
    switch (want) {
        case Kind::Object: return find(objects_, h, want) != nullptr;
        case Kind::Subsystem: return find(subsystems_, h, want) != nullptr;
        case Kind::Property: return find(properties_, h, want) != nullptr;
        case Kind::Set: return find(sets_, h, want) != nullptr;
        case Kind::Ammo: return find(ammo_, h, want) != nullptr;
        default: return find(profiles_, h, want) != nullptr;
    }
}

bool Mirror::valid(int64_t h) const {
    if (h < 0) return false;
    auto k = static_cast<int32_t>((h >> 60) & 7);
    if (k >= static_cast<int32_t>(Kind::kCount)) return false;
    return ref_live(h, static_cast<Kind>(k));
}

int64_t Mirror::register_row(Kind kind, int64_t xform_index, int64_t xform_gen,
                             int64_t obj_id) {
    int64_t h;
    switch (kind) {
        case Kind::Object: {
            h = alloc(objects_, kind);
            ObjectRow& r = objects_.rows[h & kIndexMask];
            r.xform_index = xform_index;
            r.xform_gen = xform_gen;
            r.obj_id = obj_id;
            if (obj_id >= 0) by_obj_id_[obj_id] = h;
            break;
        }
        case Kind::Subsystem: h = alloc(subsystems_, kind); break;
        case Kind::Property: h = alloc(properties_, kind); break;
        case Kind::Set: h = alloc(sets_, kind); break;
        case Kind::Profile: h = alloc(profiles_, kind); break;
        case Kind::Ammo: h = alloc(ammo_, kind); break;
        default: throw std::invalid_argument("combat mirror: bad kind");
    }
    ++epoch_;
    return h;
}

void Mirror::unregister_row(int64_t h) {
    Kind kind = kind_of(h);
    switch (kind) {
        case Kind::Object: {
            const ObjectRow& r = checked(objects_, h, kind);
            auto it = by_obj_id_.find(r.obj_id);
            if (it != by_obj_id_.end() && it->second == h) by_obj_id_.erase(it);
            release(objects_, h);
            sensor_.drop_object(h);
            break;
        }
        case Kind::Subsystem:
            checked(subsystems_, h, kind);
            release(subsystems_, h);
            sensor_.drop_mounts_of(h);
            break;
        case Kind::Property: checked(properties_, h, kind); release(properties_, h); break;
        case Kind::Set:
            checked(sets_, h, kind);
            release(sets_, h);
            sensor_.drop_set(h);
            break;
        case Kind::Ammo: checked(ammo_, h, kind); release(ammo_, h); break;
        default: checked(profiles_, h, kind); release(profiles_, h); break;
    }
    ++epoch_;
}

void Mirror::clear() {
    clear_table(objects_);
    clear_table(subsystems_);
    clear_table(properties_);
    clear_table(sets_);
    clear_table(profiles_);
    clear_table(ammo_);
    by_obj_id_.clear();
    globals_ = Globals{};
    clear_owned_state();
    ++epoch_;
}

int64_t Mirror::find_by_obj_id(int64_t obj_id) const {
    auto it = by_obj_id_.find(obj_id);
    if (it == by_obj_id_.end()) return -1;
    return find(objects_, it->second, Kind::Object) ? it->second : -1;
}

void Mirror::set_f(int64_t h, Field f, double v) {
    if (info(f).type != FieldType::F) bad("not a double field", f);
    visit(h, info(f).kind, [&](auto& row) {
        double* p = fptr(row, f);
        if (!p) bad("field not on this row", f);
        *p = v;
    });
    ++epoch_;
}

void Mirror::set_i(int64_t h, Field f, int64_t v) {
    if (info(f).type != FieldType::I) bad("not an int field", f);
    if (read_only(f)) bad("read-only (constructor data)", f);
    visit(h, info(f).kind, [&](auto& row) {
        int64_t* p = iptr(row, f);
        if (!p) bad("field not on this row", f);
        *p = v;
    });
    ++epoch_;
}

void Mirror::set_ref(int64_t h, Field f, int64_t target) {
    if (info(f).type != FieldType::Ref) bad("not a ref field", f);
    if (target != -1 && target != kRefUnrepresentable) {
        Kind tk = ref_target_kind(f);
        if (!ref_live(target, tk)) bad("ref target stale or wrong kind", f);
    }
    visit(h, info(f).kind, [&](auto& row) {
        int64_t* p = rptr(row, f);
        if (!p) bad("field not on this row", f);
        *p = target;
    });
    ++epoch_;
}

void Mirror::set_ids(int64_t h, Field f, const std::vector<int64_t>& ids) {
    if (info(f).type != FieldType::Ids) bad("not an id-list field", f);
    std::vector<int64_t> v = ids;
    auto entries_are = [&](Kind want) {
        for (int64_t x : v)
            if (x != kRefUnrepresentable &&
                (x < 0 || static_cast<Kind>((x >> 60) & 7) != want))
                bad("list entry is not a handle of the field's kind", f);
    };
    if (f == Field::ships || f == Field::nebulae || f == Field::_target_list) {
        entries_are(Kind::Object);
    } else if (f == Field::_children) {
        entries_are(Kind::Subsystem);
    } else if (f == Field::_ammo_by_slot) {
        // [slot, Ammo handle] pairs, in dict order.
        if (v.size() % 2 != 0) bad("expected [slot, handle] pairs", f);
        for (size_t i = 1; i < v.size(); i += 2)
            if (v[i] != kRefUnrepresentable &&
                (v[i] < 0 || static_cast<Kind>((v[i] >> 60) & 7) != Kind::Ammo))
                bad("list entry is not an Ammo handle", f);
    } else if (f == Field::_known_objects) {
        std::sort(v.begin(), v.end());
        v.erase(std::unique(v.begin(), v.end()), v.end());
    }
    visit(h, info(f).kind, [&](auto& row) {
        auto* p = idptr(row, f);
        if (!p) bad("field not on this row", f);
        *p = std::move(v);
    });
    ++epoch_;
}

void Mirror::set_fv(int64_t h, Field f, const std::vector<double>& v) {
    if (info(f).type != FieldType::Vec3) bad("not a 3-vector field", f);
    bool nullable = (f == Field::_fbm || f == Field::_seed ||
                     f == Field::_held_offset || f == Field::_target_offset);
    if (!(v.size() == 3 || (nullable && v.empty())))
        bad("expected 3 doubles", f);
    visit(h, info(f).kind, [&](auto& row) {
        Vec3* p = vptr(row, f);
        if (!p) bad("field not on this row", f);
        if (!v.empty()) *p = {v[0], v[1], v[2]};
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, ObjectRow>) {
            if (f == Field::_fbm) row.fbm_set = !v.empty();
            if (f == Field::_seed) row.seed_set = !v.empty();
        }
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, SubsystemRow>) {
            if (f == Field::_held_offset) row.held_offset_set = !v.empty();
            if (f == Field::_target_offset) row.target_offset_set = !v.empty();
        }
    });
    ++epoch_;
}

void Mirror::set_id_lists(int64_t h, Field f,
                          const std::vector<std::vector<int64_t>>& lists) {
    if (info(f).type != FieldType::IdLists) bad("not an id-lists field", f);
    PropertyRow& row = checked(properties_, h, Kind::Property);
    if (f != Field::_firing_chains) bad("field not on this row", f);
    row._firing_chains = lists;
    ++epoch_;
}

std::vector<std::vector<int64_t>> Mirror::get_id_lists(int64_t h,
                                                       Field f) const {
    if (info(f).type != FieldType::IdLists) bad("not an id-lists field", f);
    const PropertyRow* row = find(properties_, h, Kind::Property);
    if (!row)
        throw std::invalid_argument(
            "combat mirror: stale, freed or wrong-kind handle " +
            std::to_string(h));
    if (f != Field::_firing_chains) bad("field not on this row", f);
    return row->_firing_chains;
}

void Mirror::set_spheres(int64_t h, std::vector<Sphere> spheres) {
    checked(objects_, h, Kind::Object).spheres = std::move(spheres);
    ++epoch_;
}

void Mirror::set_profile_rows(int64_t h, std::vector<ProfileRow> rows,
                              double full_concealment) {
    ProfileRowSet& p = checked(profiles_, h, Kind::Profile);
    p.rows = std::move(rows);
    p.full_concealment = full_concealment;
    ++epoch_;
}

void Mirror::set_frame(int64_t h, int64_t profile, const Vec3& anchor,
                       const Vec3& star) {
    SetRow& r = checked(sets_, h, Kind::Set);
    if (profile != -1 && profile != kRefUnrepresentable &&
        !ref_live(profile, Kind::Profile))
        bad("ref target stale or wrong kind", Field::profile);
    r.profile = profile;
    r.mapped = profile >= 0 ? 1 : 0;
    r.anchor = anchor;
    r.star = star;
    ++epoch_;
}

void Mirror::set_global_f(Global g, double v) {
    const GlobalInfo& gi = ginfo(g);
    if (gi.is_int)
        throw std::invalid_argument(std::string("combat mirror: global ") +
                                    gi.name + " is an int");
    globals_.*(gi.f) = v;
    ++epoch_;
}

void Mirror::set_global_i(Global g, int64_t v) {
    const GlobalInfo& gi = ginfo(g);
    if (!gi.is_int)
        throw std::invalid_argument(std::string("combat mirror: global ") +
                                    gi.name + " is a double");
    globals_.*(gi.i) = v;
    ++epoch_;
}

double Mirror::get_global_f(Global g) const {
    const GlobalInfo& gi = ginfo(g);
    if (gi.is_int)
        throw std::invalid_argument(std::string("combat mirror: global ") +
                                    gi.name + " is an int");
    return globals_.*(gi.f);
}

int64_t Mirror::get_global_i(Global g) const {
    const GlobalInfo& gi = ginfo(g);
    if (!gi.is_int)
        throw std::invalid_argument(std::string("combat mirror: global ") +
                                    gi.name + " is a double");
    return globals_.*(gi.i);
}

double Mirror::get_f(int64_t h, Field f) const {
    if (info(f).type != FieldType::F) bad("not a double field", f);
    return visit(h, info(f).kind, [&](auto& row) {
        double* p = fptr(row, f);
        if (!p) bad("field not on this row", f);
        return *p;
    });
}

int64_t Mirror::get_i(int64_t h, Field f) const {
    if (info(f).type != FieldType::I) bad("not an int field", f);
    return visit(h, info(f).kind, [&](auto& row) {
        int64_t* p = iptr(row, f);
        if (!p) bad("field not on this row", f);
        return *p;
    });
}

int64_t Mirror::get_ref(int64_t h, Field f) const {
    if (info(f).type != FieldType::Ref) bad("not a ref field", f);
    int64_t t = visit(h, info(f).kind, [&](auto& row) {
        int64_t* p = rptr(row, f);
        if (!p) bad("field not on this row", f);
        return *p;
    });
    if (t == kRefUnrepresentable) return t;
    return (t >= 0 && ref_live(t, ref_target_kind(f))) ? t : -1;
}

std::vector<int64_t> Mirror::get_ids(int64_t h, Field f) const {
    if (info(f).type != FieldType::Ids) bad("not an id-list field", f);
    std::vector<int64_t> v = visit(h, info(f).kind, [&](auto& row) {
        auto* p = idptr(row, f);
        if (!p) bad("field not on this row", f);
        return *p;
    });
    // A list entry whose row was since freed is dropped, as a stale ref reads
    // none; an unrepresentable (-2) entry keeps its place.
    Kind entry = Kind::kCount;
    if (f == Field::ships || f == Field::nebulae || f == Field::_target_list)
        entry = Kind::Object;
    else if (f == Field::_children)
        entry = Kind::Subsystem;
    if (entry != Kind::kCount)
        v.erase(std::remove_if(v.begin(), v.end(),
                               [&](int64_t x) {
                                   return x != kRefUnrepresentable &&
                                          !ref_live(x, entry);
                               }),
                v.end());
    return v;
}

std::vector<double> Mirror::get_fv(int64_t h, Field f) const {
    if (info(f).type != FieldType::Vec3) bad("not a 3-vector field", f);
    return visit(h, info(f).kind, [&](auto& row) -> std::vector<double> {
        Vec3* p = vptr(row, f);
        if (!p) bad("field not on this row", f);
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, ObjectRow>) {
            if ((f == Field::_fbm && !row.fbm_set) ||
                (f == Field::_seed && !row.seed_set))
                return {};
        }
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, SubsystemRow>) {
            if ((f == Field::_held_offset && !row.held_offset_set) ||
                (f == Field::_target_offset && !row.target_offset_set))
                return {};
        }
        return {(*p)[0], (*p)[1], (*p)[2]};
    });
}

const ObjectRow* Mirror::object(int64_t h) const { return find(objects_, h, Kind::Object); }
const SubsystemRow* Mirror::subsystem(int64_t h) const { return find(subsystems_, h, Kind::Subsystem); }
const PropertyRow* Mirror::property(int64_t h) const { return find(properties_, h, Kind::Property); }
const SetRow* Mirror::set(int64_t h) const { return find(sets_, h, Kind::Set); }
const ProfileRowSet* Mirror::profile(int64_t h) const { return find(profiles_, h, Kind::Profile); }
const AmmoRow* Mirror::ammo(int64_t h) const { return find(ammo_, h, Kind::Ammo); }

Mirror& mirror() {
    static Mirror m(transform_store());
    return m;
}

}  // namespace dauntless::combat
