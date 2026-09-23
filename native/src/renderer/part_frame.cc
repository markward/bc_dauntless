// native/src/renderer/part_frame.cc
#include <renderer/part_frame.h>

#include <limits>
#include <vector>

#include <assets/model.h>

namespace renderer {
namespace {

constexpr float kSingularEps = 1e-6f;
// Slack on the rest-space bounds, in model units. This only stops a carve
// landing exactly on a mesh's surface from falling between the part and the
// hull due to float rounding -- it does not loosen the box the way testing
// the POSED subtree AABB used to (see the header doc for why that mattered).
constexpr float kBoundsSlack = 1e-3f;

bool nearly_singular(const glm::mat4& m) {
    const float d = glm::determinant(m);
    return d > -kSingularEps && d < kSingularEps;
}

struct RestBox {
    glm::vec3 lo{0.0f};
    glm::vec3 hi{0.0f};
    bool valid = false;
};

// The REST-space AABB of `node`'s own meshes plus every descendant's, in the
// model's own rest pose (no override applied anywhere). See the header for
// why this is recomputed per call rather than cached behind a bare
// `const assets::Model*`.
RestBox subtree_rest_box(const assets::Model& model, int node,
                          const std::vector<glm::mat4>& rest) {
    const std::size_t n = model.nodes.size();
    RestBox box;
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    for (std::size_t i = 0; i < n; ++i) {
        bool in_subtree = (static_cast<int>(i) == node);
        for (int p = model.nodes[i].parent_index;
             !in_subtree && p >= 0 && static_cast<std::size_t>(p) < n;
             p = model.nodes[p].parent_index) {
            if (p == node) in_subtree = true;
        }
        if (!in_subtree) continue;
        for (int mesh_idx : model.nodes[i].meshes) {
            if (mesh_idx < 0 ||
                static_cast<std::size_t>(mesh_idx) >= model.meshes.size()) {
                continue;
            }
            const std::optional<assets::MeshCpu>& cpu =
                model.meshes[mesh_idx].cpu_data();
            if (!cpu.has_value()) continue;
            for (const auto& v : cpu->vertices) {
                const glm::vec3 p(rest[i] * glm::vec4(v.position, 1.0f));
                lo = glm::min(lo, p);
                hi = glm::max(hi, p);
                box.valid = true;
            }
        }
    }
    box.lo = lo;
    box.hi = hi;
    return box;
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

    // Every override that claims body_point, so the winner among overlapping
    // claims (e.g. port/starboard wing roots overlapping near the spine) is a
    // STATED rule -- smallest rest-box volume, ties broken by lowest node
    // index -- rather than unordered_map's hash order. See the header.
    struct Claim {
        int node = -1;
        float volume = 0.0f;
        glm::mat4 to_rest{1.0f};
    };
    std::optional<Claim> best;

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

        const glm::mat4 to_rest = rest[node] * glm::inverse(posed_node);

        // Pull the QUERY back into rest space FIRST, then test it against the
        // subtree's REST-pose box -- not the posed box (see header). A
        // rotated slab's posed AABB is far bigger than the slab and would
        // over-claim neighbouring geometry; the rest box hugs the slab in
        // its own frame regardless of the override.
        const glm::vec3 candidate(to_rest * glm::vec4(body_point, 1.0f));

        const RestBox box = subtree_rest_box(model, node, rest);
        if (!box.valid) continue;
        const glm::vec3 lo = box.lo - kBoundsSlack;
        const glm::vec3 hi = box.hi + kBoundsSlack;
        if (candidate.x < lo.x || candidate.x > hi.x) continue;
        if (candidate.y < lo.y || candidate.y > hi.y) continue;
        if (candidate.z < lo.z || candidate.z > hi.z) continue;

        const glm::vec3 extent = box.hi - box.lo;
        const float volume = extent.x * extent.y * extent.z;
        if (!best.has_value() || volume < best->volume ||
            (volume == best->volume && node < best->node)) {
            best = Claim{node, volume, to_rest};
        }
    }

    if (!best.has_value()) return std::nullopt;
    return best->to_rest;
}

}  // namespace renderer
