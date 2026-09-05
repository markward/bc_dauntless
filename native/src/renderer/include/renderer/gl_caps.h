#pragma once
namespace renderer {
/// Snapshot of GL capabilities. Query with a current GL context.
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
    /// GL_MAX_SAMPLES — the ceiling on multisample renderbuffer sample counts.
    /// GL 3.3 guarantees >= 4. Queried, not assumed: we clamp the UI to it.
    int  max_samples = 0;
};
GlCaps query_gl_caps();  // requires a current GL context

/// Clamp a requested MSAA sample count to something this driver will give us.
/// 0 (and anything nonsensical) means "MSAA off" and is passed through as 0,
/// because 0 is the signal the frame path uses to skip the whole MSAA branch.
int clamp_msaa_samples(int requested, const GlCaps& caps);
}  // namespace renderer
