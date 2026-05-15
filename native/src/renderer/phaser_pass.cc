// native/src/renderer/phaser_pass.cc
#include "renderer/phaser_pass.h"
#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdio>
#include <fstream>

namespace renderer {

namespace {
constexpr const char* kBeamTexturePath = "game/data/Textures/Tactical/PhaserLights.tga";
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

void PhaserPass::ensure_mesh(const std::vector<PhaserBeamDescriptor>& beams) {
    if (beam_vao_ == 0) {
        glGenVertexArrays(1, &beam_vao_);
        glGenBuffers(1, &beam_vbo_);
    }
    // Pack per-vertex: emitter.xyz, target.xyz, corner.
    // Six vertices per beam.
    struct Vertex { glm::vec3 emitter; glm::vec3 target; float corner; };
    std::vector<Vertex> verts;
    verts.reserve(beams.size() * 6);
    for (const auto& b : beams) {
        for (int c = 0; c < 6; ++c) {
            verts.push_back({b.emitter_world, b.target_world,
                             static_cast<float>(c)});
        }
    }
    glBindVertexArray(beam_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, beam_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(Vertex)),
                 verts.data(), GL_DYNAMIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<void*>(offsetof(Vertex, emitter)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<void*>(offsetof(Vertex, target)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<void*>(offsetof(Vertex, corner)));
    glBindVertexArray(0);
}

void PhaserPass::render(const std::vector<PhaserBeamDescriptor>& beams,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline) {
    if (beams.empty()) return;
    ensure_texture();
    if (!texture_ || texture_->id() == 0) return;
    ensure_mesh(beams);

    auto& shader = pipeline.phaser_shader();
    shader.use();
    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader.set_mat4("u_view_proj", vp);
    shader.set_vec3("u_camera_pos", camera.eye);
    shader.set_int ("u_texture",   0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, texture_->id());

    glBindVertexArray(beam_vao_);
    // Each beam has its own color + width; issue one draw call per beam.
    for (std::size_t i = 0; i < beams.size(); ++i) {
        shader.set_vec4 ("u_color", beams[i].color);
        shader.set_float("u_width", beams[i].width);
        glDrawArrays(GL_TRIANGLES, static_cast<GLint>(i * 6), 6);
    }
    glBindVertexArray(0);

    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
