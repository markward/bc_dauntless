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
#include "renderer/part_severance_check.h"
#include <renderer/atmosphere_math.h>
#include <renderer/asset_path.h>
#include <renderer/breach_pass.h>   // find_base_texture_id
#include <renderer/model_draw_helpers.h>
#include <renderer/node_anim.h>
#include <renderer/planet_detail_pass.h>
#include <renderer/planet_detail_uniforms.h>
#include <renderer/scuff_texture.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/hull_carve.h>

#include <assets/file_bytes.h>
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

// SPIKE (damage redesign): hull-plating layer params, pushed live from
// engine/appc/plating_dials.py (/ L O, group "plating"). Defaults MUST match
// that module's DEFAULTS; slot meanings are listed there and in opaque.frag's
// apply_plating. [0] = enabled (0/1).
#include "renderer/structure_parts_cache.h"
#include "renderer/plating_damage.h"
namespace dauntless_plating {
    float g_params[renderer::plating::kParamCount] = {
        1.0f,   // 0 enabled
        6.0f,   // 1 panel size (model units, ~1.75 m each)
        8.0f,   // 2 primary member spacing (spokes / hoops / frames)
        5.0f,   // 3 secondary member spacing (rings / stringers)
        1.2f,   // 4 member width (secondaries 0.6x)
        0.6f,   // 5 plate depth
        1.2f,   // 6 rib depth (below the plate)
        0.40f,  // 7 reach (x scorch decal radius)
        0.5f,   // 8 wear to strip a panel
        2.5f,   // 9 wear to break ribs
        0.35f,  // 10 buckle band (wear below strip that buckles)
        0.6f,   // 11 edge noise
        0.0f,   // 12 debug (1 = stripped tint, 2 = colour by structure part)
        0.75f,  // 13 soot (x scorch deposit while plating is on)
        1.0f,   // 14 metal brightness (x rib / edge albedo)
        1.5f,   // 15 member bend (model units of distortion at full damage)
        4.5f,   // 16 breach wear (inner pressure hull tears open)
        1.0f,   // 17 inner hull brightness
        0.6f,   // 18 tear mix (0 = whole panels, 1 = torn freely)
        0.9f,   // 19 tear noise (wear units)
        0.35f,  // 20 peel band (wear units short of tearing)
        4.0f,   // 21 member survive (wear past breach a primary still spans)
        0.6f,   // 22 toughness spread (breach wear varies per panel by up to this x0.4)
        1.0f,   // 23 breach lumps (wear units of hole-scale breach-threshold variation)
        6.0f,   // 24 deck break wear (interior: a plate or far wall breaks past it)
        1.0f,   // 25 interior (> 0.5 draws decks and rooms behind cuts)
        0.0f,   // 26 force program (perf probe: undamaged hulls take the plating program)
        0.0f, 0.0f, 0.0f, 0.0f, 0.0f,   // 27-31 reserved
    };
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
    const auto bytes = assets::read_binary_file(resolved);
    if (!bytes) {
        // game root not installed — framework will be silently disabled.
        return 0;
    }
    try {
        assets::Image   img = assets::decode_tga(*bytes);
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
// The box centre is cached beside the radius: a sphere of that radius bounds
// the model only around the centre (interior_is_near), not the origin.
struct ModelBounds {
    glm::vec3 centre{0.0f};
    float radius = 0.0f;
};
std::unordered_map<scenegraph::ModelHandle, ModelBounds> g_model_radius_cache;

const ModelBounds& model_bounds(scenegraph::ModelHandle handle, const assets::Model& model) {
    auto it = g_model_radius_cache.find(handle);
    if (it != g_model_radius_cache.end()) return it->second;
    const Aabb box = compute_model_aabb(model);
    return g_model_radius_cache
        .emplace(handle, ModelBounds{box.center, glm::length(box.half_extents)})
        .first->second;
}

float model_bounding_radius(scenegraph::ModelHandle handle,
                            const assets::Model& model) {
    return model_bounds(handle, model).radius;
}

// Per-mesh body-frame boxes (mesh_body_aabbs) for the plating record
// subsets: the same per-ModelHandle cache, under the same reset discipline
// (reset_model_radius_cache clears both).
std::unordered_map<scenegraph::ModelHandle, std::vector<Aabb>> g_mesh_boxes_cache;

const std::vector<Aabb>& model_mesh_boxes(scenegraph::ModelHandle handle,
                                          const assets::Model& model) {
    auto it = g_mesh_boxes_cache.find(handle);
    if (it != g_mesh_boxes_cache.end()) return it->second;
    return g_mesh_boxes_cache.emplace(handle, mesh_body_aabbs(model)).first->second;
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
    g_mesh_boxes_cache.clear();
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

// draw_model's program choice: skinned only when the model carries a skeleton
// AND a non-empty palette is supplied. Shared with submit_plating_interior,
// whose marking draw must skip models that take the skinned program (it has
// no plating layer, so the whole hull would be stamped).
static bool draws_skinned(const assets::Model& model,
                          const std::vector<glm::mat4>& bone_palette) {
    return !model.skeleton.bones.empty() && !bone_palette.empty();
}

// SPIKE (damage redesign): the plating program's per-draw block -- params,
// the compact damage list (u_dmg_*, renderer/plating_damage.h), the hull's
// structure parts, world->body, and the mark / far / rock switches. Shared by
// draw_model's plating draws and the lean marking draw, so the two can never
// disagree about what the plating discard reads. Parts come from a background
// detection per hull source; until it lands u_part_count is 0 and the shader
// uses a body-axis box chart.
// `upload_list` false: the caller uploads u_dmg_* per mesh
// (MeshRecordUploader) instead. `parts` = structure_parts_for(model.source),
// read ONCE by the caller so the per-mesh cull margins see the same parts the
// shader is given (they land on a worker thread at any moment).
// `rock` (Instance::surface_is_rock): u_plating_rock, no panels, ribs or
// members, only a cut where wear passes breach.
// `hidden_parts` / `shown_parts` (PlatingMeshRecords): the severed parts this
// draw hides / the only parts a chunk draws; 0 / 0 for a whole hull.
static void upload_plating(Shader& prog, const plating::DamageList& dl,
                           const std::vector<voxel::StructurePart>* parts,
                           const glm::mat4& world, const float* params, bool mark,
                           bool far, bool upload_list, bool rock,
                           std::uint32_t hidden_parts, std::uint32_t shown_parts) {
    static const std::string kPlating = "u_plating", kDmgCount = "u_dmg_count",
        kDmgA = "u_dmg_a", kDmgB = "u_dmg_b", kDmgC = "u_dmg_c",
        kMark = "u_plating_mark", kFar = "u_plating_far", kRock = "u_plating_rock",
        kPartCount = "u_part_count",
        kPartA = "u_part_a", kPartB = "u_part_b", kPartC = "u_part_c",
        kPartD = "u_part_d", kWorldInv = "u_ship_world_inv",
        kPartHidden = "u_part_hidden_mask", kPartShown = "u_part_show_mask";
    if (const int loc = prog.cached_location(kPlating); loc >= 0)
        glUniform1fv(loc, renderer::plating::kParamCount, params);
    // world->body for p_body / n_body. draw_model's decal block sets it only
    // when decals are enabled and present; a plating draw must never read a
    // previous draw's matrix.
    prog.set_mat4(kWorldInv, glm::inverse(world));

    if (upload_list) {
        prog.set_int(kDmgCount, dl.count);
        prog.set_vec4_array(kDmgA, dl.a, dl.count);
        prog.set_vec4_array(kDmgB, dl.b, dl.count);
        prog.set_vec4_array(kDmgC, dl.c, dl.count);
    }

    // opaque.frag MAX_PARTS; also the parts a severance may hide.
    constexpr int kMaxParts = renderer::kMaxHideableParts;
    glm::vec4 pa[kMaxParts], pb[kMaxParts], pc[kMaxParts], pd[kMaxParts];
    int np = 0;
    if (parts != nullptr) {
        for (const auto& sp : *parts) {
            if (np >= kMaxParts) break;
            pa[np] = glm::vec4(sp.centre, static_cast<float>(static_cast<int>(sp.kind)));
            pb[np] = glm::vec4(sp.axis[0], sp.half_extent.x);
            pc[np] = glm::vec4(sp.axis[1], sp.half_extent.y);
            pd[np] = glm::vec4(sp.half_extent.z, 0.0f, 0.0f, 0.0f);
            ++np;
        }
    }
    prog.set_int(kPartCount, np);
    prog.set_vec4_array(kPartA, pa, np);
    prog.set_vec4_array(kPartB, pb, np);
    prog.set_vec4_array(kPartC, pc, np);
    prog.set_vec4_array(kPartD, pd, np);
    prog.set_int(kPartHidden, static_cast<int>(hidden_parts));
    prog.set_int(kPartShown, static_cast<int>(shown_parts));

    prog.set_int(kMark, mark ? 1 : 0);
    prog.set_int(kFar, far ? 1 : 0);
    prog.set_int(kRock, rock ? 1 : 0);
}

// Per-mesh u_dmg_* for one draw: each mesh's cached subset
// (plating::MeshRecordSubset), or the whole list for a null subset. A mesh
// with none uploads u_dmg_count 0 (the arrays keep stale values the shader
// never reads past the count). An upload equal to the previous one of this
// draw (same records, same order) is skipped, so a hull whose meshes all see
// every record uploads the list once.
namespace {
int g_plating_mesh_subset_computations = 0;
int g_plating_record_uploads = 0;
int g_draw_model_program_binds = 0;
int g_draw_model_plating_mesh_draws = 0;

class MeshRecordUploader {
public:
    MeshRecordUploader(Shader& prog, const plating::DamageList& dl) : prog_(prog), dl_(dl) {}

    void upload(const plating::MeshRecordSubset* subset) {
        std::array<std::uint8_t, plating::kMaxDamage> all;
        const std::uint8_t* idx = nullptr;
        int n = dl_.count;
        if (subset != nullptr) {
            n = subset->count;
            idx = subset->idx.data();
        } else {
            for (int k = 0; k < n; ++k) all[static_cast<std::size_t>(k)] = static_cast<std::uint8_t>(k);
            idx = all.data();
        }
        if (have_last_ && n == last_n_ && std::equal(idx, idx + n, last_idx_.begin()))
            return;
        have_last_ = true;
        last_n_ = n;
        std::copy(idx, idx + n, last_idx_.begin());

        static const std::string kDmgCount = "u_dmg_count", kDmgA = "u_dmg_a",
            kDmgB = "u_dmg_b", kDmgC = "u_dmg_c";
        ++g_plating_record_uploads;
        prog_.set_int(kDmgCount, n);
        if (n == dl_.count) {   // every record, in order: no gather
            prog_.set_vec4_array(kDmgA, dl_.a, n);
            prog_.set_vec4_array(kDmgB, dl_.b, n);
            prog_.set_vec4_array(kDmgC, dl_.c, n);
            return;
        }
        glm::vec4 a[plating::kMaxDamage], b[plating::kMaxDamage], c[plating::kMaxDamage];
        for (int k = 0; k < n; ++k) {
            a[k] = dl_.a[idx[k]];
            b[k] = dl_.b[idx[k]];
            c[k] = dl_.c[idx[k]];
        }
        prog_.set_vec4_array(kDmgA, a, n);
        prog_.set_vec4_array(kDmgB, b, n);
        prog_.set_vec4_array(kDmgC, c, n);
    }

private:
    Shader& prog_;
    const plating::DamageList& dl_;
    bool have_last_ = false;
    int last_n_ = 0;
    std::array<std::uint8_t, plating::kMaxDamage> last_idx_{};
};
}  // namespace

int plating_mesh_subset_computations() { return g_plating_mesh_subset_computations; }
int plating_record_uploads() { return g_plating_record_uploads; }
int draw_model_program_binds() { return g_draw_model_program_binds; }
int draw_model_plating_mesh_draws() { return g_draw_model_plating_mesh_draws; }

// Mesh `mesh_idx`'s subset, or nullptr (the whole list) when there is none
// for the index.
static const plating::MeshRecordSubset* plating_subset_for(
        const std::vector<plating::MeshRecordSubset>& subsets, int mesh_idx) {
    if (mesh_idx < 0 || mesh_idx >= static_cast<int>(subsets.size())) return nullptr;
    return &subsets[static_cast<std::size_t>(mesh_idx)];
}

// World matrix per node: the parent chain composed onto `world`. An
// articulated instance (BoP wings) supplies replacement node locals;
// compose_node_worlds runs the identical parent chain with those swapped in,
// and reproduces the walk below exactly when the map is empty. The empty case
// takes the inline walk so the common path allocates nothing extra. The asset
// pipeline orders nodes parents-first, so one linear pass suffices.
static std::vector<glm::mat4> node_worlds_for(
        const assets::Model& model, const glm::mat4& world,
        const std::unordered_map<int, glm::mat4>* node_overrides) {
    if (node_overrides != nullptr && !node_overrides->empty())
        return compose_node_worlds(model, world, *node_overrides);
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = world * model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
    }
    return world_per_node;
}

// Which of a model's meshes one draw_model_pass draws. `subsets` null: every
// mesh. Otherwise the meshes that take the plating program (with_records)
// or the record-free rest (!with_records); see mesh_takes_plating.
struct MeshFilter {
    const std::vector<plating::MeshRecordSubset>* subsets = nullptr;
    bool with_records = false;
};

// Whether mesh `mesh_idx` of a plated draw needs the plating program: it has
// records in its subset, has no subset (the whole list), or is the
// geosphere's substituted mesh (draw_model_pass gives it the whole list).
static bool mesh_takes_plating(const assets::Model& model, int sphere_level,
                               const std::vector<plating::MeshRecordSubset>& subsets,
                               int mesh_idx) {
    if (sphere_level >= 0 && model.sphere_map.has_value() &&
        mesh_idx == model.sphere_map->mesh_index)
        return true;
    const plating::MeshRecordSubset* subset = plating_subset_for(subsets, mesh_idx);
    return subset == nullptr || subset->count > 0;
}

// One program's half of draw_model: the per-instance uniforms on `shader`
// (or the skinned program), then the meshes `filter` selects.
static void draw_model_pass(const assets::Model& model,
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
                int sphere_level,
                const scenegraph::Instance::Atmosphere* atmo,
                glm::vec3 atmo_sun_dir,
                const plating::DamageList* plating,
                bool plating_far,
                const PlatingMeshRecords* plating_mesh_records,
                MeshFilter filter,
                bool plating_rock) {
    // Pick the program: skinned only when the model carries a skeleton AND a
    // non-empty palette is supplied. An empty palette forces the static branch,
    // which is byte-identical to the pre-skinning path (used by the plumbing
    // test to render a skinned model through the static program).
    const bool skinned = draws_skinned(model, bone_palette);
    Shader& prog = skinned ? skinned_shader : shader;
    prog.use();
    ++g_draw_model_program_binds;
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

    // SPIKE (damage redesign): plating layer -- ONLY for a draw through the
    // plating program (submit_opaque_in_pass passes the list exactly when
    // plating::wants_plating). A stock draw (plating == nullptr, or a skinned
    // model, whose program has no plating layer) touches no plating uniform.
    const plating::DamageList* const plating_list = skinned ? nullptr : plating;

    // ── SPIKE (damage redesign): plating params, damage list, parts ────────
    // Ride only plating draws (upload_plating). The part-colour debug view
    // (params[12] == 2) therefore tints only near listed damage on a hull
    // whose list is non-empty; an undamaged hull draws stock.
    // With per-mesh boxes (and no node overrides) the list goes up per mesh
    // in the loop below, each mesh only the records near it.
    const std::vector<plating::MeshRecordSubset>* const plating_subsets =
        plating_list != nullptr && plating_mesh_records != nullptr &&
                !(node_overrides != nullptr && !node_overrides->empty())
            ? plating_mesh_records->subsets
            : nullptr;
    std::optional<MeshRecordUploader> plating_records;
    if (plating_list != nullptr) {
        const std::vector<voxel::StructurePart>* const plating_parts =
            plating_mesh_records != nullptr ? plating_mesh_records->parts
                                            : renderer::structure_parts_for(model.source);
        upload_plating(prog, *plating_list, plating_parts, world, dauntless_plating::g_params,
                       /*mark=*/false, plating_far,
                       /*upload_list=*/plating_subsets == nullptr, plating_rock,
                       plating_mesh_records != nullptr ? plating_mesh_records->hidden_parts : 0u,
                       plating_mesh_records != nullptr ? plating_mesh_records->shown_parts : 0u);
        if (plating_subsets != nullptr) plating_records.emplace(prog, *plating_list);
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

    // Walk nodes; each node may reference one or more meshes by index.
    const std::vector<glm::mat4> world_per_node = node_worlds_for(model, world, node_overrides);

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
        // The game clock, for the planet_ program's gas flow. The two blocks
        // above set u_decal_time only when this draw has decals / glow
        // regions, so without this a geosphere draw would read a stale value.
        // The invariant: every set of u_decal_time in draw_model writes the
        // same `decal_time`, so wherever the shader reads it (decal and glow
        // loops, gas flow) it is this frame's game clock.
        prog.set_float("u_decal_time", decal_time);
    }

    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        for (int mesh_idx : node.meshes) {
            if (filter.subsets != nullptr &&
                mesh_takes_plating(model, sphere_level, *filter.subsets, mesh_idx) !=
                    filter.with_records)
                continue;
            const auto& mesh = model.meshes[mesh_idx];
            // Material, textures and decal mask still come from `mesh`; only
            // the geometry is substituted. EVERY draw sets u_sphere_map:
            // uniforms persist, so a skipped 0 would leak 1 onto the next ship.
            const bool this_sphere = sphere && mesh_idx == model.sphere_map->mesh_index;
            const auto& draw_mesh = this_sphere
                ? model.sphere_map->lods[static_cast<std::size_t>(std::clamp(
                      sphere_level, 0,
                      static_cast<int>(model.sphere_map->lods.size()) - 1))]
                : mesh;
            prog.set_int("u_sphere_map", this_sphere ? 1 : 0);
            // Plating: this mesh's records. The geosphere's substituted mesh
            // is not the one its box bounds: it gets the whole list.
            if (plating_records) {
                plating_records->upload(
                    this_sphere ? nullptr : plating_subset_for(*plating_subsets, mesh_idx));
            }
            // Same rule as u_sphere_map: set on EVERY draw so it cannot leak.
            const bool this_atmo = this_sphere && atmo != nullptr && atmo->enabled;
            prog.set_int("u_atmo_enabled", this_atmo ? 1 : 0);
            if (this_atmo) {
                prog.set_vec3("u_atmo_color", atmo->color);
                prog.set_vec3("u_atmo_sunset", atmo->sunset_color);
                prog.set_float("u_atmo_limb", atmo->limb);
                prog.set_vec3("u_atmo_sun_dir_ws", atmo_sun_dir);
            }
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

            const auto& mat = assets::material_or_default(model, mesh.material_index());
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
            if (plating_list != nullptr) ++g_draw_model_plating_mesh_draws;
        }
    }
    glBindVertexArray(0);
    // Never leak the decal clamp to a later pass (mask units 8-11 only).
    for (int i = 0; i < assets::kMaxDecalMasks; ++i)
        glBindSampler(kHullDecalUnit0 + i, 0);
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
                int sphere_level,
                const scenegraph::Instance::Atmosphere* atmo,
                glm::vec3 atmo_sun_dir,
                const plating::DamageList* plating,
                bool plating_far,
                const PlatingMeshRecords* plating_mesh_records,
                Shader* stock_shader,
                bool plating_rock) {
    // A plated draw with per-mesh subsets splits its meshes: the record-free
    // ones through the stock program first, then the rest through plating,
    // so the instance switches program at most once. No split for a skinned
    // draw (no plating layer), without subsets, or with node overrides (the
    // posed meshes leave their rest boxes: every mesh gets the whole list).
    const bool articulated = node_overrides != nullptr && !node_overrides->empty();
    const std::vector<plating::MeshRecordSubset>* const split =
        plating != nullptr && stock_shader != nullptr && plating_mesh_records != nullptr &&
                !articulated && !draws_skinned(model, bone_palette)
            ? plating_mesh_records->subsets
            : nullptr;
    auto pass = [&](Shader& prog, const plating::DamageList* list,
                    const PlatingMeshRecords* records, MeshFilter filter) {
        draw_model_pass(model, world, prog, skinned_shader, white_fallback, black_fallback,
                        rim_strength, decals, glow_regions, decal_time, emissive_scale,
                        bone_palette, carve, dyn_lights, dyn_light_count, carve_fill,
                        carve_invert, hull_field, node_overrides, decal_override, sphere_level,
                        atmo, atmo_sun_dir, list, plating_far, records, filter,
                        plating_rock);
    };
    if (split == nullptr) {
        pass(shader, plating, plating_mesh_records, MeshFilter{});
        return;
    }
    bool any_free = false, any_plated = false;
    for (const auto& node : model.nodes) {
        for (int mesh_idx : node.meshes) {
            if (mesh_takes_plating(model, sphere_level, *split, mesh_idx)) any_plated = true;
            else any_free = true;
        }
    }
    // The stock half gets exactly a stock draw's uniforms: no plating list.
    if (any_free) pass(*stock_shader, nullptr, nullptr, MeshFilter{split, false});
    if (any_plated) pass(shader, plating, plating_mesh_records, MeshFilter{split, true});
}

// SPIKE (damage redesign): the lean marking draw (submit_plating_interior).
// Colour and depth writes are off, so only the stencil it stamps matters, and
// that is decided by which fragments survive opaque.frag's PLATING main. This
// sets exactly what that survival reads, or neutralises it:
//   - read up to the plating discard: the plating block (params, damage list,
//     parts, u_ship_world_inv, u_plating_mark = 1, u_plating_far = 0) and, per
//     mesh, u_model (+ u_view / u_proj from the caller) and u_node_rest_fix;
//   - every other discard in main: the dither (u_dither_fade, set by the
//     caller from the instance; u_impostor_blend 0), the coverage cutout
//     (u_coverage_cutout 0), and the old carve clip after the plating discard
//     (u_carve_enabled / u_carve_count / u_carve_invert / u_hull_field_enabled
//     0 -- carve is off in the mark, as it was in the full draw_model mark
//     this replaced, which passed no hull field either);
//   - u_shadow_map's unit (5): a sampler2DShadow left on unit 0 beside the
//     sampler2Ds is GL_INVALID_OPERATION at draw on a never-drawn program.
// No texture binds, no decals, glow regions, lights or materials: whatever
// they would shade is masked off. The audit (one row per uniform) is in the
// phase 2 Task 2 report.
// `records`: as draw_model's plating_mesh_records -- the parts the plating
// block uploads, and each mesh's own subset (the whole list when the subsets
// are null or with node overrides). `skip_record_free`: a mesh whose subset
// is empty is not drawn -- opaque.frag's PLATING main discards every fragment
// of a mark with no record near it, so it could stamp nothing. Returns the
// meshes drawn. `rock`: as upload_plating's (the rock hole rule).
static int draw_plating_mark(const assets::Model& model, const glm::mat4& world,
                             Shader& prog, const plating::DamageList& dl,
                             const float* params,
                             const std::unordered_map<int, glm::mat4>* node_overrides,
                             const PlatingMeshRecords& records, bool skip_record_free,
                             bool rock) {
    static const std::string kCarveEnabled = "u_carve_enabled", kCarveCount = "u_carve_count",
        kCarveInvert = "u_carve_invert", kFieldEnabled = "u_hull_field_enabled",
        kCutout = "u_coverage_cutout", kImpostorBlend = "u_impostor_blend",
        kShadowMap = "u_shadow_map", kModel = "u_model", kRestFix = "u_node_rest_fix";
    prog.use();
    const bool articulated = node_overrides != nullptr && !node_overrides->empty();
    const std::vector<plating::MeshRecordSubset>* const subsets =
        articulated ? nullptr : records.subsets;
    upload_plating(prog, dl, records.parts, world, params, /*mark=*/true, /*far=*/false,
                   /*upload_list=*/subsets == nullptr, rock, records.hidden_parts,
                   records.shown_parts);
    std::optional<MeshRecordUploader> uploader;
    if (subsets != nullptr) uploader.emplace(prog, dl);
    prog.set_int(kCarveEnabled, 0);
    prog.set_int(kCarveCount, 0);
    prog.set_int(kCarveInvert, 0);
    prog.set_int(kFieldEnabled, 0);
    prog.set_int(kCutout, 0);
    prog.set_int(kImpostorBlend, 0);
    prog.set_int(kShadowMap, 5);

    const std::vector<glm::mat4> world_per_node = node_worlds_for(model, world, node_overrides);
    const std::vector<glm::mat4> rest_fix =
        articulated ? rest_corrections(model, *node_overrides) : std::vector<glm::mat4>{};

    // Per mesh: its records, its transform, then the draw.
    int drawn = 0;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        for (int mesh_idx : model.nodes[i].meshes) {
            const auto& mesh = model.meshes[static_cast<std::size_t>(mesh_idx)];
            if (uploader) {
                const plating::MeshRecordSubset* subset = plating_subset_for(*subsets, mesh_idx);
                if (skip_record_free && subset != nullptr && subset->count == 0) continue;
                uploader->upload(subset);
            }
            prog.set_mat4(kModel, world_per_node[i]);
            prog.set_mat4(kRestFix, articulated ? rest_fix[i] : glm::mat4(1.0f));
            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
            ++drawn;
        }
    }
    glBindVertexArray(0);
    return drawn;
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
                                           InstanceFieldCache* field_cache,
                                           const std::vector<SunDescriptor>* suns,
                                           const planet_detail::PlanetDetailPass* detail) {
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
    // Planet surface detail: only when a pass has a target does the planet_
    // program need this frame's camera and lights; otherwise it is untouched.
    const std::optional<scenegraph::InstanceId> detail_target =
        detail != nullptr ? detail->target() : std::nullopt;
    if (detail_target) configure_common(pipeline.planet_shader());
    // Plating layer (SPIKE, damage redesign): the plating_ program is
    // configured the first time a draw in this pass needs it, so an
    // undamaged scene never touches it.
    bool plating_configured = false;
    plating_far_draws_last_frame_ = 0;
    // Drop cached lists of instances no longer in the world.
    for (auto it = plating_list_cache_.begin(); it != plating_list_cache_.end();) {
        if (world.is_valid(it->first)) ++it;
        else it = plating_list_cache_.erase(it);
    }

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();
    static const std::vector<SunDescriptor> kNoSuns;

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
        const int sphere_level = m ? geosphere_level_for(*m, inst.world, camera) : -1;
        const bool is_detail_draw = m && detail_target && *detail_target == inst.id &&
                                    m->sphere_map && sphere_level >= 0;
        // Plating layer: only a hull with listed damage draws through the
        // plating_ program (plating::wants_plating); every other draw takes
        // the stock program and uploads nothing for plating. The planet
        // detail draw keeps planet_.
        // The cached list itself (no copy): the map's nodes are stable and
        // nothing below can rebuild this instance's entry.
        const plating::DamageList* plating_list = nullptr;
        PlatingListCacheEntry* plating_entry = nullptr;
        bool use_plating = false;
        // params[26] (perf probe): every non-rock, non-skinned hull takes the
        // plating program, with an empty list when it has no records.
        const bool force_plating = dauntless_plating::g_params[26] > 0.5f && m &&
                                   !inst.surface_is_rock && !draws_skinned(*m, palette);
        // A hull that has lost a structure part (or a chunk that is one)
        // hides it in the plating draw (u_part_hidden_mask / u_part_show_mask):
        // every mesh takes the plating program, no stock split, with an empty
        // list when it has no records, whatever params[0] says -- a stock draw
        // would show the whole model.
        const bool part_hiding = m && !is_detail_draw && !draws_skinned(*m, palette) &&
                                 (inst.severed_parts != 0 || inst.shown_parts != 0);
        if (m && !is_detail_draw &&
            ((dauntless_plating::g_params[0] > 0.5f &&
              (inst.hull_damage.count() > 0 || force_plating)) ||
             part_hiding)) {
            plating_entry = &plating_entry_for(inst);
            plating_list = &plating_entry->list;
            use_plating = force_plating || part_hiding ||
                          plating::wants_plating(*plating_list, dauntless_plating::g_params);
        }
        // The parts and per-mesh subsets this draw uploads, cached on the
        // entry (the mark below reuses them). A skinned draw has no plating
        // layer and needs none.
        PlatingMeshRecords plating_records{};
        if (use_plating && !draws_skinned(*m, palette))
            plating_records = plating_mesh_records_for(*plating_entry, inst, *m);
        if (use_plating && !plating_configured) {
            configure_common(pipeline.plating_shader());
            plating_configured = true;
        }
        // Near/far (InteriorPolicy): a far hull gets no interior, so its holes
        // are painted by this draw (a ship's as wreckage, a rock's crater as
        // darkened rock). submit_plating_interior takes the same decision for
        // the same instance, so a hull is either marked or painted far, never
        // both. A skinned draw has no plating layer.
        bool plating_far = false;
        if (use_plating && !draws_skinned(*m, palette)) {
            const ModelBounds& bounds = model_bounds(inst.model_handle, *m);
            plating_far = !interior_is_near(inst, bounds.centre, bounds.radius, camera,
                                            interior_policy_);
            if (plating_far) ++plating_far_draws_last_frame_;
        }
        // Far tier: a fading mesh screen-doors against its impostor. Set on
        // every program that may draw (draw_model picks one); reset only when
        // set, so a far_fade-0 instance leaves every uniform untouched.
        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", inst.far_fade);
            pipeline.skinned_shader().use();
            pipeline.skinned_shader().set_float("u_dither_fade", inst.far_fade);
            if (detail_target) {
                pipeline.planet_shader().use();
                pipeline.planet_shader().set_float("u_dither_fade", inst.far_fade);
            }
            if (plating_configured) {
                pipeline.plating_shader().use();
                pipeline.plating_shader().set_float("u_dither_fade", inst.far_fade);
            }
        }
        // Planet surface atmosphere (spec 2026-10-07 §6): the sun direction
        // from the system's suns at the planet centre, else directional 0.
        glm::vec3 atmo_sun{0.0f};
        const scenegraph::Instance::Atmosphere* atmo = nullptr;
        if (m && m->sphere_map && inst.atmosphere.enabled) {
            atmo = &inst.atmosphere;
            const glm::vec3 c =
                glm::vec3(inst.world * glm::vec4(m->sphere_map->center_body, 1.0f));
            atmo_sun = planet_atmo::sun_dir_for(
                c, suns ? *suns : kNoSuns,
                lighting.directional_count > 0 ? lighting.directional_dir_ws[0]
                                               : glm::vec3(0.0f, 0.0f, 1.0f));
        }
        // The detail target's sphere-LOD draw goes through planet_, a hull
        // with listed plating damage through plating_; every other draw
        // takes exactly the stock program.
        Shader* static_shader = &shader;
        if (is_detail_draw) {
            static_shader = &pipeline.planet_shader();
            planet_detail::apply(*static_shader, detail->uniforms_for(inst.id));
        } else if (use_plating) {
            static_shader = &pipeline.plating_shader();
        }
        if (m) draw_model(*m, inst.world, *static_shader, pipeline.skinned_shader(),
                          white, black, rim_strength,
                          inst.decals, inst.glow_regions, decal_time,
                          inst.emissive_scale, palette, inst.carve,
                          lights, light_count,
                          carve_fill_entry(carve_cache, m, inst.carve),
                          /*carve_invert=*/false, field_entry,
                          &inst.node_overrides,
                          instance_decal_override(inst.id),
                          sphere_level,
                          atmo, atmo_sun,
                          use_plating ? plating_list : nullptr, plating_far,
                          use_plating ? &plating_records : nullptr,
                          // Record-free meshes draw stock, except under the
                          // force-program probe (params[26]) or part hiding:
                          // every mesh plating.
                          (force_plating || part_hiding) ? nullptr : &shader,
                          inst.surface_is_rock);
        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", 0.0f);
            pipeline.skinned_shader().use();
            pipeline.skinned_shader().set_float("u_dither_fade", 0.0f);
            if (detail_target) {
                pipeline.planet_shader().use();
                pipeline.planet_shader().set_float("u_dither_fade", 0.0f);
            }
            if (plating_configured) {
                pipeline.plating_shader().use();
                pipeline.plating_shader().set_float("u_dither_fade", 0.0f);
            }
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

