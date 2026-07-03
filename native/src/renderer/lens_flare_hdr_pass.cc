// native/src/renderer/lens_flare_hdr_pass.cc
//
// Image-based screen-space lens flare. Reads the bloom mip0 texture (already
// half-res, blurred, thresholded, HDR-valued) and renders a half-res flare
// texture (ghosts + halo + chromatic dispersion) for the resolve pass to
// composite additively. The blurred source keeps the ghosts soft without a
// dedicated blur pass. See shaders/lens_flare_hdr.frag.

#include <renderer/lens_flare_hdr_pass.h>
#include <renderer/shader.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include "embedded_resolve_vs.h"
#include "embedded_lens_flare_hdr_fs.h"
#include "embedded_lens_flare_blur_fs.h"

namespace renderer {

LensFlareHdrPass::LensFlareHdrPass()
    : shader_(std::make_unique<Shader>(shader_src::resolve_vs,
                                       shader_src::lens_flare_hdr_fs)),
      blur_shader_(std::make_unique<Shader>(shader_src::resolve_vs,
                                            shader_src::lens_flare_blur_fs)) {
    // Fullscreen-triangle: one triangle covering [-1,3]² clipspace.
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

LensFlareHdrPass::~LensFlareHdrPass() {
    destroy();
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

namespace {
// Create a half-res RGBA16F color target (tex + fbo).
void make_target(int w, int h, std::uint32_t& tex, std::uint32_t& fbo) {
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);

    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}
}  // namespace

void LensFlareHdrPass::destroy() {
    if (tex_) glDeleteTextures(1, &tex_);
    if (fbo_) glDeleteFramebuffers(1, &fbo_);
    if (blur_tex_) glDeleteTextures(1, &blur_tex_);
    if (blur_fbo_) glDeleteFramebuffers(1, &blur_fbo_);
    tex_ = fbo_ = blur_tex_ = blur_fbo_ = 0;
    fw_ = 0;
    fh_ = 0;
}

void LensFlareHdrPass::rebuild(int fw, int fh) {
    destroy();

    int w = fw / 2;   // half-res, matching bloom mip0
    int h = fh / 2;
    if (w < 1) w = 1;
    if (h < 1) h = 1;

    make_target(w, h, tex_, fbo_);
    make_target(w, h, blur_tex_, blur_fbo_);

    fw_ = fw;
    fh_ = fh;
}

std::uint32_t LensFlareHdrPass::render(std::uint32_t bloom_mip0_tex, int fw, int fh) {
    if (fw != fw_ || fh != fh_ || !fbo_) {
        rebuild(fw, fh);
    }

    // Save the state we clobber (the fullscreen triangle winds CCW; the
    // Pipeline sets CW front-facing, so culling would drop it → black).
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, fw / 2 > 0 ? fw / 2 : 1, fh / 2 > 0 ? fh / 2 : 1);
    shader_->use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, bloom_mip0_tex);
    shader_->set_int("u_src", 0);
    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // ── Separable Gaussian blur (radius baked in the shader): softens the
    //    ghosts/halo. tex_ →(H)→ blur_tex_ →(V)→ tex_.
    const int w = fw / 2 > 0 ? fw / 2 : 1;
    const int h = fh / 2 > 0 ? fh / 2 : 1;
    blur_shader_->use();
    blur_shader_->set_int("u_src", 0);
    glActiveTexture(GL_TEXTURE0);

    // Horizontal: tex_ → blur_tex_
    glBindFramebuffer(GL_FRAMEBUFFER, blur_fbo_);
    glBindTexture(GL_TEXTURE_2D, tex_);
    blur_shader_->set_vec2("u_dir", glm::vec2(1.0f / static_cast<float>(w), 0.0f));
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Vertical: blur_tex_ → tex_
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glBindTexture(GL_TEXTURE_2D, blur_tex_);
    blur_shader_->set_vec2("u_dir", glm::vec2(0.0f, 1.0f / static_cast<float>(h)));
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glBindVertexArray(0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);

    return tex_;
}

}  // namespace renderer
