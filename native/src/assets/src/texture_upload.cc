#include <assets/texture.h>

#include "gl_handle.h"

#include <cstdio>
#include <string>

namespace assets {

namespace {

GLenum gl_format_internal(Image::Format f) {
    switch (f) {
        case Image::Format::RGBA8: return GL_RGBA8;
        case Image::Format::RGB8:  return GL_RGB8;
        case Image::Format::R8:    return GL_R8;
    }
    return GL_RGBA8;
}

GLenum gl_format(Image::Format f) {
    switch (f) {
        case Image::Format::RGBA8: return GL_RGBA;
        case Image::Format::RGB8:  return GL_RGB;
        case Image::Format::R8:    return GL_RED;
    }
    return GL_RGBA;
}

/// Drains the GL error queue; throws GlUploadError if any error was set.
void check_gl(const char* op) {
    GLenum err = glGetError();
    if (err == GL_NO_ERROR) return;
    while (glGetError() != GL_NO_ERROR) {}  // drain remainder
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%X", err);
    throw GlUploadError(
        std::string("GL error during ") + op + ": 0x" + buf, err);
}

}  // namespace

Texture upload_image(const Image& image, bool generate_mipmaps) {
    detail::TextureHandle handle;
    GLuint id = 0;
    glGenTextures(1, &id);
    handle = detail::TextureHandle(id);
    glBindTexture(GL_TEXTURE_2D, id);

    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(
        GL_TEXTURE_2D, /*level=*/0,
        gl_format_internal(image.format),
        static_cast<GLsizei>(image.width),
        static_cast<GLsizei>(image.height),
        /*border=*/0,
        gl_format(image.format),
        GL_UNSIGNED_BYTE,
        image.pixels.data());

    bool mipmaps = generate_mipmaps && image.width > 4 && image.height > 4;
    if (mipmaps) {
        glGenerateMipmap(GL_TEXTURE_2D);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    } else {
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    glBindTexture(GL_TEXTURE_2D, 0);

    check_gl("upload_image");
    return Texture(handle.release(), image.width, image.height, mipmaps);
}

}  // namespace assets
