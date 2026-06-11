// native/src/renderer/include/renderer/particle_math.h
#pragma once
#include <glm/glm.hpp>
#include <algorithm>
#include <cmath>

namespace renderer {

/// Piecewise-linear keyframe evaluation over parallel (ts[], vs[]) arrays of
/// length n, clamped outside [ts[0], ts[n-1]]. n<=0 returns 1.0 (no curve).
inline float curve_lerp1(const float* ts, const float* vs, int n, float t) {
    if (n <= 0) return 1.0f;
    if (t <= ts[0]) return vs[0];
    if (t >= ts[n - 1]) return vs[n - 1];
    for (int i = 1; i < n; ++i) {
        if (t <= ts[i]) {
            const float span = ts[i] - ts[i - 1];
            const float f = (span > 1e-9f) ? (t - ts[i - 1]) / span : 0.0f;
            return vs[i - 1] + f * (vs[i] - vs[i - 1]);
        }
    }
    return vs[n - 1];
}

/// Max simultaneously-live particles for an emitter: ceil(max_life / freq).
inline int particle_max_count(float emit_life, float emit_life_variance,
                              float emit_frequency) {
    const float max_life = emit_life + std::max(0.0f, emit_life_variance);
    if (emit_frequency <= 1e-6f) return 1;
    return std::max(1, static_cast<int>(std::ceil(max_life / emit_frequency)));
}

/// Birth age of the current occupant of slot i: the latest birth time
/// (i*freq + k*period) that is <= effect_age. Never exceeds effect_age.
inline float slot_birth_age(float effect_age, int i, int n, float emit_frequency) {
    const float period = static_cast<float>(n) * emit_frequency;
    if (period <= 1e-6f) return effect_age;
    const float phase = effect_age - static_cast<float>(i) * emit_frequency;
    const float k = std::floor(phase / period);
    return static_cast<float>(i) * emit_frequency + k * period;
}

/// World position of a particle with sub-age tau. The
/// -(1-inherit)*vel*tau term is the velocity-inherited trail.
inline glm::vec3 particle_world_pos(const glm::vec3& emit_pos_world,
                                    const glm::vec3& dir_world,
                                    const glm::vec3& emit_vel_world,
                                    float emit_velocity, float inherit,
                                    float tau) {
    return emit_pos_world
         + dir_world * (emit_velocity * tau)
         - emit_vel_world * ((1.0f - inherit) * tau);
}

/// A deterministic 3D offset of magnitude <= radius, derived from a
/// 2-component hash in [0,1) and an integer salt. Returns zero when radius<=0
/// (A1 behaviour). The salt decorrelates the r sample from h.x/h.y so
/// multiple draws with the same h but different salts are independent.
inline glm::vec3 emit_radius_offset(float radius, glm::vec2 h, int salt) {
    if (radius <= 0.0f) return glm::vec3(0.0f);
    const float theta = h.x * 6.2831853f;
    const float z   = h.y * 2.0f - 1.0f;                  // cos(phi) in [-1,1]
    const float rxy = std::sqrt(std::max(0.0f, 1.0f - z * z));
    const float frac = 0.5f + 0.5f * std::sin(static_cast<float>(salt) * 12.9898f);
    const float rr   = radius * std::cbrt(frac);           // uniform-in-sphere
    return glm::vec3(rr * rxy * std::cos(theta),
                     rr * rxy * std::sin(theta),
                     rr * z);
}

/// A 3D unit direction within cone_deg degrees of `axis`.
/// cone_deg >= 180 covers the full sphere. Uses a 2-component hash h in [0,1).
inline glm::vec3 random_cone_dir(const glm::vec3& axis, float cone_deg, glm::vec2 h) {
    const glm::vec3 a = (glm::length(axis) > 1e-6f)
                        ? glm::normalize(axis)
                        : glm::vec3(0.0f, -1.0f, 0.0f);
    const float cos_max = std::cos(std::min(cone_deg, 180.0f) * 0.0174532925f);
    const float cz = 1.0f - h.x * (1.0f - cos_max);      // cos(theta) in [cos_max, 1]
    const float sz = std::sqrt(std::max(0.0f, 1.0f - cz * cz));
    const float phi = h.y * 6.2831853f;
    // Build an orthonormal basis around a.
    const glm::vec3 up  = (std::abs(a.y) < 0.99f) ? glm::vec3(0.0f, 1.0f, 0.0f)
                                                    : glm::vec3(1.0f, 0.0f, 0.0f);
    const glm::vec3 t   = glm::normalize(glm::cross(up, a));
    const glm::vec3 b   = glm::cross(a, t);
    return glm::normalize(a * cz + (t * std::cos(phi) + b * std::sin(phi)) * sz);
}

}  // namespace renderer
