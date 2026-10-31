#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/profile_eval.h"
#include "dauntless/combat/sensor_state.h"
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
// never as the row that reused its index. kRefUnrepresentable (-2) is
// stored and read back as is.

namespace dauntless::combat {

enum class Kind : int32_t {
    Object = 0, Subsystem, Property, Set, Profile, Ammo, kCount
};

enum class FieldType : int32_t {
    F, I, Ref, Ids, Vec3, Spheres, Rows, IdLists
};

enum class Field : int32_t {
    // Object: constructor data (read-only) and class flags
    xform_index, xform_gen, obj_id,
    has_sensor_getter, has_cloak_getter, is_rock, is_meta_nebula,
    // Object: mirrored attributes
    _dead, _dying, _life_time, _containing_set, o_radius, _scale,
    _sensor_subsystem, _cloaking_subsystem, _hull,
    _fbm, _seed, spheres,
    // Object: weapon-fire inputs (phase 1b K1). has_posed_parts is 1 while
    // a part's current pose is off identity (native_combat._posed_flag);
    // has_real_is_dead is
    // implements(obj, "IsDead"); _velocity is rebound on every SetVelocity.
    has_posed_parts, has_real_is_dead, _velocity,
    _phaser_system, _pulse_weapon_system, _tractor_beam_system, _torpedo_system,
    // Subsystem
    has_parent_ship_getter, _condition, _max_condition, _disabled_percentage,
    _destroyed, _radiation_out, s_radius, _parent_subsystem, _parent_ship,
    _property, _power_factor, _base_sensor_range, _known_objects, _probe_ids,
    _cloak_state,
    // Subsystem: class flags. weapon_kind: 0 none, 1 phaser system, 2 pulse
    // system, 3 tractor system, 4 torpedo system, 5 phaser bank, 6 pulse
    // weapon, 7 tractor beam, 8 torpedo tube.
    weapon_kind, pump_self_managed,
    // k1_overridden: the class overrides a method the K1 kernel stands in
    // for (Fire, CanFire, update_weapons ...); K1 hands its system to Python.
    k1_overridden,
    // Subsystem: PoweredSubsystem
    _is_on,
    // Subsystem: WeaponSystem held-fire state (_target_list holds Object
    // handles in order, _children Subsystem handles in order, _ammo_by_slot
    // interleaved [slot, Ammo handle, slot, Ammo handle, ...] in dict order)
    _fire_held, _held_target, _held_offset, _target_list, _force_update,
    _last_weapon_idx, _last_group_fired, _firing_chain_mode, _group_fire_mode,
    _single_fire, _children,
    // Subsystem: TorpedoSystem (_selected_slot is -1 for None)
    _last_system_fire_time, _selected_slot, _ammo_by_slot,
    // Subsystem: leaf weapons (banks and tubes)
    _fire_timer, _firing, _charge_level, _max_charge, _min_firing_charge,
    _depleted, _normal_discharge_rate, _power_setting, _cooldown_remaining,
    _cooldown_time, _target, _target_offset, _num_ready, _max_ready,
    _last_fire_time, _immediate_delay, _skew_fire,
    // Subsystem: mount geometry and arcs (every subsystem has them)
    _position, _direction, _up, _right, _arc_width_lo, _arc_width_hi,
    _arc_height_lo, _arc_height_hi, _arc_set,
    // Subsystem: pulse projectile module, resolved by Python (ruling P6)
    launch_speed, lifetime, module_ok,
    // Property
    MaxCondition, MaxCondition_set, _firing_chains, _groups,
    // Set
    ships, nebulae, mapped, profile, anchor, star,
    // Profile
    rows, full_concealment,
    // Ammo (TorpedoAmmoType)
    _unlimited, _available,
    kCount
};

// Python attribute name (Object and Subsystem both have a `_radius`).
const char* field_name(Field f);
Kind field_kind(Field f);
FieldType field_type(Field f);

using Vec3 = std::array<double, 3>;

// A ref field's value when the Python referent is not None but the mirror
// cannot name it (an unregistered object: a test fake, a set before it has a
// row). Distinct from -1 (None): the kernel must not read it as "absent" and
// should take the Python path instead. Stored and read back as is.
constexpr int64_t kRefUnrepresentable = -2;

struct ObjectRow {
    int64_t xform_index = -1, xform_gen = -1, obj_id = -1;
    int64_t has_sensor_getter = 0, has_cloak_getter = 0, is_rock = 0,
            is_meta_nebula = 0;
    int64_t _dead = 0, _dying = 0;
    double _life_time = 0.0;
    int64_t _containing_set = -1;
    double _radius = 0.0, _scale = 1.0;
    int64_t _sensor_subsystem = -1, _cloaking_subsystem = -1,
            _hull = -1;
    Vec3 _fbm{0, 0, 0}, _seed{0, 0, 0};
    bool fbm_set = false, seed_set = false;
    std::vector<Sphere> spheres;
    int64_t has_posed_parts = 0, has_real_is_dead = 0;
    Vec3 _velocity{0, 0, 0};
    int64_t _phaser_system = -1, _pulse_weapon_system = -1,
            _tractor_beam_system = -1, _torpedo_system = -1;
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
    int64_t weapon_kind = 0, pump_self_managed = 0, k1_overridden = 0,
            _is_on = 0;
    int64_t _fire_held = 0, _held_target = -1;
    Vec3 _held_offset{0, 0, 0};
    bool held_offset_set = false;
    std::vector<int64_t> _target_list, _children, _ammo_by_slot;
    int64_t _force_update = 0, _last_weapon_idx = 0, _last_group_fired = 0,
            _firing_chain_mode = 0, _group_fire_mode = 0, _single_fire = 0;
    double _last_system_fire_time = 0.0;
    int64_t _selected_slot = -1;
    double _fire_timer = 0.0;
    int64_t _firing = 0;
    double _charge_level = 0.0, _max_charge = 0.0, _min_firing_charge = 0.0;
    int64_t _depleted = 0;
    double _normal_discharge_rate = 0.0;
    int64_t _power_setting = 0;
    double _cooldown_remaining = 0.0, _cooldown_time = 0.0;
    int64_t _target = -1;
    Vec3 _target_offset{0, 0, 0};
    bool target_offset_set = false;
    int64_t _num_ready = 0, _max_ready = 0;
    double _last_fire_time = 0.0, _immediate_delay = 0.0;
    int64_t _skew_fire = 0;
    Vec3 _position{0, 0, 0}, _direction{0, 0, 0}, _up{0, 0, 0},
        _right{0, 0, 0};
    double _arc_width_lo = 0.0, _arc_width_hi = 0.0, _arc_height_lo = 0.0,
           _arc_height_hi = 0.0;
    int64_t _arc_set = 0;
    double launch_speed = 0.0, lifetime = 0.0;
    int64_t module_ok = 0;
};

struct PropertyRow {
    double MaxCondition = 0.0;
    int64_t MaxCondition_set = 0;
    // One group list per chain, in chain (mode) order; the labels are not
    // mirrored. Empty for a property with no chains.
    std::vector<std::vector<int64_t>> _firing_chains;
    int64_t _groups = 0;
};

struct AmmoRow {
    int64_t _unlimited = 0, _available = 0;
};

struct SetRow {
    // Object handles in contact_index order. An entry Python cannot name
    // (a dropped row) is kRefUnrepresentable, keeping its place.
    std::vector<int64_t> ships, nebulae;
    // The RESOLVED profile frame (CDM §9.15): mapped == (profile >= 0).
    // profile is -1 for an unmapped / unresolvable set, kRefUnrepresentable
    // when resolving it raised in Python.
    int64_t mapped = 0;
    int64_t profile = -1;
    Vec3 anchor{0, 0, 0}, star{0, 0, 0};
};

// The scalar dials, flags and module constants can_detect reads, keyed by
// their Python names (engine/appc/native_combat.py push_globals). Python
// pushes every value -- the constants too -- so no number is re-typed here.
enum class Global : int32_t {
    // sensor_dials / dev_nebula_dials (developer dials)
    sensorless_range_gu, cloak_bubble_cap_gu, overboost_threshold,
    min_blocker_radius_gu, conceal_cap,
    // flags (0/1): dev_mode.is_enabled(), sensor_occlusion.enabled(),
    // sensor_detection.ENHANCED_SENSOR_CONTEST
    dev_mode, occ_enabled, enhanced_sensor_contest,
    // sensor_detection module constants (CDM §3 #2)
    CONCEAL_K, LOCK_BREAK_T, HYSTERESIS, PROFILE_CONCEALMENT_CAP,
    CLOAK_RANGE_FACTOR, CLOAK_DETECTION_BASE_GU,
    // weapon_subsystems module constants (phase 1b K1 geometry), pushed from
    // _TORPEDO_CONE_HALF_ANGLE and _PULSE_RANGE_GATE_SECONDS
    TORPEDO_CONE_HALF_ANGLE, PULSE_RANGE_GATE_SECONDS,
    // PULSE_COST_SCALE_BY_POWER_SETTING[0..2] (Task 3, the pulse charge gate)
    PULSE_COST_SCALE_0, PULSE_COST_SCALE_1, PULSE_COST_SCALE_2,
    // The K1 kernel (Task 4): WeaponSystem.FIRE_TIMER_THRESHOLD and the
    // weapon_subsystems module constant PHASER_MAX_RANGE_GU
    FIRE_TIMER_THRESHOLD, PHASER_MAX_RANGE_GU,
    kCount
};

const char* global_name(Global g);
bool global_is_int(Global g);
// Throws std::invalid_argument (Python ValueError) for an unknown name.
Global global_by_name(const std::string& name);

// Zero until Python first pushes (a cleared mirror reads zero too).
struct Globals {
    double sensorless_range_gu = 0.0, cloak_bubble_cap_gu = 0.0,
           overboost_threshold = 0.0, min_blocker_radius_gu = 0.0,
           conceal_cap = 0.0;
    int64_t dev_mode = 0, occ_enabled = 0, enhanced_sensor_contest = 0;
    double CONCEAL_K = 0.0, LOCK_BREAK_T = 0.0, HYSTERESIS = 0.0,
           PROFILE_CONCEALMENT_CAP = 0.0, CLOAK_RANGE_FACTOR = 0.0,
           CLOAK_DETECTION_BASE_GU = 0.0;
    double TORPEDO_CONE_HALF_ANGLE = 0.0, PULSE_RANGE_GATE_SECONDS = 0.0;
    double PULSE_COST_SCALE_0 = 0.0, PULSE_COST_SCALE_1 = 0.0,
           PULSE_COST_SCALE_2 = 0.0;
    double FIRE_TIMER_THRESHOLD = 0.0, PHASER_MAX_RANGE_GU = 0.0;
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
    // Every row and the globals, plus the native-owned SensorState.
    void clear();
    uint64_t epoch() const { return epoch_; }

