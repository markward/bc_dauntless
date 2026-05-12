// native/src/renderer/aabb.cc
#include "renderer/aabb.h"

#include <limits>

#include <assets/mesh.h>
#include <assets/model.h>

namespace renderer {

Aabb compute_aabb(std::span<const glm::vec3> positions) {
    if (positions.empty()) return {};
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    for (const auto& p : positions) {
        lo = glm::min(lo, p);
        hi = glm::max(hi, p);
    }
    return Aabb{
        .center = 0.5f * (lo + hi),
        .half_extents = 0.5f * (hi - lo),
    };
}

Aabb compute_model_aabb(const assets::Model& model) {
    // Walk node hierarchy to chain local_transform from root down. The asset
    // pipeline orders nodes so parents precede children, so a single linear
    // pass produces correct world-per-node matrices.
    if (model.nodes.empty()) return {};
    std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
    node_world[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            node_world[i] = node_world[node.parent_index] * node.local_transform;
        }
    }
    std::vector<glm::vec3> pts;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
            if (mesh_idx < 0 ||
                mesh_idx >= static_cast<int>(model.meshes.size())) continue;
            const auto& cpu = model.meshes[mesh_idx].cpu_data();
            if (!cpu) continue;
            for (const auto& v : cpu->vertices) {
                pts.push_back(glm::vec3(node_world[i] * glm::vec4(v.position, 1.0f)));
            }
        }
    }
    return compute_aabb(pts);
}

}  // namespace renderer
