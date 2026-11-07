#pragma once

// SelectTarget's candidate rating, native (phase 6 AI part 2, Task 3).
//
// The SDK's SelectTarget.GetTargetRating (AI/Preprocessors.py:1481-1608) was
// 20.7% of AI time at 128 ships, mostly its popularity loop over every ship in
// the set. For a stock instance (engine/appc/ai_native.py) the host's
// combat_ai_target_rating gathers the nine factors -- popularity from the set
// index (set_index.h), everything else as the SDK reads it
// (native/src/host/host_bindings.cc, the `rating` namespace) -- and this sums
// them, bit for bit (-ffp-contract=off, the SDK's operand order, libm acos as
// CPython's math.acos, IEEE sqrt as math.sqrt):
//
//   vDifference = target - ours; fDistance = sqrt(x*x + y*y + z*z)
//   fDistanceGood = 0.0; fAngleGood = 0.0
//   if fDistance > 0:
//     fDistanceGood = min_full_good_distance / fDistance, capped at 1.0
//     fAngle = forward.Dot(vDifference) / fDistance, clamped to [-1, 1]
//     fAngleGood = 1.0 - (acos(fAngle) / pi)
//   fWeaponsGood = weapons_sum / weapons_count when weapons_count > 0
//   fRating = 0.0; for each (factor, weight) in the SDK's list order:
//     fRating = fRating + (factor * weight)
//
// The caller has already turned every Python number into the double Python
// would compute with (an int only where the conversion and every product are
// exact), so plain double arithmetic here is Python's arithmetic.

namespace dauntless::combat {

struct RatingInputs {
    double our_pos[3];             // pOurShip.GetWorldLocation()
    double target_pos[3];          // pTarget.GetWorldLocation()
    double our_forward[3];         // pOurShip.GetWorldForwardTG()
    double min_full_good_distance; // self.fMinimumFullGoodDistance
    double is_target;              // fIsTargetGood: 0.0 or 1.0
    double shield;                 // fShieldGood
    double weapons_sum;            // 0.0 + each GetCombinedConditionPercentage, in match order
    long long weapons_count;       // fTotal
    double hull;                   // fHullGood
    double damage;                 // fDamageDealt
    double priority;               // fPriority
    double popularity;             // fPopularity
    // fDistanceFactor, fInFrontFactor, fIsTargetFactor, fShieldFactor,
    // fWeaponsFactor, fHullFactor, fDamageFactor, fPriorityFactor,
    // fPopularityFactor: the SDK's list order.
    double weights[9];
};

// SDK SelectTarget.GetTargetRating's fRating for a target (the -1 no-ship
// return is the caller's).
double target_rating(const RatingInputs& in);

}  // namespace dauntless::combat
