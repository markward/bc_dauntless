// native/src/renderer/model_parts.cc
#include <renderer/model_parts.h>

#include <limits>

#include <assets/model.h>

namespace renderer {
namespace {

/// The node whose children are parts: "Scene Root" if present, else the first
/// node with more than one child, else -1.
///
/// This is deliberately NOT model.root_node. On a real BC hull (measured on
/// BirdOfPrey.nif) Scene Root sits below TWO unnamed wrapper nodes, each with
/// exactly one child, so model.root_node is neither named "Scene Root" nor a
/// branch point -- it is two levels above the node whose children are the
/// actual parts. Falling back to model.root_node would make every node's
/// parent-check fail (nothing's parent_index equals the root), so every part
/// would silently come back candidate=false. See
/// ModelParts.FallsBackToTheFirstBranchingNodeWithoutASceneRoot.
int part_parent_index(const assets::Model& model) {
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name == "Scene Root") return static_cast<int>(i);
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].children.size() > 1) return static_cast<int>(i);
    }
    return -1;
}

}  // namespace

std::vector<ModelPart> model_parts(const assets::Model& model) {
    std::vector<ModelPart> out;
    const std::size_t n = model.nodes.size();
    if (n == 0) return out;

    // Rest world-per-node. The asset pipeline orders nodes so parents precede
    // children, so one linear pass suffices (same as aabb.cc).
    std::vector<glm::mat4> rest(n, glm::mat4(1.0f));
    if (model.root_node >= 0 && static_cast<std::size_t>(model.root_node) < n) {
        rest[model.root_node] = model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < n; ++i) {
        const int parent = model.nodes[i].parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            rest[i] = rest[parent] * model.nodes[i].local_transform;
        }
    }

    const int part_parent = part_parent_index(model);

    for (std::size_t i = 0; i < n; ++i) {
        const auto& node = model.nodes[i];
        if (node.name.empty()) continue;            // unnamed wrappers

        ModelPart p;
        p.name = node.name;
        const int parent = node.parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            p.parent = model.nodes[parent].name;
        }
        p.candidate = (part_parent >= 0 && parent == part_parent);

        // Subtree bounds: a part's meshes hang off its __NDL child, so the
        // node's OWN meshes are not enough.
        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        for (std::size_t j = 0; j < n; ++j) {
            bool in_subtree = (j == i);
            for (int q = model.nodes[j].parent_index;
                 !in_subtree && q >= 0 && static_cast<std::size_t>(q) < n;
                 q = model.nodes[q].parent_index) {
                if (static_cast<std::size_t>(q) == i) in_subtree = true;
            }
            if (!in_subtree) continue;
            for (int mesh_idx : model.nodes[j].meshes) {
                if (mesh_idx < 0 ||
                    static_cast<std::size_t>(mesh_idx) >= model.meshes.size()) {
                    continue;
                }
                const auto& cpu = model.meshes[mesh_idx].cpu_data();
                if (!cpu.has_value()) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 w(rest[j] * glm::vec4(v.position, 1.0f));
                    lo = glm::min(lo, w);
                    hi = glm::max(hi, w);
                    p.has_bounds = true;
                }
            }
        }
        if (p.has_bounds) { p.bounds_min = lo; p.bounds_max = hi; }
        out.push_back(std::move(p));
    }
    return out;
}

}  // namespace renderer
