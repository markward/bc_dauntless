// AvoidObstacles' obstacle test -- see ai_avoid.h. A port of the SDK's
// AvoidObstacles.NeedToAvoid (AI/Preprocessors.py:1781-1842) after its
// lDontAvoidTypes loop; each block names the Python it stands for. TGPoint3's
// Length / SqrLength / Dot (engine/appc/math.py) are `x*x + y*y + z*z`,
// left to right.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/ai_avoid.h"

#include <cmath>

namespace dauntless::combat {

bool need_to_avoid(const AvoidInputs& in) {
    // vDiff = pObject.GetWorldLocation(); vDiff.Subtract(ship); vDiff.Length()
    const double dx = in.obj_pos[0] - in.ship_pos[0];
    const double dy = in.obj_pos[1] - in.ship_pos[1];
    const double dz = in.obj_pos[2] - in.ship_pos[2];
    const double fDist = std::sqrt(dx * dx + dy * dy + dz * dz);
    if (fDist < (in.personal_space_radius + in.obj_radius)) return true;

    // vOtherVelocity: the object's GetVelocityTG(), or SetXYZ(0, 0, 0).
    const double ovx = in.is_physics ? in.obj_vel[0] : 0.0;
    const double ovy = in.is_physics ? in.obj_vel[1] : 0.0;
    const double ovz = in.is_physics ? in.obj_vel[2] : 0.0;
    // vVelDiff = ship velocity; vVelDiff.Subtract(vOtherVelocity)
    const double vx = in.ship_vel[0] - ovx;
    const double vy = in.ship_vel[1] - ovy;
    const double vz = in.ship_vel[2] - ovz;
    const double a = vx * vx + vy * vy + vz * vz;
    if (a > 0) {
        // vPosDiff = ship; vPosDiff.Subtract(object); b = 2 * Dot(vVelDiff)
        const double px = in.ship_pos[0] - in.obj_pos[0];
        const double py = in.ship_pos[1] - in.obj_pos[1];
        const double pz = in.ship_pos[2] - in.obj_pos[2];
        const double b = 2.0 * (px * vx + py * vy + pz * vz);
        const double fRadiusSum = (in.personal_space_radius + in.obj_radius);
        const double c = -(fRadiusSum * fRadiusSum) + (px * px + py * py + pz * pz);

        double fHitTime = -1.0;
        const double fSqrtPart = b * b - 4.0 * a * c;
        if (fSqrtPart >= 0) {
            const double fSqrt = std::sqrt(fSqrtPart);
            const double t1 = (-b + fSqrt) / (2.0 * a);
            const double t2 = (-b - fSqrt) / (2.0 * a);
            if (t1 < t2) {
                fHitTime = (t1 >= 0) ? t1 : t2;
            } else {
                fHitTime = (t2 >= 0) ? t2 : t1;
            }
        }
        if (fHitTime >= 0) {
            if (fHitTime < in.prediction_time) return true;
        }
    }
    return false;
}

}  // namespace dauntless::combat
