// native/src/renderer/probe_capture_gl.h
//
// Internal to the renderer: the GL pieces both bridge reflection-probe owners
// share -- BridgeProbe (one cube, one-shot capture) and BridgeProbeArray (a
// cube-map array, stepped capture). The capture face table and camera, the
// saved/restored GL state, the full-screen triangle and the GGX prefilter's
// per-mip uniforms live here once so the two can never drift apart.
#pragma once

#include "renderer/bridge_lighting_tuning.h"
#include "renderer/shader.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>

namespace renderer::probe_gl {

inline constexpr int kPrefilterSamples = 256;
inline constexpr float kCaptureNear = 0.5f;
inline constexpr float kCaptureFar = 2000.0f;

// BackdropPass::bake's face table, verbatim (backdrop_pass.cc): canonical GL
// cubemap face orientations, camera at the origin, up vectors following the
// cube's left-handed face convention, so texture(cube, worldDir) returns the
// colour drawn looking along worldDir.
struct Face { glm::vec3 dir; glm::vec3 up; };
inline const Face kFaces[6] = {
    {{ 1,  0,  0}, {0, -1,  0}},  // +X
    {{-1,  0,  0}, {0, -1,  0}},  // -X
    {{ 0,  1,  0}, {0,  0,  1}},  // +Y
    {{ 0, -1,  0}, {0,  0, -1}},  // -Y
    {{ 0,  0,  1}, {0, -1,  0}},  // +Z
    {{ 0,  0, -1}, {0, -1,  0}},  // -Z
};

inline bool have_context() { return glfwGetCurrentContext() != nullptr; }

/// Size of a probe face at `mip` (never below 1).
inline int mip_size(int mip) { return std::max(1, kBridgeProbeFace >> mip); }

// One full-screen triangle at attribute 0 (vec2).
inline void make_triangle(GLuint& vao, GLuint& vbo) {
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
    GLint draw_fbo = 0, read_fbo = 0, vp[4] = {0, 0, 0, 0};
    GLfloat clear[4] = {0, 0, 0, 0};
    GLfloat clear_depth = 1.0f;
    GLint program = 0, vao = 0, array_buffer = 0, active = GL_TEXTURE0;
    GLint cube0 = 0, cube_array0 = 0, tex2d0 = 0;
    GLboolean depth_test = GL_FALSE, blend = GL_FALSE, cull = GL_FALSE,
              scissor = GL_FALSE, depth_mask = GL_TRUE;

    void save() {
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw_fbo);
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &read_fbo);
        glGetIntegerv(GL_VIEWPORT, vp);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clear);
        glGetFloatv(GL_DEPTH_CLEAR_VALUE, &clear_depth);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube0);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP_ARRAY, &cube_array0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex2d0);
        glActiveTexture(static_cast<GLenum>(active));
        depth_test = glIsEnabled(GL_DEPTH_TEST);
        blend = glIsEnabled(GL_BLEND);
        cull = glIsEnabled(GL_CULL_FACE);
        scissor = glIsEnabled(GL_SCISSOR_TEST);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
    }
    void restore() const {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(draw_fbo));
        glBindFramebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(read_fbo));
        glViewport(vp[0], vp[1], vp[2], vp[3]);
        glClearColor(clear[0], clear[1], clear[2], clear[3]);
        glClearDepth(clear_depth);
        glUseProgram(static_cast<GLuint>(program));
        glBindVertexArray(static_cast<GLuint>(vao));
        glBindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(array_buffer));
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_CUBE_MAP, static_cast<GLuint>(cube0));
        glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, static_cast<GLuint>(cube_array0));
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
inline void full_screen_state() {
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glDepthMask(GL_FALSE);
}

/// With a capture face already bound (viewport = face²): clear it to opaque
/// black and clear depth, then return the 90° square camera at `origin`
/// looking down face `i`, for the caller's draw_face.
inline scenegraph::Camera clear_face_and_camera(int i, glm::vec3 origin) {
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

/// Ready the prefilter program to read the raw capture cube `raw` (its mip
/// chain already generated -- the pdf-driven sample level reads it) with the
/// full-screen triangle `vao`. Leaves unit 0 active with `raw` bound.
inline void begin_prefilter(const Shader& prog, GLuint raw, GLuint vao) {
    full_screen_state();
    prog.use();
    prog.set_int("u_env", 0);   // unit local to this program
    prog.set_float("u_env_size", static_cast<float>(kBridgeProbeFace));
    prog.set_float("u_env_max_lod",
                   std::floor(std::log2(static_cast<float>(kBridgeProbeFace))));
    prog.set_int("u_samples", kPrefilterSamples);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, raw);
    glBindVertexArray(vao);
}

/// Prefilter ONE face of output mip `mip` (after begin_prefilter):
/// `bind_face(face)` binds that face of that mip as the target and sets the
/// viewport to its size. Mip k is roughness k / (mips - 1); mip 0 is
/// roughness 0 = a copy.
template <class BindFace>
void prefilter_face(const Shader& prog, int mip, int face, BindFace bind_face) {
    const float rough = (kBridgeProbeMips > 1)
        ? static_cast<float>(mip) / static_cast<float>(kBridgeProbeMips - 1)
        : 0.0f;
    prog.set_float("u_roughness", rough);
    prog.set_float("u_face_size", static_cast<float>(mip_size(mip)));
    bind_face(face);
    prog.set_int("u_face", face);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}

/// Prefilter all six faces of output mip `mip` (prefilter_face per face).
template <class BindFace>
void prefilter_mip(const Shader& prog, int mip, BindFace bind_face) {
    for (int face = 0; face < 6; ++face) prefilter_face(prog, mip, face, bind_face);
}

}  // namespace renderer::probe_gl
