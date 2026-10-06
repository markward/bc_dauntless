// native/src/renderer/frame.cc
#include "renderer/frame.h"
#include "renderer/lighting.h"
#include "renderer/pipeline.h"
#include "renderer/bone_palette.h"
#include "renderer/shader.h"
#include "renderer/carve_field_cache.h"
#include "renderer/instance_field_cache.h"
#include "renderer/dynamic_lights.h"
#include "renderer/aabb.h"
#include <renderer/asset_path.h>
#include <renderer/model_draw_helpers.h>
#include <renderer/node_anim.h>
#include <renderer/scuff_texture.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <unordered_map>
#include <vector>

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/hull_carve.h>

#include <assets/flip_frame.h>
#include <assets/geosphere.h>
#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>
#include <assets/material.h>

#include <glm/gtc/matrix_transform.hpp>

#include <array>
#include <vector>

// Toggle for the opaque-pass specular term. Default on so existing
// renders look identical until the user flips the Configuration row.
// host_bindings.cc calls set_enabled(); frame.cc reads enabled() when
// binding the opaque shader and writes u_specular_enabled.
// Always on — specular is core shading, not a preference, so there is no
// user-facing toggle (same call-site-uniformity reason as
// dauntless_hull_damage below).
namespace dauntless_specular {
    bool enabled() { return true; }
}

// Normal mapping (opaque pass). Default on with unit strength: stock BC ships
// no _normal maps at all, so "on" is inert on stock assets and the switch is a
// tuning/AB-comparison aid rather than a fidelity control. strength scales the
// tangent-space xy before renormalising, so 0 collapses to the geometric
// normal exactly.
//
// flip_green defaults to true. Measured
// (TangentBasisConvention.TgaRowZeroIsTheTopOfTheImage): stb_image normalises
// the TGA origin bit, so texture row 0 (v == 0) is always the image's TOP row
// -- v runs DOWNWARD in image space. Flipping green internally is therefore
// what makes a standard OpenGL-convention (+Y up) authored map read correctly
// out of the box; leaving it false would silently require DirectX-convention
// (-Y) maps, contradicting the documented authoring convention. Flip this
// switch off only to accommodate a map that was itself authored -Y.
namespace dauntless_normal_map {
namespace {
    bool  g_enabled    = true;
    float g_strength   = 1.0f;
    bool  g_flip_green = true;
}
    bool  enabled()    { return g_enabled; }
    void  set_enabled(bool v) { g_enabled = v; }
    float strength()   { return g_strength; }
    void  set_strength(float v) { g_strength = v; }
    bool  flip_green() { return g_flip_green; }
    void  set_flip_green(bool v) { g_flip_green = v; }
}

// Developer diagnostic: makes opaque.frag report WHICH shading term went
// non-finite, as a code in the alpha channel, for NonfiniteProbe to read back.
// Off by default -- when off the shader writes the literal alpha 1.0 it always
// has, so the production path is unchanged. Driven from the same Python call
// that enables the probe: the code is only meaningful while the probe runs.
namespace dauntless_nan_debug {
namespace {
    bool g_nan_debug = false;
}
    bool enabled() { return g_nan_debug; }
    void set_enabled(bool v) { g_nan_debug = v; }
}

// Toggle for the opaque-pass Fresnel rim term. Default on so the
// "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; frame.cc reads enabled() per draw when binding the
// opaque shader's u_rim_strength.
namespace dauntless_rim {
namespace {
    bool g_rim_enabled = true;
}
    bool enabled() { return g_rim_enabled; }
    void set_enabled(bool v) { g_rim_enabled = v; }

    // Applied to Instance::rim_strength (SpecularCoef / the 0.1 default)
    // before it reaches the shader: authored values read too bright at
    // face value (tune-by-eye).
    constexpr float kStrengthScale = 0.5f;
    // kStrengthScale for other TUs (constexpr has internal linkage): the
    // minor-rock pass computes its own u_rim_strength (host_bindings.cc).
    float strength_scale() { return kStrengthScale; }
}

// Toggle for the HDR resolve pass (tonemap + bloom + grade). Default on.
// host_bindings.cc forward-declares set_enabled; frame() reads enabled()
// when calling g_resolve_pass->set_hdr_enabled().
namespace dauntless_hdr {
namespace {
    bool g_hdr_enabled = true;
}
    bool enabled() { return g_hdr_enabled; }
    void set_enabled(bool v) { g_hdr_enabled = v; }
}

// Toggle for the image-based ("modern") lens flare (Modern VFX). Default on;
// off = stock BC (the classic per-sun billboard flares, which the host loop
// suppresses while this is on). host_bindings.cc forward-declares set_enabled;
// frame() gates the LensFlareHdrPass + the resolve's lens-flare composite on
// enabled() && dauntless_hdr::enabled() && exterior.
namespace dauntless_hdr_lens_flare {
namespace {
    bool g_enabled = true;
}
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}

// Toggle for sun shadow maps (depth pre-pass + PCF in opaque). Default on.
namespace dauntless_shadows {
namespace {
    bool g_shadows_enabled = true;
}
    bool enabled() { return g_shadows_enabled; }
    void set_enabled(bool v) { g_shadows_enabled = v; }
}

// Directional-ambient strength. Not a player-facing preference yet -- the
// spec defers that until it has been seen in motion -- but reachable so it
// can be calibrated live. Default biased high on purpose (calibrate up,
// then down).
namespace dauntless_ambient_gradient {
    namespace {
        // The tuned "on" value. ONE home for this number: the Python master
        // toggle asks for enabled/disabled and never names a strength, so
        // retuning after a live look is a single-line change here.
        // Tuning history: 0.6 (first pass, biased high) -> 1.0 (Mark asked
        // for +0.5, which the [0,1] clamp put at the ceiling) -> 0.8.
        //
        // The term is 1 + strength*dot(N, dir), so the face pointing exactly
        // AWAY from the light gets 1 - strength. At the 1.0 ceiling that is
        // ZERO ambient: an unlit face goes fully black, which is flatness
        // again, mirrored to the far side -- the opposite of the problem this
        // feature exists to fix. 0.8 keeps most of the swing while leaving
        // the antipode 20% of ambient to hold shape.
        //
        // Above 1.0 the term goes negative and starts subtracting ambient,
        // which is why set_strength clamps.
        constexpr float kTunedDefault = 0.8f;
        float g_strength = kTunedDefault;
    }
    float strength() { return g_strength; }
    void  set_strength(float v) {
        g_strength = (v < 0.0f) ? 0.0f : (v > 1.0f ? 1.0f : v);
    }
    void  set_enabled(bool on) { g_strength = on ? kTunedDefault : 0.0f; }
}

// Toggle for the opaque-pass persistent damage decals (Phase 2). Default on
// so the "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; draw_model reads enabled() per instance and uploads
// u_decal_count = 0 when off (stock-BC hull, no per-fragment decal cost).
// Always on — persistent hull scorch is core damage feedback, switchable
// no more than the hull breaches it accompanies (dauntless_hull_damage).
namespace dauntless_decals {
    bool enabled() { return true; }
}

// Hull-breach renderer pass (carve emission + shader clip). Always on — the
// breach VFX is a core effect with no user-facing toggle (as in stock BC, a
// hull breach was never something you could switch off). enabled() is retained
// as an always-true gate so the pass call sites stay uniform with the other
// VFX passes.
namespace dauntless_hull_damage {
    bool enabled() { return true; }
}

// Toggle for the procedural sky (Modern VFX). Default on; off = stock BC.
namespace dauntless_procedural_sky {
    bool g_procedural_sky_enabled = true;
    bool enabled() { return g_procedural_sky_enabled; }
    void set_enabled(bool v) { g_procedural_sky_enabled = v; }
}

