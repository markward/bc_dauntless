// native/src/renderer/include/renderer/bridge_light_cull.h
#pragma once

#include <glm/glm.hpp>

namespace renderer::bridge_cull {

// Per-draw light culling for the bridge pass (perf-register SIG-134,
// SIG-138). bridge.frag already skips a light per fragment once it is out of
// range or the fragment is behind a one-sided area light, but it still pays
// each light's setup at every pixel. These say, for a whole mesh's world box,
// whether ANY point of it can pass those same per-fragment tests; a light that
// cannot is skipped for that draw, so the image is unchanged. Conservative by
// construction: a box distance never exceeds a point's, and a plane test on
// the 8 corners bounds every point inside.

// Cull only when clearly beyond the range, never on a rounding tie.
inline constexpr float kRangeSlack = 1.001f;

// World AABB of the local box [lo, hi] under m.
inline void transform_box(const glm::mat4& m, glm::vec3 lo, glm::vec3 hi,
                          glm::vec3& out_lo, glm::vec3& out_hi) {
    out_lo = glm::vec3(1e30f);
    out_hi = glm::vec3(-1e30f);
    for (int i = 0; i < 8; ++i) {
        const glm::vec3 k((i & 1) ? hi.x : lo.x, (i & 2) ? hi.y : lo.y, (i & 4) ? hi.z : lo.z);
        const glm::vec3 p = glm::vec3(m * glm::vec4(k, 1.0f));
        out_lo = glm::min(out_lo, p);
        out_hi = glm::max(out_hi, p);
    }
}

// Can a spot at `pos` light any point of the box? spot_falloff is 0 from
// `range` on, whatever the cone.
inline bool spot_can_reach(glm::vec3 lo, glm::vec3 hi, glm::vec3 pos, float range) {
    const glm::vec3 gap = glm::max(glm::vec3(0.0f), glm::max(lo - pos, pos - hi));
    return glm::length(gap) < range * kRangeSlack;
}

// Can the rectangle (centre c, half-axes u and v, emitting toward
// cross(u, v)) light any point of the box? Mirrors accumulate_area_lights'
// zero-area, one-sided and range-window early-outs.
inline bool area_can_reach(glm::vec3 lo, glm::vec3 hi, glm::vec3 c, glm::vec3 u, glm::vec3 v,
                           float range) {
    const glm::vec3 uv = glm::cross(u, v);
    if (glm::dot(uv, uv) < 1e-12f) return false;
    const glm::vec3 nl = glm::normalize(uv);
    bool in_front = false;
    for (int i = 0; i < 8 && !in_front; ++i) {
        const glm::vec3 k((i & 1) ? hi.x : lo.x, (i & 2) ? hi.y : lo.y, (i & 4) ? hi.z : lo.z);
        in_front = glm::dot(nl, k - c) > 0.0f;
    }
    if (!in_front) return false;
    // The rectangle's own AABB: no point of it is nearer the box than this.
    const glm::vec3 ext = glm::abs(u) + glm::abs(v);
    const glm::vec3 rlo = c - ext, rhi = c + ext;
    const glm::vec3 gap = glm::max(glm::vec3(0.0f), glm::max(lo - rhi, rlo - hi));
    return glm::length(gap) < range * kRangeSlack;
}

}  // namespace renderer::bridge_cull
