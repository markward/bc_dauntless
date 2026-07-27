// native/src/renderer/include/renderer/gizmo_pass.h
#pragma once

#include <glm/glm.hpp>

#include <memory>

namespace scenegraph { struct Camera; }

namespace renderer {

class Shader;

/// Developer 3-axis transform gizmo for the Ship Property Viewer: three
/// coloured arrows (shaft + small cone head) drawn in world space, depth
/// test off, always opaque. Self-contained (owns its shader + a unit-arrow
/// mesh along local +Z), not wired into the frame by default.
class GizmoPass {
public:
    struct Gizmo {
        glm::vec3 origin{0.0f};
        glm::vec3 axis[3]{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
        float length{1.0f};
        int highlight{-1};   // 0/1/2 = brightened axis, -1 = none
        int handle_kind{0};  // 0 = cone/arrow tip (move), 1 = cube tip (scale)
    };

    GizmoPass();
    ~GizmoPass();

    GizmoPass(const GizmoPass&)            = delete;
    GizmoPass& operator=(const GizmoPass&) = delete;

    // Draws three coloured arrows (shaft + head), depth-test off. No-op when
    // g.length <= 0.
    void render(const Gizmo& g, const scenegraph::Camera& camera);

private:
    void ensure_resources();

    std::unique_ptr<Shader> shader_;
    unsigned int vao_{0}, vbo_{0};
    int vertex_count_{0};

    // Second unit mesh: shaft + cube tip (Scale gizmo, handle_kind == 1).
    unsigned int cube_vao_{0}, cube_vbo_{0};
    int cube_vertex_count_{0};
};

}  // namespace renderer
