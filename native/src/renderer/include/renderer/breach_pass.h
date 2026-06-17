// native/src/renderer/include/renderer/breach_pass.h
#pragma once

#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>  // InstanceId, ModelHandle
#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; class HullCarveField; }

namespace renderer {

class Pipeline;

/// Breach pass — dual-contour interior surface (hull-breach-2b, Task 6).
///
/// For each damaged instance (one with active carve spheres), carves the
/// source hull's scalar fill with every active carve sphere, extracts a sharp
/// dual-contour surface mesh, and renders it triplanar-textured with BC's
/// Damage.tga — the flat-panel hull cross-section seen through the holes the
/// hull-clip pass punches (replaces the 2a colored-cube splat).
///
/// Runs AFTER the opaque hull pass with depth-test ON, depth-write ON, and
/// CULL OFF (double-sided: the DC mesh winds INWARD with OUTWARD normals — see
/// voxel/dual_contour.h): a surface fragment behind intact hull depth-fails
/// (hidden); one behind a hole (hull discarded, no depth written there) passes
/// (visible through the hole).
///
/// Extraction is expensive (~16 ms for the Galaxy), so the carved fill + mesh
/// are cached per instance and only re-extracted when that instance's carve
/// "version" (the max active carve seq) changes — never per frame.
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
    /// resolve its model -> source-hull fill + plane palette (via the owned
    /// cache), build the carved fill, extract the DC surface (cached), and draw
    /// it at the instance's world transform.
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup);

    /// Lower-level entry: draw the breach interior surface for ONE instance
    /// given its source fill, plane palette, carve field, and world transform.
    /// `instance_key` identifies the per-instance mesh cache slot (so repeat
    /// calls with an unchanged carve version reuse the extracted mesh). Public
    /// so the GL render test can drive it with a synthetic volume without
    /// standing up the asset cache. Assumes the breach shader GL state
    /// (depth/cull) is the caller's responsibility — render() sets it.
    void draw_instance(std::uintptr_t instance_key,
                       const voxel::VoxelVolume& fill,
                       const std::vector<glm::vec4>& palette,
                       const scenegraph::HullCarveField& carve,
                       const glm::mat4& world_xf,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline);

    /// Copy `fill` and apply every active carve sphere (smooth-falloff
    /// carve_sphere). Pure CPU; exposed for testing the carve application.
    static voxel::VoxelVolume build_carved_fill(
        const voxel::VoxelVolume& fill,
        const scenegraph::HullCarveField& carve);

    /// Filter a DC mesh's index list to only triangles whose centroid lies
    /// within (slot.radius + margin) of at least one active carve sphere.
    /// The positions array is unchanged (unused verts are harmless). Pure CPU;
    /// exposed for testing. margin should be ~1 cell (e.g. glm::length(cell)).
    static std::vector<std::uint32_t> filter_to_carves(
        const std::vector<glm::vec3>& positions,
        const std::vector<std::uint32_t>& indices,
        const scenegraph::HullCarveField& carve,
        float margin);

    /// GL texture id for the triplanar Damage.tga sample. Set once in host
    /// init. If left 0, the pass lazily loads Damage.tga from the default BC
    /// path on first draw (so GL tests work without host wiring).
    void set_damage_texture(unsigned int tex_id) { damage_tex_ = tex_id; }

private:
    void ensure_mesh_buffers();
    void ensure_damage_texture();

    // Isovalue used to threshold BC's 0..127 fill field during DC extraction.
    static constexpr int kIsovalue = 64;

    // Per-instance extracted-surface cache. Re-extract only when the carve
    // version (max active carve seq) changes.
    struct CachedMesh {
        std::uint64_t carve_version = 0;  // 0 = never extracted
        int           index_count = 0;
        // No GPU buffers per instance: we stream into a shared dynamic
        // VBO/EBO per draw, but keep CPU mesh data so a re-draw at the same
        // version doesn't re-extract.
        std::vector<float>         interleaved;  // pos.xyz, normal.xyz
        std::vector<std::uint32_t> indices;
    };

    std::uint64_t carve_version(const scenegraph::HullCarveField& carve) const;
    const CachedMesh& mesh_for(std::uintptr_t instance_key,
                               const voxel::VoxelVolume& fill,
                               const std::vector<glm::vec4>& palette,
                               const scenegraph::HullCarveField& carve);

    unsigned int vao_       = 0;
    unsigned int vbo_       = 0;  // interleaved pos+normal, streamed per draw
    unsigned int ebo_       = 0;  // indices, streamed per draw
    unsigned int damage_tex_ = 0;
    bool         damage_tex_tried_ = false;  // lazy-load attempted

    std::unordered_map<std::uintptr_t, CachedMesh> mesh_cache_;
    voxel::SourceVolumeCache source_cache_;
};

}  // namespace renderer