namespace dauntless_filmic {
    bool g_filmic_enabled = true;
    bool enabled() { return g_filmic_enabled; }
    void set_enabled(bool v) { g_filmic_enabled = v; }
    // Ambient light is dimmed to this fraction on the exterior view when filmic
    // is on (the exterior-only scope is enforced at the host call site).
    constexpr float kFilmicAmbientScale = 0.3f;   // -70% ambient on exterior when filmic on
    float ambient_scale() { return g_filmic_enabled ? kFilmicAmbientScale : 1.0f; }
}

// Toggle for Volumetric Nebulae (Modern VFX). Default on; Task 5 wires the
// volumetric render path to this toggle — until then it is state-only.
namespace dauntless_volumetric_nebulae {
namespace { bool g_enabled = true; }
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}

// Toggle for Nebula Lightning (Modern VFX). Default on; wired to the
// lightning render pass when that pass is built.
namespace dauntless_nebula_lightning {
namespace { bool g_enabled = true; }
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}

// Toggle for camera motion blur (Modern VFX). Default on. Exterior-only;
// host_bindings.cc gates on view + a valid previous-frame view-projection.
namespace dauntless_motion_blur {
    bool g_motion_blur_enabled = true;
    bool enabled() { return g_motion_blur_enabled; }
    void set_enabled(bool v) { g_motion_blur_enabled = v; }
}

// Per-frame state channel for the procedural warp flythrough. All three are
// consumed: streak drives the dust pass, flash drives the resolve pass (and,
// on the bridge, the viewscreen feed only), travel_dir orients the streaks.
// There is no enable flag — the cinematic is part of how warp reads, and the
// Python sequence builder decides whether a flythrough happens at all.
namespace dauntless_warp_vfx {
    float     g_streak  = 0.0f;                  // 0..1 star-streak intensity
    float     g_flash   = 0.0f;                  // 0..1 warp-flash intensity
    glm::vec3 g_travel(0.0f, 1.0f, 0.0f);        // world-space travel direction
    float     streak_intensity()  { return g_streak; }
    float     flash_intensity()   { return g_flash; }
    glm::vec3 travel_dir()        { return g_travel; }
    void      set_streak(float v) { g_streak = v; }
    void      set_flash(float v)  { g_flash = v; }
    void      set_travel(glm::vec3 v) { g_travel = v; }
}

// Per-frame state channel for the player's in-system-warp DASH (Set Course /
// heading, in-system-warp spec §4). A single 0..1 intensity — the dust
// pass's smear cap is the only consumer (dust_pass.h:kDashSmearScale). The
// dash draws the real system at real speed (nothing is hidden, no black
// transit), so it does NOT feed dauntless_warp_vfx's streak/travel channel —
// that drives the tunnel's own u_warp_streak drift/prism mode, which a dash
// never uses. The dash's screen flash reuses dauntless_warp_vfx's g_flash
// channel instead (engine/host_loop.py combines both flashes with `max`
// before pushing it), so there is no separate flash channel here.
namespace dauntless_dash_vfx {
    float g_intensity = 0.0f;                    // 0..1 dash intensity
    float intensity()          { return g_intensity; }
    void  set_intensity(float v) { g_intensity = v; }
}

