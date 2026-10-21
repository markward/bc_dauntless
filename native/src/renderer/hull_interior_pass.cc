// native/src/renderer/hull_interior_pass.cc
//
// SPIKE (damage redesign): see hull_interior_pass.h. The draw follows
// BreachPass::draw_hull_proxy: the same vertex stage (breach.vert, body-frame
// v_body_pos), the same geometry submission (draw_model_positions_only), the
// fill as a sampler3D on unit 0.
#include <renderer/hull_interior_pass.h>

#include <renderer/carve_field_cache.h>
#include <renderer/frame.h>   // Lighting
#include <renderer/model_draw_helpers.h>
#include <renderer/pipeline.h>
#include <renderer/shader.h>

#include <scenegraph/camera.h>
#include <assets/model.h>

#include <glad/glad.h>

namespace renderer {

void HullInteriorPass::draw(const assets::Model& model, const glm::mat4& world_xf,
                            const scenegraph::Camera& camera, Pipeline& pipeline,
                            const plating::DamageList& list,
                            const plating::DeckBreakSet& deck_break, const float* params,
                            unsigned int fill_tex, const glm::vec3& fill_origin,
                            const glm::vec3& fill_cell, const glm::ivec3& fill_dims,
                            const Lighting& lighting, float ambient_scale, float now,
                            int stencil_value,
                            const std::unordered_map<int, glm::mat4>* node_overrides) {
    // Camera in this instance's body frame: one inverse per draw.
    const glm::vec3 cam_pos_ws = glm::vec3(glm::inverse(camera.view_matrix())[3]);
    const glm::mat4 world_inv = glm::inverse(world_xf);
    const glm::vec3 cam_pos_body = glm::vec3(world_inv * glm::vec4(cam_pos_ws, 1.0f));

    Shader& shader = pipeline.hull_interior_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());
    // breach.vert: v_body_pos = u_ship_world_inv * u_model * a_pos. u_model
    // is set per mesh by draw_model_positions_only.
    shader.set_mat4("u_ship_world_inv", world_inv);
    shader.set_vec3("u_camera_pos_body", cam_pos_body);

    // Fill on unit 0, bound and set on EVERY draw, even when 0: an unset
    // sampler defaults to unit 0 anyway, and a stale bind would leak the
    // previous hull's fill into this one.
    shader.set_int("u_fill", 0);
    shader.set_int("u_fill_ok", fill_tex != 0 ? 1 : 0);
    shader.set_vec3("u_fill_origin", fill_origin);
    shader.set_vec3("u_fill_cell", fill_cell);
    shader.set_ivec3("u_fill_dims", fill_dims);
    shader.set_float("u_fill_backing",
                     static_cast<float>(CarveFieldCache::kBackingIsovalue) / 255.0f);

    shader.set_float_array("u_plating", params, plating::kParamCount);
    shader.set_int("u_dmg_count", list.count);
    if (list.count > 0) {
        shader.set_vec4_array("u_dmg_a", list.a, list.count);
        shader.set_vec4_array("u_dmg_b", list.b, list.count);
        shader.set_vec4_array("u_dmg_c", list.c, list.count);
    }
    shader.set_int("u_db_count", deck_break.count);
    shader.set_int_array("u_db_idx", deck_break.idx.data(), deck_break.count);
    shader.set_vec3("u_ambient_light", lighting.ambient * ambient_scale);
    shader.set_float("u_time", now);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_3D, fill_tex);

    // Only this hull's cut pixels; colour and depth written, nothing blended.
    glEnable(GL_STENCIL_TEST);
    glStencilFunc(GL_EQUAL, stencil_value, 0xFF);
    glStencilMask(0x00);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glEnable(GL_DEPTH_TEST);
    // LESS, not LEQUAL: a cut face wrote no depth in the opaque pass (it was
    // discarded there), so it is strictly nearer than whatever is behind it.
    // An INTACT front face of this same mesh (a part seen through a blown-
    // through hole) wrote exactly this depth and must fail the test, or the
    // stencil EQUAL above would let it be repainted as rooms. The offset
    // pushes this draw a hair back so vertex-stage rounding between the
    // opaque and breach programs cannot make the intact face win by an ulp.
    glDepthFunc(GL_LESS);
    glEnable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(1.0f, 1.0f);
    glDepthMask(GL_TRUE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDisable(GL_BLEND);

    draw_model_positions_only(model, world_xf, shader, node_overrides);
    ++draw_calls_;

    // Back to stock. Stencil mask 0xFF, not 0: glClear(GL_STENCIL_BUFFER_BIT)
    // is masked by it.
    glDisable(GL_STENCIL_TEST);
    glDisable(GL_POLYGON_OFFSET_FILL);
    glStencilMask(0xFF);
    glDepthFunc(GL_LESS);
    glBindTexture(GL_TEXTURE_3D, 0);
}

}  // namespace renderer
