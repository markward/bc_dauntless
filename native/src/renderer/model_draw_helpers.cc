// native/src/renderer/model_draw_helpers.cc
#include <renderer/model_draw_helpers.h>

#include <renderer/shader.h>
#include <assets/model.h>
#include <assets/mesh.h>

#include <glad/glad.h>

#include <vector>

namespace renderer {

void draw_model_positions_only(const assets::Model& model,
                               const glm::mat4& world,
                               Shader& prog) {
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[static_cast<std::size_t>(model.root_node)] =
            world * model.nodes[static_cast<std::size_t>(model.root_node)].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] =
                world_per_node[static_cast<std::size_t>(node.parent_index)] * node.local_transform;
        }
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
