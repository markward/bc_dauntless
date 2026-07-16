// native/src/renderer/dynamic_lights.cc
#include "renderer/dynamic_lights.h"

#include <algorithm>

namespace renderer {

float segment_distance(const glm::vec3& a, const glm::vec3& b,
                        const glm::vec3& p) {
    const glm::vec3 ab = b - a;
    const float h = glm::clamp(
        glm::dot(p - a, ab) / std::max(glm::dot(ab, ab), 1e-6f), 0.0f, 1.0f);
    return glm::length(p - (a + ab * h));
}

// MUST MATCH the GLSL implementation added in Task 9 exactly (see the
// contract comment on the declaration in dynamic_lights.h).
float dynamic_light_attenuation(float d, float radius) {
    if (radius <= 0.0f) return 0.0f;
    const float ratio = d / radius;
    const float w = glm::clamp(1.0f - ratio * ratio * ratio * ratio, 0.0f, 1.0f);
    return (w * w) / (d * d + 1.0f);
}

namespace {
constexpr glm::vec3 kLuminanceWeights(0.2126f, 0.7152f, 0.0722f);

float light_score(const DynamicLightDescriptor& light,
                   const glm::vec3& instance_center_ws,
                   float instance_radius_ws) {
    const float d = segment_distance(light.pos_a, light.pos_b,
                                      instance_center_ws);
    const float d_eff = std::max(0.0f, d - instance_radius_ws);
    const float luminance = glm::dot(light.color, kLuminanceWeights);
    return light.intensity * luminance *
           dynamic_light_attenuation(d_eff, light.radius);
}
}  // namespace

int select_dynamic_lights(
    const std::vector<DynamicLightDescriptor>& lights,
    const glm::vec3& instance_center_ws, float instance_radius_ws,
    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw>& out) {
    // Fixed-size top-K by insertion: no allocation, no full sort. Track the
    // K best scores seen so far and their slot; a new candidate that beats
    // the current minimum evicts it.
    std::array<float, kMaxDynamicLightsPerDraw> scores{};
    int count = 0;

    for (const auto& light : lights) {
        const float score = light_score(light, instance_center_ws,
                                         instance_radius_ws);
        if (score <= 0.0f) continue;

        if (count < kMaxDynamicLightsPerDraw) {
            out[count] = light;
            scores[count] = score;
            ++count;
            continue;
        }

        // Array is full: find the current minimum and evict it if beaten.
        int min_idx = 0;
        for (int i = 1; i < count; ++i) {
            if (scores[i] < scores[min_idx]) min_idx = i;
        }
        if (score > scores[min_idx]) {
            out[min_idx] = light;
            scores[min_idx] = score;
        }
    }

    return count;
}

}  // namespace renderer
