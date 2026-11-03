#pragma once

#include <cstdint>
#include <optional>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/part_pose.h"

// The native weapon geometry of the K1 fire-control kernel (phase 1b, Task 2):
// mount positions, bank aim, firing arc, torpedo cone, target offset, the
// pulse lead solve and the range gate. Docs/reference/engine/native-combat/
// k1-fire-control-map.md section 3 (F2, F7, F9-F13) is the specification.
//
// Each function is a line-for-line port of the Python function of the SAME
// NAME (the file:line is in weapon_geometry.cc), reading the Mirror and its
// TransformStore. Floats are Python's: double, the same operand order, py_min
// / py_max in Python's argument order, `** 0.5` as pow, Length as sqrt,
// MultMatrixLeft summed m00*x + m01*y + m02*z. Handles are Object rows for
// ships and targets, Subsystem rows for banks, tubes and cannons; -1 is
// Python's None.
//
// FALLBACK. As in sensor_detect.h, a function throws std::invalid_argument
// (Python ValueError) when it cannot answer exactly as the Python would:
//   * a ref it reaches is unrepresentable (-2) or names a row that is gone;
//   * a ship whose mount it must carry has a part off its NIF pose
//     (has_posed_parts) and the mount's part slot is not current (reason
//     "part_stale": stamped behind the Mirror's part_gen, past the pose
//     table, or asked on a ship other than its own). A current slot is
//     answered with the pose (part_pose.h); at identity the Python returns
//     the authored point itself, so a rigged ship with every part there is
//     answered with no slot read;
//   * a posed target's offset mount the mirror cannot name;
// The posed-part cases throw the part_pose.h subclasses a kernel counts by
// reason: PartStale (a slot that is not current), MountUnknown (the mirror
// cannot tell the mount). A posed target's offset that is no mount's own
// point is no fallback: a plain body point (fire control native only, M5).
//   * an Object's transform is invalid;
//   * a target with no real IsDead (its stub records telemetry);
//   * a pulse cannon whose projectile module did not resolve.
// The only state written is the mount memo, one finished entry at a time: a
// completed mount answer may be memoised before a LATER step throws
// (harmless: Python memoises the same entry).

namespace dauntless::combat {

// ShipSubsystem._climb_to_ship (subsystems.py:952): the owning ship's Object
// handle, or -1 for none. Throws on a stale or unnamed ref in the chain.
int64_t climb_to_ship_of(const Mirror& m, int64_t subsystem);

// subsystems.subsystem_world_position: ship_pos + R . P1/P2(local), no scale
// (posed-parts map P3: the pose BEFORE the ship rotation). `ship_arg` is Python's second argument (-1 = None: the
// subsystem's own ship). Memoised by (sub, ship_arg) in
// SensorState::mounts when `use_memo` (step_memo.active()).
Vec3 subsystem_world_position(Mirror& m, int64_t sub, int64_t ship_arg,
                              bool use_memo);

// weapon_subsystems._resolve_aim_world: unit vector ship -> target, or the
// ship's forward when there is no target (target -1) or it is degenerate.
Vec3 _resolve_aim_world(const Mirror& m, int64_t ship, int64_t target);

// weapon_subsystems._resolve_bank_aim_world (bank -1 / target -1 = None).
Vec3 _resolve_bank_aim_world(Mirror& m, int64_t bank, int64_t target,
                             bool use_memo);

// weapon_subsystems._resolve_bank_aim_world with a world POINT as the target:
// what the K2 beam step passes (`target_sub or target`) once the locked
// subsystem's GetWorldLocation is already known. `bank` must be a Subsystem.
Vec3 _resolve_bank_aim_world_at(Mirror& m, int64_t bank, const Vec3& target_pos,
                                bool use_memo);

// weapon_subsystems._emitter_in_arc (F9). `aim` is a world vector.
bool _emitter_in_arc(const Mirror& m, int64_t emitter, int64_t ship,
                     const Vec3& aim);

// weapon_subsystems._emitter_forward_world with skew=False.
Vec3 _emitter_forward_world(const Mirror& m, int64_t emitter, int64_t ship);

// subsystems.target_offset_world (F11, posed-parts map P4; fire control
// native only M5, M8.5): pos + R . (scale * P1/P2(offset)). `mount_sub` is
// Python's `mount_sub` argument, the subsystem whose authored mount the
// offset is (kNoMount = None). The pose applies BEFORE the scale. On a
// posed target the mount's part slot carries the offset only when the
// offset IS the mount's `_position` (C `==` per axis). No mount, or an
// offset off the mount, is a plain body point: body_point_world(offset).
// A mount the mirror cannot name falls back; a stale slot or another
// ship's mount falls back PartStale.
Vec3 target_offset_world(const Mirror& m, int64_t target, const Vec3& offset,
                         int64_t mount_sub);

// subsystems.body_point_world (P4's tail, no part pose): pos + R .
// (scale * point) for a body-frame point already carried by its part --
// target_offset_world's own tail, and the whole of a picked spot's.
Vec3 body_point_world(const Mirror& m, int64_t target, const Vec3& point);

// weapon_subsystems._resolve_torpedo_aim_point (F11); nullopt is Python None.
// The tube's stored offset on a POSED target is aimed through its mount
// (`_RESOLVE`: authored_mount_subsystem, part_pose.h): MountUnknown when the
// mirror cannot tell it, else target_offset_world with what was found (no
// mount: a plain body point).
std::optional<Vec3> _resolve_torpedo_aim_point(const Mirror& m, int64_t tube,
                                               int64_t target);

// weapon_subsystems._in_torpedo_cone (F12). The cone literal is the pushed
// TORPEDO_CONE_HALF_ANGLE global.
bool _in_torpedo_cone(Mirror& m, int64_t tube, int64_t ship, const Vec3& aim,
                      bool use_memo);

// weapon_subsystems._solve_pulse_launch_direction (F13). The module's
// GetLaunchSpeed / GetLifetime are the cannon's mirrored launch_speed /
// lifetime (ruling P6); module_ok == 0 throws. Target acceleration is
// (0, 0, 0), as ObjectClass.GetAccelerationTG. The range gate is the pushed
// PULSE_RANGE_GATE_SECONDS global.
std::optional<Vec3> _solve_pulse_launch_direction(Mirror& m, int64_t cannon,
                                                  int64_t ship, int64_t target,
                                                  bool use_memo);

// weapon_subsystems._target_within_range_gu (F2), _same_set included.
bool _target_within_range_gu(const Mirror& m, int64_t ship, int64_t target,
                             double max_range_gu);

}  // namespace dauntless::combat
