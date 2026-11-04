#pragma once

#include <cstdint>
#include <optional>

#include "dauntless/combat/mirror.h"

// The native beam geometry of the K2 kernel (phase 2, Task 2): the phaser aim
// point, the strip emit point, the damage dwell, the sphere tier, the shield
// predicate and the shield bubble entry. docs/reference/engine/native-combat/
// k2-beams-map.md sections 1.2-1.5 and F3-F16, F18 are the specification.
//
// Each function is a line-for-line port of the Python function named in its
// comment in beam_geometry.cc, reading the Mirror and its TransformStore.
// Floats are Python's: double, the same operand order, py_min / py_max in
// Python's argument order, `** 0.5` as py_pow, every NaN branch as Python's.
// Handles are Object rows for ships and targets, Subsystem rows for banks and
// locks; -1 is Python's None.
//
// FALLBACK. As in weapon_geometry.h, a function throws std::invalid_argument
// (Python ValueError) when it cannot answer exactly as the Python would:
//   * a ref it reaches is unrepresentable (-2) or names a row that is gone;
//   * the ship whose mount it must carry is posed and the mount's part slot
//     is not current (PartStale, part_pose.h) -- for the aim point that is
//     the LOCK's own ship, never the bank's target for a lock; a current
//     slot is answered with the pose;
//   * a Manual Aim pick on a posed target whose mount the mirror cannot
//     tell (MountUnknown); a pick that is no mount is a plain body point;
//   * an Object's transform is invalid;
//   * shields_block on a target that is not a ShipClass or has no real
//     GetShields (its getattr goes through a stub that records telemetry).
// Nothing is written but the mount memo (one finished entry at a time).

namespace dauntless::combat {

struct AimPoint {
    Vec3 point;
    int64_t target_sub = -1;  // the locked Subsystem when the point IS its
                              // mount, else -1 (Python's None)
};

// host_loop._phaser_aim_point (map 1.2): Manual Aim's offset (F4), else the
// locked subsystem's GetWorldLocation (F3, on the LOCK's own ship and that
// ship's pose flag), else the target's centre.
AimPoint phaser_aim_point(Mirror& m, int64_t ship, int64_t target,
                          bool use_memo);

// PhaserBank._strip_emit_position (F5-F10), early returns included.
Vec3 strip_emit_position(Mirror& m, int64_t bank, const Vec3& target_world,
                         bool use_memo);

// _EnergyWeaponFireMixin.accumulate_dwell / take_dwell (F13). They REPORT
// the flushed value and the dwell the Python would leave in `_dwell`, and
// write nothing: the K2 write log owns the write.
struct DwellResult {
    double flushed = 0.0;
    double new_dwell = 0.0;
    // Whether the Python assigns `_dwell` at all: accumulate_dwell's
    // not-beam-on early return writes nothing; take_dwell always writes.
    bool wrote = true;
};
DwellResult accumulate_dwell(const Mirror& m, int64_t bank, double dt);
DwellResult take_dwell(const Mirror& m, int64_t bank);

// combat.ray_sphere_entry (F18). `Origin` is Python returning the ORIGIN
// OBJECT ITSELF (origin already inside the sphere), distinct from a point
// that merely has the origin's coordinates.
struct SphereEntry {
    enum class Kind { None, Point, Origin } kind = Kind::None;
    Vec3 point{0.0, 0.0, 0.0};  // valid for Point
};
SphereEntry ray_sphere_entry(const Vec3& origin, const Vec3& dir,
                             double max_dist, const Vec3& center,
                             double radius);

// collisions.world_radius for an Object row: GetRadius(), i.e. the base radius
// x the guarded scale (non-positive or non-finite scale counts as 1).
double world_radius(const Mirror& m, int64_t object);

// combat.shields_block (map 1.5). `npc_shields_off` is the dev cheat
// (dev_combat_cheats.disable_npc_shields_active()) and `player` the current
// player's Object handle (-1 none): arguments, not mirrored state.
bool shields_block(const Mirror& m, int64_t target, bool npc_shields_off,
                   int64_t player);

// combat.shield_bubble_entry (F15-F16), _hull_box_for's rules included. A
// point with NaN coordinates is a result, not nullopt (map F16).
std::optional<Vec3> shield_bubble_entry(const Mirror& m, int64_t target,
                                        const Vec3& origin, const Vec3& dir,
                                        double max_dist);

}  // namespace dauntless::combat
