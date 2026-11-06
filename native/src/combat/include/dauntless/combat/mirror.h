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
#include "dauntless/combat/torpedo_table.h"
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
    F, I, Ref, Ids, Vec3, Spheres, Rows, IdLists,
    // An ordered list of doubles (a tube's per-slot reload lists).
    FloatList
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
    // Object: what the K2 beam kernel reads (phase 2). has_real_get_shields is
    // implements(obj, "GetShields"); is_ship_class is isinstance(obj,
    // ShipClass). _manual_target_offset is a TGPoint3 or unset. The hull box
    // is _shield_hull_box = ((cx, cy, cz), (hx, hy, hz)); hull_box_set is 1
    // only for exactly that shape, else 0 and the two vectors read zero.
    has_real_get_shields, is_ship_class, _target_subsystem, _use_target_offset,
    _manual_target_offset, _shield_subsystem, _shield_hull_box_center,
    _shield_hull_box_half, hull_box_set,
    // Subsystem
    has_parent_ship_getter, _condition, _max_condition, _disabled_percentage,
    _destroyed, _radiation_out, s_radius, _parent_subsystem, _parent_ship,
    _property, _power_factor, _base_sensor_range, _known_objects, _probe_ids,
    _cloak_state,
    // Subsystem: class flags. weapon_kind: 0 none, 1 phaser system, 2 pulse
    // system, 3 tractor system, 4 torpedo system, 5 phaser bank, 6 pulse
    // weapon, 7 tractor beam, 8 torpedo tube.
    weapon_kind,
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
    // Subsystem: what K2 reads of a phaser bank (_length, _beam_on_countdown,
    // _dwell) and of a ShieldSubsystem (has_shields = sum(_max_shields) > 0,
    // computed by Python's own HasShields expression).
    _length, _beam_on_countdown, _dwell, has_shields,
    // Subsystem: what the K0 charging kernel reads (native weapon state,
    // Task 3). _recharge_rate (energy weapons); _reload_delay and the per-slot
    // lists _reload_timers / _reload_advanced_at (tubes; written IN PLACE by
    // Python, each writer pushes the whole list after mutating);
    // _watch_checks (a pulse weapon's charge watcher's check count, pushed by
    // every check add/remove); _power_level (a PhaserSystem's, pushed only
    // when it is an index: a float level drops the row); _watch_value (that
    // watcher's `_value`, pushed by every commit of an owned watcher: the
    // old value of K0's WATCH entry, combat fire events Task 4).
    _recharge_rate, _reload_delay, _reload_timers, _reload_advanced_at,
    _watch_checks, _power_level, _watch_value,
    // Property
    MaxCondition, MaxCondition_set, _firing_chains, _groups,
    // Set
    ships, nebulae, mapped, profile, anchor, star,
    // Profile
    rows, full_concealment,
    // Ammo (TorpedoAmmoType)
    _unlimited, _available,
    // The launch deferral (spec 2026-11-02-combat-launch-deferral §4.1):
    // a tube's DamageRadiusFactor (Subsystem; ShipSubsystem's
    // _damage_radius_factor, the launcher's override); whether the ship is
    // sliding onto its warp-in placement (Object; warp_state.is_arriving,
    // FireDumb's hold); the ammo type's capacity (AddAvailable's clamp) and
    // its projectile module's launch as Python resolved it, per script
    // (Ammo; native_combat.push_ammo_launch): ammo_launch_state 0 not
    // cached yet, 1 cached, 2 no module (or no script); ammo_launch_speed
    // its GetLaunchSpeed().
    _damage_radius_factor, arriving, _max_torpedoes, ammo_launch_state,
    ammo_launch_speed,
    // Native damage (spec 2026-11-02-native-damage-design.md §4.1; damage.h
    // reads them). Subsystem: the threshold state machine's state
    // (_threshold_state: 0 operational, 1 disabled, 2 destroyed), the
    // invincible and critical flags, membership of its bay's repair queue
    // (_in_repair_queue, kept by subsystems._RepairQueue), the class's
    // damage rules (dmg_class: native_combat.DMG_*: 0 ShipSubsystem's leaf
    // predicates, 1 WeaponSystem's aggregate ones, -1 a class the chain
    // hands to Python), and each condition watcher's check count
    // (cond_watch_checks for GetConditionWatcher's, comb_watch_checks for
    // GetCombinedPercentageWatcher's: -2 no watcher, -1 one the chain cannot
    // stand in for) and committed `_value`. A ShieldSubsystem's faces:
    // _current_shields and _max_shields (written IN PLACE by Python, each
    // writer pushes the whole list) and the ramp fractions (_ramp_fraction,
    // 0.0 where Python holds None, and _ramp_set 1.0 where it holds a
    // float). Object: _hurtable (IsImmuneToDamage is `not _hurtable`) and
    // dmg_ship (1: a ShipClass whose hit the native chain stands in for).
    _threshold_state, _invincible, _critical, _in_repair_queue, dmg_class,
    cond_watch_checks, comb_watch_checks, cond_watch_value, comb_watch_value,
    _current_shields, _max_shields, _ramp_fraction, _ramp_set,
    _hurtable, dmg_ship,
    // Native damage in the kernels (Task 4): what K2's pulse reads of its
    // phaser bank (_max_damage, _max_damage_distance; its R_hit is
    // _damage_radius_factor above), and the ship's _invincible (o_invincible:
    // a Subsystem field has the name) and death splash (_splash_damage,
    // _splash_damage_radius), mirrored with every other hit input although
    // only Python reads them today (the death check and the splash, at
    // delivery).
    _max_damage, _max_damage_distance, o_invincible, _splash_damage,
    _splash_damage_radius,
    // Tractors native (fire control native only, M4, R7): the force step's
    // ship mass (Object; PhysicsObjectClass._mass, GetMass), a tractor
    // system's mode, firing edge, round-robin cursor and engage state
    // (Subsystem; TractorBeamSystem._mode, _was_firing, _next_emitter_index,
    // and _engage_state as engage_kind 0 None, 1 {"hold_point": p}, 2
    // {"tow_offset": p} with p as engage_point), and a powered system's
    // GetPowerPercentage / GetNormalPowerWanted (Subsystem;
    // PoweredSubsystem._efficiency, _normal_power: K0's holding tractor).
    _mass, _mode, _was_firing, _next_emitter_index, engage_kind, engage_point,
    _efficiency, _normal_power,
    // The SDK weapon routes (fire control native only, M8.2): a torpedo
    // system property's slot-0 script's launch, as an ammo type's
    // (Property; native_combat.push_slot0_launch): the script a tube with no
    // ammo type launches (_spawn_torpedo's `GetTorpedoScript(0)` fallback),
    // 0 not cached yet, 1 cached, 2 no module (or no script); its speed.
    slot0_launch_state, slot0_launch_speed,
    // Kernel M's inputs (native motion phase 2, Task 2), all pushed by
    // Python, which stays the authority. Object: ShipClass._current_speed;
    // four TGPoint3-or-None vectors (ShipClass._current_angular_velocity,
    // _drift_velocity, _target_angular_velocity_setpoint and
    // PhysicsObjectClass._angular_velocity), each with its read-only
    // <name>_state beside it (0 None or absent, 1 a TGPoint3, 2 anything
    // else: unrepresentable, the kernel takes the Python path), written by
    // set_fv from 0, 3 or 4 doubles; _speed_setpoint as a FloatList
    // ([] None, [speed, dx, dy, dz, frame], or 6 zeros: unrepresentable);
    // _angular_space (row default 1, DIRECTION_WORLD_SPACE); _static,
    // _stationary; _insystem_warp_transit (1 while a flight is set);
    // _impulse_engine_subsystem; and motion_stock, a class flag (1: a
    // ShipClass whose motion surface is ShipClass's own). Subsystem:
    // PoweredSubsystem._power_percentage_wanted, ImpulseEngineSubsystem's
    // authored limits, and the class flags motion_ies_stock and
    // motion_pod_stock (native_combat._flags).
    _current_speed, _current_angular_velocity, _drift_velocity,
    _target_angular_velocity_setpoint, _angular_velocity,
    _current_angular_velocity_state, _drift_velocity_state,
    _target_angular_velocity_setpoint_state, _angular_velocity_state,
    _speed_setpoint, _angular_space, _static, _stationary,
    _insystem_warp_transit, _impulse_engine_subsystem, motion_stock,
    _power_percentage_wanted, _max_speed, _max_accel, _max_angular_velocity,
    _max_angular_accel, motion_ies_stock, motion_pod_stock,
    // Object: what PhysicsObjectClass._velocity holds, beside its Vec3 (which
    // every kernel reads, unchanged): 0 never pushed, 1 a TGPoint3 (any
    // 3-double set_fv of _velocity sets it), 2 anything else the Vec3
    // encoding accepts (a tuple; native_combat.VelocityField pushes it).
    // Kernel M's drift reads `v.x` only on a 1.
    _velocity_state,
    // Shields native (phase 6 A1, Task 3; subsystem_step.h THE SHIELD
    // PIECE). Subsystem: ShieldSubsystem._charge_per_second (written IN
    // PLACE by SetShieldChargePerSecond, which pushes the whole list) and
    // _charge_accum; its seven FloatRangeWatchers (_shield_watchers, pushed
    // by native_combat.ShieldWatchersField and by every watcher it adopted:
    // each value committed, each check added or removed) as shield_watch_ok
    // (1: seven stock watchers, each adopted by this generator at its index;
    // 0: anything else, the piece is Python's), shield_watch_values (each
    // watcher's `_value`) and shield_watch_checks (per watcher in order: its
    // check count, then (threshold, direction code) per check; code 1 an
    // upward check (FRW_ABOVE), 2 a downward one (FRW_BELOW), 3 either).
    _charge_per_second, _charge_accum, shield_watch_ok, shield_watch_values,
    shield_watch_checks,
    // Power native (phase 6 A1, Task 4; subsystem_step.h THE POWER PIECE).
    // Object: ShipClass._power_subsystem (the plant whose Update the stage
    // runs) and ShipClass._powered_consumers, the pump's consumers in attach
    // order (Subsystem handles; kRefUnrepresentable for one the mirror
    // cannot name; ShipClass._attach_subsystem pushes it after its append).
    // Subsystem, a plant (PowerSubsystem): its pools, conduit budgets,
    // interval clock, dispensed and wanted totals and breach latch, and
    // its two FloatRangeWatchers (_main_battery_watcher, then
    // _backup_battery_watcher) as power_watch_ok / power_watch_values /
    // power_watch_checks, encoded as the shield generator's seven are.
    // Subsystem, a consumer (PoweredSubsystem): its per-tick demand and
    // receipt (_power_wanted, _power_received), the cloak's reserve
    // snapshot (_backup_reserve), and the class values its draw reads
    // (POWER_MODE, DRAWS_DIRECT_FROM_MAIN, the cloak's
    // CLOAK_RESERVE_DRAIN_PER_SECOND; an instance write pushes, an absent
    // one reads the class's: native_combat.NativeClassDefault). power_kind
    // is a class flag: which power rules the native pump applies to the class
    // (native_combat._power_kind: 0 PoweredSubsystem's, 1 TractorBeamSystem's
    // _wants_power, 2 CloakingSubsystem's, 3 a plant, -1 none of these).
    // Property: the five PowerProperty values PowerSubsystem._prop_f reads
    // every tick, each `float(data-bag value or 0.0)`, and power_props_ok
    // (1: all five read through the data bag, every value a float; 0: the
    // plant's piece is Python's). Pushed on every setter of the five
    // (properties.py), so a shared template's write reaches every plant
    // whose _property names it.
    _power_subsystem, _powered_consumers,
    _available_power, _main_battery_power, _backup_battery_power,
    _main_conduit_current, _backup_conduit_current, _interval_elapsed,
    _power_dispensed, _power_wanted_total, _breach_fired,
    power_watch_ok, power_watch_values, power_watch_checks,
    _power_wanted, _power_received, _backup_reserve,
    POWER_MODE, DRAWS_DIRECT_FROM_MAIN, CLOAK_RESERVE_DRAIN_PER_SECOND,
    power_kind,
    PowerOutput, MainBatteryLimit, BackupBatteryLimit, MainConduitCapacity,
    BackupConduitCapacity, power_props_ok,
    // Cloak and repair native (phase 6 A1, Task 5; subsystem_step.h THE
    // CLOAK PIECE, THE REPAIR PIECE). Object: ShipClass._repair_subsystem
    // (the bay whose Update the stage runs). Subsystem, a cloak
    // (CloakingSubsystem): its transition clock and length. Subsystem, every
    // one: ShipSubsystem._repair_complexity (GetRepairComplexity). Subsystem,
    // a bay (RepairSubsystem): its queue in order (_queue, Subsystem handles,
    // kRefUnrepresentable for a member the mirror cannot name; pushed by
    // subsystems._RepairQueue on every change), the members already told
    // ET_REPAIR_CANNOT_BE_COMPLETED (_cannot_complete_notified, a set of
    // Subsystem handles, sorted and unique), and is_repair_bay, a class
    // flag (1: a RepairSubsystem). Property: the RepairSubsystemProperty
    // values RepairSubsystem reads every tick, as GetMaxRepairPoints
    // (`float(v)`) and GetNumRepairTeams (`int(v)`) answer them (0.0 / 0 for
    // None), and repair_props_ok (1: both read through the data bag, each
    // converted; 0: the bay's piece is Python's). Pushed on every setter of
    // the two (properties.py), so a shared template's write reaches every
    // bay whose _property names it.
    _repair_subsystem, _transition_elapsed, _transition_duration,
    _repair_complexity, _queue, _cannot_complete_notified, is_repair_bay,
    MaxRepairPoints, NumRepairTeams, repair_props_ok,
    // Articulation native (phase 6 A1, Task 6; subsystem_step.h THE
    // ARTICULATION PIECE). Object: the articulated-part generation plus one
    // at which articulation.tick_ship found this ship rigless (its
    // `_rigless_key` early-out), 0 until it did. The piece is skipped iff it
    // equals Global ARTICULATION_GEN + 1.
    _rigless_gen,
    // The motion law (kernel M), pushed by Python. Object: ShipClass.
    // _motion_vel, the velocity vector and the speed it was last stepped to,
    // as a FloatList ([] None, [vx, vy, vz, speed], or 5 zeros:
    // unrepresentable); _target_angular_velocity_fraction, a point-or-none
    // with its _state as the others above (the keyboard turn fraction); and
    // _turn_goal, the stored turn goal's spec (ShipClass._turn_goal,
    // native_combat.TurnGoalField), as a FloatList: [] None; [1, px, py, pz]
    // a "loc" goal; [2, pf(3), pt(3), 0] a "dirs" goal, or [2, pf(3), pt(3),
    // 1, sf(3), st(3)] with its secondaries; [0] unrepresentable (the
    // kernel hands the row to Python). _acceleration, the
    // acceleration the law last commanded (ShipClass._acceleration,
    // GetAccelerationTG), as a FloatList ([] None, [ax, ay, az], or 4
    // zeros: unrepresentable); kernel M writes it back only when its new
    // value differs bitwise.
    _motion_vel, _target_angular_velocity_fraction,
    _target_angular_velocity_fraction_state, _turn_goal, _acceleration,
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

