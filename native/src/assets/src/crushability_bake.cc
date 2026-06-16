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
#include <cstdio>
#include <cstdlib>
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

void bake_crushability(MeshCpu& mesh, const CrushabilityParams& params) {
    if (mesh.vertices.empty()) return;
    if (mesh.indices.size() < 3) {
        // No triangles: no ray can hit anything, so every vertex is "no hit".
        for (auto& vert : mesh.vertices) vert.crushability = params.no_hit_value;
        return;
    }

    // Bounding-box diagonal gives a per-mesh, scale-invariant reference: a
    // vertex is "thin" relative to the size of its own shape.
    glm::vec3 lo(std::numeric_limits<float>::infinity());
    glm::vec3 hi(-std::numeric_limits<float>::infinity());
    for (const auto& vert : mesh.vertices) {
        lo = glm::min(lo, vert.position);
        hi = glm::max(hi, vert.position);
    }
    const float diag = glm::length(hi - lo);
    const float ref = params.thick_fraction * diag;
    const float max_dist = (diag > 0.0f) ? diag : 1.0f;  // no ray exceeds the shape

    for (auto& vert : mesh.vertices) {
        const float nlen = glm::length(vert.normal);
        if (nlen < 1e-8f) {            // degenerate normal -> can't cast inward
            vert.crushability = params.no_hit_value;
            continue;
        }
        const glm::vec3 inward = -vert.normal / nlen;
        const float thickness = probe_thickness(mesh, vert.position, inward, max_dist);
        vert.crushability = std::isinf(thickness)
            ? params.no_hit_value
            : crushability_from_thickness(thickness, ref);
    }

    // Diagnostic (DAUNTLESS_DEBUG_DEFORM=1): per-mesh crushability stats. If
    // min/max/avg are all ~0 the deform displacement (depth*fall*crush) is
    // suppressed regardless of crater depth — i.e. the hull "resists" too hard.
    static const bool dbg = std::getenv("DAUNTLESS_DEBUG_DEFORM") != nullptr;
    if (dbg && !mesh.vertices.empty()) {
        float cmin = 1.0f, cmax = 0.0f, csum = 0.0f;
        for (const auto& v : mesh.vertices) {
            cmin = std::min(cmin, v.crushability);
            cmax = std::max(cmax, v.crushability);
            csum += v.crushability;
        }
        std::fprintf(stderr,
            "[crush] verts=%zu min=%.2f max=%.2f avg=%.2f diag=%.2f ref=%.2f\n",
            mesh.vertices.size(), cmin, cmax,
            csum / static_cast<float>(mesh.vertices.size()), diag, ref);
    }
}

}  // namespace assets
