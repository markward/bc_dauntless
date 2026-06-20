#include "renderer/shadow_map_target.h"
#include <glad/glad.h>

namespace renderer {

ShadowMapTarget::~ShadowMapTarget() { destroy(); }

void ShadowMapTarget::destroy() {
    if (depth_tex_) { glDeleteTextures(1, &depth_tex_); depth_tex_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_);    fbo_ = 0; }
    width_ = height_ = 0;
}

void ShadowMapTarget::resize(int w, int h) {
    if (w == width_ && h == height_ && fbo_ != 0) return;
    destroy();
    width_ = w; height_ = h;

    glGenTextures(1, &depth_tex_);
    glBindTexture(GL_TEXTURE_2D, depth_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                 GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
    const float border[4] = {1.0f, 1.0f, 1.0f, 1.0f};  // outside box = lit
    glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, border);
    // Hardware PCF: sampler2DShadow compares ref <= stored depth.
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth_tex_, 0);
    glDrawBuffer(GL_NONE);
    glReadBuffer(GL_NONE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void ShadowMapTarget::bind() const {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

}  // namespace renderer
