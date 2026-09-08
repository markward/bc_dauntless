// native/src/voxel/src/distance_field.cc
#include <voxel/distance_field.h>

#include <cmath>

namespace voxel {

// Closest point on a triangle (Ericson, Real-Time Collision Detection, 5.1.5).
// Region-by-region: the three vertices, the three edges, then the interior.
float point_triangle_distance(const glm::vec3& p, const Tri& t) {
    const glm::vec3 ab = t.b - t.a;
    const glm::vec3 ac = t.c - t.a;
    const glm::vec3 ap = p - t.a;

    const float d1 = glm::dot(ab, ap);
    const float d2 = glm::dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) return glm::length(ap);          // vertex a

    const glm::vec3 bp = p - t.b;
    const float d3 = glm::dot(ab, bp);
    const float d4 = glm::dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) return glm::length(bp);            // vertex b

    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {                  // edge ab
        const float denom = d1 - d3;
        const float v = (std::abs(denom) > 1e-20f) ? d1 / denom : 0.0f;
        return glm::length(p - (t.a + v * ab));
    }

    const glm::vec3 cp = p - t.c;
    const float d5 = glm::dot(ab, cp);
    const float d6 = glm::dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) return glm::length(cp);            // vertex c

    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {                  // edge ac
        const float denom = d2 - d6;
        const float w = (std::abs(denom) > 1e-20f) ? d2 / denom : 0.0f;
        return glm::length(p - (t.a + w * ac));
    }

    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {    // edge bc
        const float denom = (d4 - d3) + (d5 - d6);
        const float w = (std::abs(denom) > 1e-20f) ? (d4 - d3) / denom : 0.0f;
        return glm::length(p - (t.b + w * (t.c - t.b)));
    }

    const float sum = va + vb + vc;                                 // interior
    // Guard: sum = |ab×ac|² = (2*Area)². Independent of p, depends on triangle alone.
    // Exactly-degenerate triangles (area=0) cannot reach here. Ultra-thin slivers
    // (area~1e-11) can: their interior region is real, but sum shrinks below 1e-20
    // epsilon due to quadratic scaling. Returns distance to vertex a: finite, safe, approximate.
    if (!(std::abs(sum) > 1e-20f)) return glm::length(ap);
    const float inv = 1.0f / sum;
    return glm::length(p - (t.a + ab * (vb * inv) + ac * (vc * inv)));
}

}  // namespace voxel
