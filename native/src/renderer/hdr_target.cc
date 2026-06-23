// native/src/renderer/hdr_target.cc
#include "renderer/hdr_target.h"
#include <cassert>
#include <glad/glad.h>

namespace renderer {

HdrTarget::~HdrTarget() { destroy(); }

void HdrTarget::destroy() {
    if (color_tex_) { glDeleteTextures(1, &color_tex_); color_tex_ = 0; }
    if (depth_tex_) { glDeleteTextures(1, &depth_tex_); depth_tex_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
}

void HdrTarget::resize(int w, int h) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (w == width_ && h == height_ && fbo_ != 0) return;
    destroy();
    width_ = w; height_ = h;

    glGenTextures(1, &color_tex_);
    glBindTexture(GL_TEXTURE_2D, color_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenTextures(1, &depth_tex_);
    glBindTexture(GL_TEXTURE_2D, depth_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                 GL_DEPTH_COMPONENT, GL_UNSIGNED_INT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, color_tex_, 0);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                           GL_TEXTURE_2D, depth_tex_, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void HdrTarget::bind() const {
    assert(fbo_ != 0 && "HdrTarget::bind() before resize()");
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

}  // namespace renderer
