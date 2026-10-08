// native/src/renderer/include/renderer/bridge_lighting_tuning.h
//
// Every tuning number of the bridge's lighting, in one place. BridgePass
// feeds these to bridge.frag; tests pin the shader against the CPU twins here.
#pragma once

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>

namespace renderer {

struct BridgeLightingTuning {
    float down_top    = 1.0f;   // up-facing surfaces' share of the bridge ambient
    float down_bottom = 0.25f;  // down-facing (ceiling)
    float ao_radius   = 24.0f;  // view-space units (Mark's live pick, 2026-10-08)
    float ao_strength = 2.0f;   // (Mark's live pick)
    float ao_bias     = 0.5f;   // view-space units
    float diffuse_max = 0.88f;  // lit-surface ceiling; must stay < bloom threshold (bloom_pass.h, 0.9)
};
inline constexpr BridgeLightingTuning kBridgeLighting{};
inline constexpr glm::vec3 kBridgeUp{0.0f, 0.0f, 1.0f};  // set instances draw with identity transforms
// Crease angle for generated normals lives with the generator:
// assets::detail::kSetNormalCreaseDeg (native/src/assets/src/normal_gen.h).

/// CPU twin of bridge.frag's diffuse_ceiling (tests pin the GLSL to it).
/// Lit (reflecting) bridge surfaces must never feed bloom -- only emitters
/// glow. Identity below 70% of the ceiling, then a soft exponential roll that
/// approaches `diffuse_max` and never reaches it. All channels are scaled by
/// the max channel's roll, so hue holds. `diffuse_max <= 0` disables it.
inline glm::vec3 diffuse_ceiling(glm::vec3 c, float diffuse_max) {
    if (diffuse_max <= 0.0f) return c;
    const float b = std::max({c.r, c.g, c.b});
    const float knee = 0.7f * diffuse_max;
    if (b <= knee) return c;
    const float range = diffuse_max - knee;
    const float r = knee + range * (1.0f - std::exp(-(b - knee) / range));
    return c * (r / b);
}

}  // namespace renderer
