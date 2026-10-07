// native/src/assets/include/assets/model.h
#pragma once

#include <array>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

namespace assets {

/// A BC `ObjectClass::ReplaceTexture(new, old)` request, baked into a model at
/// build time to render a Federation ship's registry / hull-name. `old_substring`
/// is matched (CASE-SENSITIVE — BC's "ID" tag is uppercase, and a case-fold would
/// also hit "...Bridge...") against each NIF texture's embedded basename;
/// `new_texture` is the replacement TGA, resolved by basename against the
/// model's texture search dirs (case-insensitive) exactly like the NIF's own
/// textures — so a BC-style path that omits the LOD subdir
/// ("FedShips/Dauntless.tga" for a file really in FedShips/High/) still resolves.
/// Participates in the AssetCache key so each distinct registry yields a distinct
/// model variant while same-registry hulls still share one. See model_build.cc
/// `apply_texture_replacements`.
struct TextureReplacement {
    std::string old_substring;
    std::string new_texture;
};

/// A hull-name decal placement, resolved by Python from `decals.json` (see
/// `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md` §3.1) into
/// absolute vectors and a resolved mask path. All vectors are in the
/// SHIP-BODY frame: model space with every NIF node transform applied and
/// the instance's world placement/scale removed -- the same frame
/// `opaque.frag` reconstructs as `p_body`. `origin`, `origin+u_axis` and
/// `origin+v_axis` are the mask rectangle's (0,0), (1,0) and (0,1) corners;
/// `normal` points outward from the hull surface the decal is projected
/// onto; `depth` is the slab half-thickness along `normal` that bounds the
/// projection. `shape` optionally names the NiTriShape (`av.obj.name`) the
/// decal is restricted to: build_model enables it only on meshes built from
/// a shape with that name. EMPTY `shape` => every mesh (still subject to the
/// shader's facing test and depth slab).
struct DecalRequest {
    std::string       shape;
    glm::vec3         origin{0.0f};
    glm::vec3         u_axis{0.0f};
    glm::vec3         v_axis{0.0f};
    glm::vec3         normal{0.0f, 0.0f, 1.0f};
    float             depth = 0.0f;
    std::filesystem::path mask;
};

/// Most hull-decal PLACEMENTS (projectors) one model carries (spec
/// 2026-09-28-spv-decal-editing-design.md §2.4a). Beyond it, the first
/// kMaxDecals are used, with one warning.
inline constexpr int kMaxDecals = 16;
static_assert(kMaxDecals <= 16, "Mesh::decal_mask() is a 16-bit enable mask");
/// Most DISTINCT mask textures one model's placements share. The shader binds
/// them on texture units 8..11 (units 0..7 are taken). Masks dedupe by
/// resolved absolute path (detail::decal_mask_key); a placement that would
/// need a fifth is skipped, with one warning.
inline constexpr int kMaxDecalMasks = 4;

/// One attached hull decal (spec 2026-09-28-spv-decal-editing-design.md
/// §2.4/§2.4a), built by build_model from a DecalRequest. `body_to_mask`
/// maps a ship-body-frame point (the shader's `p_body`) to (u, v, w, 1): u/v
/// are mask texture coordinates, w the signed distance along `normal` from
/// the decal plane (decal_body_to_mask, model_build.h). `normal` is
/// unit-length, body frame; a fragment whose body normal disagrees
/// (dot <= 0) is outside. `depth` bounds |w|. `mask_slot` (0..3) indexes the
/// list's deduplicated masks -- Model::decal_masks for a baked list,
/// DecalOverride::texture_ids for an override -- and is the texture unit
/// 8 + mask_slot the shader samples. Which meshes a decal may paint is
/// Mesh::decal_mask() bit i, for decals[i].
struct ModelDecal {
    glm::mat4 body_to_mask{1.0f};
    glm::vec3 normal{0.0f, 0.0f, 1.0f};
    float     depth = 0.0f;
    int       mask_slot = -1;
};

struct Node {
    std::string       name;
    int               parent_index = -1;
    glm::mat4         local_transform{1.0f};
    std::vector<int>  children;
    std::vector<int>  meshes;
};

/// Per-NiFlipController texture animation. `texture_indices` lists the
/// frames (indices into Model::textures) in cycle order. `delta` is
/// seconds per frame. The renderer pairs this with a wall time via
/// assets::compute_flip_frame_index to pick the active frame each draw.
struct TextureAnimation {
    std::vector<int> texture_indices;
    double           delta       = 0.0;
    double           start_time  = 0.0;
    double           frequency   = 1.0;
    double           phase       = 0.0;
};

/// Geosphere LOD replacement for BC's planet sphere mesh (spec
/// docs/superpowers/specs/2026-10-06-planet-geosphere-design.md §4.2). Built
/// only by apply_geosphere during model construction, from exactly one
/// qualifying mesh (a near-perfect sphere with a UV set). `mesh_index` names
/// the ORIGINAL mesh in Model::meshes, which stays untouched -- it still
/// backs the AABB, ray trace and any other pass keyed on Model::meshes.
/// `lods` is drawn instead, picked per frame by Task 4's draw_model given a
/// sphere_level (kGeosphereLevels index), in place of meshes[mesh_index].
struct SphereMap {
    int mesh_index = -1;              // index into Model::meshes of BC's sphere
    glm::vec3 center_body{0.0f};      // sphere centre, model/body frame
    float radius = 0.0f;              // model units
    std::array<Mesh, 4> lods;         // kGeosphereLevels, coarse -> fine
};

struct Model {
    std::vector<Node>             nodes;
    int                           root_node = 0;
    std::vector<Mesh>             meshes;
    std::vector<Texture>          textures;
    std::vector<Material>         materials;
    Skeleton                      skeleton;
    std::vector<AnimationClip>    animations;
    std::vector<TextureAnimation> texture_animations;
    /// Hull decals, in request order, at most kMaxDecals. Composited in this
    /// order by opaque.frag. Per-mesh enablement is Mesh::decal_mask(); each
    /// mesh records its source shape as Mesh::shape_name().
    std::vector<ModelDecal>       decals;
    /// The decals' distinct masks, at most kMaxDecalMasks: slot s is
    /// Model::textures[decal_masks[s]] (RGB premultiplied by alpha at load),
    /// bound on texture unit 8 + s. ModelDecal::mask_slot indexes this.
    std::vector<int>              decal_masks;
    /// A small (~96) sample of MODEL-SPACE hull surface points, already
    /// transformed out of node-local space (node->model bake applied at load).
    /// Spread across all mesh shapes for whole-hull VFX anchoring (electrical
    /// discharges, wake). Empty for models with no meshes. ~negligible memory.
    std::vector<glm::vec3>        surface_points;
    std::filesystem::path         source;

