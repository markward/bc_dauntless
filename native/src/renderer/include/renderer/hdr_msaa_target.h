// native/src/renderer/include/renderer/hdr_msaa_target.h
#pragma once
#include <cstdint>
#include "renderer/hdr_target.h"

namespace renderer {

/// A multisample HDR colour (RGBA16F by default, see set_color_format) + depth
/// target for the opaque space pass.
///
/// Both attachments are RENDERBUFFERS, not textures, and that is deliberate:
/// nothing ever samples these surfaces. The only way data leaves this target
/// is resolve_to(), a glBlitFramebuffer into a single-sample HdrTarget. Using
/// renderbuffers keeps sampler2DMS and per-sample fetch out of the codebase
/// entirely.
///
/// Allocation is lazy at the call site: resize() is only called when MSAA is
/// actually enabled, so an Off/SMAA session never creates GL objects here.
class HdrMsaaTarget {
public:
    HdrMsaaTarget() = default;
    ~HdrMsaaTarget();
    HdrMsaaTarget(const HdrMsaaTarget&) = delete;
    HdrMsaaTarget& operator=(const HdrMsaaTarget&) = delete;

    /// (Re)allocate to w x h at `samples`. No-op if already those exact
    /// parameters. `samples` < 2 destroys any existing buffers and leaves the
    /// target invalid(). A color_format() change since the last allocation
    /// also reallocates. Requires a current GL context.
    ///
    /// If the driver refuses the combination (framebuffer incomplete), the
    /// target is destroyed and left invalid() rather than half-built — the
    /// caller checks valid() and falls back to the non-MSAA path. We do not
    /// trust RGBA16F or R11F_G11F_B10F multisample support on the strength of
    /// the spec alone.
    void resize(int w, int h, int samples);

    /// Make this the draw framebuffer and set the viewport to its size.
    /// CALLER CONTRACT: matches HdrTarget::bind() — the caller must restore
    /// the intended framebuffer and viewport afterwards.
    void bind() const;

    /// Resolve colour AND depth into `dst` with a single glBlitFramebuffer.
    ///
    /// GL_NEAREST is mandatory, not a choice: a blit that includes
    /// GL_DEPTH_BUFFER_BIT rejects GL_LINEAR. `dst` must be exactly the same
    /// dimensions — a multisample blit cannot rescale.
    ///
    /// Restores no state; the caller binds what it needs next.
    /// No-op if !valid() or the sizes disagree.
    void resolve_to(const HdrTarget& dst) const;

    /// Colour format of the NEXT allocation; same contract as
    /// HdrTarget::set_color_format. resolve_to() is a same-format blit, so the
    /// caller keeps this equal to the destination HdrTarget's format.
    void set_color_format(HdrColorFormat f) { format_ = f; }
    HdrColorFormat color_format() const { return format_; }

    bool valid() const { return fbo_ != 0; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }
    int samples() const { return samples_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_rb_ = 0;
    std::uint32_t depth_rb_ = 0;
    int width_ = 0;
    int height_ = 0;
    int samples_ = 0;
    HdrColorFormat format_ = HdrColorFormat::Rgba16f;
    HdrColorFormat allocated_format_ = HdrColorFormat::Rgba16f;
};

}  // namespace renderer
