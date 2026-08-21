// native/src/renderer/include/renderer/aabb.h
#pragma once

#include <span>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

struct Aabb {
    glm::vec3 center{0.0f};
    glm::vec3 half_extents{0.0f};
};

Aabb compute_aabb(std::span<const glm::vec3> positions);

inline Aabb compute_aabb(const std::vector<glm::vec3>& v) {
    return compute_aabb(std::span<const glm::vec3>(v));
}

/// AABB of every CPU-data mesh vertex in `model`, transformed into
/// model-local space via the node hierarchy (per-mesh local_transform
/// chained from root). Meshes whose nodes are unreachable or that lack
/// cpu_data are skipped.
Aabb compute_model_aabb(const assets::Model& model);

/// One shape's authored bounding sphere, in model-local space.
struct BoundSphere {
    glm::vec3 center{0.0f};
    float radius = 0.0f;
};

/// The authored per-shape bounding spheres of `model`, composed through the
/// node hierarchy into model-local space — the same chaining compute_model_aabb
/// applies to vertices.
///
/// This is the set of pieces a hull is actually made of, and it is the only
/// structured bound data a BC model carries: the files hold no separate
/// collision mesh, and no BC model authors the optional node-level bounding
/// volume. A single model-wide sphere or AABB cannot express a CONCAVE hull —
/// a starbase's docking bay is a void between pieces, so a ship parked in it
/// sits inside the model's overall bound while touching none of these.
///
/// Meshes with no cpu_data, an unreachable node, or a zero radius are skipped:
/// none of them describes a volume, and admitting them would create phantom
/// point-obstacles.
std::vector<BoundSphere> compute_model_bounds(const assets::Model& model);

}  // namespace renderer
