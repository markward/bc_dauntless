// native/src/host/motion_write_apply.h
//
// Kernel M's write log applied by C (native motion phase 2, Task 5). The
// kernel (dauntless/combat/motion_step.h) writes the transform store and the
// mirror itself, and logs the Python attributes the step would have written;
// this stores them into the Python objects, quietly (no push: the mirror
// already holds them), exactly as engine/appc/native_motion.py
// `_apply_writes_py` (THE REFERENCE, kept) does, store for store:
//
//   per write, ship = ships[row] (an IndexError propagates at once, as the
//   reference's unguarded index does), then in the reference's order:
//     kDriftClear  ship.__dict__["_drift_velocity"] = None
//     kDriftSet    ship.__dict__["_drift_velocity"] = TGPoint3(dx, dy, dz)
//     kMotionVel   ship.__dict__["_motion_vel"] = (vx, vy, vz, speed)
//     kSpeed       ship.__dict__["_current_speed"] = speed
//     kVelocity    ship.__dict__["_velocity"] = TGPoint3(vx, vy, vz)
//     kSteer       sp = TGPoint3(*setpoint)
//                  ship.__dict__["_target_angular_velocity_setpoint"] = sp
//                  ship.__dict__["_target_angular_velocity_fraction"] = None
//                  ship.__dict__["_turn_goal"][1] = sp
//                  (a raise stops the rest of this store, as the
//                  reference's one function)
//     kAngVel      c = ship.__dict__["_current_angular_velocity"]
//                  c.x, c.y, c.z = cav      (in place, on its own object)
//     kAccel       ship.__dict__["_acceleration"] = (ax, ay, az)
//
// The TGPoint3 class is imported once from engine.appc.math and cached.
//
// EXCEPTIONS (as the reference): when one store raises, every later store
// (of the same write and of the later writes) is still applied, in order,
// and the first exception is then raised. False means a Python error is
// set. The GIL is held throughout; the only Python that runs is what the
// reference runs (TGPoint3.__init__, the stores).
#pragma once

#include <Python.h>

#include <span>

#include "dauntless/combat/motion_step.h"

namespace dauntless::host {

bool apply_motion_writes(PyObject* ships,
                         std::span<const combat::MotionWrite> w);

}  // namespace dauntless::host
