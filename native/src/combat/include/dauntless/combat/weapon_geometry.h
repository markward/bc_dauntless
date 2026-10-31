#pragma once

#include <cstdint>
#include <optional>

#include "dauntless/combat/mirror.h"

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
//   * a ship whose mount or aim it must carry has articulated parts
//     (has_posed_parts): the Python walks the rig, the mirror cannot;
//   * an Object's transform is invalid;
//   * a target with no real IsDead (its stub records telemetry);
//   * a pulse cannon whose projectile module did not resolve.
// The only state written is the mount memo, one finished entry at a time: a
// completed mount answer may be memoised before a LATER step throws
// (harmless: Python memoises the same entry).

namespace dauntless::combat {

// subsystems.subsystem_world_position (identity-pose ships only): ship_pos +
// R . local, no scale. `ship_arg` is Python's second argument (-1 = None: the
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

// weapon_subsystems._emitter_in_arc (F9). `aim` is a world vector.
bool _emitter_in_arc(const Mirror& m, int64_t emitter, int64_t ship,
                     const Vec3& aim);

// weapon_subsystems._emitter_forward_world with skew=False.
Vec3 _emitter_forward_world(const Mirror& m, int64_t emitter, int64_t ship);

// subsystems.target_offset_world (F11) for a target with no posed parts.
Vec3 target_offset_world(const Mirror& m, int64_t target, const Vec3& offset);

// weapon_subsystems._resolve_torpedo_aim_point (F11); nullopt is Python None.
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
