// SelectTarget's candidate rating -- see ai_rating.h. A port of the SDK's
// SelectTarget.GetTargetRating (AI/Preprocessors.py:1481-1608) after its
// reads; each block names the Python it stands for. TGPoint3's Length / Dot
// (engine/appc/math.py) are `x*x + y*y + z*z`, left to right.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/ai_rating.h"

#include <cmath>

namespace dauntless::combat {

namespace {
// math.pi
constexpr double kPi = 3.141592653589793;
}  // namespace

double target_rating(const RatingInputs& in) {
    // vDifference = pTarget.GetWorldLocation(); vDifference.Subtract(ours)
    const double dx = in.target_pos[0] - in.our_pos[0];
    const double dy = in.target_pos[1] - in.our_pos[1];
    const double dz = in.target_pos[2] - in.our_pos[2];

    // fDistance = vDifference.Length()
    double fDistanceGood = 0.0;
    const double fDistance = std::sqrt(dx * dx + dy * dy + dz * dz);
    if (fDistance > 0) {
        fDistanceGood = in.min_full_good_distance / fDistance;
        if (fDistanceGood > 1.0) fDistanceGood = 1.0;
    }

    double fAngleGood = 0.0;
    if (fDistance > 0) {
        // vOurForward.Dot(vDifference) / fDistance
        double fAngle = (in.our_forward[0] * dx + in.our_forward[1] * dy +
                         in.our_forward[2] * dz) /
                        fDistance;
        if (fAngle > 1.0) fAngle = 1.0;
        if (fAngle < -1.0) fAngle = -1.0;
        fAngle = std::acos(fAngle);  // math.acos: libm; a NaN passes through
        fAngleGood = (1.0 - (fAngle / kPi));
    }

    // if fTotal > 0: fWeaponsGood = fWeaponsGood / fTotal
    double fWeaponsGood = in.weapons_sum;
    if (in.weapons_count > 0) fWeaponsGood = fWeaponsGood / static_cast<double>(in.weapons_count);

    const double factors[9] = {fDistanceGood, fAngleGood,  in.is_target,
                               in.shield,     fWeaponsGood, in.hull,
                               in.damage,     in.priority,  in.popularity};
    double fRating = 0.0;
    for (int i = 0; i < 9; ++i) fRating = fRating + (factors[i] * in.weights[i]);
    return fRating;
}

}  // namespace dauntless::combat
