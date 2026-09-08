// native/src/voxel/src/field_brush.cc
#include <voxel/field_brush.h>

#include <algorithm>
#include <cmath>

namespace voxel {

void field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius) {
    if (f.empty()) return;
    if (!(radius > 0.0f)) return;
    if (!(f.scale > 0.0f)) return;

    // Reject non-finite inputs. Infinity or NaN in center_body, normal_body, or
    // radius would lead to undefined behaviour in floor() and int casts below.
    if (!std::isfinite(center_body.x) || !std::isfinite(center_body.y) ||
        !std::isfinite(center_body.z) || !std::isfinite(radius) ||
        !std::isfinite(normal_body.x) || !std::isfinite(normal_body.y) ||
        !std::isfinite(normal_body.z)) {
        return;
    }

    glm::vec3 n = normal_body;
    const float nl = glm::length(n);
    n = (nl > 1e-4f) ? n / nl : glm::vec3(0.0f, 0.0f, 1.0f);

    const float depth = kCarveDepthFactor * radius;

    // Only cells within the brush's AABB can change. The lateral reach is the
    // full radius on every axis, so a radius-sized box bounds the oblate.
    const glm::vec3 lo = center_body - glm::vec3(radius);
    const glm::vec3 hi = center_body + glm::vec3(radius);
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)),
                          int(std::floor(g.z)));
    };
    glm::ivec3 c0 = to_cell(lo);
    glm::ivec3 c1 = to_cell(hi);
    c0 = glm::max(c0, glm::ivec3(0));
    c1 = glm::min(c1, f.dims - 1);
    if (c0.x > c1.x || c0.y > c1.y || c0.z > c1.z) return;   // wholly off-grid

    for (int z = c0.z; z <= c1.z; ++z)
    for (int y = c0.y; y <= c1.y; ++y)
    for (int x = c0.x; x <= c1.x; ++x) {
        const glm::vec3 p =
            f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        const glm::vec3 v = p - center_body;
        const float along   = glm::dot(v, n);
        const glm::vec3 lat = v - along * n;
        const float ld      = glm::length(lat);

        // Signed distance to the oblate, scaled back to model units. Dividing
        // each axis by its own half-extent turns the ellipsoid into a unit
        // sphere; multiplying the result by the SMALLEST half-extent ensures
        // the correct sign at the ellipsoid boundary (shape fidelity). Monotonicity
        // is unconditional given the max() structure below: it never looks at
        // d_old, only at -d_brush, so it cannot restore material.
        const float u = ld / radius;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(radius, depth);

        const std::size_t i = f.index(x, y, z);
        const float d_old = static_cast<float>(f.dist[i]) * f.scale;
        const float d_new = std::max(d_old, -d_brush);

        float q = std::round(d_new / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[i] = static_cast<std::int8_t>(q);
    }
}

}  // namespace voxel
