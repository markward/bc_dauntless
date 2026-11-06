#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// Kernel M (native motion phase 2, Task 4): the per-ship motion step,
// a bit-exact port of engine/appc/ship_motion.py's _step_ship_motion (with
// _integrate_rotation, _effective_motion, _cap_keep, step_vector_velocity,
// law_step_vector, _ramp_toward and _no_thrust) and engine/appc/drift.py's
// step. It reads only the combat mirror and the transform store, so it runs
// with the GIL released.
//
// The walk starts at rows[begin] and, per row, in Python's order:
//   1. no live Object row, motion_stock 0, or an invalid transform: stop
//      PythonRow (the row is Python's);
//   2. immobile (_static or _stationary): next row;
//   3. an in-system warp flight: stop WarpRow (Python runs
//      warp_flight.step), unless resume_past_warp and this is rows[begin]
//      (Python's step returned False: the rest of the row is ours);
//   4. arriving (the warp-in slide): next row;
//   5. no setpoints: drift.step, unless the row is `player`;
//   6. else impulse fractions, then every pod out (online <= 0): inertial
//      drift; else the powered step -- the motion law on the velocity vector
//      (step_vector_velocity) and on the angular velocity vector
//      (law_step_vector) -- then the rotation. A stored turn goal with a
//      setpoint (_turn_goal non-empty, the setpoint a point) is steered
//      between the two, as ShipClass._steer_turn_goal steers it (ported
//      with _turn_goal_vectors, _turn_rotation, _frame_rotation and
//      _to_body): a "loc" goal reads the position after this tick's
//      translate, the rotation before this tick's spin; the new setpoint is
//      logged (kSteer) and feeds the angular law uncapped. A goal the
//      mirror cannot represent ([0]) stops PythonRow (TurnGoal);
//   7. the acceleration is the law's own output (Mark 2026-11-06), not
//      dv/dt: step_vector_velocity's (v - v0) / dt on the powered step,
//      zero (_no_thrust) on every other exit but the setpoint-less player
//      (its helm owns it: nothing written). It is logged (kAccel) and
//      written to the mirror only when it differs bitwise from the
//      mirror's _acceleration (or that is None); one the mirror cannot
//      represent is Python's (Unrepresentable).
//
// Each row is computed into locals and committed at its end. Anything the
// kernel cannot answer as Python would -- an unrepresentable input (a
// point-or-none state 2, a -2 ref, a 6-float setpoint), a Python exception
// it would raise (math.cos of an infinity, a zero spin rate, the steering's
// float division by zero or `x ** 2` overflow), a throw from
// a helper (std::invalid_argument, "answer in Python") -- stops PythonRow at
// that row with NOTHING of it written. A commit writes the store pose, the
// mirror's _current_speed, _current_angular_velocity, _velocity,
// _drift_velocity, _motion_vel, _acceleration and (steering)
// _target_angular_velocity_setpoint and _fraction, and appends one
// MotionWrite carrying exactly the attributes Python would have written
// (`what`), less an unchanged acceleration; a row with nothing to log
// (a drifter or an immobile ship whose zero acceleration is held already)
// appends none.
//
// `rows` are Object handles in the stage's order; MotionWrite::row and
// MotionResult::at are positions in it (at = rows.size() when Done).
// Throws std::invalid_argument for a `begin` outside [0, rows.size()].
namespace dauntless::combat {

enum class MotionStop : int32_t { Done = 0, WarpRow = 1, PythonRow = 2 };
enum class MotionReason : int32_t {
    None = 0, NoRow, NotStock, Unrepresentable, FallBack, BadTransform,
    TurnGoal, kCount
};
enum MotionWhat : uint8_t {
    kSpeed = 1, kAngVel = 2, kVelocity = 4, kDriftSet = 8, kDriftClear = 16,
    kMotionVel = 32, kAccel = 64, kSteer = 128
};

struct MotionWrite {
    uint32_t row;
    uint8_t what;
    double speed;        // _current_speed (kSpeed)
    Vec3 cav;            // _current_angular_velocity, in place (kAngVel)
    Vec3 velocity;       // _velocity = TGPoint3(...) (kVelocity)
    Vec3 drift;          // _drift_velocity = TGPoint3(...) (kDriftSet)
    std::array<double, 4> motion_vel;  // _motion_vel = (vx, vy, vz, speed)
    Vec3 accel;          // _acceleration = (ax, ay, az) (kAccel)
    // _target_angular_velocity_setpoint = TGPoint3(...), the fraction None,
    // _turn_goal[1] = that same point (kSteer)
    Vec3 setpoint;
};

struct MotionResult {
    MotionStop stop;
    int64_t at;
    MotionReason reason;
    std::vector<MotionWrite> writes;
};

// ship_motion.FALLBACK_MAX_ACCEL and BC_IMPULSE_TAU.
constexpr double kFallbackMaxAccel = 1.0e9;
constexpr double kBcImpulseTau = 1.0;

MotionResult motion_step(Mirror& m, dauntless::TransformStore& store,
                         const std::vector<int64_t>& rows, int64_t player,
                         double dt, int64_t begin, bool resume_past_warp);

}  // namespace dauntless::combat
