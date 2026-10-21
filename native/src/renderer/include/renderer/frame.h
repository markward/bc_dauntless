// native/src/renderer/include/renderer/frame.h
#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <map>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <array>

#include <scenegraph/instance.h>

#include <assets/decal_override.h>

#include <renderer/shadow_light.h>
#include <renderer/plating_damage.h>
// draw_model takes a voxel::VoxelVolume* and CarveFieldCache's nested
// constants, so the forward declaration below is not enough on its own.
#include <renderer/carve_field_cache.h>
#include <renderer/hull_interior_pass.h>
#include <renderer/hull_interior_policy.h>
// draw_model takes a const InstanceFieldCache::Entry* -- a nested type, so
// (like CarveFieldCache above) the forward declaration below is not enough.
#include <renderer/instance_field_cache.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; enum class Pass : std::uint8_t;
                       class DamageDecalRing; }
namespace renderer { class Pipeline; class Shader; class CarveFieldCache;
                     class InstanceFieldCache; }
namespace renderer::planet_detail { class PlanetDetailPass; }

namespace renderer {

struct Lighting {
    static constexpr int MaxDirectionals = 4;
    /// Combined color × dimmer, applied as a uniform additive term.
    glm::vec3 ambient = glm::vec3(0.1f);
    /// 0..MaxDirectionals; values past `directional_count` are ignored.
    int directional_count = 1;
    /// Direction TOWARD the light source, world space, normalized.
    glm::vec3 directional_dir_ws[MaxDirectionals] = {
        glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f))
    };
    /// Color × dimmer per directional.
    glm::vec3 directional_color[MaxDirectionals] = { glm::vec3(1.0f) };

    /// RESOLVED directional-ambient axis and strength -- already reduced from
    /// the directionals by ambient_gradient_from_lights. Stored resolved, not
    /// as a budget, because the draw path must not run that reduction:
    /// submit_opaque_instance is called PER INSTANCE, so computing there
    /// would repeat it for every ship every frame. The host resolves it once
    /// per frame in set_lighting (Task 3).
    ///
    /// ambient_gradient == 0 is the stock flat ambient, byte-identical.
    glm::vec3 ambient_dir_ws = glm::vec3(0.0f, 1.0f, 0.0f);
    float     ambient_gradient = 0.0f;
};

enum class BackdropKind { Star, Backdrop };

struct Backdrop {
    /// Source descriptor; matched against the renderer's per-texture
    /// cache. The renderer uploads on first sight and reuses thereafter.
    std::string texture_path;
    BackdropKind kind = BackdropKind::Star;
    float h_tile = 1.0f;
    float v_tile = 1.0f;
    float h_span = 1.0f;
    float v_span = 1.0f;
    glm::mat3 world_rotation = glm::mat3(1.0f);
    int target_poly_count = 256;
    // Procedural sky (Modern VFX). Ignored when the procedural toggle is off.
    int   proc_kind = 0;        // 0 = stars, 1 = starcloud (galaxy), 2 = nebula
    glm::vec3 color = glm::vec3(0.5f);  // recorded dominant colour, 0..1
    float coverage = 0.4f;      // density 0..1
    float seed = 0.0f;          // per-backdrop stable seed
    // 1 when the camera is inside this feature's sphere: the shader drops its
    // angular patch-cap and fills the whole sky instead of discarding the far
    // hemisphere (which made enveloping nebulae vanish from the inside).
    int   envelop = 0;
};

struct SunDescriptor {
    glm::vec3   position;                  // render-space center (host_loop pushes via to_view_render)
    float       radius        = 1.0f;      // body sphere radius (BC units)
    std::string base_texture_path;
    float       corona_radius = 0.0f;      // 0 = no corona; draw when > radius
    std::string flare_texture_path;        // empty = skip the SunEffect overlay
};

struct LensFlareElement {
    int         wedges       = 8;
    std::string texture_path;
    float       position     = 0.0f;   // 0=at source, 1=screen center, 2=opposite
    float       size         = 0.1f;   // fraction of viewport height
    float       freq         = 0.0f;   // Hz wobble
    float       amp          = 0.0f;   // wobble amplitude (size multiplier delta)
};

struct LensFlareDescriptor {
    glm::vec3                       source_world_pos;
    std::vector<LensFlareElement>   elements;
    // Eye->star transmittance from the system-scale nebula pass (spec
    // 2026-09-29, "The sun and its flares"): the billboard flare's
    // visibility is one depth read that can't see fog, so it takes the
    // exact ray transmittance as a brightness multiplier. 1.0 = untouched.
    float                            brightness = 1.0f;
};

