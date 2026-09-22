// native/src/renderer/include/renderer/breach_pass.h
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

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

/// Breach pass — real-hull-mesh interior surface (raymarched-breach-interior
/// Task 3, round 3; supersedes both the hull-breach-2b/2c per-carve sphere
/// scoop AND round 1/2's synthetic box proxy + entry search).
///
/// For each DAMAGED instance (one with a per-instance damage field in
/// `InstanceFieldCache` — see that header's class comment for what "damaged"
/// means there), draws the SAME hull mesh geometry the opaque pass already
/// drew (`renderer::draw_model_positions_only`), under the SAME carve
/// stencil, masked by the ORIGINAL (uncarved) hull fill. A fragment that
/// survives the stencil is therefore, by construction, sitting exactly on
/// the hull surface at a point the damage field already reads as carved —
/// the SAME `sample_hull_field(surface point) > margin` condition that made
/// the opaque pass discard it and the stencil pass mark it 1 — so
/// `breach.frag` needs no search for where the interior begins: it
/// raymarches straight from there to the cavity's far wall
/// (`raymarch_breach_cavity`, Task 2, unchanged since round 1).
///
/// This is what removes the plan's namesake defect: the old sphere-per-carve
/// draw only ever covered the fixed 24-slot `HullCarveField` ring, so a
/// carve beyond slot 24 cut hull with nothing drawn behind it (see-through
/// to space); the field itself has no such cap, so the interior tracks
/// every carve regardless of how many the sphere ring could hold. Round 2
/// tried to reach every carve by SEARCHING a box proxy for one, sized
/// against the smallest legal carve's DIAMETER — but a carve's along-normal
/// depth (the direction you actually look into a hole from) is
/// `kCarveDepthFactor` (0.45) of its radius, not its full diameter, so that
/// search could still step over a realistic carve's own narrow extent.
/// Round 3 removes the search instead of re-tuning it: drawing the real
/// hull mesh means the ray always starts exactly where the carve is, so
/// there is nothing to search for and no stride to get wrong.
///
/// GL state: depth-test ON, depth-write ON, cull BACK (the SAME winding the
/// opaque pass draws this mesh with — this is the real, outward-facing hull
/// surface, not a back-face-culled proxy shell). Must run AFTER the opaque
/// hull pass so the hull's depth occludes this draw except through the clip
/// holes, and AFTER the stencil is stamped (`FrameSubmitter::
/// submit_carve_stencil`) — the stencil test (`GL_EQUAL` against 1,
/// `breach_pass.cc`) is what keeps this draw out of open space; nothing
/// here weakens or replaces it.
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
    /// original fill from `carve_cache`, resolve the instance's model, and
    /// draw its hull mesh under the stencil. An instance with no field entry
    /// (never carved, or no baked field for its source) draws nothing —
    /// checked FIRST, before any model/fill lookup, so an undamaged ship
    /// costs exactly one map lookup, not a model-lookup + fill-cache round
    /// trip. `field_cache` may be null (feature entirely unavailable):
    /// render() then draws nothing for any instance.
    ///
    /// `now` is the current game-clock time (seconds), used to compute the
    /// molten-rim emissive term's age. With one draw per instance (not per
    /// carve) there is no longer a single carve slot to measure age from;
    /// the age (and position — see `draw_instance`'s own doc) passed to the
    /// shader come from the MOST RECENT active breach event on the instance
    /// (kRimLife + 1 age, "cold", if none). See breach_pass.cc's render()
    /// for the exact rule.
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                InstanceFieldCache* field_cache,
                float now = 0.f);

    /// Draw the breach interior for ONE instance given its ORIGINAL fill,
    /// its already-built per-instance damage-field entry, its hull `model`,
    /// and world transform. Builds and uploads a GL_R8 3D texture for the
    /// fill on first use (keyed by `instance_key`). Public so GL render
    /// tests can drive the pass without standing up the full World /
    /// CarveFieldCache / InstanceFieldCache machinery — a test builds its
    /// own `InstanceFieldCache::Entry` (pack a `voxel::DistanceField` via
    /// `voxel::pack_field_to_atlas` and upload it) and a minimal
    /// `assets::Model` (one node, one uploaded mesh) and passes both
    /// directly. Caller owns the GL state (depth/cull); render() sets it
    /// the same way.
    ///
    /// `model` supplies the ACTUAL geometry this draw submits — via
    /// `renderer::draw_model_positions_only`, the same node-walk the opaque
    /// pass and the shadow-depth pass use, so a multi-mesh model issues one
    /// `glDrawElements` per sub-mesh, exactly as the opaque pass already
    /// does for the SAME model. That is a property of the ASSET, not of
    /// this pass looping over carves — see `draw_calls()`'s own doc for why
    /// that distinction is what this class actually promises.
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
                       const assets::Model& model,
                       const glm::mat4& world_xf,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       float breach_age = scenegraph::kRimLife + 1.f,
                       const glm::vec3& breach_center = glm::vec3(0.0f),
                       float breach_radius = 0.0f);

    /// Number of PROXY SUBMISSIONS this pass instance has issued so far —
    /// one per `render()`/`draw_instance()` call that actually draws
    /// something, NOT one per raw `glDrawElements` call. A hull model with
    /// several sub-meshes (different materials/nodes) issues several GL
    /// draw calls per submission via `draw_model_positions_only` — that is
    /// an ASSET property (how many pieces the hull is split into), the same
    /// as it is for the opaque pass drawing the identical model, and is NOT
    /// what this task's "one draw per instance, not one per carve" promise
    /// is about. What this counter exists to catch — the same reason
    /// InstanceFieldCache::uploads() exists — is a regression back toward
    /// looping over carves: it must stay proportional to the number of
    /// DAMAGED INSTANCES drawn, never to the number of carves or damage
    /// sites any of them carries.
    std::size_t draw_calls() const { return draw_calls_; }

    /// Number of INTERIOR-SHELL submissions issued so far. Counted separately
    /// from `draw_calls()` because the two answer different questions: that
    /// one guards "never loop over carves", this one guards "the shell is
    /// drawn at all, and exactly once per damaged instance". Keeping them
    /// apart also means the shell's arrival does not silently change the
    /// number every existing scoop test asserts on.
    std::size_t shell_draw_calls() const { return shell_draw_calls_; }

