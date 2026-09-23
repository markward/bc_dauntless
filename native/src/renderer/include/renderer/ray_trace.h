// native/src/renderer/include/renderer/ray_trace.h
#pragma once

#include <optional>
#include <unordered_map>
#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

struct RayHit {
    glm::vec3 point{0.0f};   // World-space surface point.
    glm::vec3 normal{0.0f};  // Unit, outward-facing relative to incoming ray.
    float     t = 0.0f;      // World-space distance from origin along direction.
};

/// Möller–Trumbore ray-vs-triangle, double-sided (no backface culling).
/// Returns the t-value along `direction` at which the ray intersects the
/// triangle (v0, v1, v2), or std::nullopt if it misses or the intersection
/// is behind the origin / past max_dist. Intersections within ~1e-5 of the
/// origin are also rejected (self-hit guard). `direction` does not need to
/// be unit length — the returned t is in the same units as |direction|.
std::optional<float> intersect_triangle(
    glm::vec3 origin, glm::vec3 direction, float max_dist,
    glm::vec3 v0, glm::vec3 v1, glm::vec3 v2);

/// Walk every CPU-data mesh in `model`, transformed by
/// `instance_world * node_world`, and return the closest hit along the ray
/// (origin, unit direction, max_dist) — or std::nullopt for no hit.
///
/// Performs a world-space bounding-sphere coarse reject first; models whose
/// bounding sphere the ray segment misses return std::nullopt immediately.
/// The returned normal is flipped so dot(normal, direction) <= 0.
/// `node_overrides` (nullptr or empty = none) is the instance's articulation /
/// severance map — the SAME map every draw pass composes through, so what you
/// can hit matches what you can see. A triangle belonging to an overridden node
/// is tested through that node's override instead of its baked rest position; a
/// SEVERED part (the zero matrix) drops out entirely and cannot be hit at all.
///
/// This matters beyond cosmetics: `combat.py`'s `_resolve_impact_point` runs
/// this trace for every weapon hit, and part-severance attributes damage from
/// the point it returns. A raised wing that traced to the rest pose would
/// accumulate no damage and never come off.
///
/// Costs nothing when absent, which is the normal case: a Bird of Prey's rest
/// pose IS its combat pose (wings down = armed), so combat traces with an empty
/// map.
std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist,
    const std::unordered_map<int, glm::mat4>* node_overrides = nullptr);

}  // namespace renderer
