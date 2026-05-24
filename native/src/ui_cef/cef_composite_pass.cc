// native/src/ui_cef/cef_composite_pass.cc
#include "cef_composite_pass.h"

#include <glad/glad.h>

#include <cstdio>
#include <cstdlib>

namespace dauntless::ui_cef {

namespace {

const char* kVS = R"(
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    v_uv.y = 1.0 - v_uv.y;  // GL bottom-up; CEF bitmap top-down
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
)";

const char* kFS = R"(
#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_tex;
void main() { frag_color = texture(u_tex, v_uv); }
)";

unsigned int compile(unsigned int type, const char* src) {
    unsigned int sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetShaderInfoLog(sh, sizeof(log), nullptr, log);
        std::fprintf(stderr, "ui_cef shader compile failed: %s\n", log);
        std::exit(1);
    }
    return sh;
}

unsigned int link(unsigned int vs, unsigned int fs) {
    unsigned int p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    int ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetProgramInfoLog(p, sizeof(log), nullptr, log);
        std::fprintf(stderr, "ui_cef program link failed: %s\n", log);
        std::exit(1);
    }
    return p;
}

}  // namespace

CefCompositePass::CefCompositePass() {
    unsigned int vs = compile(GL_VERTEX_SHADER,   kVS);
    unsigned int fs = compile(GL_FRAGMENT_SHADER, kFS);
    program_id_ = link(vs, fs);
    glDeleteShader(vs); glDeleteShader(fs);

    // Fullscreen-triangle trick: one triangle covering [-1,3]² clipspace.
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);

    glGenTextures(1, &tex_id_);
    glBindTexture(GL_TEXTURE_2D, tex_id_);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
}

CefCompositePass::~CefCompositePass() {
    if (tex_id_)     glDeleteTextures(1, &tex_id_);
    if (vbo_)        glDeleteBuffers(1,  &vbo_);
    if (vao_)        glDeleteVertexArrays(1, &vao_);
    if (program_id_) glDeleteProgram(program_id_);
}

void CefCompositePass::draw_fullscreen(const std::uint8_t* pixels,
                                       int width, int height) {
    if (!pixels) return;

    glBindTexture(GL_TEXTURE_2D, tex_id_);

    // CEF delivers tight rows; GL's default UNPACK_ALIGNMENT is 4 bytes.
    // Force tight unpack so odd widths never misalign.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

    if (width != last_width_ || height != last_height_) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                     GL_BGRA, GL_UNSIGNED_BYTE, pixels);
        last_width_ = width;
        last_height_ = height;
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height,
                        GL_BGRA, GL_UNSIGNED_BYTE, pixels);
    }

    glUseProgram(program_id_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex_id_);
    glUniform1i(glGetUniformLocation(program_id_, "u_tex"), 0);

    // Save state we are about to clobber so the next frame's 3D passes
    // see the same GL config they had before the composite ran.
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_scissor    = glIsEnabled(GL_SCISSOR_TEST);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);
    GLint prev_blend_src = 0, prev_blend_dst = 0;
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &prev_blend_src);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &prev_blend_dst);

    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glEnable(GL_BLEND);
    // CEF delivers PREMULTIPLIED-alpha BGRA. The correct blend is
    // (ONE, ONE_MINUS_SRC_ALPHA). Using straight alpha would
    // double-attenuate by alpha and leave the overlay invisible.
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    // Restore everything.
    glDepthMask(GL_TRUE);
    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_scissor)    glEnable(GL_SCISSOR_TEST);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (!prev_blend)     glDisable(GL_BLEND);
    glBlendFunc(static_cast<GLenum>(prev_blend_src),
                static_cast<GLenum>(prev_blend_dst));
}

}  // namespace dauntless::ui_cef
