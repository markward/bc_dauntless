// native/src/assets/include/assets/texture.h
#pragma once

#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

#include <glad/glad.h>

namespace assets {

struct Image {
    enum class Format { RGBA8, RGB8, R8 };
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    Format format = Format::RGBA8;
    std::vector<std::uint8_t> pixels;
};

class Texture {
public:
    Texture() = default;
    Texture(GLuint id, std::uint32_t w, std::uint32_t h, bool mipmaps) noexcept;
    Texture(Texture&&) noexcept;
    Texture& operator=(Texture&&) noexcept;
    Texture(const Texture&) = delete;
    Texture& operator=(const Texture&) = delete;
    ~Texture();

    GLuint id() const noexcept { return id_; }
    std::uint32_t width() const noexcept { return width_; }
    std::uint32_t height() const noexcept { return height_; }
    bool has_mipmaps() const noexcept { return mipmaps_; }

private:
    GLuint id_ = 0;
    std::uint32_t width_ = 0;
    std::uint32_t height_ = 0;
    bool mipmaps_ = false;
};

class TextureDecodeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class UnsupportedTga : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Thrown when a GL upload (glTexImage2D / glBufferData / etc.) leaves
/// glGetError() in a non-NO_ERROR state. Carries the raw GLenum from the
/// last error fetch.
class GlUploadError : public std::runtime_error {
public:
    GlUploadError(std::string what, GLenum gl_error)
        : std::runtime_error(std::move(what)), gl_error_(gl_error) {}
    GLenum gl_error() const noexcept { return gl_error_; }
private:
    GLenum gl_error_;
};

// Public utilities; the renderer can use these for its own internal assets
// (lens-dirt textures, color-grading LUTs) without going through AssetCache.
Image decode_tga(std::span<const std::uint8_t> bytes);
Texture upload_image(const Image& image, bool generate_mipmaps = true);

}  // namespace assets

namespace nif { struct NiRawImageData; }

namespace assets {
Image decode_raw_image(const nif::NiRawImageData& raw);
}
