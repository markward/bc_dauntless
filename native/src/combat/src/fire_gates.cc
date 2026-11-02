// The native weapon fire gates -- see fire_gates.h. Each function ports the
// Python function of the same name (file:line in its comment), statement by
// statement and in the same order: keep them in step. K1M = docs/reference/
// engine/native-combat/k1-fire-control-map.md.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/fire_gates.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/weapon_geometry.h"

namespace dauntless::combat {

namespace {

// Subsystem weapon_kind codes (mirror.h).
constexpr int64_t kPhaserSystem = 1, kPulseSystem = 2, kTractorSystem = 3,
                  kTorpedoSystem = 4, kPhaserBank = 5, kPulseWeapon = 6,
                  kTractorBeam = 7, kTorpedoTube = 8;

[[noreturn]] void fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat fire_gates: ") + why +
                                " -- answer in Python");
}

const SubsystemRow& sub(const Mirror& m, int64_t h) {
    if (h < 0) fall_back("subsystem handle is none or unrepresentable");
    const SubsystemRow* r = m.subsystem(h);
    if (!r) fall_back("subsystem handle is stale, freed or not a Subsystem");
    return *r;
}

// A Subsystem ref field's referent, or nullptr for None.
const SubsystemRow* sub_ref(const Mirror& m, int64_t ref, const char* field) {
    if (ref == -1) return nullptr;
    if (ref == kRefUnrepresentable) fall_back(field);
    const SubsystemRow* r = m.subsystem(ref);
    if (!r) fall_back(field);
    return r;
}

bool is_system_kind(int64_t k) {
    return k == kPhaserSystem || k == kPulseSystem || k == kTractorSystem ||
           k == kTorpedoSystem;
}

// A WeaponSystem class (systems and the energy banks, which subclass it);
// the tube is a plain Weapon(ShipSubsystem) and keeps the ShipSubsystem rule.
bool aggregates_children(int64_t kind) {
    return (kind >= kPhaserSystem && kind <= kTractorBeam);
}

// ShipSubsystem.IsDisabled (subsystems.py:1199). Reads _max_condition, NOT
// GetMaxCondition (K1M F5).
bool leaf_is_disabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}

// ShipSubsystem.IsDestroyed (subsystems.py:1226).
bool leaf_is_destroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

// A malformed (cyclic) child chain would recurse forever in Python.
constexpr int kMaxDepth = 32;

bool is_destroyed(const Mirror& m, const SubsystemRow& s, int depth);

// WeaponSystem.IsDisabled (weapon_subsystems.py:1459): a leaf emitter (no
// children) uses the ShipSubsystem rule; otherwise ALL children disabled.
bool is_disabled(const Mirror& m, const SubsystemRow& s, int depth) {
    if (depth > kMaxDepth) fall_back("child chain too deep");
    if (!aggregates_children(s.weapon_kind) || s._children.empty())
        return leaf_is_disabled(s);
    for (const int64_t c : s._children) {
        if (!is_disabled(m, sub(m, c), depth + 1)) return false;
    }
    return true;
}

// WeaponSystem.IsDestroyed (weapon_subsystems.py:1468).
bool is_destroyed(const Mirror& m, const SubsystemRow& s, int depth) {
    if (depth > kMaxDepth) fall_back("child chain too deep");
    if (!aggregates_children(s.weapon_kind) || s._children.empty())
        return leaf_is_destroyed(s);
    if (s._destroyed) return true;
    for (const int64_t c : s._children) {
        if (!is_destroyed(m, sub(m, c), depth + 1)) return false;
    }
    return true;
}

// PowerSubsystem.IsOn (subsystems.py:1351) on a weapon system parent.
bool parent_is_on(const SubsystemRow& parent) {
    if (!is_system_kind(parent.weapon_kind))
        fall_back("parent is not a weapon system");
    return parent._is_on != 0;
}

