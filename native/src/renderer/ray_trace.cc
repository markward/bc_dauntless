// native/src/renderer/ray_trace.cc
#include "renderer/ray_trace.h"

#include <algorithm>
#include <limits>
#include <memory>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>
#include <glm/gtc/matrix_inverse.hpp>

#include "renderer/aabb.h"

namespace renderer {

std::optional<float> intersect_triangle(
    glm::vec3 origin, glm::vec3 direction, float max_dist,
    glm::vec3 v0, glm::vec3 v1, glm::vec3 v2)
{
    constexpr float kDetEps = 1e-7f;  // |det| reject for parallel / degenerate triangles.
    constexpr float kTMin   = 1e-5f;  // t reject for self-hits at the origin.
    const glm::vec3 e1 = v1 - v0;
    const glm::vec3 e2 = v2 - v0;
    const glm::vec3 p  = glm::cross(direction, e2);
    const float det = glm::dot(e1, p);
    if (std::abs(det) < kDetEps) return std::nullopt;
    const float inv_det = 1.0f / det;
    const glm::vec3 s = origin - v0;
    const float u = glm::dot(s, p) * inv_det;
    if (u < 0.0f || u > 1.0f) return std::nullopt;
    const glm::vec3 q = glm::cross(s, e1);
    const float v = glm::dot(direction, q) * inv_det;
    if (v < 0.0f || u + v > 1.0f) return std::nullopt;
    const float t = glm::dot(e2, q) * inv_det;
    if (t < kTMin || t > max_dist) return std::nullopt;
    return t;
}

namespace {

struct WorldSphere { glm::vec3 center; float radius; };

/// One triangle, already baked out of node-local space into MODEL space.
///
/// The pre-bake is what lets a single BVH span the whole model. The old loop
/// transformed the RAY into each mesh's local space instead -- one matrix
/// inverse per mesh per ray -- and could not share an acceleration structure
/// across meshes, because every mesh sat in a different space.
struct TraceTri { glm::vec3 v0, v1, v2; };

/// Binary BVH node over TraceAccel::tris, in a flat array.
/// Internal: count == 0, left child at index + 1, right child at `right`.
/// Leaf:     count  > 0, triangles are tris[first .. first + count).
struct BvhNode {
    glm::vec3 lo{0.0f};
    glm::vec3 hi{0.0f};
    int first = 0;
    int count = 0;
    int right = 0;
};

struct TraceAccel {
    std::vector<TraceTri> tris;    // model space
    std::vector<BvhNode>  nodes;
    glm::vec3 aabb_center{0.0f};
    glm::vec3 aabb_half{0.0f};
};

constexpr int kLeafTriangles = 8;   // below this a linear test beats another split
constexpr int kMaxBvhDepth   = 40;  // hard stop; degenerate geometry must not recurse forever
constexpr int kTraversalStack = 64; // >= 2 * kMaxBvhDepth, so a push can never overflow

// Mirrors aabb.cc's node-world walk; keep in sync.
std::vector<glm::mat4> build_node_world(const assets::Model& model) {
    std::vector<glm::mat4> nw(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return nw;
    nw[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            nw[i] = nw[node.parent_index] * node.local_transform;
        }
    }
    return nw;
}

void tri_bounds(const std::vector<TraceTri>& tris, int first, int count,
                glm::vec3& lo, glm::vec3& hi) {
    lo = glm::vec3(std::numeric_limits<float>::max());
    hi = glm::vec3(std::numeric_limits<float>::lowest());
    for (int i = first; i < first + count; ++i) {
        const TraceTri& t = tris[i];
        lo = glm::min(lo, glm::min(t.v0, glm::min(t.v1, t.v2)));
        hi = glm::max(hi, glm::max(t.v0, glm::max(t.v1, t.v2)));
    }
}

/// Median-split build. Returns the index of the node it wrote.
///
/// Splits on the CENTROID spread rather than the vertex bounds, which keeps
/// the halves balanced when a few long triangles straddle the model. Same
/// choice compute_model_bounds makes, for the same reason: a BC mesh is a
/// material group, not a spatial one, so single shapes routinely span a whole
/// hull.
int build_bvh(std::vector<TraceTri>& tris, std::vector<BvhNode>& nodes,
              int first, int count, int depth) {
    const int self = static_cast<int>(nodes.size());
    nodes.emplace_back();
    glm::vec3 lo, hi;
    tri_bounds(tris, first, count, lo, hi);

    const auto make_leaf = [&]() {
        BvhNode& n = nodes[self];
        n.lo = lo; n.hi = hi; n.first = first; n.count = count; n.right = 0;
        return self;
    };

    if (count <= kLeafTriangles || depth >= kMaxBvhDepth) return make_leaf();

    glm::vec3 clo(std::numeric_limits<float>::max());
    glm::vec3 chi(std::numeric_limits<float>::lowest());
    for (int i = first; i < first + count; ++i) {
        const TraceTri& t = tris[i];
        const glm::vec3 c = (t.v0 + t.v1 + t.v2) / 3.0f;
        clo = glm::min(clo, c);
        chi = glm::max(chi, c);
    }
    const glm::vec3 extent = chi - clo;
    int axis = 0;
    if (extent.y > extent[axis]) axis = 1;
    if (extent.z > extent[axis]) axis = 2;
    if (extent[axis] <= 0.0f) return make_leaf();  // coincident centroids

    const int mid = count / 2;
    std::nth_element(
        tris.begin() + first, tris.begin() + first + mid,
        tris.begin() + first + count,
        [axis](const TraceTri& a, const TraceTri& b) {
            return (a.v0[axis] + a.v1[axis] + a.v2[axis])
                 < (b.v0[axis] + b.v1[axis] + b.v2[axis]);
        });

    build_bvh(tris, nodes, first, mid, depth + 1);   // left lands at self + 1
    const int right = build_bvh(tris, nodes, first + mid, count - mid, depth + 1);
    BvhNode& n = nodes[self];
    n.lo = lo; n.hi = hi; n.first = 0; n.count = 0; n.right = right;
    return self;
}

/// Build the model's acceleration structure on first use.
///
/// Valid for the model's whole lifetime with no invalidation path, because
/// there is no input that can change: node.local_transform is static asset
/// data and the skinning path does not write it. If an animated node is ever
/// introduced, THIS is the cache that has to learn to invalidate.
const TraceAccel& ensure_trace_accel(const assets::Model& model) {
    if (model.trace_accel) {
        return *static_cast<const TraceAccel*>(model.trace_accel.get());
    }
    auto accel = std::make_shared<TraceAccel>();

    const std::vector<glm::mat4> node_world = build_node_world(model);
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());

