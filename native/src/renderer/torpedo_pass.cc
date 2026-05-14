// native/src/renderer/torpedo_pass.cc
#include "renderer/torpedo_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>

namespace renderer {

namespace {

// Unit-quad corners: two triangles (-1,-1)→(+1,+1).
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

// SDK Create() params for PhotonTorpedo.py read as:
//   core_a=0.2  core_b=1.2   ⇒ small bright pinpoint
//   glow_a=3.0  glow_b=0.3  glow_c=0.6   ⇒ larger soft halo
//   flares_a=0.7  flares_b=0.4  num_flares=8   ⇒ rotating star
// We interpret size_a as the renderer half-size in world units; size_b/c
// (when present) modulate intensity / aspect.
constexpr float kSizeScale = 0.5f;

}  // namespace

TorpedoPass::TorpedoPass() = default;

TorpedoPass::~TorpedoPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void TorpedoPass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners,
                 GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

assets::Texture* TorpedoPass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[torpedo_pass] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
    std::fprintf(stderr, "[torpedo_pass] loaded '%s'\n", path.c_str());
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
        std::fprintf(stderr, "[torpedo_pass] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

void TorpedoPass::render(const std::vector<TorpedoDescriptor>& torpedoes,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (torpedoes.empty()) return;
    ensure_quad_mesh();

    auto& shader = pipeline.torpedo_shader();
    shader.use();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    // Extract camera right/up from the view matrix.  Camera basis vectors
    // in world space are the rows of the view matrix's upper-left 3×3.
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_right = glm::vec3(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up    = glm::vec3(view[0][1], view[1][1], view[2][1]);

    shader.set_mat4("u_view_proj",     vp);
    shader.set_vec3("u_camera_right",  cam_right);
    shader.set_vec3("u_camera_up",     cam_up);
    shader.set_int ("u_texture",       0);

    // Additive blend, depth-test against scene, depth-write off.
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    auto draw_layer = [&](const std::string& path,
                          const glm::vec4& color,
                          float size,
                          const glm::vec3& world_pos,
                          float rotation,
                          float alpha) {
        if (path.empty() || size <= 0.0f) return;
        assets::Texture* tex = ensure_texture(path);
        if (!tex) return;
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_vec3 ("u_world_position", world_pos);
        shader.set_float("u_size",           size * kSizeScale);
        shader.set_vec4 ("u_tint",           color);
        shader.set_float("u_rotation",       rotation);
        shader.set_float("u_alpha",          alpha);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    };

    for (const auto& t : torpedoes) {
        // Animation: flares spin slowly around billboard centre; glow
        // pulses subtly in brightness; core stays steady.
        constexpr float kFlaresSpinRate = 1.2f;   // radians per second
        constexpr float kGlowPulseRate  = 6.0f;   // radians per second
        constexpr float kGlowPulseDepth = 0.15f;  // ±15% brightness swing
        const float flares_rot  = t.age * kFlaresSpinRate;
        const float glow_alpha  = 1.0f - kGlowPulseDepth
                                  + kGlowPulseDepth * std::sin(t.age * kGlowPulseRate);
        // Draw order: glow (largest, dimmest), then flares, then core
        // (smallest, brightest) — additive so order is mostly cosmetic.
        draw_layer(t.glow_texture,   t.glow_color,   t.glow_size_a,   t.world_pos,
                   0.0f, glow_alpha);
        draw_layer(t.flares_texture, t.flares_color, t.flares_size_a, t.world_pos,
                   flares_rot, 1.0f);
        // Core size is the product of size_a (~0.2) × size_b (~1.2) = ~0.24.
        draw_layer(t.core_texture,   t.core_color,
                    t.core_size_a * t.core_size_b, t.world_pos,
                    0.0f, 1.0f);
    }

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
