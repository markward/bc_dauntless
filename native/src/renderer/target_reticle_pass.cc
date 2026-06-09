// native/src/renderer/target_reticle_pass.cc
#include "renderer/target_reticle_pass.h"
#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <vector>

namespace renderer {

namespace {

constexpr const char* kCornerFile    = "game/data/target.tga";
constexpr const char* kCrosshairFile = "game/data/subtarget.tga";

// Constant on-screen size (pixels) for each corner glyph and the crosshair.
constexpr float kCornerSizePx    = 24.0f;
constexpr float kCrosshairSizePx = 20.0f;

std::unique_ptr<assets::Texture> load_tga(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[target_reticle] failed to open '%s'\n", path);
        return std::make_unique<assets::Texture>();
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        return std::make_unique<assets::Texture>(std::move(tex));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[target_reticle] decode/upload '%s' failed: %s\n",
                     path, e.what());
        return std::make_unique<assets::Texture>();
    }
}

}  // namespace

TargetReticlePass::TargetReticlePass()  = default;
TargetReticlePass::~TargetReticlePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void TargetReticlePass::ensure_quad() {
    if (quad_vao_) return;
    const float corners[12] = {
        -0.5f, -0.5f,   0.5f, -0.5f,   0.5f,  0.5f,
        -0.5f, -0.5f,   0.5f,  0.5f,  -0.5f,  0.5f,
    };
    glGenVertexArrays(1, &quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindVertexArray(quad_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(corners), corners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void TargetReticlePass::ensure_textures() {
    if (textures_loaded_) return;
    textures_loaded_ = true;
    corner_tex_    = load_tga(kCornerFile);
    crosshair_tex_ = load_tga(kCrosshairFile);
}

void TargetReticlePass::render(const TargetReticle& reticle,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline) {
    if (!reticle.visible) return;
    ensure_quad();
    ensure_textures();

    auto& shader = pipeline.target_reticle_shader();
    shader.use();

    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 vp   = camera.proj_matrix() * view;
    shader.set_mat4("u_view_proj", vp);

    // World-space camera basis = rows of the view rotation (see pin pass).
    const glm::vec3 cam_right(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up   (view[0][1], view[1][1], view[2][1]);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_tex", 0);

    // px → world conversion at a given distance (constant on-screen size).
    const glm::mat4 proj = camera.proj_matrix();
    const float tan_half = (proj[1][1] != 0.0f) ? (1.0f / proj[1][1]) : 1.0f;
    GLint vp_rect[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp_rect);
    const float viewport_h = (vp_rect[3] > 0) ? static_cast<float>(vp_rect[3]) : 1.0f;
    const glm::vec3 eye = camera.eye;
    auto world_for_px = [&](const glm::vec3& at, float px) {
        return glm::length(at - eye) * (2.0f * px * tan_half / viewport_h);
    };

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    // --- Full-ship corner box (target.tga) ---
    glBindTexture(GL_TEXTURE_2D, corner_tex_ ? corner_tex_->id() : 0);
    const float r = reticle.ship_radius;
    const float corner_size = world_for_px(reticle.ship_center, kCornerSizePx);
    // (sign_right, sign_up, uv_flip_x, uv_flip_y) — UL, UR, LL, LR.
    const float corners[4][4] = {
        {-1.0f,  1.0f,  1.0f,  1.0f},   // upper-left  (art as authored)
        { 1.0f,  1.0f, -1.0f,  1.0f},   // upper-right (mirror H)
        {-1.0f, -1.0f,  1.0f, -1.0f},   // lower-left  (mirror V)
        { 1.0f, -1.0f, -1.0f, -1.0f},   // lower-right (mirror H+V)
    };
    for (const auto& c : corners) {
        const glm::vec3 centre = reticle.ship_center
                               + cam_right * (c[0] * r)
                               + cam_up    * (c[1] * r);
        shader.set_vec3 ("u_center_world", centre);
        shader.set_float("u_size_world",   corner_size);
        shader.set_vec2 ("u_uv_flip", glm::vec2(c[2], c[3]));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // --- Subtarget crosshair (subtarget.tga) ---
    if (reticle.has_subtarget) {
        glBindTexture(GL_TEXTURE_2D, crosshair_tex_ ? crosshair_tex_->id() : 0);
        shader.set_vec3 ("u_center_world", reticle.subtarget_pos);
        shader.set_float("u_size_world",
                         world_for_px(reticle.subtarget_pos, kCrosshairSizePx));
        shader.set_vec2 ("u_uv_flip", glm::vec2(1.0f, 1.0f));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