    for (std::size_t ni = 0; ni < model.nodes.size(); ++ni) {
        const auto& node = model.nodes[ni];
        for (int mesh_idx : node.meshes) {
            if (mesh_idx < 0 ||
                mesh_idx >= static_cast<int>(model.meshes.size())) continue;
            const auto& cpu_opt = model.meshes[mesh_idx].cpu_data();
            if (!cpu_opt) continue;
            const auto& cpu = *cpu_opt;
            const auto& idx = cpu.indices;
            const auto& verts = cpu.vertices;
            const glm::mat4& nw = node_world[ni];
            for (std::size_t k = 0; k + 2 < idx.size(); k += 3) {
                if (idx[k] >= verts.size() || idx[k + 1] >= verts.size() ||
                    idx[k + 2] >= verts.size()) continue;
                TraceTri t;
                t.v0 = glm::vec3(nw * glm::vec4(verts[idx[k + 0]].position, 1.0f));
                t.v1 = glm::vec3(nw * glm::vec4(verts[idx[k + 1]].position, 1.0f));
                t.v2 = glm::vec3(nw * glm::vec4(verts[idx[k + 2]].position, 1.0f));
                lo = glm::min(lo, glm::min(t.v0, glm::min(t.v1, t.v2)));
                hi = glm::max(hi, glm::max(t.v0, glm::max(t.v1, t.v2)));
                accel->tris.push_back(t);
            }
        }
    }

    if (!accel->tris.empty()) {
        accel->aabb_center = 0.5f * (lo + hi);
        accel->aabb_half = 0.5f * (hi - lo);
        accel->nodes.reserve(accel->tris.size() / 4 + 8);
        build_bvh(accel->tris, accel->nodes, 0,
                  static_cast<int>(accel->tris.size()), 0);
    }

