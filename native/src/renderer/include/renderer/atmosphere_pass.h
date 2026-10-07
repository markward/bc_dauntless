// native/src/renderer/include/renderer/atmosphere_pass.h
#pragma once

#include <renderer/frame.h>   // Lighting, SunDescriptor, FrameSubmitter::ModelLookup

#include <assets/mesh.h>

#include <cstdint>
#include <optional>
#include <vector>

namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// Planet atmosphere shell (spec 2026-10-07-planet-atmosphere-design.md §5).
/// Drawn in render phase 2 (render_space_vfx) into the resolved HDR target:
/// a unit geosphere scaled to each planet's shell top, whose fragment shader
/// (atmosphere.frag) mirrors renderer::planet_atmo's single-scattering march
/// and ends it at the scene's opaque depth. Additive; depth test off.
class AtmospherePass {
public:
    using ModelLookup = FrameSubmitter::ModelLookup;

    AtmospherePass() = default;
    ~AtmospherePass();
    AtmospherePass(const AtmospherePass&) = delete;
    AtmospherePass& operator=(const AtmospherePass&) = delete;

    // Additive HDR draw of every visible Space instance whose atmosphere is
    // enabled and whose model has a sphere_map. `scene_depth` is the target's
    // resolved depth texture (sampled to end the march); depth test is off.
    // With nothing to draw it touches no GL state at all.
    void render(const scenegraph::World& world, const scenegraph::Camera& cam,
                Pipeline& pipeline, const ModelLookup& lookup, const Lighting& lighting,
                const std::vector<SunDescriptor>& suns, std::uint32_t scene_depth,
                int viewport_w, int viewport_h);

    int last_draw_count() const noexcept { return last_draw_count_; }

private:
    std::optional<assets::Mesh> shell_;   // unit geosphere, uploaded on first draw
    int last_draw_count_ = 0;
};

}  // namespace renderer
