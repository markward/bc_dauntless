// native/src/voxel/src/voxelize.cc
#include <voxel/voxelize.h>
#include <assets/model.h>
#include <nif/block.h>
#include <nif/file.h>
#include <array>
#include <cmath>
#include <cstdint>
#include <queue>
#include <unordered_map>
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

void solidify(VoxelVolume& v) {
    const glm::ivec3 d = v.dims;
    std::vector<std::uint8_t> exterior(v.occ.size(), 0);
    std::queue<glm::ivec3> q;
    auto push_if_empty = [&](int x, int y, int z) {
        if (x < 0 || y < 0 || z < 0 || x >= d.x || y >= d.y || z >= d.z) return;
        std::size_t i = v.index(x, y, z);
        if (v.occ[i] == 0 && exterior[i] == 0) { exterior[i] = 1; q.push({x, y, z}); }
    };
    // Seed from every border voxel.
    for (int z = 0; z < d.z; ++z)
    for (int y = 0; y < d.y; ++y)
    for (int x = 0; x < d.x; ++x)
        if (x==0||y==0||z==0||x==d.x-1||y==d.y-1||z==d.z-1) push_if_empty(x, y, z);
    // BFS through empty space.
    const int dx[6]={1,-1,0,0,0,0}, dy[6]={0,0,1,-1,0,0}, dz[6]={0,0,0,0,1,-1};
    while (!q.empty()) {
        glm::ivec3 c = q.front(); q.pop();
        for (int k = 0; k < 6; ++k) push_if_empty(c.x+dx[k], c.y+dy[k], c.z+dz[k]);
    }
    // Anything not reached and not already solid surface = interior solid.
    for (std::size_t i = 0; i < v.occ.size(); ++i)
        if (exterior[i] == 0) v.occ[i] = 1;
}

VoxelVolume voxelize_into(const std::vector<Tri>& tris,
                          glm::ivec3 dims,
                          glm::vec3  origin,
                          glm::vec3  cell) {
    VoxelVolume v;
    v.dims   = dims;
    v.origin = origin;
    v.cell   = cell;
    v.occ.assign(std::size_t(dims.x) * std::size_t(dims.y) * std::size_t(dims.z), 0);
    surface_voxelize(v, tris);
    solidify(v);
    return v;
}

VoxelVolume voxelize_tris(const std::vector<Tri>& tris, glm::ivec3 dims) {
    // Guard: empty tris — return an all-empty volume.
    if (tris.empty()) {
        VoxelVolume v;
        v.dims = dims;
        v.cell = glm::vec3(1.f);
        v.origin = glm::vec3(0.f);
        v.occ.assign(std::size_t(dims.x) * std::size_t(dims.y) * std::size_t(dims.z), 0);
        return v;
    }

    glm::vec3 mn(1e30f), mx(-1e30f);
    for (const auto& t : tris) {
        mn = glm::min(mn, glm::min(t.a, glm::min(t.b, t.c)));
        mx = glm::max(mx, glm::max(t.a, glm::max(t.b, t.c)));
    }

    glm::vec3 extent = mx - mn;
    glm::vec3 cell   = extent / glm::vec3(dims - 2);   // 1-voxel margin each side
    glm::vec3 origin = mn - cell;                       // shift so margin voxels are empty
    return voxelize_into(tris, dims, origin, cell);
}

VoxelVolume voxelize(const assets::Model& model, glm::ivec3 dims) {
    return voxelize_tris(collect_hull_triangles(model), dims);
}

// ---- GL-free NiNode triangle walk ----------------------------------------
// Mirrors voxel_inspect's hull_tris()/accumulate_tris() but lives in the voxel
// library so both tools and tests can use it without duplicating the code.

