#pragma once

#include <cstdint>

#include "dauntless/combat/mirror.h"

// The native weapon fire gates of the K1 fire-control kernel (phase 1b, Task
// 3): `_is_offline` for weapon systems, the parent `IsOn`, the ship-dead test
// and each kind's `CanFire`. docs/reference/engine/native-combat/
// k1-fire-control-map.md section 1.4 (CanFire per kind) and 3 (F3-F6) are the
// specification; each function ports the Python function of the SAME NAME
// (file:line in fire_gates.cc). Floats are Python's: double, the same operand
// order, py_min/py_max in Python's argument order, every NaN branch as
// Python's.
//
// FALLBACK. As in sensor_detect.h a function throws std::invalid_argument
// (Python ValueError) when it cannot answer exactly as the Python would:
//   * a ref it reaches is unrepresentable (-2) or names a row that is gone;
//   * the ship has no real IsDead (has_real_is_dead == 0: its stub records
//     telemetry in Python, which the kernel cannot reproduce);
//   * the row is not of a kind the function handles (`can_fire` takes banks,
//     cannons, tractor beams and tubes only), or a parent is not a weapon
//     system;
//   * a power setting outside the pushed 0..2 table (Python would raise).
// Only what the query actually reaches is checked, as in the Python.
//
// Nothing is written. In particular `_charge_gate`'s `_depleted = False` is
// REPORTED (CanFireResult::clear_depleted), never applied: the K1 write log
// owns that write.

namespace dauntless::combat {

// ship_death / DamageableObject.IsDead as the mixin's CanFire reads it:
// `ship is not None and hasattr(ship, "IsDead") and ship.IsDead()`. -1 (None)
// is false; a ship row without a real IsDead throws.
bool ship_dead(const Mirror& m, int64_t ship);

// subsystems._is_offline(sys) where `sys` is a weapon system (or any weapon
// row): WeaponSystem's aggregate IsDisabled / IsDestroyed over all children,
// then the radiation and out-of-action checks (shared with the sensor
// `_is_offline`, sensor_detect.h).
bool weapon_system_offline(const Mirror& m, int64_t sys);

struct CanFireResult {
    bool ok = false;
    // Python's CanFire would have run `self._depleted = False` before
    // returning (ok or not): the latch was set and the charge had climbed
    // back to MinFiringCharge. False for pulse cannons and tubes.
    bool clear_depleted = false;
};

// TorpedoSystem.GetCurrentAmmoType (weapon_subsystems.py:2083) on the
// mirror: the selected slot when it is populated, else the lowest populated
// slot (GetCurrentAmmoSlot), and that slot's Ammo row -- nullptr for Python's
// None (no ammo configured, or a slot holding None). Throws (see FALLBACK)
// when `torpedo_system` is not a torpedo system or the ammo row cannot be
// named. Shared by the tube's CanFire and K0's reload gate.
const AmmoRow* current_ammo_type(const Mirror& m,
                                 const SubsystemRow& torpedo_system);
// The same, as its Ammo handle: -1 for None.
int64_t current_ammo_handle(const Mirror& m,
                            const SubsystemRow& torpedo_system);

// CanFire for a leaf weapon, dispatched on weapon_kind: 5 phaser bank and 7
// tractor beam (_EnergyWeaponFireMixin.CanFire), 6 pulse cannon
// (PulseWeapon.CanFire), 8 torpedo tube (TorpedoTube.CanFire).
//
// `now` is the weapon game time Python's tube CanFire reads: the
// weapon_subsystems._game_time() clock, float(App.g_kUtopiaModule.
// GetGameTime()) (0.0 if that raises). Python reads it twice in one CanFire;
// the caller passes the one value both reads would see. Unused by banks.
CanFireResult can_fire(const Mirror& m, int64_t bank, double now);

// A cannon's launch (k1_fire_control.h, LAUNCHES AT THE BOUNDARY), from the
// power-setting tables Python pushes (PULSE_COST_SCALE_*, PULSE_DAMAGE_
// SCALE_*): PulseWeapon._shot_cost, NormalDischargeRate x the cost scale,
// and PulseWeapon.GetDamageScale. A power setting outside 0..2 throws
// (Python would raise IndexError).
double pulse_shot_cost(const Mirror& m, const SubsystemRow& cannon);
double pulse_damage_scale(const Mirror& m, const SubsystemRow& cannon);

}  // namespace dauntless::combat
