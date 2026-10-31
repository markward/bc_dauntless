// engine/systems/profile.py `evaluate`, the sensors column, bit for bit --
// see profile_eval.h. Mirrors the Python line for line; keep them in step.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/profile_eval.h"

namespace dauntless::combat {

double evaluate_sensors(const ProfileRow* rows, std::size_t n, double r) {
    if (n == 0) {
        return 0.0;                                    // CLEAR
    }
    if (r <= rows[0].distance_gu) {
        return rows[0].sensors;
    }
    for (std::size_t i = 0; i + 1 < n; ++i) {
        const ProfileRow& a = rows[i];
        const ProfileRow& b = rows[i + 1];
        if (r == b.distance_gu) {
            // An exact breakpoint is the row's stored value: a t = 1.0 lerp
            // is not bit-exact in IEEE754.
            return b.sensors;
        }
        if (r <= b.distance_gu) {
            const double span = b.distance_gu - a.distance_gu;
            const double t = (span <= 0.0) ? 0.0 : (r - a.distance_gu) / span;
            return a.sensors + (b.sensors - a.sensors) * t;
        }
    }
    return rows[n - 1].sensors;                        // also the NaN-r path
}

}  // namespace dauntless::combat
