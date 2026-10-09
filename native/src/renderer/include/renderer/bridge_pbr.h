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

}  // namespace renderer::pbr
