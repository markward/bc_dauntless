// native/src/renderer/part_frame.cc
#include <renderer/part_frame.h>

#include <limits>
#include <vector>

#include <assets/model.h>

namespace renderer {
namespace {

constexpr float kSingularEps = 1e-6f;
// Slack on the posed bounds, in model units. The bounds are an AABB of a
// rotated subtree and so are already loose; this only stops a carve landing
// exactly on the surface from falling between the part and the hull.
constexpr float kBoundsSlack = 1e-3f;

bool nearly_singular(const glm::mat4& m) {
    const float d = glm::determinant(m);
    return d > -kSingularEps && d < kSingularEps;
}

}  // namespace

std::optional<glm::mat4> rest_from_posed_at(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides,
    const glm::vec3& body_point) {
    if (overrides.empty() || model.nodes.empty()) return std::nullopt;
    const std::size_t n = model.nodes.size();
    if (model.root_node < 0 || static_cast<std::size_t>(model.root_node) >= n) {
        return std::nullopt;
    }

    // Rest world-per-node. The asset pipeline orders nodes so parents precede
    // children, so one linear pass suffices (same as aabb.cc).
    std::vector<glm::mat4> rest(n, glm::mat4(1.0f));
    rest[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < n; ++i) {
        const int parent = model.nodes[i].parent_index;
        if (parent >= 0 && static_cast<std::size_t>(parent) < n) {
            rest[i] = rest[parent] * model.nodes[i].local_transform;
        }
    }

    for (const auto& entry : overrides) {
        const int node = entry.first;
        if (node < 0 || static_cast<std::size_t>(node) >= n) continue;
        if (nearly_singular(entry.second)) continue;  // severed: claims nothing

        // Posed world for this node. `local` REPLACES the node's own local
        // transform; everything below it inherits the change.
        const int parent = model.nodes[node].parent_index;
        const glm::mat4 base =
            (parent >= 0 && static_cast<std::size_t>(parent) < n)
                ? rest[parent] : glm::mat4(1.0f);
        const glm::mat4 posed_node = base * entry.second;
        if (nearly_singular(posed_node) || nearly_singular(rest[node])) continue;

        // One rigid-ish map each way for the whole subtree.
        const glm::mat4 to_rest  = rest[node] * glm::inverse(posed_node);
        const glm::mat4 to_posed = posed_node * glm::inverse(rest[node]);

        // Bound this node's POSED subtree geometry and test containment.
        // Descendants are included: an override on a part moves its
        // children's meshes too, and on a real hull the meshes are ONLY on
        // the children.
        glm::vec3 lo(std::numeric_limits<float>::max());
        glm::vec3 hi(std::numeric_limits<float>::lowest());
        bool any = false;
        for (std::size_t i = 0; i < n; ++i) {
            bool in_subtree = (static_cast<int>(i) == node);
            for (int p = model.nodes[i].parent_index;
                 !in_subtree && p >= 0 && static_cast<std::size_t>(p) < n;
                 p = model.nodes[p].parent_index) {
                if (p == node) in_subtree = true;
            }
            if (!in_subtree) continue;
            const glm::mat4 world_i = to_posed * rest[i];
            for (int mesh_idx : model.nodes[i].meshes) {
                if (mesh_idx < 0 ||
                    static_cast<std::size_t>(mesh_idx) >= model.meshes.size()) {
                    continue;
                }
                const std::optional<assets::MeshCpu>& cpu =
                    model.meshes[mesh_idx].cpu_data();
                if (!cpu.has_value()) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 p(world_i * glm::vec4(v.position, 1.0f));
                    lo = glm::min(lo, p);
                    hi = glm::max(hi, p);
                    any = true;
                }
            }
        }
        if (!any) continue;
        lo -= kBoundsSlack;
        hi += kBoundsSlack;
        if (body_point.x < lo.x || body_point.x > hi.x) continue;
        if (body_point.y < lo.y || body_point.y > hi.y) continue;
        if (body_point.z < lo.z || body_point.z > hi.z) continue;
        return to_rest;
    }
    return std::nullopt;
}

}  // namespace renderer