namespace renderer {

namespace {

// Lazily load game/data/Textures/Effects/Damage.tga once per GL session.
// Returns the GL texture id, or 0 if the file is absent (game/ not installed).
// assets::upload_image defaults to GL_REPEAT, which is correct for the tiling
// lattice. The assets::Texture owner is a session-scoped static released by
// reset_damage_decal_texture() in shutdown() — see that function's contract.
unsigned int      g_decal_id    = 0;
bool              g_decal_tried  = false;
assets::Texture   g_decal_owner;     // owns the GL id in g_decal_id

unsigned int ensure_damage_decal_texture() {
    if (g_decal_tried) return g_decal_id;
    g_decal_tried = true;

    constexpr const char* kPath = "data/Textures/Effects/Damage.tga";
    const std::string resolved = resolve_asset_path(kPath);
    std::ifstream in(resolved, std::ios::binary);
    if (!in) {
        // game root not installed — framework will be silently disabled.
        return 0;
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        assets::Image   img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        g_decal_id    = tex.id();
        g_decal_owner = std::move(tex);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[frame] failed to load '%s': %s\n",
                     resolved.c_str(), e.what());
    }
    return g_decal_id;
}

// Hull-name decal masks (Model::decals) are bound on texture units 8..11
// through this sampler object: upload_image leaves every texture GL_REPEAT,
// and a mask must clamp so its edge texels never wrap onto the opposite edge
// of the projector rectangle. Created lazily per GL session; released by
// reset_decal_mask_sampler() with the other session-scoped GL objects.
GLuint g_decal_mask_sampler = 0;

GLuint ensure_decal_mask_sampler() {
    if (g_decal_mask_sampler != 0) return g_decal_mask_sampler;
    glGenSamplers(1, &g_decal_mask_sampler);
    glSamplerParameteri(g_decal_mask_sampler, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glSamplerParameteri(g_decal_mask_sampler, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glSamplerParameteri(g_decal_mask_sampler, GL_TEXTURE_MIN_FILTER,
                        GL_LINEAR_MIPMAP_LINEAR);
    glSamplerParameteri(g_decal_mask_sampler, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    return g_decal_mask_sampler;
}

// First texture unit of the hull-decal masks; decal i binds on unit
// kHullDecalUnit0 + i (units 0..7 are taken by the opaque pass).
constexpr int kHullDecalUnit0 = 8;

// The black fallback texture id currently bound on ALL FOUR decal units
// (8..11), or 0 when unknown / something else is bound there. Lets an
// undecaled draw_model skip rebinding units that already hold the fallback
// -- the overwhelmingly common case. Forgotten whenever that texture may
// have gone away (the FrameSubmitter that owns it is destroyed; the
// session's GL objects are reset). A stale value can only ever leave a unit
// holding NO texture while every u_decal_enabled_mask bit is 0, and
// opaque.frag samples no decal mask then.
GLuint g_decal_units_fallback = 0;

// Per-instance decal overrides (set_instance_decal_override), keyed by the
// full InstanceId (index + generation).
std::unordered_map<std::uint64_t, assets::DecalOverride> g_decal_overrides;

std::uint64_t decal_override_key(scenegraph::InstanceId id) {
    return (static_cast<std::uint64_t>(id.index) << 32) | id.generation;
}

// Bind ONE draw_model's hull-decal list (spec 2026-09-28-spv-decal-editing-
// design.md §2.4a): its up to four DISTINCT masks, mask slot s on unit 8+s
// through the clamp sampler -- once per draw_model however many of the up to
// 16 projectors share them -- plus the projector uniform arrays (with each
// projector's u_decal_slot), the list size and u_ship_world_inv (p_body
// reconstruction; otherwise set only for damaged / glowing / carved
// instances). Unused slots get the black fallback and sampler 0, so every
// declared sampler stays valid and nothing inherits the clamp; the units
// u_decal_mask0..3 name are fixed once, in Pipeline's constructor. Returns
// the bits of the list whose mask slot is bound; each mesh then ANDs its own
// enable mask with it (u_decal_enabled_mask, set per mesh by the caller).
//
// The baked Model::decals and a per-instance override (DecalOverride) both
// come through here -- only the slot lookup differs: `slot_ids[s]` is slot
// s's GL id, 0 for "none" (every decal on that slot is then disabled rather
// than bound). An empty list whose units already hold the fallback costs no
// GL call at all.
using DecalSlotIds = std::array<GLuint, assets::kMaxDecalMasks>;

int bind_hull_decal_list(const Shader& prog,
                         const std::vector<assets::ModelDecal>& decals,
                         const DecalSlotIds& slot_ids,
                         GLuint black_fallback,
                         const glm::mat4& world) {
    const int n = std::min<int>(static_cast<int>(decals.size()),
                                assets::kMaxDecals);
    if (n == 0 && black_fallback != 0 && g_decal_units_fallback == black_fallback)
        return 0;
    bool any_slot_bound = false;
    for (int s = 0; s < assets::kMaxDecalMasks; ++s) {
        const GLuint tex = n > 0 ? slot_ids[static_cast<std::size_t>(s)] : 0u;
        const bool bound = tex != 0;
        any_slot_bound = any_slot_bound || bound;
        glActiveTexture(GL_TEXTURE0 + kHullDecalUnit0 + s);
        glBindTexture(GL_TEXTURE_2D, bound ? tex : black_fallback);
        glBindSampler(kHullDecalUnit0 + s, bound ? ensure_decal_mask_sampler() : 0);
    }
    glActiveTexture(GL_TEXTURE0);  // restore default active unit
    g_decal_units_fallback = any_slot_bound ? 0 : black_fallback;

    int available = 0;
    glm::mat4 proj[assets::kMaxDecals];
    glm::vec3 normal[assets::kMaxDecals];
    float     depth[assets::kMaxDecals] = {};
    GLint     slot[assets::kMaxDecals] = {};
    for (int i = 0; i < assets::kMaxDecals; ++i) {
        proj[i] = glm::mat4(1.0f);
        normal[i] = glm::vec3(0.0f, 0.0f, 1.0f);
        if (i >= n) continue;
        const auto& d = decals[static_cast<std::size_t>(i)];
        const bool slot_ok = d.mask_slot >= 0 && d.mask_slot < assets::kMaxDecalMasks &&
                             slot_ids[static_cast<std::size_t>(d.mask_slot)] != 0;
        if (!slot_ok) continue;
        available |= 1 << i;
        proj[i] = d.body_to_mask;
        normal[i] = d.normal;
        depth[i] = d.depth;
        slot[i] = d.mask_slot;
    }
    prog.set_int("u_hull_decal_count", n);
    if (available != 0) {
        prog.set_mat4("u_ship_world_inv", glm::inverse(world));
        prog.set_mat4_array("u_decal_proj", proj, assets::kMaxDecals);
        prog.set_vec3_array("u_decal_normal", normal, assets::kMaxDecals);
        glUniform1fv(glGetUniformLocation(prog.program(), "u_decal_depth"),
                     assets::kMaxDecals, depth);
        glUniform1iv(glGetUniformLocation(prog.program(), "u_decal_slot"),
                     assets::kMaxDecals, slot);
    }
    return available;
}

// Lazy per-model bounding-radius cache for dynamic-light selection. Mirrors
// the g_decal_id/g_decal_tried lazy-load precedent above: computed once per
// ModelHandle (compute_model_aabb walks every mesh's CPU-data verts, not
// cheap), reused by every instance of that model. Model-local units; the
// caller multiplies by the instance's uniform world scale.
//
// Reset discipline: ModelHandle values are RECYCLED — host_bindings.cc
// derives them from g_loaded_models.size() and .clear()s that table in both
// init() and shutdown(), so after a mission swap / GL-context recreate a
// DIFFERENT model can be reissued a previously-cached handle. The host must
// call reset_model_radius_cache() wherever it clears g_loaded_models
// (mirroring the reset_damage_decal_texture() discipline), or a swapped-in
// model silently inherits the old model's bounding radius.
std::unordered_map<scenegraph::ModelHandle, float> g_model_radius_cache;

float model_bounding_radius(scenegraph::ModelHandle handle,
                            const assets::Model& model) {
    auto it = g_model_radius_cache.find(handle);
    if (it != g_model_radius_cache.end()) return it->second;
    const Aabb box = compute_model_aabb(model);
    const float radius = glm::length(box.half_extents);
    g_model_radius_cache.emplace(handle, radius);
    return radius;
}

// Select up to kMaxDynamicLightsPerDraw lights affecting `inst` from
// `lights` (nullptr or empty => none, count 0 — the production path until
// Task 10 wires a real caller). Instance world center = the world matrix's
// translation column; bounding radius = the per-model cache (model-local
// units) × the instance's uniform world scale, recovered from the world
// matrix's column-0 length (same recovery shield_pass.cc uses for
// SHIP_SCALE — BC models are uniform-scale).
int select_instance_dynamic_lights(
    const scenegraph::Instance& inst, const assets::Model* model,
    const std::vector<DynamicLightDescriptor>* lights,
    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw>& out) {
    if (!model || !lights || lights->empty()) return 0;
    const float model_radius = model_bounding_radius(inst.model_handle, *model);
    const float scale = glm::length(glm::vec3(inst.world[0]));
    const glm::vec3 center_ws = glm::vec3(inst.world[3]);
    return select_dynamic_lights(*lights, center_ws, model_radius * scale, out);
}

}  // namespace

unsigned int damage_decal_texture() { return ensure_damage_decal_texture(); }

void reset_damage_decal_texture() {
    g_decal_owner = assets::Texture{};  // glDeleteTextures in the current context
    g_decal_id    = 0;
    g_decal_tried = false;
}

void reset_model_radius_cache() {
    g_model_radius_cache.clear();
}

void reset_decal_mask_sampler() {
    if (g_decal_mask_sampler != 0) {
        GLuint id = g_decal_mask_sampler;
        glDeleteSamplers(1, &id);
    }
    g_decal_mask_sampler = 0;
    g_decal_units_fallback = 0;  // the next context's units hold nothing yet
}

void set_instance_decal_override(scenegraph::InstanceId id,
                                 assets::DecalOverride ov) {
    g_decal_overrides[decal_override_key(id)] = std::move(ov);
}

void clear_instance_decal_override(scenegraph::InstanceId id) {
    g_decal_overrides.erase(decal_override_key(id));
}

void clear_instance_decal_overrides() { g_decal_overrides.clear(); }

const assets::DecalOverride* instance_decal_override(scenegraph::InstanceId id) {
    auto it = g_decal_overrides.find(decal_override_key(id));
    return it != g_decal_overrides.end() ? &it->second : nullptr;
}

std::size_t instance_decal_override_count() { return g_decal_overrides.size(); }

// The original fill volume for an instance's hull, or nullptr when there is
// nothing to gate with. Skipped for undamaged instances so the common case never
// touches the cache; the cache memoises the decode per hull source.
static const voxel::VoxelVolume* carve_fill_entry(
        CarveFieldCache* cache,
        const assets::Model* model,
        const scenegraph::HullCarveField& carve) {
    if (cache == nullptr || model == nullptr) return nullptr;
    if (carve.count() == 0) return nullptr;
    if (model->source.empty()) return nullptr;
    const voxel::VoxelVolume& v = cache->volume_for_source(model->source);
    return v.occ.empty() ? nullptr : &v;
}

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
                    dyn_lights,
                int dyn_light_count,
                const voxel::VoxelVolume* carve_fill,
                bool carve_invert,
                const InstanceFieldCache::Entry* hull_field,
                const std::unordered_map<int, glm::mat4>* node_overrides,
                const assets::DecalOverride* decal_override,
                int sphere_level) {
    // Pick the program: skinned only when the model carries a skeleton AND a
    // non-empty palette is supplied. An empty palette forces the static branch,
    // which is byte-identical to the pre-skinning path (used by the plumbing
    // test to render a skinned model through the static program).
    const bool skinned = !model.skeleton.bones.empty() && !bone_palette.empty();
    Shader& prog = skinned ? skinned_shader : shader;
    prog.use();
    if (skinned) {
        prog.set_mat4_array("u_bones", bone_palette.data(),
                            static_cast<int>(bone_palette.size()));
    }

    // Whether any decal is active on this draw: the scuff pass then needs
    // each mesh's per-triangle edge directions (unit 7).
    bool decals_present = false;
    // ── Per-instance damage decals (Phase 2) ───────────────────────────────
    // Pack the active ring into vec4 arrays. point_body and radius are both in
    // NIF/model units (damage_decal_add converts radius GU->model before
    // ring.add), so no conversion here. u_decal_count == 0 when disabled or
    // empty makes the shader skip the loop entirely.
    {
        glm::vec4 a[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 b[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 c[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 d[scenegraph::DamageDecalRing::kMaxDecals];   // tangent_body.xyz, _
        int n = 0;
        if (dauntless_decals::enabled()) {
            for (const auto& dec : decals.slots()) {
                if (!dec.active) continue;
                a[n] = glm::vec4(dec.point_body, dec.intensity);
                b[n] = glm::vec4(dec.normal_body, dec.radius);  // already model units
                c[n] = glm::vec4(dec.birth_time,
                                 static_cast<float>(static_cast<std::uint32_t>(dec.weapon_class)),
                                 dec.dent,     // Scuff: 1 impact crumple, 0 grind scratches
                                 0.0f);
                d[n] = glm::vec4(dec.tangent_body, 0.0f);
                ++n;
            }
        }
        prog.set_int("u_decal_count", n);
        decals_present = n > 0;
        if (n > 0) {
            prog.set_vec4_array("u_decal_a", a, n);
            prog.set_vec4_array("u_decal_b", b, n);
            prog.set_vec4_array("u_decal_c", c, n);
            prog.set_vec4_array("u_decal_d", d, n);
            // world->body for the opaque shader's body-frame fragment
            // reconstruction (opaque.frag: p_body / n_body).
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));
            // Body->world rotation (x uniform scale) for the scuff pass's
            // tangent frame; the shader normalises after use.
            prog.set_mat3("u_ship_world_rot", glm::mat3(world));
            prog.set_float("u_decal_time", decal_time);
        }
    }

    // ── Warp-nacelle glow capsules ─────────────────────────────────────────
    // Dim the glow term inside an auto-fitted capsule when a warp pod is
    // disabled. u_glow_region_count == 0 makes the shader skip the loop entirely,
    // keeping the production path byte-identical.
    {
        glm::vec4 na[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nb[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nc[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 nd[scenegraph::Instance::kMaxGlowRegions];
        glm::vec4 ne[scenegraph::Instance::kMaxGlowRegions];   // shape, half_extents.xyz
        glm::vec4 nf[scenegraph::Instance::kMaxGlowRegions];   // box forward.xyz (body space)
        glm::vec4 ng[scenegraph::Instance::kMaxGlowRegions];   // box up.xyz (body space)
        int nn = 0;
        for (const auto& n : glow_regions) {
            if (!n.active) continue;
            na[nn] = glm::vec4(n.center, n.radius);
            nb[nn] = glm::vec4(n.axis, n.aft);
            nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, n.flicker);
            nd[nn] = glm::vec4(n.gain, n.gain_axis.x, n.gain_axis.y, n.gain_axis.z);
            ne[nn] = glm::vec4(n.shape, n.half_extents.x, n.half_extents.y, n.half_extents.z);
            nf[nn] = glm::vec4(n.forward, 0.0f);
            ng[nn] = glm::vec4(n.up, 0.0f);
            ++nn;
        }
        prog.set_int("u_glow_region_count", nn);
        if (nn > 0) {
            prog.set_vec4_array("u_glow_region_a", na, nn);
            prog.set_vec4_array("u_glow_region_b", nb, nn);
            prog.set_vec4_array("u_glow_region_c", nc, nn);
            prog.set_vec4_array("u_glow_region_d", nd, nn);
            prog.set_vec4_array("u_glow_region_e", ne, nn);
            prog.set_vec4_array("u_glow_region_f", nf, nn);
            prog.set_vec4_array("u_glow_region_g", ng, nn);
            // Reuse the decal world->body inverse + clock; set them here too in
            // case this instance has glow regions but no active decals.
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));
            prog.set_float("u_decal_time", decal_time);
        }
    }

    // ── Dynamic lights (torpedo glow; future hardpoint/beam lights) ────────
    // Pack the caller-selected (already top-K'd by frame.cc's submit_opaque)
    // lights into vec4 arrays. u_dyn_light_count == 0 (the default — no
    // caller passes a real list until Task 10) makes the shader skip the
    // loop entirely, mirroring how u_decal_count/u_glow_region_count handle
    // the empty case: set ONLY the count uniform.
    {
        prog.set_int("u_dyn_light_count", dyn_light_count);
        if (dyn_light_count > 0) {
            glm::vec4 la[kMaxDynamicLightsPerDraw];
            glm::vec4 lb[kMaxDynamicLightsPerDraw];
            glm::vec3 lc[kMaxDynamicLightsPerDraw];
            glm::vec4 ld[kMaxDynamicLightsPerDraw];   // dir.xyz, spot_tan_x
            glm::vec4 le[kMaxDynamicLightsPerDraw];   // up.xyz,  spot_tan_y
            for (int i = 0; i < dyn_light_count; ++i) {
                la[i] = glm::vec4(dyn_lights[i].pos_a, dyn_lights[i].radius);
                lb[i] = glm::vec4(dyn_lights[i].pos_b, 0.0f);
                lc[i] = dyn_lights[i].color * dyn_lights[i].intensity;
                ld[i] = glm::vec4(dyn_lights[i].direction, dyn_lights[i].spot_tan_x);
                le[i] = glm::vec4(dyn_lights[i].up,        dyn_lights[i].spot_tan_y);
            }
            prog.set_vec4_array("u_dyn_light_a", la, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_b", lb, dyn_light_count);
            prog.set_vec3_array("u_dyn_light_color", lc, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_dir", ld, dyn_light_count);
            prog.set_vec4_array("u_dyn_light_up",  le, dyn_light_count);
        }
    }

    // ── Hull-breach hole: pure sphere clip ────────────────────────────────
    // Upload the active carve spheres as u_carve_spheres. The opaque.frag
    // shader discards hull fragments inside any active sphere. No fill texture
    // needed — the sphere IS the clip primitive (Path C). u_carve_count == 0
    // disables the clip entirely (stock-BC path).
    {
        if (dauntless_hull_damage::enabled() && carve.count() > 0) {
            // Mirror how the decal block uses DamageDecalRing::kMaxDecals.
            // opaque.frag's `const int MAX_CARVES = 24` must stay in sync with
            // HullCarveField::kMaxCarves; confirm both equal 24 before changing either.
            static constexpr int kMaxCarves =
                static_cast<int>(scenegraph::HullCarveField::kMaxCarves);
            glm::vec4 spheres[kMaxCarves];
            glm::vec3 normals[kMaxCarves];
            int ns = 0;
            for (const auto& s : carve.slots()) {
                if (!s.active) continue;
                if (s.radius <= 0.0f) continue;   // sub-iso accumulation: invisible
                if (ns >= kMaxCarves) break;
                // Backing-material gate: skip a carve the scoop cannot fill.
                if (carve_fill != nullptr &&
                    !carve_has_backing(*carve_fill, s.center_body,
                                       s.surface_normal))
                    continue;
                spheres[ns] = glm::vec4(s.center_body, s.radius);
                normals[ns] = s.surface_normal;
                ++ns;
            }
            // A hull with no baked field has no interior: breach_pass.cc
            // returns early on a null InstanceFieldCache entry. Cutting holes
            // anyway would show space through the ship. "A hole is a hole":
            // if we cannot draw what is behind it, we do not cut it.
            prog.set_int("u_carve_enabled", hull_field != nullptr ? 1 : 0);
            prog.set_int("u_carve_count", ns);
            prog.set_int("u_carve_invert", carve_invert ? 1 : 0);
            if (ns > 0) {
                // Ensure u_ship_world_inv is set (p_body) even if this instance
                // has no decals and no glow regions.
                prog.set_mat4("u_ship_world_inv", glm::inverse(world));
                prog.set_vec4_array("u_carve_spheres", spheres, ns);
                prog.set_vec3_array("u_carve_normals", normals, ns);
            }
        } else {
            prog.set_int("u_carve_enabled", 0);
            prog.set_int("u_carve_count", 0);
            prog.set_int("u_carve_invert", carve_invert ? 1 : 0);
        }

    }

    // ── Per-instance hull distance field (hull-volume-field-transport,
    // Task 5) ────────────────────────────────────────────────────────────
    // Bind the atlas InstanceFieldCache built for this instance, if the
    // caller resolved one. hull_field == nullptr is BOTH an undamaged
    // instance (no entry exists yet) and every call site until the render
    // loop threads a real InstanceFieldCache through FrameSubmitter's
    // field_cache parameter -- either way u_hull_field_enabled=0 keeps
    // opaque.frag on its documented zero-cost branch, so an undamaged ship
    // renders byte-identically to before this feature existed.
    //
    // Unit 6 is free in this pass (0=base, 1=glow, 2=specular, 3=damage
    // decal, 4=normal map, 5=shadow map) and MUST be assigned on every path,
    // enabled or not: an unset sampler uniform defaults to unit 0 in GLSL and
    // would collide with the bound base-colour texture there
    // (GL_INVALID_OPERATION on every draw).
    {
        prog.set_int("u_hull_field", 6);
        prog.set_int("u_hull_field_enabled", hull_field != nullptr ? 1 : 0);
        if (hull_field != nullptr) {
            // u_ship_world_inv (p_body reconstruction) is otherwise only set
            // above when this instance has active carve spheres, decals, or
            // glow regions. An InstanceFieldCache::Entry persists independent
            // of the 24-slot sphere ring, so a field-enabled instance with
            // none of those active would otherwise sample the field through
            // a STALE matrix left by whichever instance drew last -- reading
            // a different ship's body frame. Pre-existing gap in the other
            // three blocks' shared assumption, unreachable before the field
            // existed to be sampled through it.
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));
            glActiveTexture(GL_TEXTURE6);
            glBindTexture(GL_TEXTURE_2D, hull_field->tex2d);
            glActiveTexture(GL_TEXTURE0);  // restore default active unit
            prog.set_vec3("u_hull_field_origin", hull_field->origin);
            prog.set_vec3("u_hull_field_cell",   hull_field->cell);
            prog.set_vec3("u_hull_field_dims",   glm::vec3(hull_field->dims));
            prog.set_vec2("u_hull_field_tiles",
                         glm::vec2(static_cast<float>(hull_field->layout.tiles_x),
                                   static_cast<float>(hull_field->layout.tiles_y)));
            prog.set_vec2("u_hull_field_texel",
                         glm::vec2(1.0f / static_cast<float>(hull_field->layout.width),
                                   1.0f / static_cast<float>(hull_field->layout.height)));
        }
    }

    // ── Skeletal framework lattice (Damage.tga alpha stencil) ─────────────────
    // Bind Damage.tga to texture unit 3 and tell the shader whether the
    // framework is active. Unit 3 is free in this pass (0=base, 1=glow,
    // 2=specular). When the toggle is off, there are no carves, or the texture
    // failed to load, u_frame_enabled=0 → framework skipped (stock path).
    {
        const unsigned int dmg_id = ensure_damage_decal_texture();
        const bool frame_on = (dmg_id != 0)
                              && dauntless_hull_damage::enabled()
                              && (carve.count() > 0);
        glActiveTexture(GL_TEXTURE3);
        glBindTexture(GL_TEXTURE_2D, dmg_id != 0 ? dmg_id : 0);
        prog.set_int("u_damage_decal",  3);
        prog.set_int("u_frame_enabled", frame_on ? 1 : 0);
        glActiveTexture(GL_TEXTURE0);  // restore default active unit
    }

    // Collision-scuff normal map (renderer/scuff_texture.h): resolved ONCE per
    // instance, here, before any mesh binds unit 0. Its first call uploads the
    // map, and upload_image binds the new texture to the ACTIVE unit -- done
    // inside the mesh loop that was unit 0, straight after the mesh's base
    // colour, so the first damaged frame drew one mesh with the normal map as
    // its albedo (FrameTest.LazyScuffMapLoadDoesNotClobberTheBaseTexture).
    // Only fetched when a decal is active so the undamaged path stays
    // byte-identical; 0 => the shader draws scuffs without relief.
    const GLuint scuff_map = decals_present ? ensure_scuff_normal_texture() : 0;

    // ── Sun shadow map (Task 6) ───────────────────────────────────────────
    // Bind the active sun shadow from the Task-5 state. When shadows are off
    // (active_shadow_enabled() == false), only u_shadows_enabled=0 is set and
    // the opaque shader's sun_shadow_factor() returns 1.0 → the lighting math
    // is byte-identical to the pre-shadow path. Unit 5 is free (0=base, 1=glow,
    // 2=specular, 3=damage_decal).
    {
        const bool shadows_on = active_shadow_enabled();
        const int unit = 5;
        prog.set_int("u_shadows_enabled", shadows_on ? 1 : 0);
        // Always assign the shadow sampler its own unit so the sampler2DShadow never collides with the base sampler2D on unit 0 (GL_INVALID_OPERATION), even when shadows are disabled.
        prog.set_int("u_shadow_map", unit);
        if (shadows_on) {
            const ShadowLight& light = active_shadow_light();
            prog.set_mat4("u_light_view_proj", light.view_proj);
            prog.set_float("u_shadow_texel", light.texel_world_size);
            glActiveTexture(GL_TEXTURE0 + unit);
            glBindTexture(GL_TEXTURE_2D, active_shadow_texture());
            glActiveTexture(GL_TEXTURE0);  // restore default active unit
        }
    }

    // Walk nodes; each node may reference one or more meshes by index. The
    // node's local_transform is composed with parent transforms here. The
    // asset pipeline already orders nodes such that parents precede children,
    // so a single linear pass suffices.
    // An articulated instance (BoP wings) supplies replacement node locals;
    // compose_node_worlds runs the identical parent chain with those swapped
    // in, and reproduces the loop below exactly when the map is empty. The
    // empty case still takes the inline walk so the overwhelmingly common
    // path allocates nothing extra.
    std::vector<glm::mat4> world_per_node;
    if (node_overrides != nullptr && !node_overrides->empty()) {
        world_per_node = compose_node_worlds(model, world, *node_overrides);
    } else {
        world_per_node.assign(model.nodes.size(), glm::mat4(1.0f));
        if (!model.nodes.empty()) {
            world_per_node[model.root_node] =
                world * model.nodes[model.root_node].local_transform;
        }
        for (std::size_t i = 0; i < model.nodes.size(); ++i) {
            const auto& node = model.nodes[i];
            if (node.parent_index >= 0) {
                world_per_node[i] =
                    world_per_node[node.parent_index] * node.local_transform;
            }
        }
    }

    // Glow regions are authored in the NIF (rest) frame, but opaque.frag
    // rebuilds a POSED body position. C_i = R_i * P_i^-1 maps it back, for
    // the glow test only. Identity for every node of an unarticulated
    // instance -- computed only when there are overrides, so the common path
    // allocates nothing extra.
    const bool articulated = node_overrides != nullptr && !node_overrides->empty();
    const std::vector<glm::mat4> rest_fix =
        articulated ? rest_corrections(model, *node_overrides)
                    : std::vector<glm::mat4>{};

    // Units 8..11 = the hull-name decal list's mask slots: bound once for the
    // whole model (a per-instance override replaces the baked Model::decals
    // and its Model::decal_masks), then each mesh below sets only its own
    // enable mask.
    DecalSlotIds decal_slot_ids{};
    if (decal_override != nullptr) {
        const auto& ids = decal_override->texture_ids;
        for (std::size_t s = 0; s < decal_slot_ids.size() && s < ids.size(); ++s)
            decal_slot_ids[s] = ids[s];
    } else {
        for (std::size_t s = 0; s < decal_slot_ids.size() && s < model.decal_masks.size(); ++s) {
            const int t = model.decal_masks[s];
            if (t >= 0 && t < static_cast<int>(model.textures.size()))
                decal_slot_ids[s] = model.textures[static_cast<std::size_t>(t)].id();
        }
    }
    const int decals_available = bind_hull_decal_list(
        prog, decal_override != nullptr ? decal_override->decals : model.decals,
        decal_slot_ids, black_fallback, world);

    // Planet geosphere (spec 2026-10-06 §4.3-4.4): the sphere mesh draws the
    // camera's icosphere LOD and opaque.frag derives normal + UV from the
    // body-frame direction to the sphere centre.
    const bool sphere = sphere_level >= 0 && model.sphere_map.has_value();
    if (sphere) {
        prog.set_mat4("u_ship_world_inv", glm::inverse(world));
        prog.set_vec3("u_sphere_center_body", model.sphere_map->center_body);
    }

    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            // Material, textures and decal mask still come from `mesh`; only
            // the geometry is substituted. EVERY draw sets u_sphere_map:
            // uniforms persist, so a skipped 0 would leak 1 onto the next ship.
            const bool this_sphere = sphere && mesh_idx == model.sphere_map->mesh_index;
            const auto& draw_mesh = this_sphere
                ? model.sphere_map->lods[static_cast<std::size_t>(std::clamp(sphere_level, 0, 3))]
                : mesh;
            prog.set_int("u_sphere_map", this_sphere ? 1 : 0);
            // SP2: skinned models carry bind-model verts posed entirely by the
            // bone palette, so the instance world is the model matrix. Static
            // (non-skinned) models keep the node-walk transform.
            prog.set_mat4("u_model", skinned ? world : world_per_node[i]);
            // EVERY draw sets it, identity included: a uniform keeps its value
            // between draws, so skipping the identity would leak the previous
            // articulated ship's correction onto this one. Skinned draws are
            // posed by the bone palette, not by node overrides: identity.
            prog.set_mat4("u_node_rest_fix",
                          (!skinned && articulated) ? rest_fix[i] : glm::mat4(1.0f));

            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            prog.set_vec3("u_diffuse_color", mat.diffuse);
            prog.set_vec3("u_emissive_color", mat.emissive);
            // Self-illumination scale (1 = normal, 0 = destroyed/dark hull).
            prog.set_float("u_emissive_scale", emissive_scale);

            // NiFlipController frames (CGSovereign's bussard collectors)
            // ride on decal_time, which is GetGameTime() from the host
            // loop — the same clock the bridge pass feeds its LCARS, so
            // the frames freeze under pause. Static materials get their
            // Base back unchanged.
            const int base_tex = assets::animated_base_texture(
                model, mat, static_cast<double>(decal_time));
            glActiveTexture(GL_TEXTURE0);
            if (base_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, white_fallback);
            }
            prog.set_int("u_base_color", 0);

            const int glow_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Glow)
            ].texture_index;
            glActiveTexture(GL_TEXTURE1);
            if (glow_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[glow_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            prog.set_int("u_glow_map", 1);

            // Opaque-pass texture-unit convention: 0 = base, 1 = glow,
            // 2 = specular mask. Each unit owns one sampler uniform.
            //
            // Spec contribution is gated on presence of a _specular/_spec
            // texture: missing -> black_fallback -> spec term multiplies
            // to zero -> ship renders identically to today. This is
            // intentional (see specular-rendering-design.md "Scope
            // decision"). Stock BC ships all author non-zero
            // NiMaterialProperty.specular/glossiness; flipping the
            // fallback to white_fallback would shift the visual baseline
            // of every existing ship in one change.
            const int spec_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Gloss)
            ].texture_index;
            glActiveTexture(GL_TEXTURE2);
            if (spec_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[spec_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            prog.set_int  ("u_specular_map",   2);
            prog.set_vec3 ("u_specular_color", mat.specular);
            prog.set_float("u_specular_power",
                renderer::glossiness_to_specular_power(mat.glossiness));
            prog.set_int("u_specular_enabled",
                           dauntless_specular::enabled() ? 1 : 0);
            prog.set_int("u_nan_debug",
                           dauntless_nan_debug::enabled() ? 1 : 0);
            prog.set_float("u_rim_strength", rim_strength);

            // Unit 4 = tangent-space normal map (0 base, 1 glow, 2 specular,
            // 3 damage decal, 5 shadow). u_normal_enabled gates the sample, so
            // the fallback bound when a material has no Bump texture is never
            // read; black_fallback keeps the sampler valid regardless.
            const int bump_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Bump)
            ].texture_index;
            glActiveTexture(GL_TEXTURE4);
            if (bump_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[bump_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            glActiveTexture(GL_TEXTURE0);  // restore default active unit
            prog.set_int  ("u_normal_map", 4);
            prog.set_int  ("u_normal_enabled",
                (bump_tex >= 0 && dauntless_normal_map::enabled()) ? 1 : 0);
            prog.set_float("u_normal_strength", dauntless_normal_map::strength());
            prog.set_int  ("u_normal_flip_g",
                dauntless_normal_map::flip_green() ? 1 : 0);

            // Collision-scuff normal map on unit 7 (assigned once in
            // Pipeline's constructor); resolved per instance above.
            glActiveTexture(GL_TEXTURE7);
            glBindTexture(GL_TEXTURE_2D, scuff_map);
            glActiveTexture(GL_TEXTURE0);  // restore default active unit
            prog.set_int("u_scuff_map_ok", scuff_map != 0 ? 1 : 0);

            // This mesh's shape-derived decal enable mask (an override
            // carries its own, one per Model::meshes entry).
            std::uint16_t mesh_decals = mesh.decal_mask();
            if (decal_override != nullptr) {
                const auto m = static_cast<std::size_t>(mesh_idx);
                mesh_decals = m < decal_override->mesh_masks.size()
                    ? decal_override->mesh_masks[m] : std::uint16_t{0};
            }
            prog.set_int("u_decal_enabled_mask", mesh_decals & decals_available);

            glBindVertexArray(draw_mesh.vao());
            glDrawElements(GL_TRIANGLES, draw_mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
    // Never leak the decal clamp to a later pass (mask units 8-11 only).
    for (int i = 0; i < assets::kMaxDecalMasks; ++i)
        glBindSampler(kHullDecalUnit0 + i, 0);
}

int geosphere_level_for(const assets::Model& m, const glm::mat4& world,
                        const scenegraph::Camera& cam) {
    if (!m.sphere_map) return -1;
    GLint vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp);
    const float focal_px = cam.proj_matrix()[1][1] * 0.5f * static_cast<float>(vp[3]);
    const float scale = glm::length(glm::vec3(world[0]));
    const glm::vec3 c = glm::vec3(world * glm::vec4(m.sphere_map->center_body, 1.0f));
    // world is render-space (camera-relative origin) and so is the eye.
    const glm::vec3 eye = glm::vec3(glm::inverse(cam.view_matrix())[3]);
    return assets::pick_geosphere_level(m.sphere_map->radius * scale,
                                        glm::length(eye - c), focal_px);
}

FrameSubmitter::~FrameSubmitter() {
    if (white_texture_ != 0) {
        GLuint t = white_texture_;
        glDeleteTextures(1, &t);
        white_texture_ = 0;
    }
    if (black_texture_ != 0) {
        // Deleting it unbinds it from units 8..11: forget that they held it.
        if (g_decal_units_fallback == black_texture_) g_decal_units_fallback = 0;
        GLuint t = black_texture_;
        glDeleteTextures(1, &t);
        black_texture_ = 0;
    }
}

std::uint32_t FrameSubmitter::ensure_white_texture() {
    if (white_texture_ != 0) return white_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t white[4] = {255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    white_texture_ = t;
    return white_texture_;
}

std::uint32_t FrameSubmitter::ensure_black_texture() {
    if (black_texture_ != 0) return black_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t black[4] = {0, 0, 0, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, black);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    black_texture_ = t;
    return black_texture_;
}

// Sets the three ambient uniforms together. One helper rather than three
// copies: u_ambient_light is set at three sites (submit_opaque,
// submit_opaque_in_pass, submit_opaque_instance) and adding the gradient
// uniforms by hand at each invites updating only some of them. External
// linkage (declared in frame.h) so MinorPass, which draws through the same
// opaque.frag, sets them through this one helper too.
void set_ambient_uniforms(Shader& s, const Lighting& lighting,
                          float ambient_scale) {
    s.set_vec3 ("u_ambient_light",    lighting.ambient * ambient_scale);
    s.set_vec3 ("u_ambient_dir_ws",   lighting.ambient_dir_ws);
    s.set_float("u_ambient_gradient", lighting.ambient_gradient);
}

void FrameSubmitter::submit_opaque(const scenegraph::World& world,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline,
                                   const ModelLookup& lookup,
                                   const Lighting& lighting,
                                   float decal_time,
                                   CarveFieldCache* carve_cache,
                                   const std::vector<DynamicLightDescriptor>* dyn_lights,
                                   InstanceFieldCache* field_cache) {
    // Per-frame uniforms common to the static AND skinned programs (view/proj,
    // camera, ambient, directional lights). The skinned vertex stage pairs with
    // opaque.frag, so the fragment-side uniforms are identical; applying the
    // same values to both keeps a skinned draw shaded identically to a static
    // one. The set + order on the static program is unchanged from before.
    auto configure_common = [&](Shader& s) {
        s.use();
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());

        const glm::vec3 cam_pos_ws =
            glm::vec3(glm::inverse(camera.view_matrix())[3]);
        s.set_vec3("u_camera_pos_ws", cam_pos_ws);

        set_ambient_uniforms(s, lighting, 1.0f);
        s.set_int("u_dir_light_count", lighting.directional_count);
        if (lighting.directional_count > 0) {
            s.set_vec3_array("u_dir_light_dir_ws",
                             lighting.directional_dir_ws,
                             lighting.directional_count);
            s.set_vec3_array("u_dir_light_color",
                             lighting.directional_color,
                             lighting.directional_count);
        }
    };

    auto& shader = pipeline.opaque_shader();
    configure_common(shader);
    configure_common(pipeline.skinned_shader());

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        const float rim_strength =
            (dauntless_rim::enabled() && inst.rim_eligible)
                ? inst.rim_strength * dauntless_rim::kStrengthScale : 0.0f;
        std::vector<glm::mat4> palette;
        if (m && !m->skeleton.bones.empty())
            palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
        std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> lights{};
        const int light_count =
            select_instance_dynamic_lights(inst, m, dyn_lights, lights);
        const InstanceFieldCache::Entry* field_entry =
            field_cache != nullptr ? field_cache->get(inst.id) : nullptr;
        if (m) draw_model(*m, inst.world, shader, pipeline.skinned_shader(),
                          white, black, rim_strength,
                          inst.decals, inst.glow_regions, decal_time,
                          inst.emissive_scale, palette, inst.carve,
                          lights, light_count,
                          carve_fill_entry(carve_cache, m, inst.carve),
                          /*carve_invert=*/false, field_entry,
                          &inst.node_overrides,
                          instance_decal_override(inst.id),
                          geosphere_level_for(*m, inst.world, camera));
    });
}