/// Projectile render descriptor, covering BOTH BC projectile families
/// (weapon-firing-mechanics.md §5.5). Populated from the SDK projectile
/// script's CreateTorpedoModel / CreateDisruptorModel call
/// (sdk/Build/scripts/Tactical/Projectiles/*.py):
///   - Torpedo-style: renderer composites three additive textured billboards
///     (glow + flares + core) at world_pos each frame, animated per the
///     audited layer sizes. Sizes are world-units half-sizes per layer.
///   - Disruptor-style (`is_disruptor`): a two-color tapered tube bolt
///     aligned to `forward` (the unit velocity direction), built from
///     `shell_color`/`bolt_core_color`/`bolt_length`/`bolt_width` instead of
///     the textured quad layers.
/// Every descriptor carries both families' fields; the family not in use
/// carries its inert defaults (empty texture paths / zero sizes for a
/// disruptor bolt, forward=(0,0,1) and zero bolt length/width for a torpedo).
struct TorpedoDescriptor {
    glm::vec3   world_pos;
    std::string core_texture;
    glm::vec4   core_color   = glm::vec4(1.0f);
    float       core_size_a  = 0.0f;
    float       core_size_b  = 0.0f;
    std::string glow_texture;
    glm::vec4   glow_color   = glm::vec4(1.0f);
    float       glow_size_a  = 0.0f;
    float       glow_size_b  = 0.0f;
    float       glow_size_c  = 0.0f;
    std::string flares_texture;
    glm::vec4   flares_color = glm::vec4(1.0f);
    int         num_flares   = 0;
    float       flares_size_a = 0.0f;
    float       flares_size_b = 0.0f;
    float       age           = 0.0f;
    int         id            = 0;       // stable per-projectile id; seeds per-flare randomness
    bool        is_disruptor  = false;
    glm::vec3   forward{0.0f, 0.0f, 1.0f};       // unit velocity direction (disruptor bolt alignment)
    glm::vec4   shell_color{1.0f};               // disruptor outer shell color
    glm::vec4   bolt_core_color{1.0f};           // disruptor inner core color
    float       bolt_length = 0.0f;              // GU
    float       bolt_width  = 0.0f;              // GU
};

/// One world-space dynamic light (point or segment). A point light is a
/// degenerate segment (pos_a == pos_b). Consumed by the opaque Space pass
/// only; no shadow interaction. First consumer: torpedo glow
/// (weapon-firing-mechanics.md §5.5 — BC torpedoes light the ships they
/// fly past); future: hardpoint-attached point/line lights.
struct DynamicLightDescriptor {
    glm::vec3 pos_a{0.0f};       // world GU; point position or segment end A
    glm::vec3 pos_b{0.0f};       // == pos_a for point lights
    glm::vec3 color{1.0f};       // linear RGB (HDR-capable)
    float     radius    = 0.0f;  // GU; attenuation reaches exactly 0 here
    float     intensity = 1.0f;  // scalar multiplier on color
    glm::vec3 direction{0.0f};       // cone forward axis (world, unit); ignored if not a cone
    float     spot_tan_x = -1.0f;    // < 0 => not a cone. tan(half-angle) along `right` (= radius/length).
    glm::vec3 up{0.0f, 1.0f, 0.0f};  // cone up axis (world, unit) — orients the ellipse
    float     spot_tan_y = -1.0f;    // tan(half-angle) along `up` (= radius_y/length)
    /// Attachment. {0,0} (the default) means every position/direction above
    /// is already WORLD space. Set => pos_a, pos_b, direction and up are the
    /// instance's BODY frame in unscaled GU, and frame() resolves them to
    /// world through inst->world via resolve_attached_dynamic_lights before
    /// any draw reads the list (same pattern as ParticleEmitterDescriptor).
    scenegraph::InstanceId instance_id{};
};
inline constexpr int kMaxDynamicLightsPerFrame = 64;
inline constexpr int kMaxDynamicLightsPerDraw  = 4;

// One warp-core breach shockwave: a camera-facing ring + core flash centered
// at world_center, expanding to max_radius over lifetime. age/lifetime drive
// the shader animation (same age-based shape as TorpedoDescriptor).
struct ShockwaveDescriptor {
    glm::vec3 world_center;
    float max_radius;
    float age;
    float lifetime;
    glm::vec3 tint{1.0f};   // ring colour multiplier; white = default look (spec 2026-10-16 §7.5)
};

