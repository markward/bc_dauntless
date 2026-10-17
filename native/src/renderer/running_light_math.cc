// native/src/renderer/running_light_math.cc
#include "renderer/running_light_math.h"

#include <algorithm>
#include <cmath>

namespace renderer {

float running_light_blink_alpha(float t, float period, float duration, float phase) {
    if (!std::isfinite(period) || !std::isfinite(duration) ||
        !std::isfinite(t) || !std::isfinite(phase))
        return 1.0f;
    if (duration <= 0.0f || period <= 0.0f || duration >= period) return 1.0f;
    float u = std::fmod(static_cast<double>(t) + static_cast<double>(phase),
                        static_cast<double>(period));
    if (u < 0.0f) u += period;
    const float r = 0.1f * duration;
    if (u >= duration) return 0.0f;
    if (u < r) return u / r;
    if (u > duration - r) return (duration - u) / r;
    return 1.0f;
}

float running_light_world_size(float size, float size_gu_per_radius, float min_px,
                               float distance, float proj11, int viewport_h) {
    const float world = std::max(0.0f, size) * size_gu_per_radius;
    if (proj11 <= 0.0f || viewport_h <= 0 || distance <= 0.0f) return world;
    const float per_px = 2.0f * distance / (proj11 * static_cast<float>(viewport_h));
    return std::max(world, min_px * per_px);
}

}  // namespace renderer
