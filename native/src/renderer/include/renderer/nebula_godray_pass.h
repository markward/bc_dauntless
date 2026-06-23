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
    // Scratch copy of the HDR colour. The radial march samples THIS (not the
    // bound HDR target) so reading + additively writing the same target never
    // happens — a same-FBO feedback loop returns tile-aligned garbage (a grid)
    // on some GPUs. Resized to the HDR viewport on demand.
    unsigned int scene_copy_tex_ = 0;
    int copy_w_ = 0, copy_h_ = 0;
    void initialize_gl();
    void ensure_scene_copy(int w, int h);
};

}  // namespace renderer