// PulseWeapon._shot_cost (weapon_subsystems.py:2830):
// NormalDischargeRate * PULSE_COST_SCALE_BY_POWER_SETTING[power_setting].
// The table is pushed from Python (PULSE_COST_SCALE_0..2); SetPowerSetting
// clamps to 0..2, so any other value is not representable here.
double shot_cost(const Mirror& m, const SubsystemRow& s) {
    const Globals& g = m.globals();
    double scale;
    switch (s._power_setting) {
        case 0: scale = g.PULSE_COST_SCALE_0; break;
        case 1: scale = g.PULSE_COST_SCALE_1; break;
        case 2: scale = g.PULSE_COST_SCALE_2; break;
        default: fall_back("power setting outside the cost table");
    }
    return s._normal_discharge_rate * scale;
}

// _EnergyWeaponFireMixin.CanFire (weapon_subsystems.py:813), with `pulse`
// choosing PulseWeapon._charge_gate (:2836) over the mixin's (:855).
CanFireResult energy_can_fire(const Mirror& m, int64_t h, bool pulse) {
    const SubsystemRow& self = sub(m, h);
    CanFireResult r;
    const SubsystemRow* parent =
        sub_ref(m, self._parent_subsystem, "_parent_subsystem");
    const bool on = parent != nullptr && parent_is_on(*parent);
    if (!on) return r;
    const int64_t ship = climb_to_ship_of(m, h);
    if (ship != -1 && ship_dead(m, ship)) return r;
    // _charge_gate
    if (pulse) {
        // 1e-9: PulseWeapon._charge_gate's inline literal
        // (weapon_subsystems.py:2845 when ported).
        if (!(self._charge_level >= shot_cost(m, self) - 1e-9)) return r;
    } else {
        if (self._depleted) {
            if (self._charge_level < self._min_firing_charge) return r;
            r.clear_depleted = true;  // self._depleted = False (reported)
        }
        if (!(self._charge_level > 0.0)) return r;
    }
    const double combined =
        condition_percentage(m, self) * condition_percentage(m, *parent);
    if (self._disabled_percentage >= combined) return r;
    r.ok = true;
    return r;
}

}  // namespace

const AmmoRow* current_ammo_type(const Mirror& m,
                                 const SubsystemRow& torpedo_system) {
    const int64_t ammo_h = current_ammo_handle(m, torpedo_system);
    return ammo_h == -1 ? nullptr : m.ammo(ammo_h);
}

int64_t current_ammo_handle(const Mirror& m,
                            const SubsystemRow& torpedo_system) {
    const SubsystemRow* parent = &torpedo_system;
    if (parent->weapon_kind != kTorpedoSystem)
        fall_back("tube parent is not a torpedo system");
    const std::vector<int64_t>& slots = parent->_ammo_by_slot;  // [slot, h, ...]
    if (slots.empty()) return -1;  // GetCurrentAmmoType: None
    // GetCurrentAmmoSlot (weapon_subsystems.py:2063): the explicit selection
    // when populated, else the lowest populated slot.
    int64_t slot = slots[0];
    bool found_selected = false;
    for (size_t i = 0; i + 1 < slots.size(); i += 2) {
        slot = (i == 0) ? slots[i] : std::min(slot, slots[i]);
        if (parent->_selected_slot != -1 && slots[i] == parent->_selected_slot)
            found_selected = true;
    }
    if (found_selected) slot = parent->_selected_slot;
    int64_t ammo_h = -1;
    for (size_t i = 0; i + 1 < slots.size(); i += 2) {
        if (slots[i] == slot) { ammo_h = slots[i + 1]; break; }
    }
    // A slot holding None.
    if (ammo_h == -1) return -1;
    if (ammo_h == kRefUnrepresentable) fall_back("ammo type is unnamed");
    if (!m.ammo(ammo_h)) fall_back("ammo row is stale");
    return ammo_h;
}

