#pragma once

// AvoidObstacles' obstacle test, native (phase 6 AI part 2, Task 2).
//
// The SDK's AvoidObstacles.TestCourseOverride walks GetNearObjects and calls
// NeedToAvoid (AI/Preprocessors.py:1769-1842) on every object but the ship
// itself; that call was 19% of AI time at 128 ships. For a stock instance
// (engine/appc/ai_native.py) the host's combat_ai_avoid_scan walks the
// iteration here instead. The lDontAvoidTypes filter, the reads and the
// per-object fallback to the SDK Python live in the binding
// (native/src/host/host_bindings.cc); this is only the arithmetic, after the
// type filter.
//
// need_to_avoid is that arithmetic, bit for bit (-ffp-contract=off, the same
// operand order, IEEE sqrt as CPython's math.sqrt):
//
//   vDiff = obj - ship; fDist = sqrt(x*x + y*y + z*z)
//   if fDist < (psr + r): 1
//   vOther = obj velocity if a physics object, else (0, 0, 0)
//   vVelDiff = ship velocity - vOther; a = vVelDiff.SqrLength()
//   if a > 0:
//     vPosDiff = ship - obj; b = 2 * vPosDiff.Dot(vVelDiff)
//     fRadiusSum = psr + r; c = -(fRadiusSum * fRadiusSum) + vPosDiff.SqrLength()
//     fHitTime = -1.0; fSqrtPart = b*b - 4.0*a*c
//     if fSqrtPart >= 0: t1 = (-b + s) / (2*a); t2 = (-b - s) / (2*a)
//       t1 < t2 ? (t1 >= 0 ? t1 : t2) : (t2 >= 0 ? t2 : t1)
//     if fHitTime >= 0 and fHitTime < fPredictionTime: 1
//   0
//
// Every comparison is written the same way round as the Python, so a NaN
// takes the same branch. No division can be by zero (a > 0).

namespace dauntless::combat {

struct AvoidInputs {
    double ship_pos[3];      // pShip.GetWorldLocation()
    double ship_vel[3];      // pShip.GetVelocityTG()
    double obj_pos[3];       // pObject.GetWorldLocation()
    double obj_vel[3];       // pObject.GetVelocityTG(), read only if is_physics
    double obj_radius;       // pObject.GetRadius()
    bool is_physics;         // App.PhysicsObjectClass_Cast(pObject) != None
    double personal_space_radius;  // the caller's fPersonalSpaceRadius
    double prediction_time;  // self.fPredictionTime
};

// SDK AvoidObstacles.NeedToAvoid after its lDontAvoidTypes loop: true for 1.
bool need_to_avoid(const AvoidInputs& in);

}  // namespace dauntless::combat
