#include "scenegraph/hull_carve.h"

#include <algorithm>

namespace scenegraph {

void HullCarveField::add(const glm::vec3& center_body, float radius) {
    const float merge_dist = kMergeFactor * radius;
    for (auto& c : slots_) {
        if (!c.active) continue;
        if (glm::length(center_body - c.center_body) <= merge_dist) {
            c.radius = std::max(c.radius, radius);
            c.center_body = center_body;   // freshest center
            c.seq = next_seq_++;           // refresh age
            return;
        }
    }
    HullCarve* target = nullptr;
    for (auto& c : slots_) { if (!c.active) { target = &c; break; } }
    if (target == nullptr) {
        // Evict the smallest carve; tie-break on oldest (smallest seq).
        HullCarve* victim = &slots_[0];
        for (auto& c : slots_) {
            if (c.radius < victim->radius ||
                (c.radius == victim->radius && c.seq < victim->seq)) {
                victim = &c;
            }
        }
        target = victim;
    }
    *target = HullCarve{center_body, radius, next_seq_++, /*active=*/true};
}

std::size_t HullCarveField::count() const {
    std::size_t n = 0;
    for (const auto& c : slots_) if (c.active) ++n;
    return n;
}

}  // namespace scenegraph
