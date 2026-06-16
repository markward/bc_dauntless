// native/src/renderer/include/renderer/gl_caps.h
#pragma once

namespace renderer {

/// Snapshot of GL capabilities relevant to the hull-deformation pipeline.
/// Must be queried with a current GL context (see query_gl_caps()).
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
};

/// Query the current GL context. Requires a current context (call after
/// renderer::Window construction / glfwMakeContextCurrent).
GlCaps query_gl_caps();

}  // namespace renderer
