// native/src/renderer/phaser_pass.cc
#include "renderer/phaser_pass.h"
#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <GLFW/glfw3.h>
#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdio>
#include <fstream>

namespace renderer {

namespace {
// Source-of-truth: galaxy.py:438 → SetTextureName("data/phaser.tga").
// PhaserLights.tga (in Textures/Tactical/) is the lit-strip markings on
// the saucer hull, NOT the beam visual.
constexpr const char* kBeamTexturePath = "game/data/phaser.tga";
}

PhaserPass::PhaserPass() = default;

PhaserPass::~PhaserPass() {
    if (beam_vbo_) glDeleteBuffers(1, &beam_vbo_);
    if (beam_vao_) glDeleteVertexArrays(1, &beam_vao_);
}

void PhaserPass::ensure_texture() {
    if (texture_loaded_) return;
    texture_loaded_ = true;
    std::ifstream in(kBeamTexturePath, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[phaser_pass] failed to open '%s'\n", kBeamTexturePath);
        texture_ = std::make_unique<assets::Texture>();
        return;
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
        texture_ = std::make_unique<assets::Texture>(std::move(tex));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[phaser_pass] failed to decode '%s': %s\n",
                     kBeamTexturePath, e.what());
        texture_ = std::make_unique<assets::Texture>();
    }
}

struct PrismVertex {
    glm::vec3 emitter;
    glm::vec3 target;
    float     t;
    float     side_angle;  // radians around beam axis
};

constexpr float kTau = 6.28318530717958647692f;

void PhaserPass::ensure_mesh(const std::vector<PhaserBeamDescriptor>& beams) {
    if (beam_vao_ == 0) {
        glGenVertexArrays(1, &beam_vao_);
        glGenBuffers(1, &beam_vbo_);
    }
    std::vector<PrismVertex> verts;
    std::size_t total = 0;
    for (const auto& b : beams) {
        const int n = (b.num_sides > 0) ? b.num_sides : 6;
        total += static_cast<std::size_t>(n) * 6u;
    }
    verts.reserve(total);
    for (const auto& b : beams) {
        const int n = (b.num_sides > 0) ? b.num_sides : 6;
        for (int s = 0; s < n; ++s) {
            const float a0 = (kTau * static_cast<float>(s))     / static_cast<float>(n);
            const float a1 = (kTau * static_cast<float>(s + 1)) / static_cast<float>(n);
            verts.push_back({b.emitter_world, b.target_world, 0.0f, a0});
            verts.push_back({b.emitter_world, b.target_world, 1.0f, a0});
            verts.push_back({b.emitter_world, b.target_world, 1.0f, a1});
            verts.push_back({b.emitter_world, b.target_world, 0.0f, a0});
            verts.push_back({b.emitter_world, b.target_world, 1.0f, a1});
            verts.push_back({b.emitter_world, b.target_world, 0.0f, a1});
        }
    }
    glBindVertexArray(beam_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, beam_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(PrismVertex)),
                 verts.data(), GL_DYNAMIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(PrismVertex),
                          reinterpret_cast<void*>(offsetof(PrismVertex, emitter)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(PrismVertex),
                          reinterpret_cast<void*>(offsetof(PrismVertex, target)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(PrismVertex),
                          reinterpret_cast<void*>(offsetof(PrismVertex, t)));
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, sizeof(PrismVertex),
                          reinterpret_cast<void*>(offsetof(PrismVertex, side_angle)));
    glBindVertexArray(0);
}

void PhaserPass::render(const std::vector<PhaserBeamDescriptor>& beams,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline,
                         bool depth_test) {
    if (beams.empty()) return;
    ensure_texture();
    if (!texture_ || texture_->id() == 0) return;
    ensure_mesh(beams);

    auto& shader = pipeline.phaser_shader();
    shader.use();
    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader.set_mat4("u_view_proj", vp);
    shader.set_int ("u_texture",    0);
    const float time = static_cast<float>(glfwGetTime());
    shader.set_float("u_time", time);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    if (depth_test) glEnable(GL_DEPTH_TEST);
    else            glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, texture_->id());

    glBindVertexArray(beam_vao_);
    GLint vert_offset = 0;
    for (const auto& b : beams) {
        const int n = (b.num_sides > 0) ? b.num_sides : 6;
        shader.set_vec4 ("u_color",            b.color);
        shader.set_float("u_main_radius",      b.width);
        shader.set_float("u_taper_radius",     b.taper_radius);
        shader.set_float("u_taper_ratio",      b.taper_ratio);
        shader.set_float("u_taper_min_length", b.taper_min_length);
        shader.set_float("u_taper_max_length", b.taper_max_length);
        shader.set_float("u_perimeter_tile",   b.perimeter_tile);
        shader.set_float("u_texture_speed",    b.texture_speed);
        shader.set_float("u_tiles",            b.u_tiles > 0.0f ? b.u_tiles : 1.0f);
        glDrawArrays(GL_TRIANGLES, vert_offset, n * 6);
        vert_offset += n * 6;
    }
    glBindVertexArray(0);

    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);   // restore (no-op for gameplay path)
    glDisable(GL_BLEND);
}

}  // namespace renderer
