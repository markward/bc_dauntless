// native/src/renderer/model_draw_helpers.cc
#include <renderer/model_draw_helpers.h>

#include <renderer/node_anim.h>
#include <renderer/shader.h>
#include <assets/model.h>
#include <assets/mesh.h>

#include <glad/glad.h>

#include <unordered_map>
#include <vector>

namespace renderer {

void draw_model_positions_only(const assets::Model& model,
                               const glm::mat4& world,
                               Shader& prog,
                               const std::unordered_map<int, glm::mat4>*
                                   node_overrides) {
    static const std::unordered_map<int, glm::mat4> kEmpty;
    const std::vector<glm::mat4> world_per_node = renderer::compose_node_worlds(
        model, world, node_overrides ? *node_overrides : kEmpty);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[static_cast<std::size_t>(mesh_idx)];
            prog.set_mat4("u_model", world_per_node[i]);
            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(mesh.index_count()),
                           GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}

}  // namespace renderer
