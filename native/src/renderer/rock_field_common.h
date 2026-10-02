// native/src/renderer/rock_field_common.h
// Internal helpers shared by the rock-fields bands (rock_near.cc, rock_mid.cc).
// Not an installed header: include it as "rock_field_common.h" from a .cc
// beside it.
#pragma once
#include <cstdint>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_access.hpp>
#include <renderer/rock_random.h>

namespace renderer::rockfield::detail {

// Restored from the retired far-tier belt generator (0fb9e591 far_field.cc).
inline std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
    rockrand::Rng r{h ^ (v + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2))};
    return r.next();
}

// Frustum planes (Gribb-Hartmann), normalised: as far_field.cc's.
struct Frustum {
    glm::vec4 planes[6];
    explicit Frustum(const glm::mat4& vp) {
        const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                        r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
        planes[0] = r3 + r0; planes[1] = r3 - r0; planes[2] = r3 + r1;
        planes[3] = r3 - r1; planes[4] = r3 + r2; planes[5] = r3 - r2;
        for (auto& p : planes) p /= glm::length(glm::vec3(p));
    }
    bool sphere(const glm::vec3& c, float r) const {   // false: wholly outside a plane
        for (const auto& pl : planes)
            if (glm::dot(glm::vec3(pl), c) + pl.w < -r) return false;
        return true;
    }
};

}  // namespace renderer::rockfield::detail
