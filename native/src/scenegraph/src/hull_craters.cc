// native/src/scenegraph/src/hull_craters.cc
#include "scenegraph/hull_craters.h"

#include <algorithm>
#include <glm/glm.hpp>

namespace scenegraph {

void HullCraterField::add(const glm::vec3& point_body,
                          const glm::vec3& impact_dir_body,
                          const glm::vec3& normal_body,
                          float radius, float depth) {
    const float clamped_depth = std::clamp(depth, 0.0f, kMaxDepth);

    // 1. Merge into a co-located crater: deepen it (accumulation). Deformation
    //    is weapon-class-agnostic, so any active crater in range is a merge
    //    target — a torpedo, a phaser, or a collision all cave the same spot.
    const float merge_dist = kMergeFactor * radius;
    for (auto& c : slots_) {
        if (!c.active) continue;
        if (glm::length(point_body - c.point_body) <= merge_dist) {
            c.depth = std::min(kMaxDepth, c.depth + clamped_depth);
            c.radius = std::max(c.radius, radius);   // a wider re-hit grows it
            c.impact_dir_body = impact_dir_body;     // freshest shove direction
            c.normal_body = normal_body;             // freshest surface normal
            c.seq = next_seq_++;                     // refresh age (a reinforced
                                                     // crater survives eviction)
            return;
        }
    }

    // 2. Allocate the first free slot. (Eviction is added in the next task; an
    //    over-full field silently drops the crater for now.)
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
