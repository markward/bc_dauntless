// native/src/renderer/rock_field_common.h
// Internal helpers shared by the rock-fields bands (rock_near.cc, rock_speck.cc, rock_puffs.cc).
// Not an installed header: include it as "rock_field_common.h" from a .cc
// beside it.
#pragma once
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_access.hpp>
#include <renderer/far_field.h>
#include <renderer/glm_exact.h>
#include <renderer/rock_random.h>

namespace renderer::rockfield::detail {

// Restored from the retired far-tier belt generator (0fb9e591 far_field.cc).
inline std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
    rockrand::Rng r{h ^ (v + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2))};
    return r.next();
}

// far::same_density plus the source id (the near band keys its cells by
// it). A view-space source's `centre` already includes the anchor
// (FarField::active_sources), so a real anchor move compares unequal.
inline bool same_generator(const far::DiscSource& a, const far::DiscSource& b) {
    return a.id == b.id && far::same_density(a, b);
}
// Element-wise, order included (the first snapping source wins a tile).
inline bool same_generators(const std::vector<far::DiscSource>& a,
                            const std::vector<far::DiscSource>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (!same_generator(a[i], b[i])) return false;
    return true;
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
    // glm::dot(vec3(plane), c) + w < -r, bit for bit, as scalars (Debug build).
    bool sphere(const glm::vec3& c, float r) const {   // false: wholly outside a plane
        for (const auto& pl : planes)
            if (glm_exact::dot3(pl.x, pl.y, pl.z, c.x, c.y, c.z) + pl.w < -r) return false;
        return true;
    }
    // The planes the sphere (c, r) does NOT lie wholly inside (bit i = plane
    // i). A point within r - rp - (rounding) of c passes sphere(p, rp) on
    // every other plane, so sphere_on(p, rp, mask) == sphere(p, rp) for it.
    unsigned straddled(const glm::vec3& c, float r, unsigned of = 0x3Fu) const {
        unsigned m = 0;
        for (unsigned i = 0; i < 6; ++i) {
            if (!(of >> i & 1u)) continue;   // known inside (a parent sphere's mask)
            const glm::vec4& pl = planes[i];
            if (!(pl.x * c.x + pl.y * c.y + pl.z * c.z + pl.w >= r)) m |= 1u << i;
        }
        return m;
    }
    // sphere(), testing only the planes in `mask`.
    bool sphere_on(const glm::vec3& c, float r, unsigned mask) const {
        for (unsigned i = 0; mask != 0; ++i, mask >>= 1) {
            if (!(mask & 1u)) continue;
            const glm::vec4& pl = planes[i];
            if (glm_exact::dot3(pl.x, pl.y, pl.z, c.x, c.y, c.z) + pl.w < -r) return false;
        }
        return true;
    }
};

}  // namespace renderer::rockfield::detail
