// native/src/assets/src/crushability_bake.cc
//
// Per-vertex hull "crushability" bake for hull-damage deformation (spec §2).
// PER-MESH approximation: each vertex's inward ray is cast against the vertex's
// own NiTriShape triangles, not the whole ship. Thin single-shape extremities
// (bow tip, saucer rim) crush; thick hull resists. Cross-mesh thickness would
// be large anyway (-> low crushability), so per-mesh is adequate and far
// cheaper than a whole-model cast.
#include "assets/crushability_bake.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>

namespace assets {

float crushability_from_thickness(float thickness, float ref) {
    if (ref <= 0.0f) return 0.0f;
    return std::clamp(1.0f - thickness / ref, 0.0f, 1.0f);
}

namespace {

// Local mirror of renderer::intersect_triangle (native/src/renderer/ray_trace.cc):
// Möller-Trumbore, double-sided, kDetEps parallel reject, kTMin self-hit guard.
// Duplicated (not shared) to keep the assets library free of a renderer
// dependency; de-duplication into a shared geometry lib is a future cleanup.
std::optional<float> ray_triangle_t(
    const glm::vec3& origin, const glm::vec3& dir, float max_dist,
    const glm::vec3& v0, const glm::vec3& v1, const glm::vec3& v2) {
    constexpr float kDetEps = 1e-7f;
    constexpr float kTMin   = 1e-5f;
    const glm::vec3 e1 = v1 - v0;
    const glm::vec3 e2 = v2 - v0;
    const glm::vec3 p  = glm::cross(dir, e2);
    const float det = glm::dot(e1, p);
    if (std::abs(det) < kDetEps) return std::nullopt;
    const float inv_det = 1.0f / det;
    const glm::vec3 s = origin - v0;
    const float u = glm::dot(s, p) * inv_det;
    if (u < 0.0f || u > 1.0f) return std::nullopt;
    const glm::vec3 q = glm::cross(s, e1);
    const float v = glm::dot(dir, q) * inv_det;
    if (v < 0.0f || u + v > 1.0f) return std::nullopt;
    const float t = glm::dot(e2, q) * inv_det;
    if (t < kTMin || t > max_dist) return std::nullopt;
    return t;
}

}  // namespace

float probe_thickness(const MeshCpu& mesh, const glm::vec3& origin,
                      const glm::vec3& dir, float max_dist) {
    float best = std::numeric_limits<float>::infinity();
    for (std::size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const glm::vec3& v0 = mesh.vertices[mesh.indices[i + 0]].position;
        const glm::vec3& v1 = mesh.vertices[mesh.indices[i + 1]].position;
        const glm::vec3& v2 = mesh.vertices[mesh.indices[i + 2]].position;
        const std::optional<float> t = ray_triangle_t(origin, dir, max_dist, v0, v1, v2);
        if (t && *t < best) best = *t;
    }
    return best;
}

}  // namespace assets