void FrameSubmitter::submit_opaque_in_pass(const scenegraph::World& world,
                                           const scenegraph::Camera& camera,
                                           Pipeline& pipeline,
                                           const ModelLookup& lookup,
                                           const Lighting& lighting,
                                           scenegraph::Pass pass,
                                           float decal_time,
                                           CarveFieldCache* carve_cache,
                                           float ambient_scale,
                                           const std::vector<DynamicLightDescriptor>* dyn_lights,
                                           InstanceFieldCache* field_cache) {
    // See submit_opaque: configure the common per-frame uniforms on BOTH the
    // static and skinned programs. The static-program set is unchanged.
    auto configure_common = [&](Shader& s) {
        s.use();
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());

        const glm::vec3 cam_pos_ws =
            glm::vec3(glm::inverse(camera.view_matrix())[3]);
        s.set_vec3("u_camera_pos_ws", cam_pos_ws);

        // ambient_scale (default 1.0) dims ambient on the exterior view when the
        // Filmic Filter is on; the host passes the filmic scale only for the
        // main exterior pass (1.0 for the viewscreen inset / all other callers).
        set_ambient_uniforms(s, lighting, ambient_scale);
        s.set_int("u_dir_light_count", lighting.directional_count);
        if (lighting.directional_count > 0) {
            s.set_vec3_array("u_dir_light_dir_ws",
                             lighting.directional_dir_ws,
                             lighting.directional_count);
            s.set_vec3_array("u_dir_light_color",
                             lighting.directional_color,
                             lighting.directional_count);
        }
    };

    auto& shader = pipeline.opaque_shader();
    configure_common(shader);
    configure_common(pipeline.skinned_shader());

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    world.for_each_visible_in_pass(pass, [&](const scenegraph::Instance& inst) {
        // Far tier (far-tier spec §3): a mesh fully handed to its impostor is
        // not drawn at all.
        if (inst.far_fade >= 1.0f) return;
        const assets::Model* m = lookup(inst.model_handle);
        const float rim_strength =
            (dauntless_rim::enabled() && inst.rim_eligible)
                ? inst.rim_strength * dauntless_rim::kStrengthScale : 0.0f;
        std::vector<glm::mat4> palette;
        if (m && !m->skeleton.bones.empty())
            palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
        std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> lights{};
        const int light_count =
            select_instance_dynamic_lights(inst, m, dyn_lights, lights);
        const InstanceFieldCache::Entry* field_entry =
            field_cache != nullptr ? field_cache->get(inst.id) : nullptr;
        // Far tier: a fading mesh screen-doors against its impostor. Set on
        // both programs (draw_model picks one); reset only when set, so a
        // far_fade-0 instance leaves every uniform untouched.
        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", inst.far_fade);
            pipeline.skinned_shader().use();
            pipeline.skinned_shader().set_float("u_dither_fade", inst.far_fade);
        }
        if (m) draw_model(*m, inst.world, shader, pipeline.skinned_shader(),
                          white, black, rim_strength,
                          inst.decals, inst.glow_regions, decal_time,
                          inst.emissive_scale, palette, inst.carve,
                          lights, light_count,
                          carve_fill_entry(carve_cache, m, inst.carve),
                          /*carve_invert=*/false, field_entry,
                          &inst.node_overrides,
                          instance_decal_override(inst.id),
                          geosphere_level_for(*m, inst.world, camera));
        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", 0.0f);
            pipeline.skinned_shader().use();
            pipeline.skinned_shader().set_float("u_dither_fade", 0.0f);
        }
    });
}

