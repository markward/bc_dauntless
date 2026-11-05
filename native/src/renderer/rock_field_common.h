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
#include <renderer/frustum.h>
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

// Frustum moved to <renderer/frustum.h> (phase 5a: hulls cull with it too);
// the rock bands keep spelling it detail::Frustum.
using renderer::Frustum;

}  // namespace renderer::rockfield::detail
