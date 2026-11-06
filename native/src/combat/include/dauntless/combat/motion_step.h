#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// Kernel M (native motion phase 2, Task 4): the per-ship motion step,
// a bit-exact port of engine/appc/ship_motion.py's step_and_record
// (_step_ship_motion with _integrate_rotation, _effective_motion, _cap_keep,
// step_vector_velocity, law_step_vector and _ramp_toward, then
// _record_acceleration) and engine/appc/drift.py's step. It reads only the combat
// mirror and the transform store, so it runs with the GIL released.
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
//      (law_step_vector) -- then the rotation. A row whose stored turn goal
//      may own its angular setpoint (_turn_goal with a setpoint) stops
//      PythonRow (TurnGoal): ShipClass._steer_turn_goal is Python's;
//   7. every row it finishes also records its acceleration, Python's
//      _record_acceleration (zero for a row passed over).
//
// Each row is computed into locals and committed at its end. Anything the
// kernel cannot answer as Python would -- an unrepresentable input (a
// point-or-none state 2, a -2 ref, a 6-float setpoint), a Python exception
// it would raise (math.cos of an infinity, a zero spin rate), a throw from
// a helper (std::invalid_argument, "answer in Python") -- stops PythonRow at
// that row with NOTHING of it written. A commit writes the store pose, the
// mirror's _current_speed, _current_angular_velocity, _velocity,
// _drift_velocity and _motion_vel, and appends one MotionWrite carrying
// exactly the attributes Python would have written (`what`; every finished
// row writes at least _acceleration, which only Python reads).
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
    kMotionVel = 32, kAccel = 64
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
