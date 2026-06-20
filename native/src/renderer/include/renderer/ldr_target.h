// native/src/renderer/include/renderer/ldr_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One offscreen RGBA8 color target (no depth). The resolve pass renders the
/// tonemapped LDR image here; SmaaPass then samples color_texture() back to
/// the backbuffer. Mirrors HdrTarget's resize/bind contract but without a
/// depth renderbuffer.
class LdrTarget {
public:
    LdrTarget() = default;
    ~LdrTarget();
    LdrTarget(const LdrTarget&) = delete;
    LdrTarget& operator=(const LdrTarget&) = delete;

    /// (Re)allocate to w x h. No-op if already that size. Must be called with
    /// a current GL context before bind().
    void resize(int w, int h);

    /// Make this the draw framebuffer and set the viewport to its size. The
    /// caller must restore the default framebuffer + window viewport before any
    /// backbuffer-targeted draw afterwards. Must be called after resize().
    void bind() const;

    std::uint32_t color_texture() const { return color_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_tex_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
