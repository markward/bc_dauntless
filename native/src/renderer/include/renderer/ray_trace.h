// native/src/renderer/include/renderer/ray_trace.h
#pragma once

#include <optional>
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
std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist);

}  // namespace renderer
