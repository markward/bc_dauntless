// native/src/renderer/rock_shading.cc
#include "renderer/rock_shading.h"

#include <glad/glad.h>

#include <glm/glm.hpp>

#include <scenegraph/camera.h>

#include "renderer/frame.h"
#include "renderer/shader.h"

// Defined in frame.cc (global namespace), read the way draw_model reads it.
namespace dauntless_nan_debug { bool enabled(); }

namespace renderer {

void configure_rock_program(Shader& s, const scenegraph::Camera& cam, const Lighting& lighting,
                            float ambient_scale, float rim_strength, unsigned white,
                            unsigned black) {
    (void)white;   // no shared uniform reads it today; callers bind it per draw

    // Per-frame uniforms, exactly as submit_opaque_in_pass's configure_common.
    s.use();
    s.set_mat4("u_view", cam.view_matrix());
    s.set_mat4("u_proj", cam.proj_matrix());
    s.set_vec3("u_camera_pos_ws", glm::vec3(glm::inverse(cam.view_matrix())[3]));
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }

    // Every per-instance feature of the opaque path is off for rocks.
    s.set_int("u_decal_count", 0);
    s.set_int("u_glow_region_count", 0);
    s.set_int("u_dyn_light_count", 0);
    s.set_int("u_carve_enabled", 0);
    s.set_int("u_carve_count", 0);
    s.set_int("u_carve_invert", 0);
    s.set_int("u_hull_field", 6);
    s.set_int("u_hull_field_enabled", 0);
    s.set_int("u_frame_enabled", 0);
    s.set_int("u_damage_decal", 3);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, black);
    s.set_int("u_hull_decal_count", 0);
    s.set_int("u_decal_enabled_mask", 0);
    s.set_mat4("u_node_rest_fix", glm::mat4(1.0f));
    s.set_float("u_emissive_scale", 1.0f);
    glActiveTexture(GL_TEXTURE7);
    glBindTexture(GL_TEXTURE_2D, 0);       // draw_model's undamaged scuff binding
    s.set_int("u_scuff_map_ok", 0);
    s.set_int("u_nan_debug", dauntless_nan_debug::enabled() ? 1 : 0);
    s.set_float("u_rim_strength", rim_strength);
    s.set_mat4("u_model", glm::mat4(1.0f));    // unused by the rock vertex shaders; never stale
    s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));   // no body-frame feature reads it
    {
        // Sun shadow, as draw_model binds it (unit 5).
        const bool shadows_on = active_shadow_enabled();
        const int unit = 5;
        s.set_int("u_shadows_enabled", shadows_on ? 1 : 0);
        s.set_int("u_shadow_map", unit);
        if (shadows_on) {
            const ShadowLight& light = active_shadow_light();
            s.set_mat4("u_light_view_proj", light.view_proj);
            s.set_float("u_shadow_texel", light.texel_world_size);
            glActiveTexture(GL_TEXTURE0 + unit);
            glBindTexture(GL_TEXTURE_2D, active_shadow_texture());
        }
    }
    glActiveTexture(GL_TEXTURE0);
}

}  // namespace renderer
