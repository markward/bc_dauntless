// native/src/renderer/starmap_pass.cc
#include "renderer/starmap_pass.h"
#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace renderer {

namespace {

// Shader `u_kind` selectors. The vertex stage only distinguishes disc (0),
// line (1) and "screen-space" (anything else); the fragment stage splits the
// screen-space case into point (2), bracket (3) and star cloud (4).
constexpr int kKindDisc    = 0;
constexpr int kKindLine    = 1;
constexpr int kKindPoint   = 2;
constexpr int kKindBracket = 3;
constexpr int kKindStarCloud = 4;

// Opaque map backdrop. "The game stays visible" means AROUND the modal, not
// through it — a transparent map over a moving starfield is unreadable.
constexpr glm::vec4 kBackdrop{0.02f, 0.03f, 0.06f, 1.0f};

// Deliberately NO mark->colour table and no marker-size literals here.
// engine/ui/star_map.py owns the MARK_* enum and the whole map palette
// (MARK_*_COLOR, BRACKET_SIZE_PX, STAR_SIZE_PX, STAR_SELECTED_SIZE_PX); a
// second copy in C++ would let a Python renumber silently recolour reticles,
// and would put every tuning tweak behind a rebuild. Colours and pixel sizes
// arrive per primitive.

}  // namespace

StarMapPass::StarMapPass() = default;

StarMapPass::~StarMapPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
    if (line_vbo_) glDeleteBuffers(1, &line_vbo_);
    if (line_vao_) glDeleteVertexArrays(1, &line_vao_);
}