// One entry of a ship's pose table (posed parts, spec 2026-11-01 §4.1): the
// current pose of one name of articulation.posed_part_names(ship), in that
// order. r is Python's R[i][j] at r[3i+j] (row-major, as stored), t the
// translation, ship units, body frame. identity is Python's
// part_pose.is_identity(pose), pushed and never recomputed; detached is
// `name in ship._parts_detached`.
struct PartPose {
    double r[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    double t[3] = {0, 0, 0};
    bool identity = true;
    bool detached = false;
};

struct ObjectRow {
    int64_t xform_index = -1, xform_gen = -1, obj_id = -1;
    // The Python object's id(), written at register and never changed (K3/
    // K4 name objects back to Python by it). Not a Field: read-only, uint64.
    uint64_t py_id = 0;
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
    int64_t has_real_get_shields = 0, is_ship_class = 0;
    int64_t _target_subsystem = -1, _use_target_offset = 0;
    Vec3 _manual_target_offset{0, 0, 0};
    bool manual_offset_set = false;
    int64_t _shield_subsystem = -1;
    Vec3 _shield_hull_box_center{0, 0, 0}, _shield_hull_box_half{0, 0, 0};
    int64_t hull_box_set = 0;
    int64_t arriving = 0;
    // Native damage (Field comment above).
    int64_t _hurtable = 0, dmg_ship = 0;
    int64_t _invincible = 0;
    double _splash_damage = 0.0, _splash_damage_radius = 0.0;
    double _mass = 0.0;  // Tractors native (Field comment above)
    // Kernel M's inputs (Field comment above). A *_state of 0 or 2 leaves
    // its vector zero.
    double _current_speed = 0.0;
    Vec3 _current_angular_velocity{0, 0, 0}, _drift_velocity{0, 0, 0},
        _target_angular_velocity_setpoint{0, 0, 0}, _angular_velocity{0, 0, 0};
    int64_t _current_angular_velocity_state = 0, _drift_velocity_state = 0,
            _target_angular_velocity_setpoint_state = 0,
            _angular_velocity_state = 0;
    std::vector<double> _speed_setpoint;
    int64_t _angular_space = 1, _static = 0, _stationary = 0,
            _insystem_warp_transit = 0;
    int64_t _impulse_engine_subsystem = -1;
    int64_t motion_stock = 0;
    int64_t _velocity_state = 0;
    // The motion law's inputs (Field comment above).
    std::vector<double> _motion_vel;
    Vec3 _target_angular_velocity_fraction{0, 0, 0};
    int64_t _target_angular_velocity_fraction_state = 0;
    std::vector<double> _turn_goal;
    std::vector<double> _acceleration;
    // Posed parts: the pose table (empty while has_posed_parts is 0) and the
    // ship's subsystems in combat._iter_subsystems order (Subsystem handles;
    // kRefUnrepresentable for one the mirror cannot name). Not Fields: set
    // by set_part_poses / set_mount_order, shown by combat_dump.
    std::vector<PartPose> part_poses;
    std::vector<int64_t> mount_order;
    // Power native (Field comment above).
    int64_t _power_subsystem = -1;
    std::vector<int64_t> _powered_consumers;
    // Cloak and repair native (Field comment above).
    int64_t _repair_subsystem = -1;
    // Articulation native (Field comment above).
    int64_t _rigless_gen = 0;
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
    int64_t weapon_kind = 0, _is_on = 0;
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
    // THE OFFSET SOURCE (phase 6 A3; k1_fire_control.h, THE WALK OFFSET).
    // Not a mirror of a Python value: which Python OBJECT a field holds.
    //   held_offset_stamp: a mirror-wide stamp, new on EVERY set_fv of this
    //     row's _held_offset (each Python push -- even of the same value, a
    //     new TGPoint3 -- and each kernel write or undo). 0 for a row whose
    //     _held_offset was never set since it was allocated.
    //   target_offset_src / _stamp: the system whose _held_offset OBJECT
    //     this row's _target_offset holds, and that system's stamp when K1
    //     stamped it (set_target_offset_source); -1: not known. Every
    //     set_fv of _target_offset (a push, any kernel's write or undo)
    //     makes it -1 first.
    // A K1 held walk's stamp is skipped only when the bank's source is the
    // walked system at the stamp its walk object has: the same object.
    uint64_t held_offset_stamp = 0;
    int64_t target_offset_src = -1;
    uint64_t target_offset_src_stamp = 0;
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
    double _length = 0.0, _beam_on_countdown = 0.0, _dwell = 0.0;
    int64_t has_shields = 0;
    // K0's inputs (Field comment above).
    double _recharge_rate = 0.0, _reload_delay = 0.0;
    std::vector<double> _reload_timers, _reload_advanced_at;
    int64_t _watch_checks = 0, _power_level = 0;
    double _watch_value = 0.0;
    double _damage_radius_factor = 0.0;
    // Native damage (Field comment above).
    int64_t _threshold_state = 0, _invincible = 0, _critical = 0,
            _in_repair_queue = 0, dmg_class = 0;
    int64_t cond_watch_checks = -2, comb_watch_checks = -2;
    double cond_watch_value = 0.0, comb_watch_value = 0.0;
    std::vector<double> _current_shields, _max_shields, _ramp_fraction,
        _ramp_set;
    double _max_damage = 0.0, _max_damage_distance = 0.0;
    // Tractors native (Field comment above).
    int64_t _mode = 0, _was_firing = 0, _next_emitter_index = 0,
            engage_kind = 0;
    Vec3 engage_point{0, 0, 0};
    double _efficiency = 0.0, _normal_power = 0.0;
    // Kernel M's inputs (Field comment above).
    double _power_percentage_wanted = 0.0, _max_speed = 0.0, _max_accel = 0.0,
           _max_angular_velocity = 0.0, _max_angular_accel = 0.0;
    int64_t motion_ies_stock = 0, motion_pod_stock = 0;
    // Posed parts: the index into the owning ship's part_poses of the part
    // Python resolved for this subsystem's own mount (detachment ignored;
    // -1 = no posable part), stamped with the global part_gen at
    // resolution. A stamp != Mirror::part_gen() is stale: not resolved.
    int32_t part_slot = -1;
    uint64_t part_gen = 0;
    // Shields native (Field comment above).
    std::vector<double> _charge_per_second, shield_watch_values,
        shield_watch_checks;
    double _charge_accum = 0.0;
    int64_t shield_watch_ok = 0;
    // Power native (Field comment above).
    double _available_power = 0.0, _main_battery_power = 0.0,
           _backup_battery_power = 0.0, _main_conduit_current = 0.0,
           _backup_conduit_current = 0.0, _interval_elapsed = 0.0,
           _power_dispensed = 0.0, _power_wanted_total = 0.0;
    int64_t _breach_fired = 0;
    int64_t power_watch_ok = 0;
    std::vector<double> power_watch_values, power_watch_checks;
    double _power_wanted = 0.0, _power_received = 0.0, _backup_reserve = 0.0;
    int64_t POWER_MODE = 0, DRAWS_DIRECT_FROM_MAIN = 0;
    double CLOAK_RESERVE_DRAIN_PER_SECOND = 0.0;
    int64_t power_kind = -1;
    // Cloak and repair native (Field comment above).
    double _transition_elapsed = 0.0, _transition_duration = 0.0,
           _repair_complexity = 0.0;
    std::vector<int64_t> _queue, _cannot_complete_notified;
    int64_t is_repair_bay = 0;
};

struct PropertyRow {
    double MaxCondition = 0.0;
    int64_t MaxCondition_set = 0;
    // One group list per chain, in chain (mode) order; the labels are not
    // mirrored. Empty for a property with no chains.
    std::vector<std::vector<int64_t>> _firing_chains;
    int64_t _groups = 0;
    int64_t slot0_launch_state = 0;
    double slot0_launch_speed = 0.0;
    // Power native (Field comment above).
    double PowerOutput = 0.0, MainBatteryLimit = 0.0, BackupBatteryLimit = 0.0,
           MainConduitCapacity = 0.0, BackupConduitCapacity = 0.0;
    int64_t power_props_ok = 0;
    // Cloak and repair native (Field comment above).
    double MaxRepairPoints = 0.0;
    int64_t NumRepairTeams = 0, repair_props_ok = 0;
};

struct AmmoRow {
    int64_t _unlimited = 0, _available = 0;
    int64_t _max_torpedoes = 0;
    int64_t ammo_launch_state = 0;
    double ammo_launch_speed = 0.0;
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
    // The K2 kernel (phase 2): weapon_subsystems.BEAM_DWELL_FLUSH_S and
    // combat.SHIELD_ELLIPSOID_AXIS_SCALE
    BEAM_DWELL_FLUSH_S, SHIELD_ELLIPSOID_AXIS_SCALE,
    // The K3 kernel: projectiles._LEAD_ACCEL_K (the guidance lead term)
    LEAD_ACCEL_K,
    // The K0 kernel: weapon_subsystems.PHASER_DISCHARGE_BY_POWER_LEVEL, the
    // phaser bank's drain indexed by its PhaserSystem's power level. Entries
    // 0..2 (0.0 past the table's end) and the table's length, so a kernel
    // can tell an index Python would answer from one it would not.
    PHASER_DISCHARGE_0, PHASER_DISCHARGE_1, PHASER_DISCHARGE_2,
    PHASER_DISCHARGE_LEN,
    // The K1 kernel's beam edge (spec 2026-11-02-combat-fire-events §4.3):
    // weapon_subsystems.BEAM_ON_DELAY_S, the lit bank's beam-on countdown
    BEAM_ON_DELAY_S,
    // A cannon's launch (launch deferral, Task 3): PULSE_DAMAGE_SCALE_BY_
    // POWER_SETTING[0..2] (PulseWeapon.GetDamageScale).
    PULSE_DAMAGE_SCALE_0, PULSE_DAMAGE_SCALE_1, PULSE_DAMAGE_SCALE_2,
    // Tractors native (fire control native only, R7): engine/appc/tractor.py's
    // force constants (TRACTOR_EPS is its _EPS) and weapon_subsystems.
    // TRACTOR_MAX_RANGE_GU, K1's engage range. Python is their one home.
    TRACTOR_REFERENCE_MASS, TRACTOR_REFERENCE_SPEED_GUPS,
    TRACTOR_MAX_SPEED_GUPS, TRACTOR_FALLBACK_MASS, TRACTOR_TOW_DRAG_FRACTION,
    TRACTOR_DOCK_GENTLE_FRACTION, TRACTOR_STANDOFF_MARGIN_GU, TRACTOR_EPS,
    TRACTOR_MAX_RANGE_GU,
    // Shields native (phase 6 A1, Task 3): subsystems.SHIELD_CHARGE_PERIOD_S,
    // the 0.5 s charge cadence.
    SHIELD_CHARGE_PERIOD_S,
    // Power native (phase 6 A1, Task 4): PowerSubsystem.POWER_INTERVAL, the
    // plant's 1.0 s recharge interval.
    POWER_INTERVAL,
    // Cloak native (phase 6 A1, Task 5): CloakingSubsystem.
    // MIN_RESERVE_TO_HOLD_CLOAK, the reserve at or below which a cloak
    // trying to cloak is forced off.
    MIN_RESERVE_TO_HOLD_CLOAK,
    // Articulation native (phase 6 A1, Task 6): articulated_part.generation(),
    // pushed on every bump, so a rig change wakes every ship's tick_ship.
    ARTICULATION_GEN,
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
    int64_t ARTICULATION_GEN = 0;
    double CONCEAL_K = 0.0, LOCK_BREAK_T = 0.0, HYSTERESIS = 0.0,
           PROFILE_CONCEALMENT_CAP = 0.0, CLOAK_RANGE_FACTOR = 0.0,
           CLOAK_DETECTION_BASE_GU = 0.0;
    double TORPEDO_CONE_HALF_ANGLE = 0.0, PULSE_RANGE_GATE_SECONDS = 0.0;
    double PULSE_COST_SCALE_0 = 0.0, PULSE_COST_SCALE_1 = 0.0,
           PULSE_COST_SCALE_2 = 0.0;
    double FIRE_TIMER_THRESHOLD = 0.0, PHASER_MAX_RANGE_GU = 0.0;
    double BEAM_DWELL_FLUSH_S = 0.0, SHIELD_ELLIPSOID_AXIS_SCALE = 0.0;
    double LEAD_ACCEL_K = 0.0;
    double PHASER_DISCHARGE_0 = 0.0, PHASER_DISCHARGE_1 = 0.0,
           PHASER_DISCHARGE_2 = 0.0;
    int64_t PHASER_DISCHARGE_LEN = 0;
    double BEAM_ON_DELAY_S = 0.0;
    double PULSE_DAMAGE_SCALE_0 = 0.0, PULSE_DAMAGE_SCALE_1 = 0.0,
           PULSE_DAMAGE_SCALE_2 = 0.0;
    double TRACTOR_REFERENCE_MASS = 0.0, TRACTOR_REFERENCE_SPEED_GUPS = 0.0,
           TRACTOR_MAX_SPEED_GUPS = 0.0, TRACTOR_FALLBACK_MASS = 0.0,
           TRACTOR_TOW_DRAG_FRACTION = 0.0, TRACTOR_DOCK_GENTLE_FRACTION = 0.0,
           TRACTOR_STANDOFF_MARGIN_GU = 0.0, TRACTOR_EPS = 0.0,
           TRACTOR_MAX_RANGE_GU = 0.0;
    double SHIELD_CHARGE_PERIOD_S = 0.0;
    double POWER_INTERVAL = 0.0;
    double MIN_RESERVE_TO_HOLD_CLOAK = 0.0;
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
                         int64_t xform_gen = -1, int64_t obj_id = -1,
                         uint64_t py_id = 0);
    void unregister_row(int64_t handle);
    // Every row, the torpedo table and the globals, plus the native-owned
    // SensorState.
    void clear();
    uint64_t epoch() const { return epoch_; }

