#include "renderer/node_anim.h"
#include <assets/model.h>

namespace renderer {

std::vector<glm::mat4> compose_node_worlds(
    const assets::Model& model, const glm::mat4& instance_world,
    const std::unordered_map<int, glm::mat4>& overrides) {
    std::vector<glm::mat4> world(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return world;

    auto local_of = [&](int i) -> const glm::mat4& {
        auto it = overrides.find(i);
        return it != overrides.end() ? it->second
                                     : model.nodes[i].local_transform;
    };

    world[model.root_node] = instance_world * local_of(model.root_node);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0)
            world[i] = world[node.parent_index] * local_of(static_cast<int>(i));
    }
    return world;
}

}  // namespace renderer