/// Hit-VFX render descriptor.  Engine ages each entry; renderer dispatches
/// per-tier constants (HULL / CRITICAL) based on `severity`.  `surface_normal`
/// is (0,0,0) when no mesh trace was available (sentinel = no normal).
struct HitVfxDescriptor {
    glm::vec3 world_pos;
    glm::vec3 surface_normal{0.0f};   // (0,0,0) sentinel = no normal
    float     age      = 0.0f;
    int       severity = 1;           // 1=HULL, 2=CRITICAL; SHIELD never reaches here
    // Hull anchor. Both the flash billboard and the spark burst resolve
    // against it (see hit_vfx_anchor_point) so the impact rides the hull
    // instead of being left behind in world space. body_point defaults to the
    // model origin, which is a legitimate value, so presence needs its own
    // flag rather than a sentinel.
    bool      has_body_anchor = false;
    scenegraph::InstanceId instance_id{};  // default {0,0}
    glm::vec3 body_point{0.0f};       // impact in ship body frame (model units)
    glm::vec3 body_normal{0.0f};      // surface normal, body frame
    int       weapon_kind = 1;        // 0=phaser (cool/tight), 1=torpedo (hot/wide), 2=rock dust (grey, spherical; world-anchored w/o instance)
    int       spark_count = 0;
};

/// One keyframe. Colour keys use (r,g,b); alpha/size keys use `v` only.
struct ParticleKey {
    float t = 0.0f;
    float v = 0.0f;            // alpha or size
    float r = 0.0f, g = 0.0f, b = 0.0f;  // colour keys only
};

/// A single analytic particle emitter. The renderer derives every live
/// particle's state from these fields + the per-particle hash; there is no
/// per-particle state anywhere. See particle_math.h for the model.
struct ParticleEmitterDescriptor {
    scenegraph::InstanceId instance_id{};   // {0,0} sentinel => unattached
    glm::vec3 emit_pos{0.0f};               // body-frame if attached, world if not
    glm::vec3 emit_dir{0.0f, -1.0f, 0.0f};  // body-frame if attached, world if not
    glm::vec3 emit_vel_world{0.0f};         // ship world velocity (already world)
    float inherit            = 1.0f;        // SetInheritsVelocity fraction [0,1]
    float emit_velocity      = 1.0f;
    float angle_variance     = 0.0f;        // degrees
    float emit_life          = 1.0f;
    float emit_life_variance = 0.0f;
    float emit_frequency     = 0.05f;
    float effect_age         = 0.0f;
    float stop_age           = 1.0e30f;     // emission cutoff (EffectLifeTime / explicit stop)
    int   draw_old_to_new    = 1;
    int   num_color_keys = 0; ParticleKey color_keys[8];
    int   num_alpha_keys = 0; ParticleKey alpha_keys[8];
    int   num_size_keys  = 0; ParticleKey size_keys[8];
    std::string texture_path;               // CreateTarget path; pass caches by string
    // A2 explosion extensions (all default to A1 behaviour when zero):
    int   blend_mode             = 0;       // 0 = alpha (A1 default), 1 = additive
    float emit_radius            = 0.0f;    // particles born within this sphere radius
    float random_velocity_cone   = 0.0f;    // degrees; 180 = full sphere
    float random_velocity_speed  = 0.0f;    // 0 = no random velocity (A1)
    float damping     = 0.0f;   // velocity decay rate; 0 = linear (A1/A2)
    float tail_length = 0.0f;   // streak length multiplier; 0 = camera-facing billboard
    // Billboard tumble, radians/sec. Sign and magnitude are randomised per
    // particle so a cloud spins every which way. 0 (the default) still gives
    // each particle a FIXED random roll — enough to stop N copies of one sprite
    // reading as a repeating stamp — it just doesn't animate.
    float roll_rate   = 0.0f;
    // Texture-sheet animation: texture is an atlas_cols x atlas_rows grid.
    // 1x1 (default) = whole texture. >1 => per-particle cell (frame from age
    // along the columns, variant row from a per-particle hash).
    int   atlas_cols = 1;
    int   atlas_rows = 1;
    // Stable per-emitter hash seed in [0,1). ALL per-particle randomness
    // (jitter, birth offset, variant row) derives from this — never from the
    // emitter's world position, which moves with an attached ship and would
    // re-roll every particle each frame (teleporting/flickering puffs).
    float seed = 0.0f;
    // Sprite-library playback (spec 2026-10-16 §7.4). 0 = life_columns
    // (today: frame along the columns over life, random variant row);
    // 1 = life_sequence (whole sheet row-major over life); 2 = loop (random
    // variant row, columns cycle at `fps` from a random start).
    int       playback = 0;
    float     fps      = 0.0f;
    // Quad anchor in corner units: (0,0) = centred (today); (0,-1) puts the
    // quad's bottom-centre on the emit point.
    glm::vec2 pivot{0.0f};
    // 0 = camera-facing (today); 1 = stretched along the emit direction
    // (streak path, length = particle size).
    int       orient   = 0;
};