void FrameSubmitter::submit_carve_stencil(const scenegraph::World& world,
                                          const scenegraph::Camera& camera,
                                          Pipeline& pipeline,
                                          const ModelLookup& lookup,
                                          scenegraph::Pass pass,
                                          CarveFieldCache* carve_cache,
                                          InstanceFieldCache* field_cache) {
    if (!dauntless_hull_damage::enabled()) return;

    // Collect first so the GL state change is skipped entirely in the common
    // case of an undamaged scene.
    std::vector<const scenegraph::Instance*> carved;
    world.for_each_visible_in_pass(pass, [&](const scenegraph::Instance& inst) {
        // Filters on the SPHERE ring, not the per-instance field -- correct
        // today only because HullCarveField::add never evicts down to zero
        // (the ring only grows/merges until eviction swaps in a new carve,
        // it has no clear()). A field-only damage source (no matching sphere
        // slot) would silently skip this stencil pass; if HullCarveField
        // ever gains a clear() this condition needs a field.count()-style
        // check added alongside it.
        // Far tier: a mesh drawn as its impostor has no hull to stamp.
        if (inst.far_fade >= 1.0f) return;
        if (inst.carve.count() > 0) carved.push_back(&inst);
    });
    if (carved.empty()) return;

    Shader& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    // Stencil only: no colour, no depth. Depth TEST stays on so a cut behind
    // nearer geometry does not stamp a pixel that geometry owns.
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
    glDepthMask(GL_FALSE);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_STENCIL_TEST);
    glStencilFunc(GL_ALWAYS, 1, 0xFF);
    glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
    glStencilMask(0xFF);

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    for (const scenegraph::Instance* inst : carved) {
        const assets::Model* m = lookup(inst->model_handle);
        if (!m) continue;
        std::vector<glm::mat4> palette;
        if (!m->skeleton.bones.empty())
            palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
        std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> lights{};
        const InstanceFieldCache::Entry* field_entry =
            field_cache != nullptr ? field_cache->get(inst->id) : nullptr;
        // u_carve_invert is set INSIDE draw_model's carve block (it needs the
        // same program the block configures), so it is passed through here.
        draw_model(*m, inst->world, shader, pipeline.skinned_shader(),
                   white, black, /*rim_strength=*/0.0f,
                   inst->decals, inst->glow_regions, /*decal_time=*/0.0f,
                   inst->emissive_scale, palette, inst->carve,
                   lights, /*dyn_light_count=*/0,
                   carve_fill_entry(carve_cache, m, inst->carve),
                   /*carve_invert=*/true, field_entry,
                   &inst->node_overrides,
                   instance_decal_override(inst->id));
    }

    // Back to the GL default (0xFF), NOT 0x00: glClear(GL_STENCIL_BUFFER_BIT)
    // is masked by glStencilMask, so leaving it closed would silently turn next
    // frame's stencil clear into a no-op and let marks accumulate.
    glStencilMask(0xFF);
    glDisable(GL_STENCIL_TEST);
    glDepthMask(GL_TRUE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    // Leave u_carve_invert clear so the next ordinary hull draw is unaffected
    // even if it happens before the next configure pass.
    shader.use();
    shader.set_int("u_carve_invert", 0);
    pipeline.skinned_shader().use();
    pipeline.skinned_shader().set_int("u_carve_invert", 0);
}

