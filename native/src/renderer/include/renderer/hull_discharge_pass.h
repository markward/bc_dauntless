// native/src/renderer/include/renderer/hull_discharge_pass.h
#pragma once

#include <glm/glm.hpp>

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// One active hull electrical discharge: an additive electric billboard at a
/// hull world point, eased + faded over age/life. Fed by the driver (Task 1)
/// through the host binding each frame.
struct HullDischarge {
    glm::vec3 world_pos{0.0f};
    float     age  = 0.0f;
    float     life = 0.1f;
    float     size = 0.3f;
    glm::vec3 color{0.6f, 0.8f, 1.0f};
};

/// Crackle pass — a sibling of HitVfxPass. Draws each discharge as a
/// camera-facing additive billboard with a procedural jagged electric shader.
/// Additive blend, depth-test on (occluded by nearer hull), depth-write off;
/// GL state restored to canonical defaults before returning.
class HullDischargePass {
public:
    HullDischargePass();
    ~HullDischargePass();
    HullDischargePass(const HullDischargePass&)            = delete;
    HullDischargePass& operator=(const HullDischargePass&) = delete;

    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<HullDischarge>& discharges);

    void set_enabled(bool v) noexcept { enabled_ = v; }
    bool enabled() const noexcept { return enabled_; }

private:
    bool enabled_ = true;
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;

    void ensure_quad_mesh();
};

}  // namespace renderer
