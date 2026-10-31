#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/profile_eval.h"
#include "dauntless/transform_store.h"

// The native combat mirror: one row per Python object the sensor-detection
// kernel reads (ObjectClass, Subsystem, SubsystemProperty, Set, radial
// Profile). Python keeps the rows in sync by setter calls; the kernel reads
// them with no Python crossing. Every field is named after the Python
// attribute it mirrors (field_name()).
//
// Handles are int64: index | generation << 32 | kind << 60. As in
// TransformStore the generation bumps on free AND on reuse, so a stale handle
// fails at once. A stale or wrong-kind handle throws std::invalid_argument
// (Python ValueError). A reference STORED in a row (a ref field, a ship list)
// is re-checked at read time: a ref to a since-freed row reads as none (-1),
// never as the row that reused its index.

namespace dauntless::combat {

enum class Kind : int32_t { Object = 0, Subsystem, Property, Set, Profile, kCount };

enum class FieldType : int32_t { F, I, Ref, Ids, Vec3, Spheres, Rows };

enum class Field : int32_t {
    // Object: constructor data (read-only) and class flags
    xform_index, xform_gen, obj_id,
    has_sensor_getter, has_cloak_getter, is_rock, is_meta_nebula,
    // Object: mirrored attributes
    _dead, _dying, _life_time, _containing_set, o_radius, _scale,
    _sensor_subsystem, _cloaking_subsystem, _hull_subsystem,
    _fbm, _seed, spheres,
    // Subsystem
    has_parent_ship_getter, _condition, _max_condition, _disabled_percentage,
    _destroyed, _radiation_out, s_radius, _parent_subsystem, _parent_ship,
    _property, _power_factor, _base_sensor_range, _known_objects, _probe_ids,
    _cloak_state,
    // Property
    MaxCondition, MaxCondition_set,
    // Set
    ships, nebulae, mapped, profile, anchor, star,
    // Profile
    rows, full_concealment,
    kCount
};

// Python attribute name (Object and Subsystem both have a `_radius`).
const char* field_name(Field f);
Kind field_kind(Field f);
FieldType field_type(Field f);

using Vec3 = std::array<double, 3>;

struct ObjectRow {
    int64_t xform_index = -1, xform_gen = -1, obj_id = -1;
    int64_t has_sensor_getter = 0, has_cloak_getter = 0, is_rock = 0,
            is_meta_nebula = 0;
    int64_t _dead = 0, _dying = 0;
    double _life_time = 0.0;
    int64_t _containing_set = -1;
    double _radius = 0.0, _scale = 1.0;
    int64_t _sensor_subsystem = -1, _cloaking_subsystem = -1,
            _hull_subsystem = -1;
    Vec3 _fbm{0, 0, 0}, _seed{0, 0, 0};
    bool fbm_set = false, seed_set = false;
    std::vector<Sphere> spheres;
};

struct SubsystemRow {
    int64_t has_parent_ship_getter = 0;
    double _condition = 0.0, _max_condition = 0.0, _disabled_percentage = 0.0;
    int64_t _destroyed = 0, _radiation_out = 0;
    double _radius = 0.0;
    int64_t _parent_subsystem = -1, _parent_ship = -1, _property = -1;
    double _power_factor = 0.0, _base_sensor_range = 0.0;
    std::vector<int64_t> _known_objects;  // sorted, unique (set semantics)
    std::vector<int64_t> _probe_ids;      // list order
    int64_t _cloak_state = 0;
};

struct PropertyRow {
    double MaxCondition = 0.0;
    int64_t MaxCondition_set = 0;
};

struct SetRow {
    std::vector<int64_t> ships, nebulae;  // Object handles, in order
    int64_t mapped = 0;
    int64_t profile = -1;
    Vec3 anchor{0, 0, 0}, star{0, 0, 0};
};

struct ProfileRowSet {
    std::vector<ProfileRow> rows;
    double full_concealment = 0.0;
};

class Mirror {
public:
    explicit Mirror(const TransformStore& store) : store_(store) {}

    const TransformStore& store() const { return store_; }

    int64_t register_row(Kind kind, int64_t xform_index = -1,
                         int64_t xform_gen = -1, int64_t obj_id = -1);
    void unregister_row(int64_t handle);
    void clear();  // every row, plus (Task 5) the native-owned state
    uint64_t epoch() const { return epoch_; }

    // The live Object handle for a Python object id, or -1.
    int64_t find_by_obj_id(int64_t obj_id) const;

    bool valid(int64_t handle) const;  // live and of any kind
    static Kind kind_of(int64_t handle);

    void set_f(int64_t handle, Field f, double v);
    void set_i(int64_t handle, Field f, int64_t v);
    void set_ref(int64_t handle, Field f, int64_t target_or_minus1);
    void set_ids(int64_t handle, Field f, const std::vector<int64_t>& ids);
    // 3 doubles; an empty vector clears _fbm / _seed to "unset".
    void set_fv(int64_t handle, Field f, const std::vector<double>& v);
    void set_spheres(int64_t handle, std::vector<Sphere> spheres);
    void set_profile_rows(int64_t handle, std::vector<ProfileRow> rows,
                          double full_concealment);

    // Generic readers (checked handle). Refs are re-checked: stale reads -1;
    // ship / nebula lists drop stale handles.
    double get_f(int64_t handle, Field f) const;
    int64_t get_i(int64_t handle, Field f) const;
    int64_t get_ref(int64_t handle, Field f) const;
    std::vector<int64_t> get_ids(int64_t handle, Field f) const;
    // Empty for an unset _fbm / _seed.
    std::vector<double> get_fv(int64_t handle, Field f) const;

    // Typed row access for the kernel: nullptr when the handle is stale,
    // freed or of another kind.
    const ObjectRow* object(int64_t h) const;
    const SubsystemRow* subsystem(int64_t h) const;
    const PropertyRow* property(int64_t h) const;
    const SetRow* set(int64_t h) const;
    const ProfileRowSet* profile(int64_t h) const;

private:
    template <class T>
    struct Table {
        std::vector<T> rows;
        std::vector<uint32_t> gen;
        std::vector<uint8_t> live;
        std::vector<uint32_t> free;
    };

    template <class T>
    const T* find(const Table<T>& t, int64_t h, Kind want) const;
    // Throws std::invalid_argument unless `h` is a live handle of `want`.
    template <class T>
    T& checked(Table<T>& t, int64_t h, Kind want);
    template <class T>
    int64_t alloc(Table<T>& t, Kind kind);
    template <class T>
    void release(Table<T>& t, int64_t h);
    template <class T>
    void clear_table(Table<T>& t);
    bool ref_live(int64_t h, Kind want) const;
    // Runs fn(row) on the row `h` names, which must be of kind `want`.
    template <class Fn>
    decltype(auto) visit(int64_t h, Kind want, Fn&& fn);
    template <class Fn>
    decltype(auto) visit(int64_t h, Kind want, Fn&& fn) const;

    void clear_owned_state() {}  // Task 5: latch, occlusion caches, memo

    const TransformStore& store_;
    Table<ObjectRow> objects_;
    Table<SubsystemRow> subsystems_;
    Table<PropertyRow> properties_;
    Table<SetRow> sets_;
    Table<ProfileRowSet> profiles_;
    std::unordered_map<int64_t, int64_t> by_obj_id_;
    uint64_t epoch_ = 0;
};

Mirror& mirror();  // process-wide; reads positions from transform_store()

}  // namespace dauntless::combat
