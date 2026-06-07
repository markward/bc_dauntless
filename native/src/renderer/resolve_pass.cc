// native/src/renderer/resolve_pass.cc
//
// Fullscreen-triangle resolve pass: samples the HDR RGBA16F color texture
// and writes to the currently-bound framebuffer. This task: passthrough only
// (clamp(color,0,1)); tonemapping is wired in a later task.

#include <renderer/resolve_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_resolve_fs.h"

#include <cstdio>
#include <cstdlib>

namespace renderer {

namespace {

unsigned int compile_shader(unsigned int type, const char* src) {
    unsigned int sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetShaderInfoLog(sh, sizeof(log), nullptr, log);
        std::fprintf(stderr, "resolve_pass shader compile failed: %s\n", log);
        std::exit(1);
    }
    return sh;
}

unsigned int link_program(unsigned int vs, unsigned int fs) {
    unsigned int p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    int ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetProgramInfoLog(p, sizeof(log), nullptr, log);
        std::fprintf(stderr, "resolve_pass program link failed: %s\n", log);
        std::exit(1);
    }
    return p;
}

}  // namespace

ResolvePass::ResolvePass() {
    unsigned int vs = compile_shader(GL_VERTEX_SHADER,   shader_src::resolve_vs);
    unsigned int fs = compile_shader(GL_FRAGMENT_SHADER, shader_src::resolve_fs);
    program_ = link_program(vs, fs);
    glDeleteShader(vs);
    glDeleteShader(fs);

    u_hdr_loc_         = glGetUniformLocation(program_, "u_hdr");
    u_hdr_enabled_loc_ = glGetUniformLocation(program_, "u_hdr_enabled");

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
    if (vbo_)     glDeleteBuffers(1,       &vbo_);
    if (vao_)     glDeleteVertexArrays(1,  &vao_);
    if (program_) glDeleteProgram(program_);
}

void ResolvePass::draw(std::uint32_t hdr_color_tex) {
    // Save GL state we clobber so 3D passes on the next frame see unchanged config.
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    glUseProgram(program_);
    glUniform1i(u_hdr_enabled_loc_, hdr_enabled_ ? 1 : 0);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_color_tex);
    glUniform1i(u_hdr_loc_, 0);

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
