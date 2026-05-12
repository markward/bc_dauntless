// native/src/renderer/aabb.cc
#include "renderer/aabb.h"

#include <limits>

namespace renderer {

Aabb compute_aabb(std::span<const glm::vec3> positions) {
    if (positions.empty()) return {};
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    for (const auto& p : positions) {
        lo = glm::min(lo, p);
        hi = glm::max(hi, p);
    }
    return Aabb{
        .center = 0.5f * (lo + hi),
        .half_extents = 0.5f * (hi - lo),
    };
}

}  // namespace renderer