    // The detection kernel's own state (latch, memo, occlusion caches, probe
    // guard): sensor_detect.h reads and writes it. Not a mirror of Python.
    SensorState& sensor_state() { return sensor_; }
    const SensorState& sensor_state() const { return sensor_; }

    // The live Object handle for a Python object id, or -1.
    int64_t find_by_obj_id(int64_t obj_id) const;

    bool valid(int64_t handle) const;  // live and of any kind
    static Kind kind_of(int64_t handle);

    void set_f(int64_t handle, Field f, double v);
    void set_i(int64_t handle, Field f, int64_t v);
    void set_ref(int64_t handle, Field f, int64_t target_or_minus1);
    void set_ids(int64_t handle, Field f, const std::vector<int64_t>& ids);
    // 3 doubles; an empty vector clears _fbm / _seed / _held_offset /
    // _target_offset to "unset".
    void set_fv(int64_t handle, Field f, const std::vector<double>& v);
    void set_id_lists(int64_t handle, Field f,
                      const std::vector<std::vector<int64_t>>& lists);
    void set_spheres(int64_t handle, std::vector<Sphere> spheres);
    void set_profile_rows(int64_t handle, std::vector<ProfileRow> rows,
                          double full_concealment);
    // A set's resolved frame. `profile`: a live Profile handle (mapped), -1
    // (unmapped) or kRefUnrepresentable; sets `mapped` = profile >= 0.
    void set_frame(int64_t set_handle, int64_t profile, const Vec3& anchor,
                   const Vec3& star);

