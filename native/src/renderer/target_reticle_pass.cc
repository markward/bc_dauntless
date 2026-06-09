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
constexpr const char* kBarFile   = "game/data/Icons/tilehorizline.tga";
constexpr const char* kArrowFile = "game/data/Icons/TargetArrow.tga";

// Constant on-screen size (pixels) for each corner glyph and the crosshair.
constexpr float kCornerSizePx    = 24.0f;
constexpr float kCrosshairSizePx = 40.0f;

// Chrome palette (rgb 0..1, a = alpha scale). From the UI config-panel gradient.
constexpr glm::vec4 kBoxTint      {0.847f, 0.518f, 0.314f, 1.0f};  // orange #d88450
constexpr glm::vec4 kCrosshairTint{1.000f, 0.860f, 0.000f, 1.0f};  // yellow
constexpr glm::vec4 kBarTint  {1.000f, 0.860f, 0.000f, 1.0f};  // yellow
constexpr glm::vec4 kArrowTint{0.300f, 0.850f, 0.300f, 1.0f};  // green
constexpr float kBarWidthPx  = 10.0f;   // on-screen length of each horizontal tick
constexpr float kBarTilePx   = 6.0f;    // on-screen vertical spacing between ticks
constexpr float kArrowSizePx = 11.0f;   // on-screen arrow size

// Green convergence indicator: two horizontal lines that sit apart when the
// target is off-axis and meet (becoming the arrow) when it lines up fore/aft.
constexpr float kMarkerLenPx   = 14.0f;  // length of each green converging line
constexpr float kMarkerThickPx = 4.0f;   // thickness of each green converging line
constexpr float kMarkerSpan    = 0.85f;  // max half-separation as fraction of r
constexpr float kLinedUpThresh = 0.04f;  // misalign below this -> show the arrow

