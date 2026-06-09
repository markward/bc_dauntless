// native/src/renderer/subsystem_pin_pass.cc
#include "renderer/subsystem_pin_pass.h"
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

// Glyph paths indexed by DamageIcons enum (engine/ui/damage_icons.py
// ICON_REGISTRY). Ids 0–9 map to the ten entries below.
constexpr const char* kGlyphFiles[10] = {
    "game/data/Icons/Damage/Hull.tga",       // 0
    "game/data/Icons/Damage/Impulse.tga",    // 1
    "game/data/Icons/Damage/Phaser.tga",     // 2
    "game/data/Icons/Damage/Power.tga",      // 3
    "game/data/Icons/Damage/Sensor.tga",     // 4
    "game/data/Icons/Damage/Shield.tga",     // 5
    "game/data/Icons/Damage/System.tga",     // 6 (default)
    "game/data/Icons/Damage/Torpedo.tga",    // 7
    "game/data/Icons/Damage/Warp.tga",       // 8
    "game/data/Icons/Damage/Disruptor.tga",  // 9
};

// Constant on-screen pin size (pixels), independent of zoom/distance. The
// per-pin world size is derived each frame so the billboard projects to this
// many pixels of viewport height regardless of how far the camera is.
constexpr float kPinSizePx = 60.0f;

}  // namespace

SubsystemPinPass::SubsystemPinPass() = default;

SubsystemPinPass::~SubsystemPinPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void SubsystemPinPass::ensure_quad() {
    if (quad_vao_) return;

    // Two triangles forming a unit square centred at (0,0) in billboard-local
    // coordinates. The vertex shader will expand these using cam_right/cam_up.
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
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE,
                          2 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void SubsystemPinPass::ensure_glyphs() {
    if (glyphs_loaded_) return;
    glyphs_loaded_ = true;
    glyphs_.resize(10);

    for (int i = 0; i < 10; ++i) {
        std::ifstream in(kGlyphFiles[i], std::ios::binary);
        if (!in) {
            std::fprintf(stderr, "[subsystem_pin] glyph %d: failed to open '%s' (using blank disc)\n",
                         i, kGlyphFiles[i]);
            glyphs_[i] = std::make_unique<assets::Texture>();
            continue;
        }
        std::vector<std::uint8_t> bytes(
            (std::istreambuf_iterator<char>(in)),
            std::istreambuf_iterator<char>());
        try {
            assets::Image img = assets::decode_tga(bytes);
            assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
            glyphs_[i] = std::make_unique<assets::Texture>(std::move(tex));
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[subsystem_pin] glyph %d: decode/upload failed: %s\n",
                         i, e.what());
            glyphs_[i] = std::make_unique<assets::Texture>();
        }
    }
}

void SubsystemPinPass::render(const std::vector<SubsystemPin>& pins,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline) {
    if (pins.empty()) return;
    ensure_quad();
    ensure_glyphs();

    auto& shader = pipeline.subsystem_pin_shader();
    shader.use();

    // Build view-projection matrix.
    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 vp   = camera.proj_matrix() * view;
    shader.set_mat4("u_view_proj", vp);

    // Extract world-space camera basis from the view matrix.
    //
    // GLM mat4 is column-major: view[col][row].
    // The upper-left 3x3 of the view matrix is the world→camera rotation R.
    // Its ROWS are the camera basis vectors expressed in world space:
    //   row 0 (camera right in world) = (R[0][0], R[1][0], R[2][0])
    //   row 1 (camera up    in world) = (R[0][1], R[1][1], R[2][1])
    // The billboard vertex shader reconstructs a world-space quad corner as:
    //   center_world + corner.x * cam_right * size + corner.y * cam_up * size
    // which is always perpendicular to the view direction → camera-facing. ✓
    const glm::vec3 cam_right(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up   (view[0][1], view[1][1], view[2][1]);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_glyph",        0);  // texture unit 0

    // Constant on-screen pin size: derive the world size per pin from its
    // camera distance so the billboard projects to kPinSizePx pixels of
    // viewport height at any zoom. tan(fov_y/2) = 1/proj[1][1]; viewport
    // height from the current GL viewport. world = 2·dist·px·tan / height.
    const glm::mat4 proj = camera.proj_matrix();
    const float tan_half_fov = (proj[1][1] != 0.0f) ? (1.0f / proj[1][1]) : 1.0f;
    GLint vp_rect[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp_rect);
    const float viewport_h = (vp_rect[3] > 0) ? static_cast<float>(vp_rect[3]) : 1.0f;
    const float px_to_world = 2.0f * kPinSizePx * tan_half_fov / viewport_h;
    const glm::vec3 eye = camera.eye;

    // State: blend on, depth-test off (pins always on top), cull off (two-sided).
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    for (const auto& p : pins) {
        const int id = (p.icon_id >= 0 && p.icon_id < 10) ? p.icon_id : 6;
        const auto& tex = glyphs_[id];
        // Bind glyph texture; id()==0 on a default-constructed Texture is
        // a valid bind (black/transparent result) — shader disc still shows.
        glBindTexture(GL_TEXTURE_2D, tex ? tex->id() : 0);

        const float dist = glm::length(p.world_pos - eye);
        const float size = dist * px_to_world * (p.highlighted ? 1.3f : 1.0f);
        shader.set_vec3 ("u_center_world", p.world_pos);
        shader.set_float("u_size_world",   size);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);

    // Restore default frame state: depth test on, cull on, blend off.
    // (Most passes assume depth test is ENABLED; this matches phaser_pass
    // restore behavior and the surrounding frame's expectations.)
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
