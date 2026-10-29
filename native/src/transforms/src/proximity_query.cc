// TransformStore::within_radius -- see transform_store.h.
//
// Its own translation unit so it can be compiled with -ffp-contract=off (see
// CMakeLists.txt): ProximityManager.GetNearObjects used to make this compare
// in Python, and a fused multiply-add would move objects sitting exactly on
// the radius in or out of the answer.
#include "dauntless/transform_store.h"

#if defined(__clang__)
#pragma clang fp contract(off)
#endif

namespace dauntless {

void TransformStore::within_radius(const std::uint32_t* handles, std::size_t n,
                                   const double point[3], double r2,
                                   std::uint8_t* out) const {
    for (std::size_t k = 0; k < n; ++k) {
        const std::uint32_t index = handles[2 * k];
        check(index, handles[2 * k + 1]);
        const Transform& t = slots_[index];
        const double dx = t.pos[0] - point[0];
        const double dy = t.pos[1] - point[1];
        const double dz = t.pos[2] - point[2];
        out[k] = (dx * dx + dy * dy + dz * dz <= r2) ? 1 : 0;
    }
}

}  // namespace dauntless