/// Phaser-beam render descriptor.  One entry per concentric beam layer
/// emitted by an actively-firing PhaserBank: rendered as an additive
/// N-sided prism extruded from emitter_world to target_world with
/// endpoint taper.
struct PhaserBeamDescriptor {
    glm::vec3 emitter_world;
    glm::vec3 target_world;
    glm::vec4 color;     // RGBA additive tint
    float     width;     // mid-beam half-width (= SDK MainRadius)
    float     u_tiles;   // texture repeats along beam length
    // BC-faithful geometry (SDK names retained):
    int       num_sides;        // SetNumSides — prism side count
    float     taper_radius;     // SetTaperRadius — half-width at endpoints
    float     taper_ratio;      // SetTaperRatio — fraction of length used for taper
    float     taper_min_length; // SetTaperMinLength
    float     taper_max_length; // SetTaperMaxLength
    float     perimeter_tile;   // SetPerimeterTile — V-axis texture repeats around prism
    float     texture_speed;    // SetTextureSpeed — U-axis scroll wu/sec
    float     end_width_scale = 1.0f;  // radius multiplier at the target end
                                       // (1.0 = uniform; tractors funnel out)
};

/// SPIKE (damage redesign): what a plating draw uploads per mesh. `parts` is
/// the hull's structure parts exactly as the subsets were computed with them
/// (structure_parts_for, read ONCE by the caller: they land on a worker at any
/// moment, and the shader must see the parts the cull margins assumed).
/// `subsets`: one plating::MeshRecordSubset per model.meshes entry, or nullptr
/// for the whole list on every mesh.
struct PlatingMeshRecords {
    const std::vector<voxel::StructurePart>* parts = nullptr;
    const std::vector<plating::MeshRecordSubset>* subsets = nullptr;
};

/// Draw a single model instance. Picks the skinned program when the model has
/// a skeleton AND a non-empty bone palette is supplied; otherwise draws through
/// the static `shader` byte-identically to the pre-skinning path. Declared here
/// so offscreen render tests can drive it with a controllable palette.
void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                Shader& skinned_shader,
                std::uint32_t white_fallback,
                std::uint32_t black_fallback,
                float rim_strength,
                const scenegraph::DamageDecalRing& decals,
                const std::array<scenegraph::Instance::GlowRegion,
                                 scenegraph::Instance::kMaxGlowRegions>& glow_regions,
                float decal_time,
                float emissive_scale,
                const std::vector<glm::mat4>& bone_palette,
                const scenegraph::HullCarveField& carve,
                const std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw>&
                    dyn_lights = {},
                int dyn_light_count = 0,
                const voxel::VoxelVolume* carve_fill = nullptr,
                bool carve_invert = false,
                // Per-instance hull distance field (hull-volume-field-
                // transport, Task 5): nullptr is BOTH an undamaged instance
                // (InstanceFieldCache has no entry for it) and the default
                // for every call site below until a resolved Entry is
                // threaded in -- either way u_hull_field_enabled stays 0 and
                // opaque.frag takes its documented zero-cost stock path.
                const InstanceFieldCache::Entry* hull_field = nullptr,
                // Per-instance ARTICULATED node locals (BoP wings): node index
                // -> replacement local transform, exactly the map the bridge
                // pass already consumes. nullptr or an empty map takes the
                // static node walk, which compose_node_worlds reproduces
                // byte-for-byte -- so an unarticulated hull is unchanged.
                const std::unordered_map<int, glm::mat4>* node_overrides = nullptr,
                // Per-instance hull-decal override (set_instance_decal_override):
                // when non-null its list REPLACES model.decals for this draw,
                // with its own per-mesh enable masks. nullptr = the baked list.
                const assets::DecalOverride* decal_override = nullptr,
                // Planet geosphere (spec 2026-10-06 §4.3): index into
                // Model::sphere_map->lods for this camera, from
                // geosphere_level_for. -1 (or a model without sphere_map)
                // draws BC's own mesh, byte-identically.
                int sphere_level = -1,
                // Planet surface atmosphere (spec 2026-10-07 §6): applied only
                // to the sphere-mapped mesh when non-null AND enabled; every
                // other draw sets u_atmo_enabled = 0. atmo_sun_dir is the
                // world-space unit direction toward the planet's sun.
                const scenegraph::Instance::Atmosphere* atmo = nullptr,
                glm::vec3 atmo_sun_dir = glm::vec3(0.0f),
                // SPIKE (damage redesign) plating layer: nullptr = a stock
                // draw that touches no plating uniform and never changes
                // culling. Non-null = `shader` is Pipeline::plating_shader()
                // and this list (renderer/plating_damage.h) is uploaded as
                // u_dmg_*; the draw stays front-faces-only (a cut shows the
                // interior pass's decks and rooms, not the hull's inside
                // face). Ignored for a skinned draw (the skinned
                // program has no plating layer). Always a colour draw
                // (u_plating_mark = 0): submit_plating_interior marks through
                // frame.cc's lean draw_plating_mark instead.
                const plating::DamageList* plating = nullptr,
                // Far hull (InteriorPolicy, hull_interior_policy.h): no rooms
                // behind its holes, so the program paints a hole as wreckage
                // instead of cutting it, unless it is blown clear through
                // (u_plating_far). Plating draws only.
                bool plating_far = false,
                // Plating draws only: the parts and per-mesh record subsets
                // (PlatingMeshRecords; FrameSubmitter caches them per
                // instance). With subsets each mesh uploads only its own
                // records (plating::mesh_record_subsets); a mesh with none
                // uploads u_dmg_count 0 and still draws. nullptr = the parts
                // read here and the whole list; null subsets, node overrides
                // present (the posed meshes leave their rest boxes) or the
                // geosphere's substituted mesh: every mesh gets the whole list.
                const PlatingMeshRecords* plating_mesh_records = nullptr,
                // Plating draws only: the stock program. Non-null with
                // per-mesh subsets (no node overrides, not skinned): a mesh
                // whose subset is empty draws through it, with exactly a
                // stock draw's uniforms, before the rest draw through
                // `shader` (one program switch per instance). nullptr: every
                // mesh draws through `shader` (the force-program probe).
                Shader* stock_shader = nullptr);