    // The detection kernel's own state (latch, memo, occlusion caches, probe
    // guard): sensor_detect.h reads and writes it. Not a mirror of Python.
    SensorState& sensor_state() { return sensor_; }
    const SensorState& sensor_state() const { return sensor_; }

    // The live Object handle for a Python object id, or -1.
    int64_t find_by_obj_id(int64_t obj_id) const;
    // Whether find_by_obj_id finds Object row `handle` by its obj_id: off
    // while its Python id is unregistered (ids.unregister; the row may wait
    // for a deferred free), on again at ids.register. Throws
    // std::invalid_argument for a stale or non-Object handle.
    void set_obj_id_findable(int64_t handle, bool findable);

    bool valid(int64_t handle) const;  // live and of any kind
    static Kind kind_of(int64_t handle);

    void set_f(int64_t handle, Field f, double v);
    void set_i(int64_t handle, Field f, int64_t v);
    void set_ref(int64_t handle, Field f, int64_t target_or_minus1);
    void set_ids(int64_t handle, Field f, const std::vector<int64_t>& ids);
    // 3 doubles; an empty vector clears _fbm / _seed / _held_offset /
    // _target_offset to "unset". A point-or-none field (kernel M's four
    // vectors) takes 0 (state 0), 3 (state 1) or 4 (state 2, the vector
    // reads zero) doubles and sets its <name>_state.
    void set_fv(int64_t handle, Field f, const std::vector<double>& v);
    // THE OFFSET SOURCE (SubsystemRow): `bank`'s _target_offset now holds
    // system `sys`'s _held_offset object as of `stamp`. Throws
    // std::invalid_argument for a stale or non-Subsystem `bank`.
    void set_target_offset_source(int64_t bank, int64_t sys, uint64_t stamp);
    // Every row's source forgotten (-1): Python may not hold what a kernel
    // stamped (a K1 apply that raised).
    void forget_offset_sources();
    void set_id_lists(int64_t handle, Field f,
                      const std::vector<std::vector<int64_t>>& lists);
    // A FloatList field: the whole list, every bit kept.
    void set_floats(int64_t handle, Field f, const std::vector<double>& v);
    // One element of a FloatList field, in place (the list keeps its
    // storage). std::out_of_range for an index past its end.
    void set_float_at(int64_t handle, Field f, size_t index, double v);
    void set_spheres(int64_t handle, std::vector<Sphere> spheres);
    void set_profile_rows(int64_t handle, std::vector<ProfileRow> rows,
                          double full_concealment);
    // A set's resolved frame. `profile`: a live Profile handle (mapped), -1
    // (unmapped) or kRefUnrepresentable; sets `mapped` = profile >= 0.
    void set_frame(int64_t set_handle, int64_t profile, const Vec3& anchor,
                   const Vec3& star);

