// native/src/assets/src/gl_handle.h
//
// RAII wrappers for transient GL handle ownership during upload routines.
// The Texture / Mesh classes own their final GL handles; these helpers
// guarantee that a glGen* call followed by a throwing glTexImage2D /
// glBufferData doesn't leak the freshly-allocated GL object.
#pragma once

#include <glad/glad.h>

#include <utility>

namespace assets::detail {

class TextureHandle {
public:
    TextureHandle() = default;
    explicit TextureHandle(GLuint id) noexcept : id_(id) {}
    TextureHandle(TextureHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    TextureHandle& operator=(TextureHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~TextureHandle() { reset(); }
    TextureHandle(const TextureHandle&) = delete;
    TextureHandle& operator=(const TextureHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

class BufferHandle {
public:
    BufferHandle() = default;
    explicit BufferHandle(GLuint id) noexcept : id_(id) {}
    BufferHandle(BufferHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    BufferHandle& operator=(BufferHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~BufferHandle() { reset(); }
    BufferHandle(const BufferHandle&) = delete;
    BufferHandle& operator=(const BufferHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

class VertexArrayHandle {
public:
    VertexArrayHandle() = default;
    explicit VertexArrayHandle(GLuint id) noexcept : id_(id) {}
    VertexArrayHandle(VertexArrayHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    VertexArrayHandle& operator=(VertexArrayHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~VertexArrayHandle() { reset(); }
    VertexArrayHandle(const VertexArrayHandle&) = delete;
    VertexArrayHandle& operator=(const VertexArrayHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

}  // namespace assets::detail