FrameSubmitter::PlatingListCacheEntry& FrameSubmitter::plating_entry_for(
        const scenegraph::Instance& inst) {
    PlatingListCacheEntry& e = plating_list_cache_[inst.id];
    const float* params = dauntless_plating::g_params;
    const bool same = e.valid && e.revision == inst.hull_damage.revision() &&
                      std::equal(e.params.begin(), e.params.end(), params);
    if (!same) {
        e.list = plating::build_damage_list(inst.hull_damage, params);
        e.deck_break = plating::deck_break_subset(e.list, params);
        e.revision = inst.hull_damage.revision();
        std::copy(params, params + plating::kParamCount, e.params.begin());
        e.valid = true;
        e.subsets_valid = false;
        ++plating_list_builds_;
    }
    return e;
}

PlatingMeshRecords FrameSubmitter::plating_mesh_records_for(PlatingListCacheEntry& e,
                                                            const scenegraph::Instance& inst,
                                                            const assets::Model& model) {
    PlatingMeshRecords r;
    r.parts = renderer::structure_parts_for(model.source);
    r.hidden_parts = inst.severed_parts;
    r.shown_parts = inst.shown_parts;
    if (!plating_record_culling_ || !inst.node_overrides.empty()) return r;
    if (!e.subsets_valid || e.subsets_parts != r.parts || e.subsets_handle != inst.model_handle ||
        e.subsets_model != &model) {
        e.subsets = plating::mesh_record_subsets(e.list, model_mesh_boxes(inst.model_handle, model),
                                                 e.params.data(), r.parts);
        e.mesh_has_records.resize(e.subsets.size());
        for (std::size_t k = 0; k < e.subsets.size(); ++k)
            e.mesh_has_records[k] = e.subsets[k].count > 0 ? 1 : 0;
        e.subsets_valid = true;
        e.subsets_parts = r.parts;
        e.subsets_handle = inst.model_handle;
        e.subsets_model = &model;
        ++g_plating_mesh_subset_computations;
    }
    r.subsets = &e.subsets;
    return r;
}

