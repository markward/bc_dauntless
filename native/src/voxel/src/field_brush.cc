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

    // Smallest cell axis: the field may be anisotropic, and every
    // representability floor below has to hold on the WORST axis.
    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));

    // Lateral half-extent covers the shader's OUTWARD rim perturbation, not
    // just the nominal radius -- see kCarveRimAmp.
    const float lat    = radius * (1.0f + kCarveRimAmp);
    const float depth  = std::max(kCarveDepthFactor * radius,
                                  kCarveDepthFloorCells * min_cell);
    const float offset = kCarveFieldOffsetCells * min_cell;

    // Only cells within the brush's AABB can change. The oblate is oriented
    // along `n`, which is arbitrary in body frame, so the axis-aligned box
    // must use the LARGEST half-extent on every axis. The offset dilates the
    // brush's zero crossing outward by offset/|grad|, and the shallowest
    // gradient is min(lat, depth)/max(lat, depth) -- so bound the reach by
    // scaling the largest extent by the same dilation factor the shader
    // computes. Under-sizing this box would silently truncate the carve at
    // the box edge.
    const float dil   = 1.0f + offset / std::min(lat, depth);
    const float reach = std::max(lat, depth) * dil;
    const glm::vec3 lo = center_body - glm::vec3(reach);
    const glm::vec3 hi = center_body + glm::vec3(reach);
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
        // NB: `lat_vec`, not `lat` -- `lat` is the brush's lateral half-extent
        // above, and shadowing it here silently reverted the rim dilation.
        const glm::vec3 lat_vec = v - along * n;
        const float ld          = glm::length(lat_vec);

        // Signed distance to the oblate, scaled back to model units. Dividing
        // each axis by its own half-extent turns the ellipsoid into a unit
        // sphere; multiplying the result by the SMALLEST half-extent ensures
        // the correct sign at the ellipsoid boundary (shape fidelity). Monotonicity
        // is unconditional given the max() structure below: the scaling never
        // looks at d_old, only at -d_brush, so the max() cannot restore material.
        const float u = ld / lat;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(lat, depth);

        const std::size_t i = f.index(x, y, z);
        const float d_old = static_cast<float>(f.dist[i]) * f.scale;
        // `+ offset` dilates the carve by a constant in the brush's own
        // distance units. It is added to the BRUSH only, never to d_old, so
        // the max() still cannot restore material: monotonicity holds.
        const float d_new = std::max(d_old, -d_brush + offset);

        float q = std::round(d_new / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[i] = static_cast<std::int8_t>(q);
    }
}

}  // namespace voxel
