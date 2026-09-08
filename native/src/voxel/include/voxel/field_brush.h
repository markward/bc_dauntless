// native/src/voxel/include/voxel/field_brush.h
#pragma once

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// Depth of a carve along the hit normal, as a fraction of its lateral radius.
/// MUST equal opaque.frag's kDepthFactor: the breach scoop still derives from
/// the sphere list, so hole and scoop only stay aligned while both use this
/// same oblate. Change one, change both, and live-test the pair.
inline constexpr float kCarveDepthFactor = 0.45f;

/// Subtract an oblate breach from the hull: full lateral radius `radius`,
/// kCarveDepthFactor * radius along `normal_body`, centred on the hull surface.
///
/// CSG subtraction on a signed distance field is `d = max(d, -d_brush)`, which
/// is monotonic: a carve can only ever remove material, never restore it. That
/// is what lets overlapping carves merge into one cavity instead of evicting
/// each other, which the fixed 24-slot sphere array could not do.
///
/// All arguments are body frame, MODEL UNITS. A degenerate normal falls back to
/// +Z rather than producing NaN. Empty field, non-positive radius, non-finite
/// radius, non-finite centre_body or normal_body components, or a carve
/// entirely off the grid are all no-ops.
void field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius);

}  // namespace voxel
