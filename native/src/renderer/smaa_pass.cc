// native/src/renderer/smaa_pass.cc
//
// SMAA 1x: three fullscreen passes over the resolved LDR color texture.
#include <renderer/smaa_pass.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <string>

#include "embedded_smaa_lib.h"
#include "embedded_smaa_edge_vs.h"
#include "embedded_smaa_edge_fs.h"
#include "embedded_smaa_weight_vs.h"
#include "embedded_smaa_weight_fs.h"
#include "embedded_smaa_blend_vs.h"
#include "embedded_smaa_blend_fs.h"

#include "area_tex.h"
#include "search_tex.h"

namespace renderer {
namespace {

// Common GLSL prologue + SMAA library, prepended to every stage source.
// `stage_defines` selects VS vs PS code paths inside the SMAA library.
std::string compose(const char* stage_defines, const char* entry) {
    return std::string("#version 330 core\n")
         + "#define SMAA_GLSL_3 1\n"
         + "#define SMAA_PRESET_HIGH 1\n"
         + stage_defines
         + shader_src::smaa_lib + "\n"
         + entry;
}

GLuint make_lut(GLint internal_fmt, GLenum fmt, int w, int h,
                const unsigned char* bytes) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt,
                 GL_UNSIGNED_BYTE, bytes);
    glBindTexture(GL_TEXTURE_2D, 0);
    return tex;
}

GLuint make_target(GLint internal_fmt, GLenum fmt, int w, int h, GLuint* fbo_out) {
    GLuint tex = 0, fbo = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt,
                 GL_UNSIGNED_BYTE, nullptr);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    *fbo_out = fbo;
    return tex;
}

}  // namespace

SmaaPass::SmaaPass()
    : edge_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_edge_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_edge_fs).c_str())),
      weight_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_weight_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_weight_fs).c_str())),
      blend_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_blend_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_blend_fs).c_str())) {
    const float verts[] = { -1.0f, -1.0f,  3.0f, -1.0f,  -1.0f, 3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);

    area_tex_   = make_lut(GL_RG8, GL_RG, AREATEX_WIDTH, AREATEX_HEIGHT, areaTexBytes);
    search_tex_ = make_lut(GL_R8,  GL_RED, SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, searchTexBytes);
}

SmaaPass::~SmaaPass() {
    destroy_targets();
    if (search_tex_) glDeleteTextures(1, &search_tex_);
    if (area_tex_)   glDeleteTextures(1, &area_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void SmaaPass::destroy_targets() {
    if (edges_fbo_)   glDeleteFramebuffers(1, &edges_fbo_);
    if (edges_tex_)   glDeleteTextures(1, &edges_tex_);
    if (weights_fbo_) glDeleteFramebuffers(1, &weights_fbo_);
    if (weights_tex_) glDeleteTextures(1, &weights_tex_);
    edges_fbo_ = edges_tex_ = weights_fbo_ = weights_tex_ = 0;
}

void SmaaPass::resize(int w, int h) {
    if (w == width_ && h == height_ && edges_tex_) return;
    destroy_targets();
    edges_tex_   = make_target(GL_RG8,   GL_RG,   w, h, &edges_fbo_);
    weights_tex_ = make_target(GL_RGBA8, GL_RGBA, w, h, &weights_fbo_);
    width_ = w; height_ = h;
}

void SmaaPass::draw(std::uint32_t ldr_color_tex, std::uint32_t dest_fbo,
                    int fw, int fh) {
    resize(fw, fh);

    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    const glm::vec4 rt(fw > 0 ? 1.0f / fw : 0.0f,
                       fh > 0 ? 1.0f / fh : 0.0f,
                       static_cast<float>(fw), static_cast<float>(fh));

    glBindVertexArray(vao_);

    // Pass 1: edge detection -> edges_tex_
    glBindFramebuffer(GL_FRAMEBUFFER, edges_fbo_);
    glViewport(0, 0, fw, fh);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    edge_->use();
    edge_->set_vec4("u_rt_metrics", rt);
    edge_->set_int("u_color_tex", 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, ldr_color_tex);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 2: blend-weight calc -> weights_tex_
    glBindFramebuffer(GL_FRAMEBUFFER, weights_fbo_);
    glViewport(0, 0, fw, fh);
    glClear(GL_COLOR_BUFFER_BIT);
    weight_->use();
    weight_->set_vec4("u_rt_metrics", rt);
    weight_->set_int("u_edges_tex", 0);
    weight_->set_int("u_area_tex", 1);
    weight_->set_int("u_search_tex", 2);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, edges_tex_);
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, area_tex_);
    glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, search_tex_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 3: neighborhood blend -> dest_fbo
    glBindFramebuffer(GL_FRAMEBUFFER, dest_fbo);
    glViewport(0, 0, fw, fh);
    blend_->use();
    blend_->set_vec4("u_rt_metrics", rt);
    blend_->set_int("u_color_tex", 0);
    blend_->set_int("u_blend_tex", 1);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, ldr_color_tex);
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, weights_tex_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glBindVertexArray(0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