    // Posed parts (spec 2026-11-01 §4.1). Each throws std::invalid_argument
    // for a stale or wrong-kind handle. A mount-order entry must be a
    // Subsystem handle or kRefUnrepresentable; a slot is >= -1.
    void set_part_poses(int64_t object, std::vector<PartPose> poses);
    void set_part_slot(int64_t subsystem, int32_t slot, uint64_t gen);
    void set_mount_order(int64_t object, const std::vector<int64_t>& order);
    // The global part-map generation, bumped by Python at every input of the
    // slot resolution. Starts (and clears) at 1, so a never-resolved slot
    // (part_gen 0) reads stale.
    void set_part_gen(uint64_t gen);
    uint64_t part_gen() const { return part_gen_; }

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
    // Empty for an unset _fbm / _seed. A point-or-none field reads by its
    // state: empty (0), its 3 doubles (1), or 4 zeros (2) -- what was set.
    std::vector<double> get_fv(int64_t handle, Field f) const;
    std::vector<std::vector<int64_t>> get_id_lists(int64_t handle,
                                                   Field f) const;
    std::vector<double> get_floats(int64_t handle, Field f) const;

    // Typed row access for the kernel: nullptr when the handle is stale,
    // freed or of another kind.
    const ObjectRow* object(int64_t h) const;
    const SubsystemRow* subsystem(int64_t h) const;
    const PropertyRow* property(int64_t h) const;
    const SetRow* set(int64_t h) const;
    const ProfileRowSet* profile(int64_t h) const;
    const AmmoRow* ammo(int64_t h) const;

