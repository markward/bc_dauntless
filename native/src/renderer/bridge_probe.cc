// native/src/renderer/bridge_probe.cc
#include "renderer/bridge_probe.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/shader.h"

#include "embedded_probe_prefilter_vs.h"
#include "embedded_probe_prefilter_fs.h"
#include "embedded_brdf_lut_vs.h"
#include "embedded_brdf_lut_fs.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <cmath>

namespace renderer {

namespace {

constexpr int kPrefilterSamples = 256;
constexpr int kBrdfLutSamples = 512;
constexpr float kCaptureNear = 0.5f;
constexpr float kCaptureFar = 2000.0f;

// BackdropPass::bake's face table, verbatim (backdrop_pass.cc): canonical GL
// cubemap face orientations, camera at the origin, up vectors following the
// cube's left-handed face convention, so texture(cube, worldDir) returns the
// colour drawn looking along worldDir.
struct Face { glm::vec3 dir; glm::vec3 up; };
const Face kFaces[6] = {
    {{ 1,  0,  0}, {0, -1,  0}},  // +X
    {{-1,  0,  0}, {0, -1,  0}},  // -X
    {{ 0,  1,  0}, {0,  0,  1}},  // +Y
    {{ 0, -1,  0}, {0,  0, -1}},  // -Y
    {{ 0,  0,  1}, {0, -1,  0}},  // +Z
    {{ 0,  0, -1}, {0, -1,  0}},  // -Z
};

bool have_context() { return glfwGetCurrentContext() != nullptr; }

// One full-screen triangle at attribute 0 (vec2).
void make_triangle(GLuint& vao, GLuint& vbo) {
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
}

// The GL state the probe passes touch, captured and put back verbatim.
struct GlState {
    GLint fbo = 0, vp[4] = {0, 0, 0, 0};
    GLfloat clear[4] = {0, 0, 0, 0};
    GLfloat clear_depth = 1.0f;
    GLint program = 0, vao = 0, array_buffer = 0, active = GL_TEXTURE0;
    GLint cube0 = 0, tex2d0 = 0;
    GLboolean depth_test = GL_FALSE, blend = GL_FALSE, cull = GL_FALSE,
              scissor = GL_FALSE, depth_mask = GL_TRUE;

    void save() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, vp);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clear);
        glGetFloatv(GL_DEPTH_CLEAR_VALUE, &clear_depth);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex2d0);
        glActiveTexture(static_cast<GLenum>(active));
        depth_test = glIsEnabled(GL_DEPTH_TEST);
        blend = glIsEnabled(GL_BLEND);
        cull = glIsEnabled(GL_CULL_FACE);
        scissor = glIsEnabled(GL_SCISSOR_TEST);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
    }
    void restore() const {
        glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(fbo));
        glViewport(vp[0], vp[1], vp[2], vp[3]);
        glClearColor(clear[0], clear[1], clear[2], clear[3]);
        glClearDepth(clear_depth);
        glUseProgram(static_cast<GLuint>(program));
        glBindVertexArray(static_cast<GLuint>(vao));
        glBindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(array_buffer));
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_CUBE_MAP, static_cast<GLuint>(cube0));
        glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(tex2d0));
        glActiveTexture(static_cast<GLenum>(active));
        auto set = [](GLenum cap, GLboolean on) { if (on) glEnable(cap); else glDisable(cap); };
        set(GL_DEPTH_TEST, depth_test);
        set(GL_BLEND, blend);
        set(GL_CULL_FACE, cull);
        set(GL_SCISSOR_TEST, scissor);
        glDepthMask(depth_mask);
    }
};

// Full-screen passes: no depth, no blend, no cull, no scissor.
void full_screen_state() {
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glDepthMask(GL_FALSE);
}

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
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClearDepth(1.0);
    glDepthMask(GL_TRUE);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    scenegraph::Camera cam;
    cam.eye = origin;
    cam.target = origin + kFaces[i].dir;
    cam.up = kFaces[i].up;
    cam.fov_y_rad = glm::radians(90.0f);
    cam.aspect = 1.0f;
    cam.near = kCaptureNear;
    cam.far = kCaptureFar;
    return cam;
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

    full_screen_state();
    prefilter_->use();
    prefilter_->set_int("u_env", 0);   // unit local to this program
    prefilter_->set_float("u_env_size", static_cast<float>(kBridgeProbeFace));
    prefilter_->set_float("u_env_max_lod",
                          std::floor(std::log2(static_cast<float>(kBridgeProbeFace))));
    prefilter_->set_int("u_samples", kPrefilterSamples);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, raw_.texture());
    glBindVertexArray(vao_);

    for (int mip = 0; mip < kBridgeProbeMips; ++mip) {
        // Mip k is roughness k / (mips - 1); mip 0 is roughness 0 = a copy.
        const float rough = (kBridgeProbeMips > 1)
            ? static_cast<float>(mip) / static_cast<float>(kBridgeProbeMips - 1)
            : 0.0f;
        const int size = kBridgeProbeFace >> mip > 0 ? kBridgeProbeFace >> mip : 1;
        prefilter_->set_float("u_roughness", rough);
        prefilter_->set_float("u_face_size", static_cast<float>(size));
        for (int face = 0; face < 6; ++face) {
            out_.bind_face(face, mip);
            prefilter_->set_int("u_face", face);
            glDrawArrays(GL_TRIANGLES, 0, 3);
        }
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