const plating::DamageList& FrameSubmitter::plating_list_for(const scenegraph::Instance& inst) {
    return plating_entry_for(inst).list;
}


void FrameSubmitter::submit_plating_interior(const scenegraph::World& world,
                                             const scenegraph::Camera& camera,
                                             Pipeline& pipeline,
                                             const ModelLookup& lookup,
                                             CarveFieldCache* carve_cache,
                                             const Lighting& lighting,
                                             float ambient_scale,
                                             float now) {
    plating_marks_last_frame_ = 0;
    plating_interiors_last_frame_ = 0;
    plating_mark_mesh_draws_ = 0;
    plating_interior_mesh_draws_ = 0;
    if (dauntless_plating::g_params[0] <= 0.5f) return;

    // Same per-frame uniforms submit_opaque_in_pass gives the plating_
    // program (the interior draw sets its own).
    auto configure_common = [&](Shader& s) {
        s.use();
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());
        const glm::vec3 cam_pos_ws = glm::vec3(glm::inverse(camera.view_matrix())[3]);
        s.set_vec3("u_camera_pos_ws", cam_pos_ws);
        set_ambient_uniforms(s, lighting, ambient_scale);
        s.set_int("u_dir_light_count", lighting.directional_count);
        if (lighting.directional_count > 0) {
            s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                             lighting.directional_count);
            s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                             lighting.directional_count);
        }
    };

    bool configured = false;
    bool state_saved = false;
    bool state_set = false;
    GLint saved_depth_func = GL_LESS;
    int next_value = 2;

    world.for_each_visible_in_pass(scenegraph::Pass::Space, [&](const scenegraph::Instance& inst) {
        if (next_value > 255) return;
        if (inst.far_fade >= 1.0f) return;
        // Rocks are marked too: their interior draw is the crater (the
        // interior pass's rock mode), not decks and rooms.
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || inst.hull_damage.count() == 0) return;
        // Far hulls (InteriorPolicy) take no marking and no interior: their
        // holes were painted by the plating draw (wreckage, or rock).
        const ModelBounds& bounds = model_bounds(inst.model_handle, *m);
        if (!interior_is_near(inst, bounds.centre, bounds.radius, camera, interior_policy_))
            return;
        PlatingListCacheEntry& entry = plating_entry_for(inst);
        const plating::DamageList& list = entry.list;
        if (!plating::wants_plating(list, dauntless_plating::g_params) ||
            !list.torn_possible)
            return;
        std::vector<glm::mat4> palette;
        if (!m->skeleton.bones.empty())
            palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
        if (draws_skinned(*m, palette)) return;

        Shader& shader = pipeline.plating_shader();
        if (!configured) {
            configure_common(shader);
            configured = true;
        }
        if (!state_saved) {
            glGetIntegerv(GL_DEPTH_FUNC, &saved_depth_func);
            state_saved = true;
        }
        if (!state_set) {
            // Stencil only: no colour, no depth write. Depth TEST on with
            // LEQUAL so the hull's own depth (written by the plating draw
            // just before) passes. Re-applied after every interior draw.
            glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
            glDepthMask(GL_FALSE);
            glEnable(GL_DEPTH_TEST);
            glDepthFunc(GL_LEQUAL);
            glEnable(GL_STENCIL_TEST);
            glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
            glStencilMask(0xFF);
            state_set = true;
        }
        glStencilFunc(GL_ALWAYS, next_value, 0xFF);
        ++next_value;
        ++plating_marks_last_frame_;

        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", inst.far_fade);
        }
        const PlatingMeshRecords records = plating_mesh_records_for(entry, inst, *m);
        plating_mark_mesh_draws_ +=
            draw_plating_mark(*m, inst.world, shader, list, dauntless_plating::g_params,
                              &inst.node_overrides, records, plating_skip_record_free_,
                              inst.surface_is_rock);
        if (inst.far_fade != 0.0f) {
            shader.use();
            shader.set_float("u_dither_fade", 0.0f);
        }
        // The decks and rooms behind this hull's cuts (a rock's crater, shaded
        // with its own base texture, as breach_pass did), under the value just
        // stamped, before the next hull is marked.
        if (dauntless_plating::g_params[25] > 0.5f) {
            const CarveFieldCache::Entry* fill =
                carve_cache != nullptr ? carve_cache->get_for_source(m->source) : nullptr;
            // The mark drew no record-free mesh, so none holds this value
            // where it could pass the interior's depth test: skip them too.
            const std::vector<std::uint8_t>* mesh_mask =
                plating_skip_record_free_ && records.subsets != nullptr
                    ? &entry.mesh_has_records : nullptr;
            plating_interior_mesh_draws_ += hull_interior_.draw(
                *m, inst.world, camera, pipeline, list,
                plating_record_culling_ ? entry.deck_break : plating::full_deck_break_set(list),
                dauntless_plating::g_params,
                fill ? fill->tex3d : 0u,
                fill ? fill->origin : glm::vec3(0.0f),
                fill ? fill->cell : glm::vec3(1.0f),
                fill ? fill->dims : glm::ivec3(0),
                lighting, ambient_scale, now, next_value - 1,
                &inst.node_overrides, mesh_mask, inst.surface_is_rock,
                // Looked up only for rocks, so a ship pays nothing.
                inst.surface_is_rock ? find_base_texture_id(*m) : 0u);
            ++plating_interiors_last_frame_;
            state_set = false;   // the interior draw left stock state
        }
    });

    if (state_saved) {
        // Back to the GL default (0xFF), NOT 0x00: see submit_carve_stencil.
        glStencilMask(0xFF);
        glDisable(GL_STENCIL_TEST);
        glDepthFunc(static_cast<GLenum>(saved_depth_func));
        glDepthMask(GL_TRUE);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    }
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
            // A severed-part chunk is a whole-model instance and this pass
            // cannot hide parts: it casts nothing (the parent still casts
            // its lost part too, until this pass learns the part mask).
            if (inst.shown_parts != 0) return;
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
