// native/src/renderer/warp_in_flash_shape.cc
//
// CPU twin of shaders/warp_in_flash.frag. Every line here MUST match the
// shader's core_term / ring_term / streak_term.
#include "renderer/warp_in_flash_shape.h"

#include <algorithm>
#include <cmath>

namespace renderer {

namespace {

// GLSL smoothstep, so the twin evaluates exactly what the shader does.
float smoothstep_glsl(float e0, float e1, float x) {
    const float u = std::clamp((x - e0) / (e1 - e0), 0.0f, 1.0f);
    return u * u * (3.0f - 2.0f * u);
}

constexpr float kPi = 3.14159265358979f;

}  // namespace

float warp_in_core(float r, float t, const WarpInFlashParams& p) {
    if (t >= 1.0f || p.core_radii <= 0.0f) return 0.0f;
    const float a = smoothstep_glsl(0.0f, kCoreRise, t)
                  * (1.0f - smoothstep_glsl(kCoreRise, 1.0f, t));
    const float w = p.core_radii * (0.4f + 0.6f * a);
    const float q = r / w;
    return a * std::exp(-kCoreFalloff * q * q);
}

float warp_in_ring(float r, float t, const WarpInFlashParams& p) {
    if (t >= 1.0f || p.ring_radii <= 0.0f) return 0.0f;
    const float fade = (1.0f - t) * (1.0f - t) * smoothstep_glsl(0.0f, kRingRise, t);
    const float d = (r - p.ring_radii * t) / (kRingBand * p.ring_radii);
    return fade * std::exp(-d * d);
}

float warp_in_streak(float along, float across, float t, const WarpInFlashParams& p) {
    // t >= kStreakEnd is sin(pi * 1) == 0, stated exactly (float sin(pi) is
    // not quite 0).
    if (t >= kStreakEnd || p.core_radii <= 0.0f) return 0.0f;
    const float L = p.streak_radii * std::sin(kPi * std::clamp(t / kStreakEnd, 0.0f, 1.0f));
    if (!(L > 0.0f) || along < 0.0f || along > L) return 0.0f;
    const float y = across / (kStreakThickness * p.core_radii);
    return std::sqrt(1.0f - along / L) * std::exp(-y * y) * (1.0f - t);
}

}  // namespace renderer
