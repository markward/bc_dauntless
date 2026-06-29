#include "scenegraph/hull_carve.h"

#include <algorithm>

namespace scenegraph {

HullCarve& HullCarveField::add(const glm::vec3& center_body, float influ_radius,
                               float strength, const glm::vec3& surface_normal) {
    const float merge_dist = kMergeFactor * influ_radius;
    for (auto& c : slots_) {
        if (!c.active) continue;
        if (glm::length(center_body - c.center_body) <= merge_dist) {
            c.strength += strength;                          // accumulate
            c.influ_radius = std::max(c.influ_radius, influ_radius);
            c.center_body = center_body;                     // freshest center
            // Keep the existing slot's surface_normal + visible radius (the
            // caller re-derives radius from the grown strength, monotonically).
            c.seq = next_seq_++;                             // refresh age
            return c;
        }
    }
    HullCarve* target = nullptr;
    for (auto& c : slots_) { if (!c.active) { target = &c; break; } }
    if (target == nullptr) {
        // Evict the smallest visible carve; tie-break on oldest (smallest seq).
        HullCarve* victim = &slots_[0];
        for (auto& c : slots_) {
            if (c.radius < victim->radius ||
                (c.radius == victim->radius && c.seq < victim->seq)) {
                victim = &c;
            }
        }
        target = victim;
    }
    *target = HullCarve{center_body, influ_radius, strength,
                        /*radius=*/0.0f, surface_normal, next_seq_++,
                        /*active=*/true};
    return *target;
}

std::size_t HullCarveField::count() const {
    std::size_t n = 0;
    for (const auto& c : slots_) if (c.active) ++n;
    return n;
}

}  // namespace scenegraph
