#pragma once

// FireScript's arithmetic, native (phase 6 AI part 2, Tasks 4 and 5).
//
// The host's combat_ai_fire_update (native/src/host/host_bindings.cc, the
// `fire` namespace) runs the SDK's FireScript.Update and everything it reaches
// (AI/Preprocessors.py:281-787) statement for statement for a stock instance
// (engine/appc/ai_native.py): every side effect and every read it cannot
// mirror is the very Python call the SDK makes, in the SDK's order. What it
// does natively is the vector arithmetic of TargetInRange, CheckGoodShot and
// PredictTargetLocation, on values read where an engine body is mirrored
// exactly (the transform store, `_velocity`, `_position`, ...), and the
// iLastUpdate cycle. All of that arithmetic, and every float comparison, is
// here, so the host never computes or compares a float itself
// (-ffp-contract=off applies to this library; the host's translation unit is
// not built with it). When every read of a method is native the host calls
// the method's composite below (fire_in_range,
// fire_predict_target_location, fire_good_shot_direction): what the gtests
// pin is what runs. The primitives serve the mixed cases.
//
// Each function is one engine body, bit for bit, in its operand order:
//   TGPoint3.Subtract / Add          x -= o.x ...  /  x += o.x ...
//   TGPoint3.SqrLength / Dot         x*x + y*y + z*z  /  x*o.x + y*o.y + z*o.z
//   TGPoint3.Unitize                 n = sqrt(SqrLength); if n > 1e-12: x /= n ...
//   TGPoint3.MultMatrixLeft(m)       x' = m00*x + m01*y + m02*z ... (column vector)
//   TGMatrix3.Transpose
//   ShipClass.GetPredictedPosition   t2 = 0.5*t*t; p.x + v.x*t + a.x*t2 ...

#include <cstddef>