    model.trace_accel = accel;
    return *accel;
}

WorldSphere compute_world_sphere(const glm::vec3& center,
                                 const glm::vec3& half_extents,
                                 const glm::mat4& instance_world) {
    glm::vec3 c_world = glm::vec3(instance_world * glm::vec4(center, 1.0f));
    glm::mat3 m3 = glm::mat3(instance_world);
    const glm::vec3& he = half_extents;
    glm::vec3 he_world(
        std::abs(m3[0][0]) * he.x + std::abs(m3[1][0]) * he.y + std::abs(m3[2][0]) * he.z,
        std::abs(m3[0][1]) * he.x + std::abs(m3[1][1]) * he.y + std::abs(m3[2][1]) * he.z,
        std::abs(m3[0][2]) * he.x + std::abs(m3[1][2]) * he.y + std::abs(m3[2][2]) * he.z);
    return {c_world, glm::length(he_world)};
}

bool segment_hits_sphere(glm::vec3 origin, glm::vec3 direction, float max_dist,
                         glm::vec3 center, float radius) {
    if (radius <= 0.0f) return false;
    const glm::vec3 oc = origin - center;
    const float b = glm::dot(oc, direction);
    const float c = glm::dot(oc, oc) - radius * radius;
    if (c <= 0.0f) return true;
    if (b >= 0.0f) return false;
    const float disc = b * b - c;
    if (disc < 0.0f) return false;
    const float t_enter = -b - std::sqrt(disc);
    return t_enter <= max_dist;
}

/// Ray-vs-AABB slab test.
///
/// inv_dir may hold infinities for an axis-aligned ray; the min/max ordering
/// handles those. A 0*inf NaN can only arise when the origin lies exactly on a
/// slab plane, and a NaN comparison here yields `false` -- a conservative
/// MISS. That is the one direction that could drop a real hit, so the sphere
/// test above (which has no such degeneracy) still runs first and the leaf
/// triangles are still tested exactly; the window is a measure-zero ray that
/// grazes a box plane, where the triangle test is the authority anyway.
bool slab_hit(const BvhNode& n, const glm::vec3& o, const glm::vec3& inv_dir,
              float t_max) {
    const glm::vec3 t0 = (n.lo - o) * inv_dir;
    const glm::vec3 t1 = (n.hi - o) * inv_dir;
    const glm::vec3 tsmall = glm::min(t0, t1);
    const glm::vec3 tbig = glm::max(t0, t1);
    const float tmin = std::max(std::max(tsmall.x, tsmall.y),
                                std::max(tsmall.z, 0.0f));
    const float tmax = std::min(std::min(tbig.x, tbig.y),
                                std::min(tbig.z, t_max));
    return tmin <= tmax;
}

}  // namespace

std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist)
{
    if (model.nodes.empty() || model.meshes.empty()) return std::nullopt;

    const TraceAccel& accel = ensure_trace_accel(model);
    if (accel.tris.empty() || accel.nodes.empty()) return std::nullopt;

    const WorldSphere sphere =
        compute_world_sphere(accel.aabb_center, accel.aabb_half, instance_world);
    if (sphere.radius > 0.0f &&
        !segment_hits_sphere(origin, direction, max_dist,
                             sphere.center, sphere.radius)) {
        return std::nullopt;
    }

    // ONE inverse for the whole model, not one per mesh: the triangles were
    // baked into model space at build time, so model space is the only local
    // space left.
    const glm::mat4 world_inv = glm::inverse(instance_world);
    const glm::vec3 o_local = glm::vec3(world_inv * glm::vec4(origin, 1.0f));
    const glm::vec3 d_local = glm::vec3(world_inv * glm::vec4(direction, 0.0f));
    const float d_local_len = glm::length(d_local);
    if (d_local_len < 1e-12f) return std::nullopt;
    const glm::vec3 d_unit = d_local / d_local_len;
    const float max_dist_local = max_dist * d_local_len;

    const glm::vec3 inv_dir(1.0f / d_unit.x, 1.0f / d_unit.y, 1.0f / d_unit.z);

    float best_t = std::numeric_limits<float>::infinity();
    int best_tri = -1;

    int stack[kTraversalStack];
    int sp = 0;
    stack[sp++] = 0;
    while (sp > 0) {
        const int ni = stack[--sp];
        const BvhNode& n = accel.nodes[ni];
        // Shrink the ray as hits are found, so later boxes reject sooner.
        const float limit = (best_tri >= 0) ? best_t : max_dist_local;
        if (!slab_hit(n, o_local, inv_dir, limit)) continue;
        if (n.count > 0) {
            for (int i = n.first; i < n.first + n.count; ++i) {
                const TraceTri& t = accel.tris[i];
                const auto t_local = intersect_triangle(
                    o_local, d_unit, max_dist_local, t.v0, t.v1, t.v2);
                if (!t_local || *t_local >= best_t) continue;
                best_t = *t_local;
                best_tri = i;
            }
        } else {
            // Net stack growth is +1 per level (push 2, pop 1), so depth is
            // bounded by kMaxBvhDepth and kTraversalStack cannot overflow.
            stack[sp++] = n.right;
            stack[sp++] = ni + 1;
        }
    }

    if (best_tri < 0) return std::nullopt;

    const TraceTri& t = accel.tris[best_tri];
    const glm::vec3 hit_local = o_local + d_unit * best_t;
    const glm::mat3 normal_matrix = glm::transpose(glm::mat3(world_inv));
    glm::vec3 best_normal = glm::normalize(
        normal_matrix * glm::normalize(glm::cross(t.v1 - t.v0, t.v2 - t.v0)));
    if (glm::dot(best_normal, direction) > 0.0f) best_normal = -best_normal;
    return RayHit{glm::vec3(instance_world * glm::vec4(hit_local, 1.0f)),
                  best_normal,
                  best_t / d_local_len};
}

}  // namespace renderer
