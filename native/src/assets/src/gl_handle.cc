#include "gl_handle.h"

namespace assets::detail {

void TextureHandle::reset() noexcept {
    if (id_) { glDeleteTextures(1, &id_); id_ = 0; }
}

void BufferHandle::reset() noexcept {
    if (id_) { glDeleteBuffers(1, &id_); id_ = 0; }
}

void VertexArrayHandle::reset() noexcept {
    if (id_) { glDeleteVertexArrays(1, &id_); id_ = 0; }
}

}  // namespace assets::detail
