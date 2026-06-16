// native/src/renderer/gl_caps.cc
#include "renderer/gl_caps.h"

#include <glad/glad.h>

namespace renderer {

GlCaps query_gl_caps() {
    GlCaps caps;
    glGetIntegerv(GL_MAJOR_VERSION, &caps.version_major);
    glGetIntegerv(GL_MINOR_VERSION, &caps.version_minor);
    // Tessellation control/evaluation shaders are core since GL 4.0.
    caps.tessellation_available =
        (caps.version_major > 4) ||
        (caps.version_major == 4 && caps.version_minor >= 0);
    return caps;
}

}  // namespace renderer