/// TEST counters, process-wide and monotonic (read deltas). Computations of
/// a model's per-mesh plating record subsets (plating::mesh_record_subsets),
/// and uploads of a u_dmg_* list to the plating program by a per-mesh draw
/// (an upload equal to the previous one of the same draw is skipped and not
/// counted).
int plating_mesh_subset_computations();
int plating_record_uploads();
/// TEST counters, process-wide and monotonic (read deltas): program binds
/// made by draw_model, and the mesh draws it issued through the plating
/// program (a non-null plating list).
int draw_model_program_binds();
int draw_model_plating_mesh_draws();

/// Per-camera LOD for a sphere-mapped model, or -1 when the model has none.
/// world radius = sphere_map.radius * length(world[0]); focal from proj and
/// the CURRENTLY BOUND viewport height (glGetIntegerv(GL_VIEWPORT)).
int geosphere_level_for(const assets::Model& m, const glm::mat4& world,
                        const scenegraph::Camera& cam);

/// Release the process-lifetime damage-decal texture (game/data/Textures/
/// Effects/Damage.tga) lazily loaded by draw_model, and clear its "tried" flag.
/// MUST be called by shutdown() while the creating GL context is still current:
/// init()/shutdown() destroy and recreate the context per session, and a fresh
/// context reuses GL ids from 1. Without this reset the cached id leaks into the
/// next context, where binding it to GL_TEXTURE_2D collides with a texture that
/// context created as GL_TEXTURE_3D (carve/breach fill) — GL_INVALID_OPERATION
/// (0x502), surfacing later at the next check_gl (e.g. in upload_mesh).
void reset_damage_decal_texture();

/// The framework-lattice stencil (game/data/Textures/Effects/Damage.tga), lazily
/// loaded once per GL session; 0 when game/ is not installed. Exported so the
/// breach pass binds the SAME texture the opaque pass cuts the lattice with --
/// both now run the one shared hull_cut_at(), and that function reads this
/// texture, so a second independently-loaded copy would be a way for the cut
/// and the interior to disagree again.
unsigned int damage_decal_texture();

/// Clear the lazy per-ModelHandle bounding-radius cache used by dynamic-light
/// selection. MUST be called wherever the host clears g_loaded_models (both
/// init() and shutdown() in host_bindings.cc): handle values are recycled —
/// they are derived from g_loaded_models.size(), reissued from 1 after every
/// clear — so without this reset a different model assigned a previously-
/// cached handle silently inherits the OLD model's bounding radius after a
/// mission swap / GL-context recreate. Pure CPU state (no GL objects), so
/// unlike reset_damage_decal_texture() it has no context-currency requirement.
void reset_model_radius_cache();

/// Release the lazily-created GL sampler object the opaque pass binds on
/// texture units 8-11 (one shared sampler, up to 4 distinct decal masks per
/// model, shared by up to 16 placements;
/// clamp-to-edge; the mask texture itself uploads with GL_REPEAT). Same
/// contract as
/// reset_damage_decal_texture(): call while the creating context is current,
/// or the stale sampler id leaks into the next context.
void reset_decal_mask_sampler();

