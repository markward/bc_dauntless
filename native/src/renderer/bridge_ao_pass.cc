// native/src/renderer/bridge_ao_pass.cc
#include "renderer/bridge_ao_pass.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/shader.h"

#include "embedded_resolve_vs.h"
#include "embedded_bridge_ao_fs.h"

#include <glad/glad.h>

#include <scenegraph/camera.h>

#include <glm/glm.hpp>

#include <algorithm>

namespace renderer {

BridgeAoPass::BridgeAoPass() = default;

BridgeAoPass::~BridgeAoPass() {
    if (vbo_) { GLuint b = vbo_; glDeleteBuffers(1, &b); }
    if (vao_) { GLuint v = vao_; glDeleteVertexArrays(1, &v); }
    if (sampler_raw_) { GLuint smp = sampler_raw_; glDeleteSamplers(1, &smp); }
}

std::uint32_t BridgeAoPass::ao_texture() const { return ao_.color_texture(); }
std::uint32_t BridgeAoPass::depth_texture() const { return pre_.depth_texture(); }
std::uint32_t BridgeAoPass::raw_sampler() const { return sampler_raw_; }
int BridgeAoPass::ao_width() const { return ao_.width(); }
int BridgeAoPass::ao_height() const { return ao_.height(); }

void BridgeAoPass::ensure_gl() {
    if (shader_) return;
    shader_ = std::make_unique<Shader>(shader_src::resolve_vs, shader_src::bridge_ao_fs);
    // Full-screen triangle.
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    GLuint vao = 0, vbo = 0;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    vao_ = vao;
    vbo_ = vbo;
    // Raw (non-compare, NEAREST) sampler for reading window depth.
    GLuint smp = 0;
    glGenSamplers(1, &smp);
    glSamplerParameteri(smp, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glSamplerParameteri(smp, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glSamplerParameteri(smp, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glSamplerParameteri(smp, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glSamplerParameteri(smp, GL_TEXTURE_COMPARE_MODE, GL_NONE);
    sampler_raw_ = smp;
}

bool BridgeAoPass::render(const scenegraph::Camera& camera, int w, int h,
                          const BridgeAoSettings& s,
                          const std::function<void()>& draw_normals) {
    if (w < 8 || h < 8) return false;
    // Capture the caller's state FIRST: a target resize rebinds FBO 0.
    GLint prev_fbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    GLint prev_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, prev_vp);
    GLfloat prev_clear[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prev_clear);

    ensure_gl();
    pre_.resize(w, h);   // no-op when already that size
    // The AO itself at a fraction of the view's resolution (the GPU cost is
    // the per-pixel kernel: half-res is a quarter of it); bridge.frag's
    // depth-aware filter upsamples it against the full-resolution depth.
    const int aw = std::max(8, static_cast<int>(static_cast<float>(w) * s.resolution_scale));
    const int ah = std::max(8, static_cast<int>(static_cast<float>(h) * s.resolution_scale));
    ao_.resize(aw, ah);

    // 1. Normal + depth pre-pass from the eye: the bridge drawn with its real
    //    shaders in normal-output mode, so the AO sees the same smooth normals
    //    the lighting uses (a derivative normal is flat per triangle and shows
    //    every facet of a low-poly face).
    pre_.bind();
    glViewport(0, 0, w, h);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    draw_normals();

    // 2. Full-screen AO from that depth + normal.
    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 proj = camera.proj_matrix();
    ao_.bind();
    glViewport(0, 0, aw, ah);
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    shader_->use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, pre_.depth_texture());
    glBindSampler(0, sampler_raw_);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pre_.color_texture());
    glActiveTexture(GL_TEXTURE0);
    shader_->set_int("u_depth", 0);
    shader_->set_int("u_normal", 1);
    shader_->set_mat4("u_view", view);
    shader_->set_mat4("u_proj", proj);
    shader_->set_mat4("u_inv_proj", glm::inverse(proj));
    shader_->set_vec2("u_viewport", glm::vec2(static_cast<float>(w), static_cast<float>(h)));
    shader_->set_float("u_radius", kBridgeLighting.ao_radius);
    shader_->set_float("u_strength", kBridgeLighting.ao_strength);
    shader_->set_float("u_bias", kBridgeLighting.ao_bias);
    shader_->set_int("u_samples", s.samples);
    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
    glBindSampler(0, 0);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));
    glViewport(prev_vp[0], prev_vp[1], prev_vp[2], prev_vp[3]);
    glClearColor(prev_clear[0], prev_clear[1], prev_clear[2], prev_clear[3]);
    return true;
}

}  // namespace renderer
