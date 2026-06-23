// native/src/renderer/include/renderer/nebula_godray_pass.h
#pragma once
#include <glm/glm.hpp>
#include <vector>

namespace scenegraph { struct Camera; }
namespace renderer {

class Pipeline;

/// One active lightning flash for the screen-space god-ray pass.
struct GodrayFlash {
    glm::vec3 dir       = glm::vec3(0.0f, 1.0f, 0.0f);  // world dir light comes FROM
    float     intensity = 0.0f;
    glm::vec3 color     = glm::vec3(1.0f);
};

/// Screen-space radial scatter ("crepuscular rays"). For each flash, projects
/// `dir` to a screen anchor and radially smears the bright HDR colour outward
/// from it, additively composited. Early-outs on empty/disabled.
class NebulaGodrayPass {
public:
    NebulaGodrayPass();
    ~NebulaGodrayPass();
    NebulaGodrayPass(const NebulaGodrayPass&) = delete;
    NebulaGodrayPass& operator=(const NebulaGodrayPass&) = delete;

    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<GodrayFlash>& flashes,
                std::uint32_t hdr_color_tex);

    void set_enabled(bool e) { enabled_ = e; }
    bool enabled() const { return enabled_; }

private:
    bool enabled_ = true;
    bool initialized_ = false;
    unsigned int vao_ = 0;          // empty VAO (fullscreen triangle)
    void initialize_gl();
};

}  // namespace renderer
