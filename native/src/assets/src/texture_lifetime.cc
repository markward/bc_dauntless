#include <assets/texture.h>

#include <utility>

namespace assets {

Texture::Texture(GLuint id, std::uint32_t w, std::uint32_t h, bool mipmaps) noexcept
    : id_(id), width_(w), height_(h), mipmaps_(mipmaps) {}

Texture::Texture(Texture&& o) noexcept
    : id_(std::exchange(o.id_, 0))
    , width_(std::exchange(o.width_, 0))
    , height_(std::exchange(o.height_, 0))
    , mipmaps_(std::exchange(o.mipmaps_, false)) {}

Texture& Texture::operator=(Texture&& o) noexcept {
    if (this != &o) {
        if (id_) glDeleteTextures(1, &id_);
        id_      = std::exchange(o.id_, 0);
        width_   = std::exchange(o.width_, 0);
        height_  = std::exchange(o.height_, 0);
        mipmaps_ = std::exchange(o.mipmaps_, false);
    }
    return *this;
}

Texture::~Texture() {
    if (id_) glDeleteTextures(1, &id_);
}

}  // namespace assets