void StarMapPass::ensure_buffers() {
    if (quad_vao_ == 0) {
        // Corners in [0,1]: both shader stages map them to [-1,1] themselves
        // (the vertex stage for the offset, the fragment stage for the radial
        // falloff), so v_uv must arrive un-signed.
        const float corners[12] = {
            0.0f, 0.0f,   1.0f, 0.0f,   1.0f, 1.0f,
            0.0f, 0.0f,   1.0f, 1.0f,   0.0f, 1.0f,
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
    if (line_vao_ == 0) {
        // Two vertices; a_corner.x selects u_line_a vs u_line_b in the shader.
        const float ends[4] = {0.0f, 0.0f,   1.0f, 0.0f};
        glGenVertexArrays(1, &line_vao_);
        glGenBuffers(1, &line_vbo_);
        glBindVertexArray(line_vao_);
        glBindBuffer(GL_ARRAY_BUFFER, line_vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(ends), ends, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
        glBindVertexArray(0);
    }
}

void StarMapPass::render(const StarMapScene& scene,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline,
                         float device_scale_factor) {
    if (!scene.enabled) return;
    if (scene.viewport.z <= 0 || scene.viewport.w <= 0) return;
    ensure_buffers();

    // --- save state (see letterbox_pass.cc) ---
    GLint prev_viewport[4]; glGetIntegerv(GL_VIEWPORT, prev_viewport);
    GLint prev_box[4];      glGetIntegerv(GL_SCISSOR_BOX, prev_box);
    GLfloat prev_clear[4];  glGetFloatv(GL_COLOR_CLEAR_VALUE, prev_clear);
    const GLboolean prev_scissor = glIsEnabled(GL_SCISSOR_TEST);
    const GLboolean prev_depth   = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend   = glIsEnabled(GL_BLEND);
    const GLboolean prev_cull    = glIsEnabled(GL_CULL_FACE);
    GLint prev_src_rgb = GL_ONE, prev_dst_rgb = GL_ZERO;
    GLint prev_src_a   = GL_ONE, prev_dst_a   = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB,   &prev_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB,   &prev_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &prev_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &prev_dst_a);

    glEnable(GL_SCISSOR_TEST);
    glScissor(scene.viewport.x, scene.viewport.y,
              scene.viewport.z, scene.viewport.w);
    glViewport(scene.viewport.x, scene.viewport.y,
               scene.viewport.z, scene.viewport.w);

    // Opaque fill: "game visible" means AROUND the modal, not through it.
    glClearColor(kBackdrop.r, kBackdrop.g, kBackdrop.b, kBackdrop.a);
    glClear(GL_COLOR_BUFFER_BIT);

    glDisable(GL_DEPTH_TEST);          // painter's order, decided in Python
    glDisable(GL_CULL_FACE);           // billboards have no meaningful winding
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    // The map's projection must use the SUB-RECT's aspect, not the window's,
    // or the rendered star positions drift away from the ones
    // engine/ui/star_map.project_points computes for picking and labels (it
    // derives aspect from the same rect). Copy the camera rather than mutate
    // the caller's.
    const float vw = static_cast<float>(scene.viewport.z);
    const float vh = static_cast<float>(scene.viewport.w);
    scenegraph::Camera cam = camera;
    cam.aspect = vw / vh;

    auto& shader = pipeline.starmap_shader();
    shader.use();
    const glm::mat4 view = cam.view_matrix();
    shader.set_mat4("u_view_proj", cam.proj_matrix() * view);

    // World-space camera basis = rows of the view rotation (see pin pass).
    shader.set_vec3("u_camera_right", glm::vec3(view[0][0], view[1][0], view[2][0]));
    shader.set_vec3("u_camera_up",    glm::vec3(view[0][1], view[1][1], view[2][1]));

    const float dsf = (device_scale_factor > 0.0f) ? device_scale_factor : 1.0f;
    // px -> NDC half-extent: the vertex stage offsets by +/-u_pixel_size, so a
    // marker `px` wide needs px/viewport_dimension per axis.
    auto ndc_half = [&](float px) {
        return glm::vec2(px * dsf / vw, px * dsf / vh);
    };

    // ---- Draw in the order Python supplied. No sorting here: the disc
    // back-to-front sort and the painter's order across kinds are decided and
    // tested in engine/ui/star_map.build_scene. ----

    // 1. Discs — soft world-space billboards (nebulae, star clouds).
    glBindVertexArray(quad_vao_);
    shader.set_int("u_kind", kKindDisc);
    shader.set_vec2("u_pixel_size", glm::vec2(0.0f));
    for (const auto& d : scene.discs) {
        shader.set_vec3 ("u_center",     d.position);
        shader.set_vec3 ("u_color",      d.color);
        shader.set_float("u_world_size", d.radius);
        shader.set_float("u_opacity",    d.opacity);
        shader.set_float("u_border",      d.border_opacity);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // 2. Lines — grid, drop-lines, plotted course.
    if (!scene.lines.empty()) {
        glBindVertexArray(line_vao_);
        shader.set_int  ("u_kind",    kKindLine);
        shader.set_float("u_opacity", 1.0f);
        for (const auto& l : scene.lines) {
            shader.set_vec3("u_line_a", l.a);
            shader.set_vec3("u_line_b", l.b);
            shader.set_vec3("u_color",  l.color);
            glDrawArrays(GL_LINES, 0, 2);
        }
        glBindVertexArray(quad_vao_);
    }

    // 3. Points — one dot per system, constant pixel size at any zoom.
    //    size_px arrives already resolved for selection; `selected` is not
    //    read here (see StarMapPoint).
    shader.set_int  ("u_kind",       kKindPoint);
    shader.set_float("u_world_size", 0.0f);
    shader.set_float("u_opacity",    1.0f);
    for (const auto& p : scene.points) {
        shader.set_vec3("u_center",     p.position);
        shader.set_vec3("u_color",      p.color);
        shader.set_vec3("u_core_color", p.core_color);
        shader.set_vec2("u_pixel_size", ndc_half(p.size_px));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // 4. Brackets — reticles for LIVE relationships only (here / course /
    //    mission). Colour and size come from Python; `mark` is never
    //    interpreted here. u_opacity is set explicitly rather than inherited
    //    from the points block, so this block stands alone if the draw order
    //    is ever guarded or rearranged.
    shader.set_int  ("u_kind",    kKindBracket);
    shader.set_float("u_opacity", 1.0f);
    for (const auto& b : scene.brackets) {
        shader.set_vec3("u_center",     b.position);
        shader.set_vec3("u_color",      b.color);
        shader.set_vec2("u_pixel_size", ndc_half(b.size_px));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    // 5. Star clouds — dense-star regions as a small fixed-size glyph, never
    //    selectable. Screen-scaled like the points and brackets above, NOT
    //    world-scaled like the nebula discs: drawn at their model `size` they
    //    became volumes that swallowed whole regions of the map.
    shader.set_int("u_kind", kKindStarCloud);
    for (const auto& g : scene.starclouds) {
        shader.set_vec3 ("u_center",     g.position);
        shader.set_vec3 ("u_color",      g.color);
        shader.set_float("u_opacity",    g.opacity);
        shader.set_vec2 ("u_pixel_size", ndc_half(g.size_px));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);

    // --- restore state ---
    glBlendFuncSeparate(static_cast<GLenum>(prev_src_rgb),
                        static_cast<GLenum>(prev_dst_rgb),
                        static_cast<GLenum>(prev_src_a),
                        static_cast<GLenum>(prev_dst_a));
    if (!prev_blend)   glDisable(GL_BLEND);
    if (prev_depth)    glEnable(GL_DEPTH_TEST);
    if (prev_cull)     glEnable(GL_CULL_FACE);
    glClearColor(prev_clear[0], prev_clear[1], prev_clear[2], prev_clear[3]);
    glScissor(prev_box[0], prev_box[1], prev_box[2], prev_box[3]);
    if (!prev_scissor) glDisable(GL_SCISSOR_TEST);
    glViewport(prev_viewport[0], prev_viewport[1],
               prev_viewport[2], prev_viewport[3]);
}

}  // namespace renderer
