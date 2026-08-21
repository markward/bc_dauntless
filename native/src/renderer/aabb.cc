// native/src/renderer/aabb.cc
#include "renderer/aabb.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <span>

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

namespace {

/// One triangle in model-local space, plus the centroid the split sorts on.
struct Tri {
    glm::vec3 v[3];
    glm::vec3 centroid;
};

/// Tight-ish sphere about `tris`: centred on their AABB centre, with the
/// radius reaching the furthest vertex. Not the minimal enclosing sphere —
/// that costs an iterative solve for a difference that shrinks with the leaf.
BoundSphere bound_of(std::span<const Tri> tris) {
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    for (const auto& t : tris) {
        for (const auto& p : t.v) {
            lo = glm::min(lo, p);
            hi = glm::max(hi, p);
        }
    }
    const glm::vec3 center = 0.5f * (lo + hi);
    float r2 = 0.0f;
    for (const auto& t : tris) {
        for (const auto& p : t.v) {
            r2 = std::max(r2, glm::dot(p - center, p - center));
        }
    }
    return BoundSphere{.center = center, .radius = std::sqrt(r2)};
}

/// Median-split `tris` along the longest axis of their centroid spread until
/// each leaf is small enough, then bound each leaf.
///
/// `budget` is halved down each branch, so the leaf count cannot exceed the
/// budget the top-level call starts with however pathological the geometry.
/// Splitting on the CENTROID spread rather than the vertex AABB keeps the two
/// halves balanced when a few long triangles straddle the whole model.
void split_leaves(std::span<Tri> tris, int budget, std::vector<BoundSphere>& out) {
    if (tris.empty()) return;
    if (budget <= 1 ||
        tris.size() <= static_cast<std::size_t>(kMinHullBoundLeafTriangles)) {
        out.push_back(bound_of(tris));
        return;
    }
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    for (const auto& t : tris) {
        lo = glm::min(lo, t.centroid);
        hi = glm::max(hi, t.centroid);
    }
    const glm::vec3 extent = hi - lo;
    int axis = 0;
    if (extent.y > extent[axis]) axis = 1;
    if (extent.z > extent[axis]) axis = 2;
    if (extent[axis] <= 0.0f) {          // every centroid coincident
        out.push_back(bound_of(tris));
        return;
    }
    const std::size_t mid = tris.size() / 2;
    std::nth_element(tris.begin(), tris.begin() + mid, tris.end(),
                     [axis](const Tri& a, const Tri& b) {
                         return a.centroid[axis] < b.centroid[axis];
                     });
    split_leaves(tris.subspan(0, mid), budget / 2, out);
    split_leaves(tris.subspan(mid), budget - budget / 2, out);
}

}  // namespace

std::vector<BoundSphere> compute_bounds_from_triangles(
    std::span<const std::array<glm::vec3, 3>> in) {
    std::vector<BoundSphere> out;
    if (in.empty()) return out;
    std::vector<Tri> tris;
    tris.reserve(in.size());
    for (const auto& t : in) {
        tris.push_back(Tri{
            .v = {t[0], t[1], t[2]},
            .centroid = (t[0] + t[1] + t[2]) / 3.0f,
        });
    }
    split_leaves(std::span<Tri>(tris), kMaxHullBoundLeaves, out);
    return out;
}

std::vector<BoundSphere> compute_model_bounds(const assets::Model& model) {
    // Same node-world chaining as compute_model_aabb above: the asset pipeline
    // orders parents before children, so one linear pass suffices.
    std::vector<BoundSphere> out;
    if (model.nodes.empty()) return out;
    std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
    node_world[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            node_world[i] = node_world[node.parent_index] * node.local_transform;
        }
    }

    // One soup for the WHOLE model, not one per mesh. A BC mesh is a material
    // group, not a spatial one — three of FedStarbase's five shapes each span
    // the entire station — so subdividing within mesh boundaries would leave
    // the volume under its mushroom cap claimed by geometry nowhere near it.
    std::vector<std::array<glm::vec3, 3>> tris;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
            if (mesh_idx < 0 ||
                mesh_idx >= static_cast<int>(model.meshes.size())) continue;
            const auto& cpu = model.meshes[mesh_idx].cpu_data();
            if (!cpu) continue;
            const auto& idx = cpu->indices;
            const auto& verts = cpu->vertices;
            for (std::size_t k = 0; k + 2 < idx.size(); k += 3) {
                if (idx[k] >= verts.size() || idx[k + 1] >= verts.size() ||
                    idx[k + 2] >= verts.size()) continue;
                std::array<glm::vec3, 3> t;
                for (int c = 0; c < 3; ++c) {
                    t[c] = glm::vec3(
                        node_world[i] *
                        glm::vec4(verts[idx[k + c]].position, 1.0f));
                }
                tris.push_back(t);
            }
        }
    }
    return compute_bounds_from_triangles(tris);
}

}  // namespace renderer
