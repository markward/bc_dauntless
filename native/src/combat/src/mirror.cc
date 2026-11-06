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
    {"has_real_get_shields", Kind::Object, FieldType::I},
    {"is_ship_class", Kind::Object, FieldType::I},
    {"_target_subsystem", Kind::Object, FieldType::Ref},
    {"_use_target_offset", Kind::Object, FieldType::I},
    {"_manual_target_offset", Kind::Object, FieldType::Vec3},
    {"_shield_subsystem", Kind::Object, FieldType::Ref},
    {"_shield_hull_box_center", Kind::Object, FieldType::Vec3},
    {"_shield_hull_box_half", Kind::Object, FieldType::Vec3},
    {"hull_box_set", Kind::Object, FieldType::I},
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
    {"_length", Kind::Subsystem, FieldType::F},
    {"_beam_on_countdown", Kind::Subsystem, FieldType::F},
    {"_dwell", Kind::Subsystem, FieldType::F},
    {"has_shields", Kind::Subsystem, FieldType::I},
    {"_recharge_rate", Kind::Subsystem, FieldType::F},
    {"_reload_delay", Kind::Subsystem, FieldType::F},
    {"_reload_timers", Kind::Subsystem, FieldType::FloatList},
    {"_reload_advanced_at", Kind::Subsystem, FieldType::FloatList},
    {"_watch_checks", Kind::Subsystem, FieldType::I},
    {"_power_level", Kind::Subsystem, FieldType::I},
    {"_watch_value", Kind::Subsystem, FieldType::F},
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
    {"_damage_radius_factor", Kind::Subsystem, FieldType::F},
    {"arriving", Kind::Object, FieldType::I},
    {"_max_torpedoes", Kind::Ammo, FieldType::I},
    {"ammo_launch_state", Kind::Ammo, FieldType::I},
    {"ammo_launch_speed", Kind::Ammo, FieldType::F},
    {"_threshold_state", Kind::Subsystem, FieldType::I},
    {"_invincible", Kind::Subsystem, FieldType::I},
    {"_critical", Kind::Subsystem, FieldType::I},
    {"_in_repair_queue", Kind::Subsystem, FieldType::I},
    {"dmg_class", Kind::Subsystem, FieldType::I},
    {"cond_watch_checks", Kind::Subsystem, FieldType::I},
    {"comb_watch_checks", Kind::Subsystem, FieldType::I},
    {"cond_watch_value", Kind::Subsystem, FieldType::F},
    {"comb_watch_value", Kind::Subsystem, FieldType::F},
    {"_current_shields", Kind::Subsystem, FieldType::FloatList},
    {"_max_shields", Kind::Subsystem, FieldType::FloatList},
    {"_ramp_fraction", Kind::Subsystem, FieldType::FloatList},
    {"_ramp_set", Kind::Subsystem, FieldType::FloatList},
    {"_hurtable", Kind::Object, FieldType::I},
    {"dmg_ship", Kind::Object, FieldType::I},
    {"_max_damage", Kind::Subsystem, FieldType::F},
    {"_max_damage_distance", Kind::Subsystem, FieldType::F},
    {"_invincible", Kind::Object, FieldType::I},
    {"_splash_damage", Kind::Object, FieldType::F},
    {"_splash_damage_radius", Kind::Object, FieldType::F},
    {"_mass", Kind::Object, FieldType::F},
    {"_mode", Kind::Subsystem, FieldType::I},
    {"_was_firing", Kind::Subsystem, FieldType::I},
    {"_next_emitter_index", Kind::Subsystem, FieldType::I},
    {"engage_kind", Kind::Subsystem, FieldType::I},
    {"engage_point", Kind::Subsystem, FieldType::Vec3},
    {"_efficiency", Kind::Subsystem, FieldType::F},
    {"_normal_power", Kind::Subsystem, FieldType::F},
    {"slot0_launch_state", Kind::Property, FieldType::I},
    {"slot0_launch_speed", Kind::Property, FieldType::F},
    {"_current_speed", Kind::Object, FieldType::F},
    {"_current_angular_velocity", Kind::Object, FieldType::Vec3},
    {"_drift_velocity", Kind::Object, FieldType::Vec3},
    {"_target_angular_velocity_setpoint", Kind::Object, FieldType::Vec3},
    {"_angular_velocity", Kind::Object, FieldType::Vec3},
    {"_current_angular_velocity_state", Kind::Object, FieldType::I},
    {"_drift_velocity_state", Kind::Object, FieldType::I},
    {"_target_angular_velocity_setpoint_state", Kind::Object, FieldType::I},
    {"_angular_velocity_state", Kind::Object, FieldType::I},
    {"_speed_setpoint", Kind::Object, FieldType::FloatList},
    {"_angular_space", Kind::Object, FieldType::I},
    {"_static", Kind::Object, FieldType::I},
    {"_stationary", Kind::Object, FieldType::I},
    {"_insystem_warp_transit", Kind::Object, FieldType::I},
    {"_impulse_engine_subsystem", Kind::Object, FieldType::Ref},
    {"motion_stock", Kind::Object, FieldType::I},
    {"_power_percentage_wanted", Kind::Subsystem, FieldType::F},
    {"_max_speed", Kind::Subsystem, FieldType::F},
    {"_max_accel", Kind::Subsystem, FieldType::F},
    {"_max_angular_velocity", Kind::Subsystem, FieldType::F},
    {"_max_angular_accel", Kind::Subsystem, FieldType::F},
    {"motion_ies_stock", Kind::Subsystem, FieldType::I},
    {"motion_pod_stock", Kind::Subsystem, FieldType::I},
    {"_velocity_state", Kind::Object, FieldType::I},
    {"_charge_per_second", Kind::Subsystem, FieldType::FloatList},
    {"_charge_accum", Kind::Subsystem, FieldType::F},
    {"shield_watch_ok", Kind::Subsystem, FieldType::I},
    {"shield_watch_values", Kind::Subsystem, FieldType::FloatList},
    {"shield_watch_checks", Kind::Subsystem, FieldType::FloatList},
    {"_power_subsystem", Kind::Object, FieldType::Ref},
    {"_powered_consumers", Kind::Object, FieldType::Ids},
    {"_available_power", Kind::Subsystem, FieldType::F},
    {"_main_battery_power", Kind::Subsystem, FieldType::F},
    {"_backup_battery_power", Kind::Subsystem, FieldType::F},
    {"_main_conduit_current", Kind::Subsystem, FieldType::F},
    {"_backup_conduit_current", Kind::Subsystem, FieldType::F},
    {"_interval_elapsed", Kind::Subsystem, FieldType::F},
    {"_power_dispensed", Kind::Subsystem, FieldType::F},
    {"_power_wanted_total", Kind::Subsystem, FieldType::F},
    {"_breach_fired", Kind::Subsystem, FieldType::I},
    {"power_watch_ok", Kind::Subsystem, FieldType::I},
    {"power_watch_values", Kind::Subsystem, FieldType::FloatList},
    {"power_watch_checks", Kind::Subsystem, FieldType::FloatList},
    {"_power_wanted", Kind::Subsystem, FieldType::F},
    {"_power_received", Kind::Subsystem, FieldType::F},
    {"_backup_reserve", Kind::Subsystem, FieldType::F},
    {"POWER_MODE", Kind::Subsystem, FieldType::I},
    {"DRAWS_DIRECT_FROM_MAIN", Kind::Subsystem, FieldType::I},
    {"CLOAK_RESERVE_DRAIN_PER_SECOND", Kind::Subsystem, FieldType::F},
    {"power_kind", Kind::Subsystem, FieldType::I},
    {"PowerOutput", Kind::Property, FieldType::F},
    {"MainBatteryLimit", Kind::Property, FieldType::F},
    {"BackupBatteryLimit", Kind::Property, FieldType::F},
    {"MainConduitCapacity", Kind::Property, FieldType::F},
    {"BackupConduitCapacity", Kind::Property, FieldType::F},
    {"power_props_ok", Kind::Property, FieldType::I},
    {"_repair_subsystem", Kind::Object, FieldType::Ref},
    {"_transition_elapsed", Kind::Subsystem, FieldType::F},
    {"_transition_duration", Kind::Subsystem, FieldType::F},
    {"_repair_complexity", Kind::Subsystem, FieldType::F},
    {"_queue", Kind::Subsystem, FieldType::Ids},
    {"_cannot_complete_notified", Kind::Subsystem, FieldType::Ids},
    {"is_repair_bay", Kind::Subsystem, FieldType::I},
    {"MaxRepairPoints", Kind::Property, FieldType::F},
    {"NumRepairTeams", Kind::Property, FieldType::I},
    {"repair_props_ok", Kind::Property, FieldType::I},
    {"_rigless_gen", Kind::Object, FieldType::I},
    {"_motion_vel", Kind::Object, FieldType::FloatList},
    {"_target_angular_velocity_fraction", Kind::Object, FieldType::Vec3},
    {"_target_angular_velocity_fraction_state", Kind::Object, FieldType::I},
    {"_turn_goal", Kind::Object, FieldType::FloatList},
    {"_acceleration", Kind::Object, FieldType::FloatList},
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
    {"FIRE_TIMER_THRESHOLD", false, &Globals::FIRE_TIMER_THRESHOLD, nullptr},
    {"PHASER_MAX_RANGE_GU", false, &Globals::PHASER_MAX_RANGE_GU, nullptr},
    {"BEAM_DWELL_FLUSH_S", false, &Globals::BEAM_DWELL_FLUSH_S, nullptr},
    {"SHIELD_ELLIPSOID_AXIS_SCALE", false,
     &Globals::SHIELD_ELLIPSOID_AXIS_SCALE, nullptr},
    {"LEAD_ACCEL_K", false, &Globals::LEAD_ACCEL_K, nullptr},
    {"PHASER_DISCHARGE_0", false, &Globals::PHASER_DISCHARGE_0, nullptr},
    {"PHASER_DISCHARGE_1", false, &Globals::PHASER_DISCHARGE_1, nullptr},
    {"PHASER_DISCHARGE_2", false, &Globals::PHASER_DISCHARGE_2, nullptr},
    {"PHASER_DISCHARGE_LEN", true, nullptr, &Globals::PHASER_DISCHARGE_LEN},
    {"BEAM_ON_DELAY_S", false, &Globals::BEAM_ON_DELAY_S, nullptr},
    {"PULSE_DAMAGE_SCALE_0", false, &Globals::PULSE_DAMAGE_SCALE_0, nullptr},
    {"PULSE_DAMAGE_SCALE_1", false, &Globals::PULSE_DAMAGE_SCALE_1, nullptr},
    {"PULSE_DAMAGE_SCALE_2", false, &Globals::PULSE_DAMAGE_SCALE_2, nullptr},
    {"TRACTOR_REFERENCE_MASS", false, &Globals::TRACTOR_REFERENCE_MASS,
     nullptr},
    {"TRACTOR_REFERENCE_SPEED_GUPS", false,
     &Globals::TRACTOR_REFERENCE_SPEED_GUPS, nullptr},
    {"TRACTOR_MAX_SPEED_GUPS", false, &Globals::TRACTOR_MAX_SPEED_GUPS,
     nullptr},
    {"TRACTOR_FALLBACK_MASS", false, &Globals::TRACTOR_FALLBACK_MASS, nullptr},
    {"TRACTOR_TOW_DRAG_FRACTION", false, &Globals::TRACTOR_TOW_DRAG_FRACTION,
     nullptr},
    {"TRACTOR_DOCK_GENTLE_FRACTION", false,
     &Globals::TRACTOR_DOCK_GENTLE_FRACTION, nullptr},
    {"TRACTOR_STANDOFF_MARGIN_GU", false,
     &Globals::TRACTOR_STANDOFF_MARGIN_GU, nullptr},
    {"TRACTOR_EPS", false, &Globals::TRACTOR_EPS, nullptr},
    {"TRACTOR_MAX_RANGE_GU", false, &Globals::TRACTOR_MAX_RANGE_GU, nullptr},
    {"SHIELD_CHARGE_PERIOD_S", false, &Globals::SHIELD_CHARGE_PERIOD_S,
     nullptr},
    {"POWER_INTERVAL", false, &Globals::POWER_INTERVAL, nullptr},
    {"MIN_RESERVE_TO_HOLD_CLOAK", false, &Globals::MIN_RESERVE_TO_HOLD_CLOAK,
     nullptr},
    {"ARTICULATION_GEN", true, nullptr, &Globals::ARTICULATION_GEN},
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
        case Field::_torpedo_system:
        case Field::_target_subsystem:
        case Field::_shield_subsystem:
        case Field::_power_subsystem:
        case Field::_repair_subsystem:
        case Field::_impulse_engine_subsystem: return Kind::Subsystem;
        case Field::_parent_ship:
        case Field::_held_target:
        case Field::_target: return Kind::Object;
        case Field::_property: return Kind::Property;
        case Field::profile: return Kind::Profile;
        default: return Kind::kCount;
    }
}