/// Per-instance hull-decal override (set_instance_decals, spec 2026-09-28-
/// spv-decal-editing-design.md §2.5): while set, `ov` REPLACES the instance's
/// model's baked Model::decals in every opaque draw of that instance (an empty
/// list draws no decal). Keyed by the FULL InstanceId, so a recycled index
/// never inherits it. `ov.texture_ids` are borrowed, not owned: the caller
/// (the host's DecalMaskCache) must keep them alive while the override is
/// set, and clear the override before releasing them. Pure CPU state.
void set_instance_decal_override(scenegraph::InstanceId id,
                                 assets::DecalOverride ov);
/// Drop one instance's override (its draws go back to Model::decals). No-op
/// for an id that has none. The host calls this from destroy_instance.
void clear_instance_decal_override(scenegraph::InstanceId id);
/// Drop every override. The host calls this from init() AND shutdown().
void clear_instance_decal_overrides();
/// The instance's override, or nullptr when it draws its baked list.
const assets::DecalOverride* instance_decal_override(scenegraph::InstanceId id);
/// Number of instances with an override (host introspection / tests).
std::size_t instance_decal_override_count();

class FrameSubmitter {
public:
    using ModelLookup = std::function<const assets::Model*(unsigned long long)>;

    FrameSubmitter() = default;
    ~FrameSubmitter();
    FrameSubmitter(const FrameSubmitter&) = delete;
    FrameSubmitter& operator=(const FrameSubmitter&) = delete;

    /// Iterate visible instances in `world` and draw each Mesh with the
    /// opaque shader. Caller is responsible for clearing color + depth and
    /// for swapping buffers afterward.
    void submit_opaque(const scenegraph::World& world,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       const ModelLookup& lookup,
                       const Lighting& lighting,
                       float decal_time = 0.0f,
                       CarveFieldCache* carve_cache = nullptr,
                       const std::vector<DynamicLightDescriptor>* dyn_lights = nullptr,
                       // Per-instance hull field cache (Task 5 plumbing; the
                       // owning cache is constructed and threaded in by
                       // Task 6). nullptr (the default, and every call site
                       // today) keeps every instance on draw_model's stock
                       // hull_field==nullptr path.
                       InstanceFieldCache* field_cache = nullptr);

    /// Like submit_opaque but only iterates instances tagged with `pass`.
    /// Used by the space pass to exclude bridge-tagged geometry, which
    /// is drawn by BridgePass with its own camera and shaders.
    void submit_opaque_in_pass(const scenegraph::World& world,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               const ModelLookup& lookup,
                               const Lighting& lighting,
                               scenegraph::Pass pass,
                               float decal_time = 0.0f,
                               CarveFieldCache* carve_cache = nullptr,
                               float ambient_scale = 1.0f,
                               const std::vector<DynamicLightDescriptor>* dyn_lights = nullptr,
                               InstanceFieldCache* field_cache = nullptr,
                               // The system's suns (spec 2026-10-07 §6): a planet with
                               // an enabled atmosphere takes its surface terminator
                               // and limb sun direction from these, falling back to
                               // directional 0 when nullptr / empty.
                               const std::vector<SunDescriptor>* suns = nullptr,
                               // Planet surface detail (spec 2026-10-08 §5.5):
                               // its target's sphere-LOD draw goes through the
                               // planet_ program with the pass's uniforms; every
                               // other draw (and nullptr) is exactly today's.
                               const planet_detail::PlanetDetailPass* detail = nullptr);

    /// Stamp the stencil buffer with "hull was cut away here", for every
    /// visible instance in `pass` that has active carves.
    ///
    /// Run BETWEEN the opaque hull and the breach scoop. The scoop must appear
    /// only through real holes, never in open space — `discard` writes no
    /// depth, so a hole and empty space look identical from the scoop's side,
    /// and BC's fill mask balloons up to ~3 cells past the hull (39-55% of mask
    /// volume lies outside the hull mesh, measured), which is exactly where the
    /// scoop was left floating free of the ship.
    ///
    /// Draws each carved hull again through opaque.frag with u_carve_invert=1
    /// (keep only what the hull draw discarded) with colour and depth writes
    /// masked off, so the draw contributes nothing but stencil value 1. Depth
    /// TEST stays on, so a cut hidden behind nearer geometry does not stamp.
    /// Restores all GL state it touches. No-op when nothing is carved.
    void submit_carve_stencil(const scenegraph::World& world,
                              const scenegraph::Camera& camera,
                              Pipeline& pipeline,
                              const ModelLookup& lookup,
                              scenegraph::Pass pass,
                              CarveFieldCache* carve_cache,
                              InstanceFieldCache* field_cache = nullptr);

