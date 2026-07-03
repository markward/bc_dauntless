// native/src/renderer/include/renderer/debug_volume_pass.h
#pragma once

#include <glm/glm.hpp>

#include <memory>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Shader;

/// One wireframe cylinder to draw, expressed in WORLD space.
struct DebugCylinder {
    glm::vec3 center{0.0f};             // base-cap centre
    glm::vec3 axis{0.0f, 1.0f, 0.0f};   // unit direction the tube extends along
    float     radius = 1.0f;
    float     length = 1.0f;            // extent along axis from `center`
    glm::vec3 color{0.0f, 1.0f, 0.0f};  // wireframe colour (default bright green)
};

/// Developer debug overlay: draws bright wireframe cylinders in world space.
/// Self-contained (owns its shader + a unit-cylinder mesh) and generic — the
/// caller supplies the cylinders, so it is not tied to any subsystem. Depth
/// test is OFF, so the cages are always visible over the scene.
///
/// This is a reusable diagnostic tool, not wired into the frame by default.
/// See docs/architecture/debug-volume-overlay.md for how to build cylinders
/// (e.g. from per-instance GlowRegion data) and how to wire it into
/// host_bindings.cc's frame draw in a handful of lines.
class DebugVolumePass {
public:
    DebugVolumePass();
    ~DebugVolumePass();

    DebugVolumePass(const DebugVolumePass&)            = delete;
    DebugVolumePass& operator=(const DebugVolumePass&) = delete;

    void render(const std::vector<DebugCylinder>& cylinders,
                const scenegraph::Camera& camera);

private:
    void ensure_resources();

    unsigned int vao_ = 0;
    unsigned int vbo_ = 0;
    int vertex_count_ = 0;
    std::unique_ptr<Shader> shader_;
};

}  // namespace renderer