    /// Index of the first grafted HEAD mesh in `meshes` (-1 if none). Head
    /// meshes are appended last by compose_officer_model, so the head set is
    /// [head_mesh_begin, meshes.size()). Used by the lip-sync face sink to
    /// blend only the head meshes' base texture.
    int                           head_mesh_begin = -1;
    /// Officer FACE-texture set: slot name ("a","e","u","blink1","blink2",
    /// "eyesclosed") -> index into `textures`. Populated by
    /// compose_officer_model from the character's facial images; empty for
    /// non-officer models. "neutral" is implicit (the head's own base texture).
    std::unordered_map<std::string, int> face_textures;

    /// Set only by apply_geosphere, at construction time, on a model whose
    /// single mesh passed the sphere gate (spec §4.2) -- empty for every
    /// other model, including every non-planet NIF and every plain (non-
    /// geosphere) load of a planet NIF. See SphereMap above.
    std::optional<SphereMap>      sphere_map;

    /// Lazily-built, purely DERIVED ray-trace acceleration: the model-space
    /// triangle soup, a BVH over it, and the model AABB. All are functions of
    /// `nodes` + mesh vertices alone -- nothing instance-specific -- but
    /// ray_trace_instance used to rebuild the node-world chain and the AABB on
    /// EVERY call and then test every triangle linearly.
    ///
    /// Measured at 100 ships, before caching: 1.81 ms of setup and 0.55 ms of
    /// triangle loop per trace, over 3,376 triangles, ~21 traces/frame.
    ///
    /// Held HERE, not in a renderer-side map keyed on `const Model*`, so it
    /// cannot outlive its model: a freed model whose address got reused by a
    /// new allocation would otherwise be served the previous model's geometry
    /// -- a wrong-hit-point bug that presents as a physics glitch, not a crash.
    ///
    /// INVALIDATION. There is no invalidation path, and the two inputs that
    /// could need one are NOT node animation. Node animation leaves
    /// `nodes[].local_transform` alone -- renderer/node_anim.cc only READS it
    /// and publishes its results through a separate node_index -> transform
    /// override map (renderer/bridge_node_anim_store.h), which this cache
    /// never consults and which therefore cannot stale it. The two things that
    /// do mutate the cache's actual inputs IN PLACE are:
    ///   * assets::tessellate_model_in_place (assets/src/tessellate.cc) --
    ///     rewrites every mesh's vertices and indices;
    ///   * Mesh::set_cpu_data (assets/include/assets/mesh.h), called from
    ///     tessellate.cc, model_build.cc and model_compose.cc -- replaces a
    ///     mesh's CPU geometry wholesale.
    /// Both run strictly during model CONSTRUCTION -- build_model
    /// (model_build.cc) and compose_officer_model (model_compose.cc) -- i.e.
    /// before the finished Model is published and before any trace can reach
    /// it. That ordering, not any property of the geometry, is what makes the
    /// cache sound. If either mutator ever runs on a live, already-published
    /// model, THIS is what has to be reset (assign a null shared_ptr; the next
    /// trace rebuilds).
    ///
    /// THREADING. `mutable` + lazy assignment from a `const` method means two
    /// threads tracing the same model concurrently would both build and both
    /// write this shared_ptr -- a data race. Tracing is single-threaded today;
    /// making it parallel requires a call_once / atomic here first.
    ///
    /// Opaque (`void`) because the BVH layout is a renderer concern and assets
    /// must not depend on renderer headers; renderer/ray_trace.cc owns the
    /// concrete type and does the cast. shared_ptr, so the lifetime is the
    /// model's with no manual teardown. Mutable + lazy so const trace paths
    /// can fill it on first use.
    mutable std::shared_ptr<void> trace_accel;
};

}  // namespace assets