void FrameSubmitter::submit_opaque_instance(const scenegraph::World& world,
                                            scenegraph::InstanceId instance_id,
                                            const scenegraph::Camera& camera,
                                            Pipeline& pipeline,
                                            const ModelLookup& lookup,
                                            const Lighting& lighting,
                                            float decal_time,
                                            CarveFieldCache* carve_cache,
                                            const std::vector<DynamicLightDescriptor>* dyn_lights,
                                            InstanceFieldCache* field_cache) {
    const scenegraph::Instance* inst = world.get(instance_id);
    if (!inst) return;
    const assets::Model* m = lookup(inst->model_handle);
    if (!m) return;

    // Same per-frame common uniforms as submit_opaque_in_pass, on both the
    // static and skinned programs. ambient_scale is fixed at 1.0 here: the
    // viewer's isolated presentation is not the exterior filmic pass.
    auto configure_common = [&](Shader& s) {
        s.use();
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());
        const glm::vec3 cam_pos_ws =
            glm::vec3(glm::inverse(camera.view_matrix())[3]);
        s.set_vec3("u_camera_pos_ws", cam_pos_ws);
        set_ambient_uniforms(s, lighting, 1.0f);
        s.set_int("u_dir_light_count", lighting.directional_count);
        if (lighting.directional_count > 0) {
            s.set_vec3_array("u_dir_light_dir_ws",
                             lighting.directional_dir_ws,
                             lighting.directional_count);
            s.set_vec3_array("u_dir_light_color",
                             lighting.directional_color,
                             lighting.directional_count);
        }
    };

    auto& shader = pipeline.opaque_shader();
    configure_common(shader);
    configure_common(pipeline.skinned_shader());

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    const float rim_strength =
        (dauntless_rim::enabled() && inst->rim_eligible)
            ? inst->rim_strength * dauntless_rim::kStrengthScale : 0.0f;
    std::vector<glm::mat4> palette;
    if (!m->skeleton.bones.empty())
        palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
    std::array<DynamicLightDescriptor, kMaxDynamicLightsPerDraw> lights{};
    const int light_count =
        select_instance_dynamic_lights(*inst, m, dyn_lights, lights);
    const InstanceFieldCache::Entry* field_entry =
        field_cache != nullptr ? field_cache->get(inst->id) : nullptr;
    draw_model(*m, inst->world, shader, pipeline.skinned_shader(),
               white, black, rim_strength,
               inst->decals, inst->glow_regions, decal_time,
               inst->emissive_scale, palette, inst->carve,
               lights, light_count,
               carve_fill_entry(carve_cache, m, inst->carve),
               /*carve_invert=*/false, field_entry,
               &inst->node_overrides,
               instance_decal_override(inst->id));
}

