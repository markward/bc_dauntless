// native/src/renderer/motion_blur_pass.cc
//
// Camera motion blur: depthless fixed-distance reprojection against the
// previous-frame view-projection. Reuses resolve.vert.

#include <renderer/motion_blur_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_motion_blur_fs.h"

namespace renderer {

MotionBlurPass::MotionBlurPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::motion_blur_fs)) {
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

MotionBlurPass::~MotionBlurPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void MotionBlurPass::draw(std::uint32_t src_tex, std::uint32_t dst_fbo,
                          int fw, int fh, const glm::mat4& inv_proj,
                          const glm::mat3& cam_rot, const glm::vec3& cam_pos,
                          const glm::mat4& prev_viewproj) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, dst_fbo);
    glViewport(0, 0, fw, fh);

    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    shader_->use();
    shader_->set_int("u_src", 0);
    shader_->set_mat4("u_inv_proj", inv_proj);
    shader_->set_mat3("u_cam_rot", cam_rot);
    shader_->set_vec3("u_cam_pos", cam_pos);
    shader_->set_mat4("u_prev_viewproj", prev_viewproj);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
