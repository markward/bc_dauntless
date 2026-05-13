// native/src/renderer/lens_flare_pass.cc
#include "renderer/lens_flare_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>

namespace renderer {

NgonMeshData build_ngon_mesh(int wedges) {
    if (wedges < 3)  wedges = 3;
    if (wedges > 64) wedges = 64;

    NgonMeshData m;
    m.vertices.reserve(static_cast<std::size_t>(wedges) * 3);
    m.indices.reserve(static_cast<std::size_t>(wedges) * 3);

    const float kTwoPi = 6.28318530717958647692f;
    for (int k = 0; k < wedges; ++k) {
        const float a0 = (kTwoPi * static_cast<float>(k))       / static_cast<float>(wedges);
        const float a1 = (kTwoPi * static_cast<float>(k + 1))   / static_cast<float>(wedges);
        const NgonVertex center {{0.0f, 0.0f}, {0.5f, 1.0f}};
        const NgonVertex left   {{std::cos(a0), std::sin(a0)}, {0.0f, 0.0f}};
        const NgonVertex right  {{std::cos(a1), std::sin(a1)}, {1.0f, 0.0f}};
        const unsigned int base = static_cast<unsigned int>(m.vertices.size());
        m.vertices.push_back(center);
        m.vertices.push_back(left);
        m.vertices.push_back(right);
        m.indices.push_back(base + 0);
        m.indices.push_back(base + 1);
        m.indices.push_back(base + 2);
    }
    return m;
}

LensFlarePass::~LensFlarePass() {
    for (auto& [n, mesh] : wedge_meshes_) {
        if (mesh.ebo) glDeleteBuffers(1, &mesh.ebo);
        if (mesh.vbo) glDeleteBuffers(1, &mesh.vbo);
        if (mesh.vao) glDeleteVertexArrays(1, &mesh.vao);
    }
}

void LensFlarePass::render(const std::vector<LensFlareDescriptor>&,
                           const scenegraph::Camera&,
                           Pipeline&,
                           int, int, double) {
    // Implemented in Task 10.
}

LensFlarePass::WedgeMesh& LensFlarePass::ensure_wedge_mesh(int n) {
    auto it = wedge_meshes_.find(n);
    if (it != wedge_meshes_.end()) return it->second;
    NgonMeshData data = build_ngon_mesh(n);
    WedgeMesh m;
    glGenVertexArrays(1, &m.vao);
    glBindVertexArray(m.vao);
    glGenBuffers(1, &m.vbo);
    glBindBuffer(GL_ARRAY_BUFFER, m.vbo);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(data.vertices.size() * sizeof(NgonVertex)),
                 data.vertices.data(), GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(NgonVertex),
                          reinterpret_cast<void*>(offsetof(NgonVertex, pos)));
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(NgonVertex),
                          reinterpret_cast<void*>(offsetof(NgonVertex, uv)));
    glEnableVertexAttribArray(1);
    glGenBuffers(1, &m.ebo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m.ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(data.indices.size() * sizeof(unsigned int)),
                 data.indices.data(), GL_STATIC_DRAW);
    glBindVertexArray(0);
    m.index_count = static_cast<int>(data.indices.size());
    auto [ins_it, _] = wedge_meshes_.emplace(n, m);
    return ins_it->second;
}

assets::Texture* LensFlarePass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[lens_flare] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        auto owned = std::make_unique<assets::Texture>(std::move(tex));
        auto* raw = owned.get();
        texture_cache_.emplace(path, std::move(owned));
        return raw;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[lens_flare] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

}  // namespace renderer