// ── Shadow depth pre-pass ──────────────────────────────────────────────────

namespace {

// Frame-scoped active-shadow state. Set once per frame by host_bindings.cc and
// read by the opaque pass (Task 6). Defaults make shadows absent until set.
ShadowLight   g_active_shadow_light{};
std::uint32_t g_active_shadow_tex     = 0;
bool          g_active_shadow_enabled = false;

}  // namespace

void submit_shadow_depth(const scenegraph::World& world,
                         const ShadowLight& light,
                         Pipeline& pipeline,
                         const FrameSubmitter::ModelLookup& lookup) {
    // Depth-only state. Color writes off (FBO also has no color attachment).
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
    glEnable(GL_CULL_FACE);
    // Render back faces into the depth map (front-face cull) to push the
    // depth comparison surface to the far side of each hull, reducing acne.
    // STARTING guess for the det=-1 (X-flipped) ship basis; Task 7 tunes this
    // empirically against a pitched hull and may flip to GL_BACK.
    glCullFace(GL_FRONT);
    // Slope-scaled + constant depth bias as a second acne backstop.
    glEnable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(2.0f, 4.0f);

    Shader& prog = pipeline.shadow_depth_shader();
    prog.use();
    prog.set_mat4("u_light_view_proj", light.view_proj);

    // draw_model_positions_only (renderer/model_draw_helpers.h) sets only
    // u_model per mesh (u_light_view_proj is set once above) and issues the
    // same VAO bind + glDrawElements draw_model uses. No materials,
    // textures, decals, glow, carve, or skinning: casters in Pass::Space are
    // rim_eligible hulls, which are static models -- their geometry already
    // lives in the bind-pose VAOs that draw_model renders. (A skinned model
    // handed here would draw in bind pose, but no rim_eligible Space
    // instance is skinned, so it never is.)
    world.for_each_visible_in_pass(
        scenegraph::Pass::Space, [&](const scenegraph::Instance& inst) {
            if (!inst.rim_eligible) return;  // ships + stations only
            const assets::Model* m = lookup(inst.model_handle);
            if (!m) return;
            draw_model_positions_only(*m, inst.world, prog, &inst.node_overrides);
        });

    // Restore opaque-pass defaults so later passes are unaffected.
    glDisable(GL_POLYGON_OFFSET_FILL);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glCullFace(GL_BACK);
}

void set_active_shadow(const ShadowLight& light,
                       std::uint32_t depth_tex,
                       bool enabled) {
    g_active_shadow_light   = light;
    g_active_shadow_tex     = depth_tex;
    g_active_shadow_enabled = enabled;
}

const ShadowLight& active_shadow_light() noexcept { return g_active_shadow_light; }
std::uint32_t      active_shadow_texture() noexcept { return g_active_shadow_tex; }
bool               active_shadow_enabled() noexcept { return g_active_shadow_enabled; }

}  // namespace renderer
