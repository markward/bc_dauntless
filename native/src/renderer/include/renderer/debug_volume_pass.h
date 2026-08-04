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

/// One wireframe box to draw, expressed in WORLD space. ex/ey/ez are the box's
/// three half-extent edge vectors (already rotated), so the drawn box is
/// center +/- ex +/- ey +/- ez.
struct DebugBox {
    glm::vec3 center{0.0f};
    glm::vec3 ex{1.0f, 0.0f, 0.0f};
    glm::vec3 ey{0.0f, 1.0f, 0.0f};
    glm::vec3 ez{0.0f, 0.0f, 1.0f};
    glm::vec3 color{0.0f, 1.0f, 0.0f};
};

/// One wireframe sphere to draw, expressed in WORLD space (uniform radius).
struct DebugSphere {
    glm::vec3 center{0.0f};
    float     radius = 1.0f;
    glm::vec3 color{0.0f, 1.0f, 0.0f};
};

/// One wireframe cone to draw, expressed in WORLD space. apex is the tip,
/// axis points from apex toward the base (unit), radius is the base radius
/// (along `right = axis x up`), radius_y is the base radius along `up`
/// (defaults to radius for a circular cone), length is the apex->base
/// distance. `up` orients the ellipse; degenerate/parallel-to-axis falls
/// back to the Gram-Schmidt world-up construction.
struct DebugCone {
    glm::vec3 apex{0.0f};
    glm::vec3 axis{0.0f, -1.0f, 0.0f};   // unit, apex -> base
    float     radius = 1.0f;             // base radius (along `right`)
    float     length = 1.0f;             // apex -> base distance
    glm::vec3 color{1.0f, 0.55f, 0.1f};
    float     radius_y = 1.0f;           // base radius along `up`
    glm::vec3 up{0.0f, 1.0f, 0.0f};      // authored up axis, orients the ellipse
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

    void render(const std::vector<DebugBox>& boxes,
                const scenegraph::Camera& camera);

    void render(const std::vector<DebugSphere>& spheres,
                const scenegraph::Camera& camera);

    void render(const std::vector<DebugCone>& cones,
                const scenegraph::Camera& camera);

private:
    void ensure_resources();
    void ensure_box_resources();
    void ensure_sphere_resources();
    void ensure_cone_resources();

    unsigned int vao_ = 0;
    unsigned int vbo_ = 0;
    int vertex_count_ = 0;
    std::unique_ptr<Shader> shader_;

    unsigned int box_vao_ = 0;
    unsigned int box_vbo_ = 0;
    int box_vertex_count_ = 0;

    unsigned int sphere_vao_ = 0;
    unsigned int sphere_vbo_ = 0;
    int sphere_vertex_count_ = 0;

    unsigned int cone_vao_ = 0;
    unsigned int cone_vbo_ = 0;
    int cone_vertex_count_ = 0;
};

}  // namespace renderer