// Kernel M's point-or-none vectors: set_fv also sets their <name>_state.
bool point_or_none(Field f) {
    return f == Field::_current_angular_velocity ||
           f == Field::_drift_velocity ||
           f == Field::_target_angular_velocity_setpoint ||
           f == Field::_angular_velocity ||
           f == Field::_target_angular_velocity_fraction;
}

int64_t* point_state(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_current_angular_velocity:
            return &r._current_angular_velocity_state;
        case Field::_drift_velocity: return &r._drift_velocity_state;
        case Field::_target_angular_velocity_setpoint:
            return &r._target_angular_velocity_setpoint_state;
        case Field::_angular_velocity: return &r._angular_velocity_state;
        case Field::_target_angular_velocity_fraction:
            return &r._target_angular_velocity_fraction_state;
        default: return nullptr;
    }
}

bool read_only(Field f) {
    // A point-or-none field's state is written by set_fv with its vector.
    return f == Field::xform_index || f == Field::xform_gen ||
           f == Field::obj_id || f == Field::_current_angular_velocity_state ||
           f == Field::_drift_velocity_state ||
           f == Field::_target_angular_velocity_setpoint_state ||
           f == Field::_angular_velocity_state ||
           f == Field::_target_angular_velocity_fraction_state;
}

// Per-row-type field lookups; the generic overloads find nothing.
template <class R> double* fptr(R&, Field) { return nullptr; }
template <class R> int64_t* iptr(R&, Field) { return nullptr; }
template <class R> int64_t* rptr(R&, Field) { return nullptr; }
template <class R> std::vector<int64_t>* idptr(R&, Field) { return nullptr; }
template <class R> Vec3* vptr(R&, Field) { return nullptr; }
template <class R> std::vector<double>* flptr(R&, Field) { return nullptr; }

double* fptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_life_time: return &r._life_time;
        case Field::o_radius: return &r._radius;
        case Field::_scale: return &r._scale;
        case Field::_splash_damage: return &r._splash_damage;
        case Field::_splash_damage_radius: return &r._splash_damage_radius;
        case Field::_mass: return &r._mass;
        case Field::_current_speed: return &r._current_speed;
        default: return nullptr;
    }
}
int64_t* iptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::has_posed_parts: return &r.has_posed_parts;
        case Field::_rigless_gen: return &r._rigless_gen;
        case Field::has_real_is_dead: return &r.has_real_is_dead;
        case Field::has_real_get_shields: return &r.has_real_get_shields;
        case Field::is_ship_class: return &r.is_ship_class;
        case Field::_use_target_offset: return &r._use_target_offset;
        case Field::hull_box_set: return &r.hull_box_set;
        case Field::xform_index: return &r.xform_index;
        case Field::xform_gen: return &r.xform_gen;
        case Field::obj_id: return &r.obj_id;
        case Field::has_sensor_getter: return &r.has_sensor_getter;
        case Field::has_cloak_getter: return &r.has_cloak_getter;
        case Field::is_rock: return &r.is_rock;
        case Field::is_meta_nebula: return &r.is_meta_nebula;
        case Field::_dead: return &r._dead;
        case Field::_dying: return &r._dying;
        case Field::arriving: return &r.arriving;
        case Field::_hurtable: return &r._hurtable;
        case Field::dmg_ship: return &r.dmg_ship;
        case Field::o_invincible: return &r._invincible;
        case Field::_current_angular_velocity_state:
            return &r._current_angular_velocity_state;
        case Field::_drift_velocity_state: return &r._drift_velocity_state;
        case Field::_target_angular_velocity_setpoint_state:
            return &r._target_angular_velocity_setpoint_state;
        case Field::_angular_velocity_state:
            return &r._angular_velocity_state;
        case Field::_angular_space: return &r._angular_space;
        case Field::_static: return &r._static;
        case Field::_stationary: return &r._stationary;
        case Field::_insystem_warp_transit: return &r._insystem_warp_transit;
        case Field::motion_stock: return &r.motion_stock;
        case Field::_velocity_state: return &r._velocity_state;
        case Field::_target_angular_velocity_fraction_state:
            return &r._target_angular_velocity_fraction_state;
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
        case Field::_target_subsystem: return &r._target_subsystem;
        case Field::_shield_subsystem: return &r._shield_subsystem;
        case Field::_impulse_engine_subsystem:
            return &r._impulse_engine_subsystem;
        case Field::_power_subsystem: return &r._power_subsystem;
        case Field::_repair_subsystem: return &r._repair_subsystem;
        default: return nullptr;
    }
}
Vec3* vptr(ObjectRow& r, Field f) {
    switch (f) {
        case Field::_velocity: return &r._velocity;
        case Field::_manual_target_offset: return &r._manual_target_offset;
        case Field::_shield_hull_box_center: return &r._shield_hull_box_center;
        case Field::_shield_hull_box_half: return &r._shield_hull_box_half;
        case Field::_fbm: return &r._fbm;
        case Field::_seed: return &r._seed;
        case Field::_current_angular_velocity:
            return &r._current_angular_velocity;
        case Field::_drift_velocity: return &r._drift_velocity;
        case Field::_target_angular_velocity_setpoint:
            return &r._target_angular_velocity_setpoint;
        case Field::_angular_velocity: return &r._angular_velocity;
        case Field::_target_angular_velocity_fraction:
            return &r._target_angular_velocity_fraction;
        default: return nullptr;
    }
}
std::vector<double>* flptr(ObjectRow& r, Field f) {
    if (f == Field::_speed_setpoint) return &r._speed_setpoint;
    if (f == Field::_acceleration) return &r._acceleration;
    if (f == Field::_turn_goal) return &r._turn_goal;
    return f == Field::_motion_vel ? &r._motion_vel : nullptr;
}
std::vector<int64_t>* idptr(ObjectRow& r, Field f) {
    return f == Field::_powered_consumers ? &r._powered_consumers : nullptr;
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
        case Field::_length: return &r._length;
        case Field::_beam_on_countdown: return &r._beam_on_countdown;
        case Field::_dwell: return &r._dwell;
        case Field::_recharge_rate: return &r._recharge_rate;
        case Field::_reload_delay: return &r._reload_delay;
        case Field::_watch_value: return &r._watch_value;
        case Field::_damage_radius_factor: return &r._damage_radius_factor;
        case Field::cond_watch_value: return &r.cond_watch_value;
        case Field::comb_watch_value: return &r.comb_watch_value;
        case Field::_max_damage: return &r._max_damage;
        case Field::_max_damage_distance: return &r._max_damage_distance;
        case Field::_efficiency: return &r._efficiency;
        case Field::_normal_power: return &r._normal_power;
        case Field::_power_percentage_wanted:
            return &r._power_percentage_wanted;
        case Field::_max_speed: return &r._max_speed;
        case Field::_max_accel: return &r._max_accel;
        case Field::_max_angular_velocity: return &r._max_angular_velocity;
        case Field::_max_angular_accel: return &r._max_angular_accel;
        case Field::_charge_accum: return &r._charge_accum;
        case Field::_available_power: return &r._available_power;
        case Field::_main_battery_power: return &r._main_battery_power;
        case Field::_backup_battery_power: return &r._backup_battery_power;
        case Field::_main_conduit_current: return &r._main_conduit_current;
        case Field::_backup_conduit_current:
            return &r._backup_conduit_current;
        case Field::_interval_elapsed: return &r._interval_elapsed;
        case Field::_power_dispensed: return &r._power_dispensed;
        case Field::_power_wanted_total: return &r._power_wanted_total;
        case Field::_power_wanted: return &r._power_wanted;
        case Field::_power_received: return &r._power_received;
        case Field::_backup_reserve: return &r._backup_reserve;
        case Field::CLOAK_RESERVE_DRAIN_PER_SECOND:
            return &r.CLOAK_RESERVE_DRAIN_PER_SECOND;
        case Field::_transition_elapsed: return &r._transition_elapsed;
        case Field::_transition_duration: return &r._transition_duration;
        case Field::_repair_complexity: return &r._repair_complexity;
        default: return nullptr;
    }
}
int64_t* iptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::weapon_kind: return &r.weapon_kind;
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
        case Field::has_shields: return &r.has_shields;
        case Field::has_parent_ship_getter: return &r.has_parent_ship_getter;
        case Field::_destroyed: return &r._destroyed;
        case Field::_radiation_out: return &r._radiation_out;
        case Field::_cloak_state: return &r._cloak_state;
        case Field::_watch_checks: return &r._watch_checks;
        case Field::_power_level: return &r._power_level;
        case Field::_threshold_state: return &r._threshold_state;
        case Field::_invincible: return &r._invincible;
        case Field::_critical: return &r._critical;
        case Field::_in_repair_queue: return &r._in_repair_queue;
        case Field::dmg_class: return &r.dmg_class;
        case Field::cond_watch_checks: return &r.cond_watch_checks;
        case Field::comb_watch_checks: return &r.comb_watch_checks;
        case Field::_mode: return &r._mode;
        case Field::_was_firing: return &r._was_firing;
        case Field::_next_emitter_index: return &r._next_emitter_index;
        case Field::engage_kind: return &r.engage_kind;
        case Field::motion_ies_stock: return &r.motion_ies_stock;
        case Field::motion_pod_stock: return &r.motion_pod_stock;
        case Field::shield_watch_ok: return &r.shield_watch_ok;
        case Field::_breach_fired: return &r._breach_fired;
        case Field::power_watch_ok: return &r.power_watch_ok;
        case Field::POWER_MODE: return &r.POWER_MODE;
        case Field::DRAWS_DIRECT_FROM_MAIN: return &r.DRAWS_DIRECT_FROM_MAIN;
        case Field::power_kind: return &r.power_kind;
        case Field::is_repair_bay: return &r.is_repair_bay;
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
        case Field::_queue: return &r._queue;
        case Field::_cannot_complete_notified:
            return &r._cannot_complete_notified;
        case Field::_target_list: return &r._target_list;
        case Field::_children: return &r._children;
        case Field::_ammo_by_slot: return &r._ammo_by_slot;
        default: return nullptr;
    }
}
std::vector<double>* flptr(SubsystemRow& r, Field f) {
    switch (f) {
        case Field::_reload_timers: return &r._reload_timers;
        case Field::_reload_advanced_at: return &r._reload_advanced_at;
        case Field::_current_shields: return &r._current_shields;
        case Field::_max_shields: return &r._max_shields;
        case Field::_ramp_fraction: return &r._ramp_fraction;
        case Field::_ramp_set: return &r._ramp_set;
        case Field::_charge_per_second: return &r._charge_per_second;
        case Field::shield_watch_values: return &r.shield_watch_values;
        case Field::shield_watch_checks: return &r.shield_watch_checks;
        case Field::power_watch_values: return &r.power_watch_values;
        case Field::power_watch_checks: return &r.power_watch_checks;
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
        case Field::engage_point: return &r.engage_point;
        default: return nullptr;
    }
}

