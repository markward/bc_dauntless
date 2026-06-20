#pragma once
#include <glm/glm.hpp>

namespace renderer {

struct ShadowLight {
    glm::mat4 view_proj{1.0f};
    float texel_world_size = 0.0f;
};

struct ShadowFitParams {
    float radius_scale     = 3.0f;
    float radius_min_gu    = 2.0f;
    float radius_max_gu    = 40.0f;
    float caster_reach_gu  = 30.0f;
    float receiver_depth_gu = 30.0f;
    int   resolution       = 2048;
};

// light_dir_ws points TOWARD the sun (matches Lighting::directional_dir_ws).
ShadowLight compute_light_matrix(const glm::vec3& player_pos_ws,
                                 float player_bound_radius_gu,
                                 const glm::vec3& light_dir_ws,
                                 const ShadowFitParams& params);

}  // namespace renderer
