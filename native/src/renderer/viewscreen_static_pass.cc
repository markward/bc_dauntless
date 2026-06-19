#include <renderer/viewscreen_static_pass.h>
#include <renderer/shader.h>
#include <assets/flip_frame.h>
#include <glad/glad.h>
#include <fstream>
#include <iterator>
#include <cstdio>

namespace renderer {

namespace {
assets::Texture load_tga(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { std::fprintf(stderr, "[vs-static] open '%s' failed\n", path.c_str()); return {}; }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                     std::istreambuf_iterator<char>());
    try { return assets::upload_image(assets::decode_tga(bytes), /*generate_mipmaps=*/false); }
    catch (const std::exception& e) {
        std::fprintf(stderr, "[vs-static] decode '%s': %s\n", path.c_str(), e.what());
        return {};
    }
}
}  // namespace

ViewscreenStaticPass::~ViewscreenStaticPass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void ViewscreenStaticPass::ensure_quad() {
    if (vao_) return;
    const float verts[] = { -1.f, -1.f,  3.f, -1.f,  -1.f, 3.f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void ViewscreenStaticPass::set_textures(const std::vector<std::string>& paths) {
    if (paths == loaded_paths_) return;
    frames_.clear();
    for (const auto& p : paths) {
        assets::Texture t = load_tga(p);
        if (t.id() != 0) frames_.push_back(std::move(t));
    }
    loaded_paths_ = paths;
}

void ViewscreenStaticPass::set_solid_noise_for_test(float v) {
    GLuint id = 0; glGenTextures(1, &id);
    glBindTexture(GL_TEXTURE_2D, id);
    const unsigned char px[4] = {
        (unsigned char)(v * 255), (unsigned char)(v * 255),
        (unsigned char)(v * 255), 255 };
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    frames_.clear();
    frames_.emplace_back(id, 1, 1, false);
    loaded_paths_ = {"__test_solid__"};
}

void ViewscreenStaticPass::render(Shader& shader, float intensity, double wall_time) {
    if (frames_.empty() || intensity <= 0.0f) return;
    ensure_quad();
    const int n = static_cast<int>(frames_.size());
    const int frame = assets::compute_flip_frame_index(
        wall_time, /*start*/0.0, /*freq*/1.0, /*phase*/0.0, /*delta*/1.0 / 15.0, n);

    const GLboolean prev_blend = glIsEnabled(GL_BLEND);
    const GLboolean prev_depth = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_cull  = glIsEnabled(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    shader.use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, frames_[frame].id());
    shader.set_int("u_noise", 0);
    shader.set_float("u_intensity", intensity);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    if (!prev_blend) glDisable(GL_BLEND);
    if (prev_depth)  glEnable(GL_DEPTH_TEST);
    if (prev_cull)   glEnable(GL_CULL_FACE);
}

}  // namespace renderer