    /// Hull interior under the plating tear. For each visible Space instance
    /// with far_fade < 1, a model, wants_plating and torn_possible (world
    /// order), stamps stencil value 2 + k (k = ordinal; stops after 255)
    /// exactly where the hull is cut through. Value 1 is the old carve's.
    /// Colour and depth writes are off; depth TEST on (GL_LEQUAL). Right
    /// after each marking draw, while params[25] > 0.5, HullInteriorPass
    /// draws that hull's decks and rooms under the value just stamped (fill
    /// from carve_cache->get_for_source; none = rooms without the
    /// left-the-ship test). params[25] <= 0.5 keeps the marking and leaves
    /// the holes see-through. Restores stencil off / mask 0xFF / masks on /
    /// the depth func it found.
    void submit_plating_interior(const scenegraph::World& world,
                                 const scenegraph::Camera& camera,
                                 Pipeline& pipeline,
                                 const ModelLookup& lookup,
                                 CarveFieldCache* carve_cache,
                                 const Lighting& lighting,
                                 float ambient_scale,
                                 float now);

    /// The instance's plating damage list, built from its HullDamageStore.
    /// Cached per instance id; rebuilt only when the store's revision or any
    /// of the plating params differ from the cached copy. Valid until the
    /// next call that can rebuild this instance's entry.
    const plating::DamageList& plating_list_for(const scenegraph::Instance& inst);
    /// How many times plating_list_for rebuilt a list (tests).
    int plating_list_builds() const { return plating_list_builds_; }
    /// Cached lists held (tests). submit_opaque_in_pass drops ids no longer
    /// in its world before it draws.
    std::size_t plating_list_cache_size() const { return plating_list_cache_.size(); }
    /// TEST / DIAGNOSTIC SWITCH, not a quality or perf setting: production
    /// never calls it and nothing should depend on it. Record culling (default
    /// on): each plating mesh draw and marking draw uploads only the records
    /// near that mesh (plating::plating_cull_margin), and the interior walk's
    /// blown tests read only the deck-break subset. Off = the whole list
    /// everywhere: the A/B the tests use to prove culling never changes a
    /// pixel.
    void set_plating_record_culling(bool on) { plating_record_culling_ = on; }

    /// TEST / DIAGNOSTIC SWITCH, like set_plating_record_culling: production
    /// never calls it. Skipping (default on, only with record culling): the
    /// mark and the interior draw no mesh whose record subset is empty -- the
    /// mark would discard every fragment of it, and the interior cannot pass
    /// stencil and depth on it. Off = every mesh: the A/B proving the skip
    /// never changes a pixel. One dev-only exception to byte-identity:
    /// DAUNTLESS_HULL_CARVING=1 with plating on (the old carve / hull-field
    /// discards on a record-free mesh in front of a cut).
    void set_plating_skip_record_free_meshes(bool on) { plating_skip_record_free_ = on; }

    /// Marking draws issued by the last submit_plating_interior.
    int plating_marks_last_frame() const { return plating_marks_last_frame_; }
    /// Mesh draws (glDrawElements) of those marking draws, and of the
    /// interior draws that followed them.
    int plating_mark_mesh_draws_last_frame() const { return plating_mark_mesh_draws_; }
    int plating_interior_mesh_draws_last_frame() const { return plating_interior_mesh_draws_; }

    /// Interior draws (HullInteriorPass::draw) issued by the last
    /// submit_plating_interior: one per marked hull while params[25] > 0.5.
    int plating_interiors_last_frame() const { return plating_interiors_last_frame_; }

    /// Which hulls get rooms in the renders that follow (hull_interior_policy.h).
    /// The host sets it before each render's submits: the viewscreen feed with
    /// its target, the main view with the default.
    void set_interior_policy(const InteriorPolicy& policy) { interior_policy_ = policy; }
    const InteriorPolicy& interior_policy() const { return interior_policy_; }

    /// Plated draws in the last submit_opaque_in_pass whose holes were painted
    /// as far wreckage (u_plating_far = 1) instead of cut for rooms.
    int plating_far_draws_last_frame() const { return plating_far_draws_last_frame_; }

    /// Draw a SINGLE instance (by id) through the full opaque lighting/texture
    /// path, ignoring its visibility flag. Used by the Ship Property Viewer's
    /// hull-texture mode to render just the inspected ship on the isolated
    /// solid background (the space scene is skipped in viewer mode). No-op if
    /// the instance or its model is missing.
    void submit_opaque_instance(const scenegraph::World& world,
                                scenegraph::InstanceId instance_id,
                                const scenegraph::Camera& camera,
                                Pipeline& pipeline,
                                const ModelLookup& lookup,
                                const Lighting& lighting,
                                float decal_time = 0.0f,
                                CarveFieldCache* carve_cache = nullptr,
                                const std::vector<DynamicLightDescriptor>* dyn_lights = nullptr,
                                InstanceFieldCache* field_cache = nullptr);

private:
    /// Lazily-allocated 1x1 white texture used as a fallback when a material
    /// has no Base-stage texture. Keeps the sampler bound to a valid object
    /// so the shader's texture(...) sample returns white instead of black
    /// (the GL "zero texture") and the lighting math actually shows up.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();

