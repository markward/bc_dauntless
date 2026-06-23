// native/src/renderer/include/renderer/nebula_pass.h
#pragma once

#include <glm/glm.hpp>

#include <memory>
#include <string>
#include <vector>

namespace assets { class Texture; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// One MetaNebula volume: a union of fuzzy spheres with a tint and an
/// inside-visibility falloff distance (GU). Textures are faithful BC assets.
struct NebulaVolume {
    std::vector<glm::vec4> spheres;   // xyz = centre (GU), w = radius (GU)
    glm::vec3   rgb        = glm::vec3(0.5f);
    float       visibility = 145.0f;  // GU; inside-fog falloff distance
    std::string external_tex;         // from-outside billboard (opaque)
    std::string internal_tex;         // inside-fog overlay (alpha)
};

class NebulaPass {
public:
    // Render style. FAITHFUL is the only path this project ships; the seam
    // is here so a future Modern-VFX VOLUMETRIC path drops in behind the
    // same data contract (NebulaVolume) with no host/model changes.
    enum class Style { FAITHFUL, VOLUMETRIC };

    NebulaPass();
    ~NebulaPass();
    NebulaPass(const NebulaPass&) = delete;
    NebulaPass& operator=(const NebulaPass&) = delete;

    /// Draw all volumes. Caller guarantees the scene depth buffer is
    /// populated (inside fog reads depth so hulls occlude correctly).
    /// Early-outs when `volumes` is empty or the pass is disabled.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaVolume>& volumes);

    void  set_enabled(bool enabled) { enabled_ = enabled; }
    bool  enabled() const { return enabled_; }
    void  set_style(Style s) { style_ = s; }
    Style style() const { return style_; }

private:
    bool  enabled_     = true;
    bool  initialized_ = false;
    Style style_       = Style::FAITHFUL;

    void initialize_gl();
};

}  // namespace renderer
