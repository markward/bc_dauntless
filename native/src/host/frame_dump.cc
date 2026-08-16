// native/src/host/frame_dump.cc
//
// PNG dump of the default framebuffer, for developer diagnostics.

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image_write.h>

#include "frame_dump.h"

#include <glad/glad.h>

#include <vector>

namespace dauntless {

bool dump_default_framebuffer_png(const std::string& path, int w, int h) {
    if (w < 1 || h < 1) return false;

    std::vector<unsigned char> pixels(static_cast<std::size_t>(w) * h * 3);

    // Bind FBO 0 explicitly: callers run this at end-of-frame, but a stray
    // bound FBO would silently dump the wrong surface.
    GLint prev_fbo = 0;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &prev_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glReadBuffer(GL_BACK);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));

    // GL's origin is bottom-left, PNG's is top-left.
    stbi_flip_vertically_on_write(1);
    const int ok = stbi_write_png(path.c_str(), w, h, 3, pixels.data(), w * 3);
    stbi_flip_vertically_on_write(0);
    return ok != 0;
}

}  // namespace dauntless
