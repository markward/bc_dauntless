// native/src/renderer/include/renderer/hdr_msaa_target.h
#pragma once
#include <cstdint>

namespace renderer {

class HdrTarget;

/// A multisample RGBA16F colour + depth target for the opaque space pass.
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
    /// target invalid(). Requires a current GL context.
    ///
    /// If the driver refuses the combination (framebuffer incomplete), the
    /// target is destroyed and left invalid() rather than half-built — the
    /// caller checks valid() and falls back to the non-MSAA path. We do not
    /// trust GL_RGBA16F multisample support on the strength of the spec alone.
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
};

}  // namespace renderer
