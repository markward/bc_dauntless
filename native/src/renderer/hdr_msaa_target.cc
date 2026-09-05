// native/src/renderer/hdr_msaa_target.cc
#include "renderer/hdr_msaa_target.h"
#include "renderer/hdr_target.h"
#include <glad/glad.h>

namespace renderer {

HdrMsaaTarget::~HdrMsaaTarget() { destroy(); }

void HdrMsaaTarget::destroy() {
    if (color_rb_) { glDeleteRenderbuffers(1, &color_rb_); color_rb_ = 0; }
    if (depth_rb_) { glDeleteRenderbuffers(1, &depth_rb_); depth_rb_ = 0; }
    if (fbo_)      { glDeleteFramebuffers(1, &fbo_);       fbo_ = 0; }
    width_ = height_ = samples_ = 0;
}

void HdrMsaaTarget::resize(int w, int h, int samples) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (samples < 2) { destroy(); return; }
    if (w == width_ && h == height_ && samples == samples_ && fbo_ != 0) return;
    destroy();

    glGenRenderbuffers(1, &color_rb_);
    glBindRenderbuffer(GL_RENDERBUFFER, color_rb_);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples, GL_RGBA16F, w, h);

    glGenRenderbuffers(1, &depth_rb_);
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rb_);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples,
                                     GL_DEPTH_COMPONENT24, w, h);
    glBindRenderbuffer(GL_RENDERBUFFER, 0);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, color_rb_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                              GL_RENDERBUFFER, depth_rb_);

    const GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        // Driver refused this combination. Leave nothing half-built: the
        // caller's valid() check routes the frame down the non-MSAA path.
        destroy();
        return;
    }

    width_ = w; height_ = h; samples_ = samples;
}

void HdrMsaaTarget::bind() const {
    if (fbo_ == 0) return;
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

void HdrMsaaTarget::resolve_to(const HdrTarget& dst) const {
    if (fbo_ == 0) return;
    if (dst.width() != width_ || dst.height() != height_) return;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo_);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst.fbo());
    // GL_NEAREST is required whenever the blit includes depth. Src and dst
    // rects are identical because a multisample blit cannot rescale.
    glBlitFramebuffer(0, 0, width_, height_,
                      0, 0, width_, height_,
                      GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT,
                      GL_NEAREST);
}

}  // namespace renderer