double* fptr(PropertyRow& r, Field f) {
    switch (f) {
        case Field::MaxCondition: return &r.MaxCondition;
        case Field::slot0_launch_speed: return &r.slot0_launch_speed;
        case Field::PowerOutput: return &r.PowerOutput;
        case Field::MainBatteryLimit: return &r.MainBatteryLimit;
        case Field::BackupBatteryLimit: return &r.BackupBatteryLimit;
        case Field::MainConduitCapacity: return &r.MainConduitCapacity;
        case Field::BackupConduitCapacity: return &r.BackupConduitCapacity;
        case Field::MaxRepairPoints: return &r.MaxRepairPoints;
        default: return nullptr;
    }
}
int64_t* iptr(PropertyRow& r, Field f) {
    switch (f) {
        case Field::MaxCondition_set: return &r.MaxCondition_set;
        case Field::_groups: return &r._groups;
        case Field::slot0_launch_state: return &r.slot0_launch_state;
        case Field::power_props_ok: return &r.power_props_ok;
        case Field::NumRepairTeams: return &r.NumRepairTeams;
        case Field::repair_props_ok: return &r.repair_props_ok;
        default: return nullptr;
    }
}

int64_t* iptr(AmmoRow& r, Field f) {
    switch (f) {
        case Field::_unlimited: return &r._unlimited;
        case Field::_available: return &r._available;
        case Field::_max_torpedoes: return &r._max_torpedoes;
        case Field::ammo_launch_state: return &r.ammo_launch_state;
        default: return nullptr;
    }
}
double* fptr(AmmoRow& r, Field f) {
    return f == Field::ammo_launch_speed ? &r.ammo_launch_speed : nullptr;
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
                             int64_t obj_id, uint64_t py_id) {
    int64_t h;
    switch (kind) {
        case Kind::Object: {
            h = alloc(objects_, kind);
            ObjectRow& r = objects_.rows[h & kIndexMask];
            r.xform_index = xform_index;
            r.xform_gen = xform_gen;
            r.obj_id = obj_id;
            r.py_id = py_id;
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
    torpedoes_.clear();
    globals_ = Globals{};
    part_gen_ = 1;
    clear_owned_state();
    ++epoch_;
}

int64_t Mirror::find_by_obj_id(int64_t obj_id) const {
    auto it = by_obj_id_.find(obj_id);
    if (it == by_obj_id_.end()) return -1;
    return find(objects_, it->second, Kind::Object) ? it->second : -1;
}

void Mirror::set_obj_id_findable(int64_t h, bool findable) {
    if (kind_of(h) != Kind::Object)
        throw std::invalid_argument("combat mirror: not an Object row");
    const ObjectRow& r = checked(objects_, h, Kind::Object);
    if (r.obj_id < 0) return;
    if (findable) {
        by_obj_id_[r.obj_id] = h;
    } else {
        auto it = by_obj_id_.find(r.obj_id);
        if (it != by_obj_id_.end() && it->second == h) by_obj_id_.erase(it);
    }
    ++epoch_;
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
    } else if (f == Field::_children || f == Field::_powered_consumers ||
               f == Field::_queue) {
        entries_are(Kind::Subsystem);
    } else if (f == Field::_ammo_by_slot) {
        // [slot, Ammo handle] pairs, in dict order; -1 is a slot holding
        // None.
        if (v.size() % 2 != 0) bad("expected [slot, handle] pairs", f);
        for (size_t i = 1; i < v.size(); i += 2)
            if (v[i] != kRefUnrepresentable && v[i] != -1 &&
                (v[i] < 0 || static_cast<Kind>((v[i] >> 60) & 7) != Kind::Ammo))
                bad("list entry is not an Ammo handle", f);
    } else if (f == Field::_cannot_complete_notified) {
        entries_are(Kind::Subsystem);
        std::sort(v.begin(), v.end());
        v.erase(std::unique(v.begin(), v.end()), v.end());
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
                     f == Field::_held_offset || f == Field::_target_offset ||
                     f == Field::_manual_target_offset);
    if (point_or_none(f)) {
        // 0 doubles: None (state 0); 3: a TGPoint3 (1); 4: unrepresentable
        // (2), the vector reads zero.
        if (!(v.empty() || v.size() == 3 || v.size() == 4))
            bad("expected 0, 3 or 4 doubles", f);
        ObjectRow& row = checked(objects_, h, Kind::Object);
        Vec3* p = vptr(row, f);
        *p = v.size() == 3 ? Vec3{v[0], v[1], v[2]} : Vec3{0, 0, 0};
        *point_state(row, f) = v.empty() ? 0 : (v.size() == 3 ? 1 : 2);
        ++epoch_;
        return;
    }
    if (!(v.size() == 3 || (nullable && v.empty())))
        bad("expected 3 doubles", f);
    visit(h, info(f).kind, [&](auto& row) {
        Vec3* p = vptr(row, f);
        if (!p) bad("field not on this row", f);
        if (!v.empty()) *p = {v[0], v[1], v[2]};
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, ObjectRow>) {
            if (f == Field::_fbm) row.fbm_set = !v.empty();
            if (f == Field::_seed) row.seed_set = !v.empty();
            if (f == Field::_manual_target_offset)
                row.manual_offset_set = !v.empty();
            // A TGPoint3 is what every native writer stores; Python
            // re-marks a non-TGPoint3 value 2 (VelocityField).
            if (f == Field::_velocity) row._velocity_state = 1;
        }
        if constexpr (std::is_same_v<std::decay_t<decltype(row)>, SubsystemRow>) {
            if (f == Field::_held_offset) {
                row.held_offset_set = !v.empty();
                row.held_offset_stamp = ++offset_stamp_;  // a new object
            }
            if (f == Field::_target_offset) {
                row.target_offset_set = !v.empty();
                row.target_offset_src = -1;  // its object no longer known
            }
        }
    });
    ++epoch_;
}

