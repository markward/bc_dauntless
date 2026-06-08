// native/src/renderer/fxaa_pass.cc
//
// Fullscreen-triangle FXAA pass: samples the resolved LDR color texture and
// writes anti-aliased color to the currently-bound framebuffer.

#include <renderer/fxaa_pass.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include "embedded_fxaa_vs.h"
#include "embedded_fxaa_fs.h"

namespace renderer {

FxaaPass::FxaaPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::fxaa_vs, shader_src::fxaa_fs)) {
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

FxaaPass::~FxaaPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void FxaaPass::draw(std::uint32_t ldr_color_tex, int fw, int fh) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    const float inv_w = fw > 0 ? 1.0f / static_cast<float>(fw) : 0.0f;
    const float inv_h = fh > 0 ? 1.0f / static_cast<float>(fh) : 0.0f;

    shader_->use();
    shader_->set_int("u_tex", 0);
    shader_->set_vec2("u_inv_resolution", glm::vec2(inv_w, inv_h));

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, ldr_color_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
