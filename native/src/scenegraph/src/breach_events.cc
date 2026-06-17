#include "scenegraph/breach_events.h"
#include <algorithm>
#include <limits>

namespace scenegraph {

void BreachEventRing::push(const glm::vec3& center_body, float radius,
                            const glm::vec3& surface_normal,
                            float birth_time, std::uint64_t seed) {
    // Find a free slot first.
    for (auto& e : slots_) {
        if (!e.active) {
            e = BreachEvent{center_body, radius, surface_normal, birth_time, seed, true};
            return;
        }
    }
    // All slots occupied: overwrite the oldest (smallest birth_time).
    // Tie-break: when all slots share the same birth_time, the search finds
    // no slot strictly older than slots_[0], so slot 0 is overwritten
    // (deterministic — no UB, consistent across calls).
    BreachEvent* oldest = &slots_[0];
    for (auto& e : slots_) {
        if (e.birth_time < oldest->birth_time) oldest = &e;
    }
    *oldest = BreachEvent{center_body, radius, surface_normal, birth_time, seed, true};
}

void BreachEventRing::tick(float now) {
    for (auto& e : slots_) {
        if (e.active && (now - e.birth_time) >= kEventLife) {
            e.active = false;
        }
    }
}

std::size_t BreachEventRing::count() const {
    std::size_t n = 0;
    for (const auto& e : slots_) if (e.active) ++n;
    return n;
}

} // namespace scenegraph
