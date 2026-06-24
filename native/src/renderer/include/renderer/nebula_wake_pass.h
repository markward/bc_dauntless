// native/src/renderer/include/renderer/nebula_wake_pass.h
#pragma once

#include <glm/glm.hpp>

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// One wake trail point: world position, age-faded strength (0..1), and the
/// emitting pod's size (radius). The billboard half-size is size × a dial.
struct NebulaWakePoint {
    glm::vec3 pos{0.0f};
    float     strength = 0.0f;
    float     size     = 0.0f;
};

/// Decoupled ship-wake trail (spec §8 Plan B #1). Draws each wake trail point
/// (NebulaWakePoint: world pos, age-faded strength, per-point size) as a
/// camera-facing additive soft-glow billboard — self-luminous, independent of
/// cloud density. One trail per impulse-engine pod, sized per pod. A sibling
/// of HullDischargePass: additive blend, depth-test ON (nearer hull occludes),
/// depth-write OFF; GL state restored to canonical defaults before returning.
class NebulaWakePass {
public:
    NebulaWakePass();
    ~NebulaWakePass();
    NebulaWakePass(const NebulaWakePass&)            = delete;
    NebulaWakePass& operator=(const NebulaWakePass&) = delete;

    /// wake: trail points (world pos, strength 0..1, per-point size). time_s
    /// drives the slow churn in the shader.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaWakePoint>& wake,
                float time_s);

    void set_enabled(bool v) noexcept { enabled_ = v; }
    bool enabled() const noexcept { return enabled_; }

private:
    bool enabled_ = true;
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;

    void ensure_quad_mesh();
};

}  // namespace renderer
