// native/src/renderer/include/renderer/dynamic_lights.h
#pragma once

#include <array>
#include <vector>

#include <glm/glm.hpp>

#include <renderer/frame.h>

namespace renderer {

/// Distance from point `p` to the segment `ab`. Degenerate segments
/// (a == b) reduce to the point distance |p - a| (the max() in the
/// denominator prevents a 0/0 division). Model: closest-point-on-segment
/// via clamped projection.
float segment_distance(const glm::vec3& a, const glm::vec3& b,
                        const glm::vec3& p);

/// UE-style windowed inverse-square attenuation. `radius <= 0` => 0.
/// MUST MATCH the GLSL implementation added in Task 9 exactly (same
/// formula, same clamp) so CPU-side selection/culling and the shader's
/// per-fragment falloff agree on where a light's contribution is zero.
/// If you change this, change the shader too.
float dynamic_light_attenuation(float d, float radius);

/// Select up to kMaxDynamicLightsPerDraw lights from `lights` that most
/// strongly affect an instance centered at `instance_center_ws` with
/// bounding radius `instance_radius_ws`. Score = intensity * luminance(color)
/// * dynamic_light_attenuation(d_eff, radius), where d_eff is the segment
/// distance from the light to the instance center minus the instance
/// radius (floored at 0). Zero-score lights are never selected. Pure,
/// allocation-free top-K by insertion into the fixed-size `out` array.
/// Returns the number of lights written (0..kMaxDynamicLightsPerDraw).
int select_dynamic_lights(
    const std::vector<DynamicLightDescriptor>& lights,
    const glm::vec3& instance_center_ws, float instance_radius_ws,
    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw>& out);

}  // namespace renderer
