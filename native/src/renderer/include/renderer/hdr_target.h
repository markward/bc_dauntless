// native/src/renderer/include/renderer/hdr_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One offscreen RGBA16F color + depth target. The whole 3D scene renders
/// here; the resolve pass reads color_texture() back to the backbuffer.
/// First FBO in the renderer.
class HdrTarget {
public:
    HdrTarget() = default;
    ~HdrTarget();
    HdrTarget(const HdrTarget&) = delete;
    HdrTarget& operator=(const HdrTarget&) = delete;

    /// (Re)allocate to w x h. No-op if already that size. Must be called
    /// with a current GL context before bind().
    void resize(int w, int h);

    /// Make this the draw framebuffer and set the viewport to its size.
    /// CALLER CONTRACT: after rendering into this target, the caller must
    /// restore the default framebuffer (glBindFramebuffer(GL_FRAMEBUFFER, 0))
    /// AND reset the viewport to the window size before any backbuffer-
    /// targeted draw (e.g. the resolve pass or CEF composite), or that draw
    /// will be confined to this target's sub-rect. Must be called after
    /// resize() — binding before the first resize() is a programming error.
    void bind() const;

    std::uint32_t color_texture() const { return color_tex_; }
    std::uint32_t depth_texture() const { return depth_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_tex_ = 0;
    std::uint32_t depth_tex_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