    /// Lazily-allocated 1x1 black texture (RGBA 0,0,0,255) used as the
    /// fallback for the Glow stage when a mesh has no glow texture.
    /// Sampling it returns (0,0,0,1) so the glow term contributes nothing.
    std::uint32_t black_texture_ = 0;
    std::uint32_t ensure_black_texture();

    struct InstanceIdLess {
        bool operator()(const scenegraph::InstanceId& a,
                        const scenegraph::InstanceId& b) const {
            if (a.index != b.index) return a.index < b.index;
            return a.generation < b.generation;
        }
    };
    struct PlatingListCacheEntry {
        bool valid = false;
        std::uint32_t revision = 0;
        std::array<float, plating::kParamCount> params{};
        plating::DamageList list;
        // plating::deck_break_subset(list), under the same key.
        plating::DeckBreakSet deck_break;
        // plating::mesh_record_subsets(list, ...), built on first use: valid
        // for this list (cleared on a rebuild) and the parts pointer and
        // model it was built with.
        bool subsets_valid = false;
        const std::vector<voxel::StructurePart>* subsets_parts = nullptr;
        scenegraph::ModelHandle subsets_handle{};
        const assets::Model* subsets_model = nullptr;
        std::vector<plating::MeshRecordSubset> subsets;
        // Per mesh: 1 when its subset holds a record (the interior's mesh
        // mask when record-free meshes are skipped).
        std::vector<std::uint8_t> mesh_has_records;
    };
    /// plating_list_for's entry (list + deck-break subset), rebuilt when stale.
    PlatingListCacheEntry& plating_entry_for(const scenegraph::Instance& inst);
    /// The parts and per-mesh subsets an instance's plating draws upload
    /// (`entry` = its plating_entry_for). Subsets are null with record
    /// culling off or node overrides present; else cached on the entry and
    /// recomputed only when the list, the parts pointer or the model changed.
    PlatingMeshRecords plating_mesh_records_for(PlatingListCacheEntry& entry,
                                                const scenegraph::Instance& inst,
                                                const assets::Model& model);
    std::map<scenegraph::InstanceId, PlatingListCacheEntry, InstanceIdLess> plating_list_cache_;
    int plating_list_builds_ = 0;
    bool plating_record_culling_ = true;

    bool plating_skip_record_free_ = true;
    int plating_marks_last_frame_ = 0;
    int plating_mark_mesh_draws_ = 0;
    int plating_interior_mesh_draws_ = 0;
    int plating_interiors_last_frame_ = 0;
    int plating_far_draws_last_frame_ = 0;
    InteriorPolicy interior_policy_;
    HullInteriorPass hull_interior_;
};

/// Render depth-only for every visible `rim_eligible` caster in `Pass::Space`
/// into the currently-bound depth framebuffer, using the pipeline's
/// `shadow_depth` program and `light.view_proj` as `u_light_view_proj`. The
/// caller must bind the shadow FBO and clear depth first, and restore the
/// previous framebuffer afterward. GL state changed here (cull face, polygon
/// offset, color mask) is restored to the opaque-pass defaults on exit.
void submit_shadow_depth(const scenegraph::World& world,
                         const ShadowLight& light,
                         Pipeline& pipeline,
                         const FrameSubmitter::ModelLookup& lookup);

/// Stash the frame's active shadow (light matrix + depth texture id + on/off)
/// for the opaque pass (Task 6) to sample. Passing `enabled=false` makes the
/// opaque pass treat shadows as absent — the OFF path stays byte-identical.
void set_active_shadow(const ShadowLight& light,
                       std::uint32_t depth_tex,
                       bool enabled);

/// Accessors the opaque pass (Task 6) reads. `active_shadow_enabled()` gates
/// any shadow sampling so the production path is untouched when shadows are off.
const ShadowLight& active_shadow_light() noexcept;
std::uint32_t      active_shadow_texture() noexcept;
bool               active_shadow_enabled() noexcept;

/// Set opaque.frag's three ambient uniforms (u_ambient_light scaled by
/// `ambient_scale`, u_ambient_dir_ws, u_ambient_gradient) on `s`, which must
/// be in use. Every program linked with opaque.frag sets ambient through this
/// one helper (the opaque submit paths and MinorPass).
void set_ambient_uniforms(Shader& s, const Lighting& lighting, float ambient_scale);

}  // namespace renderer
