// native/src/renderer/include/renderer/breach_pass.h
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/breach_events.h>
#include <scenegraph/instance.h>  // InstanceId, ModelHandle

#include <renderer/instance_field_cache.h>  // InstanceFieldCache::Entry
#include <voxel/volume.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;
class CarveFieldCache;

/// Breach pass — box-proxy interior surface (raymarched-breach-interior
/// Task 3; supersedes the hull-breach-2b/2c per-carve sphere scoop).
///
/// For each DAMAGED instance (one with a per-instance damage field in
/// `InstanceFieldCache` — see that header's class comment for what "damaged"
/// means there), draws ONE box proxy covering the field's own body-frame
/// extent (`InstanceFieldCache::Entry::origin` / `dims * cell`), masked by
/// the ORIGINAL (uncarved) hull fill. The box itself is undecorated —
/// `breach.vert` performs no per-carve deformation — and every pixel it
/// covers raymarches the damage field per-fragment (`breach.frag`) to find
/// the actual cavity wall, or discards. This is what removes the plan's
/// namesake defect: the old sphere-per-carve draw only ever covered the
/// fixed 24-slot `HullCarveField` ring, so a carve beyond slot 24 cut hull
/// with nothing drawn behind it (see-through to space); the field itself has
/// no such cap, so the box proxy's interior tracks every carve regardless of
/// how many the sphere ring could hold.
///
/// GL state: depth-test ON, depth-write ON, cull FRONT (so only the box's
/// far faces — exactly the point where each covered pixel's view ray exits
/// the box — are rasterised). Must run AFTER the opaque hull pass so the
/// hull's depth occludes the proxy except through the clip holes, and AFTER
/// the stencil is stamped (`FrameSubmitter::submit_carve_stencil`) — the
/// stencil test (`GL_EQUAL` against 1, `breach_pass.cc`) is what keeps the
/// proxy from painting over the whole ship; nothing here weakens or
/// replaces it.
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

    /// Iterate the world; for each Space-pass instance with a per-instance
    /// damage field (`field_cache->get(inst.id) != nullptr`), fetch the
    /// original fill from `carve_cache` and draw ONE box proxy. An instance
    /// with no field entry (never carved, or no baked field for its source)
    /// draws nothing — checked FIRST, before any model/fill lookup, so an
    /// undamaged ship costs exactly one map lookup, not a model-lookup +
    /// fill-cache round trip. `field_cache` may be null (feature entirely
    /// unavailable): render() then draws nothing for any instance.
    ///
    /// `now` is the current game-clock time (seconds), used to compute the
    /// molten-rim emissive term's age. With one draw per instance (not per
    /// carve) there is no longer a single carve slot to measure age from;
    /// the uniform passed to the shader is the age of the MOST RECENT active
    /// breach event on the instance (kRimLife + 1, "cold", if none) — a
    /// simplification from the old per-carve-localised rim glow, not a
    /// faithful per-fragment reconstruction of it. See breach_pass.cc's
    /// render() for the exact rule.
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                InstanceFieldCache* field_cache,
                float now = 0.f);

    /// Draw the breach box proxy for ONE instance given its ORIGINAL fill,
    /// its already-built per-instance damage-field entry, and world
    /// transform. Builds and uploads a GL_R8 3D texture for the fill on
    /// first use (keyed by `instance_key`). Public so GL render tests can
    /// drive the pass without standing up the full asset cache / World /
    /// CarveFieldCache / InstanceFieldCache machinery — a test builds its
    /// own `InstanceFieldCache::Entry` (pack a `voxel::DistanceField` via
    /// `voxel::pack_field_to_atlas` and upload it) and passes it directly.
    /// Caller owns the GL state (depth/cull); render() sets it the same way.
    ///
    /// `instance_key` is used to cache the per-instance FILL 3D texture in
    /// this test/standalone path; in production the fill texture comes from
    /// `CarveFieldCache` instead (source-keyed, shared across instances of
    /// the same hull). `field.tex2d` (the DAMAGE atlas) is never cached
    /// here — it is always the caller's own, already-uploaded texture,
    /// exactly as `InstanceFieldCache::get()` returns it in production.
    ///
    /// `breach_age` is the age (in seconds) of the matching breach event for
    /// the molten-rim emissive. Pass 0.0f for a fresh (hot) proxy, or
    /// kRimLife + 1 (the default) for a cold/no-event proxy — which is
    /// byte-identical to the pre-emissive scoop.
    ///
    /// `breach_center`/`breach_radius` are that SAME event's own
    /// `center_body`/`radius` (scenegraph::BreachEvent — both already
    /// carried by the event ring, no new plumbing upstream of this pass).
    /// One instance can hold several old, cooled breaches alongside one
    /// fresh one; `u_breach_age` alone is a single scalar applied to every
    /// fragment on the WHOLE instance, so without a position the molten-rim
    /// term would re-ignite every old hole on the hull, not just the fresh
    /// one. breach.frag gates the emissive by distance from `breach_center`
    /// (scaled by `breach_radius`) as well as by age. Defaults (origin,
    /// 0) are harmless when `breach_age` is also left at its cold default —
    /// heat is already 0 from the age term in that case.
    void draw_instance(std::uintptr_t instance_key,
                       const voxel::VoxelVolume& fill,
                       const InstanceFieldCache::Entry& field,
                       const glm::mat4& world_xf,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       float breach_age = scenegraph::kRimLife + 1.f,
                       const glm::vec3& breach_center = glm::vec3(0.0f),
                       float breach_radius = 0.0f);

    /// Total number of box-proxy draw calls (glDrawElements invocations)
    /// issued by this pass instance so far, across every render()/
    /// draw_instance() call. Exists for the same reason InstanceFieldCache::
    /// uploads() does: a pass that silently issued more than one draw per
    /// damaged instance (the exact regression this task exists to prevent —
    /// the old code drew one sphere PER CARVE) would otherwise be
    /// indistinguishable, from the rendered pixels alone, from one that
    /// draws correctly.
    std::size_t draw_calls() const { return draw_calls_; }

