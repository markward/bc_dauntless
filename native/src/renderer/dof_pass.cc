// native/src/renderer/dof_pass.cc
//
// Fullscreen-triangle depth-of-field over an HDR colour + depth pair.
// Reuses resolve.vert.

#include <renderer/dof_pass.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include "embedded_resolve_vs.h"
#include "embedded_dof_fs.h"

namespace renderer {

DofPass::DofPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::dof_fs)) {
    // Fullscreen-triangle trick: one triangle covering [-1,3]² clipspace.
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

DofPass::~DofPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void DofPass::draw(std::uint32_t src_tex, std::uint32_t depth_tex,
                   std::uint32_t dest_fbo, int fw, int fh,
                   float near_gu, float far_gu, const DofParams& p) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, dest_fbo);
    glViewport(0, 0, fw, fh);

    // The fullscreen triangle winds CCW; the Pipeline sets CW front-facing, so
    // it would be culled as a back face → black screen. Disable + restore.
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    shader_->use();
    shader_->set_int("u_src",   0);
    shader_->set_int("u_depth", 1);
    shader_->set_float("u_near",          near_gu);
    shader_->set_float("u_far",           far_gu);
    shader_->set_float("u_focus_gu",      p.focus_gu);
    shader_->set_float("u_blend",         p.blend);
    shader_->set_float("u_near_strength", p.near_strength);
    shader_->set_float("u_far_strength",  p.far_strength);
    shader_->set_float("u_far_ceiling",   p.far_ceiling);
    shader_->set_float("u_near_sharp_gu", p.near_sharp_gu);
    shader_->set_float("u_near_full_gu",  p.near_full_gu);
    // The radius is authored as a fraction of screen HEIGHT so it is
    // resolution-independent; converting here keeps the framebuffer size out
    // of the shader.
    shader_->set_float("u_max_radius_px",
                       p.max_radius_frac * static_cast<float>(fh));
    shader_->set_vec2("u_texel",
                      glm::vec2(1.0f / static_cast<float>(fw),
                                1.0f / static_cast<float>(fh)));

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src_tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, depth_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
