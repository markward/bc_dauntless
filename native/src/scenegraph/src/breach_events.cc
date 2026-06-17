#include "scenegraph/breach_events.h"
#include <algorithm>
#include <limits>

namespace scenegraph {

void BreachEventRing::push(const glm::vec3& center_body, float radius,
                            float birth_time, std::uint64_t seed) {
    // Find a free slot first.
    for (auto& e : slots_) {
        if (!e.active) {
            e = BreachEvent{center_body, radius, birth_time, seed, true};
            return;
        }
    }
    // All slots occupied: overwrite the oldest (smallest birth_time).
    BreachEvent* oldest = &slots_[0];
    for (auto& e : slots_) {
        if (e.birth_time < oldest->birth_time) oldest = &e;
    }
    *oldest = BreachEvent{center_body, radius, birth_time, seed, true};
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
