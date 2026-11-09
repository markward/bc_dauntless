// native/src/renderer/include/renderer/hdr_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// Colour format of an HDR target, chosen per instance.
///  - Rgba16f: signed half floats with alpha. The default: bridge AO keeps
///    signed normals in an HdrTarget, and the dev nonfinite probe reads a cause
///    code from alpha and needs negatives / -Inf.
///  - R11g11b10f: GL_R11F_G11F_B10F, half the bandwidth. NO alpha (reads 1)
///    and UNSIGNED (negatives and -Inf clamp to 0); NaN and +Inf survive. For
///    targets nothing reads alpha or a negative from: the main scene and its
///    MSAA twin (probe off), the viewscreen, DOF and the bloom chain.
enum class HdrColorFormat { Rgba16f, R11g11b10f };

/// One offscreen HDR color (RGBA16F by default, see set_color_format) + depth
/// target. The whole 3D scene renders here; the resolve pass reads
/// color_texture() back to the backbuffer. First FBO in the renderer.
class HdrTarget {
public:
    HdrTarget() = default;
    ~HdrTarget();
    HdrTarget(const HdrTarget&) = delete;
    HdrTarget& operator=(const HdrTarget&) = delete;

    /// (Re)allocate to w x h. No-op if already that size and color_format()
    /// has not changed since the last allocation. Must be called
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

    /// Colour format of the NEXT allocation. A change invalidates the size key,
    /// so the next resize() reallocates even at the same size; setting the
    /// current format keeps the allocation. Default Rgba16f.
    void set_color_format(HdrColorFormat f) { format_ = f; }
    HdrColorFormat color_format() const { return format_; }

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
    HdrColorFormat format_ = HdrColorFormat::Rgba16f;
    HdrColorFormat allocated_format_ = HdrColorFormat::Rgba16f;
};

}  // namespace renderer