namespace dauntless::combat {

struct FireVec {
    double x, y, z;
};

// TGMatrix3's nine entries, row-major (m00 m01 m02 m10 ... m22), as
// TGMatrix3.as_tuple() and the transform store's get_rotation order them.
struct FireMat {
    double m[9];
};

// FireScript.Update's `((self.iLastUpdate + 3) % (len(self.lWeapons) + 2)) - 2`
// with Python's floor modulo. The caller keeps |last| well inside long long
// and n_weapons >= 0.
long long fire_cycle(long long last, long long n_weapons);

void fire_subtract(FireVec& self, const FireVec& other);
void fire_add(FireVec& self, const FireVec& other);
double fire_sqr_length(const FireVec& v);
double fire_dot(const FireVec& a, const FireVec& b);
double fire_unitize(FireVec& v);
void fire_mult_matrix_left(FireVec& v, const FireMat& m);
FireMat fire_transpose(const FireMat& m);
FireVec fire_predicted_position(const FireVec& p, const FireVec& v, const FireVec& a, double t);
// `a / b` for the host, which must not do float arithmetic itself.
double fire_div(double a, double b);

// The SDK's two float comparisons, so the host compares nothing itself:
// `fSqrLength <= (fMaxFiringRange * fMaxFiringRange)` and
// `fDot >= self.fFireDotThreshold`.
bool fire_sqr_within(double sqr_length, double max_range);
bool fire_at_least(double dot, double threshold);

// TargetInRange after its reads: `vDiff.SqrLength() <= (fMaxFiringRange *
// fMaxFiringRange)` with vDiff = target - ship.
bool fire_in_range(const FireVec& target, const FireVec& ship, double max_range);

// PredictTargetLocation when every read is native and fSpeed is a float.
struct PredictInputs {
    FireVec target_pos;     // pTarget.GetWorldLocation() (each of its three calls)
    FireVec our_pos;        // pOurShip.GetWorldLocation()
    double speed;           // fSpeed
    bool physics;           // App.PhysicsObjectClass_Cast(pTarget) != None
    FireVec velocity;       // pPhysicsTarget.GetVelocityTG()
    FireVec acceleration;   // pPhysicsTarget.GetAccelerationTG()
    bool subsystem;         // `if pSubsystem:`
    FireVec subsystem_pos;  // pSubsystem.GetPositionTG()
    FireMat target_rot;     // pTarget.GetWorldRotation()
};

// The SDK's vPredicted; false where `fDistance / fSpeed` raises
// ZeroDivisionError (fSpeed zero).
bool fire_predict_target_location(const PredictInputs& in, FireVec& out);

// CheckGoodShot's `vTargetLocation.Subtract(ours);
// vTargetLocation.MultMatrixLeft(ourRotation.Transpose());
// vTargetLocation.Unitize()`.
FireVec fire_to_local_unit(FireVec predicted, const FireVec& our_pos, const FireMat& our_rot);

// CheckGoodShot's direction loop on the predicted point: the index of the
// first direction with `vTargetLocation.Dot(vDirection) >= threshold`, -1 if
// none (the SDK's `return 0`).
int fire_good_shot_direction(const FireVec& predicted, const FireVec& our_pos,
                             const FireMat& our_rot, const FireVec* dirs, std::size_t n,
                             double threshold);

// ── ChooseTargetSubsystem and ChooseTorpType (Task 5) ────────────────────────
// The host (the `fire` namespace) makes every Python call of
// ChooseTargetSubsystem, GetTargetableSubsystems, RateSubsystemForTargeting,
// PickTargetSubsystemFromList and ChooseTorpType (AI/Preprocessors.py:533-640,
// 789-1045) itself, in the SDK's order; when every value a sum reads is a
// plain float (or a small int the SDK only multiplies by a float), the sum is
// computed here. Anything else is Python's own arithmetic in the host.

// RateSubsystemForTargeting after its reads:
//   fDisabledCondition = GetDisabledPercentage() * fMaxCondition
//   fDamageToDisable = fCondition - fDisabledCondition if fCondition > it, else 0.0
//   fRating = 0.0 + fCritical*6.0 + fDamageToDisable*-0.0005
//             + fIsDisabled*(-3.0*bDisableFirst) + fCondition*-0.0005
//             + fHittable*1.0 + fSystemRating*1.0   (left to right)
struct SubsystemRatingInputs {
    double critical;             // float(pSubsystem.IsCritical())
    double max_condition;        // GetMaxCondition()
    double disabled_percentage;  // GetDisabledPercentage()
    double condition;            // GetCondition()
    double is_disabled;          // float(pSubsystem.IsDisabled())
    double hittable;             // IsHittableFromLocation(ours)
    double system_rating;        // fire_system_rating(first IsTypeOf hit)
    double disable_first;        // self.bDisableFirst
};
double fire_subsystem_rating(const SubsystemRatingInputs& in);

// RateSubsystemForTargeting's type table, in the SDK's order: CT_WEAPON_SYSTEM
// 5.0, CT_WEAPON 5.0, CT_SHIELD_SUBSYSTEM 5.0, CT_CLOAKING_SUBSYSTEM 4.0,
// CT_IMPULSE_ENGINE_SUBSYSTEM 3.0, CT_HULL_SUBSYSTEM -200.0. The rating of row
// `first_match` (the first whose IsTypeOf is true), 0.0 for none (-1).
constexpr int kFireSystemRatingRows = 6;
double fire_system_rating(int first_match);

// PickTargetSubsystemFromList's `fRating = 0.0 + fIsTargetRating*1.0 +
// fHealthyRating*-1.0 + fDisabledRating*-1.0`.
double fire_pick_rating(double is_target, double healthy, double disabled);

// `a > b` (fScore > fBestScore, fRating > fHighestRating, fRating >
// fTargetRating).
bool fire_greater(double a, double b);

// ChooseTorpType's per-type ideals (fIdealDistMin, fIdealDistMax,
// fIdealTargetSpeedMin, fIdealTargetSpeedMax) and fRating = damage - cost.
struct TorpIdeals {
    double dist_min, dist_max, speed_min, speed_max, rating;
};
TorpIdeals fire_torp_ideals(double launch_speed, double power_cost, double damage,
                            double guidance_lifetime, double turn_rate);

// The last FuzzyLogic threshold ChooseTorpType passes: `(fMax - fMin) * 1.5`
// when fMin > 0, else `fMax * 1.5`.
double fire_torp_far(double min, double max);

// `fScore = (0.25 * (fRating * (fLowIdeal + fHighIdeal))) + (fRating *
// (fLowIdeal' + fHighIdeal'))`: the distance memberships, then the speed ones.
double fire_torp_score(double rating, double dist_low, double dist_high, double speed_low,
                       double speed_high);

}  // namespace dauntless::combat
