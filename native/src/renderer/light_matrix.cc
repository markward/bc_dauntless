#include "renderer/shadow_light.h"
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <cmath>

namespace renderer {

namespace {
// Deterministic perpendicular to L for the light "up" — NOT a world-up
// reference; just the numerically-stable axis least aligned with L.
glm::vec3 stable_up(const glm::vec3& L) {
    glm::vec3 a;
    float ax = std::abs(L.x), ay = std::abs(L.y), az = std::abs(L.z);
    if (ax <= ay && ax <= az)      a = glm::vec3(1, 0, 0);
    else if (ay <= az)             a = glm::vec3(0, 1, 0);
    else                           a = glm::vec3(0, 0, 1);
    glm::vec3 right = glm::normalize(glm::cross(a, L));
    return glm::cross(L, right);
}
}  // namespace

ShadowLight compute_light_matrix(const glm::vec3& player_pos_ws,
                                 float player_bound_radius_gu,
                                 const glm::vec3& light_dir_ws,
                                 const ShadowFitParams& params) {
    const glm::vec3 L = glm::normalize(light_dir_ws); // toward the sun
    const float R = std::clamp(params.radius_scale * player_bound_radius_gu,
                               params.radius_min_gu, params.radius_max_gu);
    const glm::vec3 center = player_pos_ws;
    const glm::vec3 up = stable_up(L);

    // Eye sits caster_reach toward the sun; look back along -L through center.
    const glm::vec3 eye = center + L * params.caster_reach_gu;
    const glm::mat4 view = glm::lookAt(eye, center, up);

    // Depth runs from the eye (near=0, at the sun-side reach) to receiver_depth
    // behind the center.
    const float near_p = 0.0f;
    const float far_p  = params.caster_reach_gu + params.receiver_depth_gu;
    glm::mat4 proj = glm::ortho(-R, R, -R, R, near_p, far_p);

    // Texel-snap the center in light space to kill edge crawl.
    const glm::mat4 vp0 = proj * view;
    glm::vec4 origin = vp0 * glm::vec4(center, 1.0f);
    const float half_res = params.resolution * 0.5f;
    glm::vec2 origin_tx = glm::vec2(origin.x, origin.y) * half_res;
    glm::vec2 rounded = glm::vec2(std::round(origin_tx.x), std::round(origin_tx.y));
    glm::vec2 offset = (rounded - origin_tx) / half_res;
    proj[3][0] += offset.x;
    proj[3][1] += offset.y;

    ShadowLight out;
    out.view_proj = proj * view;
    out.texel_world_size = 2.0f * R / static_cast<float>(params.resolution);
    return out;
}

}  // namespace renderer