// Texture sub-rect (umin, vmin, uextent, vextent). Most elements use the full
// texture; the arrow samples just the centre up-triangle of TargetArrow.tga,
// a 64x32 three-arrow atlas (left + centre-up + right), to avoid drawing the
// whole jumbled sheet.
constexpr glm::vec4 kFullUvRect {0.0f,   0.0f, 1.0f,   1.0f};
constexpr glm::vec4 kArrowUvRect{0.375f, 0.0f, 0.281f, 0.70f};

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
    bar_tex_   = load_tga(kBarFile);
    arrow_tex_ = load_tga(kArrowFile);
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
    const float kCornerDefs[4][4] = {
        {-1.0f,  1.0f,  1.0f,  1.0f},   // upper-left  (art as authored)
        { 1.0f,  1.0f, -1.0f,  1.0f},   // upper-right (mirror H)
        {-1.0f, -1.0f,  1.0f, -1.0f},   // lower-left  (mirror V)
        { 1.0f, -1.0f, -1.0f, -1.0f},   // lower-right (mirror H+V)
    };
    shader.set_vec4("u_tint",    kBoxTint);
    shader.set_vec4("u_uv_rect", kFullUvRect);   // box/crosshair use full texture
    shader.set_vec2("u_rot",     glm::vec2(1.0f, 0.0f));  // unrotated
    for (const auto& c : kCornerDefs) {
        const glm::vec3 centre = reticle.ship_center
                               + cam_right * (c[0] * r)
                               + cam_up    * (c[1] * r);
        shader.set_vec3("u_center_world", centre);
        shader.set_vec2("u_size_world",   glm::vec2(corner_size, corner_size));
        shader.set_vec2("u_uv_flip",      glm::vec2(c[2], c[3]));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // --- Subtarget crosshair (subtarget.tga) ---
    if (reticle.has_subtarget) {
        glBindTexture(GL_TEXTURE_2D, crosshair_tex_ ? crosshair_tex_->id() : 0);
        const float cs = world_for_px(reticle.subtarget_pos, kCrosshairSizePx);
        shader.set_vec4("u_tint",         kCrosshairTint);
        shader.set_vec3("u_center_world", reticle.subtarget_pos);
        shader.set_vec2("u_size_world",   glm::vec2(cs, cs));
        shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // --- Fore/aft side bars: tiled yellow ticks + a green convergence
    //     indicator. Two green horizontal lines sit apart when the target is
    //     off-axis and converge as it lines up; when lined up (fore or aft)
    //     they meet and become a single green arrow. ---
    if (reticle.has_bars) {
        const float bar_w = world_for_px(reticle.ship_center, kBarWidthPx);
        // Tile the single-line tile vertically so the bar reads as a column of
        // repeating horizontal ticks: v runs 0..reps and the texture wraps.
        const float world_per_px = world_for_px(reticle.ship_center, 1.0f);
        const float bar_px  = (world_per_px > 1e-9f) ? (2.0f * r / world_per_px) : 0.0f;
        const float bar_reps = (bar_px > kBarTilePx) ? (bar_px / kBarTilePx) : 1.0f;
        const float align = (reticle.bar_alignment < -1.0f) ? -1.0f
                          : (reticle.bar_alignment >  1.0f) ?  1.0f
                          : reticle.bar_alignment;
        const float aa = (align < 0.0f) ? -align : align;
        const float misalign = 1.0f - aa;                // 0 = lined up, 1 = abeam
        const bool lined_up = misalign < kLinedUpThresh;
        for (float side : {-1.0f, 1.0f}) {               // left, right edge
            const glm::vec3 bar_centre = reticle.ship_center + cam_right * (side * r);
            // Bar: a vertical strip of repeating horizontal yellow ticks.
            glBindTexture(GL_TEXTURE_2D, bar_tex_ ? bar_tex_->id() : 0);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);  // crisp tiled lines
            shader.set_vec4("u_tint",        kBarTint);
            shader.set_vec4("u_uv_rect",     glm::vec4(0.0f, 0.0f, 1.0f, bar_reps));
            shader.set_vec2("u_rot",         glm::vec2(1.0f, 0.0f));
            shader.set_vec3("u_center_world", bar_centre);
            shader.set_vec2("u_size_world",   glm::vec2(bar_w, 2.0f * r));
            shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
            glDrawArrays(GL_TRIANGLES, 0, 6);

            if (lined_up) {
                // Converged: a single green arrow (centre triangle, 90°).
                const float asz = world_for_px(bar_centre, kArrowSizePx);
                glBindTexture(GL_TEXTURE_2D, arrow_tex_ ? arrow_tex_->id() : 0);
                shader.set_vec4("u_tint",        kArrowTint);
                shader.set_vec4("u_uv_rect",     kArrowUvRect);
                // Rotate 90°; sign flips with the side so the left arrow is the
                // horizontal mirror of the right (both point inward).
                shader.set_vec2("u_rot",         glm::vec2(0.0f, side));
                shader.set_vec3("u_center_world", bar_centre);
                shader.set_vec2("u_size_world",   glm::vec2(asz, asz));
                shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
                glDrawArrays(GL_TRIANGLES, 0, 6);
            } else {
                // Two green horizontal lines converging toward the centre; the
                // separation shrinks as the target lines up (misalign -> 0).
                const float off = misalign * r * kMarkerSpan;
                const float mw  = world_for_px(bar_centre, kMarkerLenPx);
                const float mh  = world_for_px(bar_centre, kMarkerThickPx);
                glBindTexture(GL_TEXTURE_2D, bar_tex_ ? bar_tex_->id() : 0);
                shader.set_vec4("u_tint",        kArrowTint);   // green
                shader.set_vec4("u_uv_rect",     kFullUvRect);
                shader.set_vec2("u_rot",         glm::vec2(1.0f, 0.0f));
                shader.set_vec2("u_size_world",   glm::vec2(mw, mh));
                shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
                for (float ms : {-1.0f, 1.0f}) {
                    const glm::vec3 mc = bar_centre + cam_up * (ms * off);
                    shader.set_vec3("u_center_world", mc);
                    glDrawArrays(GL_TRIANGLES, 0, 6);
                }
            }
        }
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