    // Globals: throw std::invalid_argument on a type mismatch.
    void set_global_f(Global g, double v);
    void set_global_i(Global g, int64_t v);
    double get_global_f(Global g) const;
    int64_t get_global_i(Global g) const;
    const Globals& globals() const { return globals_; }

    // Generic readers (checked handle). Refs are re-checked: stale reads -1;
    // ship / nebula lists drop stale handles and keep kRefUnrepresentable.
    double get_f(int64_t handle, Field f) const;
    int64_t get_i(int64_t handle, Field f) const;
    int64_t get_ref(int64_t handle, Field f) const;
    std::vector<int64_t> get_ids(int64_t handle, Field f) const;
    // Empty for an unset _fbm / _seed.
    std::vector<double> get_fv(int64_t handle, Field f) const;
    std::vector<std::vector<int64_t>> get_id_lists(int64_t handle,
                                                   Field f) const;

    // Typed row access for the kernel: nullptr when the handle is stale,
    // freed or of another kind.
    const ObjectRow* object(int64_t h) const;
    const SubsystemRow* subsystem(int64_t h) const;
    const PropertyRow* property(int64_t h) const;
    const SetRow* set(int64_t h) const;
    const ProfileRowSet* profile(int64_t h) const;
    const AmmoRow* ammo(int64_t h) const;

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

    void clear_owned_state() { sensor_.clear(); }

    const TransformStore& store_;
    Table<ObjectRow> objects_;
    Table<SubsystemRow> subsystems_;
    Table<PropertyRow> properties_;
    Table<SetRow> sets_;
    Table<ProfileRowSet> profiles_;
    Table<AmmoRow> ammo_;
    std::unordered_map<int64_t, int64_t> by_obj_id_;
    Globals globals_;
    SensorState sensor_;
    uint64_t epoch_ = 0;
};

Mirror& mirror();  // process-wide; reads positions from transform_store()

}  // namespace dauntless::combat
