// native/src/renderer/include/renderer/dynamic_lights.h
#pragma once

#include <array>
#include <vector>

#include <glm/glm.hpp>

#include <renderer/frame.h>

namespace scenegraph { class World; }

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

// Ship-scale ceiling (GU): dynamic lights at or below this radius keep the
// legacy absolute inverse-square falloff (ref == 1, byte-identical). Above it,
// the inverse-square reference grows so a station-scale light stays bright
// across its (large) volume instead of collapsing at a fixed 1 GU reference.
// MUST match the literal in opaque.frag.
constexpr float kDynLightShipCeilingGU = 40.0f;
// Falloff-reference growth per GU of radius above the ceiling. Tuning knob.
// MUST match the literal in opaque.frag.
constexpr float kDynLightFalloffK = 0.3f;

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

/// Resolve every ATTACHED light (instance_id != {0,0}) in `lights` to world
/// space through its instance's CURRENT `world` matrix, in place. Body
/// positions are unscaled GU, so the instance's uniform scale (column-0
/// length of `world`, the same recovery select_instance_dynamic_lights and
/// shield_pass.cc use) is divided back out: p_world = t + (R·s·p)/s.
/// Directions (cones only) are rotated and re-normalised. The resolved
/// entry's instance_id is reset to the sentinel so nothing downstream can
/// tell it was attached. An attached light whose instance no longer exists
/// is erased (particle_pass.cc makes the same choice). Unattached entries
/// are byte-identical before and after.
///
/// MUST run once per frame AFTER the transform-store sweep and every
/// set_world_transform push have landed (host frame(): right after
/// sync_instance_transforms_from_store()) — resolving at set_dynamic_lights
/// time would read last frame's matrices, which is the hull/light jitter
/// this exists to remove.
void resolve_attached_dynamic_lights(const scenegraph::World& world,
                                     std::vector<DynamicLightDescriptor>& lights);

}  // namespace renderer