void Mirror::set_target_offset_source(int64_t bank, int64_t sys,
                                      uint64_t stamp) {
    SubsystemRow& row = checked(subsystems_, bank, Kind::Subsystem);
    row.target_offset_src = sys;
    row.target_offset_src_stamp = stamp;
}

void Mirror::forget_offset_sources() {
    for (SubsystemRow& row : subsystems_.rows) row.target_offset_src = -1;
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

void Mirror::set_floats(int64_t h, Field f, const std::vector<double>& v) {
    if (info(f).type != FieldType::FloatList) bad("not a float-list field", f);
    visit(h, info(f).kind, [&](auto& row) {
        auto* p = flptr(row, f);
        if (!p) bad("field not on this row", f);
        *p = v;
    });
    ++epoch_;
}

void Mirror::set_float_at(int64_t h, Field f, size_t index, double v) {
    if (info(f).type != FieldType::FloatList) bad("not a float-list field", f);
    visit(h, info(f).kind, [&](auto& row) {
        auto* p = flptr(row, f);
        if (!p) bad("field not on this row", f);
        p->at(index) = v;
    });
    ++epoch_;
}

std::vector<double> Mirror::get_floats(int64_t h, Field f) const {
    if (info(f).type != FieldType::FloatList) bad("not a float-list field", f);
    return visit(h, info(f).kind, [&](auto& row) {
        auto* p = flptr(row, f);
        if (!p) bad("field not on this row", f);
        return *p;
    });
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

void Mirror::set_part_poses(int64_t h, std::vector<PartPose> poses) {
    checked(objects_, h, Kind::Object).part_poses = std::move(poses);
    ++epoch_;
}

void Mirror::set_part_slot(int64_t h, int32_t slot, uint64_t gen) {
    if (slot < -1)
        throw std::invalid_argument("combat mirror: part slot below -1");
    SubsystemRow& r = checked(subsystems_, h, Kind::Subsystem);
    r.part_slot = slot;
    r.part_gen = gen;
    ++epoch_;
}

void Mirror::set_mount_order(int64_t h, const std::vector<int64_t>& order) {
    for (int64_t x : order)
        if (x != kRefUnrepresentable &&
            (x < 0 || static_cast<Kind>((x >> 60) & 7) != Kind::Subsystem))
            throw std::invalid_argument(
                "combat mirror: mount order entry is not a Subsystem handle");
    checked(objects_, h, Kind::Object).mount_order = order;
    ++epoch_;
}

void Mirror::set_part_gen(uint64_t gen) {
    part_gen_ = gen;
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
                (f == Field::_seed && !row.seed_set) ||
                (f == Field::_manual_target_offset && !row.manual_offset_set))
                return {};
            if (point_or_none(f)) {
                int64_t state = *point_state(row, f);
                if (state == 0) return {};
                if (state == 2) return {0.0, 0.0, 0.0, 0.0};
            }
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

namespace {

Kind torpedo_ref_kind(TorpField f) {
    switch (f) {
        case TorpField::_target_ship:
        case TorpField::_source_ship: return Kind::Object;
        case TorpField::_containing_set: return Kind::Set;
        case TorpField::_mount_key: return Kind::Subsystem;
        default:
            throw std::invalid_argument(
                std::string("torpedo table: not a ref field (field ") +
                torp_field_name(f) + ")");
    }
}

}  // namespace

void Mirror::set_torpedo_ref(int64_t torp, TorpField f, int64_t ref) {
    Kind want = torpedo_ref_kind(f);
    if (f == TorpField::_mount_key)
        throw std::invalid_argument(
            "torpedo table: _mount_key is set by set_torpedo_mount");
    if (ref != -1 && ref != kRefUnrepresentable && !ref_live(ref, want))
        throw std::invalid_argument(
            std::string("torpedo table: ref target stale or wrong kind "
                        "(field ") + torp_field_name(f) + ")");
    torpedoes_.set_ref(torp, f, ref);
}

void Mirror::set_torpedo_mount(int64_t torp, bool attributed, int64_t sub,
                               const Vec3& offset) {
    if (sub != -1 && sub != kRefUnrepresentable &&
        !ref_live(sub, Kind::Subsystem))
        throw std::invalid_argument(
            "torpedo table: ref target stale or wrong kind (field "
            "_mount_key)");
    torpedoes_.set_mount(torp, attributed, sub, offset);
}

int64_t Mirror::torpedo_ref(const TorpedoRow& row, TorpField f) const {
    Kind want = torpedo_ref_kind(f);
    int64_t t;
    switch (f) {
        case TorpField::_target_ship: t = row.target; break;
        case TorpField::_source_ship: t = row.source; break;
        case TorpField::_containing_set: t = row.cset; break;
        default: t = row.mount_sub; break;
    }
    // Unlike get_ref: the torpedo holds its referents strongly, so a stored
    // handle whose row is gone means the row was DROPPED (the object took the
    // Python path), never that the object is gone -- it must not read None.
    if (t >= 0 && !ref_live(t, want)) return kRefUnrepresentable;
    return t;
}

Mirror& mirror() {
    static Mirror m(transform_store());
    return m;
}

}  // namespace dauntless::combat
