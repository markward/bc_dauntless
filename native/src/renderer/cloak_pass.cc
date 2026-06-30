// native/src/renderer/cloak_pass.cc
#include "renderer/cloak_pass.h"
#include "renderer/pipeline.h"

#include <assets/mesh.h>
#include <assets/model.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <vector>

namespace renderer {

CloakRefractionPass::~CloakRefractionPass() {
    // glDeleteTextures(1, &0) is a no-op per spec, so the never-initialised
    // path leaves nothing to leak.
    if (scene_copy_tex_) glDeleteTextures(1, &scene_copy_tex_);
}

void CloakRefractionPass::ensure_scene_copy(int w, int h) {
    if (scene_copy_tex_ && w == copy_w_ && h == copy_h_) return;
    if (scene_copy_tex_) glDeleteTextures(1, &scene_copy_tex_);
    glGenTextures(1, &scene_copy_tex_);
    glBindTexture(GL_TEXTURE_2D, scene_copy_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    copy_w_ = w; copy_h_ = h;
}

void CloakRefractionPass::render(const std::vector<CloakShipDescriptor>& ships,
                                 const scenegraph::World& world,
                                 const scenegraph::Camera& camera,
                                 Pipeline& pipeline,
                                 const ModelLookup& lookup) {
    if (ships.empty()) return;

    // ── Copy the live HDR colour into a scratch texture. ─────────────────────
    // We sample the scene colour AND draw back into the same bound HDR target;
    // sampling the bound target directly is a same-FBO feedback loop (undefined
    // per the GL spec, tile-aligned garbage on some GPUs). Copy first, sample
    // the copy. Mirrors NebulaGodrayPass.
    GLint vp[4];
    glGetIntegerv(GL_VIEWPORT, vp);
    const int cw = vp[2] > 0 ? vp[2] : 1;
    const int ch = vp[3] > 0 ? vp[3] : 1;
    ensure_scene_copy(cw, ch);
    glBindTexture(GL_TEXTURE_2D, scene_copy_tex_);
    glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, vp[0], vp[1], cw, ch);

    auto& shader = pipeline.cloak_refraction_shader();
    shader.use();

    const glm::mat4 vp_mat = camera.proj_matrix() * camera.view_matrix();
    shader.set_mat4 ("u_view_proj",  vp_mat);
    shader.set_vec3 ("u_camera_pos", camera.eye);
    shader.set_vec2 ("u_viewport",   glm::vec2(static_cast<float>(cw),
                                               static_cast<float>(ch)));
    shader.set_float("u_strength",   strength_);
    shader.set_float("u_dispersion", dispersion_);
    shader.set_vec3 ("u_tint",       tint_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, scene_copy_tex_);
    shader.set_int("u_scene", 0);

    // Over-blend the refracted scene onto the hull pixels; depth-test on (the
    // shell is occluded by nearer geometry), depth-write off, culling off so
    // both faces of the thin shell contribute.
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    for (const auto& s : ships) {
        if (s.frac <= 0.0f) continue;
        const scenegraph::Instance* inst = world.get(s.instance);
        if (!inst) continue;
        const assets::Model* model = lookup(inst->model_handle);
        if (!model) continue;

        shader.set_float("u_frac", s.frac);

        // Walk nodes exactly as the opaque/hologram pass does: each node
        // composes parent * local; parents precede children, so one linear pass
        // suffices. inst->world is the host's right-handed ship transform.
        const glm::mat4& world_xf = inst->world;
        std::vector<glm::mat4> world_per_node(model->nodes.size(), glm::mat4(1.0f));
        if (!model->nodes.empty()) {
            world_per_node[model->root_node] =
                world_xf * model->nodes[model->root_node].local_transform;
        }
        for (std::size_t i = 0; i < model->nodes.size(); ++i) {
            const auto& node = model->nodes[i];
            if (node.parent_index >= 0) {
                world_per_node[i] =
                    world_per_node[node.parent_index] * node.local_transform;
            }
            for (int mesh_idx : node.meshes) {
                const auto& mesh = model->meshes[mesh_idx];
                shader.set_mat4("u_model", world_per_node[i]);
                glBindVertexArray(mesh.vao());
                glDrawElements(GL_TRIANGLES, mesh.index_count(),
                               GL_UNSIGNED_INT, nullptr);
            }
        }
    }
    glBindVertexArray(0);
    glBindTexture(GL_TEXTURE_2D, 0);

    // Restore default opaque-pass GL state (matches hologram_pass).
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
