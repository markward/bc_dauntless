// native/src/renderer/include/renderer/nebula_pass.h
#pragma once

#include <glm/glm.hpp>

#include <memory>
#include <string>
#include <vector>

namespace assets { class Texture; class Mesh; }
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
    ~NebulaPass();  // frees quad_vao_/quad_vbo_ if initialized
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

    // Unit sphere mesh (radius 1, built lazily via build_uv_sphere — same
    // source the sun/backdrop passes use). Scaled per-volume in the shader.
    std::unique_ptr<assets::Mesh>    sphere_;
    // Inside-fog overlay (nebulaoverlay.tga). Loaded once from the first
    // volume's internal_tex; a null/zero-id texture means "no noise" but the
    // pass still draws solid fog.
    std::unique_ptr<assets::Texture> overlay_tex_;
    std::string                      overlay_path_;   // path the texture loaded from

    // Outside billboard shell (Task 7): external texture + camera-facing quad VBO.
    std::unique_ptr<assets::Texture> external_tex_;
    std::string                      external_path_;  // path the texture loaded from
    unsigned int                     quad_vao_ = 0;
    unsigned int                     quad_vbo_ = 0;

    void initialize_gl();
    // Lazily load the overlay texture for `path`. No-op if already loaded
    // (path-keyed); returns the GL texture id (0 when absent/failed).
    unsigned int ensure_overlay(const std::string& path);
    // Lazily load the external billboard texture for `path`. Same guard semantics.
    unsigned int ensure_external(const std::string& path);
};

}  // namespace renderer
