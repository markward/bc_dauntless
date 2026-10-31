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
    {"MaxCondition", Kind::Property, FieldType::F},
    {"MaxCondition_set", Kind::Property, FieldType::I},
    {"ships", Kind::Set, FieldType::Ids},
    {"nebulae", Kind::Set, FieldType::Ids},
    {"mapped", Kind::Set, FieldType::I},
    {"profile", Kind::Set, FieldType::Ref},
    {"anchor", Kind::Set, FieldType::Vec3},
    {"star", Kind::Set, FieldType::Vec3},
    {"rows", Kind::Profile, FieldType::Rows},
    {"full_concealment", Kind::Profile, FieldType::F},
};
static_assert(sizeof(kInfo) / sizeof(kInfo[0]) ==
              static_cast<size_t>(Field::kCount));

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
        case Field::_parent_subsystem: return Kind::Subsystem;
        case Field::_parent_ship: return Kind::Object;
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
        default: return nullptr;
    }
}
Vec3* vptr(ObjectRow& r, Field f) {
    switch (f) {
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
        default: return nullptr;
    }
}
int64_t* iptr(SubsystemRow& r, Field f) {
    switch (f) {
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
        default: return nullptr;
    }
}
std::vector<int64_t>* idptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_known_objects: return &r._known_objects;
        case Field::_probe_ids: return &r._probe_ids;
        default: return nullptr;
    }
}

double* fptr(PropertyRow& r, Field f) {
    return f == Field::MaxCondition ? &r.MaxCondition : nullptr;
}
int64_t* iptr(PropertyRow& r, Field f) {
    return f == Field::MaxCondition_set ? &r.MaxCondition_set : nullptr;
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
            break;
        }
        case Kind::Subsystem: checked(subsystems_, h, kind); release(subsystems_, h); break;
        case Kind::Property: checked(properties_, h, kind); release(properties_, h); break;
        case Kind::Set: checked(sets_, h, kind); release(sets_, h); break;
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
    by_obj_id_.clear();
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
    if (f == Field::ships || f == Field::nebulae) {
        for (int64_t x : v)
            if (x < 0 || static_cast<Kind>((x >> 60) & 7) != Kind::Object)
                bad("list entry is not an Object handle", f);
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
    bool nullable = (f == Field::_fbm || f == Field::_seed);
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
    });
    ++epoch_;
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
    if (f == Field::ships || f == Field::nebulae)
        v.erase(std::remove_if(v.begin(), v.end(),
                               [&](int64_t x) {
                                   return !ref_live(x, Kind::Object);
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
        return {(*p)[0], (*p)[1], (*p)[2]};
    });
}

const ObjectRow* Mirror::object(int64_t h) const { return find(objects_, h, Kind::Object); }
const SubsystemRow* Mirror::subsystem(int64_t h) const { return find(subsystems_, h, Kind::Subsystem); }
const PropertyRow* Mirror::property(int64_t h) const { return find(properties_, h, Kind::Property); }
const SetRow* Mirror::set(int64_t h) const { return find(sets_, h, Kind::Set); }
const ProfileRowSet* Mirror::profile(int64_t h) const { return find(profiles_, h, Kind::Profile); }

Mirror& mirror() {
    static Mirror m(transform_store());
    return m;
}

}  // namespace dauntless::combat