    // The K3 torpedo table (torpedo_table.h). Its writes do not bump the
    // epoch: no K1/K2 answer reads a torpedo row.
    TorpedoTable& torpedoes() { return torpedoes_; }
    const TorpedoTable& torpedoes() const { return torpedoes_; }
    // A torpedo ref field (_target_ship / _source_ship: Object,
    // _containing_set: Set). Throws std::invalid_argument for a stale
    // torpedo handle or a live ref of the wrong kind / a stale ref.
    void set_torpedo_ref(int64_t torp, TorpField f, int64_t ref);
    // `_mount_key`: `sub` a Subsystem handle, -1 or kRefUnrepresentable.
    void set_torpedo_mount(int64_t torp, bool attributed, int64_t sub,
                           const Vec3& offset);
    // A torpedo row's ref (the three refs and _mount_key's subsystem),
    // re-checked: a since-freed row reads kRefUnrepresentable (-2), NOT -1
    // as get_ref does -- the torpedo holds its referents strongly, so a dead
    // handle means the referent's row was dropped, not that it is gone.
    int64_t torpedo_ref(const TorpedoRow& row, TorpField f) const;

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
    TorpedoTable torpedoes_;
    Globals globals_;
    SensorState sensor_;
    uint64_t epoch_ = 0;
    uint64_t part_gen_ = 1;
    // SubsystemRow::held_offset_stamp's source: never reused, clear()
    // included.
    uint64_t offset_stamp_ = 0;
};

Mirror& mirror();  // process-wide; reads positions from transform_store()

}  // namespace dauntless::combat
