#pragma once
namespace renderer {
/// Snapshot of GL capabilities. Query with a current GL context.
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
};
GlCaps query_gl_caps();  // requires a current GL context
}  // namespace renderer
