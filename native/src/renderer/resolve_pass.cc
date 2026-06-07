// native/src/renderer/resolve_pass.cc
//
// Fullscreen-triangle resolve pass: samples the HDR RGBA16F color texture
// and writes to the currently-bound framebuffer. This task: passthrough only
// (clamp(color,0,1)); tonemapping is wired in a later task.

#include <renderer/resolve_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_resolve_fs.h"

namespace renderer {

ResolvePass::ResolvePass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::resolve_fs)) {
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

ResolvePass::~ResolvePass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
    // shader_ is RAII — no glDeleteProgram needed here.
}

void ResolvePass::draw(std::uint32_t hdr_color_tex) {
    // Save GL state we clobber so 3D passes on the next frame see unchanged config.
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    shader_->use();
    shader_->set_int("u_hdr", 0);
    shader_->set_int("u_hdr_enabled", hdr_enabled_ ? 1 : 0);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_color_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glBindTexture(GL_TEXTURE_2D, 0);

    // Restore.
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
