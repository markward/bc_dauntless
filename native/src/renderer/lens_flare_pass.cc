// native/src/renderer/lens_flare_pass.cc
#include "renderer/lens_flare_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>

namespace renderer {

constexpr float kTwoPi = 6.28318530717958647692f;

// SDK size values (0.001..0.4 typical) are calibrated for BC's original
// projection/viewport; in our renderer they read about 3× too small.
// Applied at render time so the aggregator stays a faithful SDK pass-through.
constexpr float kSizeCalibration = 3.0f;

NgonMeshData build_ngon_mesh(int wedges) {
    if (wedges < 3)  wedges = 3;
    if (wedges > 64) wedges = 64;

    NgonMeshData m;
    m.vertices.reserve(static_cast<std::size_t>(wedges) * 3);
    m.indices.reserve(static_cast<std::size_t>(wedges) * 3);

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

void LensFlarePass::render(const std::vector<LensFlareDescriptor>& flares,
                           const scenegraph::Camera& camera,
                           Pipeline& pipeline,
                           int viewport_w, int viewport_h,
                           double now_seconds) {
    if (flares.empty() || viewport_w <= 0 || viewport_h <= 0) return;

    auto& shader = pipeline.lens_flare_shader();
    shader.use();

    const float aspect =
        static_cast<float>(viewport_w) / static_cast<float>(viewport_h);
    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();

    shader.set_float("u_aspect", aspect);
    shader.set_int("u_texture", 0);
    shader.set_float("u_brightness", 1.0f);
    glActiveTexture(GL_TEXTURE0);

    bool gl_state_active = false;
    auto activate_gl_state = [&]() {
        if (gl_state_active) return;
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
        glDisable(GL_CULL_FACE);
        gl_state_active = true;
    };

    for (const auto& f : flares) {
        const glm::vec4 clip = vp * glm::vec4(f.source_world_pos, 1.0f);
        if (clip.w <= 0.0f) continue;
        const glm::vec3 ndc = glm::vec3(clip) / clip.w;
        if (std::abs(ndc.x) > 1.2f || std::abs(ndc.y) > 1.2f) continue;
        if (ndc.z < -1.0f || ndc.z > 1.0f) continue;

        // Depth occlusion: sample the depth buffer at the source's pixel.
        // The sun sphere itself was drawn into the depth buffer earlier in
        // the frame; eps lifts the test off the sphere's own surface.
        const float u01 = (ndc.x * 0.5f + 0.5f);
        const float v01 = (ndc.y * 0.5f + 0.5f);
        const int px = std::min(viewport_w - 1, std::max(0,
                          static_cast<int>(u01 * static_cast<float>(viewport_w))));
        const int py = std::min(viewport_h - 1, std::max(0,
                          static_cast<int>(v01 * static_cast<float>(viewport_h))));
        float sampled_depth = 1.0f;
        glReadPixels(px, py, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &sampled_depth);
        const float source_depth01 = ndc.z * 0.5f + 0.5f;
        constexpr float kDepthEps = 1e-4f;
        if (sampled_depth + kDepthEps < source_depth01) continue;

        activate_gl_state();

        for (const auto& e : f.elements) {
            assets::Texture* tex = ensure_texture(e.texture_path);
            if (!tex) continue;
            const WedgeMesh& mesh = ensure_wedge_mesh(e.wedges);
            if (mesh.index_count == 0) continue;

            const glm::vec2 src_ndc(ndc.x, ndc.y);
            const glm::vec2 center =
                glm::mix(src_ndc, glm::vec2(0.0f, 0.0f), e.position);
            const float wobble = (e.amp != 0.0f && e.freq != 0.0f)
                ? e.amp * std::sin(kTwoPi * e.freq * static_cast<float>(now_seconds))
                : 0.0f;
            const float scale = e.size * kSizeCalibration * (1.0f + wobble);

            shader.set_vec2("u_screen_center", center);
            shader.set_float("u_scale", scale);
            glBindTexture(GL_TEXTURE_2D, tex->id());
            glBindVertexArray(mesh.vao);
            glDrawElements(GL_TRIANGLES, mesh.index_count, GL_UNSIGNED_INT, nullptr);
        }
    }

    if (gl_state_active) {
        glBindVertexArray(0);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glEnable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
    }
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