namespace {

struct InspMat4 {
    std::array<float, 16> m{};
    float& at(int r, int c) { return m[static_cast<std::size_t>(r * 4 + c)]; }
    float  at(int r, int c) const { return m[static_cast<std::size_t>(r * 4 + c)]; }
    static InspMat4 identity() {
        InspMat4 o;
        o.at(0,0) = o.at(1,1) = o.at(2,2) = o.at(3,3) = 1.f;
        return o;
    }
};

InspMat4 insp_mul(const InspMat4& a, const InspMat4& b) {
    InspMat4 o;
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float s = 0;
            for (int k = 0; k < 4; ++k) s += a.at(r,k) * b.at(k,c);
            o.at(r,c) = s;
        }
    return o;
}

InspMat4 av_to_insp_mat4(const nif::AvObjectBase& av) {
    InspMat4 o = InspMat4::identity();
    const auto& R = av.rotation.m;  // row-major 3x3
    const float s = av.scale;
    o.at(0,0)=R[0]*s; o.at(0,1)=R[1]*s; o.at(0,2)=R[2]*s;
    o.at(1,0)=R[3]*s; o.at(1,1)=R[4]*s; o.at(1,2)=R[5]*s;
    o.at(2,0)=R[6]*s; o.at(2,1)=R[7]*s; o.at(2,2)=R[8]*s;
    o.at(0,3)=av.translation.x;
    o.at(1,3)=av.translation.y;
    o.at(2,3)=av.translation.z;
    return o;
}

glm::vec3 insp_transform(const InspMat4& M, const nif::Vec3& p) {
    return glm::vec3(
        M.at(0,0)*p.x + M.at(0,1)*p.y + M.at(0,2)*p.z + M.at(0,3),
        M.at(1,0)*p.x + M.at(1,1)*p.y + M.at(1,2)*p.z + M.at(1,3),
        M.at(2,0)*p.x + M.at(2,1)*p.y + M.at(2,2)*p.z + M.at(2,3)
    );
}

void accumulate_nif_tris(const nif::File& f,
                         const std::unordered_map<std::uint32_t,std::size_t>& links,
                         std::size_t idx,
                         const InspMat4& parent,
                         std::vector<bool>& visited,
                         std::vector<Tri>& out) {
    if (idx >= f.blocks.size() || visited[idx]) return;
    visited[idx] = true;
    const auto& blk = f.blocks[idx];
    if (auto* n = std::get_if<nif::NiNode>(&blk)) {
        InspMat4 world = insp_mul(parent, av_to_insp_mat4(n->av));
        for (auto link : n->child_links) {
            auto it = links.find(link);
            if (it != links.end())
                accumulate_nif_tris(f, links, it->second, world, visited, out);
        }
    } else if (auto* sh = std::get_if<nif::NiTriShape>(&blk)) {
        InspMat4 world = insp_mul(parent, av_to_insp_mat4(sh->av));
        auto it = links.find(sh->data_link);
        if (it == links.end()) return;
        const auto* d = std::get_if<nif::NiTriShapeData>(&f.blocks[it->second]);
        if (!d) return;
        for (const auto& tri : d->triangles) {
            if (tri[0] >= d->vertices.size() ||
                tri[1] >= d->vertices.size() ||
                tri[2] >= d->vertices.size()) continue;
            out.push_back({
                insp_transform(world, d->vertices[tri[0]]),
                insp_transform(world, d->vertices[tri[1]]),
                insp_transform(world, d->vertices[tri[2]]),
            });
        }
    }
}

}  // anonymous namespace

std::vector<Tri> collect_hull_triangles_from_nif(const nif::File& f) {
    std::unordered_map<std::uint32_t,std::size_t> links;
    links.reserve(f.block_ids.size());
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) links[f.block_ids[i]] = i;

    std::vector<Tri> out;
    std::vector<bool> visited(f.blocks.size(), false);
    if (f.root.ptr) {
        std::size_t start = 0;
        for (std::size_t i = 0; i < f.blocks.size(); ++i)
            if (&f.blocks[i] == f.root.ptr) { start = i; break; }
        accumulate_nif_tris(f, links, start, InspMat4::identity(), visited, out);
    } else {
        for (std::size_t i = 0; i < f.blocks.size(); ++i)
            accumulate_nif_tris(f, links, i, InspMat4::identity(), visited, out);
    }
    return out;
}

}  // namespace voxel
