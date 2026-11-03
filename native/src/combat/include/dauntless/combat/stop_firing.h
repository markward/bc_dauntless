#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

// `weapon.StopFiring()` on a leaf the kernels stand in for: the fields it
// writes, in Python's order, and whether a FIRING one stops its loop sound
// (the LOOP_STOP queue entry, spec 2026-11-02-combat-fire-events §4.3). One
// encoding, written by each kernel through its own write log: K1 (a walk's
// or the pump's stop, k1_fire_control.cc bank_stop), K2 (a phaser step's
// stop, k2_beams.cc) and K0 (a bank drained dry, k0_charging.cc). The
// Python (engine/appc/weapon_subsystems.py), by weapon_kind (mirror.h):
//   5 PhaserBank   _EnergyWeaponFireMixin.StopFiring: `_firing = False;
//                  _beam_on_countdown = 0.0`, then, if it was firing, the
//                  loop sound's stop
//   6 PulseWeapon  PulseWeapon.StopFiring: `_firing = False; _target =
//                  None; _target_offset = None` (no loop sound)
//   7 TractorBeam  the mixin's, as a PhaserBank (K1's tractor walk, K0's
//                  holding tractor: its `_firing` applies through the
//                  beam's NativeThawParentWakeField setter, so the parent's
//                  power program still thaws)
//   8 TorpedoTube  Weapon.StopFiring: `_firing = False`
// A change to one of those StopFiring methods changes this table: change
// both.

namespace dauntless::combat {

enum class StopWrite : int32_t {
    FiringFalse = 0,       // `_firing = False`
    BeamOnCountdownZero,   // `_beam_on_countdown = 0.0`
    TargetNone,            // `_target = None`
    TargetOffsetNone,      // `_target_offset = None`
};

struct StopFiring {
    std::array<StopWrite, 3> writes{};
    size_t n = 0;           // writes[0, n), in Python's order
    bool loop_stop = false; // a firing one queues LOOP_STOP after them
};

// The stop of a leaf of `weapon_kind`, or nullopt (not one the kernels
// write: the caller keeps its record or hands the weapon back).
constexpr std::optional<StopFiring> stop_firing_of(int64_t weapon_kind) {
    switch (weapon_kind) {
        case 5:  // PhaserBank: the mixin's (WS:920)
        case 7:  // TractorBeam: the mixin's too
            return StopFiring{{StopWrite::FiringFalse,
                               StopWrite::BeamOnCountdownZero},
                              2,
                              true};
        case 6:  // PulseWeapon (WS:3027)
            return StopFiring{{StopWrite::FiringFalse, StopWrite::TargetNone,
                               StopWrite::TargetOffsetNone},
                              3,
                              false};
        case 8:  // TorpedoTube: Weapon.StopFiring (WS:1222)
            return StopFiring{{StopWrite::FiringFalse}, 1, false};
        default:
            return std::nullopt;
    }
}

}  // namespace dauntless::combat