private:
    void ensure_box();
    // Lazily load the 4-frame animated interior texture (game/data/Damage1..4.tga).
    void ensure_damage_frames();

    // Draw one box proxy for a single instance using an already-uploaded
    // fill 3D texture and an already-built damage-field entry. Sets every
    // per-instance uniform (fill, field atlas on unit 2, damage texture,
    // rim age) and issues exactly one glDrawElements call.
    void draw_box_proxy(const InstanceFieldCache::Entry& field,
                        unsigned int fill_tex,
                        const glm::vec3& fill_origin,
                        const glm::vec3& fill_cell,
                        const glm::ivec3& fill_dims,
                        const glm::mat4& world_xf,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        float breach_age,             // age of matching event; large = cold
                        const glm::vec3& breach_center,  // that event's own centre, body frame
                        float breach_radius,          // that event's own visible radius
                        unsigned int damage_tex);  // current animation frame texture

    // Build (once) a fill GL_R8 3D texture from a VoxelVolume.
    // Returns 0 on failure.  Caller owns the GL texture.
    static unsigned int upload_fill_tex(const voxel::VoxelVolume& fill);

    // Unit-cube ([0,1]^3) VAO/VBO/EBO — built once per pass lifetime. Scaled
    // and offset per-instance in breach.vert via u_hull_field_origin/cell/
    // dims; this CPU-side mesh never changes.
    std::unique_ptr<assets::Mesh> box_mesh_;

    // 4-frame animated interior texture (game/data/Damage1..4.tga), cycled by
    // the game clock in render(). Any frame left 0 (asset missing / headless
    // test) degrades to the shader's grey base — never a hole to the stars.
    unsigned int damage_frames_[4]  = {0, 0, 0, 0};
    bool         damage_frames_tried_ = false;
    // Owns the GL textures backing damage_frames_[]. Tied to the pass (not a
    // process-lifetime static) so they are released in the same GL context that
    // created them when shutdown() resets the pass — see load_damage_tga().
    std::vector<assets::Texture> damage_owned_;

    // Per-instance fill 3D texture cache used by the test/standalone path in
    // draw_instance(). In the production path, the fill tex comes from
    // CarveFieldCache. Keyed by instance_key; textures are deleted in the dtor.
    struct FillEntry { unsigned int tex3d = 0; };
    std::unordered_map<std::uintptr_t, FillEntry> fill_cache_;

    // See draw_calls(). Incremented once per glDrawElements call, inside
    // draw_box_proxy() — the ONE place either render() or draw_instance()
    // actually submits geometry.
    std::size_t draw_calls_ = 0;
};

}  // namespace renderer
