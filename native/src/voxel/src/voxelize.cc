// native/src/voxel/src/voxelize.cc
#include <voxel/voxelize.h>
#include <assets/model.h>

namespace voxel {

std::vector<Tri> collect_hull_triangles(const assets::Model& model) {
    // Build per-node world transforms in a single linear pass.
    // The asset pipeline guarantees parents precede children in model.nodes
    // order (same assumption used by renderer/aabb.cc and renderer/ray_trace.cc),
    // so node_world[parent] is always ready before node_world[child].
    std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        node_world[model.root_node] =
            model.nodes[model.root_node].local_transform;
        for (std::size_t i = 0; i < model.nodes.size(); ++i) {
            const auto& node = model.nodes[i];
            if (node.parent_index >= 0) {
                node_world[i] =
                    node_world[static_cast<std::size_t>(node.parent_index)] *
                    node.local_transform;
            }
        }
    }

    std::vector<Tri> out;
    for (std::size_t ni = 0; ni < model.nodes.size(); ++ni) {
        const glm::mat4& w = node_world[ni];
        for (int mi : model.nodes[ni].meshes) {
            // Bounds-check mesh index (mirrors ray_trace.cc).
            if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
            // assets::Mesh is a GPU object; CPU data may or may not be retained.
            const auto& cpu_opt =
                model.meshes[static_cast<std::size_t>(mi)].cpu_data();
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
