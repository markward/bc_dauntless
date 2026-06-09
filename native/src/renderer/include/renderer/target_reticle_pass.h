// native/src/renderer/include/renderer/target_reticle_pass.h
#pragma once

#include <assets/texture.h>

#include <memory>

#include <glm/glm.hpp>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Faithful BC two-element target reticle:
///   - four target.tga corner billboards boxing the whole target ship
///     (sized from the target's bounding-sphere radius), and
///   - one subtarget.tga crosshair on the locked subsystem (optional).
/// Drawn depth-test OFF so the reticle is always visible over the hull.
struct TargetReticle {
    bool      visible       = false;
    glm::vec3 ship_center   {0.0f};
    float     ship_radius   = 0.0f;
    bool      has_subtarget = false;
    glm::vec3 subtarget_pos {0.0f};
    bool      has_bars      = false;
    float     bar_alignment = 0.0f;   // [-1,+1], +1 fore, -1 aft
};

class TargetReticlePass {
public:
    TargetReticlePass();
    ~TargetReticlePass();
    TargetReticlePass(const TargetReticlePass&)            = delete;
    TargetReticlePass& operator=(const TargetReticlePass&) = delete;

    void render(const TargetReticle& reticle,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    void ensure_quad();
    void ensure_textures();

    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::unique_ptr<assets::Texture> corner_tex_;     // game/data/target.tga
    std::unique_ptr<assets::Texture> crosshair_tex_;  // game/data/subtarget.tga
    std::unique_ptr<assets::Texture> bar_tex_;     // game/data/Icons/tilevertline.tga
    std::unique_ptr<assets::Texture> arrow_tex_;   // game/data/Icons/TargetArrow.tga
    bool textures_loaded_ = false;
};

}  // namespace renderer
