// native/src/renderer/include/renderer/subsystem_pin_pass.h
#pragma once

#include <assets/texture.h>

#include <cstdint>
#include <memory>
#include <vector>

#include <glm/glm.hpp>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// One billboard pin to be drawn above a subsystem hardpoint.
struct SubsystemPin {
    glm::vec3 world_pos;
    int       icon_id    = 6;     // DamageIcons enum 0..9 (default = System)
    bool      highlighted = false;
};

/// Draws camera-facing billboard quads (one per SubsystemPin) with the
/// subsystem's DamageIcons glyph composited on a white circular disc.
/// Rendered with depth-test OFF so pins are always visible through the hull.
class SubsystemPinPass {
public:
    SubsystemPinPass();
    ~SubsystemPinPass();

    SubsystemPinPass(const SubsystemPinPass&)            = delete;
    SubsystemPinPass& operator=(const SubsystemPinPass&) = delete;

    /// device_scale_factor is the display's device-pixel ratio
    /// (framebuffer / logical window size). Pins are sized in logical
    /// points and multiplied by this so they keep a constant apparent
    /// size on HiDPI/Retina displays. Defaults to 1.0 (no scaling).
    void render(const std::vector<SubsystemPin>& pins,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                float device_scale_factor = 1.0f);

private:
    void ensure_quad();
    void ensure_glyphs();

    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;

    // Indexed by icon_id (0..9). Entries are always non-null after ensure_glyphs();
    // a default-constructed Texture has id()==0 and acts as a no-op bind.
    std::vector<std::unique_ptr<assets::Texture>> glyphs_;
    bool glyphs_loaded_ = false;
};

}  // namespace renderer
