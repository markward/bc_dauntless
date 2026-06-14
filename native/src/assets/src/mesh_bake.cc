// native/src/assets/src/mesh_bake.cc
#include "mesh_bake.h"

#include <glm/glm.hpp>

namespace assets::detail {

std::vector<glm::mat4> compute_local_world_per_node(
    const std::vector<Node>& nodes, int root_node)
{
    std::vector<glm::mat4> world(nodes.size(), glm::mat4(1.0f));
    if (nodes.empty()) return world;
    if (root_node >= 0 && root_node < static_cast<int>(nodes.size()))
        world[root_node] = nodes[root_node].local_transform;
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        const auto& node = nodes[i];
        if (node.parent_index >= 0 &&
            node.parent_index < static_cast<int>(nodes.size())) {
            world[i] = world[node.parent_index] * node.local_transform;
        }
    }
    return world;
}

void bake_mesh_to_model_space(MeshCpu& cpu, const glm::mat4& m) {
    const glm::mat3 n3(m);
    for (auto& v : cpu.vertices) {
        v.position = glm::vec3(m * glm::vec4(v.position, 1.0f));
        v.normal = glm::normalize(n3 * v.normal);
    }
}

}  // namespace assets::detail
