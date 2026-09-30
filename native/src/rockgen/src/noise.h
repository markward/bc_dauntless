// native/src/rockgen/src/noise.h
#pragma once

#include <glm/glm.hpp>
#include <cmath>
#include <cstdint>

// Deterministic value noise + fbm for rock-catalogue generation (ported from feat/procedural-asteroids).
//
// File-local and self-contained ON PURPOSE. `hash3` already exists twice in
// the renderer (hit_vfx_pass.cc:89, particle_pass.cc:38) but both return a
// vec2 for sprite jitter; neither is a scalar 3D field. Adding a third copy of
// those would be worse than one purpose-built helper here.
//
// Integer hashing, not trig: `fract(sin(x))` diverges across GPU/CPU and
// across compilers, and this generator's output must be bit-reproducible.
namespace rockgen::detail {

inline std::uint32_t hash_u32(std::uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

inline float hash_to_unit(std::int32_t x, std::int32_t y, std::int32_t z,
                          std::uint32_t seed) {
    std::uint32_t h = hash_u32(static_cast<std::uint32_t>(x) * 0x9e3779b9u
                             ^ hash_u32(static_cast<std::uint32_t>(y) * 0x85ebca6bu
                             ^ hash_u32(static_cast<std::uint32_t>(z) * 0xc2b2ae35u ^ seed)));
    return static_cast<float>(h & 0x00ffffffu) / static_cast<float>(0x01000000u);
}

/// Value noise in [0,1], trilinearly interpolated with a smoothstep fade.
inline float value_noise(const glm::vec3& p, std::uint32_t seed) {
    const glm::vec3 i = glm::floor(p);
    const glm::vec3 f = p - i;
    const glm::vec3 w = f * f * (3.0f - 2.0f * f);   // smoothstep fade
    const auto ix = static_cast<std::int32_t>(i.x);
    const auto iy = static_cast<std::int32_t>(i.y);
    const auto iz = static_cast<std::int32_t>(i.z);

    auto c = [&](int dx, int dy, int dz) {
        return hash_to_unit(ix + dx, iy + dy, iz + dz, seed);
    };
    const float x00 = glm::mix(c(0,0,0), c(1,0,0), w.x);
    const float x10 = glm::mix(c(0,1,0), c(1,1,0), w.x);
    const float x01 = glm::mix(c(0,0,1), c(1,0,1), w.x);
    const float x11 = glm::mix(c(0,1,1), c(1,1,1), w.x);
    return glm::mix(glm::mix(x00, x10, w.y), glm::mix(x01, x11, w.y), w.z);
}

/// Fractal sum. Returns roughly [0,1].
inline float fbm(const glm::vec3& p, std::uint32_t seed, int octaves) {
    float sum = 0.0f, amp = 0.5f, norm = 0.0f;
    glm::vec3 q = p;
    for (int o = 0; o < octaves; ++o) {
        sum  += amp * value_noise(q, seed + static_cast<std::uint32_t>(o) * 131u);
        norm += amp;
        q    *= 2.02f;      // slightly off 2.0 to avoid axis-aligned banding
        amp  *= 0.5f;
    }
    return norm > 0.0f ? sum / norm : 0.0f;
}

}  // namespace rockgen::detail
