// native/src/renderer/warp_in_flash_pass.cc
#include "renderer/warp_in_flash_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

namespace {

// Ribbon half-width in streak sigmas: exp(-3^2) ~ 1e-4, below the shader's
// discard floor, so the streak's gaussian is wholly inside the ribbon.
constexpr float kRibbonHalfWidthSigmas = 3.0f;

}  // namespace

WarpInFlashPass::~WarpInFlashPass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void WarpInFlashPass::initialize_gl() {
    // Unit quad in [-1, 1], two triangles, one vec2 attribute (location 0).
    static const float kQuad[] = {
        -1.0f, -1.0f,   1.0f, -1.0f,   1.0f, 1.0f,
        -1.0f, -1.0f,   1.0f,  1.0f,  -1.0f, 1.0f,
    };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuad), kQuad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    initialized_ = true;
}

void WarpInFlashPass::render(const scenegraph::Camera& cam,
                             const std::vector<WarpInFlashDescriptor>& flashes,
                             const WarpInFlashParams& params,
                             Pipeline& pipeline) {
    if (flashes.empty()) return;
    if (!initialized_) initialize_gl();

    // Save exactly what we change, restore it after.
    const GLboolean was_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean was_blend = glIsEnabled(GL_BLEND);
    const GLboolean was_cull = glIsEnabled(GL_CULL_FACE);
    GLboolean was_depth_mask = GL_TRUE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &was_depth_mask);
    GLint was_depth_func = GL_LESS;
    glGetIntegerv(GL_DEPTH_FUNC, &was_depth_func);
    GLint src_rgb = GL_ONE, dst_rgb = GL_ZERO, src_a = GL_ONE, dst_a = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB, &src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &dst_a);

    // Additive, depth-tested (a nearer hull or planet hides it), no writes.
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glDisable(GL_CULL_FACE);

    Shader& sh = pipeline.warp_in_flash_shader();
    sh.use();
    sh.set_mat4("u_view", cam.view_matrix());
    sh.set_mat4("u_proj", cam.proj_matrix());
    sh.set_float("u_core_radii", params.core_radii);
    sh.set_float("u_streak_radii", params.streak_radii);
    sh.set_float("u_ring_radii", params.ring_radii);
    sh.set_float("u_ribbon_half_w",
                 kRibbonHalfWidthSigmas * kStreakThickness * params.core_radii);
    sh.set_float("u_intensity", params.intensity);
    sh.set_vec3("u_tint", params.tint);

    glBindVertexArray(vao_);
    for (const auto& f : flashes) {
        const float t = (f.lifetime > 0.0f) ? (f.age / f.lifetime) : 1.0f;
        if (t >= 1.0f || f.radius <= 0.0f) continue;
        sh.set_vec3("u_center", f.world_center);
        sh.set_vec3("u_forward", f.forward);
        sh.set_float("u_radius", f.radius);
        sh.set_float("u_t", t);
        sh.set_int("u_mode", 0);   // billboard: core + ring
        glDrawArrays(GL_TRIANGLES, 0, 6);
        sh.set_int("u_mode", 1);   // ribbon: streak
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);

    glBlendFuncSeparate(static_cast<GLenum>(src_rgb), static_cast<GLenum>(dst_rgb),
                        static_cast<GLenum>(src_a), static_cast<GLenum>(dst_a));
    if (!was_blend) glDisable(GL_BLEND);
    if (was_cull) glEnable(GL_CULL_FACE);
    glDepthMask(was_depth_mask);
    glDepthFunc(static_cast<GLenum>(was_depth_func));
    if (!was_depth_test) glDisable(GL_DEPTH_TEST);
}

}  // namespace renderer
