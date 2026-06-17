// native/src/renderer/include/renderer/breach_pass.h
#pragma once

#include <functional>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>  // InstanceId, ModelHandle
#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; class HullCarveField; }

namespace renderer {

class Pipeline;

/// Breach pass — classic colored-voxel interior splat (Task 9).
///
/// For each damaged instance (one with active carve spheres), draws the source
/// hull's solid interior voxels that fall inside each carve sphere as small
/// colored cubes — the authentic BC "chunky colored guts" seen through the
/// see-through holes the hull-clip pass (Task 8) punches.
///
/// Runs AFTER the opaque hull pass with depth-test ON, depth-write ON: a gut
/// cube behind intact hull depth-fails (hidden); a gut cube behind a hole
/// (hull discarded, no depth written there) passes (visible through the hole).
///
/// Gated entirely on dauntless_hull_damage::enabled(): when off, render() is a
/// no-op and the stock-BC path is byte-identical.
class BreachPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    BreachPass();
    ~BreachPass();
    BreachPass(const BreachPass&)            = delete;
    BreachPass& operator=(const BreachPass&) = delete;

    /// Iterate the world; for each Space-pass instance with carve spheres,
    /// resolve its model -> source-hull voxel volume (via the owned cache),
    /// select the solid voxels inside each active carve sphere, and splat them
    /// as colored cubes at the instance's world transform.
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup);

    /// Lower-level entry: draw the breach cubes for ONE instance given an
    /// already-resolved source volume, its carve field, and the world
    /// transform. Public so the GL render test can drive it with a synthetic
    /// volume without standing up the asset cache. Assumes the breach shader
    /// state (depth/blend) is the caller's responsibility — render() sets it.
    void draw_instance(const voxel::VoxelVolume& volume,
                       const scenegraph::HullCarveField& carve,
                       const glm::mat4& world_xf,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline);

private:
    void ensure_cube_mesh();

    unsigned int cube_vao_      = 0;
    unsigned int cube_vbo_      = 0;  // unit-cube vertices
    unsigned int cube_ebo_      = 0;  // cube indices
    unsigned int instance_vbo_  = 0;  // per-instance vec4 (center + seed)
    int          index_count_   = 0;

    // Scratch reused across instances to avoid per-frame allocation.
    std::vector<glm::vec4> scratch_;
    voxel::SourceVolumeCache source_cache_;
};

}  // namespace renderer