private:
    // Lazily load the 4-frame animated interior texture (game/data/Damage1..4.tga).
    void ensure_damage_frames();

    // Draw one instance's hull mesh under the stencil, using an already-
    // uploaded fill 3D texture and an already-built damage-field entry.
    // Sets every per-instance uniform (fill, field atlas on unit 2, damage
    // texture, rim age/position) and submits `model`'s own geometry via
    // draw_model_positions_only — one or more glDrawElements calls,
    // depending on the model's own sub-mesh count.
    void draw_hull_proxy(const assets::Model& model,
                         const InstanceFieldCache::Entry& field,
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
                         unsigned int damage_tex,   // current animation frame texture
                         bool interior_shell = false);  // true = back-face interior shell

    // Draw the hull's BACK faces under the same stencil: the inside of the
    // plating on the far side of a hole. Without it a breach whose carve
    // leaves the authored fill volume (routine -- BC's volumes are 3-9 nodes
    // thick) resolves to the SKYBOX, because the hull is a single-sided shell
    // and the far plating's inside face is culled. Submitted BEFORE the scoop
    // so the scoop, which writes depth at the nearer hull surface, still wins
    // wherever it finds a real cavity wall.
    void draw_interior_shell(const assets::Model& model,
                             const InstanceFieldCache::Entry& field,
                             unsigned int fill_tex,
                             const glm::vec3& fill_origin,
                             const glm::vec3& fill_cell,
                             const glm::ivec3& fill_dims,
                             const glm::mat4& world_xf,
                             const scenegraph::Camera& camera,
                             Pipeline& pipeline,
                             float breach_age,
                             const glm::vec3& breach_center,
                             float breach_radius,
                             unsigned int damage_tex);

    // Build (once) a fill GL_R8 3D texture from a VoxelVolume.
    // Returns 0 on failure.  Caller owns the GL texture.
    static unsigned int upload_fill_tex(const voxel::VoxelVolume& fill);

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

    // See draw_calls(). Incremented once per draw_hull_proxy() CALL (not per
    // glDrawElements inside it) — the ONE place either render() or
    // draw_instance() actually submits an instance's geometry.
    std::size_t draw_calls_ = 0;

    // See shell_draw_calls(). Incremented once per draw_interior_shell() CALL.
    std::size_t shell_draw_calls_ = 0;
};

}  // namespace renderer
