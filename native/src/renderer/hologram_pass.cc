// native/src/renderer/hologram_pass.cc
#include "renderer/hologram_pass.h"
#include "renderer/pipeline.h"

#include <assets/mesh.h>
#include <assets/model.h>
#include <renderer/node_anim.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <vector>

namespace renderer {

void HologramPass::render(const HologramShip& ship,
                          const scenegraph::World& world,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline,
                          const ModelLookup& lookup) {
    if (!ship.active) return;

    const scenegraph::Instance* inst = world.get(ship.instance);
    if (!inst) return;

    const assets::Model* model = lookup(inst->model_handle);
    if (!model) return;

    auto& shader = pipeline.hologram_shader();
    shader.use();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader.set_mat4 ("u_view_proj",      vp);
    shader.set_vec3 ("u_camera_pos",     camera.eye);
    shader.set_vec3 ("u_color",          ship.color);
    shader.set_float("u_opacity_facing", ship.opacity_facing);
    shader.set_float("u_opacity_grazing", ship.opacity_grazing);

    // Additive translucency: depth-test on so the hologram is occluded by
    // nearer geometry, depth-write off so its own fragments don't reject one
    // another, culling off so both faces contribute to the Fresnel glow.
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    // Honour node overrides so the hologram matches the hull: the SPV draws
    // its subsystem pins against THIS pose, so a mismatch here puts every pin
    // on an articulated part in the wrong place.
    const glm::mat4& world_xf = inst->world;
    const std::vector<glm::mat4> world_per_node =
        renderer::compose_node_worlds(*model, world_xf, inst->node_overrides);
    for (std::size_t i = 0; i < model->nodes.size(); ++i) {
        const auto& node = model->nodes[i];
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model->meshes[mesh_idx];
            shader.set_mat4("u_model", world_per_node[i]);
            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(),
                           GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);

    // Restore default opaque-pass GL state (matches phaser_pass).
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
