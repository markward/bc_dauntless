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
    // Render-space distance from the eye to the light's body (a star), or 0
    // for a light with no body on screen (a lightning flash). Geometry nearer
    // than half of it is an occluder: it shadows the shafts but is never
    // smeared along them. 0 makes every hull an occluder (only sky scatters).
    float     distance  = 0.0f;
};

/// Window depth at or beyond which a pixel is a SOURCE of `flash`'s shafts
/// (sky, the light's own body); anything nearer occludes. 1.0 (sky only) for
/// a light with no body or one behind the eye.
float godray_source_depth(const scenegraph::Camera& camera,
                          const GodrayFlash& flash);

/// Screen-space radial scatter ("crepuscular rays"). For each flash, projects
/// `dir` to a screen anchor and radially smears the bright HDR colour outward
/// from it at half resolution, then adds it into the HDR target blurred. Only
/// the sky and the light's own body are smeared (hulls in front of the light
/// occlude; their lights never streak). Early-outs on empty/disabled, and the
/// caller's framebuffer and viewport are bound again on return.
class NebulaGodrayPass {
public:
    NebulaGodrayPass();
    ~NebulaGodrayPass();
    NebulaGodrayPass(const NebulaGodrayPass&) = delete;
    NebulaGodrayPass& operator=(const NebulaGodrayPass&) = delete;

    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<GodrayFlash>& flashes,
                std::uint32_t hdr_color_tex,
                std::uint32_t hdr_depth_tex);

    void set_enabled(bool e) { enabled_ = e; }
    bool enabled() const { return enabled_; }

private:
    bool enabled_ = true;
    bool initialized_ = false;
    unsigned int vao_ = 0;          // empty VAO (fullscreen triangle)
    // Half-res scratch, (re)allocated with the viewport. mask = the masked
    // source image (sky + the light's body, hulls zeroed); rays = every
    // light's march, added up, then blurred up into the HDR target. Neither
    // is the HDR target, so no pass reads what it writes.
    unsigned int mask_tex_ = 0, mask_fbo_ = 0;
    unsigned int rays_tex_ = 0, rays_fbo_ = 0;
    int half_w_ = 0, half_h_ = 0;
    void initialize_gl();
    void ensure_half_targets(int w, int h);
    void destroy_half_targets();
};

}  // namespace renderer
