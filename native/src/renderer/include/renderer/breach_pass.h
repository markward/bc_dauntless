// native/src/renderer/include/renderer/breach_pass.h
#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <unordered_map>

#include <glm/glm.hpp>

#include <assets/mesh.h>
#include <scenegraph/instance.h>  // InstanceId, ModelHandle

#include <voxel/volume.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; class HullCarveField; }

namespace renderer {

class Pipeline;
class CarveFieldCache;

/// Breach pass — sphere-scoop interior surface (hull-breach-2b Path C).
///
/// For each damaged instance (with active carve spheres), draws the inner
/// (far) wall of a unit sphere scaled to each active carve sphere's radius,
/// masked by the ORIGINAL (uncarved) hull fill. Fragments where the original
/// fill says "no material" (open space, far side of thin hull) are discarded,
/// giving genuine see-through. Fragments in solid material render the recessed
/// interior bowl, triplanar-textured with BC's Damage.tga.
///
/// GL state: depth-test ON, depth-write ON, cull FRONT (so the inner/far wall
/// is drawn and cannot poke out past the hull). Must run AFTER the opaque hull
/// pass so the hull's depth occludes the scoop except through the clip holes.
///
/// The hull hole clip (opaque.frag) is now a pure sphere clip — identical
/// spheres — so hole and scoop align by construction.
///
/// Gated entirely on dauntless_hull_damage::enabled(): when off, render() is
/// a no-op and the stock-BC path is byte-identical.
class BreachPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    BreachPass();
    ~BreachPass();
    BreachPass(const BreachPass&)            = delete;
    BreachPass& operator=(const BreachPass&) = delete;

    /// Iterate the world; for each Space-pass instance with active carves,
    /// fetch the original fill from `carve_cache` and draw the scoop.
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache);

    /// Draw the breach scoop for ONE instance given its ORIGINAL fill,
    /// carve field, and world transform. Builds and uploads a GL_R8 3D
    /// texture for the fill on first use (keyed by fill pointer). Public so
    /// GL render tests can drive the pass without standing up the full asset
    /// cache. Caller owns the GL state (depth/cull); render() sets it.
    ///
    /// `instance_key` is used to cache the per-instance fill 3D texture in
    /// test paths; in production, the fill texture comes from CarveFieldCache.
    void draw_instance(std::uintptr_t instance_key,
                       const voxel::VoxelVolume& fill,
                       const scenegraph::HullCarveField& carve,
                       const glm::mat4& world_xf,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline);

    /// GL texture id for the triplanar Damage.tga sample. Set once in host
    /// init. If left 0, the pass lazily loads Damage.tga from the default BC
    /// path on first draw.
    void set_damage_texture(unsigned int tex_id) { damage_tex_ = tex_id; }

private:
    void ensure_sphere();
    void ensure_damage_texture();

    // Draw one sphere scoop for a single carve slot using an already-uploaded
    // fill 3D texture. Sets the per-carve uniforms (center, radius, fill).
    void draw_scoop(const glm::vec3& center_body,
                    float radius,
                    unsigned int fill_tex,
                    const glm::vec3& fill_origin,
                    const glm::vec3& fill_cell,
                    const glm::ivec3& fill_dims,
                    const glm::mat4& world_xf,
                    const scenegraph::Camera& camera,
                    Pipeline& pipeline);

    // Build (once) a fill GL_R8 3D texture from a VoxelVolume.
    // Returns 0 on failure.  Caller owns the GL texture.
    static unsigned int upload_fill_tex(const voxel::VoxelVolume& fill);

    // Sphere VAO/VBO/EBO — built once per pass lifetime.
    std::unique_ptr<assets::Mesh> sphere_mesh_;

    unsigned int damage_tex_       = 0;
    bool         damage_tex_tried_ = false;

    // Per-instance fill 3D texture cache used by the test/standalone path in
    // draw_instance(). In the production path, the fill tex comes from
    // CarveFieldCache. Keyed by instance_key; textures are deleted in the dtor.
    struct FillEntry { unsigned int tex3d = 0; };
    std::unordered_map<std::uintptr_t, FillEntry> fill_cache_;
};

}  // namespace renderer
