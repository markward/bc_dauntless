// native/src/assets/src/tessellate.cc
#include <assets/tessellate.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <map>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

namespace assets {

namespace {

using V = MeshCpu::Vertex;

std::uint64_t edge_key(std::uint32_t a, std::uint32_t b) {
    if (a > b) std::swap(a, b);
    return (static_cast<std::uint64_t>(a) << 32) | b;
}

// Canonical position id per vertex: weld byte-identical positions to one id.
// Boundary classification keys on these, so UV-seam duplicate vertices (same
// position, different UV -> distinct indices) read as an INTERIOR edge and get
// rounded, while genuine open borders (a single triangle on a spatial edge)
// stay pinned. Uses exact float bits — seam duplicates are copied vertices, so
// their positions match to the bit; distinct authored points never collide.
std::vector<std::uint32_t> weld_positions(const std::vector<V>& verts) {
    std::map<std::array<std::uint32_t, 3>, std::uint32_t> canon;
    std::vector<std::uint32_t> pid(verts.size());
    for (std::size_t i = 0; i < verts.size(); ++i) {
        std::array<std::uint32_t, 3> key{};
        std::memcpy(key.data(), &verts[i].position, sizeof(float) * 3);
        auto it = canon.emplace(key, static_cast<std::uint32_t>(canon.size()));
        pid[i] = it.first->second;
    }
    return pid;
}

// Project point q onto the tangent plane at (p, n).
glm::vec3 project_to_plane(const glm::vec3& q, const glm::vec3& p,
                           const glm::vec3& n) {
    return q - glm::dot(q - p, n) * n;
}

// Accumulate the (index, weight) influences of two endpoints, keep the top 4,
// renormalize to sum ~255. Rigid endpoints (identical single bone) pass through
// unchanged; skinned endpoints blend.
void blend_bones(const V& a, const V& b, V& out) {
    std::array<int, 8> idx{};
    std::array<int, 8> wt{};
    int n = 0;
    auto add = [&](int bone, int w) {
        if (w <= 0) return;
        for (int i = 0; i < n; ++i) {
            if (idx[i] == bone) { wt[i] += w; return; }
        }
        idx[n] = bone;
        wt[n] = w;
        ++n;
    };
    for (int k = 0; k < 4; ++k) {
        add(a.bone_indices[k], a.bone_weights[k]);
        add(b.bone_indices[k], b.bone_weights[k]);
    }
    // Partial-sort the top 4 by weight.
    for (int i = 0; i < 4 && i < n; ++i) {
        int best = i;
        for (int j = i + 1; j < n; ++j)
            if (wt[j] > wt[best]) best = j;
        std::swap(wt[i], wt[best]);
        std::swap(idx[i], idx[best]);
    }
    const int keep = n < 4 ? n : 4;
    int total = 0;
    for (int i = 0; i < keep; ++i) total += wt[i];
    out.bone_indices = glm::u8vec4(0, 0, 0, 0);
    out.bone_weights = glm::u8vec4(0, 0, 0, 0);
    if (total <= 0) {
        out.bone_indices[0] = a.bone_indices[0];
        out.bone_weights[0] = 255;
        return;
    }
    int acc = 0;
    for (int i = 0; i < keep; ++i) {
        int w = (i == keep - 1) ? (255 - acc)
                                : static_cast<int>(wt[i] * 255.0f / total + 0.5f);
        acc += w;
        out.bone_indices[i] = static_cast<std::uint8_t>(idx[i]);
        out.bone_weights[i] = static_cast<std::uint8_t>(w < 0 ? 0 : w);
    }
}

V make_midpoint(const V& a, const V& b, bool boundary, float phong_strength) {
    V m;
    const glm::vec3 lin = 0.5f * (a.position + b.position);
    glm::vec3 pos = lin;
    if (!boundary && phong_strength > 0.0f) {
        // Phong tessellation: average the two tangent-plane projections.
        const glm::vec3 phong =
            0.5f * (project_to_plane(lin, a.position, a.normal) +
                    project_to_plane(lin, b.position, b.normal));
        pos = glm::mix(lin, phong, phong_strength);
    }
    m.position = pos;
    glm::vec3 nrm = a.normal + b.normal;
    const float len = glm::length(nrm);
    m.normal = len > 1e-6f ? nrm / len : a.normal;
    m.uv = 0.5f * (a.uv + b.uv);
    m.uv1 = 0.5f * (a.uv1 + b.uv1);
    m.color = glm::u8vec4((glm::ivec4(a.color) + glm::ivec4(b.color)) / 2);
    blend_bones(a, b, m);
    return m;
}

}  // namespace

MeshCpu tessellate_phong(const MeshCpu& src, float phong_strength) {
    const std::size_t tri_count = src.indices.size() / 3;
    if (tri_count == 0) return src;

    // Classify boundary edges by welded POSITION, not vertex index, so a UV
    // seam (duplicate verts across a continuous surface) counts as interior and
    // rounds, while a genuine open border stays pinned.
    const std::vector<std::uint32_t> pid = weld_positions(src.vertices);
    auto pos_edge = [&](std::uint32_t a, std::uint32_t b) {
        return edge_key(pid[a], pid[b]);
    };
    std::unordered_map<std::uint64_t, int> edge_tris;
    edge_tris.reserve(tri_count * 3);
    for (std::size_t t = 0; t < tri_count; ++t) {
        const std::uint32_t i0 = src.indices[t * 3 + 0];
        const std::uint32_t i1 = src.indices[t * 3 + 1];
        const std::uint32_t i2 = src.indices[t * 3 + 2];
        edge_tris[pos_edge(i0, i1)]++;
        edge_tris[pos_edge(i1, i2)]++;
        edge_tris[pos_edge(i2, i0)]++;
    }

    MeshCpu out;
    out.material_index = src.material_index;
    out.node_index = src.node_index;
    out.vertices = src.vertices;  // originals keep their indices
    out.indices.reserve(src.indices.size() * 4);

    // Dedup midpoints by INDEX edge (not position): two triangles that share a
    // UV seam keep their own midpoint on each side so per-side UVs survive. Both
    // land at the same position (same endpoints) so the surface stays watertight.
    std::unordered_map<std::uint64_t, std::uint32_t> mid_cache;
    mid_cache.reserve(tri_count * 3);
    auto midpoint = [&](std::uint32_t a, std::uint32_t b) -> std::uint32_t {
        const std::uint64_t key = edge_key(a, b);
        auto it = mid_cache.find(key);
        if (it != mid_cache.end()) return it->second;
        const bool boundary = edge_tris[pos_edge(a, b)] < 2;
        const std::uint32_t idx = static_cast<std::uint32_t>(out.vertices.size());
        out.vertices.push_back(make_midpoint(src.vertices[a], src.vertices[b],
                                             boundary, phong_strength));
        mid_cache.emplace(key, idx);
        return idx;
    };

    for (std::size_t t = 0; t < tri_count; ++t) {
        const std::uint32_t a = src.indices[t * 3 + 0];
        const std::uint32_t b = src.indices[t * 3 + 1];
        const std::uint32_t c = src.indices[t * 3 + 2];
        const std::uint32_t ab = midpoint(a, b);
        const std::uint32_t bc = midpoint(b, c);
        const std::uint32_t ca = midpoint(c, a);
        const std::uint32_t quad[4][3] = {
            {a, ab, ca}, {ab, b, bc}, {ca, bc, c}, {ab, bc, ca}};
        for (auto& tri : quad) {
            out.indices.push_back(tri[0]);
            out.indices.push_back(tri[1]);
            out.indices.push_back(tri[2]);
        }
    }
    return out;
}

void tessellate_model_in_place(Model& model, int levels, float strength) {
    if (levels <= 0) return;
    for (auto& mesh : model.meshes) {
        if (!mesh.cpu_data()) continue;
        MeshCpu tess = *mesh.cpu_data();
        for (int L = 0; L < levels; ++L)
            tess = tessellate_phong(tess, strength);
        mesh = upload_mesh(tess);
        mesh.set_cpu_data(std::move(tess));
    }
}

}  // namespace assets
