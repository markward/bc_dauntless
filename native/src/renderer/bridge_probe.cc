// native/src/renderer/bridge_probe.cc
#include "renderer/bridge_probe.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/shader.h"
#include "probe_capture_gl.h"

#include "embedded_probe_prefilter_vs.h"
#include "embedded_probe_prefilter_fs.h"
#include "embedded_brdf_lut_vs.h"
#include "embedded_brdf_lut_fs.h"

#include <glad/glad.h>

namespace renderer {

namespace {

using probe_gl::GlState;
using probe_gl::full_screen_state;
using probe_gl::have_context;
using probe_gl::make_triangle;

constexpr int kBrdfLutSamples = 512;

}  // namespace

struct BridgeProbe::SavedState { GlState gl; };

BridgeProbe::BridgeProbe() = default;

BridgeProbe::~BridgeProbe() {
    // raw_ / out_ release their own cube, depth and FBO; prefilter_ its program.
    if (vbo_) { GLuint b = vbo_; glDeleteBuffers(1, &b); }
    if (vao_) { GLuint v = vao_; glDeleteVertexArrays(1, &v); }
}

bool BridgeProbe::ensure() {
    if (prefilter_ && raw_.valid() && out_.valid()) return true;
    if (!have_context()) return false;
    GlState s;
    s.save();
    // allocate() binds a cube on the ACTIVE unit: do it on unit 0, which the
    // saved state restores, so the caller's unit N keeps its binding.
    glActiveTexture(GL_TEXTURE0);
    // Raw capture: one allocated level (the backdrop's allocate), its chain
    // built by generate_mips() after each capture so the prefilter can pick a
    // raw level per sample from the sample's pdf.
    bool ok = raw_.allocate(kBridgeProbeFace) &&
              out_.allocate(kBridgeProbeFace, kBridgeProbeMips);
    if (ok && !prefilter_) {
        prefilter_ = std::make_unique<Shader>(shader_src::probe_prefilter_vs,
                                              shader_src::probe_prefilter_fs);
    }
    if (ok && !vao_) {
        GLuint vao = 0, vbo = 0;
        make_triangle(vao, vbo);
        vao_ = vao;
        vbo_ = vbo;
    }
    s.restore();
    return ok;
}

void BridgeProbe::begin_capture() {
    // The raw cube is about to be overwritten; until all six faces land it is
    // not a capture (a throwing draw leaves it partial). out_ keeps the last
    // good prefilter, so valid() is unchanged.
    raw_captured_ = false;
    saved_ = std::make_unique<SavedState>();
    saved_->gl.save();
    glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS);   // as the backdrop bake; left on
}

scenegraph::Camera BridgeProbe::begin_face(int i, glm::vec3 origin) {
    raw_.bind_face(i);
    return probe_gl::clear_face_and_camera(i, origin);
}

void BridgeProbe::finish_capture() {
    raw_captured_ = true;
    run_prefilter();
    captured_ = true;
}

void BridgeProbe::restore_capture_state() {
    if (saved_) saved_->gl.restore();
    saved_.reset();
}

void BridgeProbe::prefilter() {
    if (!raw_captured_ || !ensure()) return;
    GlState s;
    s.save();
    glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS);
    run_prefilter();
    captured_ = true;
    s.restore();
}

void BridgeProbe::run_prefilter() {
    // Raw chain for the pdf-driven sample level.
    glActiveTexture(GL_TEXTURE0);
    raw_.generate_mips();
    probe_gl::begin_prefilter(*prefilter_, raw_.texture(), vao_);
    for (int mip = 0; mip < kBridgeProbeMips; ++mip) {
        probe_gl::prefilter_mip(*prefilter_, mip,
                                [&](int face) { out_.bind_face(face, mip); });
    }
}

BrdfLut::~BrdfLut() {
    if (tex_) { GLuint t = tex_; glDeleteTextures(1, &t); }
}

bool BrdfLut::ensure() {
    if (tex_) return true;
    if (!have_context()) return false;

    GlState s;
    s.save();

    GLuint tex = 0;
    glGenTextures(1, &tex);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RG16F, kBridgeBrdfLutSize, kBridgeBrdfLutSize,
                 0, GL_RG, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint fbo = 0;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    const bool ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (ok) {
        Shader prog(shader_src::brdf_lut_vs, shader_src::brdf_lut_fs);
        GLuint vao = 0, vbo = 0;
        make_triangle(vao, vbo);
        full_screen_state();
        glViewport(0, 0, kBridgeBrdfLutSize, kBridgeBrdfLutSize);
        prog.use();
        prog.set_float("u_size", static_cast<float>(kBridgeBrdfLutSize));
        prog.set_int("u_samples", kBrdfLutSamples);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);
        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
        glUseProgram(0);   // before prog's destructor deletes it
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDeleteFramebuffers(1, &fbo);
    if (!ok) { glDeleteTextures(1, &tex); tex = 0; }
    s.restore();

    tex_ = tex;
    return tex_ != 0;
}

}  // namespace renderer
