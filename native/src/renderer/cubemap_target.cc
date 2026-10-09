// native/src/renderer/cubemap_target.cc
#include "renderer/cubemap_target.h"
#include <glad/glad.h>

#include <algorithm>

namespace renderer {

CubemapTarget::~CubemapTarget() { destroy(); }

void CubemapTarget::destroy() {
    if (cube_tex_)  { glDeleteTextures(1, &cube_tex_); cube_tex_ = 0; }
    if (depth_rbo_) { glDeleteRenderbuffers(1, &depth_rbo_); depth_rbo_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
    mip_levels_ = 0;
}

bool CubemapTarget::allocate(int face_size, int mip_levels) {
    if (face_size < 1) face_size = 1;
    if (mip_levels < 1) mip_levels = 1;
    if (face_size == face_size_ && mip_levels == mip_levels_ && fbo_ != 0) return true;
    destroy();
    face_size_ = face_size;
    mip_levels_ = mip_levels;

    glGenTextures(1, &cube_tex_);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube_tex_);
    for (int level = 0; level < mip_levels; ++level) {
        const int sz = std::max(1, face_size >> level);
        for (int i = 0; i < 6; ++i) {
            glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, level, GL_RGBA16F,
                         sz, sz, 0, GL_RGBA, GL_FLOAT, nullptr);
        }
    }
    if (mip_levels > 1) {
        // Only for an explicit chain: a single-level target keeps GL's default
        // MAX_LEVEL so generate_mips() can still build a full chain (backdrop).
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_BASE_LEVEL, 0);
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAX_LEVEL, mip_levels - 1);
    }
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);

    glGenRenderbuffers(1, &depth_rbo_);
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rbo_);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, face_size, face_size);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                              GL_RENDERBUFFER, depth_rbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_CUBE_MAP_POSITIVE_X, cube_tex_, 0);
    const bool ok =
        glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (!ok) destroy();
    return ok;
}

void CubemapTarget::bind_face(int i, int mip) const {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, cube_tex_, mip);
    const int sz = std::max(1, face_size_ >> mip);
    glViewport(0, 0, sz, sz);
}

void CubemapTarget::generate_mips() const {
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube_tex_);
    glGenerateMipmap(GL_TEXTURE_CUBE_MAP);
}

}  // namespace renderer
