// native/src/renderer/scuff_panels.cc
#include "renderer/scuff_panels.h"

#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <vector>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <assets/model.h>

namespace renderer {
namespace {

struct Entry {
    GLuint buffer = 0;
    GLuint texture = 0;
    GLuint vao = 0;        // the mesh's VAO at build time: a recycled Mesh
                           // address with a different VAO is a different mesh
};

std::unordered_map<const assets::Mesh*, Entry>& cache() {
    static std::unordered_map<const assets::Mesh*, Entry> c;
    return c;
}

/// Node -> model-space matrices (parents precede children in the node list,
/// the same walk compute_model_bounds / ensure_trace_accel rely on).
std::vector<glm::mat4> node_model_matrices(const assets::Model& model) {
    std::vector<glm::mat4> out(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return out;
    out[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            out[i] = out[node.parent_index] * node.local_transform;
        }
    }
    return out;
}

/// Unit direction of the triangle's SHORTEST usable edge, with a canonical
/// sign: the largest-magnitude component positive, so two parallel edges never
/// come out as e and -e (which would mirror the panel grid across a mesh edge).
///
/// Shortest, not longest: BC hulls are authored as quads that the NIF splits
/// along a diagonal, and that diagonal is the longest edge of both halves --
/// on Galaxy.nif 73% of triangles are quad halves (measured 2026-09-21). The
/// diagonal is invisible on the hull; the seams a viewer reads are the quad's
/// sides, and the shortest edge of a quad half is always a side. The grid is
/// symmetric under a quarter turn, so either side yields the same lines.
/// A needle triangle's shortest edge is direction noise, so an edge under
/// kMinEdgeFraction of the longest is skipped for the next shortest.
constexpr float kMinEdgeFraction = 0.05f;

glm::vec3 panel_edge_dir(const glm::vec3& a, const glm::vec3& b, const glm::vec3& c) {
    const glm::vec3 edges[3] = {b - a, c - b, a - c};
    float len2[3];
    float longest2 = 0.0f;
    for (int k = 0; k < 3; ++k) {
        len2[k] = glm::dot(edges[k], edges[k]);
        longest2 = std::max(longest2, len2[k]);
    }
    if (longest2 <= 1e-20f) return glm::vec3(1.0f, 0.0f, 0.0f);
    const float floor2 = longest2 * kMinEdgeFraction * kMinEdgeFraction;
    int best = -1;
    for (int k = 0; k < 3; ++k) {
        if (len2[k] < floor2) continue;
        if (best < 0 || len2[k] < len2[best]) best = k;
    }
    glm::vec3 dir = edges[best] / std::sqrt(len2[best]);
    const glm::vec3 m = glm::abs(dir);
    const float pivot = (m.x >= m.y && m.x >= m.z) ? dir.x : (m.y >= m.z ? dir.y : dir.z);
    return pivot < 0.0f ? -dir : dir;
}

}  // namespace

std::uint32_t scuff_tri_dir_texture(const assets::Model& model,
                                    std::size_t node_index, int mesh_index) {
    if (mesh_index < 0 || mesh_index >= static_cast<int>(model.meshes.size())) return 0;
    if (node_index >= model.nodes.size()) return 0;
    const assets::Mesh& mesh = model.meshes[mesh_index];
    auto& c = cache();
    auto it = c.find(&mesh);
    if (it != c.end() && it->second.vao == mesh.vao()) return it->second.texture;

    const auto& cpu = mesh.cpu_data();
    if (!cpu) return 0;
    const glm::mat4 nm = node_model_matrices(model)[node_index];
    const auto& idx = cpu->indices;
    const auto& verts = cpu->vertices;
    std::vector<glm::vec3> dirs;
    dirs.reserve(idx.size() / 3);
    for (std::size_t k = 0; k + 2 < idx.size(); k += 3) {
        if (idx[k] >= verts.size() || idx[k + 1] >= verts.size() || idx[k + 2] >= verts.size()) {
            dirs.push_back(glm::vec3(1.0f, 0.0f, 0.0f));
            continue;
        }
        const glm::vec3 a(nm * glm::vec4(verts[idx[k]].position, 1.0f));
        const glm::vec3 b(nm * glm::vec4(verts[idx[k + 1]].position, 1.0f));
        const glm::vec3 d(nm * glm::vec4(verts[idx[k + 2]].position, 1.0f));
        dirs.push_back(panel_edge_dir(a, b, d));
    }
    if (dirs.empty()) return 0;

    Entry e;
    e.vao = mesh.vao();
    glGenBuffers(1, &e.buffer);
    glBindBuffer(GL_TEXTURE_BUFFER, e.buffer);
    glBufferData(GL_TEXTURE_BUFFER,
                 static_cast<GLsizeiptr>(dirs.size() * sizeof(glm::vec3)),
                 dirs.data(), GL_STATIC_DRAW);
    glGenTextures(1, &e.texture);
    glBindTexture(GL_TEXTURE_BUFFER, e.texture);
    glTexBuffer(GL_TEXTURE_BUFFER, GL_RGB32F, e.buffer);
    glBindTexture(GL_TEXTURE_BUFFER, 0);
    glBindBuffer(GL_TEXTURE_BUFFER, 0);
    if (it != c.end()) {
        glDeleteTextures(1, &it->second.texture);
        glDeleteBuffers(1, &it->second.buffer);
        it->second = e;
    } else {
        c.emplace(&mesh, e);
    }
    return e.texture;
}

void reset_scuff_tri_dir_cache() {
    for (auto& [mesh, e] : cache()) {
        glDeleteTextures(1, &e.texture);
        glDeleteBuffers(1, &e.buffer);
    }
    cache().clear();
}

}  // namespace renderer