namespace {

// TorpedoTube._ammo_exhausted (weapon_subsystems.py:3232): the parent
// TorpedoSystem's selected ammo type is a FINITE magazine with nothing left.
bool ammo_exhausted(const Mirror& m, const SubsystemRow* parent) {
    // _parent_ammo: parent.GetCurrentAmmoType() (TorpedoSystem only).
    if (parent == nullptr) return false;
    const AmmoRow* ammo = current_ammo_type(m, *parent);
    // `ammo is not None` is false: not finite.
    if (ammo == nullptr) return false;
    const bool finite = !ammo->_unlimited;  // getattr(ammo, "_unlimited", True)
    return finite && ammo->_available <= 0;
}

// TorpedoTube.CanFire (weapon_subsystems.py:3284).
CanFireResult tube_can_fire(const Mirror& m, int64_t h, double now) {
    const SubsystemRow& self = sub(m, h);
    CanFireResult r;
    const SubsystemRow* parent =
        sub_ref(m, self._parent_subsystem, "_parent_subsystem");
    if (parent == nullptr || !parent_is_on(*parent)) return r;
    // not self.IsSkewFire() and parent is not None and
    //   _game_time() - getattr(parent, "_last_system_fire_time", -1000.0) <= 0.5
    // (-1000.0 and 0.5 are inline literals, weapon_subsystems.py:3308; only a
    // TorpedoSystem carries the attribute.)
    if (!self._skew_fire) {
        const double last = (parent->weapon_kind == kTorpedoSystem)
                                ? parent->_last_system_fire_time
                                : -1000.0;
        if (now - last <= 0.5) return r;
    }
    if (self._num_ready <= 0) return r;
    if (leaf_is_disabled(self)) return r;  // self.IsDisabled(): a plain Weapon
    if (now - self._last_fire_time < self._immediate_delay) return r;
    if (ammo_exhausted(m, parent)) return r;
    r.ok = true;
    return r;
}

}  // namespace

bool ship_dead(const Mirror& m, int64_t ship) {
    if (ship == -1) return false;
    if (ship == kRefUnrepresentable) fall_back("ship is unnamed");
    const ObjectRow* o = m.object(ship);
    if (!o) fall_back("ship handle is stale, freed or not an Object");
    // hasattr(ship, "IsDead") is vacuously true on a stub; only a real IsDead
    // is answered here.
    if (!o->has_real_is_dead) fall_back("ship has no real IsDead");
    return o->_dead != 0;  // DamageableObject.IsDead (objects.py:916)
}

bool weapon_system_offline(const Mirror& m, int64_t sys) {
    const SubsystemRow& s = sub(m, sys);
    if (is_disabled(m, s, 0) || is_destroyed(m, s, 0)) return true;
    return is_offline_after_condition(m, s);
}

CanFireResult can_fire(const Mirror& m, int64_t bank, double now) {
    const SubsystemRow& s = sub(m, bank);
    switch (s.weapon_kind) {
        case kPhaserBank:
        case kTractorBeam:
            return energy_can_fire(m, bank, false);
        case kPulseWeapon:
            // PulseWeapon.CanFire (:2847): cooldown first.
            if (s._cooldown_remaining > 0.0) return CanFireResult{};
            return energy_can_fire(m, bank, true);
        case kTorpedoTube:
            return tube_can_fire(m, bank, now);
        default:
            fall_back("not a leaf weapon");
    }
}

double pulse_shot_cost(const Mirror& m, const SubsystemRow& cannon) {
    return shot_cost(m, cannon);
}

// PulseWeapon.GetDamageScale (weapon_subsystems.py):
// PULSE_DAMAGE_SCALE_BY_POWER_SETTING[power_setting], the table pushed from
// Python (PULSE_DAMAGE_SCALE_0..2) as shot_cost's is.
double pulse_damage_scale(const Mirror& m, const SubsystemRow& cannon) {
    const Globals& g = m.globals();
    switch (cannon._power_setting) {
        case 0: return g.PULSE_DAMAGE_SCALE_0;
        case 1: return g.PULSE_DAMAGE_SCALE_1;
        case 2: return g.PULSE_DAMAGE_SCALE_2;
        default: fall_back("power setting outside the damage-scale table");
    }
}

}  // namespace dauntless::combat
