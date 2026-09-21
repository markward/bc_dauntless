// native/src/renderer/scuff_panels.cc
#include "renderer/scuff_panels.h"

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

/// Unit longest-edge direction with a canonical sign: the largest-magnitude
/// component positive, so two parallel edges never come out as e and -e
/// (which would mirror the panel grid across a mesh edge).
glm::vec3 longest_edge_dir(const glm::vec3& a, const glm::vec3& b, const glm::vec3& c) {
    const glm::vec3 edges[3] = {b - a, c - b, a - c};
    glm::vec3 best = edges[0];
    float best_len = glm::dot(best, best);
    for (int k = 1; k < 3; ++k) {
        const float l = glm::dot(edges[k], edges[k]);
        if (l > best_len) { best = edges[k]; best_len = l; }
    }
    if (best_len <= 1e-20f) return glm::vec3(1.0f, 0.0f, 0.0f);
    best /= std::sqrt(best_len);
    const glm::vec3 m = glm::abs(best);
    const float pivot = (m.x >= m.y && m.x >= m.z) ? best.x : (m.y >= m.z ? best.y : best.z);
    return pivot < 0.0f ? -best : best;
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
        dirs.push_back(longest_edge_dir(a, b, d));
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
