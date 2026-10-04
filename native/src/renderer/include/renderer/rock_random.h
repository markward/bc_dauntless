// native/src/renderer/include/renderer/rock_random.h
// Deterministic RNG helpers shared by the minor-rocks field and the far
// tier's cell generator (docs/superpowers/specs/2026-10-01-far-tier-design.md).
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <glm/glm.hpp>

namespace renderer::rockrand {

// splitmix64: deterministic, platform-independent (std::*_distribution is not).
struct Rng {
    std::uint64_t s;
    std::uint64_t next() {
        std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    float unit() { return static_cast<float>(next() >> 40) / 16777216.0f; }  // [0,1)
};

inline glm::vec3 unit_vector(Rng& r) {
    const float z = r.unit() * 2.0f - 1.0f;
    const float t = r.unit() * 6.28318530718f;
    const float s = std::sqrt(std::max(0.0f, 1.0f - z * z));
    return {s * std::cos(t), s * std::sin(t), z};
}

// Inverse CDF of pdf ∝ r^-a on [lo, hi].
inline float power_law(float u, float lo, float hi, float a) {
    if (hi <= lo) return lo;
    if (std::fabs(a - 1.0f) < 1e-4f)
        return lo * std::pow(hi / lo, u);
    const float e = 1.0f - a;
    const float l = std::pow(lo, e), h = std::pow(hi, e);
    return std::pow(l + u * (h - l), 1.0f / e);
}

}  // namespace renderer::rockrand
