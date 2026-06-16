// native/src/scenegraph/src/hull_craters.cc
#include "scenegraph/hull_craters.h"

#include <algorithm>

namespace scenegraph {

void HullCraterField::add(const glm::vec3& point_body,
                          const glm::vec3& impact_dir_body,
                          const glm::vec3& normal_body,
                          float radius, float depth) {
    const float clamped_depth = std::clamp(depth, 0.0f, kMaxDepth);

    // Allocate the first free slot. (Merge and eviction are added in later
    // tasks; for now an over-full field silently drops the crater.)
    HullCrater* target = nullptr;
    for (auto& c : slots_) {
        if (!c.active) { target = &c; break; }
    }
    if (target == nullptr) return;

    *target = HullCrater{
        point_body, impact_dir_body, normal_body,
        radius, clamped_depth, next_seq_++, /*active=*/true,
    };
}

std::size_t HullCraterField::count() const {
    std::size_t n = 0;
    for (const auto& c : slots_) if (c.active) ++n;
    return n;
}

}  // namespace scenegraph
