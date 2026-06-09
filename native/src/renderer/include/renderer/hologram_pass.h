// native/src/renderer/include/renderer/hologram_pass.h
#pragma once

#include <functional>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>  // InstanceId, ModelHandle

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// Descriptor for the single ship drawn as a Fresnel hologram. The viewer
/// (Task B4) owns one of these and flips `active`. `instance` is the real
/// scenegraph instance whose geometry + world transform are re-drawn with
/// the hologram shader; nothing is re-centred — everything stays in absolute
/// world space.
struct HologramShip {
    bool                  active   = false;
    scenegraph::InstanceId instance{};
    glm::vec3             color    = glm::vec3(0.30f, 0.62f, 1.0f);
    float                 opacity_facing  = 0.05f;
    float                 opacity_grazing = 0.50f;
};

class HologramPass {
public:
    /// Resolve a model handle to its CPU-side asset (same lookup the opaque
    /// pass uses). Returns nullptr if the handle is stale.
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    HologramPass()                               = default;
    ~HologramPass()                              = default;
    HologramPass(const HologramPass&)            = delete;
    HologramPass& operator=(const HologramPass&) = delete;

    /// Re-draw `ship.instance`'s mesh with the hologram (Fresnel) shader at
    /// its real world transform: additive, depth-test on, depth-write off,
    /// culling off. No-op when `ship.active` is false or the instance/model
    /// can't be resolved.
    void render(const HologramShip& ship,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup);
};

}  // namespace renderer
