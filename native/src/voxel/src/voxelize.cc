// native/src/voxel/src/voxelize.cc
#include <voxel/voxelize.h>
#include <assets/model.h>

namespace voxel {

/// Accumulate world transform for node_idx by walking the parent chain
/// from root down to the node (root -> ... -> node).
static glm::mat4 world_transform(const assets::Model& m, int node_idx) {
    // Collect the ancestor chain from node_idx up to the root.
    std::vector<int> chain;
    for (int i = node_idx; i >= 0; i = m.nodes[static_cast<std::size_t>(i)].parent_index)
        chain.push_back(i);
    // Multiply root-first (root -> ... -> node).
    glm::mat4 t(1.0f);
    for (auto it = chain.rbegin(); it != chain.rend(); ++it)
        t = t * m.nodes[static_cast<std::size_t>(*it)].local_transform;
    return t;
}

std::vector<Tri> collect_hull_triangles(const assets::Model& model) {
    std::vector<Tri> out;
    for (int ni = 0; ni < static_cast<int>(model.nodes.size()); ++ni) {
        const glm::mat4 w = world_transform(model, ni);
        for (int mi : model.nodes[static_cast<std::size_t>(ni)].meshes) {
            // assets::Mesh is a GPU object; CPU data may or may not be retained.
            const auto& cpu_opt = model.meshes[static_cast<std::size_t>(mi)].cpu_data();
            if (!cpu_opt) continue;
            const auto& cpu = *cpu_opt;
            if (cpu.indices.empty() || cpu.vertices.empty()) continue;

            // P: transform vertex vi from body frame to world frame.
            auto P = [&](std::uint32_t vi) -> glm::vec3 {
                glm::vec4 p = w * glm::vec4(cpu.vertices[vi].position, 1.0f);
                return glm::vec3(p);
            };

            for (std::size_t i = 0; i + 2 < cpu.indices.size(); i += 3) {
                out.push_back({P(cpu.indices[i]),
                               P(cpu.indices[i + 1]),
                               P(cpu.indices[i + 2])});
            }
        }
    }
    return out;
}

}  // namespace voxel
