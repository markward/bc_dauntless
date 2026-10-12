// native/src/renderer/include/renderer/bridge_pbr.h
//
// CPU twin of the bridge PBR path in shaders/bridge.frag (spec
// docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §9). Every
// function here has a GLSL counterpart of the same name in bridge.frag; keep
// them in step — bridge_pbr_test.cc pins these, and the frame tests assert
// the shader against them.
#pragma once
#include <algorithm>
#include <cmath>
#include <glm/glm.hpp>
#include <renderer/bridge_lighting_tuning.h>

namespace renderer::pbr {

inline constexpr float kGamma = 2.2f;
inline constexpr float kPi = 3.14159265358979f;

// The pipeline is gamma-space end to end (textures upload GL_RGBA8, resolve
// never encodes): the bridge decodes to light, then re-encodes.
inline glm::vec3 decode(glm::vec3 c) { return glm::pow(glm::max(c, glm::vec3(0.0f)), glm::vec3(kGamma)); }
inline glm::vec3 encode(glm::vec3 c) { return glm::pow(glm::max(c, glm::vec3(0.0f)), glm::vec3(1.0f / kGamma)); }

inline float D_ggx(float n_dot_h, float rough) {
    const float a = rough * rough, a2 = a * a;
    const float d = n_dot_h * n_dot_h * (a2 - 1.0f) + 1.0f;
    return a2 / std::max(kPi * d * d, 1e-7f);
}
inline float G_schlick_ggx(float n_dot_x, float k) { return n_dot_x / (n_dot_x * (1.0f - k) + k); }
inline float G_smith(float n_dot_v, float n_dot_l, float rough) {
    const float k = (rough + 1.0f) * (rough + 1.0f) / 8.0f;
    return G_schlick_ggx(n_dot_v, k) * G_schlick_ggx(n_dot_l, k);
}
inline glm::vec3 F_schlick(float cos_t, glm::vec3 f0) {
    const float m = std::pow(std::clamp(1.0f - cos_t, 0.0f, 1.0f), 5.0f);
    return f0 + (glm::vec3(1.0f) - f0) * m;
}
// Roughness-aware Schlick (Lagarde): a rough surface's Fresnel rises less
// toward grazing -- at rough 1 a dielectric stays at F0 at every angle, at
// rough 0 this IS F_schlick. Weights the AMBIENT diffuse only (spot lights
// keep F_schlick(VdotH); the probe term's Fresnel is in the BRDF LUT).
inline glm::vec3 F_schlick_rough(float cos_t, glm::vec3 f0, float rough) {
    const float m = std::pow(std::clamp(1.0f - cos_t, 0.0f, 1.0f), 5.0f);
    return f0 + (glm::max(glm::vec3(1.0f - rough), f0) - f0) * m;
}
inline glm::vec3 f0_for(glm::vec3 albedo_lin, float metal) {
    return glm::mix(glm::vec3(0.04f), albedo_lin, metal);
}
inline float spot_falloff(float d, float range) {
    const float r = d / std::max(range, 1e-4f);
    const float w = std::clamp(1.0f - r * r * r * r, 0.0f, 1.0f);
    return w * w / (d * d + 1.0f);
}
inline float spot_cone(float cos_angle, float cos_outer, float cos_inner) {
    const float t = std::clamp((cos_angle - cos_outer) / std::max(cos_inner - cos_outer, 1e-5f), 0.0f, 1.0f);
    const float s = t * t * (3.0f - 2.0f * t);
    return s * s;
}
inline glm::vec3 combine(glm::vec3 diffuse_lin, glm::vec3 spec_lin, float diffuse_max) {
    const glm::vec3 d = encode(diffuse_lin);
    const glm::vec3 ds = encode(diffuse_lin + spec_lin);
    return diffuse_ceiling(d, diffuse_max) + glm::max(ds - d, glm::vec3(0.0f));
}
// Clamps the pow base to avoid NaN when n_dot_v + ao is negative. The GLSL twin
// (shaders/bridge.frag) must clamp the same way.
inline float specular_occlusion(float n_dot_v, float ao, float rough) {
    return std::clamp(std::pow(std::max(n_dot_v + ao, 0.0f), std::exp2(-16.0f * rough - 1.0f)) - 1.0f + ao, 0.0f, 1.0f);
}
inline glm::vec3 box_project(glm::vec3 pos, glm::vec3 dir, glm::vec3 bmin, glm::vec3 bmax, glm::vec3 probe) {
    const glm::vec3 inv = 1.0f / dir;
    const glm::vec3 t1 = (bmax - pos) * inv, t2 = (bmin - pos) * inv;
    const glm::vec3 tf = glm::max(t1, t2);
    const float t = std::min(tf.x, std::min(tf.y, tf.z));
    return glm::normalize(pos + dir * t - probe);
}
inline float prefilter_mip(float rough) { return std::clamp(rough, 0.0f, 1.0f) * float(kBridgeProbeMips - 1); }

// ── Area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──
// A rectangle: centre c, half-axes u and v (perpendicular); it emits toward
// cross(u, v) only. Diffuse is the exact horizon-clipped Lambert edge
// integral (Heitz); specular is GGX at a representative point (Karis),
// its lobe widened by the light's size. Twins of bridge.frag's same names.

// spot_falloff's window alone: 1 inside, 0 at `range`.
inline float range_window(float d, float range) {
    const float r = d / std::max(range, 1e-4f);
    const float w = std::clamp(1.0f - r * r * r * r, 0.0f, 1.0f);
    return w * w;
}

inline void rect_corners(glm::vec3 c, glm::vec3 u, glm::vec3 v, glm::vec3 out[4]) {
    out[0] = c - u - v; out[1] = c + u - v; out[2] = c + u + v; out[3] = c - u + v;
}

inline float area_integrate_edge(glm::vec3 v1, glm::vec3 v2) {
    const float cos_t = std::clamp(glm::dot(v1, v2), -1.0f, 1.0f);
    const float theta = std::acos(cos_t);
    return glm::cross(v1, v2).z * ((theta > 0.001f) ? theta / std::sin(theta) : 1.0f);
}

// Heitz's ClipQuadToHorizon: clip L[0..3] (tangent space, z up) against
// z = 0; returns the vertex count (0, 3, 4 or 5) in L[0..n-1].
inline int area_clip_quad_to_horizon(glm::vec3 L[5]) {
    int config = 0;
    if (L[0].z > 0.0f) config += 1;
    if (L[1].z > 0.0f) config += 2;
    if (L[2].z > 0.0f) config += 4;
    if (L[3].z > 0.0f) config += 8;
    int n = 0;
    switch (config) {
        case 0: n = 0; break;
        case 1: n = 3; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[3].z * L[0] + L[0].z * L[3]; break;
        case 2: n = 3; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; break;
        case 3: n = 4; L[2] = -L[2].z * L[1] + L[1].z * L[2]; L[3] = -L[3].z * L[0] + L[0].z * L[3]; break;
        case 4: n = 3; L[0] = -L[3].z * L[2] + L[2].z * L[3]; L[1] = -L[1].z * L[2] + L[2].z * L[1]; break;
        case 5: n = 0; break;
        case 6: n = 4; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; break;
        case 7: n = 5; L[4] = -L[3].z * L[0] + L[0].z * L[3]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; break;
        case 8: n = 3; L[0] = -L[0].z * L[3] + L[3].z * L[0]; L[1] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = L[3]; break;
        case 9: n = 4; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[2].z * L[3] + L[3].z * L[2]; break;
        case 10: n = 0; break;
        case 11: n = 5; L[4] = L[3]; L[3] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; break;
        case 12: n = 4; L[1] = -L[1].z * L[2] + L[2].z * L[1]; L[0] = -L[0].z * L[3] + L[3].z * L[0]; break;
        case 13: n = 5; L[4] = L[3]; L[3] = L[2]; L[2] = -L[1].z * L[2] + L[2].z * L[1]; L[1] = -L[1].z * L[0] + L[0].z * L[1]; break;
        case 14: n = 5; L[4] = -L[0].z * L[3] + L[3].z * L[0]; L[0] = -L[0].z * L[1] + L[1].z * L[0]; break;
        default: n = 4; break;
    }
    if (n == 3) L[3] = L[0];
    if (n == 4) L[4] = L[0];
    return n;
}

// The fraction of the cosine-weighted hemisphere at (p, n) the quad covers.
inline float rect_form_factor(glm::vec3 p, glm::vec3 n, const glm::vec3 c[4]) {
    const glm::vec3 ln = glm::normalize(glm::cross(c[1] - c[0], c[3] - c[0]));
    if (glm::dot(ln, p - c[0]) <= 0.0f) return 0.0f;                  // behind: one-sided
    const glm::vec3 helper = (std::fabs(n.z) < 0.9f) ? glm::vec3(0, 0, 1) : glm::vec3(1, 0, 0);
    const glm::vec3 t1 = glm::normalize(glm::cross(helper, n));
    const glm::vec3 t2 = glm::cross(n, t1);
    glm::vec3 L[5];
    for (int i = 0; i < 4; ++i) {
        const glm::vec3 d = c[i] - p;
        L[i] = glm::vec3(glm::dot(d, t1), glm::dot(d, t2), glm::dot(d, n));
    }
    L[4] = L[0];
    const int m = area_clip_quad_to_horizon(L);
    if (m == 0) return 0.0f;
    for (int i = 0; i < 5; ++i) {
        const float len = glm::length(L[i]);
        if (len < 1e-9f) return 0.0f;                                  // on a corner
        L[i] /= len;
    }
    float s = area_integrate_edge(L[0], L[1]) + area_integrate_edge(L[1], L[2]) +
              area_integrate_edge(L[2], L[3]);
    if (m >= 4) s += area_integrate_edge(L[3], L[4]);
    if (m == 5) s += area_integrate_edge(L[4], L[0]);
    return std::clamp(std::fabs(s) / (2.0f * kPi), 0.0f, 1.0f);
}

inline glm::vec3 rect_nearest(glm::vec3 p, glm::vec3 c, glm::vec3 u, glm::vec3 v) {
    const float s = std::clamp(glm::dot(p - c, u) / std::max(glm::dot(u, u), 1e-12f), -1.0f, 1.0f);
    const float t = std::clamp(glm::dot(p - c, v) / std::max(glm::dot(v, v), 1e-12f), -1.0f, 1.0f);
    return c + u * s + v * t;
}

// Where the ray p + t r meets the rectangle's plane, clamped into it; the
// nearest point when the ray runs away from (or along) the light.
inline glm::vec3 rect_representative(glm::vec3 p, glm::vec3 r, glm::vec3 c, glm::vec3 u, glm::vec3 v) {
    const glm::vec3 n = glm::normalize(glm::cross(u, v));
    const float denom = glm::dot(r, n);
    if (denom > -1e-6f) return rect_nearest(p, c, u, v);
    const float t = glm::dot(c - p, n) / denom;
    if (t <= 0.0f) return rect_nearest(p, c, u, v);
    return rect_nearest(p + r * t, c, u, v);
}

struct AreaTerms { glm::vec3 diffuse{0.0f}; glm::vec3 spec{0.0f}; };

// Spec §16.8: a snapped strip is a chain of rectangles. Each gives
// its own representative-point highlight, so where two meet both put a full
// highlight on the joint (measured on DBridge Map 3: 0.75 + 0.75 against
// 0.65 mid-segment -- bloom blobs at every joint). At an end JOINED to a
// neighbour (bit 0: the -u end, bit 1: the +u end) the highlight fades to
// half as the reflection reaches that end and to nothing past it, over the
// lobe's footprint d x a_eff, so the two neighbours sum to one. Free ends
// are untouched (a lone rectangle is exactly as before).
inline float area_join_weight(glm::vec3 p, glm::vec3 r, glm::vec3 c, glm::vec3 u, glm::vec3 nl,
                              int joins, float margin) {
    if (joins == 0) return 1.0f;
    const float denom = glm::dot(r, nl);
    float t = denom < -1e-6f ? glm::dot(c - p, nl) / denom : -1.0f;
    const glm::vec3 hit = t > 0.0f ? p + r * t : p - nl * glm::dot(p - c, nl);
    const float half = glm::length(u);
    const float along = glm::dot(hit - c, u) / std::max(half, 1e-6f);
    const float m = std::max(margin, 1e-3f);
    float w = 1.0f;
    if (joins & 1) w *= std::clamp(0.5f + (along + half) / m, 0.0f, 1.0f);
    if (joins & 2) w *= std::clamp(0.5f + (half - along) / m, 0.0f, 1.0f);
    return w;
}

inline AreaTerms area_light(glm::vec3 p, glm::vec3 N, glm::vec3 V, float n_dot_v,
                            glm::vec3 albedo, float metal, float rough, glm::vec3 f0,
                            glm::vec3 c, glm::vec3 u, glm::vec3 v,
                            glm::vec3 radiance, float range, int joins = 0) {
    AreaTerms out;
    const glm::vec3 uv = glm::cross(u, v);
    if (glm::dot(uv, uv) < 1e-12f) return out;                         // zero-area: no light
    const glm::vec3 nl = glm::normalize(uv);
    if (glm::dot(nl, p - c) <= 0.0f) return out;                       // behind / on it
    const glm::vec3 near_p = rect_nearest(p, c, u, v);
    const float dn = glm::length(near_p - p);
    const float win = range_window(dn, range);
    if (win <= 0.0f) return out;
    glm::vec3 q[4];
    rect_corners(c, u, v, q);
    const float ff = rect_form_factor(p, N, q);
    const glm::vec3 Ln = (near_p - p) / std::max(dn, 1e-4f);
    const glm::vec3 h = Ln + V;
    const float hl = glm::length(h);
    const glm::vec3 Hd = hl > 1e-6f ? h / hl : N;                       // Ln == -V: no half-vector
    const glm::vec3 Fd = F_schlick(std::max(glm::dot(V, Hd), 0.0f), f0);
    const glm::vec3 rad = radiance * win;
    out.diffuse = (glm::vec3(1.0f) - Fd) * (1.0f - metal) * albedo * rad * ff;
    const glm::vec3 rep = rect_representative(p, glm::reflect(-V, N), c, u, v);
    const float d = std::max(glm::length(rep - p), 1e-4f);
    const glm::vec3 L = (rep - p) / d;
    const float n_dot_l = std::max(glm::dot(N, L), 0.0f);
    if (n_dot_l <= 0.0f) return out;
    const float cos_l = std::max(glm::dot(-L, nl), 0.0f);
    const float area = 4.0f * glm::length(u) * glm::length(v);
    const float omega = std::min(area * cos_l / (d * d), 2.0f * kPi);
    const float a = rough * rough;
    const float a_eff = std::min(a + std::sqrt(area / kPi) / (2.0f * d), 1.0f);
    const glm::vec3 H = glm::normalize(L + V);
    const glm::vec3 F = F_schlick(std::max(glm::dot(V, H), 0.0f), f0);
    out.spec = D_ggx(std::max(glm::dot(N, H), 0.0f), std::sqrt(a_eff)) *
               G_smith(n_dot_v, n_dot_l, rough) * F /
               std::max(4.0f * n_dot_v * n_dot_l, 1e-4f) * rad * n_dot_l * omega *
               area_join_weight(p, glm::reflect(-V, N), c, u, nl, joins, d * a_eff);
    return out;
}

}  // namespace renderer::pbr
