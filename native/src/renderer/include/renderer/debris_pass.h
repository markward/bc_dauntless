// native/src/renderer/include/renderer/debris_pass.h
#pragma once
#include <memory>
#include <functional>
#include <glm/glm.hpp>
#include <assets/mesh.h>
#include <scenegraph/instance.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer {
class Pipeline;
class CarveFieldCache;

/// Debris pass — tumbling voxel chunks ejected from a breach event.
///
/// For each visible Space-pass instance with active breach events, samples
/// kChunkCount solid voxels from the ship's original fill inside the event's
/// carve sphere, then draws each chunk as a unit cube (scaled to the voxel cell
/// size), positioned + rotated analytically from (birth_time, seed, age).
///
/// Depth-tested against the scene; alpha-blended for the fade.
/// Gated entirely on dauntless_hull_damage::enabled().
class DebrisPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    DebrisPass();
    ~DebrisPass() = default;
    DebrisPass(const DebrisPass&)            = delete;
    DebrisPass& operator=(const DebrisPass&) = delete;

    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                float now);

private:
    void ensure_cube();
    std::unique_ptr<assets::Mesh> cube_mesh_;
};

} // namespace renderer
