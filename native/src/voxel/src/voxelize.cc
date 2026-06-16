// native/src/voxel/src/voxelize.cc
#include <voxel/voxelize.h>
#include <assets/model.h>
#include <cmath>
#include <glm/glm.hpp>

namespace voxel {

namespace {
glm::ivec3 to_cell(const VoxelVolume& v, glm::vec3 p) {
    glm::vec3 g = (p - v.origin) / v.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}
}  // namespace

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

void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris) {
    const int N = 16;  // samples per edge; dense enough to leave no gaps at grid res
    for (const auto& t : tris) {
        for (int i = 0; i <= N; ++i)
        for (int j = 0; j + i <= N; ++j) {
            float u = float(i) / N, w = float(j) / N;
            glm::vec3 p = t.a + u * (t.b - t.a) + w * (t.c - t.a);
            glm::ivec3 c = to_cell(v, p);
            if (glm::all(glm::greaterThanEqual(c, glm::ivec3(0))) &&
                glm::all(glm::lessThan(c, v.dims)))
                v.set(c.x, c.y, c.z, true);
        }
    }
}

}  // namespace voxel
