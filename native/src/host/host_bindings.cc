// native/src/host/host_bindings.cc
//
// pybind11 module exposing the renderer host API to Python. Built as both:
//   1. A standalone Python extension module (_dauntless_host.so) for pytest.
//   2. Statically linked into open_stbc (registered via
//      PyImport_AppendInittab before Py_InitializeEx).
//
// Full renderer + Python host bindings: init/shutdown manage the window and
// GL context lifetime; frame() runs all render passes; Python drives sim state
// through the remaining bindings.

#include "host_bindings.h"

#include <algorithm>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <audio/python_binding.h>
#include "dauntless/transform_store.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/bone_palette.h>
#include <renderer/animation_update.h>
#include <renderer/channel_binder.h>
#include <renderer/frame.h>
#include <renderer/scuff_texture.h>
#include <renderer/frame_timer.h>
#include <renderer/lighting.h>
#include <renderer/dynamic_lights.h>
#include <renderer/backdrop_pass.h>
#include <renderer/sun_pass.h>
#include <renderer/dust_pass.h>
#include <renderer/minor_field.h>
#include <renderer/minor_pass.h>
#include <renderer/far_field.h>
#include <renderer/far_pass.h>
#include <renderer/rock_mid.h>
#include <renderer/rock_near.h>
#include <renderer/rock_speck.h>
#include <renderer/rock_puffs.h>
#include <renderer/nebula_pass.h>
#include <renderer/nebula_volumetric_pass.h>
#include <renderer/nebula_atmosphere.h>
#include <renderer/system_nebula_pass.h>
#include <renderer/nebula_godray_pass.h>
#include <renderer/shield_pass.h>
#include <renderer/lens_flare_pass.h>
#include <renderer/lens_flare_hdr_pass.h>
#include <renderer/torpedo_pass.h>
#include <renderer/hit_vfx_pass.h>
#include <renderer/hull_discharge_pass.h>
#include <renderer/nebula_wake_pass.h>
#include <renderer/shockwave_pass.h>
#include <renderer/particle_pass.h>
#include <renderer/phaser_pass.h>
#include <renderer/hologram_pass.h>
#include <renderer/cloak_pass.h>
#include <renderer/breach_pass.h>
#include <renderer/breach_venting.h>  // venting descriptor builder
#include <renderer/breach_debris.h>  // debris descriptor builder
#include <renderer/carve_field_cache.h>
#include <renderer/subsystem_pin_pass.h>
#include <renderer/debug_volume_pass.h>
#include <renderer/gizmo_pass.h>
#include <renderer/target_reticle_pass.h>
#include <renderer/starmap_pass.h>
#include <renderer/letterbox_pass.h>
#include <renderer/bridge_pass.h>
#include <renderer/viewscreen_static_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/gl_caps.h>
#include <renderer/bloom_pass.h>
#include <renderer/nonfinite_probe.h>
#include "frame_dump.h"
#include <renderer/resolve_pass.h>
#include <renderer/ldr_target.h>
#include <renderer/smaa_pass.h>
#include <renderer/filmic_pass.h>
#include <renderer/motion_blur_pass.h>
#include <renderer/motion_blur_shutter.h>
#include <renderer/render_origin.h>
#include <renderer/dof_pass.h>
#include <renderer/aabb.h>
#include <renderer/shadow_light.h>
#include <renderer/shadow_map_target.h>
#include <renderer/asset_path.h>
#include <renderer/ray_trace.h>
#include <voxel/hull_connectivity.h>
#include <renderer/glow_region.h>
#include <renderer/node_anim.h>
#include <renderer/bridge_node_anim_store.h>
#include <renderer/model_parts.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <assets/cache.h>
#include <assets/decal_override.h>
#include <assets/hull_source.h>
#include <assets/mesh_fix.h>
#include <assets/model_compose.h>
#include <assets/texture.h>
#include <nif/file.h>
#include <nif/scene_camera.h>
#include <platform/folder_picker.h>

#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/matrix_inverse.hpp>
#include <array>
#include <cstdio>
#include <unordered_set>
#include "developer_mode.h"

#ifdef DAUNTLESS_ENABLE_CEF
#include "ui_cef/cef_lifecycle.h"
#endif

#include <cmath>
#include <limits>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <map>
#include <fstream>
#include <iterator>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <functional>
#include <vector>

namespace py = pybind11;

// Toggle for the HDR resolve pass. Defined in frame.cc (librenderer).
// Forward-declared here (before the anonymous namespace) so frame() inside
// the anonymous namespace can call dauntless_hdr::enabled().
namespace dauntless_hdr {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
namespace dauntless_hdr_lens_flare {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
namespace dauntless_procedural_sky {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
// Developer diagnostic: opaque.frag reports the non-finite shading term as a
// code in alpha. Driven from nonfinite_probe_set_enabled (see below).
namespace dauntless_nan_debug {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
// Forward-declared here (before the anonymous namespace) so the space render
// phases inside the anonymous namespace can read the always-on hull-breach
// gate.
namespace dauntless_hull_damage {
    bool enabled();            // defined in frame.cc
}
// Toggle for sun shadow maps. Defined in frame.cc. Forward-declared here so
// frame() can gate the shadow depth pre-pass on dauntless_shadows::enabled().
namespace dauntless_shadows {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
namespace dauntless_filmic {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
    float ambient_scale();     // defined in frame.cc (0.8 when on, 1.0 when off)
}
namespace dauntless_motion_blur {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
// Depth-of-field state. `enabled` is the Camera Realism master; `params`
// arrives whole from Python each frame. Deliberately no tuned defaults here
// -- engine/cameras/dof.py is the single home for every look-affecting
// number, so that tuning needs no rebuild.
namespace dauntless_dof {
namespace {
bool                 g_enabled = true;
renderer::DofParams  g_params;
}
bool enabled() { return g_enabled; }
void set_enabled(bool e) { g_enabled = e; }
const renderer::DofParams& params() { return g_params; }
void set_params(const renderer::DofParams& p) { g_params = p; }
}  // namespace dauntless_dof
namespace dauntless_warp_vfx {
    float streak_intensity(); float flash_intensity();
    glm::vec3 travel_dir();
    void set_streak(float); void set_flash(float); void set_travel(glm::vec3);
}
namespace dauntless_dash_vfx {
    float intensity();          // defined in frame.cc
    void set_intensity(float v); // defined in frame.cc
}
namespace dauntless_volumetric_nebulae {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
namespace dauntless_nebula_lightning {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
// Opaque-pass Fresnel rim gate + scale. Defined in frame.cc. The minor-rock
// pass draws outside FrameSubmitter, so it computes u_rim_strength here.
namespace dauntless_rim {
    bool enabled();            // defined in frame.cc
    float strength_scale();    // defined in frame.cc (kStrengthScale)
}
namespace dauntless_ambient_gradient {
    float strength();          // defined in frame.cc
    void  set_strength(float);  // defined in frame.cc
    void  set_enabled(bool);    // defined in frame.cc
}

namespace {

std::unique_ptr<renderer::Window> g_window;
scenegraph::World g_world;
// The floating render origin (VIEW-space, double). frame() subtracts it from
// every Space-pass instance's double translation before narrowing to the
// float matrix the passes read (World::resolve_render_space). Pushed from
// Python via set_render_origin; (0,0,0) = render space IS view space.
glm::dvec3 g_render_origin{0.0};

// What to add to a point computed from `inst.world` (RENDER space) to put it
// back in VIEW space: the origin that world was last resolved against, for a
// Space-pass instance; zero for Bridge/Comm, which never move with it. The
// bindings that hand inst->world-derived points to Python (node worlds,
// surface points, bounds, head centre) return VIEW space through this.
glm::dvec3 view_offset_of(const scenegraph::Instance& inst) {
    return inst.pass == scenegraph::Pass::Space ? g_world.render_origin()
                                                : glm::dvec3(0.0);
}

scenegraph::Camera g_camera;
renderer::Lighting g_lighting;
// Separate lighting state for the bridge pass. Populated by the Python
// host loop via set_bridge_lighting() each tick, mirroring the space
// pass's set_lighting() flow. Decoupled because the bridge interior's
// ambient is authored on its own SetClass and is typically much
// brighter than the space scene's.
renderer::Lighting g_bridge_lighting;
// Ambient multiplier for the bridge INTERIOR only (red-alert dim). Applied
// where the main bridge pass renders, never to the comm-set RTT feed — the
// viewscreen shows another ship's room, whose lighting must not follow our
// alert level.
float g_bridge_ambient_scale = 1.0f;
std::vector<renderer::Backdrop> g_backdrops;
bool g_sky_dirty = true;            // cubemap needs (re)baking
bool g_sky_last_procedural = false; // procedural-toggle state at the last frame
std::unique_ptr<renderer::BackdropPass> g_backdrop_pass;
std::vector<renderer::SunDescriptor> g_suns;
std::vector<glm::vec4> g_dust_planets;   // xyz = world pos, w = radius
float g_dust_profile = 0.0f;   // radial-profile `dust` column at the camera, 0-1
std::unique_ptr<renderer::SunPass> g_sun_pass;
std::unique_ptr<renderer::DustPass> g_dust_pass;
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md). The
// field is pure CPU state stepped in frame()'s xform_sync block; the pass owns
// GL (VAOs, instance buffer) and lives with the context like the other passes.
renderer::minors::MinorField g_minor_field;
std::unique_ptr<renderer::MinorPass> g_minor_pass;
bool g_minors_enabled = true;
std::optional<scenegraph::InstanceId> g_minor_player;
// What the last frame actually drew, summed over every target that drew
// minors (main view, or the bridge viewscreen RTT). Zeroed each frame.
int g_minor_draw_calls = 0;
int g_minor_drawn = 0;
// Reused per-target bins: each drawn target re-bins the field against its own
// camera and height (MinorField::build_bins), never the step's g_camera bins.
std::vector<renderer::minors::Bin> g_minor_target_bins;
// Model-space hull AABB per model handle, for the player's contact box.
// compute_model_aabb walks every vertex, so it runs once per handle; cleared
// with the handles (reset_frame_state) because handles are reissued.
std::unordered_map<std::uint64_t, renderer::Aabb> g_minor_player_aabbs;
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md). The field
// is pure CPU state, built per DRAWN camera in render_space_geometry (main
// view or viewscreen RTT); the pass owns GL (atlases, VAOs) like g_minor_pass.
renderer::far::FarField g_far_field;
std::unique_ptr<renderer::FarPass> g_far_pass;
// Atlas paths by catalogue index (far_set_catalogue). Like the FarField's
// catalogue they outlive a session -- not mission content -- and init() hands
// them to each new FarPass, so a catalogue pushed with the host down draws.
std::vector<std::pair<std::string, std::string>> g_far_atlas_paths;
bool g_far_enabled = true;
// Rock-real Part 1 (2026-10-03) strip-back: two toggles INDEPENDENT of
// g_far_enabled (the master switch, which still disables everything when
// off). Each gates only its own band's build + every draw of it (solid and
// fading). Off by default while rock fields are rebuilt band by band
// (Mark, 2026-10-03).
bool g_rock_mid_enabled = false;
// spike/rock-specks: the volumetric haze is replaced by puffs (below); its
// toggle stays for comparison.
bool g_rock_haze_enabled = false;
// Rock-field puffs (SPIKE): soft lit billboards placed by the field density,
// drawn in the MSAA pass after every opaque writer.
bool g_rock_puffs_enabled = true;
renderer::rockfield::PuffField g_puff_field;
int g_rock_puffs_drawn = 0;
// Rock-field speck band (SPIKE, spike/rock-specks 2026-10-04): the near
// band's large rocks past their billboard edge as GPU-faded specks.
bool g_rock_specks_enabled = true;
renderer::rockfield::SpeckBand g_speck_band;
bool g_speck_upload = false;        // instances changed since the last upload
int g_rock_specks_drawn = 0;        // instances submitted (GPU culls/fades them)
// The last camera's build; reused across cameras so the vectors keep their
// capacity. Its specks and g_minor_specks draw in ONE render_specks call.
renderer::far::FarOutput g_far_out;
std::vector<renderer::SpeckGpu> g_minor_specks;
std::vector<renderer::SpeckGpu> g_far_speck_staging;
// Instance keys currently flagged (far_set_rocks): an instance unflagged, or
// every one when the tier is disabled/cleared, gets far_fade written back to 0
// so a stale fade can never hide its mesh.
std::vector<std::uint64_t> g_far_flagged_keys;
// What the last frame built and drew, summed over its drawn cameras.
int g_far_impostors = 0;
int g_far_specks = 0;
int g_far_draw_calls = 0;
// Rock fields near band (docs/superpowers/specs/2026-10-02-rock-fields-design.md).
// Pure CPU state streamed + stepped in frame()'s xform_sync block around the
// player (or the main camera), built per DRAWN camera in render_space_geometry
// and drawn through g_minor_pass (meshes) and g_far_pass (billboards). Gated
// on g_far_enabled with the rest of the far tier.
renderer::rockfield::NearField g_near_field;
renderer::rockfield::NearOutput g_near_out;
// What NearField was last handed (far_set_catalogue), and each list slot's
// fragment (lod0/lod1 handles + bound) for the near FragmentLookup. Model
// handles die with the session, so reset_frame_state empties all three.
renderer::rockfield::NearCatalogue g_near_catalogue;
std::vector<renderer::minors::Fragment> g_near_small_frags;
std::vector<renderer::minors::Fragment> g_near_large_frags;
// > 0: the player's LARGE-rock contact box half extents x this (shields up).
float g_near_shield_inflate = 0.0f;
// The near band's own contact player (rockfield_set_player, pushed every
// frame by far_tier.reconcile). Its own, not the minors' g_minor_player:
// that one is pushed only while Minor Rocks is on and has a catalogue, and
// scenery collisions must not hang off the minors toggle.
std::optional<scenegraph::InstanceId> g_near_player;
// What the last frame built, summed over its drawn cameras.
int g_near_meshes = 0;
int g_near_billboards = 0;   // solid/dithered + translucent
int g_near_fading = 0;       // translucent (rock fade): drawn in rock.fade.draw
// Rock fields mid band: one baked collection sprite per tile, in three nested
// tile levels. Pure CPU: fed the far tier's active sources, built per DRAWN
// camera in render_space_geometry and drawn through g_far_pass (collection
// atlases occupy the slots after the catalogue's). Gated on g_far_enabled.
// The collections are not mission content (as the catalogue), so a session
// reset keeps them.
renderer::rockfield::MidField g_mid_field;
renderer::rockfield::MidOutput g_mid_out;
// What the last frame drew / examined, summed over its drawn cameras.
int g_mid_sprites = 0;       // solid + translucent
int g_mid_fading = 0;        // translucent (rock fade): drawn in rock.fade.draw
int g_mid_tiles = 0;
std::vector<renderer::NebulaVolume> g_nebulae;
std::vector<renderer::NebulaWakePoint> g_nebula_wake;   // world pos, faded strength, pod size
std::unique_ptr<renderer::NebulaPass> g_nebula_pass;
std::unique_ptr<renderer::NebulaVolumetricPass> g_nebula_volumetric_pass;
// System-scale nebula (star-centred atmosphere). DEVELOPER-ONLY: frame()
// runs it only under --developer with Volumetric Nebulae on.
std::unique_ptr<renderer::SystemNebulaPass> g_system_nebula_pass;
std::vector<renderer::GodrayFlash> g_nebula_godrays;
std::unique_ptr<renderer::NebulaGodrayPass> g_nebula_godray_pass;
std::unique_ptr<renderer::ShieldPass> g_shield_pass;
std::vector<renderer::LensFlareDescriptor> g_lens_flares;
std::unique_ptr<renderer::LensFlarePass>   g_lens_flare_pass;
std::vector<renderer::TorpedoDescriptor>   g_torpedoes;
std::unique_ptr<renderer::TorpedoPass>     g_torpedo_pass;
// Full-replace per-frame dynamic-light list (Task 10). Empty in production
// until Task 11 wires a real emitter (torpedo glow); consumed only by the
// Space-pass opaque submit below.
std::vector<renderer::DynamicLightDescriptor> g_dynamic_lights;
std::vector<renderer::ShockwaveDescriptor> g_shockwaves;
std::unique_ptr<renderer::ShockwavePass>   g_shockwave_pass;
std::vector<renderer::HitVfxDescriptor>    g_hit_vfx;
std::unique_ptr<renderer::HitVfxPass>      g_hit_vfx_pass;
std::vector<renderer::HullDischarge>       g_hull_discharges;
std::unique_ptr<renderer::HullDischargePass> g_hull_discharge_pass;
std::unique_ptr<renderer::NebulaWakePass> g_nebula_wake_pass;
std::vector<renderer::ParticleEmitterDescriptor> g_particle_emitters;
std::unique_ptr<renderer::ParticlePass>          g_particle_pass;
std::vector<renderer::PhaserBeamDescriptor> g_phaser_beams;
// Tractor beams reuse the weapon-agnostic PhaserBeamDescriptor + PhaserPass —
// only the data list is separate (honest naming; rendered by g_phaser_pass).
std::vector<renderer::PhaserBeamDescriptor> g_tractor_beams;
std::vector<renderer::PhaserBeamDescriptor> g_spv_overlay_beams;
std::unique_ptr<renderer::PhaserPass>      g_phaser_pass;
renderer::HologramShip                       g_hologram_ship;
std::unique_ptr<renderer::HologramPass>      g_hologram_pass;
// Cloaking ships drawn as refractive shells this frame (set each frame from
// Python via set_cloak_ships). The pass bends + chromatically disperses the
// scene behind each hull; empty list → zero GL work.
std::vector<renderer::CloakShipDescriptor>   g_cloak_ships;
std::unique_ptr<renderer::CloakRefractionPass> g_cloak_pass;
std::unique_ptr<renderer::BreachPass>        g_breach_pass;
// Shared static original-fill cache: the UNCARVED hull fill + its GL_R8 3D
// texture are built once per hull source path (not per-instance) and consumed
// ONLY by the breach pass as a material mask (fill >= iso → solid interior;
// discard otherwise). The opaque hull clip is a pure sphere test — it needs no
// fill texture. Owns GL textures; lives/dies with the GL context.
std::unique_ptr<renderer::CarveFieldCache>   g_carve_cache;
// Per-instance mutable hull damage field (hull-volume-field-transport Task
// 6): carved alongside HullCarveField (the sphere ring above) on every
// hull_carve_add deposit, via renderer::hull_carve_deposit, using the SAME
// body-frame centre/normal/derived visible radius the sphere receives. Unlike
// g_carve_cache (one STATIC original-fill texture per hull SOURCE), this one
// is keyed per INSTANCE and mutable -- every damaged ship gets its own
// battle-scarred copy. Owns GL atlas textures; lives/dies with the GL
// context, like every other *_pass/*_cache global here.
//
// KNOWN, ACCEPTED CONSEQUENCE (hull-volume-field-transport plan 2a; the fix
// is plan 2b's job, not this one's): the breach scoop (submit_carve_stencil
// above, breach.vert/frag) still derives its geometry ENTIRELY from the
// sphere ring, which this plan deliberately leaves in place. The field has
// no such 24-slot ceiling, so a carve that never fit in the ring -- the 25th+
// on one hull, or one merged into a slot the ring later evicts -- cuts a
// real hole in opaque.frag via this cache, but the scoop never draws
// anything behind it (submit_carve_stencil only stamps for instances with
// carve.count() > 0, and only where a sphere still exists to be stamped from).
// The result is a genuine see-through hole rather than a filled cavity for
// any carve past the ring's capacity. This project has previously chosen "a
// hole is a hole" over a wrongly-filled hole (see backing-material gate,
// carve_field_cache.h), so this is the accepted failure mode here, not a bug
// to chase -- expect it in a live death-cascade past 24 accumulated carves.
std::unique_ptr<renderer::InstanceFieldCache> g_instance_field_cache;
std::vector<renderer::SubsystemPin>          g_subsystem_pins;
std::unique_ptr<renderer::SubsystemPinPass>  g_subsystem_pin_pass;
// Developer debug overlay (Ship Property Viewer "Glow Regions" toggle):
// world-space wireframe cylinders set each frame from Python. Empty list →
// zero GL work; only rendered in viewer_mode.
std::vector<renderer::DebugCylinder>         g_debug_cylinders;
std::vector<renderer::DebugBox>              g_debug_boxes;
std::vector<renderer::DebugSphere>           g_debug_spheres;
std::vector<renderer::DebugCone>             g_debug_cones;
std::unique_ptr<renderer::DebugVolumePass>   g_debug_volume_pass;
// Ship Property Viewer transform gizmo: three coloured arrows set each frame
// from Python. length == 0 -> hidden (production frames never touch it, so
// the render path stays byte-identical when unset).
renderer::GizmoPass::Gizmo                   g_transform_gizmo;
std::unique_ptr<renderer::GizmoPass>         g_gizmo_pass;
renderer::TargetReticle                      g_target_reticle;
std::unique_ptr<renderer::TargetReticlePass> g_target_reticle_pass;
// Helm -> Set Course star map. Drawn into a scissored sub-rect of FBO 0 after
// the post chain resolves and before ui_cef::composite(), so the map is not
// tonemapped and the CEF modal chrome lands on top of it. It has its OWN
// camera (an orbit rig anchored on the player's system, driven from
// engine/ui/star_map.py) -- g_camera is the gameplay camera and is still
// rendering the live scene around the modal.
renderer::StarMapScene                       g_starmap_scene;
scenegraph::Camera                           g_starmap_camera;
std::unique_ptr<renderer::StarMapPass>       g_starmap_pass;
// "Hologram-only" frame mode: when on (set by the Ship Property Viewer while
// open), frame() clears to g_hologram_bg and skips both the space scene and the
// bridge pass, drawing only the hologram + subsystem pins.
bool      g_hologram_only_mode = false;
glm::vec3 g_hologram_bg{0.0f, 0.0f, 0.0f};
// Ship Property Viewer render mode: when true, the inspected ship is drawn with
// its real hull textures (full opaque lighting) instead of the Fresnel
// hologram. Default false = hologram. Only consulted while g_hologram_ship is
// active (i.e. the viewer is open).
bool      g_spv_hull_mode = false;
std::unique_ptr<renderer::BridgePass>      g_bridge_pass;
std::unique_ptr<renderer::HdrTarget>       g_hdr_target;
// Multisample target for the opaque space pass. Constructed unconditionally
// but allocates NO GL objects until resize() is called with samples >= 2,
// which only happens when the player has actually selected an MSAA mode.
std::unique_ptr<renderer::HdrMsaaTarget>   g_msaa_target;
std::unique_ptr<renderer::HdrTarget>       g_viewscreen_hdr;
std::unique_ptr<renderer::BloomPass>       g_bloom_pass;
// Developer-only NaN/Inf detector for the HDR target. Off by default even under
// --developer: it inspects every texel and does a synchronous readback.
std::unique_ptr<renderer::NonfiniteProbe>  g_nonfinite_probe;
// opaque.frag's u_nan_debug cause codes, index == code. Keep in lockstep with
// the if/else chain at the end of that shader's main().
const char* const kNanCauseNames[] = {
    "none",
    "n (normalize(v_normal_ws) - zero/degenerate vertex normal)",     //  1
    "V (view vector - camera at the fragment)",                       //  2
    "sun_sf (sun_shadow_factor)",                                     //  3
    "lit_dir (directional diffuse)",                                  //  4
    "spec_acc (specular - normalize(L+V) with L == -V)",              //  5
    "lit_dyn (dynamic lights - cone 0/0, or att*nl*Inf)",             //  6
    "n_body (body-frame normal)",                                     //  7
    "base.rgb (base colour texture)",                                 //  8
    "decal_emissive (damage-decal ember / heat-glow)",                //  9
    "glow_flicker (decal glow flicker)",                              // 10
    "lit (combined diffuse, post-decal soot mix)",                    // 11
    "spec (specular * specular map)",                                 // 12
    "rim (Fresnel rim)",                                              // 13
    "nac/region_gain (glow_region_mult)",                             // 14
    "glow_rgb (hue_rotate of the glow map)",                          // 15
    "self_illum (self illumination)",                                 // 16
    "final_color (finite inputs, non-finite result)",                 // 17
};
bool        g_nfprobe_enabled   = false;
std::string g_nfprobe_dump_dir;              // absolute; empty = no PNG dumps
int         g_nfprobe_max_dumps = 8;         // cap so a steady source can't fill the disk
int         g_nfprobe_dumps     = 0;
long long   g_nfprobe_frames    = 0;         // frames probed
long long   g_nfprobe_hits      = 0;         // frames holding a non-finite texel
bool        g_nfprobe_dump_pending = false;  // set at probe time, serviced pre-swap
std::vector<std::pair<int, int>> g_nfprobe_last_cells;  // grid coords, bottom-left origin
std::unique_ptr<renderer::LensFlareHdrPass> g_lens_flare_hdr_pass;  // image-based screen-space flare
std::unique_ptr<renderer::ResolvePass>     g_resolve_pass;
std::unique_ptr<renderer::LdrTarget>       g_ldr_target;
std::unique_ptr<renderer::LdrTarget>       g_ldr_target2;   // SMAA→filmic intermediate
std::unique_ptr<renderer::FilmicPass>      g_filmic_pass;
std::unique_ptr<renderer::SmaaPass>        g_smaa_pass;
std::unique_ptr<renderer::MotionBlurPass>  g_motion_blur_pass;
std::unique_ptr<renderer::DofPass>    g_dof_pass;
std::unique_ptr<renderer::HdrTarget>  g_dof_target;
glm::mat4 g_prev_viewproj = glm::mat4(1.0f);   // previous exterior frame proj*view
glm::dvec3 g_prev_viewproj_origin{0.0};       // the render origin g_prev_viewproj was in
bool      g_have_prev_viewproj = false;         // false until first exterior frame
// Motion blur is normalised to this frame rate. At or above it the shutter
// scale is 1.0 and the blur is exactly as tuned; below it the blur shrinks in
// proportion, instead of growing because the frame took longer.
constexpr double kMotionBlurRefDt = 1.0 / 60.0;
// Sun shadow map: depth-only caster FBO rendered once per frame from the sun's
// POV (see frame()), shared by the main view and the viewscreen RTT. Owned here
// so its GL handles are released in shutdown() while the context is current.
std::unique_ptr<renderer::ShadowMapTarget> g_shadow_target;
bool g_smaa_enabled = true;   // post-process SMAA 1x; default on. Set by smaa_set_enabled.
// Requested MSAA sample count for the opaque space pass. 0 == off, which is
// the stock path: no multisample target is allocated and no blit occurs.
// Set by msaa_set_samples; clamped against GL_MAX_SAMPLES at apply time.
int g_msaa_samples = 0;
double g_prev_frame_time_seconds = 0.0;
float g_decal_game_time = 0.0f;  // game-time secs for decal ember; set by damage_decals_tick

// Bridge pass state. Camera is set from Python via set_bridge_camera each
// tick when bridge mode is active. The pass renders after the dust pass;
// see frame().
scenegraph::Camera g_bridge_camera;
bool g_bridge_pass_enabled = false;
bool g_viewscreen_enabled = false;

// Fixed resolution of the viewscreen render-to-texture feed (16:9). The screen
// quad is small, so this is plenty and keeps the second scene render cheap.
constexpr int kViewscreenRttW = 640;
constexpr int kViewscreenRttH = 360;

// Active comm source: when set, frame() renders this comm set from the given
// camera into the viewscreen RTT instead of the forward space feed.
struct CommSource { bool active = false; std::uint32_t set_id = 0; scenegraph::Camera cam; };
CommSource g_comm_source;

// Active scene source: when set (and no comm source is active), frame() renders
// the main exterior scene from this camera into the viewscreen RTT instead of
// the fixed forward g_camera feed. Drives ViewscreenZoomTarget (host_loop
// _viewscreen_scene_feed). active == false → byte-identical forward feed.
struct SceneSource { bool active = false; scenegraph::Camera cam; };
SceneSource g_scene_source;

// Viewscreen static/"snow" overlay: composited over the viewscreen RTT after
// the feed (comm or forward) is rendered. on/intensity are pushed per frame by
// host_loop (intensity = SDK fMin/fMax flicker); textures come from the
// "View Screen Static" icon group paths resolved in Python.
struct ViewscreenStatic { bool on = false; float intensity = 0.0f; };
ViewscreenStatic g_viewscreen_static;
std::unique_ptr<renderer::ViewscreenStaticPass> g_viewscreen_static_pass;

struct LoadedModel {
    std::filesystem::path nif_path;
    assets::ModelHandle handle;
    // Federation registry / hull-name swap key (BC ReplaceTexture). Empty for
    // the common no-replacement load. Part of the dedupe identity so two ships
    // of the same class with DIFFERENT registries get distinct handles, while
    // same-registry hulls collapse onto one.
    std::string replacements_key;
    // True only for models built by assemble_officer. Those models are wrapped
    // in a non-const shared_ptr (owned, mutable) so load_instance_clip can
    // safely const_cast and append clips. Cache-loaded models (load_model_impl)
    // are genuinely const; is_officer=false prevents any const_cast on them.
    bool is_officer = false;
    // Idempotency cache for load_instance_clip: maps the path string passed to
    // the call → first clip index appended for that path.  Keyed by the raw
    // path string so the lookup is exact-match (same as the dedup in
    // load_model_impl).  Only populated for officer models (is_officer=true).
    std::unordered_map<std::string, int> appended_clips;
};

std::unique_ptr<assets::AssetCache> g_cache;
// Hull-decal mask textures for set_instance_decals overrides, loaded once per
// path. Owns GL textures: cleared in shutdown() while the context is current
// (after every override that borrows its ids is dropped), and again in init().
assets::DecalMaskCache g_decal_mask_cache;
std::vector<LoadedModel> g_loaded_models;  // index = our public ModelHandle - 1

// Bridge-node animation store: the active non-skinned node clips (doors, chairs).
// A SET per instance, merged on sample — doors and chairs animate the same bridge
// node hierarchy and BC never arbitrates between them.
renderer::BridgeNodeAnimStore g_bridge_node_anims;

// The store is keyed by InstanceId::index (it must not depend on scenegraph, so it
// stays GL-free and unit-testable). World lookups need the full id, so keep it here.
std::unordered_map<std::uint32_t, scenegraph::InstanceId> g_bridge_node_ids;

// Resolve a model handle to its loaded asset (or nullptr). File-scope so both
// frame()'s draw lookup and the get_instance_bounds binding share one path.
const assets::Model* resolve_model(scenegraph::ModelHandle h) {
    if (h == 0 || h > g_loaded_models.size()) return nullptr;
    return g_loaded_models[h - 1].handle.get();
}

// Tracks key state from the previous frame() so key_pressed can detect
// rising edges. Only keys that have been queried via key_pressed appear
// here; lookup misses (key never queried) are treated as "previously up".
std::unordered_map<int, bool> g_prev_key_state;
// Mouse-button rising/falling-edge detection. Mirrors g_prev_key_state.
std::unordered_map<int, bool> g_prev_mouse_state;
std::unique_ptr<renderer::Pipeline> g_pipeline;
// FrameSubmitter is a unique_ptr (not a static instance) so its destructor —
// which calls glDeleteTextures on the white-fallback texture — runs from
// shutdown() while the GL context is still alive, not from process-exit
// static destruction order which would run after the Window is gone.
std::unique_ptr<renderer::FrameSubmitter> g_submitter;

// Parse one Python decal entry -- a 7-sequence (shape, origin3, u_axis3,
// v_axis3, normal3, depth, mask_path), exactly `hull_decals.DecalSpec` --
// into a native DecalRequest. Returns false (leaving *out untouched) on
// wrong arity or a non-numeric field; never throws. Mirrors model_build.cc's
// apply_decals tolerance: a malformed entry must not stop a ship load
// (spec S5), so the caller skips it and warns once instead of propagating
// a TypeError out of load_model.
bool parse_decal_request(const py::handle& item, assets::DecalRequest* out) {
    try {
        auto seq = item.cast<py::sequence>();
        if (seq.size() != 7) return false;

        auto parse_vec3 = [](py::handle h) -> glm::vec3 {
            auto v = h.cast<py::sequence>();
            if (v.size() != 3) throw std::runtime_error("decal vector arity");
            return glm::vec3(v[0].cast<float>(), v[1].cast<float>(), v[2].cast<float>());
        };

        assets::DecalRequest req;
        req.shape  = seq[0].cast<std::string>();
        req.origin = parse_vec3(seq[1]);
        req.u_axis = parse_vec3(seq[2]);
        req.v_axis = parse_vec3(seq[3]);
        req.normal = parse_vec3(seq[4]);
        req.depth  = seq[5].cast<float>();
        req.mask   = seq[6].cast<std::string>();
        *out = std::move(req);
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

scenegraph::ModelHandle load_model_impl(
    const std::string& nif_path,
    const py::object& texture_search_path,
    const py::object& texture_replacements,
    const py::object& decals,
    float scale) {
    if (!g_window) {
        throw std::runtime_error("load_model: init must be called first (asset upload needs a GL context)");
    }

    // Accept either a single str or a sequence of strs. Ship NIFs whose
    // textures live in their own per-ship directory plus a shared
    // SharedTextures/<class>/<LOD> fallback need the multi-dir form;
    // legacy single-path callers stay unchanged.
    std::vector<std::filesystem::path> search_paths;
    if (py::isinstance<py::str>(texture_search_path)) {
        search_paths.emplace_back(texture_search_path.cast<std::string>());
    } else {
        for (auto item : texture_search_path) {
            search_paths.emplace_back(item.cast<std::string>());
        }
    }

    // Federation registry / hull-name swaps: a list of (old_substring,
    // new_texture) pairs. None / empty leaves the model byte-identical.
    std::vector<assets::TextureReplacement> replacements;
    std::string rep_key;
    if (!texture_replacements.is_none()) {
        for (auto item : texture_replacements) {
            auto pair = item.cast<py::sequence>();
            assets::TextureReplacement r;
            r.old_substring = pair[0].cast<std::string>();
            r.new_texture   = pair[1].cast<std::string>();
            rep_key += r.old_substring + '=' + r.new_texture + ';';
            replacements.push_back(std::move(r));
        }
    }

    // Hull-name decals: a list of 7-sequences (see parse_decal_request).
    // Every entry is passed on and folded into the dedupe key below; the
    // caps (16 placements, 4 distinct masks) are enforced by build_model.
    // None / empty leaves the model byte-identical, same as replacements.
    // Malformed entries are skipped (not thrown) and warned once, keyed by
    // nif_path + index so a mission that reloads the same bad decal list
    // every frame doesn't spam stderr.
    static std::unordered_set<std::string> warned_malformed_decals;
    std::vector<assets::DecalRequest> decal_requests;
    if (!decals.is_none()) {
        std::size_t index = 0;
        for (auto item : decals) {
            assets::DecalRequest req;
            if (parse_decal_request(item, &req)) {
                // Geometry included (lossless): an SPV placement edit keeps
                // shape + mask, and must not dedupe onto the stale handle.
                rep_key += "|decals:" + assets::decal_request_key(req);
                decal_requests.push_back(std::move(req));
            } else {
                const std::string key = nif_path + "|decal-arg|" + std::to_string(index);
                if (warned_malformed_decals.insert(key).second) {
                    std::fprintf(stderr,
                        "load_model: malformed decal entry %zu for %s "
                        "(expected a 7-sequence of shape, origin, u_axis, "
                        "v_axis, normal, depth, mask_path); skipping\n",
                        index, nif_path.c_str());
                }
            }
            ++index;
        }
    }

    // Uniform import scale (glTF only): folded into rep_key only when it
    // differs from the default, so every existing key (NIF loads, and glTF
    // loads at scale 1.0) stays byte-identical. Formatted by the same helper
    // as Model::source (%.6g) -- std::to_string's %f collapses tiny scales
    // (1e-7 and 2e-7 both "0.000000") onto one handle.
    if (scale != 1.0f) {
        const std::string src = assets::hull_source_string(nif_path, scale);
        rep_key += "|scale:" + src.substr(src.rfind("#s=") + 3);
    }

    // Dedupe by (nif_path, replacements, decals): callers that load the same
    // NIF + registry + decal set for multiple ships get the same handle and
    // the underlying assets::AssetCache::load isn't even called a second
    // time. Distinct registries or decal sets on the same NIF correctly
    // produce distinct handles.
    std::filesystem::path canonical = nif_path;
    for (std::size_t i = 0; i < g_loaded_models.size(); ++i) {
        if (g_loaded_models[i].nif_path == canonical &&
            g_loaded_models[i].replacements_key == rep_key) {
            return static_cast<scenegraph::ModelHandle>(i + 1);
        }
    }
    if (!g_cache) {
        assets::AssetCache::Config cfg;
        // Shield pass (model_aabb + skin-mesh build) walks mesh.cpu_data().
        // Without retention every Mesh::cpu_data() returns nullopt and the
        // shield bubble collapses to zero size.
        cfg.keep_cpu_data = true;
        // Resolved at EACH load, not captured here: the project asset root
        // is set once at boot (host_loop), after this cache may already
        // exist for tests, so a lambda -- not a stored path -- keeps this
        // live if that ever changes.
        cfg.mesh_fix_dir = [] {
            return std::filesystem::path(renderer::project_asset_root()) / "mesh_fixes";
        };
        g_cache = std::make_unique<assets::AssetCache>(std::move(cfg));
    }
    auto handle = g_cache->load(nif_path, search_paths, replacements, decal_requests, scale);
    LoadedModel lm;
    lm.nif_path         = std::move(canonical);
    lm.handle           = std::move(handle);
    lm.replacements_key = std::move(rep_key);
    g_loaded_models.push_back(std::move(lm));
    return static_cast<scenegraph::ModelHandle>(g_loaded_models.size());
}

// Per-frame state that Python pushes and frame() consumes. Called from BOTH
// init() and shutdown() so the two can never disagree about what a fresh
// session looks like.
//
// THE INVARIANT: any global frame() reads, and that a Python binding can write
// while the host is down, must be cleared by init() as well as shutdown(). The
// _dauntless_host module object outlives an init/shutdown pair and none of the
// setters check for a window, so anything pushed between sessions is stale
// content rendered into what the next caller believes is a fresh scene.
//
// It first surfaced as a test-isolation failure (tests/host/
// test_backdrops_integration's empty-backdrop row is asserted FLAT; it read 53
// with no preceding tests, 63 after 39, and 77-94 after 636 -- monotonic in how
// much leftover VFX had piled up), but the bug is not confined to tests:
// anything that re-inits the host inherits the previous scene's beams,
// torpedoes, lights, debris, hologram mode and reticle.
//
// Pinned by tests/host/test_init_resets_frame_state.py, which dirties every
// reachable global and then diffs the source of the two functions so the NEXT
// descriptor list cannot be added to one end only.
//
// NOT here, deliberately: g_world, g_loaded_models, the model-radius cache and
// the pass objects. Those own GL handles or are rebuilt by init(), and their
// ORDER relative to the GL-context teardown in shutdown() is load-bearing.
// Far tier: a FarField key is minor_instance_key()'s (index << 32 | generation).
scenegraph::Instance* far_instance_of(std::uint64_t key) {
    const scenegraph::InstanceId id{static_cast<std::uint32_t>(key >> 32),
                                    static_cast<std::uint32_t>(key & 0xffffffffu)};
    return g_world.get(id);
}

// Write far_fade = 0 (mesh only) on every currently flagged instance that
// still exists. Called whenever the tier stops owning those fades: disabled,
// cleared, or a rock unflagged (far_set_rocks).
void far_zero_fades(const std::vector<std::uint64_t>& keys) {
    for (const std::uint64_t key : keys)
        if (scenegraph::Instance* inst = far_instance_of(key)) inst->far_fade = 0.0f;
}

void reset_frame_state() {
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_ambient_scale = 1.0f;
    g_bridge_pass_enabled = false;
    g_viewscreen_enabled = false;
    g_backdrops.clear();
    g_sky_dirty = true;
    g_suns.clear();
    g_dust_planets.clear();
    g_dust_profile = 0.0f;
    g_nebula_godrays.clear();
    g_nebulae.clear();
    g_nebula_wake.clear();

    // Fifteen per-frame descriptor lists: eleven VFX + four debug volumes.
    g_torpedoes.clear();
    g_phaser_beams.clear();
    g_tractor_beams.clear();
    g_hit_vfx.clear();
    g_shockwaves.clear();
    g_particle_emitters.clear();
    g_dynamic_lights.clear();
    g_lens_flares.clear();
    g_hull_discharges.clear();
    g_cloak_ships.clear();
    g_subsystem_pins.clear();
    g_debug_cylinders.clear();
    g_debug_boxes.clear();
    g_debug_spheres.clear();
    g_debug_cones.clear();

    // Ship Property Viewer state. g_hologram_only_mode is the worst of these
    // to leak: it makes frame() skip the entire space scene and bridge pass.
    g_spv_overlay_beams.clear();
    g_hologram_ship = renderer::HologramShip{};
    g_hologram_only_mode = false;
    g_spv_hull_mode = false;
    g_transform_gizmo.length = 0.0f;   // hidden until Python sets a gizmo

    g_target_reticle = renderer::TargetReticle{};
    g_starmap_scene = renderer::StarMapScene{};

    // Motion blur reprojects against the previous exterior frame's viewproj.
    // Left set, frame 1 of a new session smears against the OLD camera.
    g_have_prev_viewproj = false;

    // The floating render origin: a new session starts at (0,0,0). Left set,
    // the next session's first frames draw every Space instance offset by
    // the last session's camera eye until Python pushes its own origin.
    g_render_origin = glm::dvec3(0.0);

    // Rising/falling-edge maps: a stale entry reports a phantom key/button
    // release on the first frame of the next session.
    g_prev_key_state.clear();
    g_prev_mouse_state.clear();

    // g_covered (native/src/renderer/letterbox_pass.cc) is a TU-static, not
    // owned by this file, and _pump_letterbox re-establishes it from Python
    // state every frame before r.frame() runs -- but letterbox_set() is a
    // binding like any other and can be called with the host down, so zero it
    // here with the rest.
    renderer::letterbox::set_covered(0.0f);

    // Per-instance decal overrides (set_instance_decals). Keyed by full
    // InstanceId and borrowing g_decal_mask_cache's texture ids: a new
    // session's world recycles ids from scratch, so none may survive.
    renderer::clear_instance_decal_overrides();

    // Minor rocks: clouds, fragment tables, pending contacts and the player's
    // previous pose all belong to the old session. MinorPass VAOs are keyed
    // on model handles, which a new session reissues from 1.
    g_minor_field.clear();
    g_minor_field.reset_player();
    g_minor_field.set_dials({});
    g_minors_enabled = true;
    g_minor_player.reset();
    g_minor_draw_calls = 0;
    g_minor_drawn = 0;
    g_minor_target_bins.clear();
    g_minor_player_aabbs.clear();
    // Belt-and-braces: on both real paths the pass is null here (init() calls
    // this before make_unique; shutdown() resets the pass first), and a fresh
    // pass has no VAOs. It guards a future caller that resets mid-session.
    if (g_minor_pass) g_minor_pass->forget_models();

    // Far tier: sources, flagged rocks and frame belong to the old
    // session (the catalogue is not mission content and survives). Flagged
    // keys name instances of the old world, which init()/shutdown() have
    // already replaced, so there is no fade to write back here.
    g_far_field.clear();
    g_far_field.set_dials({});
    g_far_enabled = true;
    // Rock-real Part 1 strip-back (Mark, 2026-10-03): off by default while
    // rock fields are rebuilt band by band -- independent of g_far_enabled
    // above, which still gates everything when off.
    g_rock_mid_enabled = false;
    g_rock_haze_enabled = false;
    g_rock_specks_enabled = true;
    g_rock_puffs_enabled = true;
    g_puff_field.clear();
    g_puff_field.set_dials({});
    g_rock_puffs_drawn = 0;
    g_speck_band.set_catalogue({}, {});
    g_speck_band.set_sources({});
    g_speck_band.set_dials({});
    g_speck_band.set_near_dials({});
    g_speck_upload = true;
    g_rock_specks_drawn = 0;
    g_far_out = {};
    g_minor_specks.clear();
    g_far_speck_staging.clear();
    g_far_flagged_keys.clear();
    g_minor_field.set_specks(true, g_far_field.dials().tiers.p_min);
    g_far_impostors = 0;
    g_far_specks = 0;
    g_far_draw_calls = 0;
    // Near band: cells, contacts and sweep state belong to the old session,
    // and the catalogue's model handles are reissued by the new one.
    g_near_catalogue = {};
    g_near_small_frags.clear();
    g_near_large_frags.clear();
    g_near_field.set_catalogue({});
    g_near_field.set_sources({});
    g_near_field.set_dials({});
    g_near_field.clear();
    g_near_field.reset_player();
    g_near_out = {};
    g_near_shield_inflate = 0.0f;
    g_near_player.reset();
    g_near_meshes = 0;
    g_near_billboards = 0;
    g_near_fading = 0;
    // Mid band: sources and dials belong to the old session.
    g_mid_field.set_sources({});
    g_mid_field.set_dials({});
    g_mid_out = {};
    g_mid_sprites = 0;
    g_mid_fading = 0;
    g_mid_tiles = 0;
}

void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_dauntless_host: init called while host already initialized");
    }
    // Visible by default. Tests that need offscreen can set OPEN_STBC_HOST_HEADLESS=1.
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
    g_pipeline = std::make_unique<renderer::Pipeline>();
    g_submitter = std::make_unique<renderer::FrameSubmitter>();
    g_world = scenegraph::World{};
    g_loaded_models.clear();
    // ModelHandles are reissued from 1 after every g_loaded_models.clear();
    // drop the renderer's per-handle bounding-radius cache in lockstep or a
    // new model recycled onto an old handle inherits the old model's radius.
    renderer::reset_model_radius_cache();
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
    // Everything frame() consumes and Python can push: see reset_frame_state().
    reset_frame_state();
    // Empty after any shutdown(); cleared here too so the two ends agree.
    g_decal_mask_cache.clear();
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_sun_pass = std::make_unique<renderer::SunPass>();
    g_dust_pass = std::make_unique<renderer::DustPass>();
    g_minor_pass = std::make_unique<renderer::MinorPass>();
    g_far_pass = std::make_unique<renderer::FarPass>();
    g_far_pass->set_atlas_paths(g_far_atlas_paths);
    g_nebula_pass = std::make_unique<renderer::NebulaPass>();
    g_nebula_volumetric_pass = std::make_unique<renderer::NebulaVolumetricPass>();
    g_system_nebula_pass = std::make_unique<renderer::SystemNebulaPass>();
    g_nebula_godray_pass = std::make_unique<renderer::NebulaGodrayPass>();
    g_shockwave_pass = std::make_unique<renderer::ShockwavePass>();
    g_shield_pass = std::make_unique<renderer::ShieldPass>();
    g_lens_flare_pass = std::make_unique<renderer::LensFlarePass>();
    g_torpedo_pass = std::make_unique<renderer::TorpedoPass>();
    g_hit_vfx_pass = std::make_unique<renderer::HitVfxPass>();
    g_hull_discharge_pass = std::make_unique<renderer::HullDischargePass>();
    g_nebula_wake_pass = std::make_unique<renderer::NebulaWakePass>();
    g_particle_pass = std::make_unique<renderer::ParticlePass>();
    g_phaser_pass        = std::make_unique<renderer::PhaserPass>();
    g_hologram_pass      = std::make_unique<renderer::HologramPass>();
    g_cloak_pass         = std::make_unique<renderer::CloakRefractionPass>();
    g_breach_pass        = std::make_unique<renderer::BreachPass>();
    g_carve_cache        = std::make_unique<renderer::CarveFieldCache>();
    g_instance_field_cache = std::make_unique<renderer::InstanceFieldCache>();
    // The breach pass lazily loads its own animated interior texture
    // (game/data/Damage1..4.tga) on first draw — no host wiring needed.
    g_subsystem_pin_pass  = std::make_unique<renderer::SubsystemPinPass>();
    g_debug_volume_pass   = std::make_unique<renderer::DebugVolumePass>();
    g_gizmo_pass          = std::make_unique<renderer::GizmoPass>();
    g_target_reticle_pass = std::make_unique<renderer::TargetReticlePass>();
    g_starmap_pass        = std::make_unique<renderer::StarMapPass>();
    g_bridge_pass         = std::make_unique<renderer::BridgePass>();
    g_viewscreen_static_pass = std::make_unique<renderer::ViewscreenStaticPass>();
    g_hdr_target      = std::make_unique<renderer::HdrTarget>();
    g_msaa_target     = std::make_unique<renderer::HdrMsaaTarget>();
    g_viewscreen_hdr  = std::make_unique<renderer::HdrTarget>();
    g_bloom_pass   = std::make_unique<renderer::BloomPass>();
    g_nonfinite_probe = std::make_unique<renderer::NonfiniteProbe>();
    g_lens_flare_hdr_pass = std::make_unique<renderer::LensFlareHdrPass>();
    g_resolve_pass = std::make_unique<renderer::ResolvePass>();
    g_ldr_target   = std::make_unique<renderer::LdrTarget>();
    g_ldr_target2  = std::make_unique<renderer::LdrTarget>();
    g_filmic_pass  = std::make_unique<renderer::FilmicPass>();
    g_smaa_pass    = std::make_unique<renderer::SmaaPass>();
    g_motion_blur_pass = std::make_unique<renderer::MotionBlurPass>();
    g_dof_pass   = std::make_unique<renderer::DofPass>();
    g_dof_target = std::make_unique<renderer::HdrTarget>();
    g_shadow_target = std::make_unique<renderer::ShadowMapTarget>();
    g_shadow_target->resize(2048, 2048);
    g_prev_frame_time_seconds = glfwGetTime();
}

void shutdown() {
    // Destroy GL-handle owners BEFORE the GL context (g_window) goes away.
    // Order matters: pipeline shaders and the submitter's white-fallback
    // texture are GL objects that must be released while the context is
    // still current.
    g_submitter.reset();
    g_pipeline.reset();
    // Release the session-scoped damage-decal texture while this context is
    // still current; otherwise its id leaks into the next init()'s context and
    // collides with a 3D texture id there (GL_INVALID_OPERATION). See
    // renderer::reset_damage_decal_texture().
    renderer::reset_damage_decal_texture();
    // Same hazard for the collision-scuff normal map (renderer/scuff_texture.h).
    renderer::reset_scuff_normal_texture();
    // And for the hull-name decal masks' shared clamp sampler (units 8-11,
    // frame.cc).
    renderer::reset_decal_mask_sampler();
    // set_instance_decals masks: drop the overrides that borrow their ids
    // first, then release the textures while this context is current.
    renderer::clear_instance_decal_overrides();
    g_decal_mask_cache.clear();
    g_loaded_models.clear();
    // Handle-recycling hazard: see the matching call in init(). Pure CPU
    // state (no GL), safe regardless of context currency.
    renderer::reset_model_radius_cache();
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_backdrop_pass.reset();  // releases sphere + texture caches while the
                              // GL context is still alive.
    g_sun_pass.reset();
    g_dust_pass.reset();
    g_minor_pass.reset();     // releases VAOs + instance buffer (GL alive)
    g_far_pass.reset();       // releases atlases + VAOs + buffers (GL alive)
    g_nebula_pass.reset();
    g_nebula_volumetric_pass.reset();
    g_system_nebula_pass.reset();
    g_nebula_godray_pass.reset();
    g_shield_pass.reset();
    g_lens_flare_pass.reset();
    g_torpedo_pass.reset();
    g_shockwave_pass.reset();
    g_hit_vfx_pass.reset();
    g_hull_discharge_pass.reset();
    g_nebula_wake_pass.reset();
    g_particle_pass.reset();
    g_phaser_pass.reset();
    g_hologram_pass.reset();
    g_cloak_pass.reset();
    g_breach_pass.reset();   // releases the sphere mesh + fill textures while the GL context lives
    g_carve_cache.reset();   // releases the carved-fill 3D textures (GL alive)
    g_instance_field_cache.reset();  // releases every damaged instance's atlas (GL alive)
    g_subsystem_pin_pass.reset();
    g_debug_volume_pass.reset();
    g_gizmo_pass.reset();
    g_target_reticle_pass.reset();
    g_starmap_pass.reset();
    g_bridge_pass.reset();
    g_viewscreen_static_pass.reset();
    g_bloom_pass.reset();
    g_nonfinite_probe.reset();
    g_lens_flare_hdr_pass.reset();
    g_motion_blur_pass.reset();
    g_dof_target.reset();
    g_dof_pass.reset();
    g_smaa_pass.reset();
    g_filmic_pass.reset();
    g_ldr_target2.reset();
    g_ldr_target.reset();
    g_resolve_pass.reset();
    g_hdr_target.reset();
    g_msaa_target.reset();
    g_viewscreen_hdr.reset();
    g_shadow_target.reset();
    g_window.reset();
    // Every descriptor list, flag and cached matrix frame() consumes. Shared
    // with init() so the two ends cannot drift -- see reset_frame_state(). It
    // is pure CPU state, so it is safe here, after the GL context is gone.
    reset_frame_state();
}

bool should_close() {
    return !g_window || g_window->should_close();
}

// Sample active bridge-node clips into each instance's node_overrides.
// Called once per frame() after update_animations so skinned characters
// and non-skinned bridge geometry are both up to date before any draw pass.
void update_bridge_node_anims(double now) {
    for (std::uint32_t index : g_bridge_node_anims.instances()) {
        auto id_it = g_bridge_node_ids.find(index);
        if (id_it == g_bridge_node_ids.end()) { g_bridge_node_anims.stop(index); continue; }
        scenegraph::Instance* inst = g_world.get(id_it->second);
        if (!inst) {                                  // instance destroyed
            g_bridge_node_anims.stop(index);
            g_bridge_node_ids.erase(id_it);
            continue;
        }
        const assets::Model* m = resolve_model(inst->model_handle);
        if (!m) continue;
        inst->node_overrides = g_bridge_node_anims.sample(index, *m, now);
    }
}

// Recompose the world matrix of every store-bound instance from the transform
// store. Run once at the top of frame(), before anything reads inst->world, so
// a bound object's position/rotation never has to cross into Python and back
// as sixteen floats.
//
// Unbound instances (xform_index < 0) are untouched: they keep whatever
// set_world_transform last pushed. A stale handle (the object was collected
// but its render instance outlived it) unbinds itself and freezes on its last
// matrix rather than reading whatever object recycled the slot.
//
// The Transform& from at() is used immediately and never retained — the
// store's backing vector reallocates on growth.
void sync_instance_transforms_from_store() {
    dauntless::TransformStore& store = dauntless::transform_store();
    g_world.for_each_alive([&store](scenegraph::Instance& inst) {
        if (inst.xform_index < 0) return;
        const auto index = static_cast<std::uint32_t>(inst.xform_index);
        if (!store.valid(index, inst.xform_generation)) {
            inst.xform_index = -1;
            return;
        }
        // The translation stays DOUBLE here; it is narrowed only after the
        // render origin is subtracted (resolve_render_space, below).
        dauntless::compose_world_linear_translation(
            store.at(index), inst.xform_scale, inst.world_linear,
            inst.world_translation_d);
    });
}

// A player's contact box for this frame, or nullopt when there is no
// player, its instance is gone, or its model is unresolved. The hull AABB
// cache is per model handle, shared by the minors' and the near band's player.
std::optional<renderer::minors::PlayerBox> player_box_of(
        const std::optional<scenegraph::InstanceId>& player) {
    if (!player) return std::nullopt;
    const scenegraph::Instance* inst = g_world.get(*player);
    if (inst == nullptr) return std::nullopt;
    auto it = g_minor_player_aabbs.find(inst->model_handle);
    if (it == g_minor_player_aabbs.end()) {
        const assets::Model* m = resolve_model(inst->model_handle);
        if (m == nullptr) return std::nullopt;
        it = g_minor_player_aabbs.emplace(inst->model_handle,
                                          renderer::compute_model_aabb(*m)).first;
    }
    return renderer::minors::PlayerBox{inst->world, it->second.center,
                                       it->second.half_extents};
}

// One MinorField step for frame(). Instance anchors are keyed
// (index<<32)|generation and resolve to the instance's RENDER-space origin.
void step_minor_field(float viewport_h) {
    renderer::minors::StepInput in;
    in.game_time = g_decal_game_time;
    in.render_origin = g_world.render_origin();
    in.view = g_camera.view_matrix();
    in.proj = g_camera.proj_matrix();
    in.viewport_h = viewport_h;
    in.anchor_of = [](std::uint64_t key, glm::vec3& out) {
        const scenegraph::InstanceId id{static_cast<std::uint32_t>(key >> 32),
                                        static_cast<std::uint32_t>(key & 0xffffffffu)};
        const scenegraph::Instance* inst = g_world.get(id);
        if (inst == nullptr) return false;
        out = glm::vec3(inst->world[3]);
        return true;
    };
    in.player = player_box_of(g_minor_player);
    // A player that vanished this frame must not be swept from its last pose
    // when it (or a successor) reappears.
    if (!in.player) g_minor_field.reset_player();
    g_minor_field.step(in);
}

// Near band: stream around its own player's contact box (else the main
// camera eye), then step its contacts against that box. System = render
// origin + render position + the far frame's anchor, as the far haze
// computes it. A player that vanished is not swept from its last pose
// (NearField::step resets the sweep on an unset player).
void step_near_field() {
    const auto player = player_box_of(g_near_player);
    const glm::dvec3 to_sys = g_world.render_origin() + g_far_field.anchor();
    const glm::dvec3 centre_render = player
        ? glm::dvec3(player->world * glm::vec4(player->center_mu, 1.0f))
        : glm::dvec3(g_camera.eye);
    g_near_field.stream(centre_render + to_sys);
    if (g_rock_specks_enabled &&
        g_speck_band.stream(centre_render + to_sys, g_near_field.dials().dash_collapse_step_gu))
        g_speck_upload = true;
    renderer::rockfield::NearStepInput in;
    in.game_time = g_decal_game_time;
    in.render_origin = g_world.render_origin();
    in.anchor_sys = g_far_field.anchor();
    in.player = player;
    in.shield_inflate = g_near_shield_inflate;
    in.minor_dials = g_minor_field.dials();
    g_near_field.step(in);
}

// The near band's bins: slot = index into the catalogue's class list.
const renderer::minors::Fragment* near_fragment(int family, int slot) {
    const auto* frags = family == renderer::rockfield::kNearSmallFamily ? &g_near_small_frags
                      : family == renderer::rockfield::kNearLargeFamily ? &g_near_large_frags
                      : nullptr;
    if (frags == nullptr || slot < 0 || slot >= static_cast<int>(frags->size())) return nullptr;
    return &(*frags)[static_cast<std::size_t>(slot)];
}

void frame() {
    if (!g_window || !g_pipeline || !g_submitter) {
        throw std::runtime_error("_dauntless_host: frame called before init");
    }
    // Whole-frame scope. Everything below nests inside it, so the report's
    // top row is the real per-frame cost and the children account for it.
    // The RAII object outlives end_frame() below (both are at function scope);
    // that is fine and intended — end_frame() force-closes any scope still
    // open, and the trailing pop() on an already-ended frame is ignored.
    renderer::frame_timer().begin_frame();
    DAUNTLESS_FRAME_SCOPE("frame");

    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);

    // Route 3D scene into the HDR target. resize() is a no-op when unchanged.
    // Hologram-only mode (Ship Property Viewer open): clear to a solid colour
    // and skip the whole space scene + bridge pass, drawing just the hologram
    // and pins. The orbit camera is supplied via set_camera by the host loop.
    const bool viewer_mode = g_hologram_only_mode;

    auto lookup = resolve_model;

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;

    {
        // Store-bound instances first: everything below (animation, culling,
        // every draw pass) reads inst->world.
        DAUNTLESS_FRAME_SCOPE("xform_sync");
        sync_instance_transforms_from_store();
        // The floating render origin's one per-frame narrowing: every alive
        // instance's float `world` = [linear | float(translation_d - origin)]
        // (origin zero off the Space pass). Follows the sweep, which fills the
        // double translations; everything below reads the RENDER-space
        // inst->world it produces.
        g_world.resolve_render_space(g_render_origin);
        // Attached dynamic lights resolve through the SAME inst->world the
        // hull draws with this frame. Must follow the sweep + resolve
        // (store-bound ships) and every set_world_transform push
        // (interpolated ships, which landed before frame() was entered).
        renderer::resolve_attached_dynamic_lights(g_world, g_dynamic_lights);
        // Minor rocks step against the same RENDER-space inst->world the
        // hulls draw with: Instance anchors and the player's contact box.
        g_minor_draw_calls = 0;   // the draws below add to these, if they run
        g_minor_drawn = 0;
        g_far_impostors = 0;      // likewise the far tier's per-camera builds
        g_far_specks = 0;
        g_far_draw_calls = 0;
        g_near_meshes = 0;
        g_near_billboards = 0;
        g_near_fading = 0;
        g_rock_specks_drawn = 0;
        g_rock_puffs_drawn = 0;
        g_mid_sprites = 0;
        g_mid_fading = 0;
        g_mid_tiles = 0;
        if (g_minors_enabled) {
            DAUNTLESS_FRAME_SCOPE("space.minors.step");
            step_minor_field(static_cast<float>(fh));
        }
        if (g_far_enabled) {
            DAUNTLESS_FRAME_SCOPE("rock.near.stream");
            step_near_field();
        }
    }

    {
        DAUNTLESS_FRAME_SCOPE("anim");
        g_world.propagate();
        // SP2: rebuild each animated instance's bone palette for this frame BEFORE
        // anything consumes it (the space skinned draw and the bridge pass). Shares
        // the `now` wall clock with draw_model / flip controllers.
        renderer::update_animations(g_world, lookup, now);
        update_bridge_node_anims(now);
    }

    const bool bridge_active = !viewer_mode && g_bridge_pass_enabled && g_bridge_pass;
    const bool viewscreen_on = bridge_active && g_viewscreen_enabled;

    // ── Cubemap sky bake (static-per-system) ───────────────────────────────
    // The map-driven procedural sky is fixed per vantage; bake it once into a
    // cubemap (on first sight or when the descriptor diff flagged a change) and
    // sample it each frame instead of re-rendering 14 noise spheres. Stock-BC
    // and the unmapped-authored fallback keep the per-frame textured path.
    const bool sky_procedural = dauntless_procedural_sky::enabled();
    if (sky_procedural != g_sky_last_procedural) {
        g_sky_dirty = true;
        g_sky_last_procedural = sky_procedural;
    }
    const bool sky_bakeable =
        sky_procedural && renderer::backdrops_are_procedural(g_backdrops);
    bool sky_use_cubemap = false;
    if (sky_bakeable && g_backdrop_pass) {
        if (g_sky_dirty || !g_backdrop_pass->has_cubemap()) {
            DAUNTLESS_FRAME_SCOPE("sky.bake");
            g_backdrop_pass->bake(g_backdrops, *g_pipeline,
                                  static_cast<float>(now));
            g_sky_dirty = false;
        }
        sky_use_cubemap = g_backdrop_pass->has_cubemap();  // false if alloc failed
    }
    // The space scene renders in two phases.
    //
    // PHASE 1 (here) — depth-writing geometry: backdrop, suns, hulls, breach,
    // shields. It reads no scene textures, which is precisely why it can be
    // multisampled: nothing in it samples the surface it is drawing into.
    // Renders into EITHER the plain HDR target (msaa == nullptr, the stock
    // path) or a multisample target the caller then resolves into the HDR
    // target. Exactly one of hdr/msaa is non-null.
    //
    // PHASE 2 is render_space_vfx below; see its comment for why it can never
    // be multisampled.
    // `dyn_lights` is an explicit parameter rather than a captured global so
    // every call site has to state what it wants. The viewscreen passes
    // nullptr: emitter, torpedo and explosion lights are all suppressed on
    // that feed, leaving only the sun (a separate pass plus the directionals
    // in g_lighting, neither of which is a dynamic light).
    //
    // This is a CPU saving, not a fill saving. The RTT is only 640x360, but
    // select_instance_dynamic_lights runs PER INSTANCE and scores EVERY light
    // in the list, which costs the same at any resolution — and with the
    // bridge up that whole selection currently runs twice per frame.
    auto render_space_geometry = [&](const scenegraph::Camera& cam,
                                     renderer::HdrTarget* hdr,
                                     renderer::HdrMsaaTarget* msaa,
                                     float ambient_scale,
                                     const std::vector<renderer::DynamicLightDescriptor>*
                                         dyn_lights) {
        if (msaa != nullptr) msaa->bind(); else hdr->bind();
        // The drawn target's framebuffer size: the viewscreen RTT is
        // kViewscreenRtt{W,H}; the main view (plain or MSAA) is fw x fh.
        const bool to_viewscreen = hdr != nullptr && hdr == g_viewscreen_hdr.get();
        const float target_h = to_viewscreen ? static_cast<float>(kViewscreenRttH)
                                             : static_cast<float>(fh);
        const int target_w = to_viewscreen ? kViewscreenRttW : fw;
        // Instance::rim_strength's 0.1 default, gated + scaled as
        // FrameSubmitter does for every opaque instance (minors + impostors).
        const float rim = dauntless_rim::enabled()
            ? 0.1f * dauntless_rim::strength_scale() : 0.0f;
        if (g_far_pass) g_far_pass->reset_counts();
        // The translucent lists are drawn by render_space_vfx (rock.fade.draw)
        // for THIS camera: never replay a list a skipped build left behind.
        g_near_out.billboards_fading.clear();
        g_mid_out.sprites_fading.clear();
        // Far tier build for THIS camera, before the hull draw: it writes each
        // flagged rock's far_fade, which space.opaque reads (dither / skip).
        if (g_far_enabled) {
            DAUNTLESS_FRAME_SCOPE("space.far.build");
            renderer::far::BuildInput in;
            in.view = cam.view_matrix();
            in.proj = cam.proj_matrix();
            in.viewport_h = target_h;
            in.render_origin = g_world.render_origin();
            in.game_time = g_decal_game_time;
            in.world_of = [](std::uint64_t key, glm::mat4& world) {
                const scenegraph::Instance* inst = far_instance_of(key);
                // A hidden rock is unplaceable: fade 0, no impostor or speck.
                if (inst == nullptr || !inst->visible) return false;
                world = inst->world;
                return true;
            };
            g_far_field.build(in, g_far_out);
            // Impostor availability is one truth: a bin whose atlas cannot
            // load (loaded here, GL current, before space.opaque reads the
            // fades) drops that rock's impostor in FarField, and THIS camera
            // rebuilds, so the rock keeps its mesh instead of vanishing.
            if (g_far_pass) {
                bool dropped = false;
                for (const auto& bin : g_far_out.impostors)
                    if (!bin.items.empty() && !g_far_pass->has_atlas(bin.rock)) {
                        g_far_field.drop_impostor(bin.rock);
                        dropped = true;
                    }
                if (dropped) g_far_field.build(in, g_far_out);
            }
            for (const auto& [key, fade] : g_far_out.fades)
                if (scenegraph::Instance* inst = far_instance_of(key)) inst->far_fade = fade;
            for (const auto& bin : g_far_out.impostors)
                g_far_impostors += static_cast<int>(bin.items.size());
        }
        {
            DAUNTLESS_FRAME_SCOPE("space.backdrop");
            if (sky_use_cubemap)
                g_backdrop_pass->render_cubemap(cam, *g_pipeline);
            else
                g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                                        dauntless_procedural_sky::enabled(),
                                        static_cast<float>(now));
        }
        {
            DAUNTLESS_FRAME_SCOPE("space.suns");
            g_sun_pass->render(g_suns, cam, *g_pipeline, now);
        }
        {
            // The hull draw. No frustum or distance cull runs ahead of this —
            // every visible Space instance is submitted — so this scope is the
            // one to watch as ship counts grow.
            DAUNTLESS_FRAME_SCOPE("space.opaque");
            g_submitter->submit_opaque_in_pass(
                g_world, cam, *g_pipeline, lookup, g_lighting,
                scenegraph::Pass::Space, g_decal_game_time, g_carve_cache.get(),
                ambient_scale, dyn_lights, g_instance_field_cache.get());
        }
        // Minor rocks. The step culled against g_camera; this target may be
        // the bridge viewscreen RTT (its own camera, kViewscreenRttH tall) --
        // in bridge view, the ONLY space render -- so re-bin the stepped poses
        // against the camera and height actually drawn with.
        g_minor_specks.clear();
        if (g_minors_enabled && g_minor_pass) {
            DAUNTLESS_FRAME_SCOPE("space.minors.draw");
            int drawn = 0;
            // With the far tier on, the sub-min_pixel_radius band becomes
            // specks (drawn below with the far specks) instead of vanishing.
            g_minor_field.build_bins(cam.view_matrix(), cam.proj_matrix(), target_h,
                                     g_minor_target_bins, &drawn,
                                     g_far_enabled ? &g_minor_specks : nullptr);
            g_minor_pass->render(g_minor_field, g_minor_target_bins, cam, *g_pipeline,
                                 [](std::uint64_t h) { return resolve_model(h); },
                                 g_lighting, ambient_scale, rim);
            g_minor_draw_calls += g_minor_pass->last_draw_calls();
            g_minor_drawn += drawn;
        }
        // Near band for THIS camera: meshes through the minors' instanced
        // draw, billboards through the far impostor draw (catalogue atlases
        // FarPass already loads).
        if (g_far_enabled && g_far_pass && g_minor_pass) {
            DAUNTLESS_FRAME_SCOPE("rock.near.draw");
            renderer::rockfield::NearBuildInput in;
            in.view = cam.view_matrix();
            in.proj = cam.proj_matrix();
            in.viewport_h = target_h;
            in.render_origin = g_world.render_origin();
            in.anchor_sys = g_far_field.anchor();
            in.game_time = g_decal_game_time;
            in.lod0_pixel_radius = g_minor_field.dials().lod0_pixel_radius;
            g_near_field.build(in, g_near_out);
            g_minor_pass->render(near_fragment, g_near_out.meshes, cam, *g_pipeline,
                                 [](std::uint64_t h) { return resolve_model(h); },
                                 g_lighting, ambient_scale, rim);
            g_far_draw_calls += g_minor_pass->last_draw_calls();
            g_far_pass->render_impostors(g_near_out.billboards, cam, *g_pipeline, g_lighting,
                                         ambient_scale, rim);
            // billboards_fading draw translucent in render_space_vfx (rock.fade.draw).
            // A billboard bin whose atlas cannot load is skipped by
            // render_impostors (its rock still draws in the mesh tier); the
            // field is never mutated from the draw. Count what DREW.
            g_near_meshes += g_near_out.mesh_count;
            for (const auto& bin : g_near_out.billboards)
                if (!bin.items.empty() && g_far_pass->has_atlas(bin.rock))
                    g_near_billboards += static_cast<int>(bin.items.size());
            for (const auto& bin : g_near_out.billboards_fading)
                if (!bin.items.empty() && g_far_pass->has_atlas(bin.rock)) {
                    g_near_billboards += static_cast<int>(bin.items.size());
                    g_near_fading += static_cast<int>(bin.items.size());
                }
        }
        // Mid band for THIS camera: collection sprites through the far
        // impostor draw. A bin whose atlas cannot load is skipped by
        // render_impostors; nothing is mutated from the draw. Gated on
        // g_rock_mid_enabled too (rock-real Part 1 strip-back, 2026-10-03):
        // off skips the build AND every draw (solid and fading -- the
        // fading list was already cleared for this camera above, so a
        // skipped build leaves nothing stale for rock.fade.draw to replay).
        if (g_far_enabled && g_far_pass && g_rock_mid_enabled) {
            DAUNTLESS_FRAME_SCOPE("rock.mid.draw");
            renderer::rockfield::MidBuildInput in;
            in.view = cam.view_matrix();
            in.proj = cam.proj_matrix();
            in.viewport_h = target_h;
            in.render_origin = g_world.render_origin();
            in.anchor_sys = g_far_field.anchor();
            g_mid_field.build(in, g_mid_out);
            g_far_pass->render_impostors(g_mid_out.sprites, cam, *g_pipeline, g_lighting,
                                         ambient_scale, rim);
            // sprites_fading draw translucent in render_space_vfx (rock.fade.draw).
            g_mid_tiles += g_mid_out.tiles;
            for (const auto& bin : g_mid_out.sprites)
                if (!bin.items.empty() && g_far_pass->has_atlas(bin.rock))
                    g_mid_sprites += static_cast<int>(bin.items.size());
            for (const auto& bin : g_mid_out.sprites_fading)
                if (!bin.items.empty() && g_far_pass->has_atlas(bin.rock)) {
                    g_mid_sprites += static_cast<int>(bin.items.size());
                    g_mid_fading += static_cast<int>(bin.items.size());
                }
        }
        if (g_far_enabled && g_far_pass) {
            DAUNTLESS_FRAME_SCOPE("space.far.impostors");
            g_far_pass->render_impostors(g_far_out.impostors, cam, *g_pipeline, g_lighting,
                                         ambient_scale, rim);
        }
        // Stencil-mark where the hull was cut away, so the scoop below draws
        // only through real holes and never in open space. Must sit between the
        // hull draw and the breach pass; costs one extra draw per carved
        // instance and nothing at all when nothing is damaged.
        if (g_submitter && g_carve_cache) {
            DAUNTLESS_FRAME_SCOPE("space.carve_stencil");
            g_submitter->submit_carve_stencil(g_world, cam, *g_pipeline, lookup,
                                              scenegraph::Pass::Space,
                                              g_carve_cache.get(),
                                              g_instance_field_cache.get());
        }
        // Breach interior pass (raymarched-breach-interior Task 3): one
        // hull-mesh draw per DAMAGED instance -- the same geometry and the
        // same winding (cull BACK) the opaque pass drew, under the carve
        // stencil -- raymarching the
        // per-instance damage field per fragment to find the cavity wall,
        // masked by the original hull fill (triplanar Damage.tga). Runs
        // right after the opaque hull (depth-test/write on) so the interior
        // shows only through clip holes. Gated on
        // dauntless_hull_damage::enabled() inside the pass (no-op when off).
        if (g_breach_pass && g_carve_cache) {
            DAUNTLESS_FRAME_SCOPE("space.breach");
            g_breach_pass->render(g_world, cam, *g_pipeline, lookup,
                                  *g_carve_cache, g_instance_field_cache.get(),
                                  g_decal_game_time, g_lighting, ambient_scale);
        }
        // Far + minor specks in ONE instanced draw, after every opaque writer
        // (hull, minors, impostors, breach) so they depth-test against all of
        // it. render_specks leaves depth test/writes on, cull on, blend off --
        // the state space.shield's submit sets up from anyway.
        if (g_far_enabled && g_far_pass) {
            DAUNTLESS_FRAME_SCOPE("space.far.specks");
            g_far_speck_staging.clear();
            g_far_speck_staging.insert(g_far_speck_staging.end(),
                                       g_far_out.specks.begin(), g_far_out.specks.end());
            g_far_speck_staging.insert(g_far_speck_staging.end(),
                                       g_minor_specks.begin(), g_minor_specks.end());
            g_far_pass->render_specks(g_far_speck_staging, cam, *g_pipeline, g_lighting,
                                      ambient_scale, g_far_field.dials().speck_gain,
                                      target_w, static_cast<int>(target_h));
            g_far_specks += static_cast<int>(g_far_speck_staging.size());
        }
        // Puffs (SPIKE): soft lit billboards, depth-tested in the MSAA pass so
        // a hull in front antialiases against them like any geometry.
        if (g_far_enabled && g_far_pass && g_rock_puffs_enabled) {
            DAUNTLESS_FRAME_SCOPE("rock.puffs.draw");
            if (g_puff_field.take_dirty()) g_far_pass->upload_rock_puffs(g_puff_field.instances());
            const glm::vec3 offset = glm::vec3(g_puff_field.origin_sys() -
                                               (g_world.render_origin() + g_far_field.anchor()));
            g_far_pass->render_rock_puffs(offset, g_puff_field.dials(), cam, *g_pipeline,
                                          g_lighting, ambient_scale);
            g_rock_puffs_drawn += g_far_pass->rock_puff_count();
        }
        // Speck band (SPIKE): one instanced draw, radius + alpha on the GPU.
        // Phase 1, after every opaque writer AND the puffs: a speck writes no
        // depth, so drawn first every puff blended over it, nearer or not.
        if (g_far_enabled && g_far_pass && g_rock_specks_enabled && !g_speck_band.hidden()) {
            DAUNTLESS_FRAME_SCOPE("rock.specks.draw");
            if (g_speck_upload) {
                g_far_pass->upload_rock_specks(g_speck_band.instances());
                g_speck_upload = false;
            }
            renderer::FarPass::RockSpeckDraw d;
            d.offset = glm::vec3(g_speck_band.origin_sys() -
                                 (g_world.render_origin() + g_far_field.anchor()));
            d.in_gu = g_near_field.effective_dials().large.billboard_gu;
            d.in_fade_gu = g_near_field.effective_dials().fade_gu;
            const auto& sd = g_speck_band.dials();
            d.out_gu = sd.out_gu;
            d.out_fade_gu = sd.out_fade_gu;
            d.keep_d0_gu = sd.keep_d0_gu;
            d.keep_band = sd.keep_band;
            d.keep_power = sd.keep_power;
            d.gain = sd.gain;
            g_far_pass->render_rock_specks(d, cam, *g_pipeline, g_lighting, ambient_scale,
                                           g_far_field.dials().speck_gain,
                                           target_w, static_cast<int>(target_h));
            g_rock_specks_drawn += g_far_pass->rock_speck_count();
        }
        if (g_far_pass) g_far_draw_calls += g_far_pass->last_draw_calls();
        if (g_shield_pass) {
            DAUNTLESS_FRAME_SCOPE("space.shield");
            g_shield_pass->submit(g_world, cam, *g_pipeline, now, lookup);
        }
    };

    // PHASE 2 — everything transparent, additive, or reading the scene back,
    // rendered into `target` whose color/depth textures and viewport dims
    // (vw, vh) drive the framebuffer-coupled passes.
    //
    // ALWAYS single-sample, and that is a hard constraint rather than a
    // preference: nebula_volumetric samples target.depth_texture() to
    // terminate its raymarch, and both nebula_godray and cloak_pass sample
    // target.color_texture() as u_scene while drawing into that same target.
    // Those reads need a resolved, sampleable surface — a multisample
    // renderbuffer cannot be sampled by an ordinary sampler2D at all.
    //
    // The viewscreen RTT renders every pass the main view does — dust
    // (camera-anchored smear, keyed off for_viewscreen so the cockpit isn't
    // smeared except during warp streaking), nebulae, godrays, lens flares,
    // hull discharges, shockwaves, particles, and cloak refraction — so the
    // bridge viewscreen matches the exterior view.
    auto render_space_vfx = [&](const scenegraph::Camera& cam,
                                bool for_viewscreen,
                                renderer::HdrTarget& target,
                                int vw, int vh, float ambient_scale) {
        target.bind();
        // Dust is normally skipped on the viewscreen RTT (a camera-anchored
        // cockpit smear), but the WARP STREAK lives in this pass — so during
        // warp (streak > 0) we DO render it onto the viewscreen so the bridge
        // crew see the streaks too. Safe re: the dust pass's cross-frame state
        // (prev_eye_/warp_drift_phase_): the main and viewscreen render_space
        // calls are mutually exclusive per frame (main only when !bridge_active,
        // viewscreen only when bridge_active), so the state advances exactly
        // once per frame either way, and the viewscreen reuses g_camera's eye.
        const bool warp_streaking =
            dauntless_warp_vfx::streak_intensity() > 0.0f;
        if (g_dust_pass && (!for_viewscreen || warp_streaking)) {
            DAUNTLESS_FRAME_SCOPE("space.dust");
            g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets,
                                dauntless_warp_vfx::streak_intensity(),
                                dauntless_warp_vfx::travel_dir(),
                                g_world.render_origin(),
                                dauntless_dash_vfx::intensity(),
                                g_dust_profile);
        }
        // Belt haze: the unresolved remainder of every active disc source.
        // Samples target.depth_texture() on unit 0 while drawing into
        // `target` -- the same arrangement as nebula_volumetric's composite
        // and system_nebula below: depth test AND depth writes off for the
        // draw, so the depth attachment is only read, never written.
        // render_haze restores depth test/writes on, cull on, blend off.
        // Gated on g_rock_haze_enabled too (rock-real Part 1 strip-back,
        // 2026-10-03): off skips the draw for every camera.
        if (g_far_enabled && g_far_pass && g_rock_haze_enabled &&
            !g_far_field.active_sources().empty()) {
            DAUNTLESS_FRAME_SCOPE("rock.haze");
            g_far_pass->reset_counts();
            const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
            const glm::dvec3 origin_sys =
                g_world.render_origin() + glm::dvec3(cam.eye) + g_far_field.anchor();
            g_far_pass->render_haze(
                g_far_field.active_sources(), origin_sys, cam, *g_pipeline, g_lighting,
                ambient_scale, target.depth_texture(), inv_vp, g_far_field.dials());
            g_far_draw_calls += g_far_pass->last_draw_calls();
        }
        // Rock fade (2026-10-03): the near and mid impostors fading in from
        // (or out to) nothing, TRANSLUCENT, built for THIS camera by
        // render_space_geometry. Here in phase 2, straight AFTER the belt
        // haze, into the resolved single-sample target against its depth
        // (depth test on, no depth writes, premultiplied): the haze marches
        // to the scene depth, which a fading rock never writes, so drawn
        // before it the haze fogged the rock and popped when it turned solid.
        // Every phase-1 writer (hull, rocks, impostors, breach, specks,
        // shields) is underneath; dust (drawn above) is attenuated where a
        // fading rock lies behind it (accepted). No MSAA (accepted). Far to
        // near: the mid band (never nearer than mid in_lo_gu) before the near
        // band (never beyond its largest billboard_gu), each list already
        // sorted far to near by its build. Leaves blending off, depth
        // test/writes on.
        if (g_far_enabled && g_far_pass) {
            DAUNTLESS_FRAME_SCOPE("rock.fade.draw");
            g_far_pass->reset_counts();
            const float rim = dauntless_rim::enabled()
                ? 0.1f * dauntless_rim::strength_scale() : 0.0f;   // as render_space_geometry
            g_far_pass->render_impostors_blended(g_mid_out.sprites_fading, cam, *g_pipeline,
                                                 g_lighting, ambient_scale, rim);
            g_far_pass->render_impostors_blended(g_near_out.billboards_fading, cam, *g_pipeline,
                                                 g_lighting, ambient_scale, rim);
            g_far_draw_calls += g_far_pass->last_draw_calls();
        }
        // System-scale nebula: developer-only. Without --developer (or with
        // Volumetric Nebulae off) the legacy branch runs exactly as before.
        const renderer::NebulaDrawPlan neb_plan = renderer::plan_nebula_draws(
            dauntless_volumetric_nebulae::enabled(),
            dauntless::is_developer_mode() && g_system_nebula_pass != nullptr,
            g_system_nebula_pass && g_system_nebula_pass->has_profile(),
            !g_nebulae.empty(), !g_nebula_wake.empty());
        if (neb_plan.system) {
            DAUNTLESS_FRAME_SCOPE("space.system_nebula");
            const glm::mat4 inv_vp =
                glm::inverse(cam.proj_matrix() * cam.view_matrix());
            g_system_nebula_pass->render(
                cam, *g_pipeline, g_nebulae, g_lighting,
                target.color_texture(), target.depth_texture(),
                inv_vp, cam.eye, static_cast<float>(now),
                g_world.render_origin());
        } else if (neb_plan.legacy) {
            DAUNTLESS_FRAME_SCOPE("space.nebula");
            if (dauntless_volumetric_nebulae::enabled() && g_nebula_volumetric_pass) {
                // VOLUMETRIC (Modern VFX): raymarch the fbm field, blended
                // into the HDR target, occluded by the scene depth texture.
                const glm::mat4 inv_vp =
                    glm::inverse(cam.proj_matrix() * cam.view_matrix());
                g_nebula_volumetric_pass->render(
                    cam, *g_pipeline, g_nebulae, g_lighting,
                    target.color_texture(), target.depth_texture(),
                    inv_vp, cam.eye, static_cast<float>(now),
                    g_world.render_origin());
            } else if (g_nebula_pass) {
                g_nebula_pass->render(cam, *g_pipeline, g_nebulae,  // V1 faithful
                                      g_world.render_origin());
            }
        }
        // Decoupled additive wake trail (Plan B #1) -- drawn over whichever
        // cloud branch ran, so it survives under the system nebula pass too.
        if (neb_plan.wake && g_nebula_wake_pass)
            g_nebula_wake_pass->render(cam, *g_pipeline, g_nebula_wake,
                                       static_cast<float>(now));
        if (dauntless_nebula_lightning::enabled()
                && g_nebula_godray_pass && !g_nebula_godrays.empty())
            g_nebula_godray_pass->render(cam, *g_pipeline, g_nebula_godrays,
                                         target.color_texture());
        if (g_lens_flare_pass) {
            DAUNTLESS_FRAME_SCOPE("space.lens_flare");
            g_lens_flare_pass->render(g_lens_flares, cam, *g_pipeline, vw, vh, now);
        }
        {
            DAUNTLESS_FRAME_SCOPE("space.weapons");
            if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    cam, *g_pipeline);
            if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, cam, *g_pipeline);
            if (g_phaser_pass)  g_phaser_pass ->render(g_tractor_beams, cam, *g_pipeline);
            if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, cam, *g_pipeline);
        }
        if (dauntless_nebula_lightning::enabled()
                && g_hull_discharge_pass && !g_hull_discharges.empty())
            g_hull_discharge_pass->render(cam, *g_pipeline, g_hull_discharges);
        if (g_shockwave_pass)
            g_shockwave_pass->render(cam, g_shockwaves, *g_pipeline);
        // Venting jets: build per-frame descriptors from active breach events
        // and append to a combined emitter list for the particle pass.
        // Never mutate g_particle_emitters in place (Python-owned).
        if (g_particle_pass) {
            DAUNTLESS_FRAME_SCOPE("space.particles");
            std::vector<renderer::ParticleEmitterDescriptor> all_emitters = g_particle_emitters;
            // Venting jets are hull-breach VFX; skip descriptor build entirely
            // when the hull-breach toggle is off (Python-owned g_particle_emitters
            // still renders regardless of the toggle).
            if (dauntless_hull_damage::enabled()) {
                g_world.for_each_visible_in_pass(
                    scenegraph::Pass::Space,
                    [&](const scenegraph::Instance& inst) {
                        if (inst.breach_events.count() == 0) return;
                        auto vent = renderer::build_venting_descriptors(
                            inst.breach_events, inst.id, g_decal_game_time,
                            inst.surface_is_rock);
                        all_emitters.insert(all_emitters.end(),
                                            vent.begin(), vent.end());
                        auto debris = renderer::build_debris_descriptors(
                            inst.breach_events, inst.id, g_decal_game_time,
                            inst.surface_is_rock);
                        all_emitters.insert(all_emitters.end(),
                                            debris.begin(), debris.end());
                    });
            }
            g_particle_pass->render(all_emitters, g_world, cam, *g_pipeline);
        }
        // Cloak refraction: bend + chromatically disperse the scene behind each
        // cloaking hull. Runs last (the target holds the fully lit scene and is
        // still bound). Now shared by both the main view and the viewscreen RTT.
        if (g_cloak_pass && !g_cloak_ships.empty()) {
            DAUNTLESS_FRAME_SCOPE("space.cloak");
            g_cloak_pass->render(g_cloak_ships, g_world, cam, *g_pipeline, lookup,
                                 static_cast<float>(now), g_lighting, ambient_scale,
                                 g_decal_game_time, g_world.render_origin());
        }
    };

    // ── Sun shadow map (depth-only pre-pass) ───────────────────────────────
    // Computed once per frame from the sun's POV, BEFORE any render_space call
    // (both the main view and the viewscreen RTT sample the same map). The box
    // is player-centered: there is no C++ "player ship" handle, so we use the
    // rim_eligible Space instance nearest the exterior camera's look-at point
    // (g_camera.target) — the same point the camera orbits the player ship —
    // as the player, and its model AABB radius (× instance scale, matching
    // get_instance_bounds) as the bound radius. compute_light_matrix clamps the
    // radius into [R_min, R_max] and pads the depth slab, so this is robust.
    //
    // OFF path: when dauntless_shadows::enabled() is false we touch no GL state
    // and only call set_active_shadow(..., false), which makes the opaque pass
    // (Task 6) a no-op — the production render path stays byte-identical.
    if (dauntless_shadows::enabled() && g_shadow_target) {
        const glm::vec3 focus = g_camera.target;
        const scenegraph::Instance* player = nullptr;
        float player_radius_gu = 0.0f;
        float best_d2 = std::numeric_limits<float>::max();
        g_world.for_each_visible_in_pass(
            scenegraph::Pass::Space, [&](const scenegraph::Instance& inst) {
                if (!inst.rim_eligible) return;
                const assets::Model* m = resolve_model(inst.model_handle);
                if (m == nullptr) return;
                const glm::vec3 pos = glm::vec3(inst.world[3]);
                const float d2 = glm::dot(pos - focus, pos - focus);
                if (d2 >= best_d2) return;
                best_d2 = d2;
                player = &inst;
                renderer::Aabb box = renderer::compute_model_aabb(*m);
                const float scale = glm::length(glm::vec3(inst.world[0]));
                player_radius_gu = glm::length(box.half_extents) * scale;
            });

        if (player != nullptr) {
            renderer::ShadowFitParams fp;  // defaults
            glm::vec3 light_dir = g_lighting.directional_dir_ws[0];
            renderer::ShadowLight sl = renderer::compute_light_matrix(
                glm::vec3(player->world[3]), player_radius_gu, light_dir, fp);

            DAUNTLESS_FRAME_SCOPE("shadow");
            GLint prev_fbo = 0;
            glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
            g_shadow_target->bind();   // sets the 2048² viewport
            glClear(GL_DEPTH_BUFFER_BIT);
            renderer::submit_shadow_depth(g_world, sl, *g_pipeline, lookup);
            glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));

            renderer::set_active_shadow(sl, g_shadow_target->depth_texture(), true);
        } else {
            renderer::set_active_shadow({}, 0, false);
        }
    } else {
        renderer::set_active_shadow({}, 0, false);
    }

    // ── Viewscreen render-to-texture (bridge view, screen on) ──────────────
    // The forward space view (g_camera is already forward-from-ship in bridge
    // mode — see host_loop._compute_camera) renders into an offscreen HDR
    // target, which the bridge pass samples onto the viewscreen instance.
    if (viewscreen_on) {
        // The bridge viewscreen re-renders the whole space scene into an
        // offscreen target. Its children appear in the report with calls=2
        // whenever the exterior view is also drawing them.
        DAUNTLESS_FRAME_SCOPE("viewscreen.rtt");
        g_viewscreen_hdr->resize(kViewscreenRttW, kViewscreenRttH);
        g_viewscreen_hdr->bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        if (g_comm_source.active && g_bridge_pass) {
            scenegraph::Camera ccam = g_comm_source.cam;
            ccam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            g_bridge_pass->render(g_world, ccam, *g_pipeline, lookup,
                                  g_bridge_lighting, scenegraph::Pass::Comm,
                                  g_comm_source.set_id);
        } else if (g_scene_source.active) {
            scenegraph::Camera scam = g_scene_source.cam;
            scam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            // The viewscreen RTT is deliberately never multisampled: it is a
            // small in-world surface where edge quality barely reads.
            const float vs_ambient = dauntless_filmic::ambient_scale();
            render_space_geometry(scam, g_viewscreen_hdr.get(), nullptr,
                                  vs_ambient, /*dyn_lights=*/nullptr);
            render_space_vfx(scam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        kViewscreenRttW, kViewscreenRttH, vs_ambient);
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            const float vs_ambient = dauntless_filmic::ambient_scale();
            render_space_geometry(vcam, g_viewscreen_hdr.get(), nullptr,
                                  vs_ambient, /*dyn_lights=*/nullptr);
            render_space_vfx(vcam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        kViewscreenRttW, kViewscreenRttH, vs_ambient);
        }
        // Static/"snow" overlay over the feed (degraded-signal hail look).
        if (g_viewscreen_static.on && g_viewscreen_static_pass
                && g_viewscreen_static_pass->has_textures()) {
            g_viewscreen_static_pass->render(
                g_pipeline->viewscreen_static_shader(),
                g_viewscreen_static.intensity, now);
        }
        g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
    } else if (g_bridge_pass) {
        // Off -> the bridge pass falls back to the SDK's SetOffTexture image
        // (the mission loading screen), or to the NIF material if none is set.
        g_bridge_pass->set_viewscreen_texture(0);
    }

    // ── Main HDR target ────────────────────────────────────────────────────
    g_hdr_target->resize(fw, fh);
    g_hdr_target->bind();   // sets viewport to fw x fh
    if (viewer_mode) {
        glClearColor(g_hologram_bg.r, g_hologram_bg.g, g_hologram_bg.b, 1.0f);
    } else {
        glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    }
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    // Space scene goes to the main view only outside bridge view (in bridge
    // view it went to the RTT above, or nowhere when the screen is off — the
    // bridge pass fills the screen either way). This also retires the old
    // "wasted space render in bridge mode".
    if (!viewer_mode && !bridge_active) {
        DAUNTLESS_FRAME_SCOPE("space");
        const float ex_ambient = dauntless_filmic::ambient_scale();

        // MSAA path: the depth-writing geometry renders multisampled, then
        // resolves colour+depth into g_hdr_target so every VFX pass and the
        // whole post chain receive exactly the single-sample textures they
        // already expect. Nothing downstream of the resolve is aware of MSAA.
        //
        // Falls through to the stock path whenever the requested count clamps
        // to 0, or the driver refused the allocation (!valid()) — we never
        // trust GL_RGBA16F multisample on the strength of the spec alone.
        const int msaa = renderer::clamp_msaa_samples(
            g_msaa_samples, renderer::query_gl_caps());
        if (msaa >= 2) g_msaa_target->resize(fw, fh, msaa);
        if (msaa >= 2 && g_msaa_target->valid()) {
            // The multisample target is a DIFFERENT buffer from g_hdr_target
            // and does not inherit the clear applied to it above; without this
            // it would carry the previous frame's colour and a stale depth
            // buffer. glClearColor is still set from that block and nothing
            // between here and there touches it, so the two match by
            // construction rather than by a duplicated literal.
            g_msaa_target->bind();
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
            render_space_geometry(g_camera, nullptr, g_msaa_target.get(),
                                  ex_ambient, &g_dynamic_lights);
            g_msaa_target->resolve_to(*g_hdr_target);
            // resolve_to leaves the READ/DRAW bindings split; the VFX phase
            // re-binds g_hdr_target as GL_FRAMEBUFFER before it draws.
        } else {
            render_space_geometry(g_camera, g_hdr_target.get(), nullptr,
                                  ex_ambient, &g_dynamic_lights);
        }
        render_space_vfx(g_camera, /*for_viewscreen=*/false, *g_hdr_target,
                         fw, fh, ex_ambient);
    }

    if (g_hologram_ship.active) {
        DAUNTLESS_FRAME_SCOPE("hologram");
        if (g_spv_hull_mode && g_submitter) {
            // Hull-texture mode: draw just the inspected ship through the full
            // opaque path (real textures + system lighting) on the isolated
            // solid background. The space scene is skipped in viewer_mode, so
            // this single-instance draw is the only hull render.
            g_submitter->submit_opaque_instance(
                g_world, g_hologram_ship.instance, g_camera, *g_pipeline, lookup,
                g_lighting, g_decal_game_time, g_carve_cache.get(),
                &g_dynamic_lights, g_instance_field_cache.get());
        } else if (g_hologram_pass) {
            g_hologram_pass->render(g_hologram_ship, g_world, g_camera,
                                    *g_pipeline, lookup);
        }
    }
    if (viewer_mode && g_phaser_pass && !g_spv_overlay_beams.empty())
        g_phaser_pass->render(g_spv_overlay_beams, g_camera, *g_pipeline,
                              /*depth_test=*/false);
    if (viewer_mode && g_debug_volume_pass && !g_debug_cylinders.empty())
        g_debug_volume_pass->render(g_debug_cylinders, g_camera);
    if (viewer_mode && g_debug_volume_pass && !g_debug_boxes.empty())
        g_debug_volume_pass->render(g_debug_boxes, g_camera);
    if (viewer_mode && g_debug_volume_pass && !g_debug_spheres.empty())
        g_debug_volume_pass->render(g_debug_spheres, g_camera);
    if (viewer_mode && g_debug_volume_pass && !g_debug_cones.empty())
        g_debug_volume_pass->render(g_debug_cones, g_camera);
    if (viewer_mode && g_gizmo_pass && g_transform_gizmo.length > 0.0f)
        g_gizmo_pass->render(g_transform_gizmo, g_camera);
    if (g_subsystem_pin_pass && !g_subsystem_pins.empty()) {
        // Device-pixel ratio = framebuffer / logical window height, so pins
        // keep a constant apparent size on HiDPI/Retina displays.
        int fb_w = 0, fb_h = 0, win_w = 0, win_h = 0;
        g_window->framebuffer_size(&fb_w, &fb_h);
        g_window->window_size(&win_w, &win_h);
        const float dsf = (win_h > 0) ? static_cast<float>(fb_h) / static_cast<float>(win_h) : 1.0f;
        g_subsystem_pin_pass->render(g_subsystem_pins, g_camera, *g_pipeline, dsf);
    }
    if (g_target_reticle_pass && g_target_reticle.visible) {
        // Same device-pixel ratio the subsystem pins use, so the reticule
        // keeps a constant apparent size on HiDPI/Retina displays.
        int fb_w = 0, fb_h = 0, win_w = 0, win_h = 0;
        g_window->framebuffer_size(&fb_w, &fb_h);
        g_window->window_size(&win_w, &win_h);
        const float dsf = (win_h > 0) ? static_cast<float>(fb_h) / static_cast<float>(win_h) : 1.0f;
        g_target_reticle_pass->render(g_target_reticle, g_camera, *g_pipeline, dsf);
    }

    // ── Bridge pass ──────────────────────────────────────────────────────
    // Renders bridge-tagged instances with the bridge camera, after a
    // color + depth clear so the bridge geometry overlays the space
    // scene cleanly (without the space pass's color leaking through any
    // gaps in the bridge interior). In bridge mode the main-target space
    // render is now skipped entirely (see the `!bridge_active` guard
    // above); the forward space view instead renders into the viewscreen
    // RTT and the bridge pass samples it onto the viewscreen instance.
    if (bridge_active) {
        DAUNTLESS_FRAME_SCOPE("bridge");
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        if (fh > 0) g_bridge_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);
        // Warp boom flash on the bridge is confined to the viewscreen feed (the
        // surrounding interior must not flash); the main resolve-pass flash is
        // suppressed below when bridge_active. 0 when not warping.
        g_bridge_pass->set_viewscreen_flash(dauntless_warp_vfx::flash_intensity());
        // Red-alert dim applies to the interior render only; the comm-set
        // RTT above uses the unscaled g_bridge_lighting so the viewscreen
        // feed's brightness stays constant across alert levels.
        renderer::Lighting interior = g_bridge_lighting;
        interior.ambient *= g_bridge_ambient_scale;
        g_bridge_pass->render(g_world, g_bridge_camera, *g_pipeline,
                              lookup, interior);
    }

    // ── Non-finite probe (developer diagnostic) ────────────────────────────
    // Runs BEFORE the bloom chain, and that ordering is the whole point.
    // bloom_prefilter.frag now sanitises its input, so a NaN/Inf in the HDR
    // target leaves no trace downstream — the black rectangles it used to
    // produce are exactly what we fixed. Watching the HDR target keeps the
    // SOURCE observable after its symptom is gone. See nonfinite_probe.h.
    if (g_nfprobe_enabled && g_nonfinite_probe) {
        DAUNTLESS_FRAME_SCOPE("nfprobe");
        const auto& probe = g_nonfinite_probe->run(g_hdr_target->color_texture(),
                                                    fw, fh);
        ++g_nfprobe_frames;
        if (probe.any) {
            ++g_nfprobe_hits;
            g_nfprobe_last_cells.clear();
            constexpr int GW = renderer::NonfiniteProbe::kGridW;
            constexpr int GH = renderer::NonfiniteProbe::kGridH;
            for (int y = 0; y < GH; ++y) {
                for (int x = 0; x < GW; ++x) {
                    if (probe.grid[static_cast<std::size_t>(y) * GW + x])
                        g_nfprobe_last_cells.emplace_back(x, y);
                }
            }
            // Cell coords are bottom-left origin; report the first hit in
            // pixels too, so it can be matched against what was on screen.
            const int cx = g_nfprobe_last_cells.front().first;
            const int cy = g_nfprobe_last_cells.front().second;
            const int code = probe.max_code;
            const int n_names = static_cast<int>(
                sizeof(kNanCauseNames) / sizeof(kNanCauseNames[0]));
            // Code 1 also means "flagged, cause not recorded" -- alpha's normal
            // value. Only claim a cause when the shader-side debug was on AND
            // the writer emitted a real code.
            const char* cause =
                (!dauntless_nan_debug::enabled() || code <= 0)
                    ? "unknown (shader cause-probe off)"
                : (code < n_names) ? kNanCauseNames[code]
                                   : "unrecognised code (non-opaque pass?)";
            std::fprintf(stderr,
                "[nonfinite] frame %lld: %d/%d cells; first cell (%d,%d) "
                "~= pixels x[%d..%d] y[%d..%d] (bottom-left origin); "
                "cause=%d %s\n",
                g_nfprobe_frames, probe.flagged_cells, GW * GH, cx, cy,
                cx * fw / GW, (cx + 1) * fw / GW,
                cy * fh / GH, (cy + 1) * fh / GH,
                code, cause);
            g_nfprobe_dump_pending =
                !g_nfprobe_dump_dir.empty() && g_nfprobe_dumps < g_nfprobe_max_dumps;
        }
    }

    const bool exterior = !viewer_mode && !bridge_active;

    // Depth of field. Runs in HDR BEFORE bloom, which is the whole point: a
    // defocused nav light has to still be bright when it spreads, or it reads
    // as a grey smudge rather than bokeh. Physically it is also the right
    // order -- lens defocus happens before the sensor.
    //
    // Skipped entirely unless a subject is actually focused (blend > 0), so
    // the default deep-focus frame is byte-identical to the pre-DOF renderer:
    // bloom and resolve read g_hdr_target exactly as they always did.
    std::uint32_t scene_tex = g_hdr_target->color_texture();
    const bool dof_on = dauntless_dof::enabled()
                        && dauntless_dof::params().blend > 0.0f
                        && exterior
                        && g_dof_pass && g_dof_target;
    if (dof_on) {
        DAUNTLESS_FRAME_SCOPE("dof");
        g_dof_target->resize(fw, fh);
        g_dof_pass->draw(g_hdr_target->color_texture(),
                         g_hdr_target->depth_texture(),
                         g_dof_target->fbo(), fw, fh,
                         g_camera.near, g_camera.far,
                         dauntless_dof::params());
        scene_tex = g_dof_target->color_texture();
    }

    // Compute bloom from the HDR target while the HDR FBO is still in use.
    // bloom_tex is set to the HDR color texture as a harmless dummy when HDR is
    // off — the resolve's OFF branch never samples u_bloom.
    std::uint32_t bloom_tex = scene_tex;
    if (dauntless_hdr::enabled()) {
        DAUNTLESS_FRAME_SCOPE("bloom");
        bloom_tex = g_bloom_pass->render(scene_tex, fw, fh);
    }

    // Resolve the HDR target, then run any active optional LDR post passes
    // (SMAA -> motion blur -> filmic) as a 2-target ping-pong, the last writing
    // the backbuffer. With none active, resolve writes straight to the
    // backbuffer (unchanged, zero-added-cost path). CEF composite + swap run
    // after this so the overlay composites on top of the resolved 3D scene.
    const bool aa_on    = g_smaa_enabled;
    const bool filmic_on = dauntless_filmic::enabled() && exterior;
    const bool mblur_on  = dauntless_motion_blur::enabled() && exterior
                           && g_have_prev_viewproj;

    // Optional LDR post passes run, in order, after the HDR resolve:
    //   SMAA -> motion blur -> filmic.
    // Ping-pong between two LDR targets; the LAST active pass writes the
    // backbuffer. With none active, resolve writes straight to the backbuffer
    // (the original zero-cost path, byte-identical).
    const bool any_post = aa_on || mblur_on || filmic_on;

    // Image-based ("modern") lens flare: generate a half-res flare texture from
    // the bloom bright-buffer and composite it in the resolve. Exterior-only
    // (no flares on the bridge interior), and only when HDR + the toggle are on
    // (the toggle also suppresses the classic billboard flares in host_loop).
    std::uint32_t lens_flare_tex = scene_tex;  // dummy when off
    float lens_flare_strength = 0.0f;
    if (dauntless_hdr::enabled() && dauntless_hdr_lens_flare::enabled()
            && exterior && g_lens_flare_hdr_pass) {
        lens_flare_tex = g_lens_flare_hdr_pass->render(
            bloom_tex, g_bloom_pass ? g_bloom_pass->coarsest_texture() : 0u,
            fw, fh);
        lens_flare_strength = 0.108f;  // additive flare intensity (0.15 -20% -10%)
    }

    if (any_post) { g_ldr_target->resize(fw, fh); g_ldr_target->bind(); }
    else { glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0, 0, fw, fh); }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->set_lens_flare_strength(lens_flare_strength);
    // On the bridge the warp flash is confined to the viewscreen feed (applied
    // in the bridge pass); suppress it on the main resolve so the interior
    // doesn't white out. Exterior view keeps the full-screen flash.
    g_resolve_pass->set_warp_flash(
        bridge_active ? 0.0f : dauntless_warp_vfx::flash_intensity());
    {
        DAUNTLESS_FRAME_SCOPE("resolve");
        g_resolve_pass->draw(scene_tex, bloom_tex, lens_flare_tex);
    }

    if (any_post) {
        DAUNTLESS_FRAME_SCOPE("post");
        g_ldr_target2->resize(fw, fh);

        // Active optional passes as uniform (src_tex, dst_fbo) callables.
        std::vector<std::function<void(std::uint32_t, std::uint32_t)>> passes;
        if (aa_on)
            passes.emplace_back([&](std::uint32_t s, std::uint32_t d) {
                g_smaa_pass->draw(s, d, fw, fh);
            });
        if (mblur_on) {
            // Current-camera matrices for the blur, computed only when the pass
            // actually runs. Captured by value so they outlive this scope when
            // the ping-pong loop below invokes the lambda.
            const glm::mat4 inv_proj = glm::inverse(g_camera.proj_matrix());
            const glm::mat3 cam_rot  = glm::mat3(glm::inverse(g_camera.view_matrix()));
            const glm::vec3 cam_pos  = g_camera.eye;
            // Last frame's matrix was in last frame's render space; the
            // origin followed the camera since (render_origin.h).
            const glm::mat4 prev     = renderer::render_origin::rebase_prev_viewproj(
                g_prev_viewproj, g_prev_viewproj_origin, g_world.render_origin());
            // Shutter: frame-rate normalised and faded out by the dash
            // intensity (renderer/motion_blur_shutter.h documents both).
            // `dt` is the wall-clock frame time already computed at the top
            // of frame(); no second timestamp is tracked for this.
            const float shutter = renderer::motion_blur_shutter(
                dt, kMotionBlurRefDt, dauntless_dash_vfx::intensity());
            passes.emplace_back([inv_proj, cam_rot, cam_pos, prev, fw, fh, shutter]
                                (std::uint32_t s, std::uint32_t d) {
                g_motion_blur_pass->draw(s, d, fw, fh, inv_proj, cam_rot,
                                         cam_pos, prev, shutter);
            });
        }
        if (filmic_on)
            passes.emplace_back([&](std::uint32_t s, std::uint32_t d) {
                g_filmic_pass->draw(s, d, fw, fh, static_cast<float>(now));
            });

        // resolve wrote into target[0]; ping-pong to target[1], alternating.
        renderer::LdrTarget* targets[2] = { g_ldr_target.get(), g_ldr_target2.get() };
        std::uint32_t cur_tex = targets[0]->color_texture();
        int dst_idx = 1;
        for (std::size_t i = 0; i < passes.size(); ++i) {
            const bool last = (i + 1 == passes.size());
            const std::uint32_t dst_fbo = last ? 0u : targets[dst_idx]->fbo();
            passes[i](cur_tex, dst_fbo);
            if (!last) { cur_tex = targets[dst_idx]->color_texture(); dst_idx ^= 1; }
        }
    }

    // Cutscene letterbox — the final image is now in FBO 0 whether or not the
    // post chain ran. Draw the bars over the scene but BEFORE the CEF
    // composite below, so every UI element (subtitles, crew menus, info boxes,
    // pause menu) lands on top of them. No-op outside a cutscene.
    //
    // Skipped in viewer_mode: the Ship Property Viewer owns the whole frame
    // (it already skips the space scene AND the bridge pass above), and the
    // bars are scene framing, not a UI overlay -- the SPV can be opened from
    // the pause menu mid-cutscene (ESC freezes _player_dt at 0, which holds
    // the animator's last value), and without this gate the frozen bars sit
    // over the hologram and its subsystem pins. This is NOT the same as the
    // "unconditional, not view-gated" rule from the design spec, which is
    // about bridge-vs-exterior view (BC letterboxes bridge cutscenes too,
    // and that must keep working) -- viewer_mode isn't a view, it's a
    // separate full-frame override that pre-empts the space scene entirely.
    if (!viewer_mode) {
        DAUNTLESS_FRAME_SCOPE("letterbox");
        renderer::letterbox::draw(fw, fh);
    }

    // ── Helm -> Set Course star map ──────────────────────────────────────
    // Slot matters: AFTER the post chain has resolved into FBO 0 (so the map
    // is not tonemapped along with the scene) and BEFORE ui_cef::composite()
    // (so the modal's chrome, labels and buttons land on top of it). It draws
    // into a scissored sub-rect, leaving the live scene visible around the
    // modal, and saves/restores viewport + scissor itself.
    if (g_starmap_pass && g_starmap_scene.enabled) {
        DAUNTLESS_FRAME_SCOPE("starmap");
        // Bind FBO 0 explicitly, as letterbox::draw does for itself: the post
        // chain does land here, but viewer_mode skips the letterbox draw, so
        // this slot must not inherit its framebuffer from a neighbour.
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        int fb_w = 0, fb_h = 0, win_w = 0, win_h = 0;
        g_window->framebuffer_size(&fb_w, &fb_h);
        g_window->window_size(&win_w, &win_h);
        const float dsf = (win_h > 0) ? static_cast<float>(fb_h) / static_cast<float>(win_h) : 1.0f;
        g_starmap_pass->render(g_starmap_scene, g_starmap_camera, *g_pipeline, dsf);
    }

    // Cache this exterior frame's view-projection for next frame's motion blur.
    // Non-exterior frames invalidate it so re-entering the exterior view skips
    // one frame of blur instead of smearing across the transition.
    if (exterior) {
        g_prev_viewproj = g_camera.proj_matrix() * g_camera.view_matrix();
        g_prev_viewproj_origin = g_world.render_origin();
        g_have_prev_viewproj = true;
    } else {
        g_have_prev_viewproj = false;
    }

    // Snapshot tracked keys' current state BEFORE poll_events. The next
    // tick's Python sees the post-poll state as `now` and this pre-poll
    // state as `prev`, so any change made by this poll surfaces as a
    // rising edge. (Snapshotting AFTER poll would make now==prev for
    // every Python call, silently breaking key_pressed.)
    for (auto& [k, prev] : g_prev_key_state) {
        prev = (glfwGetKey(g_window->native_handle(), k) == GLFW_PRESS);
    }
    for (auto& [b, prev] : g_prev_mouse_state) {
        prev = (glfwGetMouseButton(g_window->native_handle(), b) == GLFW_PRESS);
    }
    // GLFW poll BEFORE CEF pump: on macOS both drain from the same NSApp
    // event queue, and CefDoMessageLoopWork() consumes keyboard events
    // (we observed SPACE / digit / R presses being lost when CEF pumped
    // first). Polling GLFW first guarantees the GL window's window owner
    // gets first crack at the OS event queue; CEF then drains whatever
    // it needs for its own internal work afterward.
    {
        DAUNTLESS_FRAME_SCOPE("poll_events");
        g_window->poll_events();
    }

#ifdef DAUNTLESS_ENABLE_CEF
    // Pump CEF's message loop (may deliver OnPaint synchronously into
    // g_client), then composite the latest bitmap over the 3D scene with
    // premultiplied-alpha blend. Runs AFTER poll_events to avoid stealing
    // keyboard events from GLFW (see comment above poll_events).
    {
        DAUNTLESS_FRAME_SCOPE("cef.pump");
        dauntless::ui_cef::pump();
    }
    {
        // The composite uploads the ENTIRE CEF surface every frame — no
        // dirty-rect, no PBO — so this scope carries that cost. At 2560x1440
        // BGRA that is ~14.7 MB of synchronous glTexSubImage2D per frame.
        DAUNTLESS_FRAME_SCOPE("cef.composite");
        dauntless::ui_cef::composite();
    }
#endif

    // Serviced here, not at probe time: the artefact only exists once the
    // resolve + post chain + UI have composited into the back buffer, and this
    // is the last moment before it is presented and lost.
    if (g_nfprobe_dump_pending) {
        g_nfprobe_dump_pending = false;
        char name[128];
        std::snprintf(name, sizeof(name), "/nonfinite_%04d_frame%lld.png",
                      g_nfprobe_dumps, g_nfprobe_frames);
        const std::string path = g_nfprobe_dump_dir + name;
        if (dauntless::dump_default_framebuffer_png(path, fw, fh)) {
            ++g_nfprobe_dumps;
            std::fprintf(stderr, "[nonfinite] wrote %s\n", path.c_str());
            if (g_nfprobe_dumps >= g_nfprobe_max_dumps) {
                std::fprintf(stderr,
                    "[nonfinite] dump cap (%d) reached; still counting hits\n",
                    g_nfprobe_max_dumps);
            }
        } else {
            std::fprintf(stderr, "[nonfinite] FAILED to write %s\n", path.c_str());
        }
    }

    {
        // Under vsync (glfwSwapInterval(1)) this scope IS the wait for the
        // next refresh. A large `present` with small siblings means the frame
        // finished early and blocked — not that presenting is slow.
        DAUNTLESS_FRAME_SCOPE("present");
        g_window->swap_buffers();
    }

    renderer::frame_timer().end_frame();
}

// Re-derive the resolved ambient gradient from whatever directionals
// g_lighting currently holds. Called from set_lighting (once per frame,
// after the directionals are populated) and from the two knob setters so
// a change bites on the next frame rather than waiting for Python's next
// lighting push.
void resolve_ambient_gradient() {
    const renderer::AmbientGradient ag = renderer::ambient_gradient_from_lights(
        g_lighting.directional_dir_ws, g_lighting.directional_color,
        g_lighting.directional_count, dauntless_ambient_gradient::strength());
    g_lighting.ambient_dir_ws   = ag.dir_ws;
    g_lighting.ambient_gradient = ag.strength;
}

}  // namespace

// Toggle for the opaque-pass Fresnel rim term. Defined in frame.cc.
namespace dauntless_rim {
    void set_enabled(bool v);  // defined in frame.cc
}
// dauntless_shadows is forward-declared earlier (before frame()).
// Normal mapping controls. Defined in frame.cc.
namespace dauntless_normal_map {
    void set_enabled(bool v);
    void set_strength(float v);
    void set_flip_green(bool v);
}
// Hull-breach renderer pass — always-on gate. Defined in frame.cc.
namespace dauntless_hull_damage {
    bool enabled();            // defined in frame.cc
}

static renderer::PhaserBeamDescriptor beam_from_dict(const py::dict& d) {
    renderer::PhaserBeamDescriptor b;
    auto e = d["emitter"].cast<std::tuple<float, float, float>>();
    auto t = d["target"].cast<std::tuple<float, float, float>>();
    auto c = d["color"].cast<std::tuple<float, float, float, float>>();
    b.emitter_world = {std::get<0>(e), std::get<1>(e), std::get<2>(e)};
    b.target_world  = {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
    b.color         = {std::get<0>(c), std::get<1>(c), std::get<2>(c), std::get<3>(c)};
    b.width         = d["width"].cast<float>();
    b.u_tiles       = d.contains("u_tiles") ? d["u_tiles"].cast<float>() : 1.0f;
    b.num_sides        = d.contains("num_sides")        ? d["num_sides"].cast<int>()          : 6;
    b.taper_radius     = d.contains("taper_radius")     ? d["taper_radius"].cast<float>()     : 0.01f;
    b.taper_ratio      = d.contains("taper_ratio")      ? d["taper_ratio"].cast<float>()      : 0.25f;
    b.taper_min_length = d.contains("taper_min_length") ? d["taper_min_length"].cast<float>() : 5.0f;
    b.taper_max_length = d.contains("taper_max_length") ? d["taper_max_length"].cast<float>() : 30.0f;
    b.perimeter_tile   = d.contains("perimeter_tile")   ? d["perimeter_tile"].cast<float>()   : 1.0f;
    b.texture_speed    = d.contains("texture_speed")    ? d["texture_speed"].cast<float>()    : 0.0f;
    b.end_width_scale  = d.contains("end_width_scale")  ? d["end_width_scale"].cast<float>()  : 1.0f;
    return b;
}

// Parse-only: extract the embedded set camera (frustum + world transform)
// from a NIF without any GL context or asset-cache entry. Feeds
// MissionLib.SetupBridgeSet's embedded-camera path via ModelManager.CloneCamera.
py::object parse_set_camera_impl(const std::string& nif_abs_path) {
    std::filesystem::path path = nif_abs_path;
    if (!std::filesystem::exists(path)) return py::none();
    nif::File f;
    try {
        f = nif::load(path);
    } catch (const std::exception&) {
        return py::none();
    }
    auto cam = nif::find_first_camera(f);
    if (!cam.has_value()) return py::none();
    py::dict d;
    d["position"] = py::make_tuple(cam->position[0], cam->position[1],
                                   cam->position[2]);
    d["rotation"] = py::make_tuple(
        cam->rotation[0], cam->rotation[1], cam->rotation[2],
        cam->rotation[3], cam->rotation[4], cam->rotation[5],
        cam->rotation[6], cam->rotation[7], cam->rotation[8]);
    d["frustum"] = py::make_tuple(cam->frustum[0], cam->frustum[1],
                                  cam->frustum[2], cam->frustum[3]);
    d["near"] = cam->near_distance;
    d["far"] = cam->far_distance;
    return d;
}

namespace {

/// Block-array index whose `file.block_ids` entry equals `link_id`, or
/// npos. Mirrors mesh_fix.cc's local index_of (not exported); nif_shapes
/// needs its own copy to resolve property/image links.
std::size_t nif_shapes_index_of(const nif::File& file, std::uint32_t link_id) {
    for (std::size_t i = 0; i < file.block_ids.size(); ++i)
        if (file.block_ids[i] == link_id) return i;
    return std::string::npos;
}

/// The part of `path` after the last '/' or '\\'.
std::string nif_shapes_basename(const std::string& path) {
    auto pos = path.find_last_of("/\\");
    return pos == std::string::npos ? path : path.substr(pos + 1);
}

/// Append the basename of the NiImage `img_link` resolves to, if any, to
/// `out` -- only for external (on-disk) images; embedded images have no
/// filename to report.
void nif_shapes_collect_image(const nif::File& file, std::uint32_t img_link,
                               std::vector<std::string>* out) {
    std::size_t idx = nif_shapes_index_of(file, img_link);
    if (idx == std::string::npos || idx >= file.blocks.size()) return;
    const auto* img = std::get_if<nif::NiImage>(&file.blocks[idx]);
    if (!img || img->use_external == 0 || img->file_name.empty()) return;
    out->push_back(nif_shapes_basename(img->file_name));
}

}  // namespace

// Read-only geometry dump for the mesh-fix generator (tools/gen_mesh_fixes.py):
// one dict per NiTriShape, in block order, with world-space vertices/normals,
// UV set 0, triangles, texture basenames and the hidden flag. Parse-only, no
// GL context, and applies no mesh fix -- callers see the raw stock geometry.
py::object nif_shapes_impl(const std::string& nif_abs_path) {
    std::filesystem::path path = nif_abs_path;
    if (!std::filesystem::exists(path)) return py::none();
    nif::File f;
    try {
        f = nif::load(path);
    } catch (const std::exception&) {
        return py::none();
    }

    py::list out;
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* shape = std::get_if<nif::NiTriShape>(&f.blocks[i]);
        if (!shape) continue;

        py::dict d;
        d["block"] = static_cast<int>(i);
        d["name"] = shape->av.obj.name;

        std::vector<std::string> textures;
        for (std::uint32_t link : shape->av.property_links) {
            std::size_t idx = nif_shapes_index_of(f, link);
            if (idx == std::string::npos || idx >= f.blocks.size()) continue;
            const auto& b = f.blocks[idx];
            if (const auto* tp = std::get_if<nif::NiTextureProperty>(&b)) {
                nif_shapes_collect_image(f, tp->image_link, &textures);
            } else if (const auto* mtp = std::get_if<nif::NiMultiTextureProperty>(&b)) {
                for (const auto& elem : mtp->elements) {
                    if (elem.has_image) nif_shapes_collect_image(f, elem.image_link, &textures);
                }
            }
        }
        d["textures"] = textures;

        const nif::NiTriShapeData* data = nullptr;
        std::size_t data_idx = nif_shapes_index_of(f, shape->data_link);
        if (data_idx != std::string::npos && data_idx < f.blocks.size())
            data = std::get_if<nif::NiTriShapeData>(&f.blocks[data_idx]);

        py::list vertices, normals, uvs, triangles;
        if (data) {
            const glm::mat4 world = assets::nif_block_world(f, i);
            const glm::mat3 normal_mat = glm::mat3(world);
            for (const auto& v : data->vertices) {
                const glm::vec4 wp = world * glm::vec4(v.x, v.y, v.z, 1.0f);
                vertices.append(py::make_tuple(wp.x, wp.y, wp.z));
            }
            for (const auto& n : data->normals) {
                const glm::vec3 wn = glm::normalize(normal_mat * glm::vec3(n.x, n.y, n.z));
                normals.append(py::make_tuple(wn.x, wn.y, wn.z));
            }
            if (!data->uv_sets.empty()) {
                for (const auto& uv : data->uv_sets[0]) {
                    uvs.append(py::make_tuple(uv.u, uv.v));
                }
            }
            for (const auto& t : data->triangles) {
                triangles.append(py::make_tuple(t[0], t[1], t[2]));
            }
        }
        d["vertices"] = vertices;
        d["normals"] = normals;
        d["uvs"] = uvs;
        d["triangles"] = triangles;
        d["hidden"] = (shape->av.flags & 0x0001u) != 0;

        out.append(d);
    }
    return out;
}

// ── Minor rocks: Python <-> renderer::minors conversions ───────────────────
namespace {

namespace mr = renderer::minors;

std::uint64_t minor_instance_key(const scenegraph::InstanceId& id) {
    return (static_cast<std::uint64_t>(id.index) << 32) | id.generation;
}

glm::vec3 vec3_of(const py::handle& o) {
    const auto t = o.cast<std::tuple<float, float, float>>();
    return {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
}
glm::dvec3 dvec3_of(const py::handle& o) {
    const auto t = o.cast<std::tuple<double, double, double>>();
    return {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
}
glm::mat4 mat4_of(const std::vector<float>& m16, const char* what) {
    if (m16.size() != 16)
        throw std::runtime_error(std::string(what) + ": need 16 floats (column-major)");
    return glm::make_mat4(m16.data());
}

// A float32 dial as the Python float it was written as: the shortest decimal
// that round-trips to the same float (0.05f -> 0.05, not 0.05000000074505806),
// so dials() compares equal to engine/rocks/minor_dials.py's DEFAULTS.
double py_float(float v) {
    char buf[32];
    for (int prec = 6; prec <= 9; ++prec) {
        std::snprintf(buf, sizeof buf, "%.*g", prec, static_cast<double>(v));
        if (std::strtof(buf, nullptr) == v) break;
    }
    return std::strtod(buf, nullptr);
}

std::vector<mr::DebrisSpec> debris_of(const py::handle& list) {
    std::vector<mr::DebrisSpec> out;
    if (list.is_none()) return out;
    for (const auto& item : list.cast<py::list>()) {
        const auto d = item.cast<py::dict>();
        mr::DebrisSpec s;
        s.offset = vec3_of(d["offset"]);
        s.v0 = vec3_of(d["v0"]);
        s.radius = d["radius"].cast<float>();
        s.seed = d["seed"].cast<std::uint32_t>();
        out.push_back(s);
    }
    return out;
}

mr::CloudDesc cloud_desc_of(const py::dict& d) {
    mr::CloudDesc c;
    c.id = d["id"].cast<std::uint32_t>();
    const auto anchor = d["anchor"].cast<std::string>();
    if (anchor == "instance") c.anchor = mr::Anchor::Instance;
    else if (anchor == "point") c.anchor = mr::Anchor::Point;
    else if (anchor == "free") c.anchor = mr::Anchor::Free;
    else throw std::runtime_error("minors: unknown anchor '" + anchor + "'");
    if (d.contains("instance") && !d["instance"].is_none())
        c.instance_key = minor_instance_key(d["instance"].cast<scenegraph::InstanceId>());
    c.point = dvec3_of(d["point"]);
    c.velocity = vec3_of(d["velocity"]);
    c.t0 = d["t0"].cast<double>();
    c.shell_inner = d["shell_inner"].cast<float>();
    c.shell_outer = d["shell_outer"].cast<float>();
    c.falloff = d["falloff"].cast<float>();
    c.count = d["count"].cast<int>();
    c.r_min = d["r_min"].cast<float>();
    c.r_max = d["r_max"].cast<float>();
    c.size_exponent = d["size_exponent"].cast<float>();
    c.family = d["family"].cast<int>();
    c.seed = d["seed"].cast<std::uint32_t>();
    c.orbit_rate = d["orbit_rate"].cast<float>();
    c.fade_in = d["fade_in"].cast<bool>();
    c.debris = debris_of(d.contains("debris") ? py::handle(d["debris"]) : py::handle(py::none()));
    return c;
}

// (lod0, lod1, bound_mu) or, far tier, (lod0, lod1, bound_mu, (r, g, b)):
// the 4th element is the fragment's speck albedo (catalogue avg_albedo).
std::vector<mr::Fragment> fragments_of(const std::vector<py::tuple>& entries) {
    std::vector<mr::Fragment> out;
    out.reserve(entries.size());
    for (const auto& e : entries) {
        if (e.size() != 3 && e.size() != 4)
            throw py::value_error("fragment entry must be (lod0, lod1, bound_mu[, (r, g, b)])");
        mr::Fragment f;
        f.lod0 = e[0].cast<std::uint64_t>();
        f.lod1 = e[1].cast<std::uint64_t>();
        f.bound_radius_mu = e[2].cast<float>();
        if (e.size() == 4) {
            const auto rgb = e[3].cast<std::tuple<float, float, float>>();
            f.albedo = glm::vec3(std::get<0>(rgb), std::get<1>(rgb), std::get<2>(rgb));
        }
        out.push_back(f);
    }
    return out;
}

// Each key read with `contains`; an omitted key resets to the struct default
// (the system_nebula_set_dials convention).
mr::Dials dials_of(const py::dict& d) {
    mr::Dials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    auto i = [&](const char* k, int& v) { if (d.contains(k)) v = d[k].cast<int>(); };
    f("min_pixel_radius", o.min_pixel_radius);
    f("lod0_pixel_radius", o.lod0_pixel_radius);
    f("tumble_min", o.tumble_min);
    f("tumble_max", o.tumble_max);
    f("cloud_fade_in_seconds", o.cloud_fade_in_seconds);
    f("contact_margin_gu", o.contact_margin_gu);
    f("shove_transfer", o.shove_transfer);
    f("shove_min_gups", o.shove_min_gups);
    f("shove_damp_seconds", o.shove_damp_seconds);
    f("shove_tumble", o.shove_tumble);
    i("max_shoves_per_frame", o.max_shoves_per_frame);
    f("teleport_gu", o.teleport_gu);
    f("contact_cooldown_s", o.contact_cooldown_s);
    f("debris_damp_seconds", o.debris_damp_seconds);
    return o;
}

py::dict dials_dict(const mr::Dials& o) {
    py::dict d;
    d["min_pixel_radius"] = py_float(o.min_pixel_radius);
    d["lod0_pixel_radius"] = py_float(o.lod0_pixel_radius);
    d["tumble_min"] = py_float(o.tumble_min);
    d["tumble_max"] = py_float(o.tumble_max);
    d["cloud_fade_in_seconds"] = py_float(o.cloud_fade_in_seconds);
    d["contact_margin_gu"] = py_float(o.contact_margin_gu);
    d["shove_transfer"] = py_float(o.shove_transfer);
    d["shove_min_gups"] = py_float(o.shove_min_gups);
    d["shove_damp_seconds"] = py_float(o.shove_damp_seconds);
    d["shove_tumble"] = py_float(o.shove_tumble);
    d["max_shoves_per_frame"] = o.max_shoves_per_frame;
    d["teleport_gu"] = py_float(o.teleport_gu);
    d["contact_cooldown_s"] = py_float(o.contact_cooldown_s);
    d["debris_damp_seconds"] = py_float(o.debris_damp_seconds);
    return d;
}

// ── Far tier: Python <-> renderer::far conversions ─────────────────────────
namespace rf = renderer::far;

std::vector<int> ints_of(const py::handle& o) { return o.cast<std::vector<int>>(); }
std::vector<float> floats_of(const py::handle& o) { return o.cast<std::vector<float>>(); }

rf::Population population_of(const py::dict& d) {
    rf::Population p;
    p.kind = d["kind"].cast<int>();
    p.density_at_1 = d["density_at_1"].cast<float>();
    p.a_lo = d["a_lo"].cast<float>();
    p.a_hi = d["a_hi"].cast<float>();
    p.size = rf::PowerLaw{d["r_min"].cast<float>(), d["r_max"].cast<float>(),
                          d["exponent"].cast<float>()};
    p.rocks = ints_of(d["rocks"]);
    p.weights = floats_of(d["weights"]);
    if (p.rocks.size() != p.weights.size())
        throw py::value_error("far population: rocks and weights differ in length");
    p.albedo = vec3_of(d["albedo"]);
    return p;
}

// Keys exactly DiscSource.to_native() (engine side, far-tier plan Task 9).
// Optional (tile-field haze, 2026-10-02): shape ("disc" | "sphere"),
// procedural, view_space, sphere_radius_gu, sphere_edge_frac, gain_scale;
// brightness (haze colour only, ruling R16) -- a missing key keeps the
// DiscSource default (a disc source as before, brightness 1).
rf::DiscSource disc_source_of(const py::dict& d) {
    rf::DiscSource s;
    s.id = d["id"].cast<std::uint32_t>();
    s.frame = d["frame"].cast<std::string>();
    s.centre = dvec3_of(d["centre"]);
    s.normal = vec3_of(d["normal"]);
    for (const auto& row : d["table"].cast<py::list>()) {
        const auto t = row.cast<std::tuple<float, float>>();
        s.table.emplace_back(std::get<0>(t), std::get<1>(t));
    }
    s.outer_fade_gu = d["outer_fade_gu"].cast<float>();
    s.scale_height_frac = d["scale_height_frac"].cast<float>();
    s.scale_height_min_gu = d["scale_height_min_gu"].cast<float>();
    s.seed = d["seed"].cast<std::uint32_t>();
    for (const auto& reg : d["explicit_regions"].cast<py::list>()) {
        const auto t = reg.cast<py::tuple>();
        if (t.size() != 2)
            throw py::value_error("far explicit region must be ((x, y, z), r)");
        s.explicit_regions.emplace_back(dvec3_of(t[0]), t[1].cast<double>());
    }
    for (const auto& pop : d["populations"].cast<py::list>())
        s.pops.push_back(population_of(pop.cast<py::dict>()));
    if (d.contains("shape")) {
        const auto shape = d["shape"].cast<std::string>();
        if (shape == "disc") s.shape = rf::DiscSource::Shape::Disc;
        else if (shape == "sphere") s.shape = rf::DiscSource::Shape::Sphere;
        else throw py::value_error("far source shape must be 'disc' or 'sphere', not '" + shape + "'");
    }
    if (d.contains("procedural")) s.procedural = d["procedural"].cast<bool>();
    if (d.contains("view_space")) s.view_space = d["view_space"].cast<bool>();
    if (d.contains("sphere_radius_gu")) s.sphere_radius_gu = d["sphere_radius_gu"].cast<float>();
    if (d.contains("sphere_edge_frac")) s.sphere_edge_frac = d["sphere_edge_frac"].cast<float>();
    if (d.contains("gain_scale")) s.gain_scale = d["gain_scale"].cast<float>();
    if (d.contains("brightness")) s.brightness = d["brightness"].cast<float>();
    // Haze noise (every shape) + per-source steps (2026-10-02): omitted = off /
    // the global haze_steps.
    if (d.contains("noise_scale_gu")) s.noise_scale_gu = d["noise_scale_gu"].cast<float>();
    // Contrast lives in [0, 1] (rock-fields R1): noise_m_bound = 1 + contrast.
    if (d.contains("noise_contrast"))
        s.noise_contrast = std::clamp(d["noise_contrast"].cast<float>(), 0.0f, 1.0f);
    if (d.contains("noise_octaves")) s.noise_octaves = d["noise_octaves"].cast<int>();
    if (d.contains("noise_sharpness")) s.noise_sharpness = std::max(0.0f, d["noise_sharpness"].cast<float>());
    if (d.contains("shape_warp")) s.shape_warp = std::clamp(d["shape_warp"].cast<float>(), 0.0f, 0.9f);
    if (d.contains("shape_warp_scale_gu")) s.shape_warp_scale_gu = d["shape_warp_scale_gu"].cast<float>();
    if (d.contains("steps")) s.steps = d["steps"].cast<int>();
    return s;
}

// An omitted key resets to its default (dials_of's convention).
rf::FarDials far_dials_of(const py::dict& d) {
    rf::FarDials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    auto i = [&](const char* k, int& v) { if (d.contains(k)) v = d[k].cast<int>(); };
    f("imp_hi", o.tiers.imp_hi);
    f("imp_lo", o.tiers.imp_lo);
    f("speck_hi", o.tiers.speck_hi);
    f("speck_lo", o.tiers.speck_lo);
    f("p_min", o.tiers.p_min);
    f("slab_sigmas", o.slab_sigmas);
    f("speck_gain", o.speck_gain);
    f("haze_gain", o.haze_gain);
    i("haze_steps", o.haze_steps);
    // Rock-fields Task 12. haze_start_* arrive DERIVED from haze_handoff_*
    // (engine/rocks/far_tier.py native_dials); the divisor floors at 1.
    f("haze_start_gu", o.haze_start_gu);
    f("haze_start_ramp_gu", o.haze_start_ramp_gu);
    i("haze_res_divisor", o.haze_res_divisor);
    o.haze_res_divisor = std::max(o.haze_res_divisor, 1);
    return o;
}

// The near band's keys of the same dict (far_dials.py near_* +
// collide_cooldown_s); an omitted key resets to its default. cell_gu is
// floored at 1 GU (Task 4 review: with NearField::stream's 33-cells-per-axis
// cap, a tiny cell would otherwise shrink the streamed range to nothing).
renderer::rockfield::NearDials near_dials_of(const py::dict& d) {
    renderer::rockfield::NearDials o;
    auto f = [&](const std::string& k, float& v) { if (d.contains(k)) v = d[k.c_str()].cast<float>(); };
    auto i = [&](const std::string& k, int& v) { if (d.contains(k)) v = d[k.c_str()].cast<int>(); };
    for (auto [name, c] : {std::pair<const char*, renderer::rockfield::NearClassDials*>{"small", &o.small},
                           {"large", &o.large}}) {
        const std::string p = std::string("near_") + name + "_";
        f(p + "density", c->density);
        f(p + "r_min", c->r_min);
        f(p + "r_max", c->r_max);
        f(p + "exponent", c->exponent);
        f(p + "cell_gu", c->cell_gu);
        f(p + "mesh_gu", c->mesh_gu);
        f(p + "billboard_gu", c->billboard_gu);
        i(p + "max", c->max_instances);
        c->cell_gu = std::max(c->cell_gu, 1.0f);
    }
    f("near_fade_gu", o.fade_gu);
    f("near_handoff_fade_gu", o.handoff_fade_gu);
    f("near_tumble_scale", o.tumble_scale);
    f("near_dash_collapse_step_gu", o.dash_collapse_step_gu);
    f("near_large_far_gu", o.large_far_gu);          // the far shell (rock-real Part 1)
    f("near_large_far_fade_gu", o.large_far_fade_gu);
    f("near_large_min_px", o.large_min_px);
    f("near_small_min_px", o.small_min_px);
    f("near_far_shell_max_step_gu", o.far_shell_max_step_gu);
    f("near_far_shell_regrow_gu", o.far_shell_regrow_gu);
    f("near_stream_margin_gu", o.stream_margin_gu);
    f("collide_cooldown_s", o.collide_cooldown_s);
    return o;
}

// The speck band's keys of the same dict (far_dials.py speck_*; SPIKE).
renderer::rockfield::SpeckDials speck_dials_of(const py::dict& d) {
    renderer::rockfield::SpeckDials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    f("speck_out_gu", o.out_gu);
    f("speck_out_fade_gu", o.out_fade_gu);
    f("speck_keep_d0_gu", o.keep_d0_gu);
    f("speck_keep_band", o.keep_band);
    f("speck_keep_power", o.keep_power);
    f("speck_restream_gu", o.restream_gu);
    f("speck_band_gain", o.gain);
    return o;
}

// The puffs' keys of the same dict (far_dials.py puff_*; SPIKE).
renderer::rockfield::PuffDials puff_dials_of(const py::dict& d) {
    renderer::rockfield::PuffDials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    if (d.contains("puff_count")) o.count = std::clamp(d["puff_count"].cast<int>(), 0, 20000);
    f("puff_size_frac", o.size_frac);
    f("puff_opacity", o.opacity);
    f("puff_brightness", o.brightness);
    f("puff_start_gu", o.start_gu);
    f("puff_ramp_gu", o.ramp_gu);
    f("puff_near_fade", o.near_fade);
    return o;
}

// The mid band's keys of the same dict (far_dials.py mid_* + haze_handoff_*);
// an omitted key resets to its default.
renderer::rockfield::MidDials mid_dials_of(const py::dict& d) {
    renderer::rockfield::MidDials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    auto i = [&](const char* k, int& v) { if (d.contains(k)) v = d[k].cast<int>(); };
    f("mid_l0_tile_gu", o.l0_tile_gu);
    f("mid_l1_tile_gu", o.l1_tile_gu);
    f("mid_l2_tile_gu", o.l2_tile_gu);
    f("mid_in_lo_gu", o.in_lo_gu);
    f("mid_in_hi_gu", o.in_hi_gu);
    f("mid_l0_out_gu", o.l0_out_gu);
    f("mid_l1_out_gu", o.l1_out_gu);
    f("mid_xfade_frac", o.xfade_frac);
    f("haze_handoff_gu", o.handoff_gu);
    f("haze_handoff_band_gu", o.handoff_band_gu);
    f("mid_fill", o.fill);
    f("mid_sprite_scale", o.sprite_scale);
    i("mid_max_sprites", o.max_sprites);
    return o;
}

py::list near_contacts_list(const std::vector<renderer::rockfield::NearContact>& contacts) {
    py::list out;
    for (const auto& c : contacts) {
        py::dict d;
        d["point"] = py::make_tuple(c.point_view.x, c.point_view.y, c.point_view.z);
        d["normal"] = py::make_tuple(c.normal.x, c.normal.y, c.normal.z);
        d["rock_centre"] = py::make_tuple(c.rock_centre_view.x, c.rock_centre_view.y,
                                          c.rock_centre_view.z);
        d["rock_radius"] = c.rock_radius;
        d["rel_speed"] = c.rel_speed;
        d["pen"] = c.pen;
        d["key"] = c.key;
        out.append(d);
    }
    return out;
}

py::list contacts_list(std::vector<mr::Contact> contacts) {
    py::list out;
    for (const auto& c : contacts) {
        py::dict d;
        d["point"] = py::make_tuple(c.point_view.x, c.point_view.y, c.point_view.z);
        d["radius"] = c.radius;
        d["rel_speed"] = c.rel_speed;
        out.append(d);
    }
    return out;
}

py::dict stats_dict(const mr::Stats& s) {
    py::dict d;
    d["clouds"] = s.clouds;
    d["minors"] = s.minors;
    d["drawn"] = s.drawn;
    d["bins"] = s.bins;
    return d;
}

}  // namespace

PYBIND11_MODULE(_dauntless_host, m) {
    m.doc() = "dauntless renderer + sim host bindings";

    // Process-global developer-mode flag. Set in host_main.cc from --developer.
    // When loaded standalone (e.g. pytest), defaults to False; tests can
    // monkey-patch this attribute to exercise enabled code paths.
    m.attr("developer_mode") = dauntless::is_developer_mode();

    m.def("init", &init,
          py::arg("width"), py::arg("height"), py::arg("title"),
          "Open a window and initialise the renderer.");
    m.def("shutdown", &shutdown);

    m.def("set_game_root",
          [](const std::string& root) { renderer::set_game_root(root); },
          py::arg("root"),
          "Absolute path to the BC game install. Every relative asset path "
          "the renderer resolves is joined onto this. Default is the literal "
          "\"game\" (cwd-relative). Callable more than once.");

    m.def("set_project_asset_root",
          [](const std::string& root) { renderer::set_project_asset_root(root); },
          py::arg("root"),
          "Absolute path to the checkout's native/assets: project-authored "
          "renderer textures (the collision-scuff normal map) resolve against "
          "this, never the BC install. Pushed at boot beside set_game_root.");

    m.def("set_asset_overrides",
          [](const std::map<std::string, std::string>& overrides) {
              renderer::set_asset_overrides(overrides);
          },
          py::arg("overrides"),
          "Install mod asset overrides, keyed by case-folded relative path.");

    m.def("pick_folder",
          [](const std::string& title, const std::string& message)
              -> std::optional<std::string> {
              // The panel is modal and blocks for as long as the player
              // takes to answer. Holding the GIL across that would freeze
              // every other Python thread for the duration.
              py::gil_scoped_release release;
              return dauntless::platform::pick_folder(title, message);
          },
          py::arg("title"), py::arg("message"),
          "Show a native folder chooser and return the chosen absolute "
          "path. Returns None when the player cancels -- and also when "
          "this platform has no implementation, which callers must treat "
          "identically. title names the window; message is the "
          "explanatory line inside the panel.");

    // Introspection for tests/host/test_init_resets_frame_state.py: everything
    // reset_frame_state() clears, reduced to a count or a flag. Deliberately
    // read-only and deliberately covering EVERY member of that function -- the
    // test asserts the key set, so dropping one here fails loudly rather than
    // quietly shrinking the coverage. Safe with the host down; touches no GL.
    m.def("frame_state_debug",
          []() {
              py::dict d;
              d["phaser_beams"]       = g_phaser_beams.size();
              d["tractor_beams"]      = g_tractor_beams.size();
              d["spv_overlay_beams"]  = g_spv_overlay_beams.size();
              d["torpedoes"]          = g_torpedoes.size();
              d["hit_vfx"]            = g_hit_vfx.size();
              d["shockwaves"]         = g_shockwaves.size();
              d["particle_emitters"]  = g_particle_emitters.size();
              d["dynamic_lights"]     = g_dynamic_lights.size();
              d["lens_flares"]        = g_lens_flares.size();
              d["hull_discharges"]    = g_hull_discharges.size();
              d["cloak_ships"]        = g_cloak_ships.size();
              d["subsystem_pins"]     = g_subsystem_pins.size();
              d["debug_cylinders"]    = g_debug_cylinders.size();
              d["debug_boxes"]        = g_debug_boxes.size();
              d["debug_spheres"]      = g_debug_spheres.size();
              d["debug_cones"]        = g_debug_cones.size();
              d["backdrops"]          = g_backdrops.size();
              d["suns"]               = g_suns.size();
              d["dust_planets"]       = g_dust_planets.size();
              d["nebulae"]            = g_nebulae.size();
              d["nebula_wake"]        = g_nebula_wake.size();
              d["nebula_godrays"]     = g_nebula_godrays.size();
              d["hologram_ship_active"]   = g_hologram_ship.active;
              d["hologram_only_mode"]     = g_hologram_only_mode;
              d["spv_hull_mode"]          = g_spv_hull_mode;
              d["instance_decal_overrides"] = renderer::instance_decal_override_count();
              d["target_reticle_visible"] = g_target_reticle.visible;
              d["starmap_enabled"]        = g_starmap_scene.enabled;
              d["viewscreen_enabled"]     = g_viewscreen_enabled;
              d["bridge_pass_enabled"]    = g_bridge_pass_enabled;
              d["transform_gizmo_length"] = g_transform_gizmo.length;
              d["have_prev_viewproj"]     = g_have_prev_viewproj;
              d["render_origin"] = py::make_tuple(
                  g_render_origin.x, g_render_origin.y, g_render_origin.z);
              d["dust_motion_history"] =
                  g_dust_pass ? g_dust_pass->has_motion_history() : false;
              d["nebula_history"] = g_nebula_volumetric_pass
                  ? g_nebula_volumetric_pass->has_history() : false;
              d["letterbox_covered"]      = renderer::letterbox::covered();
              d["sky_dirty"]              = g_sky_dirty;
              d["prev_input_edges"]       = g_prev_key_state.size()
                                          + g_prev_mouse_state.size();
              d["minor_clouds"]           = g_minor_field.cloud_count();
              d["minors_enabled"]         = g_minors_enabled;
              d["minor_player"]           = g_minor_player.has_value();
              d["minor_shove_min_gups"]   = py_float(g_minor_field.dials().shove_min_gups);
              d["minor_aabb_cache"]       = g_minor_player_aabbs.size();
              d["far_sources"]            = g_far_field.source_count();
              d["far_rocks"]              = g_far_field.rock_count();
              d["far_enabled"]            = g_far_enabled;
              d["far_p_min"]              = py_float(g_far_field.dials().tiers.p_min);
              d["near_player"]            = g_near_player.has_value();
              return d;
          },
          "Test-only snapshot of the per-frame state reset_frame_state() owns: "
          "list lengths and flag values. Never call this from game code.");
    m.def("should_close", &should_close);
    m.def("frame", &frame);
    m.def("load_model", &load_model_impl,
          py::arg("nif_path"), py::arg("texture_search_path"),
          py::arg("texture_replacements") = py::none(),
          py::arg("decals") = py::none(),
          py::arg("scale") = 1.0f);
    m.def("parse_set_camera", &parse_set_camera_impl,
          "Extract the embedded camera (frustum + world transform) from a set "
          "NIF, or None. Parse-only; no GL context required.");
    m.def("nif_shapes", &nif_shapes_impl,
          py::arg("abs_path"),
          "Every NiTriShape in a NIF, in block order: block index, name, "
          "texture basenames, world-space vertices/normals, UV set 0, "
          "triangles, hidden flag. None if the file is missing or fails to "
          "parse. Parse-only, no GL context; applies no mesh fix. Feeds "
          "tools/gen_mesh_fixes.py.");

    py::class_<scenegraph::InstanceId>(m, "InstanceId")
        .def(py::init<>())
        .def_readonly("index", &scenegraph::InstanceId::index)
        .def_readonly("generation", &scenegraph::InstanceId::generation);

    m.def("create_instance",
          [](scenegraph::ModelHandle h) { return g_world.create_instance(h); },
          py::arg("model"));
    m.def("destroy_instance",
          [](scenegraph::InstanceId id) {
              // g_world.destroy_instance silently no-ops on a stale id (index
              // reused by a later generation, or already-destroyed). Guard the
              // purge below the same way: only fire it when this id was
              // actually the CURRENT occupant of that index. Without this, a
              // double-destroy on a stale id whose index has since been
              // recycled by a live instance would wipe that live instance's
              // bridge node-anim clips out from under it.
              const bool was_valid = g_world.is_valid(id);
              g_world.destroy_instance(id);
              if (was_valid) {
                  // Purge any bridge node-anim state keyed on this index BEFORE
                  // it can be recycled by a new instance in the same Python step
                  // (the lazy per-frame sweep in update_bridge_node_anims runs
                  // too late if teardown+reload happen inside a single frame).
                  g_bridge_node_anims.stop(id.index);
                  g_bridge_node_ids.erase(id.index);
                  // Release this instance's private damage field + GL atlas
                  // NOW, not whenever it next happens to be evicted:
                  // InstanceFieldCache is keyed on the FULL InstanceId
                  // (index+generation), so a new instance recycling this same
                  // index (World bumps the generation on every reuse) could
                  // never read this entry back even without this call -- but
                  // skipping it would leak the GL texture for the rest of the
                  // process's life every time a damaged ship is destroyed.
                  if (g_instance_field_cache) g_instance_field_cache->forget(id);
                  // Its set_instance_decals override (keyed on the full id,
                  // so unreachable anyway -- but not leaked).
                  renderer::clear_instance_decal_override(id);
              }
          },
          py::arg("id"));
    m.def("set_world_transform",
          [](scenegraph::InstanceId id, const std::vector<double>& m) {
              if (m.size() != 16) {
                  throw std::runtime_error("set_world_transform: need 16 doubles");
              }
              // Row-major DOUBLES from Python (pybind converts Python floats
              // losslessly); glm is column-major. Rotation*scale narrows to
              // float here (bounded, precision is fine); the translation
              // column stays double until the render origin is subtracted.
              glm::mat3 linear;
              for (int r = 0; r < 3; ++r)
                  for (int c = 0; c < 3; ++c)
                      linear[c][r] = static_cast<float>(m[r * 4 + c]);
              g_world.set_world_transform_d(id, linear,
                                            glm::dvec3(m[3], m[7], m[11]));
          },
          py::arg("id"), py::arg("mat4"),
          "Push an instance's VIEW-space pose as a row-major 4x4 of doubles. "
          "The translation column is kept in double; the renderer subtracts "
          "the render origin (set_render_origin) before narrowing to float. "
          "Unbinds any transform-store slot (a push wins over a binding).");
    m.def("set_render_origin",
          [](double x, double y, double z) {
              g_render_origin = glm::dvec3(x, y, z);
          },
          py::arg("x"), py::arg("y"), py::arg("z"),
          "The floating render origin, in VIEW space (doubles). Each frame the "
          "renderer subtracts it from every Space-pass instance's double "
          "translation before narrowing to float; Bridge and Comm instances "
          "never move with it. Takes effect at the next frame(). The camera "
          "(set_camera) must then be supplied in the same render space.");
    m.def("reset_render_origin",
          []() {
              // A discontinuity, not camera travel: zero the origin AND make
              // every pass that remembers last frame's origin forget it, so
              // the jump is never read as a smear or reprojected history.
              g_render_origin = glm::dvec3(0.0);
              if (g_dust_pass) g_dust_pass->reset_motion_history();
              if (g_nebula_volumetric_pass)
                  g_nebula_volumetric_pass->reset_history();
              if (g_system_nebula_pass)
                  g_system_nebula_pass->reset_history();
              g_have_prev_viewproj = false;
          },
          "Reset the floating render origin to (0,0,0) for a new mission, and "
          "drop the origin-dependent history of the dust, volumetric-nebula "
          "and motion-blur passes. Use set_render_origin for per-frame moves.");
    m.def("instance_translation",
          [](scenegraph::InstanceId id) -> py::object {
              const auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const glm::dvec3& t = inst->world_translation_d;
              return py::make_tuple(t.x, t.y, t.z);
          },
          py::arg("iid"),
          "The instance's VIEW-space translation (x, y, z) in double, or None "
          "for a stale id. Subtract it (in double) from a world point to form "
          "the INSTANCE-RELATIVE points the mesh queries take (ray_trace_mesh, "
          "shield_hit, hull_carve_add, hull_carve_capsule, world_to_body, "
          "damage_decal_add), and add it back to ray_trace_mesh's hit.");
    m.def("set_instance_transform_slot",
          [](scenegraph::InstanceId id, int index, std::uint32_t generation,
             double scale) {
              // Compose once now, so an instance realized between frames is
              // already in place for everything that reads inst->world outside
              // frame() (world_to_body, damage_decal_add, hull_carve_add,
              // ray_trace_mesh) instead of sitting at identity until the next
              // frame. Cheap: one instance, not a sweep.
              //
              // Order matters: set_world_transform() unbinds by construction
              // (a push always wins over a binding), so the composed matrix
              // is pushed FIRST and set_transform_slot() re-binds SECOND —
              // otherwise this "compose once" step would immediately undo
              // the very binding this function exists to create.
              if (index >= 0) {
                  auto& store = dauntless::transform_store();
                  const auto i = static_cast<std::uint32_t>(index);
                  if (store.valid(i, generation)) {
                      glm::mat3 linear;
                      glm::dvec3 translation;
                      dauntless::compose_world_linear_translation(
                          store.at(i), scale, linear, translation);
                      g_world.set_world_transform_d(id, linear, translation);
                  }
              }
              g_world.set_transform_slot(id, index, generation, scale);
          },
          py::arg("iid"), py::arg("index"), py::arg("generation"),
          py::arg("scale"),
          "Bind a render instance to a transform-store slot plus a uniform "
          "scale. The renderer composes its world matrix from the store each "
          "frame, so the transform never crosses into Python. index < 0 "
          "unbinds and restores the explicit set_world_transform path.");

    // TEST-ONLY: runs the exact per-frame store->instance sweep frame() runs,
    // without needing a GL context. Named _test_only_ (not just _debug_) so
    // its status is unmistakable at every call site — this is production
    // machinery (sync_instance_transforms_from_store, defined above) exposed
    // purely so headless tests can exercise it deterministically; it is not
    // gated behind developer mode because pytest never goes through
    // host_main.cc's argv parsing, so dauntless::is_developer_mode() would
    // read permanently false there and silently no-op every caller.
    m.def("_test_only_sync_instance_transforms",
          []() {
              sync_instance_transforms_from_store();
              g_world.resolve_render_space(g_render_origin);
          },
          "Test hook: run the per-frame store->instance sweep (and the render "
          "origin resolve) that frame() runs, without needing a GL context.");

    m.def("set_instance_bone_palette",
          [](scenegraph::InstanceId id,
             const std::vector<std::array<float, 16>>& mats) {
              // Clamp to the shader's u_bones[kMaxBones] just like
              // build_bone_palette does, so this path can't overflow the
              // uniform array on stricter GL drivers.
              const std::size_t n = std::min(mats.size(), renderer::kMaxBones);
              std::vector<glm::mat4> palette;
              palette.reserve(n);
              // glm is column-major; Python sends each mat4 as 16 floats in
              // column-major order (column 0, then column 1, ...).
              for (std::size_t i = 0; i < n; ++i)
                  palette.push_back(glm::make_mat4(mats[i].data()));
              g_world.set_bone_palette(id, std::move(palette));
          },
          py::arg("id"), py::arg("matrices"),
          "Set an instance's skinning palette (list of column-major mat4 as "
          "16 floats). Empty list restores the model's bind pose.");
    m.def("set_officer_face",
          [](scenegraph::InstanceId id, const std::string& slot_a,
             const std::string& slot_b, float mix) {
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return;
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return;
              // Resolve a slot name to a GL texture id. "neutral" (or any
              // unknown slot) -> 0, which the renderer falls back to the head's
              // own base texture for.
              auto gid = [&](const std::string& slot) -> std::uint32_t {
                  if (slot == "neutral") return 0u;
                  auto it = m->face_textures.find(slot);
                  return it != m->face_textures.end()
                      ? m->textures[static_cast<std::size_t>(it->second)].id()
                      : 0u;
              };
              g_world.set_officer_face(id, gid(slot_a), gid(slot_b), mix);
          },
          py::arg("id"), py::arg("slot_a"), py::arg("slot_b"), py::arg("mix"),
          "Lip-sync: blend an officer instance's head face texture between two "
          "slots ('neutral','a','e','u','blink1','blink2','eyesclosed') by mix "
          "in [0,1]. 'neutral' = the head's own base texture. No-op for a bad "
          "id or a non-officer model.");
    m.def("set_officer_jaw",
          [](scenegraph::InstanceId id, float openness) {
              g_world.set_officer_jaw(id, openness);
          },
          py::arg("id"), py::arg("openness"),
          "Lip-sync: set an officer's jaw openness in [0,1]; drives the "
          "Bip01 Ponytail1 bone. 0 = closed (rest). No-op for a bad id.");
    // Bind a clip onto an instance's channel table. Returns bones bound
    // (0 = dead clip on this skeleton — BC's silent no-op).
    auto bind_instance_clip = [](scenegraph::InstanceId id, int clip_index,
                                 const renderer::BindOptions& opts) -> int {
        scenegraph::Instance* in = g_world.get(id);
        if (!in) return 0;
        const assets::Model* m = resolve_model(in->model_handle);
        if (!m) return 0;
        return renderer::bind_clip(*in, *m, clip_index, opts, glfwGetTime());
    };

    m.def("set_instance_animation",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index,
                               bool loop, bool sample_at_start) {
              renderer::BindOptions o;
              o.loop = loop;
              o.root_motion = true;
              o.use_clip_base = true;
              o.hold_at_start = sample_at_start;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("sample_at_start") = false,
          "SP2: bind model.animations[clip_index]'s name-matched tracks onto "
          "this instance's bone channels (full clip: root motion applied, "
          "omitted channels fall back to the clip's own rest pose). loop=false "
          "plays once and holds; sample_at_start holds frame 0.");

    m.def("set_instance_rest_pose",
          [](scenegraph::InstanceId id, int clip_index, bool at_start) {
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return;
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return;
              renderer::set_rest_pose(*in, *m, clip_index, at_start);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("at_start") = false,
          "Freeze the officer's placement pose: sample the clip once "
          "(at_start=true → first frame, else last) into the per-bone rest "
          "locals and unbind every channel. Snap — no blend (BC positioning).");

    m.def("restore_rest_pose",
          [](scenegraph::InstanceId id) {
              scenegraph::Instance* in = g_world.get(id);
              if (!in || !in->anim.has_rest) return;
              renderer::clear_channels(*in);
          },
          py::arg("iid"),
          "Snap the instance back to its stored rest pose (AT_DEFAULT): "
          "unbind every channel; bones fall back to the placement locals.");

    m.def("anim_blend_set",
          [](float cap_s, float short_factor, int curve) {
              if (!dauntless::is_developer_mode()) return;
              renderer::set_blend_params({cap_s, short_factor, curve});
          },
          py::arg("cap_s") = 0.34f, py::arg("short_factor") = 0.75f,
          py::arg("curve") = 0,
          "DEV ONLY (--developer; no-op otherwise): live-tune the animation "
          "blend-in dials. BC defaults: cap 0.34 s, short-clip factor 0.75, "
          "curve 0 = linear (1 = smoothstep). anim_blend_set(0, 0, 0) disables "
          "blending entirely for A/B against the structural swap.");

    m.def("play_instance_idle",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              renderer::BindOptions o;
              o.loop = true;
              o.blend = true;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Loop an idle (e.g. breathing) on the clip's name-matched bones; "
          "every other bone keeps its current channel or rest local. Loops "
          "until a later bind takes its bones (per-bone last-bind-wins).");

    m.def("play_instance_gesture",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              renderer::BindOptions o;
              o.blend = true;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a transient gesture on the clip's name-matched bones only: "
          "those bones clamp+hold at the last frame until the next bind; all "
          "other bones keep running their idle (BC's non-exclusive layering). "
          "A clip matching zero bones binds nothing — BC's exact-strcmp "
          "channel join makes dead clips silent no-ops by construction.");

    m.def("play_instance_walk",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              renderer::BindOptions o;
              o.root_motion = true;
              o.use_clip_base = true;
              o.blend = true;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a walk clip WITH ROOT MOTION: the baked Bip01 root translation "
          "moves the character across the set. Plays once and settles at the "
          "last frame. Bones the clip does not track keep their channels "
          "(BC walk-ons are non-exclusive).");

    m.def("debug_instance_anim",
          [](scenegraph::InstanceId id) {
              py::list out;
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return out;
              const assets::Model* m = resolve_model(in->model_handle);
              for (std::size_t i = 0; i < in->anim.channels.size(); ++i) {
                  const auto& ch = in->anim.channels[i];
                  if (ch.clip_index < 0) continue;
                  py::dict d;
                  d["bone"] = (m && i < m->skeleton.bones.size())
                                  ? m->skeleton.bones[i].name
                                  : std::to_string(i);
                  d["clip"] = ch.clip_index;
                  d["start"] = ch.start_wall_time;
                  d["loop"] = ch.loop;
                  d["settled"] = ch.settled;
                  d["blend_in_s"] = ch.blend_in_s;
                  out.append(d);
              }
              return out;
          },
          py::arg("iid"),
          "DEV: list this instance's BOUND bone channels "
          "[{bone, clip, start, loop, settled, blend_in_s}]. Empty for a bad "
          "id or an instance with no bound channels.");

    m.def("debug_bone_palette_row",
          [](scenegraph::InstanceId id, const std::string& bone_name)
              -> py::object {
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return py::none();
              for (std::size_t i = 0; i < m->skeleton.bones.size(); ++i) {
                  if (m->skeleton.bones[i].name != bone_name) continue;
                  if (i >= in->bone_palette.size()) return py::none();
                  const glm::mat4& p = in->bone_palette[i];
                  py::list row;
                  for (int c = 0; c < 4; ++c)
                      for (int r = 0; r < 4; ++r) row.append(p[c][r]);
                  return row;
              }
              return py::none();
          },
          py::arg("iid"), py::arg("bone_name"),
          "DEV: the named bone's current 4x4 palette matrix as 16 floats "
          "(column-major), or None if the id/bone/palette is missing. Live "
          "oracle: grep stdout while printing this per frame — body bones "
          "keep oscillating through a gesture, the gesture bone plays it.");

    // ── Bridge-node (non-skinned) animation bindings ─────────────────────────
    m.def("play_instance_node_anim",
          [](scenegraph::InstanceId id, int clip_index, bool loop, bool reverse) {
              auto* in = g_world.get(id);
              if (!in) return;
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m || clip_index < 0 ||
                  clip_index >= static_cast<int>(m->animations.size())) return;
              g_bridge_node_ids[id.index] = id;
              g_bridge_node_anims.play(id.index,
                                       "embedded:" + std::to_string(clip_index),
                                       m->animations[clip_index],   // owned copy
                                       glfwGetTime(), loop, reverse);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("reverse") = false,
          "Play the instance model's embedded animations[clip_index] on its "
          "node hierarchy (non-skinned; e.g. bridge doors baked into DBridge.nif).");

    m.def("play_instance_node_clip",
          [](scenegraph::InstanceId id, const std::string& path, bool loop,
             bool reverse) {
              auto* in = g_world.get(id);
              if (!in) return;
              auto clips = assets::load_animation_clips(
                  renderer::resolve_asset_path(path));
              if (clips.empty()) return;               // NIF had no clips
              g_bridge_node_ids[id.index] = id;
              g_bridge_node_anims.play(id.index, path, std::move(clips[0]),
                                       glfwGetTime(), loop, reverse);
          },
          py::arg("iid"), py::arg("path"), py::arg("loop") = false,
          py::arg("reverse") = false,
          "Load an EXTERNAL NIF's first clip and play it on this instance's node "
          "hierarchy (e.g. db_chair_*_face_capt.nif rotating a 'console seat NN' "
          "node). The clip is held host-side; the const bridge model is never "
          "mutated.");

    m.def("stop_instance_node_anim",
          [](scenegraph::InstanceId id) {
              g_bridge_node_anims.stop(id.index);
              g_bridge_node_ids.erase(id.index);
              auto* in = g_world.get(id);
              if (in) in->node_overrides.clear();      // snap back to static
          },
          py::arg("iid"),
          "Stop any bridge-node clip on this instance and clear its node "
          "overrides (snaps the geometry back to its static pose).");

    m.def("_debug_bridge_node_anim_active_count",
          [](std::uint32_t instance_index) {
              return g_bridge_node_anims.active_count(instance_index);
          },
          py::arg("instance_index"),
          "Test-only introspection: how many bridge-node clips are active on "
          "this instance INDEX (not id). Exists so the destroy_instance "
          "stale-id purge guard can be regression-tested without a GL context.");

    m.def("instance_node_world",
          [](scenegraph::InstanceId id, const std::string& node_name,
             bool animated) -> py::object {
              auto* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return py::none();
              // Resolve robustly to the OVERRIDDEN duplicate: BC bridge models
              // NEST two nodes with the same name (e.g. "console seat 01" — an
              // outer PLACED node and its identity-local mesh child), and the
              // chair clip's override lands on the PLACED one. A naive
              // first-match could read the other (un-animated) duplicate, so a
              // coupling would see anim == rest (no motion).
              int idx = renderer::resolve_overridden_node(
                  *m, node_name, in->node_overrides);
              if (idx < 0) return py::none();
              static const std::unordered_map<int, glm::mat4> kEmpty;
              auto worlds = renderer::compose_node_worlds(
                  *m, in->world, animated ? in->node_overrides : kEmpty);
              const glm::mat4& w = worlds[idx];
              std::vector<double> out(16);             // ROW-MAJOR for Python
              for (int r = 0; r < 4; ++r)
                  for (int c = 0; c < 4; ++c) out[r * 4 + c] = w[c][r];
              // VIEW space: add back the render origin inst->world has
              // subtracted (Space pass only), in double.
              const glm::dvec3 o = view_offset_of(*in);
              out[3] += o.x; out[7] += o.y; out[11] += o.z;
              return py::cast(out);
          },
          py::arg("iid"), py::arg("node_name"), py::arg("animated") = true,
          "Return the named node's VIEW-space world transform as 16 doubles "
          "(row-major), or None if the instance/node is absent. animated=True "
          "applies the current node overrides; False composes the static "
          "locals (rest).");

    m.def("model_nodes",
          [](scenegraph::InstanceId id) {
              // SHIP units out: the SPV, articulation.part_boxes_for's derived
              // per-part boxes and hardpoint mounts all work in ship units,
              // and this is the only place the model-unit geometry meets
              // them. MODEL_TO_SHIP == BC_MODEL_SCALE == 0.01.
              constexpr float kModelToShip = 0.01f;
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) return out;          // stale id -> empty
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return out;
              for (const auto& p : renderer::model_parts(*model)) {
                  if (!p.has_bounds) continue;          // no geometry, no part
                  py::dict d;
                  d["name"] = p.name;
                  d["parent"] = p.parent;
                  d["candidate"] = p.candidate;
                  d["bounds_min"] = py::make_tuple(p.bounds_min.x * kModelToShip,
                                                   p.bounds_min.y * kModelToShip,
                                                   p.bounds_min.z * kModelToShip);
                  d["bounds_max"] = py::make_tuple(p.bounds_max.x * kModelToShip,
                                                   p.bounds_max.y * kModelToShip,
                                                   p.bounds_max.z * kModelToShip);
                  out.append(std::move(d));
              }
              return out;
          },
          py::arg("instance_id"),
          "Return [{name, parent, candidate, bounds_min, bounds_max}, ...] for "
          "every named node in this instance's model that has geometry "
          "somewhere in its subtree, bounds in SHIP units. `candidate` marks "
          "the nodes a human would call a part (renderer::model_parts).");

    // ── Per-instance decal override (SPV live preview) ───────────────────
    // Spec 2026-09-28-spv-decal-editing-design.md §2.5. Never throws: a bad
    // entry is skipped (warned once), an unknown id / a host that is down is
    // a no-op, and every per-decal fault (unknown shape, degenerate
    // projector, unloadable mask) skips that decal inside
    // build_decal_override.
    m.def("set_instance_decals",
          [](scenegraph::InstanceId id, const py::object& decals) {
              if (decals.is_none()) {
                  renderer::clear_instance_decal_override(id);
                  return;
              }
              if (!g_window) return;  // mask upload needs the GL context
              const scenegraph::Instance* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale / unknown id
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return;

              static std::unordered_set<std::string> warned_malformed;
              std::vector<assets::DecalRequest> requests;
              std::size_t index = 0;
              try {
                  for (auto item : decals) {
                      assets::DecalRequest req;
                      if (parse_decal_request(item, &req)) {
                          requests.push_back(std::move(req));
                      } else if (warned_malformed.insert(
                                     model->source.string() + "|" +
                                     std::to_string(index)).second) {
                          std::fprintf(stderr,
                              "set_instance_decals: malformed decal entry %zu "
                              "for %s (expected a 7-sequence of shape, origin, "
                              "u_axis, v_axis, normal, depth, mask_path); "
                              "skipping\n",
                              index, model->source.string().c_str());
                      }
                      ++index;
                  }
              } catch (const std::exception&) {
                  // `decals` itself is not iterable: nothing to draw.
                  std::fprintf(stderr,
                      "set_instance_decals: decals must be a list or None; "
                      "ignoring\n");
                  return;
              }
              renderer::set_instance_decal_override(
                  id, assets::build_decal_override(
                          *model, requests,
                          [](const std::filesystem::path& p) {
                              return g_decal_mask_cache.get(p);
                          }));
          },
          py::arg("instance_id"), py::arg("decals"),
          "Replace this instance's baked hull decals for drawing with `decals` "
          "(the load_model decal entry shape: (shape_or_empty, origin, "
          "u_axis, v_axis, normal, depth, mask_path), body frame, at most 16 "
          "entries sharing at most 4 distinct masks), "
          "or None to go back to the baked list. An empty list draws none. "
          "Masks load once per path, and again when the file mtime changes. "
          "Never raises.");
    m.def("instance_decal_override_size",
          [](scenegraph::InstanceId id) -> std::optional<std::size_t> {
              const auto* ov = renderer::instance_decal_override(id);
              if (ov == nullptr) return std::nullopt;
              return ov->decals.size();
          },
          py::arg("instance_id"),
          "Number of decals this instance's set_instance_decals override "
          "draws, or None when it draws its baked list.");

    // ── Part articulation (BoP wings) ────────────────────────────────────
    // Python owns the POSE (engine/appc/articulation.py, advanced on the sim
    // tick) and builds its matrix (part_pose.matrix4_model, the one place
    // ship units become model units); this binding just installs it.
    m.def("set_instance_node_transform",
          [](scenegraph::InstanceId id, const std::string& node_name,
             const std::vector<float>& m16) -> bool {
              // A full rigid pose per node (spec 2026-09-25 §5): the override
              // becomes M * local, M column-major in the node's PARENT
              // (model) space, MODEL units. Identity clears the override so a
              // part at its NIF pose leaves an EMPTY map (static node walk).
              if (m16.size() != 16) return false;
              auto* in = g_world.get(id);
              if (!in) return false;
              const assets::Model* m2 = resolve_model(in->model_handle);
              if (!m2) return false;
              const int idx = renderer::resolve_overridden_node(
                  *m2, node_name, in->node_overrides);
              if (idx < 0) return false;
              glm::mat4 M(1.0f);
              for (int c = 0; c < 4; ++c)
                  for (int r = 0; r < 4; ++r)
                      M[c][r] = m16[static_cast<std::size_t>(c * 4 + r)];
              if (M == glm::mat4(1.0f)) {
                  in->node_overrides.erase(idx);
                  return true;
              }
              in->node_overrides[idx] =
                  M * m2->nodes[static_cast<std::size_t>(idx)].local_transform;
              return true;
          },
          py::arg("iid"), py::arg("node_name"), py::arg("m16"),
          "Set a named node's pose: override = M * local, M a column-major "
          "4x4 (16 floats) in the node's PARENT space, MODEL units. Identity "
          "clears the override. False when the instance, model or node is "
          "absent, or m16 is not 16 values.");

    // The model handle an instance was created from. Appendage severance draws
    // a severed part as a SECOND INSTANCE OF THE SAME MODEL with every other
    // part hidden, so it needs the parent's handle to create that copy. Voxel
    // chunks never needed this because the native side instances them itself.
    m.def("instance_model",
          [](scenegraph::InstanceId id) -> scenegraph::ModelHandle {
              auto* in = g_world.get(id);
              return in ? in->model_handle : 0;
          },
          py::arg("iid"),
          "The model handle behind an instance, or 0 when it is absent.");

    // Hide or show ONE named node's whole subtree, by overriding its local
    // transform with the ZERO matrix: compose_node_worlds chains
    // parent_world * local, so every descendant collapses to a point and its
    // triangles become zero-area (drawn, but covering no pixels).
    //
    // Used by appendage severance to take a wing off the ship and to show ONLY
    // that wing on its debris chunk -- both are the same model, so one binding
    // serves both ends. Reuses the articulation override map rather than adding
    // a second per-node channel: hide and rotate write the SAME
    // node_overrides[idx] slot, so whichever one is called LAST wins outright
    // -- there is no ordering or priority enforced here in C++.
    //
    // That means a re-posed transform call on an already-hidden node WOULD
    // overwrite the hide (and, with the identity, ERASE it permanently). This
    // binding cannot see severance state to refuse that call, so the
    // guarantee that it never happens lives entirely on the Python side:
    // host_loop._sync_ship_articulation skips any part
    // part_severance.is_detached() reports as gone before it ever reaches
    // set_instance_node_transform, and articulation.part_transform_point
    // applies the same guard to mount points. See
    // tests/unit/test_part_severance.py's render-sync regression test for the
    // failure this once was.
    m.def("set_instance_node_hidden",
          [](scenegraph::InstanceId id, const std::string& node_name,
             bool hidden) -> bool {
              auto* in = g_world.get(id);
              if (!in) return false;
              const assets::Model* m2 = resolve_model(in->model_handle);
              if (!m2) return false;
              const int idx = renderer::resolve_overridden_node(
                  *m2, node_name, in->node_overrides);
              if (idx < 0) return false;
              if (hidden) {
                  in->node_overrides[idx] = glm::mat4(0.0f);
              } else {
                  in->node_overrides.erase(idx);
              }
              return true;
          },
          py::arg("iid"), py::arg("node_name"), py::arg("hidden"),
          "Collapse (or restore) a named node's subtree. Hiding writes the zero "
          "matrix as its local transform; showing erases the override, so the "
          "node returns to the model's authored local. False when the instance, "
          "model or node is absent.");

    m.def("clear_instance_node_overrides",
          [](scenegraph::InstanceId id) -> bool {
              auto* in = g_world.get(id);
              if (!in) return false;
              in->node_overrides.clear();
              return true;
          },
          py::arg("iid"),
          "Drop every node override on an instance (returns it to its static "
          "pose). False when the instance is absent.");

    m.def("instance_surface_points",
          [](scenegraph::InstanceId id) -> py::object {
              auto* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* mdl = resolve_model(in->model_handle);
              if (!mdl) return py::none();
              std::vector<std::tuple<double, double, double>> out;
              out.reserve(mdl->surface_points.size());
              const glm::dvec3 o = view_offset_of(*in);
              for (const glm::vec3& p : mdl->surface_points) {
                  glm::vec4 w = in->world * glm::vec4(p, 1.0f);  // model -> render
                  out.emplace_back(w.x + o.x, w.y + o.y, w.z + o.z);
              }
              return py::cast(out);
          },
          py::arg("iid"),
          "VIEW-space sample of the instance model's hull surface points "
          "(spread across the hull) for VFX anchoring.");

    m.def("load_animation_clips",
          [](const std::string& path) {
              py::list clips_out;
              for (const auto& clip :
                   assets::load_animation_clips(renderer::resolve_asset_path(path))) {
                  py::dict d;
                  d["name"] = clip.name;
                  d["duration"] = clip.duration_seconds;
                  py::list tracks_out;
                  for (const auto& tr : clip.tracks) {
                      py::dict td;
                      td["node"] = tr.target_node_name;
                      py::list tl;
                      for (const auto& k : tr.translation)
                          tl.append(py::make_tuple(k.time, k.value.x,
                                                   k.value.y, k.value.z));
                      td["translation"] = tl;
                      py::list rl;
                      for (const auto& k : tr.rotation)
                          rl.append(py::make_tuple(k.time, k.value.x,
                                                   k.value.y, k.value.z,
                                                   k.value.w));
                      td["rotation"] = rl;
                      tracks_out.append(td);
                  }
                  d["tracks"] = tracks_out;
                  clips_out.append(d);
              }
              return clips_out;
          },
          py::arg("path"),
          "Parse a NIF's keyframe controllers into animation clips: "
          "[{name, duration, tracks:[{node, translation:[(t,x,y,z)], "
          "rotation:[(t,x,y,z,w)]}]}]. Quaternions are (x,y,z,w).");
    m.def("set_visible",
          [](scenegraph::InstanceId id, bool v) { g_world.set_visible(id, v); },
          py::arg("id"), py::arg("visible"));
    m.def("set_rim_eligible",
          [](scenegraph::InstanceId id, bool eligible) {
              g_world.set_rim_eligible(id, eligible);
          },
          py::arg("id"), py::arg("eligible"),
          "Mark an instance as a ship hull eligible for the Fresnel rim "
          "term. Default false (planets stay rim-free).");
    m.def("set_rim_strength",
          [](scenegraph::InstanceId id, float strength) {
              g_world.set_rim_strength(id, strength);
          },
          py::arg("id"), py::arg("strength"),
          "Fresnel rim intensity for a rim-eligible instance. Authored by "
          "the hardpoint stats' 'SpecularCoef'; defaults to 0.1 when the "
          "ship does not define one.");
    m.def("set_surface_rock",
          [](scenegraph::InstanceId id, bool rock) {
              g_world.set_surface_rock(id, rock);
          },
          py::arg("id"), py::arg("rock"),
          "Mark an instance as rock: rock craters, no venting, grey debris.");
    m.def("set_emissive_scale",
          [](scenegraph::InstanceId id, float scale) {
              g_world.set_emissive_scale(id, scale);
          },
          py::arg("id"), py::arg("scale"),
          "Scale an instance's self-illumination (material emissive + glow "
          "map). 1.0 = normal, 0.0 = destroyed/dark hull.");

    m.def("create_bridge_instance",
          [](scenegraph::ModelHandle h) {
              auto id = g_world.create_instance(h);
              g_world.set_pass(id, scenegraph::Pass::Bridge);
              return id;
          },
          py::arg("model"),
          "Like create_instance but tags the new instance for the bridge pass.");

    m.def("create_comm_instance",
          [](scenegraph::ModelHandle h) {
              auto id = g_world.create_instance(h);
              g_world.set_pass(id, scenegraph::Pass::Comm);
              return id;
          },
          py::arg("model"),
          "Like create_instance but tags the new instance for the comm pass.");

    m.def("set_comm_set_id",
          [](scenegraph::InstanceId id, unsigned int set_id) {
              g_world.set_comm_set_id(id, set_id);
          },
          py::arg("iid"), py::arg("set_id"));

    // Developer-only (SP1): load a skinned character NIF and spawn one instance
    // framed in front of the active camera, tagged for the active pass (bridge
    // or space), with identity rotation. Character body textures live next to
    // the NIF (e.g. BodyMaleL/body.tga), so the texture search path is the NIF's
    // own directory. Reuses load_model_impl/create_instance/set_world_transform
    // — no special skinned-spawn path is needed: a non-empty skeleton routes the
    // instance through the skinned draw branch automatically.
    m.def("spawn_test_character",
          [](const std::string& nif_path) {
              std::filesystem::path tex_dir =
                  std::filesystem::path(nif_path).parent_path();
              auto handle = load_model_impl(nif_path, py::cast(tex_dir.string()),
                                            py::none(), py::none(), 1.0f);
              auto id = g_world.create_instance(handle);

              // The host owns the cameras + pass state, so it places the
              // character in front of the *active* camera (bridge if the bridge
              // pass is live, else the space/exterior camera) and tags the
              // *active* pass, so the preview is visible wherever we are.
              const bool bridge = g_bridge_pass_enabled && g_bridge_pass;
              const scenegraph::Camera& cam = bridge ? g_bridge_camera : g_camera;

              // Bounds-aware framing: the instance has an identity transform
              // (scale 1), so the model-local AABB is the world-space AABB. Use
              // the center→corner distance (length of the AABB half-extents),
              // matching get_instance_bounds, and the AABB center to recentre —
              // a character NIF's origin sits at its feet, so placing the origin
              // (rather than the centre) on the view ray rides the body up out of
              // frame. Fall back to a sane radius if the model has no CPU bounds.
              float radius = 3.0f;
              glm::vec3 center(0.0f);
              if (const assets::Model* model = resolve_model(handle)) {
                  const renderer::Aabb box = renderer::compute_model_aabb(*model);
                  const float r = glm::length(box.half_extents);
                  if (r > 0.0f) radius = r;
                  center = box.center;
              }

              glm::vec3 fwd = cam.target - cam.eye;
              const float len = glm::length(fwd);
              fwd = (len > 1e-4f) ? fwd / len : glm::vec3(0.0f, 0.0f, -1.0f);
              // Frame point ~2.5 radii ahead (margin around the body), then shift
              // so the AABB *centre* lands there rather than the model origin.
              const glm::vec3 frame_point = cam.eye + fwd * (radius * 2.5f);
              const glm::vec3 pos = frame_point - center;

              // `pos` is in the camera's space. The space camera is pushed in
              // RENDER space (relative to g_render_origin, the origin Python
              // set alongside it), and set_world_transform_d takes VIEW
              // space -- so add the origin back once, or the resolve would
              // subtract it a second time. The bridge camera is not Space.
              const glm::dvec3 view_pos =
                  glm::dvec3(pos) + (bridge ? glm::dvec3(0.0) : g_render_origin);
              g_world.set_pass(id, bridge ? scenegraph::Pass::Bridge
                                          : scenegraph::Pass::Space);
              g_world.set_world_transform_d(id, glm::mat3(1.0f), view_pos);
              return id;
          },
          py::arg("nif_path"),
          "Developer-only: spawn a skinned NIF framed in front of the active "
          "camera, tagged for the active pass (bridge or space). Returns its "
          "InstanceId.");

    // SP3: compose a bridge officer from a body NIF (skinned, owns the Bip01
    // skeleton + animations) and a separate head NIF. The head's meshes are
    // welded onto the body skeleton (authored multi-bone skin weights kept,
    // remapped by name onto body bone indices, with alias bones absorbing
    // any bind-pose mismatch) so the pair renders as ONE skinned bridge
    // instance sharing one skeleton + palette.
    //
    // body_tex / head_tex are per-officer skin FILE paths (str), resolved by
    // the caller the same way NIF paths are (absolute, or relative to cwd).
    // BC officer skins are differently-NAMED .tga files than the basename the
    // NIF embeds ("body.tga"), so a search-dir lookup can never select them;
    // compose_officer_model overrides the loaded material's Base stage via
    // set_base_texture. Empty / omitted -> keep the NIF's authored default; a
    // missing path warns and keeps the default (never crashes).
    //
    // Returns a fresh ModelHandle for the composed model (not deduped/cached —
    // each composed officer is a distinct asset). Mirrors load_model_impl's
    // handle registration.
    m.def("assemble_officer",
          [](const std::string& body_nif, const std::string& head_nif,
             const py::object& body_tex, const py::object& head_tex,
             const py::object& placement_nif, bool sample_at_start,
             const py::dict& face_images)
              -> scenegraph::ModelHandle {
              if (!g_window) {
                  throw std::runtime_error(
                      "assemble_officer: init must be called first "
                      "(asset upload needs a GL context)");
              }
              auto as_path = [](const py::object& o)
                  -> std::filesystem::path {
                  if (o.is_none()) return {};
                  return std::filesystem::path(o.cast<std::string>());
              };

              // Lip-sync face textures: {slot: path}. None values skipped.
              std::map<std::string, std::filesystem::path> faces;
              for (auto item : face_images) {
                  if (item.second.is_none()) continue;
                  faces[item.first.cast<std::string>()] =
                      std::filesystem::path(item.second.cast<std::string>());
              }

              assets::Model composed = assets::compose_officer_model(
                  body_nif, as_path(body_tex),
                  head_nif, as_path(head_tex),
                  "Bip01 Head", faces);

              // SP2: keep the skeleton; load the placement clip so the
              // per-frame animation updater can pose it through the GPU bone
              // palette. No node-walk, no skeleton clear. The Python caller
              // forwards sample_at_start to set_instance_animation (it picks the
              // clip START for "move-to-L1" clips), so it is unused here.
              (void)sample_at_start;
              const std::filesystem::path placement = as_path(placement_nif);
              if (!placement.empty()) {
                  composed.animations = assets::load_animation_clips(placement);
              }

              // Register as a new handle. compose_officer_model bypasses
              // g_cache (it builds owned, mutable models so the head's textures
              // can be moved into the body), so we wrap the composed model in a
              // shared_ptr<const Model> directly — the same handle type the
              // cache hands out. nif_path is the body NIF for diagnostics; this
              // entry is never matched by load_model_impl's dedupe (it compares
              // against single-NIF loads), which is intended.
              // Resolution 1: store as non-const shared_ptr so that
              // load_instance_clip can later const_cast the pointer and append
              // clips without UB.  The implicit conversion to ModelHandle
              // (shared_ptr<const Model>) is valid and the externally-visible
              // type is unchanged.
              assets::ModelHandle handle =
                  std::make_shared<assets::Model>(std::move(composed));
              LoadedModel lm;
              lm.nif_path   = std::filesystem::path(body_nif);
              lm.handle     = std::move(handle);
              lm.is_officer = true;
              g_loaded_models.push_back(std::move(lm));
              return static_cast<scenegraph::ModelHandle>(g_loaded_models.size());
          },
          py::arg("body_nif"), py::arg("head_nif"),
          py::arg("body_tex") = py::none(), py::arg("head_tex") = py::none(),
          py::arg("placement_nif") = py::none(),
          py::arg("sample_at_start") = false,
          py::arg("face_images") = py::dict(),
          "Developer/SP3: compose a bridge officer from a body NIF + head NIF, "
          "grafting the head onto the body's 'Bip01 Head' node. "
          "body_tex/head_tex are per-officer skin .tga FILE paths (str) that "
          "override the body/head materials' Base stage; omit to keep the NIF "
          "default. If placement_nif (str) is given, its placement clip is "
          "loaded into the composed model's animations[0] (the skeleton is "
          "KEPT); the caller then calls set_instance_animation to play it "
          "through the GPU bone palette. sample_at_start is unused here (the "
          "caller forwards it to set_instance_animation). Returns a "
          "ModelHandle.");

    // Task 4: attach a gesture/reaction NIF's animation clips to an already-
    // assembled officer model at runtime.  Returns the first new clip index so
    // the caller can drive set_instance_animation with it.
    //
    // Idempotent per (model, path): if the same path has already been appended
    // to this instance's model the stored index is returned without re-appending,
    // so the Task-5 controller can call this freely on every gesture start.
    m.def("load_instance_clip",
          [](scenegraph::InstanceId id, const std::string& path) -> int {
              auto* inst = g_world.get(id);
              if (!inst) return -1;
              auto h = inst->model_handle;
              if (h == 0 || h > static_cast<scenegraph::ModelHandle>(
                                     g_loaded_models.size())) return -1;
              auto& lm = g_loaded_models[h - 1];

              // Guard: only officer models (assemble_officer) own a mutable
              // Model underneath the const ModelHandle. Cache-loaded models
              // (load_model_impl, is_officer=false) are genuinely const —
              // const_cast on them is undefined behaviour and must never happen.
              if (!lm.is_officer) return -1;

              // Idempotency: if we've already appended clips from this path,
              // return the cached first-clip index without touching the model.
              auto it = lm.appended_clips.find(path);
              if (it != lm.appended_clips.end()) return it->second;

              // assemble_officer stored a non-const Model under the const
              // ModelHandle, so const_cast is defined behaviour here (the
              // is_officer guard above ensures we never reach this for
              // cache-loaded const models).
              assets::Model* m_ptr =
                  const_cast<assets::Model*>(lm.handle.get());
              if (!m_ptr) return -1;

              int first = static_cast<int>(m_ptr->animations.size());
              for (auto& clip :
                       assets::load_animation_clips(
                           renderer::resolve_asset_path(path))) {
                  m_ptr->animations.push_back(std::move(clip));
              }
              if (static_cast<int>(m_ptr->animations.size()) == first)
                  return -1;  // NIF had no clips — nothing appended

              lm.appended_clips[path] = first;
              return first;
          },
          py::arg("iid"), py::arg("path"),
          "Append a NIF's animation clips to this officer instance's model. "
          "Returns the first new clip index (>= 1 when a placement clip is at "
          "index 0), or -1 on failure. Idempotent: repeated calls with the same "
          "path return the same index without re-appending. Officer models are "
          "per-instance (assemble_officer never dedupes), so this is safe.");

    m.def("set_bridge_camera",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_bridge_camera.eye    = {std::get<0>(eye),    std::get<1>(eye),    std::get<2>(eye)};
              g_bridge_camera.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_bridge_camera.up     = {std::get<0>(up),     std::get<1>(up),     std::get<2>(up)};
              g_bridge_camera.fov_y_rad = fov_y_rad;
              g_bridge_camera.near = near;
              g_bridge_camera.far  = far;
              if (g_window) {
                  int fw = 0, fh = 0;
                  g_window->framebuffer_size(&fw, &fh);
                  if (fh > 0) g_bridge_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);
              }
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"),
          "Set the bridge pass camera. No-op until bridge_pass_set_enabled(True).");

    m.def("bridge_pass_set_enabled",
          [](bool enabled) { g_bridge_pass_enabled = enabled; },
          py::arg("enabled"),
          "Enable or disable the bridge render pass.");
    m.def("set_viewscreen_model",
          [](unsigned long long h) { if (g_bridge_pass) g_bridge_pass->set_viewscreen_model(h); });
    m.def("set_viewscreen_off_texture",
          [](const std::string& path) {
              if (g_bridge_pass) g_bridge_pass->set_viewscreen_off_texture(path);
          }, py::arg("path"));
    m.def("set_viewscreen_enabled",
          [](bool on) { g_viewscreen_enabled = on; });
    m.def("set_viewscreen_brightness",
          [](float b) { if (g_bridge_pass) g_bridge_pass->set_viewscreen_brightness(b); },
          py::arg("b"));
    m.def("set_viewscreen_comm_source",
          [](unsigned int set_id,
             std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_comm_source.active = true;
              g_comm_source.set_id = set_id;
              g_comm_source.cam.eye    = {std::get<0>(eye),    std::get<1>(eye),    std::get<2>(eye)};
              g_comm_source.cam.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_comm_source.cam.up     = {std::get<0>(up),     std::get<1>(up),     std::get<2>(up)};
              g_comm_source.cam.fov_y_rad = fov_y_rad;
              g_comm_source.cam.near = near;
              g_comm_source.cam.far  = far;
          },
          py::arg("set_id"), py::arg("eye"), py::arg("target"),
          py::arg("up"), py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));
    m.def("clear_viewscreen_comm_source",
          []() { g_comm_source.active = false; });
    m.def("set_viewscreen_scene_source",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_scene_source.active = true;
              g_scene_source.cam.eye    = {std::get<0>(eye),    std::get<1>(eye),    std::get<2>(eye)};
              g_scene_source.cam.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_scene_source.cam.up     = {std::get<0>(up),     std::get<1>(up),     std::get<2>(up)};
              g_scene_source.cam.fov_y_rad = fov_y_rad;
              g_scene_source.cam.near = near;
              g_scene_source.cam.far  = far;
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));
    m.def("clear_viewscreen_scene_source",
          []() { g_scene_source.active = false; });
    m.def("set_viewscreen_static_source",
          [](std::vector<std::string> paths) {
              if (g_viewscreen_static_pass)
                  g_viewscreen_static_pass->set_textures(paths);
          }, py::arg("paths"));
    m.def("set_viewscreen_static",
          [](bool on, float intensity) {
              g_viewscreen_static.on = on;
              g_viewscreen_static.intensity = intensity;
          }, py::arg("on"), py::arg("intensity"));

    m.def("set_camera",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_camera.eye = {std::get<0>(eye), std::get<1>(eye), std::get<2>(eye)};
              g_camera.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_camera.up = {std::get<0>(up), std::get<1>(up), std::get<2>(up)};
              g_camera.fov_y_rad = fov_y_rad;
              g_camera.near = near;
              g_camera.far = far;
              if (g_window) {
                  int fw = 0, fh = 0;
                  g_window->framebuffer_size(&fw, &fh);
                  if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);
              }
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));

    m.def("set_lighting",
          [](std::tuple<float,float,float> ambient,
             const std::vector<std::tuple<
                 std::tuple<float,float,float>,
                 std::tuple<float,float,float>>>& directionals) {
              g_lighting.ambient = {std::get<0>(ambient),
                                    std::get<1>(ambient),
                                    std::get<2>(ambient)};
              int n = std::min(static_cast<int>(directionals.size()),
                               renderer::Lighting::MaxDirectionals);
              g_lighting.directional_count = n;
              for (int i = 0; i < n; ++i) {
                  const auto& [dir, col] = directionals[i];
                  glm::vec3 d{std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  float len = glm::length(d);
                  g_lighting.directional_dir_ws[i] =
                      (len > 1e-6f) ? d / len : glm::vec3(0.0f, 1.0f, 0.0f);
                  g_lighting.directional_color[i] = {
                      std::get<0>(col), std::get<1>(col), std::get<2>(col)};
              }
              // Resolve the gradient ONCE PER FRAME, here -- not in the draw
              // path. submit_opaque_instance runs per instance, so reducing
              // the lights there would repeat this for every ship.
              resolve_ambient_gradient();
          },
          py::arg("ambient"), py::arg("directionals"),
          "Set the global lighting state used by the next frame()'s opaque pass.");

    m.def("set_bridge_lighting",
          [](std::tuple<float,float,float> ambient,
             const std::vector<std::tuple<
                 std::tuple<float,float,float>,
                 std::tuple<float,float,float>>>& directionals) {
              g_bridge_lighting.ambient = {std::get<0>(ambient),
                                           std::get<1>(ambient),
                                           std::get<2>(ambient)};
              int n = std::min(static_cast<int>(directionals.size()),
                               renderer::Lighting::MaxDirectionals);
              g_bridge_lighting.directional_count = n;
              for (int i = 0; i < n; ++i) {
                  const auto& [dir, col] = directionals[i];
                  glm::vec3 d{std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  float len = glm::length(d);
                  g_bridge_lighting.directional_dir_ws[i] =
                      (len > 1e-6f) ? d / len : glm::vec3(0.0f, 1.0f, 0.0f);
                  g_bridge_lighting.directional_color[i] = {
                      std::get<0>(col), std::get<1>(col), std::get<2>(col)};
              }
          },
          py::arg("ambient"), py::arg("directionals"),
          "Set the bridge pass's lighting state, applied each frame() when "
          "the bridge pass is enabled. Separate from set_lighting (which "
          "feeds the space scene).");

    m.def("set_bridge_ambient_scale",
          [](float s) { g_bridge_ambient_scale = s; },
          py::arg("scale"),
          "Ambient multiplier for the bridge INTERIOR render only (red-alert "
          "dim). The comm-set viewscreen feed always renders with the "
          "unscaled bridge lighting, so viewscreen brightness stays constant "
          "across alert levels. Default 1.0.");

    m.def("set_bridge_wall_time",
          [](double t) { if (g_bridge_pass) g_bridge_pass->set_wall_time(t); },
          py::arg("t"),
          "Wall-clock seconds used to advance NiFlipController-driven "
          "texture animations on bridge materials (e.g. EBridge's LCARS "
          "Schematic Right panel). Host loop pushes time.monotonic() each "
          "tick.");

    m.def("set_backdrops",
          [](const std::vector<py::dict>& descriptors) {
              std::vector<renderer::Backdrop> next;
              next.reserve(descriptors.size());
              for (const auto& d : descriptors) {
                  renderer::Backdrop b;
                  b.texture_path      = d["texture_path"].cast<std::string>();
                  std::string kind    = d["kind"].cast<std::string>();
                  b.kind = (kind == "star") ? renderer::BackdropKind::Star
                                            : renderer::BackdropKind::Backdrop;
                  b.h_tile            = d["h_tile"].cast<float>();
                  b.v_tile            = d["v_tile"].cast<float>();
                  b.h_span            = d["h_span"].cast<float>();
                  b.v_span            = d["v_span"].cast<float>();
                  b.target_poly_count = d["target_poly_count"].cast<int>();
                  if (d.contains("proc_kind")) {
                      std::string pk = d["proc_kind"].cast<std::string>();
                      b.proc_kind = (pk == "stars") ? 0 : (pk == "starcloud") ? 1 : 2;
                      auto col = d["color"].cast<std::vector<float>>();
                      if (col.size() == 3) b.color = glm::vec3(col[0], col[1], col[2]);
                      b.coverage = d["coverage"].cast<float>();
                      b.seed = d["seed"].cast<float>();
                      if (d.contains("envelop"))
                          b.envelop = d["envelop"].cast<int>();
                  }
                  auto m9 = d["world_rotation"].cast<std::vector<float>>();
                  if (m9.size() == 9) {
                      b.world_rotation = glm::mat3(
                          m9[0], m9[1], m9[2],
                          m9[3], m9[4], m9[5],
                          m9[6], m9[7], m9[8]);
                  }
                  next.push_back(std::move(b));
              }
              if (!renderer::backdrops_equal(next, g_backdrops)) {
                  g_sky_dirty = true;
              }
              g_backdrops = std::move(next);
          },
          py::arg("backdrops"),
          "Set the active set's ordered backdrop list, applied each frame().");

    m.def("set_suns",
          [](const std::vector<py::dict>& descs) {
              g_suns.clear();
              g_suns.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::SunDescriptor s;
                  auto pos = d["position"].cast<std::tuple<float,float,float>>();
                  s.position           = {std::get<0>(pos),
                                          std::get<1>(pos),
                                          std::get<2>(pos)};
                  s.radius             = d["radius"].cast<float>();
                  s.base_texture_path  = d["base_texture_path"].cast<std::string>();
                  s.corona_radius      = d["corona_radius"].cast<float>();
                  s.flare_texture_path =
                      d.contains("flare_texture_path")
                          ? d["flare_texture_path"].cast<std::string>()
                          : std::string{};
                  g_suns.push_back(std::move(s));
              }
          },
          py::arg("suns"),
          "Set the active sun list, applied each frame().");

    m.def("set_dust_planets",
          [](const std::vector<py::dict>& descs) {
              g_dust_planets.clear();
              g_dust_planets.reserve(descs.size());
              for (const auto& d : descs) {
                  auto pos = d["position"].cast<std::tuple<float,float,float>>();
                  const float radius = d["radius"].cast<float>();
                  g_dust_planets.emplace_back(std::get<0>(pos),
                                              std::get<1>(pos),
                                              std::get<2>(pos),
                                              radius);
              }
          },
          py::arg("planets"),
          "Set planet centres+radii used by the dust pass for proximity "
          "density scaling, applied each frame().");

    m.def("set_dust_profile",
          [](float dust) { g_dust_profile = dust; },
          py::arg("dust"),
          "Radial-profile dust column at the camera (0-1), applied each frame().");

    m.def("set_nebulae",
          [](const std::vector<py::dict>& descs) {
              g_nebulae.clear();
              g_nebulae.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::NebulaVolume v;
                  for (const auto& s :
                       d["spheres"].cast<std::vector<std::tuple<float,float,float,float>>>()) {
                      v.spheres.emplace_back(std::get<0>(s), std::get<1>(s),
                                             std::get<2>(s), std::get<3>(s));
                  }
                  auto rgb = d["rgb"].cast<std::tuple<float,float,float>>();
                  v.rgb = glm::vec3(std::get<0>(rgb), std::get<1>(rgb),
                                    std::get<2>(rgb));
                  v.visibility   = d["visibility"].cast<float>();
                  v.external_tex = d["external_tex"].cast<std::string>();
                  v.internal_tex = d["internal_tex"].cast<std::string>();
                  auto fb = d["fbm"].cast<std::tuple<float,float,float>>();
                  v.fbm  = glm::vec3(std::get<0>(fb), std::get<1>(fb), std::get<2>(fb));
                  auto sd2 = d["seed"].cast<std::tuple<float,float,float>>();
                  v.seed = glm::vec3(std::get<0>(sd2), std::get<1>(sd2), std::get<2>(sd2));
                  g_nebulae.push_back(std::move(v));
              }
          },
          py::arg("nebulae"),
          "Set the active set's MetaNebula volumes, applied each frame().");

    m.def("set_system_nebula_profile",
          [](py::object desc) {
              if (desc.is_none()) {
                  if (g_system_nebula_pass) g_system_nebula_pass->clear_profile();
                  return;
              }
              const py::dict d = desc.cast<py::dict>();
              renderer::atmosphere::RadialProfile p;
              p.r = d["r"].cast<std::vector<float>>();
              p.nebula = d["nebula"].cast<std::vector<float>>();
              if (p.r.empty() || p.r.size() != p.nebula.size())
                  throw py::value_error(
                      "set_system_nebula_profile: 'r' and 'nebula' must be "
                      "non-empty and the same length");
              p.k_sys = d["k_sys"].cast<float>();
              p.star_radius = d["star_radius"].cast<float>();
              auto rgb3 = [&](const char* key) {
                  auto t = d[key].cast<std::tuple<float, float, float>>();
                  return glm::vec3(std::get<0>(t), std::get<1>(t), std::get<2>(t));
              };
              p.cloud_rgb = rgb3("cloud_rgb");
              p.star_rgb = rgb3("star_rgb");
              renderer::atmosphere::LookParams look;
              if (d.contains("g"))       look.g = d["g"].cast<float>();
              if (d.contains("floor"))   look.floor = d["floor"].cast<float>();
              if (d.contains("scatter")) look.scatter = d["scatter"].cast<float>();
              if (d.contains("far_gu"))  look.far_gu = d["far_gu"].cast<float>();
              // Validated above even with the host down; the upload needs GL.
              if (!g_system_nebula_pass) return;
              g_system_nebula_pass->set_profile(p, look);
          },
          py::arg("profile"),
          "Set (dict) or clear (None) the system-scale nebula profile: keys "
          "r, nebula (lists, GU / 0-1), k_sys, star_radius, cloud_rgb, "
          "star_rgb (3-tuples), optional g, floor, scatter, far_gu. Builds "
          "and uploads the far-field table (CPU, ~1-2 s). Drawn only under "
          "--developer with Volumetric Nebulae on.");
    m.def("set_system_nebula_star",
          [](py::object pos) {
              if (!g_system_nebula_pass) return;
              if (pos.is_none()) {
                  g_system_nebula_pass->clear_star();
                  return;
              }
              const auto t = pos.cast<std::tuple<float, float, float>>();
              g_system_nebula_pass->set_star(glm::vec3(
                  std::get<0>(t), std::get<1>(t), std::get<2>(t)));
          },
          py::arg("pos"),
          "The system nebula's star centre in RENDER space (relative to the "
          "floating origin), applied each frame(); None when the viewed set "
          "has no sun (no forward scatter, no star-centred haze).");
    m.def("system_nebula_has_star",
          []() {
              return g_system_nebula_pass ? g_system_nebula_pass->has_star()
                                          : false;
          },
          "True when the system-scale nebula pass holds a star position.");
    m.def("system_nebula_has_profile",
          []() {
              return g_system_nebula_pass ? g_system_nebula_pass->has_profile()
                                          : false;
          },
          "True when a system-scale nebula profile is uploaded.");

    m.def("set_system_nebula_flashes",
          [](const std::vector<py::dict>& descs) {
              std::vector<renderer::GodrayFlash> flashes;
              flashes.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::GodrayFlash g;
                  auto dir = d["dir"].cast<std::tuple<float,float,float>>();
                  g.dir = glm::vec3(std::get<0>(dir), std::get<1>(dir), std::get<2>(dir));
                  g.intensity = d["intensity"].cast<float>();
                  auto c = d["color"].cast<std::tuple<float,float,float>>();
                  g.color = glm::vec3(std::get<0>(c), std::get<1>(c), std::get<2>(c));
                  flashes.push_back(g);
              }
              if (!g_system_nebula_pass) return;
              g_system_nebula_pass->set_flashes(flashes);
          },
          py::arg("flashes"),
          "Lightning flashes that light the system-scale nebula (haze and "
          "clumps): the set_nebula_godrays dict shape -- dir (render-space "
          "unit vector TOWARD the flash), intensity, color. Up to 4; extras "
          "dropped. Cleared with the profile. Developer-only pass.");
    m.def("system_nebula_flash_count",
          []() {
              return g_system_nebula_pass ? g_system_nebula_pass->flash_count()
                                          : 0;
          },
          "Number of lightning flashes the system-scale nebula pass holds.");

    m.def("system_nebula_set_dials",
          [](py::dict d) {
              if (!g_system_nebula_pass) return;
              renderer::SystemNebulaPass::Dials dials;
              if (d.contains("lane_size"))
                  dials.lane_size = d["lane_size"].cast<float>();
              if (d.contains("lane_contrast"))
                  dials.lane_contrast = d["lane_contrast"].cast<float>();
              if (d.contains("g"))
                  dials.g = d["g"].cast<float>();
              if (d.contains("floor"))
                  dials.floor = d["floor"].cast<float>();
              if (d.contains("near_range"))
                  dials.near_range = d["near_range"].cast<float>();
              g_system_nebula_pass->set_dials(dials);
          },
          py::arg("dials"),
          "Set the system-scale nebula's live look dials: optional keys "
          "lane_size, lane_contrast, g, floor, near_range -- any "
          "key omitted resets that dial to the struct default. A change to "
          "g or floor rebuilds the far-field table (~1-2s) when a profile is "
          "already uploaded; lane_size/lane_contrast/near_range never "
          "rebuild. Developer-only tuning: engine/dev_nebula_dials.py.");
    m.def("system_nebula_dials",
          []() -> py::dict {
              py::dict out;
              if (!g_system_nebula_pass) return out;
              const auto& d = g_system_nebula_pass->dials();
              out["lane_size"] = d.lane_size;
              out["lane_contrast"] = d.lane_contrast;
              out["g"] = d.g;
              out["floor"] = d.floor;
              out["near_range"] = d.near_range;
              return out;
          },
          "Current system-scale nebula look dials as a dict (empty before "
          "init).");

    // ── Minor rocks (minor-rocks spec; engine/renderer.py façade) ──────────
    // All safe with the host down: they touch only the CPU-side field. `now`
    // for clouds, fades and detaches is g_decal_game_time, the clock frame()
    // steps the field with.
    m.def("minors_add_cloud",
          [](py::dict desc) { g_minor_field.add_cloud(cloud_desc_of(desc), g_decal_game_time); },
          py::arg("desc"),
          "Add (or replace, same id) a minor-rock cloud from a desc dict.");
    m.def("minors_remove_cloud",
          [](std::uint32_t id) { g_minor_field.remove_cloud(id); }, py::arg("id"));
    m.def("minors_detach",
          [](std::uint32_t id, std::tuple<double, double, double> p0,
             std::tuple<float, float, float> v, double t0, py::object debris) {
              g_minor_field.detach(id,
                  {std::get<0>(p0), std::get<1>(p0), std::get<2>(p0)},
                  {std::get<0>(v), std::get<1>(v), std::get<2>(v)}, t0,
                  debris_of(debris));
          },
          py::arg("id"), py::arg("p0"), py::arg("v"), py::arg("t0"),
          py::arg("debris") = py::none(),
          "Turn an Instance cloud Free at VIEW-space p0 moving at v (GU/s) "
          "from game time t0, appending breakup debris dicts (None: none).");
    m.def("minors_fade_out",
          [](std::uint32_t id, float seconds) {
              g_minor_field.fade_out(id, seconds, g_decal_game_time);
          },
          py::arg("id"), py::arg("seconds"));
    m.def("minors_set_fragments",
          [](int family, const std::vector<py::tuple>& entries) {
              g_minor_field.set_fragments(family, fragments_of(entries));
          },
          py::arg("family"), py::arg("entries"),
          "Set a family's fragment meshes: [(lod0_handle, lod1_handle, "
          "bound_radius_mu[, (r, g, b) speck albedo]), ...], each loaded at scale 1.");
    m.def("minors_set_player",
          [](std::optional<scenegraph::InstanceId> iid) {
              // A new player (or none) must not be swept from the old pose.
              if (!iid || !g_minor_player || !(*iid == *g_minor_player))
                  g_minor_field.reset_player();
              g_minor_player = iid;
          },
          py::arg("iid"),
          "The instance whose hull box touches minors, or None for no contact.");
    m.def("minors_set_dials",
          [](py::dict d) { g_minor_field.set_dials(dials_of(d)); },
          py::arg("dials"),
          "Set the native minor dials (engine/rocks/minor_dials.py NATIVE_KEYS); "
          "an omitted key resets to its default.");
    m.def("minors_set_enabled",
          [](bool on) { g_minors_enabled = on; }, py::arg("enabled"));
    m.def("minors_enabled", []() { return g_minors_enabled; });
    m.def("minors_drain_contacts",
          []() {
              // Small near-band rocks are minors to the game: their shove
              // touches ride the same list, after MinorField's.
              auto out = g_minor_field.drain_contacts();
              auto near_small = g_near_field.drain_small_contacts();
              out.insert(out.end(), near_small.begin(), near_small.end());
              return contacts_list(std::move(out));
          },
          "Player/minor touches since the last drain (MinorField's, then the "
          "near band's small rocks): [{'point': VIEW-space "
          "(x,y,z), 'radius', 'rel_speed'}, ...].");
    m.def("minors_stats",
          []() {
              py::dict d = stats_dict(g_minor_field.stats());
              // What was DRAWN, summed over the frame's targets -- not the
              // step's own g_camera binning.
              d["drawn"] = g_minor_drawn;
              d["draw_calls"] = g_minor_draw_calls;
              return d;
          },
          "{'clouds', 'minors', 'bins'} from the last step; {'drawn', "
          "'draw_calls'} summed over the targets the last frame drew minors into.");
    m.def("minors_clear", []() { g_minor_field.clear(); },
          "Drop every cloud, fragment table and pending contact.");

    // ── Far tier (far-tier spec; engine/renderer.py façade) ────────────────
    // Safe with the host down: CPU state only. Atlas paths are kept in
    // g_far_atlas_paths and handed to the pass init() makes.
    m.def("far_set_catalogue",
          [](py::list entries, const std::vector<std::tuple<float, float, float>>& view_dirs,
             py::list collections) {
              std::vector<rf::CatalogueRock> rocks;
              std::vector<std::pair<std::string, std::string>> paths;
              renderer::rockfield::NearCatalogue near;
              std::vector<renderer::minors::Fragment> small_frags, large_frags;
              for (const auto& item : entries) {
                  const auto d = item.cast<py::dict>();
                  const int index = static_cast<int>(rocks.size());
                  // Near band: silicate fragments (small) and majors (large)
                  // that carry both LOD handles.
                  auto str = [&](const char* k) {
                      return d.contains(k) && !d[k].is_none() ? d[k].cast<std::string>()
                                                              : std::string();
                  };
                  const bool has_lods = d.contains("lod0") && !d["lod0"].is_none() &&
                                        d.contains("lod1") && !d["lod1"].is_none();
                  const std::string kind = str("kind");
                  if (has_lods && str("family") == "silicate" &&
                      (kind == "fragment" || kind == "major")) {
                      renderer::minors::Fragment fr;
                      fr.lod0 = d["lod0"].cast<std::uint64_t>();
                      fr.lod1 = d["lod1"].cast<std::uint64_t>();
                      fr.bound_radius_mu = d.contains("bound_radius_mu")
                          ? d["bound_radius_mu"].cast<float>() : 0.0f;
                      fr.albedo = vec3_of(d["avg_albedo"]);
                      const bool small = kind == "fragment";
                      (small ? near.small_rocks : near.large_rocks).push_back(index);
                      (small ? near.small_bound_mu : near.large_bound_mu)
                          .push_back(fr.bound_radius_mu);
                      (small ? small_frags : large_frags).push_back(fr);
                  }
                  auto albedo = d["albedo"].is_none() ? std::string()
                                                      : d["albedo"].cast<std::string>();
                  auto normal = d["normal"].is_none() ? std::string()
                                                      : d["normal"].cast<std::string>();
                  rf::CatalogueRock r;
                  r.avg_albedo = vec3_of(d["avg_albedo"]);
                  r.has_impostor = !albedo.empty() && !normal.empty();
                  rocks.push_back(r);
                  paths.emplace_back(std::move(albedo), std::move(normal));
              }
              std::vector<glm::vec3> dirs;
              dirs.reserve(view_dirs.size());
              for (const auto& t : view_dirs)
                  dirs.emplace_back(std::get<0>(t), std::get<1>(t), std::get<2>(t));
              near.view_dirs_gltf = dirs;
              // Mid band: collection i draws from atlas slot len(entries) + i.
              std::vector<renderer::rockfield::MidCollection> mid;
              for (const auto& item : collections) {
                  const auto d = item.cast<py::dict>();
                  auto path = [&](const char* k) {
                      return d.contains(k) && !d[k].is_none() ? d[k].cast<std::string>()
                                                              : std::string();
                  };
                  const int variant = d["variant"].cast<int>();
                  if (variant < 0 || variant > 2)
                      throw py::value_error("collection variant must be 0, 1 or 2");
                  mid.push_back({static_cast<int>(paths.size()), variant});
                  paths.emplace_back(path("albedo"), path("normal"));
              }
              g_mid_field.set_view_dirs(dirs);
              g_mid_field.set_collections(std::move(mid));
              g_far_field.set_catalogue(std::move(rocks), std::move(dirs));
              g_far_atlas_paths = std::move(paths);
              if (g_far_pass) g_far_pass->set_atlas_paths(g_far_atlas_paths);
              g_near_catalogue = std::move(near);
              g_near_small_frags = std::move(small_frags);
              g_near_large_frags = std::move(large_frags);
              g_near_field.set_catalogue(g_near_catalogue);
              std::vector<glm::vec3> albedo;
              for (const auto& c : g_far_field.catalogue()) albedo.push_back(c.avg_albedo);
              g_speck_band.set_catalogue(g_near_catalogue, std::move(albedo));
          },
          py::arg("entries"), py::arg("view_dirs"), py::arg("collections") = py::list(),
          "Catalogue for the far tier: [{'albedo', 'normal' (atlas paths, empty "
          "or None = no impostor), 'avg_albedo': (r, g, b)}, ...] by catalogue "
          "index, and the impostor bake's view directions (glTF axes). "
          "Optional per entry: 'kind' ('fragment' | 'major'), 'family', "
          "'lod0'/'lod1' model handles, 'bound_radius_mu' -- a silicate "
          "fragment / major with both handles streams in the near band. "
          "collections: the mid band's baked collection impostors, "
          "[{'albedo', 'normal', 'avg_albedo', 'variant' (0 sparse, 1 medium, "
          "2 dense)}, ...]; collection i uses atlas slot len(entries) + i.");
    m.def("far_set_rocks",
          [](py::list rocks) {
              std::vector<rf::FlaggedRock> out;
              std::vector<std::uint64_t> keys;
              for (const auto& item : rocks) {
                  const auto d = item.cast<py::dict>();
                  const std::uint64_t key =
                      minor_instance_key(d["instance"].cast<scenegraph::InstanceId>());
                  out.push_back(rf::FlaggedRock{key, d["index"].cast<int>(),
                                                d["radius_mu"].cast<float>()});
                  keys.push_back(key);
              }
              // Unflagged rocks go back to mesh-only now, not on some later
              // frame that may never draw them.
              std::vector<std::uint64_t> dropped;
              for (const std::uint64_t k : g_far_flagged_keys)
                  if (std::find(keys.begin(), keys.end(), k) == keys.end())
                      dropped.push_back(k);
              far_zero_fades(dropped);
              g_far_flagged_keys = std::move(keys);
              g_far_field.set_rocks(std::move(out));
          },
          py::arg("rocks"),
          "Flagged mission/breakup rocks: [{'instance': InstanceId, 'index': "
          "catalogue index (-1 = no impostor), 'radius_mu'}, ...]. Replaces the "
          "list; a rock no longer listed gets far_fade 0 at once.");
    m.def("far_set_sources",
          [](py::list sources) {
              std::vector<rf::DiscSource> out;
              for (const auto& item : sources) out.push_back(disc_source_of(item.cast<py::dict>()));
              g_far_field.set_sources(std::move(out));
              g_near_field.set_sources(g_far_field.active_sources());
              g_mid_field.set_sources(g_far_field.active_sources());
              g_speck_band.set_sources(g_far_field.active_sources());
              g_puff_field.set_sources(g_far_field.active_sources());
          },
          py::arg("sources"), "Disc density sources (DiscSource.to_native() dicts).");
    m.def("far_set_frame",
          [](std::optional<std::string> system, std::tuple<double, double, double> anchor) {
              g_far_field.set_frame(std::move(system),
                                    {std::get<0>(anchor), std::get<1>(anchor),
                                     std::get<2>(anchor)});
              g_near_field.set_sources(g_far_field.active_sources());
              g_mid_field.set_sources(g_far_field.active_sources());
              g_speck_band.set_sources(g_far_field.active_sources());
              g_puff_field.set_sources(g_far_field.active_sources());
          },
          py::arg("system"), py::arg("anchor"),
          "The viewed system (None: none) and the system position of view-space origin.");
    m.def("far_set_dials",
          [](py::dict d) {
              g_far_field.set_dials(far_dials_of(d));
              g_near_field.set_dials(near_dials_of(d));
              g_speck_band.set_near_dials(near_dials_of(d));
              g_speck_band.set_dials(speck_dials_of(d));
              g_puff_field.set_dials(puff_dials_of(d));
              g_mid_field.set_dials(mid_dials_of(d));
              g_minor_field.set_specks(g_far_enabled, g_far_field.dials().tiers.p_min);
          },
          py::arg("dials"),
          "Set the native far dials; an omitted key resets to its default.");
    m.def("far_set_enabled",
          [](bool on) {
              g_far_enabled = on;
              if (!on) {
                  far_zero_fades(g_far_flagged_keys);
                  g_near_field.clear();   // re-streams when back on
                  g_speck_band.clear();
                  g_mid_out = {};         // no stale mid output
                  g_mid_sprites = 0;
                  g_mid_fading = 0;
                  g_mid_tiles = 0;
              }
              g_minor_field.set_specks(on, g_far_field.dials().tiers.p_min);
          },
          py::arg("enabled"),
          "Turn the far tier on or off. Off: no build, no draws, every flagged "
          "rock back to mesh-only, minors stop emitting specks, and the near "
          "band drops its cells.");
    m.def("far_enabled", []() { return g_far_enabled; });
    // Rock-real Part 1 strip-back (Mark, 2026-10-03): two toggles
    // independent of far_set_enabled above (that master switch still gates
    // everything when off). Off: skip that band's build and every draw of
    // it (solid and fading); its stats read back 0. No side effects beyond
    // that -- unlike far_set_enabled, there is no stale state to clear,
    // because reset_frame_state()/far_set_enabled(false) already own that.
    m.def("rock_mid_set_enabled",
          [](bool on) { g_rock_mid_enabled = on; }, py::arg("enabled"),
          "Turn the rock-fields mid band's build and draws on or off, "
          "independent of far_set_enabled. Off: no build, no draws (solid "
          "or fading), mid_sprites/mid_fading/mid_tiles read back 0.");
    m.def("rock_mid_enabled", []() { return g_rock_mid_enabled; });
    m.def("rock_haze_set_enabled",
          [](bool on) { g_rock_haze_enabled = on; }, py::arg("enabled"),
          "Turn the rock-fields belt haze draw on or off, independent of "
          "far_set_enabled. Off: rock.haze never runs for any camera.");
    m.def("rock_haze_enabled", []() { return g_rock_haze_enabled; });
    m.def("rock_specks_set_enabled",
          [](bool on) { g_rock_specks_enabled = on; if (!on) g_speck_band.clear(); },
          py::arg("enabled"), "SPIKE: the rock-field speck band on or off.");
    m.def("rock_specks_enabled", []() { return g_rock_specks_enabled; });
    m.def("rock_puffs_set_enabled", [](bool on) { g_rock_puffs_enabled = on; },
          py::arg("enabled"), "SPIKE: the rock-field puffs on or off.");
    m.def("rock_puffs_enabled", []() { return g_rock_puffs_enabled; });
    m.def("far_stats",
          []() {
              py::dict d;
              d["sources"] = g_far_field.source_count();
              d["rocks"] = g_far_field.rock_count();
              d["impostors"] = g_far_impostors;
              d["specks"] = g_far_specks;
              d["draw_calls"] = g_far_draw_calls;
              const auto ns = g_near_field.stats();
              d["near_cells"] = ns.cells;
              d["near_small"] = ns.small;
              d["near_large"] = ns.large;
              d["near_ghosted"] = ns.ghosted;
              d["near_meshes"] = g_near_meshes;
              d["near_billboards"] = g_near_billboards;
              d["near_fading"] = g_near_fading;
              d["speck_cells"] = g_speck_band.cells();
              d["band_specks"] = g_rock_specks_drawn;
              d["puffs"] = g_rock_puffs_drawn;
              d["mid_sprites"] = g_mid_sprites;
              d["mid_fading"] = g_mid_fading;
              d["mid_tiles"] = g_mid_tiles;
              d["mid_cache_evictions"] = g_mid_field.cache_stats().evictions;
              return d;
          },
          "{'sources', 'rocks', 'near_cells', 'near_small', 'near_large', "
          "'near_ghosted'} now; {'near_meshes', 'near_billboards', "
          "'near_fading' (of the billboards, translucent), "
          "'mid_sprites' (drawn), 'mid_fading' (of the sprites, translucent), "
          "'mid_tiles' (examined)} built, "
          "'mid_cache_evictions' (MidField tile-cache size-bound clears, cumulative) and "
          "{'impostors', 'specks' (far + minor), "
          "'draw_calls'} summed over the cameras the last frame drew.");
    m.def("far_clear",
          []() {
              far_zero_fades(g_far_flagged_keys);
              g_far_flagged_keys.clear();
              g_far_field.clear();
              g_near_field.set_sources(g_far_field.active_sources());
              g_near_field.clear();
              g_near_field.reset_player();
              g_near_player.reset();
              g_mid_field.set_sources(g_far_field.active_sources());
              g_mid_out = {};
              g_mid_sprites = 0;
              g_mid_fading = 0;
              g_mid_tiles = 0;
          },
          "Drop sources, flagged rocks (back to mesh-only), frame, the near "
          "band's cells, contacts, sweep state and player, and the mid band's output; "
          "keeps the catalogue and collections.");
    m.def("rockfield_drain_contacts",
          []() { return near_contacts_list(g_near_field.drain_large_contacts()); },
          "Player/large near-rock touches since the last drain: [{'point', "
          "'normal' (rock -> ship), 'rock_centre': VIEW-space tuples, "
          "'rock_radius', 'rel_speed' (GU/s), 'pen', 'key' (int; "
          "rockfield_rearm)}, ...].");
    m.def("rockfield_rearm",
          [](std::uint64_t key) { g_near_field.rearm(key); },
          py::arg("key"),
          "Clear one large rock's touch cooldown (Python rejected its touch "
          "for geometry, e.g. a shield-bubble miss). Unknown key: no-op.");
    m.def("rockfield_catalogue_size",
          []() {
              return g_near_catalogue.small_rocks.size() + g_near_catalogue.large_rocks.size();
          },
          "Rocks in the near catalogue (small + large). 0 after init(): its "
          "model handles died with the old session, so far_tier re-pushes.");
    m.def("rockfield_set_player",
          [](std::optional<scenegraph::InstanceId> iid) {
              // A new player (or none) must not be swept from the old pose.
              if (!iid || !g_near_player || !(*iid == *g_near_player))
                  g_near_field.reset_player();
              g_near_player = iid;
          },
          py::arg("iid"),
          "The instance the near band streams around and whose hull box meets "
          "its rocks, or None (stream around the main camera, no contacts).");
    m.def("rockfield_set_shield_inflate",
          [](float scale) { g_near_shield_inflate = scale; },
          py::arg("scale"),
          "> 0: the player's near-band contact box half extents x this "
          "(shields up); <= 0: the bare hull box.");
    m.def("far_debug_haze_dials",
          []() {
              const auto& o = g_far_field.dials();
              py::dict d;
              d["haze_start_gu"] = py_float(o.haze_start_gu);
              d["haze_start_ramp_gu"] = py_float(o.haze_start_ramp_gu);
              d["haze_res_divisor"] = o.haze_res_divisor;
              return d;
          },
          "TEST-ONLY: the native haze start / ramp / resolution divisor (rock-fields Task 12).");
    m.def("far_debug_mid_centres",
          []() {
              py::list out;
              for (const auto* list : {&g_mid_out.sprites, &g_mid_out.sprites_fading})
                for (const auto& bin : *list)
                  for (const auto& it : bin.items) {
                      py::dict d;
                      d["centre"] = py::make_tuple(it.centre_half.x, it.centre_half.y,
                                                   it.centre_half.z);
                      d["half"] = it.centre_half.w;
                      d["atlas"] = bin.rock;
                      d["view"] = it.views.x;   // the heaviest blended view
                      d["dither"] = it.axis_y_dither.w;
                      out.append(d);
                  }
              return out;
          },
          "TEST-ONLY (rock-fields Task 14): the mid sprites the last drawn camera "
          "built, solid then translucent, [{'centre' (RENDER space), 'half' (GU), "
          "'atlas' (FarPass slot), 'view' (heaviest blended view index), 'dither' (signed; "
          "!= 0: translucent)}, ...]. Never call from game code.");
    m.def("far_debug_active_sources",
          []() {
              py::list out;
              for (const auto& src : g_far_field.active_sources()) {
                  py::dict d;
                  d["id"] = src.id;
                  d["shape"] = src.shape == rf::DiscSource::Shape::Sphere ? "sphere" : "disc";
                  d["procedural"] = src.procedural;
                  d["view_space"] = src.view_space;
                  d["centre"] = py::make_tuple(src.centre.x, src.centre.y, src.centre.z);
                  d["sphere_radius_gu"] = src.sphere_radius_gu;
                  d["sphere_edge_frac"] = src.sphere_edge_frac;
                  d["gain_scale"] = src.gain_scale;
                  d["brightness"] = src.brightness;
                  d["noise_scale_gu"] = src.noise_scale_gu;
                  d["noise_contrast"] = src.noise_contrast;
                  d["noise_octaves"] = src.noise_octaves;
                  d["steps"] = src.steps;
                  out.append(d);
              }
              return out;
          },
          "TEST-ONLY: the active sources (system-coordinate centres). Never call "
          "from game code.");
    m.def("far_debug_fade",
          [](scenegraph::InstanceId id) -> float {
              const scenegraph::Instance* inst = g_world.get(id);
              if (inst == nullptr) throw py::value_error("far_debug_fade: no such instance");
              return inst->far_fade;
          },
          py::arg("iid"), "TEST-ONLY: an instance's far_fade. Never call from game code.");

    // Standalone field for headless probes: no GL, no init(), no frame().
    py::class_<mr::MinorField>(m, "MinorField")
        .def(py::init<>())
        .def("add_cloud",
             [](mr::MinorField& f, py::dict desc, double now) {
                 f.add_cloud(cloud_desc_of(desc), now);
             },
             py::arg("desc"), py::arg("now"))
        .def("remove_cloud", &mr::MinorField::remove_cloud, py::arg("id"))
        .def("detach",
             [](mr::MinorField& f, std::uint32_t id,
                std::tuple<double, double, double> p0,
                std::tuple<float, float, float> v, double t0, py::object debris) {
                 f.detach(id, {std::get<0>(p0), std::get<1>(p0), std::get<2>(p0)},
                          {std::get<0>(v), std::get<1>(v), std::get<2>(v)}, t0,
                          debris_of(debris));
             },
             py::arg("id"), py::arg("p0"), py::arg("v"), py::arg("t0"),
             py::arg("debris") = py::none())
        .def("fade_out",
             [](mr::MinorField& f, std::uint32_t id, float s, double now) {
                 f.fade_out(id, s, now);
             },
             py::arg("id"), py::arg("seconds"), py::arg("now"))
        .def("set_fragments",
             [](mr::MinorField& f, int family, const std::vector<py::tuple>& e) {
                 f.set_fragments(family, fragments_of(e));
             },
             py::arg("family"), py::arg("entries"))
        .def("set_dials",
             [](mr::MinorField& f, py::dict d) { f.set_dials(dials_of(d)); },
             py::arg("dials"))
        .def("dials", [](const mr::MinorField& f) { return dials_dict(f.dials()); })
        .def("step",
             [](mr::MinorField& f, double game_time, const std::vector<float>& view16,
                const std::vector<float>& proj16, float viewport_h, py::dict anchors,
                py::object player, std::tuple<double, double, double> render_origin) {
                 mr::StepInput in;
                 in.game_time = game_time;
                 in.view = mat4_of(view16, "MinorField.step view");
                 in.proj = mat4_of(proj16, "MinorField.step proj");
                 in.viewport_h = viewport_h;
                 in.render_origin = {std::get<0>(render_origin),
                                     std::get<1>(render_origin),
                                     std::get<2>(render_origin)};
                 std::unordered_map<std::uint64_t, glm::vec3> table;
                 for (const auto& [k, v] : anchors)
                     table[k.cast<std::uint64_t>()] = vec3_of(v);
                 in.anchor_of = [table](std::uint64_t key, glm::vec3& out) {
                     const auto it = table.find(key);
                     if (it == table.end()) return false;
                     out = it->second;
                     return true;
                 };
                 if (!player.is_none()) {
                     const auto p = player.cast<py::dict>();
                     in.player = mr::PlayerBox{
                         mat4_of(p["world"].cast<std::vector<float>>(),
                                 "MinorField.step player.world"),
                         vec3_of(p["center"]), vec3_of(p["half"])};
                 }
                 f.step(in);
             },
             py::arg("game_time"), py::arg("view16"), py::arg("proj16"),
             py::arg("viewport_h"), py::arg("anchors") = py::dict(),
             py::arg("player") = py::none(),
             py::arg("render_origin") = std::make_tuple(0.0, 0.0, 0.0),
             "One step. view16/proj16 and player['world'] are 16 floats, "
             "column-major; anchors maps (index<<32)|generation -> RENDER-space "
             "(x,y,z).")
        .def("drain_contacts",
             [](mr::MinorField& f) { return contacts_list(f.drain_contacts()); })
        .def("stats", [](const mr::MinorField& f) { return stats_dict(f.stats()); });

    m.def("set_nebula_wake",
          [](const std::vector<py::dict>& pts) {
              g_nebula_wake.clear();
              g_nebula_wake.reserve(pts.size());
              for (const auto& d : pts) {
                  auto p = d["pos"].cast<std::tuple<float,float,float>>();
                  renderer::NebulaWakePoint wp;
                  wp.pos      = glm::vec3(std::get<0>(p), std::get<1>(p), std::get<2>(p));
                  wp.strength = d["strength"].cast<float>();
                  wp.size     = d["size"].cast<float>();
                  g_nebula_wake.push_back(wp);
              }
          },
          py::arg("points"), "Set the player's nebula wake trail points (pos, strength, size).");

    m.def("set_nebula_godrays",
          [](const std::vector<py::dict>& descs) {
              g_nebula_godrays.clear();
              g_nebula_godrays.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::GodrayFlash g;
                  auto dir = d["dir"].cast<std::tuple<float,float,float>>();
                  g.dir = glm::vec3(std::get<0>(dir), std::get<1>(dir), std::get<2>(dir));
                  g.intensity = d["intensity"].cast<float>();
                  auto c = d["color"].cast<std::tuple<float,float,float>>();
                  g.color = glm::vec3(std::get<0>(c), std::get<1>(c), std::get<2>(c));
                  g_nebula_godrays.push_back(g);
              }
          },
          py::arg("flashes"), "Set active lightning flashes for the god-ray pass.");

    m.def("set_lens_flares",
          [](const std::vector<py::dict>& descs) {
              g_lens_flares.clear();
              g_lens_flares.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::LensFlareDescriptor f;
                  auto pos = d["source_world_pos"].cast<std::tuple<float,float,float>>();
                  f.source_world_pos = {std::get<0>(pos),
                                        std::get<1>(pos),
                                        std::get<2>(pos)};
                  auto elements      = d["elements"].cast<std::vector<py::dict>>();
                  f.elements.reserve(elements.size());
                  for (const auto& ed : elements) {
                      renderer::LensFlareElement e;
                      e.wedges       = ed["wedges"].cast<int>();
                      e.texture_path = ed["texture_path"].cast<std::string>();
                      e.position     = ed["position"].cast<float>();
                      e.size         = ed["size"].cast<float>();
                      e.freq         = ed["freq"].cast<float>();
                      e.amp          = ed["amp"].cast<float>();
                      f.elements.push_back(std::move(e));
                  }
                  if (d.contains("brightness"))
                      f.brightness = d["brightness"].cast<float>();
                  g_lens_flares.push_back(std::move(f));
              }
          },
          py::arg("flares"),
          "Set the active lens-flare list, applied each frame().");

    // Introspection for tests/host/test_lens_flare_brightness_binding.py:
    // set_lens_flares has no other way to prove the optional "brightness"
    // key was parsed and stored rather than silently ignored (pybind
    // doesn't reject unread dict keys). Read-only, touches no GL.
    m.def("lens_flares_brightness_debug",
          []() {
              std::vector<float> out;
              out.reserve(g_lens_flares.size());
              for (const auto& f : g_lens_flares) out.push_back(f.brightness);
              return out;
          },
          "Current per-flare brightness values, in set_lens_flares order.");

    m.def("set_torpedoes",
          [](const std::vector<py::dict>& descs) {
              g_torpedoes.clear();
              g_torpedoes.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::TorpedoDescriptor t;
                  auto pos = d["position"].cast<std::tuple<float, float, float>>();
                  t.world_pos = {std::get<0>(pos), std::get<1>(pos), std::get<2>(pos)};
                  t.core_texture = d["core_texture"].cast<std::string>();
                  auto cc = d["core_color"].cast<std::tuple<float, float, float, float>>();
                  t.core_color = {std::get<0>(cc), std::get<1>(cc),
                                   std::get<2>(cc), std::get<3>(cc)};
                  t.core_size_a = d["core_size_a"].cast<float>();
                  t.core_size_b = d["core_size_b"].cast<float>();
                  t.glow_texture = d["glow_texture"].cast<std::string>();
                  auto gc = d["glow_color"].cast<std::tuple<float, float, float, float>>();
                  t.glow_color = {std::get<0>(gc), std::get<1>(gc),
                                   std::get<2>(gc), std::get<3>(gc)};
                  t.glow_size_a = d["glow_size_a"].cast<float>();
                  t.glow_size_b = d["glow_size_b"].cast<float>();
                  t.glow_size_c = d["glow_size_c"].cast<float>();
                  t.flares_texture = d["flares_texture"].cast<std::string>();
                  auto fc = d["flares_color"].cast<std::tuple<float, float, float, float>>();
                  t.flares_color = {std::get<0>(fc), std::get<1>(fc),
                                     std::get<2>(fc), std::get<3>(fc)};
                  t.num_flares     = d["num_flares"].cast<int>();
                  t.flares_size_a  = d["flares_size_a"].cast<float>();
                  t.flares_size_b  = d["flares_size_b"].cast<float>();
                  t.age            = d["age"].cast<float>();
                  t.id             = d["id"].cast<int>();
                  t.is_disruptor   = d["is_disruptor"].cast<bool>();
                  auto fwd = d["forward"].cast<std::tuple<float, float, float>>();
                  t.forward = {std::get<0>(fwd), std::get<1>(fwd), std::get<2>(fwd)};
                  auto sc = d["shell_color"].cast<std::tuple<float, float, float, float>>();
                  t.shell_color = {std::get<0>(sc), std::get<1>(sc),
                                    std::get<2>(sc), std::get<3>(sc)};
                  auto bcc = d["bolt_core_color"].cast<std::tuple<float, float, float, float>>();
                  t.bolt_core_color = {std::get<0>(bcc), std::get<1>(bcc),
                                        std::get<2>(bcc), std::get<3>(bcc)};
                  t.bolt_length = d["bolt_length"].cast<float>();
                  t.bolt_width  = d["bolt_width"].cast<float>();
                  g_torpedoes.push_back(std::move(t));
              }
          },
          py::arg("torpedoes"),
          "Set the active torpedo list, applied each frame().");

    m.def("set_dynamic_lights",
          [](const std::vector<py::dict>& descs) {
              g_dynamic_lights.clear();
              // Hard clamp to the native per-frame cap (64): silently ignore
              // any excess entries rather than raising. There is no shared
              // warning mechanism in this binding file for a soft-cap
              // condition (the other full-replace bindings here either parse
              // unconditionally or degrade via .contains(), never clamp), so
              // this is a plain comment + hard clamp rather than inventing one.
              const std::size_t n =
                  std::min(descs.size(),
                           static_cast<std::size_t>(renderer::kMaxDynamicLightsPerFrame));
              g_dynamic_lights.reserve(n);
              for (std::size_t i = 0; i < n; ++i) {
                  const auto& d = descs[i];
                  renderer::DynamicLightDescriptor l;
                  auto pos = d["position"].cast<std::tuple<float, float, float>>();
                  l.pos_a = {std::get<0>(pos), std::get<1>(pos), std::get<2>(pos)};
                  // position_b and instance_id are the two optional keys
                  // parsed unconditionally here: a point light is a
                  // degenerate segment (pos_b == pos_a), so absent/None both
                  // collapse to that same default rather than raising.
                  if (d.contains("position_b") && !d["position_b"].is_none()) {
                      auto pos_b = d["position_b"].cast<std::tuple<float, float, float>>();
                      l.pos_b = {std::get<0>(pos_b), std::get<1>(pos_b), std::get<2>(pos_b)};
                  } else {
                      l.pos_b = l.pos_a;
                  }
                  auto c = d["color"].cast<std::tuple<float, float, float>>();
                  l.color = {std::get<0>(c), std::get<1>(c), std::get<2>(c)};
                  l.radius    = d["radius"].cast<float>();
                  l.intensity = d["intensity"].cast<float>();
                  // Optional cone keys (default: not a cone). Point/strip omit all.
                  if (d.contains("direction") && !d["direction"].is_none()) {
                      auto dir = d["direction"].cast<std::tuple<float, float, float>>();
                      l.direction = {std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  }
                  if (d.contains("up") && !d["up"].is_none()) {
                      auto up = d["up"].cast<std::tuple<float, float, float>>();
                      l.up = {std::get<0>(up), std::get<1>(up), std::get<2>(up)};
                  }
                  if (d.contains("spot_tan_x") && !d["spot_tan_x"].is_none()) {
                      l.spot_tan_x = d["spot_tan_x"].cast<float>();
                  }
                  if (d.contains("spot_tan_y") && !d["spot_tan_y"].is_none()) {
                      l.spot_tan_y = d["spot_tan_y"].cast<float>();
                  }
                  // Optional attachment (second optional key after position_b).
                  // Set => the geometry above is BODY-frame and frame()
                  // resolves it through inst->world after the store sweep.
                  // Absent/None => world-space, byte-identical to before.
                  if (d.contains("instance_id") && !d["instance_id"].is_none())
                      l.instance_id = d["instance_id"].cast<scenegraph::InstanceId>();
                  g_dynamic_lights.push_back(l);
              }
          },
          py::arg("lights"),
          "Replace the active dynamic-light list, applied each frame(). Each "
          "dict has position (pos_a), color, radius, intensity, plus optional "
          "position_b (pos_b defaults to position for a point light), and "
          "optional cone keys direction (3-tuple, world-space axis), up "
          "(3-tuple, world-space axis orienting the ellipse; defaults to "
          "{0,1,0}), spot_tan_x and spot_tan_y (tan(half-angle) along right/up; "
          "absent/None => not a cone, point/strip behaviour unchanged), and "
          "instance_id (an InstanceId; when set, position/position_b/direction/"
          "up above are BODY-frame and frame() resolves them through the "
          "instance's world transform after the store sweep; absent/None => "
          "world-space, unchanged). "
          "Clamped to kMaxDynamicLightsPerFrame entries.");

    m.def("set_shockwaves",
          [](const std::vector<py::dict>& descs) {
              g_shockwaves.clear();
              g_shockwaves.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::ShockwaveDescriptor s;
                  auto c = d["world_center"].cast<std::tuple<float, float, float>>();
                  s.world_center = {std::get<0>(c), std::get<1>(c), std::get<2>(c)};
                  s.max_radius = d["max_radius"].cast<float>();
                  s.age        = d["age"].cast<float>();
                  s.lifetime   = d["lifetime"].cast<float>();
                  g_shockwaves.push_back(std::move(s));
              }
          },
          py::arg("shockwaves"),
          "Replace the active warp-core breach shockwaves: a list of dicts with "
          "keys world_center (a (cx,cy,cz) tuple), max_radius, age, lifetime.");

    m.def("set_hit_vfx",
          [](const std::vector<py::dict>& descs) {
              g_hit_vfx.clear();
              g_hit_vfx.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::HitVfxDescriptor v;
                  auto pos = d["position"].cast<std::tuple<float, float, float>>();
                  v.world_pos = {std::get<0>(pos), std::get<1>(pos), std::get<2>(pos)};
                  auto n = d["normal"].cast<std::tuple<float, float, float>>();
                  v.surface_normal = {std::get<0>(n), std::get<1>(n), std::get<2>(n)};
                  v.severity = d["severity"].cast<int>();
                  v.age = d["age"].cast<float>();
                  if (d.contains("instance_id") && !d["instance_id"].is_none()) {
                      v.instance_id = d["instance_id"].cast<scenegraph::InstanceId>();
                  }
                  v.weapon_kind = d.contains("weapon_kind") ? d["weapon_kind"].cast<int>() : 1;
                  v.spark_count = d.contains("spark_count") ? d["spark_count"].cast<int>() : 0;
                  if (d.contains("body_point") && !d["body_point"].is_none()) {
                      auto bp = d["body_point"].cast<std::tuple<float, float, float>>();
                      v.body_point = {std::get<0>(bp), std::get<1>(bp), std::get<2>(bp)};
                      // Both the flash and the sparks ride this. body_point
                      // defaults to the model origin, a legitimate value, so
                      // presence is flagged rather than sniffed.
                      v.has_body_anchor = true;
                  }
                  if (d.contains("body_normal") && !d["body_normal"].is_none()) {
                      auto bn = d["body_normal"].cast<std::tuple<float, float, float>>();
                      v.body_normal = {std::get<0>(bn), std::get<1>(bn), std::get<2>(bn)};
                  }
                  g_hit_vfx.push_back(std::move(v));
              }
          },
          py::arg("vfx"),
          "Set the active hit-VFX list, applied each frame(). Each dict has "
          "position + normal + severity + age, plus optional spark fields "
          "(instance_id, body_point, body_normal, weapon_kind, spark_count).");

    m.def("set_hull_discharges",
          [](const std::vector<py::dict>& descs) {
              g_hull_discharges.clear();
              g_hull_discharges.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::HullDischarge h;
                  auto p = d["world_pos"].cast<std::tuple<float,float,float>>();
                  h.world_pos = glm::vec3(std::get<0>(p), std::get<1>(p), std::get<2>(p));
                  h.age  = d["age"].cast<float>();
                  h.life = d["life"].cast<float>();
                  h.size = d["size"].cast<float>();
                  auto c = d["color"].cast<std::tuple<float,float,float>>();
                  h.color = glm::vec3(std::get<0>(c), std::get<1>(c), std::get<2>(c));
                  g_hull_discharges.push_back(h);
              }
          },
          py::arg("discharges"), "Set active hull electrical discharges.");

    m.def("set_particle_emitters",
          [](const std::vector<py::dict>& descs) {
              g_particle_emitters.clear();
              g_particle_emitters.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::ParticleEmitterDescriptor e;
                  if (d.contains("instance_id") && !d["instance_id"].is_none())
                      e.instance_id = d["instance_id"].cast<scenegraph::InstanceId>();
                  auto p = d["emit_pos"].cast<std::tuple<float,float,float>>();
                  e.emit_pos = {std::get<0>(p), std::get<1>(p), std::get<2>(p)};
                  auto dir = d["emit_dir"].cast<std::tuple<float,float,float>>();
                  e.emit_dir = {std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  auto vel = d["emit_vel_world"].cast<std::tuple<float,float,float>>();
                  e.emit_vel_world = {std::get<0>(vel), std::get<1>(vel), std::get<2>(vel)};
                  e.inherit            = d["inherit"].cast<float>();
                  e.emit_velocity      = d["emit_velocity"].cast<float>();
                  e.angle_variance     = d["angle_variance"].cast<float>();
                  e.emit_life          = d["emit_life"].cast<float>();
                  e.emit_life_variance = d["emit_life_variance"].cast<float>();
                  e.emit_frequency     = d["emit_frequency"].cast<float>();
                  e.effect_age         = d["effect_age"].cast<float>();
                  e.stop_age           = d["stop_age"].cast<float>();
                  e.draw_old_to_new    = d["draw_old_to_new"].cast<int>();
                  e.texture_path       = d["texture_path"].cast<std::string>();
                  auto load_keys = [&](const char* key, int& count, renderer::ParticleKey* out, bool color) {
                      count = 0;
                      if (!d.contains(key)) return;
                      for (const auto& k : d[key].cast<std::vector<py::tuple>>()) {
                          if (count >= 8) break;
                          renderer::ParticleKey pk;
                          pk.t = k[0].cast<float>();
                          if (color) { pk.r = k[1].cast<float>(); pk.g = k[2].cast<float>(); pk.b = k[3].cast<float>(); }
                          else       { pk.v = k[1].cast<float>(); }
                          out[count++] = pk;
                      }
                  };
                  load_keys("color_keys", e.num_color_keys, e.color_keys, true);
                  load_keys("alpha_keys", e.num_alpha_keys, e.alpha_keys, false);
                  load_keys("size_keys",  e.num_size_keys,  e.size_keys,  false);
                  // A2 explosion extensions — default to A1 behaviour when absent.
                  e.blend_mode            = d.contains("blend_mode")            ? d["blend_mode"].cast<int>()            : 0;
                  e.emit_radius           = d.contains("emit_radius")           ? d["emit_radius"].cast<float>()           : 0.0f;
                  e.random_velocity_cone  = d.contains("random_velocity_cone")  ? d["random_velocity_cone"].cast<float>()  : 0.0f;
                  e.random_velocity_speed = d.contains("random_velocity_speed") ? d["random_velocity_speed"].cast<float>() : 0.0f;
                  e.damping     = d.contains("damping")     ? d["damping"].cast<float>()     : 0.0f;
                  e.tail_length = d.contains("tail_length") ? d["tail_length"].cast<float>() : 0.0f;
                  e.atlas_cols  = d.contains("atlas_cols")  ? d["atlas_cols"].cast<int>()    : 1;
                  e.atlas_rows  = d.contains("atlas_rows")  ? d["atlas_rows"].cast<int>()    : 1;
                  e.seed        = d.contains("seed")        ? d["seed"].cast<float>()        : 0.0f;
                  g_particle_emitters.push_back(std::move(e));
              }
          },
          py::arg("emitters"),
          "Set the active particle-emitter list, applied each frame().");

    m.def("set_phaser_beams",
          [](const std::vector<py::dict>& descs) {
              g_phaser_beams.clear();
              g_phaser_beams.reserve(descs.size());
              for (const auto& d : descs)
                  g_phaser_beams.push_back(beam_from_dict(d));
          },
          py::arg("beams"),
          "Set the active phaser-beam list, applied each frame().");

    m.def("set_tractor_beams",
          [](const std::vector<py::dict>& descs) {
              g_tractor_beams.clear();
              g_tractor_beams.reserve(descs.size());
              for (const auto& d : descs)
                  g_tractor_beams.push_back(beam_from_dict(d));
          },
          py::arg("beams"),
          "Set the active tractor-beam list (rendered by the shared beam pass), "
          "applied each frame().");

    m.def("set_spv_overlay_beams",
          [](const std::vector<py::dict>& descs) {
              g_spv_overlay_beams.clear();
              g_spv_overlay_beams.reserve(descs.size());
              for (const auto& d : descs)
                  g_spv_overlay_beams.push_back(beam_from_dict(d));
          },
          py::arg("beams"),
          "Set the Ship Property Viewer phaser strip/arc overlay beams "
          "(rendered depth-test-off in viewer_mode). Applied each frame().");

    m.def("clear_spv_overlay_beams",
          []() { g_spv_overlay_beams.clear(); },
          "Clear the SPV phaser overlay beams. Takes effect next frame().");

    m.def("set_debug_cylinders",
          [](const std::vector<py::dict>& descs) {
              g_debug_cylinders.clear();
              g_debug_cylinders.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::DebugCylinder c;
                  if (d.contains("center")) {
                      auto v = d["center"].cast<std::array<float, 3>>();
                      c.center = {v[0], v[1], v[2]};
                  }
                  if (d.contains("axis")) {
                      auto v = d["axis"].cast<std::array<float, 3>>();
                      c.axis = {v[0], v[1], v[2]};
                  }
                  if (d.contains("radius")) c.radius = d["radius"].cast<float>();
                  if (d.contains("length")) c.length = d["length"].cast<float>();
                  if (d.contains("color")) {
                      auto v = d["color"].cast<std::array<float, 3>>();
                      c.color = {v[0], v[1], v[2]};
                  }
                  g_debug_cylinders.push_back(c);
              }
          },
          py::arg("cylinders"),
          "Set the world-space debug wireframe cylinders (Ship Property Viewer "
          "glow-region overlay; rendered depth-test-off in viewer_mode only). "
          "Each dict: center, axis, radius, length, color. Applied each frame().");

    m.def("clear_debug_cylinders",
          []() { g_debug_cylinders.clear(); },
          "Clear the debug wireframe cylinders. Takes effect next frame().");

    m.def("set_debug_boxes",
          [](const std::vector<py::dict>& descs) {
              g_debug_boxes.clear();
              g_debug_boxes.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::DebugBox b;
                  auto v3 = [&](const char* k, glm::vec3& out) {
                      if (d.contains(k)) {
                          auto v = d[k].cast<std::array<float, 3>>();
                          out = {v[0], v[1], v[2]};
                      }
                  };
                  v3("center", b.center); v3("ex", b.ex); v3("ey", b.ey);
                  v3("ez", b.ez); v3("color", b.color);
                  g_debug_boxes.push_back(b);
              }
          },
          py::arg("boxes"),
          "Set the world-space debug wireframe boxes (SPV glow-region overlay; "
          "viewer_mode only). Each dict: center, ex, ey, ez, color.");

    m.def("clear_debug_boxes",
          []() { g_debug_boxes.clear(); },
          "Clear the debug wireframe boxes. Takes effect next frame().");

    m.def("set_debug_spheres",
          [](const std::vector<py::dict>& descs) {
              g_debug_spheres.clear();
              g_debug_spheres.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::DebugSphere s;
                  if (d.contains("center")) {
                      auto v = d["center"].cast<std::array<float, 3>>();
                      s.center = {v[0], v[1], v[2]};
                  }
                  if (d.contains("radius")) s.radius = d["radius"].cast<float>();
                  if (d.contains("color")) {
                      auto v = d["color"].cast<std::array<float, 3>>();
                      s.color = {v[0], v[1], v[2]};
                  }
                  g_debug_spheres.push_back(s);
              }
          },
          py::arg("spheres"),
          "Set the world-space debug wireframe spheres (SPV selected-subsystem "
          "volume; viewer_mode only). Each dict: center, radius, color.");

    m.def("clear_debug_spheres",
          []() { g_debug_spheres.clear(); },
          "Clear the debug wireframe spheres. Takes effect next frame().");

    m.def("set_debug_cones",
          [](const std::vector<py::dict>& descs) {
              g_debug_cones.clear();
              g_debug_cones.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::DebugCone c;
                  if (d.contains("apex")) {
                      auto v = d["apex"].cast<std::array<float, 3>>();
                      c.apex = {v[0], v[1], v[2]};
                  }
                  if (d.contains("axis")) {
                      auto v = d["axis"].cast<std::array<float, 3>>();
                      c.axis = {v[0], v[1], v[2]};
                  }
                  if (d.contains("radius")) c.radius = d["radius"].cast<float>();
                  if (d.contains("length")) c.length = d["length"].cast<float>();
                  if (d.contains("color")) {
                      auto v = d["color"].cast<std::array<float, 3>>();
                      c.color = {v[0], v[1], v[2]};
                  }
                  // radius_y defaults to radius (circular cone); up defaults
                  // to the struct default {0,1,0}.
                  c.radius_y = c.radius;
                  if (d.contains("radius_y") && !d["radius_y"].is_none()) {
                      c.radius_y = d["radius_y"].cast<float>();
                  }
                  if (d.contains("up") && !d["up"].is_none()) {
                      auto v = d["up"].cast<std::array<float, 3>>();
                      c.up = {v[0], v[1], v[2]};
                  }
                  g_debug_cones.push_back(c);
              }
          },
          py::arg("cones"),
          "Set the world-space debug wireframe cones (SPV cone light-emitter "
          "overlay; rendered depth-test-off in viewer_mode only). Each dict: "
          "apex, axis, radius, length, color, plus optional radius_y (base "
          "radius along up; defaults to radius) and up (3-tuple, orients the "
          "ellipse; defaults to {0,1,0}). Applied each frame().");

    m.def("clear_debug_cones",
          []() { g_debug_cones.clear(); },
          "Clear the debug wireframe cones. Takes effect next frame().");

    m.def("set_transform_gizmo",
          [](std::array<float, 3> o,
             std::array<float, 3> ax, std::array<float, 3> ay, std::array<float, 3> az,
             float length, int highlight, int handle_kind) {
              g_transform_gizmo.origin = {o[0], o[1], o[2]};
              g_transform_gizmo.axis[0] = {ax[0], ax[1], ax[2]};
              g_transform_gizmo.axis[1] = {ay[0], ay[1], ay[2]};
              g_transform_gizmo.axis[2] = {az[0], az[1], az[2]};
              g_transform_gizmo.length = length;
              g_transform_gizmo.highlight = highlight;
              g_transform_gizmo.handle_kind = handle_kind;
          },
          py::arg("origin"), py::arg("axis_x"), py::arg("axis_y"), py::arg("axis_z"),
          py::arg("length"), py::arg("highlight"), py::arg("handle_kind"),
          "Set the Ship Property Viewer transform gizmo (three coloured "
          "arrows; rendered depth-test-off in viewer_mode only). "
          "highlight: 0/1/2 brightens that axis, -1 for none. "
          "handle_kind: 0 = cone tip (Move), 1 = cube tip (Scale), "
          "2 = rings (Rotate). "
          "Applied each frame().");

    m.def("clear_transform_gizmo",
          []() { g_transform_gizmo.length = 0.0f; },
          "Hide the transform gizmo. Takes effect next frame().");

    m.def("set_hologram_ship",
          [](scenegraph::InstanceId iid,
             std::array<float, 3> color,
             float opacity_facing,
             float opacity_grazing) {
              g_hologram_ship.active          = true;
              g_hologram_ship.instance        = iid;
              g_hologram_ship.color           = {color[0], color[1], color[2]};
              g_hologram_ship.opacity_facing  = opacity_facing;
              g_hologram_ship.opacity_grazing = opacity_grazing;
          },
          py::arg("instance_id"), py::arg("color"),
          py::arg("opacity_facing"), py::arg("opacity_grazing"),
          "Set the ship drawn as a Fresnel hologram overlay. Pass the scenegraph "
          "InstanceId of the ship, its tint color (r,g,b), and opacity at facing "
          "and grazing angles. Takes effect next frame().");
    m.def("clear_hologram_ship",
          []() { g_hologram_ship = renderer::HologramShip{}; },
          "Clear the hologram overlay (deactivates it). Takes effect next frame().");
    m.def("set_cloak_ships",
          [](const std::vector<std::pair<scenegraph::InstanceId, float>>& ships) {
              g_cloak_ships.clear();
              g_cloak_ships.reserve(ships.size());
              for (const auto& s : ships)
                  g_cloak_ships.push_back({s.first, s.second});
          },
          py::arg("ships"),
          "Set the cloaking ships drawn as refractive shells this frame. Each "
          "entry is (instance_id, frac) where frac in [0,1] is cloak progress "
          "(0 = visible, 1 = fully cloaked). Replaces the prior list; pass an "
          "empty list to draw none. Takes effect next frame().");
    m.def("set_cloak_dials",
          [](float strength, float dispersion, std::array<float, 3> tint,
             float opacity_floor, float opacity_ceiling, float shimmer_amp,
             float shimmer_speed, float vertex_wobble, float normal_bias) {
              if (g_cloak_pass) {
                  g_cloak_pass->set_strength(strength);
                  g_cloak_pass->set_dispersion(dispersion);
                  g_cloak_pass->set_tint({tint[0], tint[1], tint[2]});
                  g_cloak_pass->set_opacity_floor(opacity_floor);
                  g_cloak_pass->set_opacity_ceiling(opacity_ceiling);
                  g_cloak_pass->set_shimmer_amp(shimmer_amp);
                  g_cloak_pass->set_shimmer_speed(shimmer_speed);
                  g_cloak_pass->set_vertex_wobble(vertex_wobble);
                  g_cloak_pass->set_normal_bias(normal_bias);
              }
          },
          py::arg("strength"), py::arg("dispersion"),
          py::arg("tint") = std::array<float, 3>{0.20f, 0.85f, 0.55f},
          py::arg("opacity_floor") = 0.10f,
          py::arg("opacity_ceiling") = 0.50f,
          py::arg("shimmer_amp") = 0.010f,
          py::arg("shimmer_speed") = 6.0f,
          py::arg("vertex_wobble") = 0.05f,
          py::arg("normal_bias") = 1.0f,
          "Live-tune the cloak: max screen-space refraction offset (strength), "
          "prism split (dispersion), rim tint (r,g,b), glow-keyed opacity "
          "floor/ceiling, animated screen-space shimmer amp/speed, vertex-wobble "
          "amplitude (game units), and normal_bias (0 = flat, 1 = grazing).");
    m.def("set_hologram_only_mode",
          [](bool enabled, std::array<float, 3> bg) {
              g_hologram_only_mode = enabled;
              g_hologram_bg = {bg[0], bg[1], bg[2]};
          },
          py::arg("enabled"), py::arg("bg") = std::array<float, 3>{0.0f, 0.0f, 0.0f},
          "When enabled, frame() clears to bg (r,g,b) and skips the space scene "
          "and bridge pass, drawing only the hologram + subsystem pins.");
    m.def("set_spv_hull_mode",
          [](bool enabled) { g_spv_hull_mode = enabled; },
          py::arg("enabled"),
          "Ship Property Viewer render mode. When enabled, the active hologram "
          "ship is drawn with its real hull textures (full opaque lighting) "
          "instead of the Fresnel hologram. Default false = hologram.");
    m.def("get_instance_bounds",
          [](scenegraph::InstanceId iid) -> py::object {
              const scenegraph::Instance* inst = g_world.get(iid);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return py::none();
              renderer::Aabb box = renderer::compute_model_aabb(*model);
              const glm::vec4 c = inst->world * glm::vec4(box.center, 1.0f);
              // Uniform-scale factor baked into the instance world matrix
              // (the X basis column length), so the world-space bounding
              // radius matches the rendered size even if the ship is scaled.
              const float scale = glm::length(glm::vec3(inst->world[0]));
              const float radius = glm::length(box.half_extents) * scale;
              const glm::dvec3 o = view_offset_of(*inst);
              return py::make_tuple(c.x + o.x, c.y + o.y, c.z + o.z, radius);
          },
          py::arg("instance_id"),
          "Return (cx, cy, cz, radius) VIEW-space bounding sphere of the "
          "instance's model, or None if the instance/model is not resolvable.");
    m.def("get_instance_head_center",
          [](scenegraph::InstanceId iid) -> py::object {
              // World-space centre of a posed character's HEAD — the officer
              // zoom look-at point. Skins every vertex exactly as
              // skinned_bridge.vert does (skin = sum w_k * palette[idx_k];
              // world = u_model * skin * v), then takes the AABB centre of
              // ONLY the vertices that belong to the grafted head mesh range
              // [model->head_mesh_begin, meshes.size()) — the canonical
              // head/body partition set up by graft_head_cpu (see
              // model_compose.h). The weld remaps grafted head vertices onto
              // ALIAS bones (name = body bone + "@head-bind") on bind-pose-
              // mismatched pairs, so those vertices are no longer bound to
              // the body's own "Bip01 Head" bone index; classifying by mesh
              // range instead of bone index is robust to that. Falls back to
              // the "Bip01 Head" bone-index test only when the model has no
              // head_mesh_begin (head_mesh_begin < 0, e.g. non-composed
              // models), then to the full-body skinned centre when there is
              // no head bone either. Returns None for an unskinned / not-yet-
              // posed instance (caller -> captain view).
              //
              // Unlike get_instance_bounds (static AABB * inst.world), this
              // uses the bone palette: a bridge officer sits at inst.world ==
              // identity with the station offset baked into the palette, so
              // get_instance_bounds collapses every officer to ~the model
              // origin (low + identical for all). The body AABB centre reads
              // too low (waist); the head centre gives a level look at the face.
              const scenegraph::Instance* inst = g_world.get(iid);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || inst->bone_palette.empty()) return py::none();
              const auto& palette = inst->bone_palette;

              const bool use_mesh_range = model->head_mesh_begin >= 0;

              int head_bi = -1;
              if (!use_mesh_range) {
                  for (std::size_t i = 0; i < model->skeleton.bones.size(); ++i) {
                      if (model->skeleton.bones[i].name == "Bip01 Head") {
                          head_bi = static_cast<int>(i);
                          break;
                      }
                  }
              }

              glm::vec3 head_lo(1e30f), head_hi(-1e30f);
              glm::vec3 body_lo(1e30f), body_hi(-1e30f);
              bool any_head = false, any_body = false;
              for (std::size_t mesh_idx = 0; mesh_idx < model->meshes.size();
                   ++mesh_idx) {
                  const auto& mesh = model->meshes[mesh_idx];
                  const bool mesh_is_head =
                      use_mesh_range &&
                      static_cast<int>(mesh_idx) >= model->head_mesh_begin;
                  const auto& cd = mesh.cpu_data();
                  if (!cd) continue;
                  for (const auto& v : cd->vertices) {
                      const glm::vec4 p(v.position, 1.0f);
                      glm::vec4 skinned(0.0f);
                      float wsum = 0.0f;
                      bool on_head = mesh_is_head;
                      for (int k = 0; k < 4; ++k) {
                          const float w = static_cast<float>(v.bone_weights[k]) / 255.0f;
                          if (w <= 0.0f) continue;
                          const std::size_t bi =
                              static_cast<std::size_t>(v.bone_indices[k]);
                          if (bi >= palette.size()) continue;   // GPU-safe guard
                          skinned += w * (palette[bi] * p);
                          wsum += w;
                          if (!use_mesh_range && static_cast<int>(bi) == head_bi) {
                              on_head = true;
                          }
                      }
                      if (wsum <= 0.0f) continue;
                      const glm::vec3 s(skinned);
                      body_lo = glm::min(body_lo, s);
                      body_hi = glm::max(body_hi, s);
                      any_body = true;
                      if (on_head) {
                          head_lo = glm::min(head_lo, s);
                          head_hi = glm::max(head_hi, s);
                          any_head = true;
                      }
                  }
              }
              glm::vec3 center;
              if (any_head)      center = 0.5f * (head_lo + head_hi);
              else if (any_body) center = 0.5f * (body_lo + body_hi);
              else               return py::none();
              const glm::vec4 c = inst->world * glm::vec4(center, 1.0f);
              const glm::dvec3 o = view_offset_of(*inst);
              return py::make_tuple(c.x + o.x, c.y + o.y, c.z + o.z);
          },
          py::arg("instance_id"),
          "Return (cx, cy, cz) VIEW-space centre of a posed character's HEAD "
          "(vertices in the grafted head mesh range, model->head_mesh_begin, "
          "or bound to 'Bip01 Head' as a fallback for non-composed models), "
          "or the full skinned centre if there is no head, or None if "
          "unskinned / not posed. The officer zoom look-at point — "
          "get_instance_bounds ignores the bone palette.");
    m.def("set_subsystem_pins",
          [](const std::vector<std::tuple<std::array<float, 3>, int, bool>>& pins) {
              g_subsystem_pins.clear();
              g_subsystem_pins.reserve(pins.size());
              for (const auto& t : pins) {
                  renderer::SubsystemPin p;
                  const auto& pos = std::get<0>(t);
                  p.world_pos   = {pos[0], pos[1], pos[2]};
                  p.icon_id     = std::get<1>(t);
                  p.highlighted = std::get<2>(t);
                  g_subsystem_pins.push_back(p);
              }
          },
          py::arg("pins"),
          "Set the subsystem pin billboard list. Each element is "
          "(world_pos:(x,y,z), icon_id:int, highlighted:bool). Applied each frame().");
    m.def("clear_subsystem_pins",
          []() { g_subsystem_pins.clear(); },
          "Clear all subsystem pin billboards. Takes effect next frame().");

    m.def("set_target_reticle",
          [](bool visible,
             std::array<float, 3> ship_center, float ship_radius,
             py::object subtarget_pos, float bar_alignment) {
              g_target_reticle.visible     = visible;
              g_target_reticle.ship_center = {ship_center[0], ship_center[1], ship_center[2]};
              g_target_reticle.ship_radius = ship_radius;
              g_target_reticle.has_bars      = visible;
              g_target_reticle.bar_alignment = bar_alignment;
              if (subtarget_pos.is_none()) {
                  g_target_reticle.has_subtarget = false;
              } else {
                  auto s = subtarget_pos.cast<std::array<float, 3>>();
                  g_target_reticle.has_subtarget = true;
                  g_target_reticle.subtarget_pos = {s[0], s[1], s[2]};
              }
          },
          py::arg("visible"), py::arg("ship_center"), py::arg("ship_radius"),
          py::arg("subtarget_pos"), py::arg("bar_alignment"),
          "Set the target reticle: full-ship corner box, optional subtarget "
          "crosshair, and fore/aft side bars whose arrows sit at bar_alignment "
          "([-1,+1], +1 fore). Applied each frame().");
    m.def("clear_target_reticle",
          []() { g_target_reticle = renderer::TargetReticle{}; },
          "Hide the target reticle. Takes effect next frame().");

    // ── Helm -> Set Course star map ──────────────────────────────────────
    m.def("starmap_set_enabled",
          [](bool enabled) { g_starmap_scene.enabled = enabled; },
          py::arg("enabled"),
          "Show/hide the star map. Off by default; the pass is skipped "
          "entirely when off, so production frames are byte-identical.");
    m.def("starmap_set_viewport",
          [](int x, int y, int w, int h) {
              g_starmap_scene.viewport = {x, y, w, h};
          },
          py::arg("x"), py::arg("y"), py::arg("w"), py::arg("h"),
          "Set the map's sub-rect in FRAMEBUFFER pixels, GL convention "
          "(origin bottom-left). A zero-area rect makes the pass a no-op.");
    m.def("starmap_set_camera",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_starmap_camera.eye    = {std::get<0>(eye), std::get<1>(eye), std::get<2>(eye)};
              g_starmap_camera.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_starmap_camera.up     = {std::get<0>(up), std::get<1>(up), std::get<2>(up)};
              g_starmap_camera.fov_y_rad = fov_y_rad;
              g_starmap_camera.near = near;
              g_starmap_camera.far  = far;
              // No aspect argument on purpose: the pass derives it from the
              // map's own sub-rect, which is the same rect
              // engine/ui/star_map.project_points uses for picking, so the
              // drawn stars and the clickable stars agree by construction.
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"),
          "Set the star map's own orbit camera. Independent of set_camera() — "
          "the gameplay camera keeps rendering the live scene around the modal.");
    m.def("starmap_set_scene",
          [](const std::vector<std::tuple<std::array<float,3>, std::array<float,3>,
                                          float, float, float>>& discs,
             const std::vector<std::tuple<std::array<float,3>, std::array<float,3>,
                                          std::array<float,3>>>& lines,
             const std::vector<std::tuple<std::array<float,3>, std::array<float,3>,
                                          float, bool,
                                          std::array<float,3>>>& points,
             const std::vector<std::tuple<std::array<float,3>, int,
                                          std::array<float,3>, float>>& brackets,
             const std::vector<std::tuple<std::array<float,3>, std::array<float,3>,
                                          float, float>>& starclouds) {
              g_starmap_scene.discs.clear();
              g_starmap_scene.discs.reserve(discs.size());
              for (const auto& t : discs) {
                  renderer::StarMapDisc d;
                  const auto& p = std::get<0>(t);
                  const auto& c = std::get<1>(t);
                  d.position = {p[0], p[1], p[2]};
                  d.color    = {c[0], c[1], c[2]};
                  d.radius   = std::get<2>(t);
                  d.opacity  = std::get<3>(t);
                  d.border_opacity = std::get<4>(t);
                  g_starmap_scene.discs.push_back(d);
              }
              g_starmap_scene.lines.clear();
              g_starmap_scene.lines.reserve(lines.size());
              for (const auto& t : lines) {
                  renderer::StarMapLine l;
                  const auto& a = std::get<0>(t);
                  const auto& b = std::get<1>(t);
                  const auto& c = std::get<2>(t);
                  l.a     = {a[0], a[1], a[2]};
                  l.b     = {b[0], b[1], b[2]};
                  l.color = {c[0], c[1], c[2]};
                  g_starmap_scene.lines.push_back(l);
              }
              g_starmap_scene.points.clear();
              g_starmap_scene.points.reserve(points.size());
              for (const auto& t : points) {
                  renderer::StarMapPoint pt;
                  const auto& p = std::get<0>(t);
                  const auto& c = std::get<1>(t);
                  pt.position = {p[0], p[1], p[2]};
                  pt.color    = {c[0], c[1], c[2]};
                  pt.size_px  = std::get<2>(t);
                  pt.selected = std::get<3>(t);
                  const auto& cc = std::get<4>(t);
                  pt.core_color = {cc[0], cc[1], cc[2]};
                  g_starmap_scene.points.push_back(pt);
              }
              g_starmap_scene.brackets.clear();
              g_starmap_scene.brackets.reserve(brackets.size());
              for (const auto& t : brackets) {
                  renderer::StarMapBracket br;
                  const auto& p = std::get<0>(t);
                  const auto& c = std::get<2>(t);
                  br.position = {p[0], p[1], p[2]};
                  br.mark     = std::get<1>(t);
                  br.color    = {c[0], c[1], c[2]};
                  br.size_px  = std::get<3>(t);
                  g_starmap_scene.brackets.push_back(br);
              }
              g_starmap_scene.starclouds.clear();
              g_starmap_scene.starclouds.reserve(starclouds.size());
              for (const auto& t : starclouds) {
                  renderer::StarMapStarCloud g;
                  const auto& p = std::get<0>(t);
                  const auto& c = std::get<1>(t);
                  g.position = {p[0], p[1], p[2]};
                  g.color    = {c[0], c[1], c[2]};
                  g.size_px  = std::get<2>(t);
                  g.opacity  = std::get<3>(t);
                  g_starmap_scene.starclouds.push_back(g);
              }
          },
          py::arg("discs"), py::arg("lines"), py::arg("points"), py::arg("brackets"),
          py::arg("starclouds"),
          "Replace the star map scene. Tuple shapes:\n"
          "  discs:      ((x,y,z), (r,g,b), radius_world, fill_alpha, border_alpha)\n"
          "  lines:      ((ax,ay,az), (bx,by,bz), (r,g,b))\n"
          "  points:     ((x,y,z), (r,g,b), size_px, selected)\n"
          "  brackets:   ((x,y,z), mark, (r,g,b), size_px)\n"
          "  starclouds: ((x,y,z), (r,g,b), size_px, opacity)\n"
          "Discs are nebula REGIONS -- a faint flat fill inside a crisp "
          "boundary, not soft clouds -- and are world-scaled. Star clouds are "
          "screen-scaled glyphs: drawn at their model `size` they became "
          "volumes that swallowed whole regions of the map.\n"
          "The five lists are drawn in THAT order with depth test off. Python "
          "owns every ordering decision (engine/ui/star_map.build_scene); the "
          "pass never sorts or reorders, which is what keeps star markers from "
          "being occluded by nebula scenery.\n"
          "`mark` (1 here, 2 course, 3 mission) and `selected` are carried for "
          "semantics only -- the pass derives NO colour or size from either. "
          "star_map.py owns those enums and the palette, so every colour and "
          "pixel size arrives as a value.");

    m.def("breach_set_shell_debug",
          [](bool on) { renderer::BreachPass::set_shell_debug(on); },
          py::arg("on"),
          "Developer diagnostic: paint the hull-breach INTERIOR SHELL flat "
          "magenta, leaving the raymarched scoop untouched. Exists because an "
          "unlit interior and a hole straight through the hull both render as "
          "black against a starfield, so 'is the shell drawing here?' cannot "
          "be answered by eye. Off by default; only bound under --developer.");

    m.def("breach_shell_debug",
          []() { return renderer::BreachPass::shell_debug(); },
          "Current state of the interior-shell debug view.");

    m.def("dust_set_enabled",
          [](bool enabled) {
              if (g_dust_pass) g_dust_pass->set_enabled(enabled);
          },
          py::arg("enabled"),
          "Toggle the space-dust pass at runtime. Default: on.");

    m.def("letterbox_set",
          [](float covered) { renderer::letterbox::set_covered(covered); },
          py::arg("covered"),
          "Set the cutscene letterbox TOTAL covered fraction (BC's "
          "fCoveredArea; 0.125 => 6.25% per bar). Clamped to [0, 1]. The bars "
          "draw over the 3D scene and under the whole CEF overlay.");

    m.def("rim_set_enabled",
          [](bool enabled) { dauntless_rim::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass Fresnel rim term. Default: on.");
    m.def("normal_map_set_enabled",
          [](bool enabled) { dauntless_normal_map::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle tangent-space normal mapping on ship hulls. Default: on "
          "(inert on stock assets, which ship no _normal maps).");
    m.def("normal_map_set_strength",
          [](float strength) { dauntless_normal_map::set_strength(strength); },
          py::arg("strength"),
          "Scale the normal map's tangent-space xy. 0 = flat (identical to "
          "disabled), 1 = as authored. Default: 1.0.");
    m.def("normal_map_set_flip_green",
          [](bool flip) { dauntless_normal_map::set_flip_green(flip); },
          py::arg("flip"),
          "Flip the normal map's green channel. Default: ON -- texture row 0 "
          "(v == 0) is always the image's TOP row (stb_image normalises the "
          "TGA origin bit), so v runs downward in image space, and flipping "
          "green internally is what makes a standard OpenGL-convention "
          "(+Y up) authored map render correctly. Turn this off only for a "
          "map authored to the DirectX convention (-Y).");
    m.def("procedural_sky_set_enabled",
          [](bool enabled) { dauntless_procedural_sky::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the procedural sky (Modern VFX). Default: on; off = stock BC.");
    m.def("procedural_sky_enabled",
          []() { return dauntless_procedural_sky::enabled(); },
          "Read the procedural-sky toggle (Modern VFX). Default: on.");
    m.def("filmic_set_enabled",
          [](bool enabled) { dauntless_filmic::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the Filmic Filter (Modern VFX): grain + vignette + chromatic "
          "aberration on the exterior view. Default: on.");
    m.def("filmic_enabled",
          []() { return dauntless_filmic::enabled(); },
          "Read the Filmic Filter toggle (Modern VFX). Default: on.");
    m.def("motion_blur_set_enabled",
          [](bool enabled) { dauntless_motion_blur::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle camera Motion Blur (Modern VFX) on the exterior view. "
          "Default: on.");
    m.def("motion_blur_enabled",
          []() { return dauntless_motion_blur::enabled(); },
          "Read the Motion Blur toggle (Modern VFX). Default: on.");
    m.def("dof_set_enabled",
          [](bool enabled) { dauntless_dof::set_enabled(enabled); },
          "Toggle depth of field (the Camera Realism master). Default: on. "
          "Off means the pass never runs, whatever params say.");
    m.def("dof_enabled",
          []() { return dauntless_dof::enabled(); },
          "Whether depth of field is enabled.");
    m.def("dof_set_params",
          [](float focus_gu, float blend, float near_strength,
             float far_strength, float far_ceiling, float max_radius_frac,
             float near_sharp_gu, float near_full_gu) {
              renderer::DofParams p;
              p.focus_gu        = focus_gu;
              p.blend           = blend;
              p.near_strength   = near_strength;
              p.far_strength    = far_strength;
              p.far_ceiling     = far_ceiling;
              p.max_radius_frac = max_radius_frac;
              p.near_sharp_gu   = near_sharp_gu;
              p.near_full_gu    = near_full_gu;
              dauntless_dof::set_params(p);
          },
          // Named args, unlike the neighbours above: six consecutive floats
          // in a fixed order is exactly the signature a future edit can
          // transpose silently. With py::arg the contract is documented at
          // the binding and a mis-ordered keyword call fails loudly instead.
          py::arg("focus_gu"), py::arg("blend"), py::arg("near_strength"),
          py::arg("far_strength"), py::arg("far_ceiling"),
          py::arg("max_radius_frac"),
          py::arg("near_sharp_gu"), py::arg("near_full_gu"),
          "Push the whole DOF parameter set for this frame. blend <= 0 means "
          "no subject is focused and the pass is skipped entirely. Every "
          "value is authored in engine/cameras/dof.py -- there is no C++ "
          "default that means anything.");
    m.def("volumetric_nebulae_set_enabled",
          [](bool enabled) { dauntless_volumetric_nebulae::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle Volumetric Nebulae (Modern VFX). Default: on.");
    m.def("volumetric_nebulae_enabled",
          []() { return dauntless_volumetric_nebulae::enabled(); },
          "Read the Volumetric Nebulae toggle (Modern VFX). Default: on.");
    m.def("nebula_lightning_set_enabled",
          [](bool enabled) { dauntless_nebula_lightning::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle Nebula Lightning (Modern VFX). Default: on.");
    m.def("nebula_lightning_enabled",
          []() { return dauntless_nebula_lightning::enabled(); },
          "Read the Nebula Lightning toggle (Modern VFX). Default: on.");
    m.def("set_warp_streak_intensity",
          [](float i) { dauntless_warp_vfx::set_streak(i); },
          py::arg("intensity"),
          "Set the 0..1 star-streak intensity for the warp flythrough.");
    m.def("set_warp_flash_intensity",
          [](float i) { dauntless_warp_vfx::set_flash(i); },
          py::arg("intensity"),
          "Set the 0..1 warp-flash intensity for the warp flythrough.");
    m.def("set_warp_travel_dir",
          [](float x, float y, float z) { dauntless_warp_vfx::set_travel(glm::vec3(x, y, z)); },
          py::arg("x"), py::arg("y"), py::arg("z"),
          "Set the world-space travel direction for the warp flythrough.");
    m.def("set_dash_intensity",
          [](float i) { dauntless_dash_vfx::set_intensity(i); },
          py::arg("intensity"),
          "Set the 0..1 intensity for the player's in-system-warp dash "
          "(raises the dust pass's smear cap; separate from the warp "
          "flythrough's streak channel).");
    m.def("hdr_set_enabled",
          [](bool e) { dauntless_hdr::set_enabled(e); },
          py::arg("enabled"),
          "Toggle the HDR resolve (tonemap+bloom+grade). Default: on.");
    m.def("nonfinite_probe_set_enabled",
          [](bool enabled, const std::string& dump_dir, int max_dumps) {
              g_nfprobe_enabled   = enabled;
              g_nfprobe_dump_dir  = dump_dir;
              g_nfprobe_max_dumps = max_dumps;
              // The per-term cause probe in opaque.frag is only meaningful
              // while this is running, and it costs a pile of finiteness tests
              // per hull fragment, so it rides the same switch.
              dauntless_nan_debug::set_enabled(enabled);
              if (enabled) {
                  g_nfprobe_frames = 0;
                  g_nfprobe_hits   = 0;
                  g_nfprobe_dumps  = 0;
                  g_nfprobe_last_cells.clear();
              }
              g_nfprobe_dump_pending = false;
          },
          py::arg("enabled"), py::arg("dump_dir") = std::string(),
          py::arg("max_dumps") = 8,
          "Developer NaN/Inf detector on the HDR target, checked every frame "
          "BEFORE bloom. Off by default: it inspects every texel and does a "
          "synchronous readback. `dump_dir` must be ABSOLUTE (GLFW changes the "
          "process cwd on macOS); empty disables PNG dumps. Enabling resets the "
          "counters.");
    m.def("nonfinite_probe_enabled",
          []() { return g_nfprobe_enabled; },
          "True when the non-finite probe is running.");
    m.def("nonfinite_probe_stats",
          []() {
              py::dict d;
              d["enabled"]        = g_nfprobe_enabled;
              d["frames_probed"]  = g_nfprobe_frames;
              d["frames_flagged"] = g_nfprobe_hits;
              d["dumps_written"]  = g_nfprobe_dumps;
              d["grid_w"]         = renderer::NonfiniteProbe::kGridW;
              d["grid_h"]         = renderer::NonfiniteProbe::kGridH;
              py::list cells;
              for (const auto& c : g_nfprobe_last_cells)
                  cells.append(py::make_tuple(c.first, c.second));
              d["last_cells"] = cells;   // bottom-left origin
              return d;
          },
          "Counters plus the grid cells flagged on the most recent hit "
          "(bottom-left origin, grid_w x grid_h).");
    m.def("hdr_lens_flare_set_enabled",
          [](bool enabled) { dauntless_hdr_lens_flare::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the image-based Modern Lens Flares (Modern VFX). Default: on; "
          "off restores the classic per-sun billboard flares (stock BC).");
    m.def("hdr_lens_flare_enabled",
          []() { return dauntless_hdr_lens_flare::enabled(); },
          "Read the Modern Lens Flares toggle (Modern VFX). Default: on.");
    m.def("shadows_set_enabled",
          [](bool enabled) { dauntless_shadows::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle sun shadow maps. Default: on.");

    // ── Frame profiler ────────────────────────────────────────────────────
    // Per-pass CPU + GPU timings for the render half of the frame. Off by
    // default; enabling allocates GL timer queries lazily on the next frame.
    m.def("profiler_set_enabled",
          [](bool enabled) { renderer::frame_timer().set_enabled(enabled); },
          py::arg("enabled"),
          "Enable/disable per-pass frame timing. Off by default. Toggling "
          "either way clears the accumulated averages.");
    m.def("profiler_enabled",
          []() { return renderer::frame_timer().enabled(); },
          "True when per-pass frame timing is recording.");
    m.def("profiler_reset",
          []() { renderer::frame_timer().reset(); },
          "Drop all accumulated averages and the scope table.");
    m.def("set_swap_interval",
          [](int interval) {
              if (!g_window) {
                  throw std::runtime_error(
                      "set_swap_interval: init must be called first");
              }
              g_window->set_swap_interval(interval);
          },
          py::arg("interval"),
          "Buffer-swap interval: 1 = vsync, 0 = uncapped. A visible window "
          "defaults to 1 and a hidden one to 0. Turn it off for a profiling "
          "capture -- a vsync-capped frame measures the monitor.");
    m.def("swap_interval",
          []() { return g_window ? g_window->swap_interval() : -1; },
          "The interval currently set, or -1 when there is no window. The "
          "profiler reports this rather than assuming vsync.");
    m.def("profiler_scopes",
          []() {
              // One list of dicts per resolved frame, in pass order. Values are
              // EMA-smoothed milliseconds; `calls` is the raw count from the
              // last resolved frame, so a pass that ran twice (exterior +
              // viewscreen RTT) is visible as such rather than averaged away.
              py::list out;
              for (const auto& r : renderer::frame_timer().results()) {
                  py::dict d;
                  d["name"]   = r.name;
                  d["cpu_ms"] = r.cpu_ms;
                  d["gpu_ms"] = r.gpu_ms;
                  d["calls"]  = r.calls;
                  d["depth"]  = r.depth;
                  out.append(std::move(d));
              }
              return out;
          },
          "Per-pass render timings from the last resolved frame.");
    m.def("profiler_frame",
          []() {
              py::dict d;
              const auto& t = renderer::frame_timer();
              d["cpu_ms"] = t.frame_cpu_ms();
              // Whole-frame GPU is first-timestamp-to-last, not the sum of the
              // scopes: scopes nest, so a sum would double-count.
              d["gpu_ms"] = t.frame_gpu_ms();
              d["frames"] = t.frames_resolved();
              d["enabled"] = t.enabled();
              // Reported, not assumed: a hidden window already runs uncapped,
              // so a report that hard-coded "present is the vsync wait" was
              // telling every headless capture the opposite of the truth.
              d["swap_interval"] = g_window ? g_window->swap_interval() : -1;
              return d;
          },
          "Whole-frame CPU/GPU totals and the number of frames resolved.");
    m.def("smaa_set_enabled",
          [](bool enabled) { g_smaa_enabled = enabled; },
          py::arg("enabled"),
          "Enable/disable the post-process SMAA 1x pass (default on).");

    m.def("ambient_gradient_set",
          [](float v) {
              dauntless_ambient_gradient::set_strength(v);
              // Re-resolve immediately so the knob bites on the NEXT frame
              // rather than waiting for Python's next set_lighting push --
              // which, on a static scene, may not come at all.
              resolve_ambient_gradient();
          },
          py::arg("strength"),
          "Directional-ambient strength, clamped to [0, 1]. 0 is the stock "
          "flat ambient (byte-identical).");

    m.def("ambient_gradient_get",
          []() { return dauntless_ambient_gradient::strength(); },
          "Current directional-ambient strength.");

    m.def("ambient_gradient_set_enabled",
          [](bool on) {
              dauntless_ambient_gradient::set_enabled(on);
              resolve_ambient_gradient();
          },
          py::arg("enabled"),
          "Directional ambient on/off for the Cinematic Lighting master. On "
          "restores the engine's tuned strength; off is 0 (the stock path).");

    m.def("msaa_set_samples",
          [](int samples) { g_msaa_samples = samples; },
          py::arg("samples"),
          "Set MSAA sample count for the opaque space pass. 0 disables it "
          "(the stock path: no multisample buffer, no resolve blit). "
          "2/4/8 are clamped against GL_MAX_SAMPLES when applied.");

    m.def("msaa_max_samples",
          []() {
              // MUST be guarded on g_window. query_gl_caps calls glGetIntegerv,
              // and with no context glad's function pointer is null -- calling
              // this before init() SEGFAULTS the interpreter rather than
              // raising. Returning 0 makes the UI offer no MSAA segments,
              // which is the correct answer for "no context".
              if (!g_window) return 0;
              return renderer::query_gl_caps().max_samples;
          },
          "GL_MAX_SAMPLES for this context -- the ceiling the UI offers. "
          "Returns 0 before init(), when there is no context to ask.");

    m.def("dust_set_density",
          [](int count) {
              if (g_dust_pass) g_dust_pass->set_density(count);
          },
          py::arg("count"),
          "Reseed the dust particle buffer with `count` particles "
          "(clamped to [0, 50000]).");

    m.def("model_aabb",
          [](scenegraph::ModelHandle h)
              -> std::tuple<std::tuple<float, float, float>,
                            std::tuple<float, float, float>> {
              if (h == 0 || h > g_loaded_models.size()) {
                  return {{0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f}};
              }
              const assets::Model* model = g_loaded_models[h - 1].handle.get();
              if (!model) return {{0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f}};

              const renderer::Aabb box = renderer::compute_model_aabb(*model);
              return {{box.center.x, box.center.y, box.center.z},
                      {box.half_extents.x, box.half_extents.y, box.half_extents.z}};
          },
          py::arg("model"),
          "Returns ((center_x,y,z), (half_extents_x,y,z)) computed from the "
          "union of every CPU-side mesh vertex position in the model. (0,0,0) "
          "tuples on invalid handle or model with no retained CPU data.");

    // Model::source -- the hull-volume cache key ("<path>" or
    // "<path>#s=<scale %.6g>"). Empty for an invalid handle.
    m.def("model_source",
          [](scenegraph::ModelHandle h) -> std::string {
              if (h == 0 || h > g_loaded_models.size()) return {};
              const assets::Model* model = g_loaded_models[h - 1].handle.get();
              return model ? model->source.string() : std::string{};
          },
          py::arg("model"),
          "The loaded model's Model::source string (the .dhv/.dvox cache "
          "key): the bare path, or '<path>#s=<scale>' for a scaled glTF. "
          "Empty string for an invalid handle.");

    // The one formatter for a scaled source string (float32, %.6g). Python
    // must never format the scale itself -- the boot pre-bake's target has
    // to be byte-identical to the Model::source the runtime keys on.
    m.def("hull_source_string",
          [](const std::string& path, float scale) -> std::string {
              return assets::hull_source_string(path, scale);
          },
          py::arg("path"), py::arg("scale"),
          "assets::hull_source_string: '<path>' when scale == 1.0, else "
          "'<path>#s=<scale as float32 %.6g>'. Pure; no GL context needed.");

    m.def("model_bounds",
          [](scenegraph::ModelHandle h)
              -> std::vector<std::tuple<float, float, float, float>> {
              std::vector<std::tuple<float, float, float, float>> out;
              if (h == 0 || h > g_loaded_models.size()) return out;
              const assets::Model* model = g_loaded_models[h - 1].handle.get();
              if (!model) return out;

              for (const auto& s : renderer::compute_model_bounds(*model)) {
                  out.emplace_back(s.center.x, s.center.y, s.center.z, s.radius);
              }
              return out;
          },
          py::arg("model"),
          "Returns [(cx, cy, cz, radius), ...] — the model's authored per-shape "
          "bounding spheres, composed through the node hierarchy into model "
          "space. This is the set of pieces the hull is made of; a single "
          "model-wide bound cannot express a CONCAVE hull, which is why a ship "
          "sitting in a starbase's docking bay reads as inside the station. "
          "Empty list on an invalid handle, a model with no retained CPU data, "
          "or one whose shapes carry no authored radius.");

    m.def("shield_register",
          [](scenegraph::InstanceId id,
             int mode,
             float decay_seconds,
             std::tuple<float, float, float, float> default_color,
             std::tuple<float, float, float> aabb_center,
             std::tuple<float, float, float> aabb_half_extents) {
              if (!g_shield_pass) return;
              const glm::vec4 dc(std::get<0>(default_color),
                                  std::get<1>(default_color),
                                  std::get<2>(default_color),
                                  std::get<3>(default_color));
              const glm::vec3 ac(std::get<0>(aabb_center),
                                  std::get<1>(aabb_center),
                                  std::get<2>(aabb_center));
              const glm::vec3 ah(std::get<0>(aabb_half_extents),
                                  std::get<1>(aabb_half_extents),
                                  std::get<2>(aabb_half_extents));
              g_shield_pass->register_ship(
                  id, static_cast<renderer::ShieldMode>(mode),
                  decay_seconds, dc, ac, ah);
          },
          py::arg("instance_id"), py::arg("mode"),
          py::arg("decay_seconds"), py::arg("default_color"),
          py::arg("aabb_center"), py::arg("aabb_half_extents"),
          "Register a ship's shield state with the renderer. mode=0 ellipsoid, "
          "mode=1 skin. default_color is the ShieldGlowColor RGBA the renderer "
          "substitutes when shield_hit is called with rgba=(0,0,0,0).");

    m.def("shield_unregister",
          [](scenegraph::InstanceId id) {
              if (g_shield_pass) g_shield_pass->unregister_ship(id);
          },
          py::arg("instance_id"),
          "Remove a ship's shield state. No-op if unregistered.");

    m.def("shield_hit",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> point,
             std::tuple<float, float, float, float> rgba,
             float intensity,
             float radius) {
              if (!g_shield_pass) return;
              const glm::vec3 p(std::get<0>(point),
                                 std::get<1>(point),
                                 std::get<2>(point));
              const glm::vec4 c(std::get<0>(rgba),
                                 std::get<1>(rgba),
                                 std::get<2>(rgba),
                                 std::get<3>(rgba));
              // Callers pass an INSTANCE-RELATIVE point (the world hit minus
              // instance_translation, formed in double), but the state stores
              // BODY so the splash rides the hull instead of being left behind
              // as the ship flies on. Convert here, once, inverting only
              // rotation*scale — never a large translation (the floating render
              // origin). An unknown instance drops the hit — the pass would
              // drop it anyway.
              const auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              const glm::vec3 body = scenegraph::relative_to_body(inst->world_linear, p);
              g_shield_pass->shield_hit(id, body, c, intensity, glfwGetTime(),
                                        radius);
          },
          py::arg("instance_id"), py::arg("point"),
          py::arg("rgba") = std::make_tuple(0.0f, 0.0f, 0.0f, 0.0f),
          py::arg("intensity") = 1.0f,
          py::arg("radius") = 0.0f,
          "Push a shield-hit flash for the given ship at an INSTANCE-RELATIVE "
          "point (world point minus instance_translation). "
          "rgba=(0,0,0,0) substitutes the ship's default ShieldGlowColor. "
          "radius is the weapon's DamageRadiusFactor in GU, which sizes the "
          "procedural ripple; 0 clamps up to the renderer's reach floor.");

    m.def("ray_trace_mesh",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> origin,
             std::tuple<float, float, float> direction,
             float max_dist) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) {
                  throw std::runtime_error("ray_trace_mesh: invalid InstanceId");
              }
              const auto h = inst->model_handle;
              if (h == 0 || h > g_loaded_models.size()) {
                  throw std::runtime_error("ray_trace_mesh: instance has no model");
              }
              const assets::Model* model = g_loaded_models[h - 1].handle.get();
              if (model == nullptr) return py::none();

              const glm::vec3 o(std::get<0>(origin),
                                std::get<1>(origin),
                                std::get<2>(origin));
              glm::vec3 d(std::get<0>(direction),
                          std::get<1>(direction),
                          std::get<2>(direction));
              const float dlen = glm::length(d);
              if (dlen < 1e-9f) return py::none();
              d /= dlen;
              if (!std::isfinite(max_dist) || max_dist <= 0.0f) return py::none();

              // Trace against the pose the instance is DRAWN at, not its
              // rest pose. Without &inst->node_overrides a raised Bird of Prey
              // wing is visible but unhittable, and -- because
              // combat._resolve_impact_point runs this trace and
              // part_severance attributes damage from the point it returns --
              // a wing shot while raised would accumulate nothing and never
              // come off.
              // Instance-relative ray, rotation*scale inverted only: a ship
              // 1e6 GU out traces with the precision of one at the origin.
              auto hit = renderer::ray_trace_instance_linear(
                  *model, inst->world_linear, o, d, max_dist,
                  &inst->node_overrides);
              if (!hit) return py::none();
              return py::make_tuple(
                  py::make_tuple(hit->point.x, hit->point.y, hit->point.z),
                  py::make_tuple(hit->normal.x, hit->normal.y, hit->normal.z),
                  hit->t);
          },
          py::arg("instance_id"),
          py::arg("origin"),
          py::arg("direction"),
          py::arg("max_dist"),
          "Ray-cast a ray against an instance's loaded mesh, at "
          "the pose it is DRAWN at -- the instance's node overrides "
          "(articulation / severance) are applied, so a moved part is hit "
          "where it appears and a severed one cannot be hit at all. origin "
          "is INSTANCE-RELATIVE (world origin minus instance_translation); "
          "direction is a world direction, auto-normalised. Returns "
          "((point), (normal), t) on hit or None on miss; point is "
          "instance-relative too (add instance_translation back). t is the "
          "world-space distance from origin.");

    m.def("damage_decal_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float radius, float intensity,
             std::uint32_t weapon_class, float time,
             std::tuple<float, float, float> world_tangent, float dent) {
              if (weapon_class > 2u) return;  // unknown weapon class — drop silently
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              // pw is INSTANCE-RELATIVE (floating render origin).
              const glm::vec3 pb = scenegraph::relative_to_body(inst->world_linear, pw);
              const glm::vec3 nb = scenegraph::dir_to_body(inst->world_linear, nw);
              const glm::vec3 tw(std::get<0>(world_tangent),
                                 std::get<1>(world_tangent),
                                 std::get<2>(world_tangent));
              // Zero stays zero (dir_to_body returns a length-0 input
              // unchanged); the ring then derives a perpendicular.
              const glm::vec3 tb = scenegraph::dir_to_body(inst->world_linear, tw);
              // Convert radius game-units -> NIF/model units here (the same
              // space as pb), so the ring's merge test and the shader both work
              // in model units. s = |world's X column| = the uniform NIF->world
              // scale baked into inst->world.
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float radius_model = (s > 0.0f) ? radius / s : radius;
              inst->decals.add(pb, nb, radius_model, intensity,
                               static_cast<scenegraph::WeaponClass>(weapon_class),
                               time, tb, dent);
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("radius"), py::arg("intensity"),
          py::arg("weapon_class"), py::arg("time"),
          py::arg("world_tangent") = std::make_tuple(0.0f, 0.0f, 0.0f),
          py::arg("dent") = 0.0f,
          "Record an object-space damage decal on a ship instance. The point is "
          "INSTANCE-RELATIVE (world point minus instance_translation); it and "
          "the world normal are transformed into the ship body frame. weapon_class: "
          "0=HeatGlow (phaser), 1=Scorch (torpedo/disruptor), 2=Scuff (collision; "
          "world_tangent = slip direction, zero = no preferred direction; "
          "dent 1 = impact crumple, 0 = grind scratches).");

    m.def("hull_carve_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float influ_radius, float strength, float /*time*/,
             float floor_radius, float radius_modifier) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              // pw is INSTANCE-RELATIVE (floating render origin): only
              // rotation*scale is inverted.
              const glm::vec3 pb = scenegraph::relative_to_body(inst->world_linear, pw);
              // Transform the world-space surface normal to body frame.
              // dir_to_body strips scale; result is a unit body-frame outward
              // normal. Fall back to the radial direction from origin if the
              // transformed result is degenerate.
              glm::vec3 nb = scenegraph::dir_to_body(inst->world_linear, nw);
              if (glm::length(nb) < 1e-4f) {
                  nb = (glm::length(pb) > 1e-4f)
                       ? glm::normalize(pb)
                       : glm::vec3(0.f, 0.f, 1.f);
              }
              // NOTE: pb stays POSED. The per-instance carve field is
              // SAMPLED in posed body space -- opaque.vert builds
              // v_position_ws from world_per_node[i] (overrides included)
              // while opaque.frag's u_ship_world_inv is the INSTANCE inverse
              // with no override -- so a hit on a moved part already lands
              // where the shader will look for it. Pulling it back into rest
              // space was tried (eb6fedc8) and reverted: it wrote where
              // nothing samples. See the spec's 4.3.
              // s = |world's X column| = the uniform NIF->world scale baked into
              // inst->world (same derivation as damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              const float influ_model = influ_radius * inv_s;
              const float floor_model = floor_radius * inv_s;

              // Resolve this instance's hull source + authored damage
              // resolution the same way hull_volume_set_resolution /
              // compute_capsule_region do -- model->source is the key
              // breach_pass.cc and CarveFieldCache::get_for_source already
              // use, so InstanceFieldCache::carve looks up the SAME baked
              // field those consume. An unresolvable model (no source) just
              // means the field side stays a no-op; the sphere ring below is
              // unaffected.
              const assets::Model* model = resolve_model(inst->model_handle);
              const std::filesystem::path source =
                  (model != nullptr) ? model->source : std::filesystem::path{};
              const float authored_res =
                  source.empty() ? 0.0f : renderer::hull_volume_resolution(source);

              // A resolved hull source with NO resolution ever pushed for it
              // (engine/appc/hull_volume.py's push_resolution never ran, or
              // ran for a different path) degrades silently and correctly:
              // authored_res 0 -> HullVolumeCache::get derives cell 0 and
              // bakes nothing -> InstanceFieldCache::carve sees an empty
              // baked field and creates no entry. The sphere ring is
              // unaffected either way. That silence is exactly the kind of
              // inert-feature bug this project has shipped repeatedly (see
              // CLAUDE.md's stub-hardening ratchet), so make it audible once
              // per hull source rather than leaving it invisible.
              if (!source.empty() && authored_res == 0.0f &&
                  dauntless::is_developer_mode()) {
                  static std::unordered_set<std::string> warned_sources;
                  if (warned_sources.insert(source.string()).second) {
                      std::fprintf(stderr,
                                   "[hull_carve_add] no authored damage "
                                   "resolution was ever pushed for hull "
                                   "source \"%s\" -- its per-instance "
                                   "distance field will stay absent for "
                                   "every carve (sphere ring is unaffected).\n",
                                   source.string().c_str());
                  }
              }

              // Backing-material gate input: the same ORIGINAL fill volume
              // frame.cc's sphere path already gates u_carve_spheres with
              // (renderer::carve_has_backing / CarveFieldCache::
              // volume_for_source). Null when there is no fill to gate with
              // (no cache, no source, or a hull with no decoded mask) --
              // hull_carve_deposit then carves the field ungated, matching
              // frame.cc's carve_fill_entry falling back to nullptr in the
              // same situation.
              const voxel::VoxelVolume* fill_for_gate = nullptr;
              if (!source.empty() && g_carve_cache) {
                  const voxel::VoxelVolume& v =
                      g_carve_cache->volume_for_source(source);
                  if (!v.occ.empty()) fill_for_gate = &v;
              }

              // Deposit onto BOTH representations of this instance's damage
              // (hull-volume-field-transport Task 6): the fixed 24-slot
              // sphere ring (still what the breach scoop / framework lattice
              // / breach-event ring below read) AND, alongside it, the
              // per-instance distance field -- same body-frame centre,
              // normal, and derived visible radius for both. See
              // renderer::hull_carve_deposit's doc comment for why this
              // arithmetic lives there rather than inline here.
              const renderer::HullCarveDepositResult result =
                  renderer::hull_carve_deposit(
                      inst->carve, g_instance_field_cache.get(), id, source,
                      authored_res, pb, nb, influ_model, strength,
                      floor_model, radius_modifier, inv_s, fill_for_gate);

              // Breach event (transient VFX: debris, venting, rim) only when the
              // carve newly appears or visibly grows — sub-iso accumulation is
              // silent, so phaser dribble doesn't spray debris before it breaches.
              if (result.radius > result.prev_radius + 1e-4f &&
                  result.radius > 0.0f) {
                  // Seed: deterministic hash of center_body XOR a per-push
                  // counter, to decorrelate closely-spaced breaches on one ship.
                  static std::uint64_t s_counter = 0;
                  const auto bx = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.x * 1000.f));
                  const auto by = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.y * 1000.f));
                  const auto bz = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.z * 1000.f));
                  const std::uint64_t seed =
                      (bx * 2654435761ull) ^ (by * 805459861ull) ^
                      (bz * 3674653429ull) ^ (++s_counter * 6364136223846793005ull);
                  inst->breach_events.push(pb, result.radius, nb,
                                           g_decal_game_time, seed);
              }
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("influ_radius"), py::arg("strength"), py::arg("time"),
          py::arg("floor_radius") = 0.0f, py::arg("radius_modifier") = 1.0f,
          "Deposit hull-damage strength onto a ship instance (BC additive "
          "metaball field). World-space point + normal are transformed to body "
          "frame (model units). influ_radius is the merge proximity; strength "
          "accumulates; the visible carve radius = max(floor_radius, "
          "strength->absolute-GU curve * radius_modifier), never shrinking. "
          "radius_modifier is BC's per-ship DamageRadMod (default 1.0); carve "
          "sizes are absolute (a weapon makes the same hole on any hull). "
          "floor_radius guarantees a size for authored / core-breach carves "
          "(combat hits pass floor 0 and stay invisible until accumulated "
          "strength crosses the iso). time is accepted for call-shape symmetry "
          "with damage_decal_add but unused.");

    m.def("hull_split_detached",
          [](scenegraph::InstanceId id, int min_cells) {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr || !g_instance_field_cache) return out;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return out;
              const std::filesystem::path& source = model->source;
              const float authored_res = renderer::hull_volume_resolution(source);
              if (authored_res <= 0.0f) return out;

              const voxel::DistanceField* damage = g_instance_field_cache->field(id);
              if (damage == nullptr) return out;   // never carved: nothing to sever
              const voxel::DistanceField& baked =
                  renderer::hull_volume_cache().get(source, authored_res,
                                                    voxel::kDefaultQuality);
              if (baked.empty()) return out;

              // Pay for the full-lattice BFS only when a carve since the
              // last check could have cut something off; the first check
              // on an instance is always the full one. See
              // renderer::severance_decision.
              const bool first = g_instance_field_cache->take_first_severance_check(id);
              const voxel::CellBox box = g_instance_field_cache->take_severance_box(id);
              if (renderer::severance_decision(first, baked, *damage, box) ==
                  renderer::SeveranceDecision::kSkip) {
                  return out;
              }

              const voxel::ConnectivityResult r = voxel::hull_connectivity(baked, *damage);
              if (r.detached.empty()) return out;

              const float s = glm::length(glm::vec3(inst->world[0]));   // model->GU
              for (const voxel::HullComponent& c : r.detached) {
                  py::dict d;
                  d["cells"] = c.cells;
                  // Repeated on every dict rather than returned once: the
                  // binding returns a flat list of components, and Python's
                  // after_carve needs the parent's remaining occupied cells
                  // (for the mass-fraction split) alongside each component
                  // without a second call.
                  d["main_body_cells"] = r.main_body_cells;
                  d["centroid"] = py::make_tuple(c.centroid_body.x * s,
                                                 c.centroid_body.y * s,
                                                 c.centroid_body.z * s);
                  d["bounds_min"] = py::make_tuple(c.bounds_min_body.x * s,
                                                   c.bounds_min_body.y * s,
                                                   c.bounds_min_body.z * s);
                  d["bounds_max"] = py::make_tuple(c.bounds_max_body.x * s,
                                                   c.bounds_max_body.y * s,
                                                   c.bounds_max_body.z * s);
                  d["radius_gu"] = 0.5f * glm::length(c.bounds_max_body - c.bounds_min_body) * s;
                  if (static_cast<int>(c.cells) >= min_cells) {
                      const scenegraph::InstanceId child =
                          g_world.create_instance(inst->model_handle);
                      auto* cinst = g_world.get(child);
                      if (cinst != nullptr) {
                          // All three pose fields: `world` alone would be
                          // rebuilt from the child's default (identity at the
                          // origin) pose by the next resolve_render_space.
                          cinst->world = inst->world;
                          cinst->world_linear = inst->world_linear;
                          cinst->world_translation_d = inst->world_translation_d;
                          // Copy render-cosmetic fields from parent to child
                          // so a severed chunk keeps the hull's look --
                          // without rim_eligible/rim_strength the Fresnel
                          // rim term vanishes on the chunk the instant it
                          // splits off.
                          cinst->visible = inst->visible;
                          cinst->pass = inst->pass;
                          cinst->comm_set_id = inst->comm_set_id;
                          cinst->rim_eligible = inst->rim_eligible;
                          cinst->rim_strength = inst->rim_strength;
                          cinst->emissive_scale = inst->emissive_scale;
                          cinst->surface_is_rock = inst->surface_is_rock;
                      }
                      if (g_instance_field_cache->split(id, child, c.cell_list)) {
                          d["instance_id"] = child;
                      } else {
                          g_world.destroy_instance(child);
                          d["instance_id"] = py::none();
                          g_instance_field_cache->remove_cells(id, c.cell_list);
                      }
                  } else {
                      g_instance_field_cache->remove_cells(id, c.cell_list);
                      d["instance_id"] = py::none();
                  }
                  out.append(std::move(d));
              }
              return out;
          },
          py::arg("instance_id"), py::arg("min_cells"),
          "Split every detached hull component out of an instance's damage "
          "field. Components with >= min_cells cells become a new renderer "
          "instance of the same model on a copied transform, with their own "
          "field; smaller ones are removed from the parent. Positions are "
          "body-frame GAME UNITS. Each dict also repeats main_body_cells, "
          "the parent's remaining occupied cell count.");

    m.def("breach_burst",
          [](scenegraph::InstanceId id, std::tuple<float, float, float> body_point_gu,
             float radius_gu) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 pb(std::get<0>(body_point_gu) * inv_s,
                                 std::get<1>(body_point_gu) * inv_s,
                                 std::get<2>(body_point_gu) * inv_s);
              const glm::vec3 nb = (glm::length(pb) > 1e-4f) ? glm::normalize(pb)
                                                              : glm::vec3(0.f, 0.f, 1.f);
              static std::uint64_t s_counter = 0;
              inst->breach_events.push(pb, radius_gu * inv_s, nb, g_decal_game_time,
                                       ++s_counter * 6364136223846793005ull);
          },
          py::arg("instance_id"), py::arg("body_point_gu"), py::arg("radius_gu"),
          "Transient breach VFX (debris, venting, rim) at a body-frame point, "
          "for a sub-floor severed component that becomes no chunk.");

    m.def("hull_carve_capsule",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> p0_world,
             std::tuple<float, float, float> p1_world,
             float radius_gu) {
              auto* inst = g_world.get(id);
              if (inst == nullptr || !g_instance_field_cache) return;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return;
              const float authored_res = renderer::hull_volume_resolution(model->source);
              const glm::vec3 a(std::get<0>(p0_world), std::get<1>(p0_world), std::get<2>(p0_world));
              const glm::vec3 b(std::get<0>(p1_world), std::get<1>(p1_world), std::get<2>(p1_world));
              // a, b are INSTANCE-RELATIVE (floating render origin).
              const glm::vec3 pa = scenegraph::relative_to_body(inst->world_linear, a);
              const glm::vec3 pb = scenegraph::relative_to_body(inst->world_linear, b);
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              g_instance_field_cache->carve_capsule(id, model->source, authored_res,
                                                    pa, pb, radius_gu * inv_s);
          },
          py::arg("instance_id"), py::arg("p0_world"), py::arg("p1_world"),
          py::arg("radius_gu"),
          "Field-only swept cut between two INSTANCE-RELATIVE points (world "
          "points minus instance_translation). Never enters the "
          "sphere list -- beyond tracked carves the field is the hole "
          "authority (plan 2c).");

    // Where HullVolumeCache reads/writes its on-disk .dhv bakes. Pushed once
    // from Python at boot, right alongside set_game_root -- see
    // engine.renderer.hull_volume_set_cache_root (no hasattr guard there
    // deliberately: host_loop.py's realize-set path documents a feature that
    // shipped completely inert because a guard turned a loud missing-binding
    // failure into a silent skip). Only the value in place at the FIRST call
    // to renderer::hull_volume_cache() matters -- see that function's doc
    // comment in carve_field_cache.h.
    m.def("hull_volume_set_cache_root",
          [](const std::string& root) {
              renderer::set_hull_volume_cache_root(root);
          },
          py::arg("root"),
          "Directory HullVolumeCache reads/writes its on-disk .dhv bakes "
          "under. Set once from Python at boot, before any hull volume is "
          "baked. Callable more than once, but only the value configured "
          "before the cache's first use takes effect.");

    // BC authors a damage-volume resolution per ship
    // (ShipProperty.SetDamageResolution, in every hardpoint file). This is
    // NOT the bake cell size -- it is a per-ship detail RATIO (Shuttle 6,
    // Akira 8, Galaxy 10, Warbird 12, stations 15). HullVolumeCache::get
    // derives the actual cell size in model units as
    // `authored_res / quality`, where quality is the global fidelity
    // multiplier (kDefaultQuality). Reading this value as a cell size
    // directly bakes every hull at half the intended fidelity.
    m.def("hull_volume_set_resolution",
          [](scenegraph::InstanceId id, float resolution) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;      // stale id — drop silently
              if (!(resolution > 0.0f)) return; // unset: keep the native default
              // An Instance holds a model_handle, not a path. resolve_model is
              // the idiom used throughout this file (e.g. compute_capsule_region,
              // just below), and model->source is the same key breach_pass.cc:328
              // hands to CarveFieldCache::get_for_source -- so the resolution is
              // keyed by exactly the string the volume will be looked up by.
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return;
              renderer::set_hull_volume_resolution(model->source, resolution);
          },
          pybind11::arg("instance_id"), pybind11::arg("resolution"));

    // Boot-time pre-bake (engine/appc/hull_volume.py's prebake_all): bake or
    // validate ONE hull's .dhv on disk, under the same root the main-thread
    // HullVolumeCache reads, and nothing else -- no memo, no resolution map,
    // no GL. Called from a Python worker thread with the GIL RELEASED for the
    // bake (up to ~8 s for a coarsened station at -O0), so the game loop and
    // every other Python thread keep running; the filesystem is the only
    // shared state, and write_dhv's temp-file + rename keeps a concurrent
    // get on the main thread correct (it sees no file, or a complete one).
    // `hull_path` must be the ABSOLUTE path the runtime will load the model
    // from (host_loop's _ship_nif_path resolution) -- the cache key is that
    // string, so any other spelling bakes an entry nothing will ever hit.
    m.def("hull_volume_bake_to_disk",
          [](const std::string& hull_path, float authored_res) -> bool {
              if (!(authored_res > 0.0f)) return false;
              const std::filesystem::path root =
                  renderer::effective_hull_volume_cache_root();
              py::gil_scoped_release release;
              return voxel::ensure_dhv(root, hull_path, authored_res,
                                       voxel::kDefaultQuality);
          },
          py::arg("hull_path"), py::arg("authored_res"),
          "Bake (or validate) the on-disk .dhv for one hull at BC's authored "
          "SetDamageResolution, releasing the GIL for the duration. Returns "
          "True when a valid file is on disk afterwards; False for a missing "
          "hull, a non-positive resolution, or a failed write. Safe to call "
          "from a worker thread: touches only the filesystem.");

    // Spec §4 puts the bake "on first use of a hull, during model load" --
    // without this call nothing pre-warmed it, so the bake instead ran
    // lazily from hull_carve_add's field_cache->carve() the first time a
    // player HIT that hull class, mid-combat: a full NIF re-parse +
    // voxelization + distance transform + up to a ~2.4 MB .dhv write, spec-
    // measured at 57ms (Galor) to 192ms (Warbird) -- 4-12 dropped frames on
    // the first hit against each new hull class. Called from
    // engine/appc/hull_volume.py's prewarm_field, right after
    // push_resolution, at both host_loop.py spawn sites -- so the cost lands
    // at mission load instead.
    //
    // Pure CPU + disk I/O (HullVolumeCache::get parses/voxelizes/bakes/reads
    // .dhv; nothing here touches GL), so it is safe to call synchronously
    // from Python at spawn time with no render context considerations --
    // the exact same call InstanceFieldCache::carve() already makes lazily.
    m.def("hull_volume_prewarm",
          [](scenegraph::InstanceId id) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return;
              const float authored_res =
                  renderer::hull_volume_resolution(model->source);
              // No authored resolution pushed for this source (yet, or
              // ever): the baker would derive cell 0 from it and bake
              // nothing (see HullVolumeCache::get) -- match that no-op
              // rather than forcing a bake at some arbitrary substitute
              // resolution.
              if (!(authored_res > 0.0f)) return;
              renderer::hull_volume_cache().get(model->source, authored_res,
                                                voxel::kDefaultQuality);
          },
          pybind11::arg("instance_id"),
          "Force this instance's hull damage field to bake now (or load its "
          "on-disk .dhv cache), instead of lazily on its first "
          "hull_carve_add deposit during combat. No-op when no authored "
          "resolution has been pushed for this hull yet.");

    m.def("compute_capsule_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center,
             std::tuple<float, float, float> axis,
             float radius) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return -1;
              // hardpoint center/radius are in game units; convert to the
              // model frame the CPU verts live in (same s as damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              glm::vec3 a(std::get<0>(axis), std::get<1>(axis),
                          std::get<2>(axis));
              const float alen = glm::length(a);
              a = (alen > 0.0f) ? a / alen : glm::vec3(0.0f, 1.0f, 0.0f);
              const renderer::GlowRegion fit =
                  renderer::compute_capsule_region(*model, c, a, radius * inv);
              // find a free slot
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n.center = fit.center;
                  n.axis = fit.axis;
                  n.radius = fit.radius;
                  n.aft = fit.aft;
                  n.fore = fit.fore;
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.flicker = 0.0f;
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("axis"),
          py::arg("radius"),
          "Fit and store a warp-nacelle glow capsule on the instance. "
          "center/axis/radius are in game units / body frame. Returns the "
          "region index, or -1 on failure (stale id, no model, no slot).");

    m.def("clear_glow_regions",
          [](scenegraph::InstanceId id) {
              // Reset every slot to its default (inactive) state, so a
              // controller can re-register from scratch. Regions otherwise
              // register once, at spawn; the SPV's Save refresh
              // (host_loop.refresh_ship_glow) is the caller. Stale id: no-op.
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              for (auto& n : inst->glow_regions) n = {};
          },
          py::arg("instance_id"),
          "Deactivate every glow region on the instance (stale id: no-op).");

    m.def("add_sphere_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center, float radius) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              // hardpoint center/radius are in game units; convert to model
              // frame (same s as compute_capsule_region / damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              const renderer::GlowRegion reg =
                  renderer::add_sphere_region(c, radius * inv);
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n.center = reg.center;
                  n.axis = reg.axis;
                  n.radius = reg.radius;
                  n.aft = reg.aft;
                  n.fore = reg.fore;
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.flicker = 0.0f;
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("radius"),
          "Store a sphere glow region at a hardpoint (game units / body frame). "
          "Returns the region index, or -1 on failure (stale id, no slot).");

    m.def("add_cylinder_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center,
             std::tuple<float, float, float> axis,
             float radius, float length) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              // center/radius/length are game units -> model frame; axis is a
              // direction (normalize, no scale).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              glm::vec3 a(std::get<0>(axis), std::get<1>(axis), std::get<2>(axis));
              const float alen = glm::length(a);
              a = (alen > 1e-6f) ? (a / alen) : glm::vec3(0.0f, 1.0f, 0.0f);
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n.center = c;
                  n.axis = a;                 // cylinder axis (aft dir)
                  n.radius = radius * inv;
                  n.aft = 0.0f;               // from the centre...
                  n.fore = length * inv;      // ...forward along axis for length
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.flicker = 0.0f;
                  n.gain = 1.0f;
                  n.gain_axis = glm::vec3(0.0f);
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("axis"),
          py::arg("radius"), py::arg("length"),
          "Store a cylinder glow region: from center along axis (unit dir) for "
          "length, radius wide (all game units / body frame; aft=0, fore=length). "
          "Returns the region index, or -1 on failure.");

    m.def("add_box_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center,
             std::tuple<float, float, float> half,
             std::tuple<float, float, float> forward,
             std::tuple<float, float, float> up) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              const glm::vec3 he(std::get<0>(half) * inv,
                                 std::get<1>(half) * inv,
                                 std::get<2>(half) * inv);
              // Orientation is a pure direction basis (no scale). Identity
              // (forward=+Y, up=+Z) => shader R = I => byte-identical.
              const glm::vec3 fwd(std::get<0>(forward), std::get<1>(forward),
                                  std::get<2>(forward));
              const glm::vec3 upv(std::get<0>(up), std::get<1>(up),
                                  std::get<2>(up));
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n = scenegraph::Instance::GlowRegion{};   // reset to defaults
                  n.center = c;
                  n.shape = 1.0f;
                  n.half_extents = he;
                  n.forward = fwd;
                  n.up = upv;
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("half_extents"),
          py::arg("forward") = std::make_tuple(0.0f, 1.0f, 0.0f),
          py::arg("up") = std::make_tuple(0.0f, 0.0f, 1.0f),
          "Store a box glow region (game units / body frame), optionally tilted "
          "by a (forward, up) body-space basis (default identity = axis-aligned). "
          "Returns the region index, or -1 on failure (stale id, no slot).");

    m.def("set_glow_region_dim",
          [](scenegraph::InstanceId id, int region_index,
             float dim_target, float disable_time, float flicker) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              if (region_index < 0 ||
                  region_index >= static_cast<int>(inst->glow_regions.size())) return;
              auto& n = inst->glow_regions[static_cast<std::size_t>(region_index)];
              if (!n.active) return;
              n.dim_target = dim_target;
              n.disable_time = disable_time;
              n.flicker = flicker;
          },
          py::arg("instance_id"), py::arg("region_index"),
          py::arg("dim_target"), py::arg("disable_time"), py::arg("flicker"),
          "Update a glow region's live dim target [0,1], the game-time seconds "
          "of the last state-change edge (<0 = healthy), and the flicker flag "
          "(1 = disabled/continuous flicker, 0 = solid settle to dim_target).");

    m.def("set_glow_region_gain",
          [](scenegraph::InstanceId id, int region_index, float gain,
             std::tuple<float, float, float> gate_axis) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              if (region_index < 0 ||
                  region_index >= static_cast<int>(inst->glow_regions.size())) return;
              auto& n = inst->glow_regions[static_cast<std::size_t>(region_index)];
              if (!n.active) return;
              n.gain = gain;
              // Gate axis is a direction (model space) — normalize, no scale.
              glm::vec3 a(std::get<0>(gate_axis), std::get<1>(gate_axis),
                          std::get<2>(gate_axis));
              const float len = glm::length(a);
              n.gain_axis = (len > 1e-6f) ? (a / len) : glm::vec3(0.0f);
          },
          py::arg("instance_id"), py::arg("region_index"), py::arg("gain"),
          py::arg("gate_axis") = std::make_tuple(0.0f, 0.0f, 0.0f),
          "Update a glow region's brightness gain (1.0 = untouched, >1 brightens "
          "the glow inside the region for impulse engine power/speed; feeds HDR). "
          "gate_axis (model-space dir, 0 = none) restricts the gain to faces "
          "whose normal points along it (aft impulse faces only).");

    m.def("world_to_body",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal)
              -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();  // stale id
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              // pw is INSTANCE-RELATIVE (floating render origin).
              const glm::vec3 pb = scenegraph::relative_to_body(inst->world_linear, pw);
              const glm::vec3 nb = scenegraph::dir_to_body(inst->world_linear, nw);
              return py::make_tuple(
                  py::make_tuple(pb.x, pb.y, pb.z),
                  py::make_tuple(nb.x, nb.y, nb.z));
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          "Convert an INSTANCE-RELATIVE hit point (world point minus "
          "instance_translation) + world normal into the ship instance's "
          "body frame (model units). Returns ((bx,by,bz),(nx,ny,nz)) or None "
          "if the instance id is stale.");

    m.def("damage_decals_tick",
          [](float time) {
              g_decal_game_time = time;
              g_world.for_each_alive([&](scenegraph::Instance& inst) {
                  inst.decals.tick(time);
                  inst.breach_events.tick(time);
              });
          },
          py::arg("time"),
          "Age every instance's decal ring; reclaim cold heat-glow decals. "
          "Also ticks the breach-event ring for each instance, expiring events "
          "whose age exceeds kEventLife.");

    auto keys = m.def_submodule("keys", "GLFW key-code constants for input bindings.");
    keys.attr("KEY_W") = GLFW_KEY_W;
    keys.attr("KEY_S") = GLFW_KEY_S;
    keys.attr("KEY_A") = GLFW_KEY_A;
    keys.attr("KEY_D") = GLFW_KEY_D;
    keys.attr("KEY_Q") = GLFW_KEY_Q;
    keys.attr("KEY_E") = GLFW_KEY_E;
    keys.attr("KEY_R") = GLFW_KEY_R;
    keys.attr("KEY_F") = GLFW_KEY_F;  // primary fire (phasers)
    keys.attr("KEY_G") = GLFW_KEY_G;  // tertiary fire (disruptors/pulse)
    keys.attr("KEY_X") = GLFW_KEY_X;  // secondary fire (torpedoes)
    keys.attr("KEY_T")         = GLFW_KEY_T;          // tractor toggle (with Alt)
    keys.attr("KEY_LEFT_ALT")  = GLFW_KEY_LEFT_ALT;   // Alt modifier
    keys.attr("KEY_RIGHT_ALT") = GLFW_KEY_RIGHT_ALT;
    keys.attr("KEY_I") = GLFW_KEY_I;
    keys.attr("KEY_K") = GLFW_KEY_K;  // dev: cycle BoP wing deflection
    keys.attr("KEY_0") = GLFW_KEY_0;
    keys.attr("KEY_1") = GLFW_KEY_1;
    keys.attr("KEY_2") = GLFW_KEY_2;
    keys.attr("KEY_3") = GLFW_KEY_3;
    keys.attr("KEY_4") = GLFW_KEY_4;
    keys.attr("KEY_5") = GLFW_KEY_5;
    keys.attr("KEY_6") = GLFW_KEY_6;
    keys.attr("KEY_7") = GLFW_KEY_7;
    keys.attr("KEY_8") = GLFW_KEY_8;
    keys.attr("KEY_9") = GLFW_KEY_9;
    keys.attr("KEY_C")     = GLFW_KEY_C;
    keys.attr("KEY_V")     = GLFW_KEY_V;
    keys.attr("KEY_Z")     = GLFW_KEY_Z;
    keys.attr("KEY_EQUAL") = GLFW_KEY_EQUAL;
    keys.attr("KEY_MINUS") = GLFW_KEY_MINUS;
    keys.attr("KEY_UP")    = GLFW_KEY_UP;
    keys.attr("KEY_DOWN")  = GLFW_KEY_DOWN;
    keys.attr("KEY_LEFT")  = GLFW_KEY_LEFT;
    keys.attr("KEY_RIGHT") = GLFW_KEY_RIGHT;
    keys.attr("KEY_F1")    = GLFW_KEY_F1;
    keys.attr("KEY_F2")    = GLFW_KEY_F2;
    keys.attr("KEY_F3")    = GLFW_KEY_F3;
    keys.attr("KEY_F4")    = GLFW_KEY_F4;
    keys.attr("KEY_F5")    = GLFW_KEY_F5;
    keys.attr("KEY_F6")    = GLFW_KEY_F6;
    keys.attr("KEY_F7")    = GLFW_KEY_F7;
    keys.attr("KEY_F8")    = GLFW_KEY_F8;
    keys.attr("KEY_F9")    = GLFW_KEY_F9;
    keys.attr("KEY_F10")   = GLFW_KEY_F10;
    keys.attr("KEY_F11")   = GLFW_KEY_F11;
    keys.attr("KEY_F12")          = GLFW_KEY_F12;
    keys.attr("KEY_LEFT_BRACKET")  = GLFW_KEY_LEFT_BRACKET;
    keys.attr("KEY_RIGHT_BRACKET") = GLFW_KEY_RIGHT_BRACKET;
    keys.attr("KEY_GRAVE_ACCENT")  = GLFW_KEY_GRAVE_ACCENT;
    // Punctuation used by the dev tuning keybindings. A dev binding on an
    // UNEXPORTED constant raises AttributeError on the first developer-mode
    // tick, and the enclosing try in host_loop has no except clause -- so it
    // kills the process before any live look. That is exactly how a dead key
    // shipped once already; tests/unit/test_host_key_manifest.py and
    // test_dev_key_collisions.py now guard it from both directions.
    // All four are unbound in engine/input_map.py's ACTIONS table.
    keys.attr("KEY_COMMA")      = GLFW_KEY_COMMA;
    keys.attr("KEY_PERIOD")     = GLFW_KEY_PERIOD;
    keys.attr("KEY_SEMICOLON")  = GLFW_KEY_SEMICOLON;
    keys.attr("KEY_APOSTROPHE") = GLFW_KEY_APOSTROPHE;
    // Dev system-nebula look-dial tuning (engine/dev_nebula_dials.py). Free
    // in input_map.ACTIONS, the dev-keybinding registry, the directly-read
    // set, the SDK-routed F6/F9, AND every App.WC_* key BC's own
    // DefaultKeyboardBinding.py binds -- see test_dev_key_collisions.py's
    // "namespace 5" check. (An earlier cut used J/N/M/U/B/P here, which
    // collided with BC's own WC_J/N/M/U/B bindings; removed.)
    keys.attr("KEY_L") = GLFW_KEY_L;
    keys.attr("KEY_O") = GLFW_KEY_O;
    keys.attr("KEY_SLASH") = GLFW_KEY_SLASH;
    keys.attr("KEY_PAUSE") = GLFW_KEY_PAUSE;
    keys.attr("KEY_KP_0")        = GLFW_KEY_KP_0;
    keys.attr("KEY_KP_DECIMAL")  = GLFW_KEY_KP_DECIMAL;
    keys.attr("KEY_KP_MULTIPLY") = GLFW_KEY_KP_MULTIPLY;
    keys.attr("KEY_KP_DIVIDE")   = GLFW_KEY_KP_DIVIDE;
    keys.attr("KEY_LEFT_SUPER")   = GLFW_KEY_LEFT_SUPER;
    keys.attr("KEY_LEFT_CONTROL") = GLFW_KEY_LEFT_CONTROL;
    keys.attr("KEY_SPACE") = GLFW_KEY_SPACE;
    keys.attr("KEY_ESCAPE") = GLFW_KEY_ESCAPE;
    keys.attr("KEY_LEFT_SHIFT")  = GLFW_KEY_LEFT_SHIFT;
    keys.attr("KEY_RIGHT_SHIFT") = GLFW_KEY_RIGHT_SHIFT;
    keys.attr("MOUSE_BUTTON_LEFT")   = GLFW_MOUSE_BUTTON_LEFT;
    keys.attr("MOUSE_BUTTON_RIGHT")  = GLFW_MOUSE_BUTTON_RIGHT;
    keys.attr("MOUSE_BUTTON_MIDDLE") = GLFW_MOUSE_BUTTON_MIDDLE;

    m.def("key_state",
          [](int key) {
              if (!g_window) {
                  throw std::runtime_error("key_state: init must be called first");
              }
              return g_window->key_state(key);
          },
          py::arg("key"),
          "Returns true while the key is held.");

    m.def("consume_scroll_y",
          []() {
              if (!g_window) {
                  throw std::runtime_error("consume_scroll_y: init must be called first");
              }
              return g_window->consume_scroll_y();
          },
          "Return the accumulated mouse-wheel Y delta since the last call "
          "and reset the accumulator. Positive = scroll up.");

    m.def("consume_mouse_delta",
          []() {
              if (!g_window) {
                  throw std::runtime_error("consume_mouse_delta: init must be called first");
              }
              double dx = 0.0, dy = 0.0;
              g_window->consume_mouse_delta(&dx, &dy);
              return std::make_tuple(dx, dy);
          },
          "Return (dx, dy) accumulated cursor motion in pixels since the last call. "
          "Reset on each call. GLFW raw mode while cursor is locked.");

    m.def("cursor_pos",
          []() {
              if (!g_window) {
                  throw std::runtime_error("cursor_pos: init must be called first");
              }
              double x = 0.0, y = 0.0;
              g_window->cursor_pos(&x, &y);
              return std::make_tuple(x, y);
          },
          "Return (x, y) cursor position in screen pixels.  Updated by "
          "GLFW cursor callbacks; returns the most recent value.  Origin "
          "is top-left of the window.");

    m.def("set_cursor_locked",
          [](bool locked) {
              if (!g_window) {
                  throw std::runtime_error("set_cursor_locked: init must be called first");
              }
              g_window->set_cursor_locked(locked);
          },
          py::arg("locked"),
          "Lock the cursor (hidden + raw deltas) or release it.");

    m.def("set_cursor_shape",
          [](const std::string& shape) {
              if (!g_window) {
                  throw std::runtime_error("set_cursor_shape: init must be called first");
              }
              if (shape == "crosshair") {
                  g_window->set_cursor_shape(1);
              } else if (shape == "arrow") {
                  g_window->set_cursor_shape(0);
              } else {
                  throw std::invalid_argument("set_cursor_shape: unknown shape '" + shape + "'");
              }
          },
          py::arg("shape"),
          "OS pointer shape while unlocked: \"arrow\" or \"crosshair\" "
          "(Manual Aim). Soft-guarded on the Python side (host_io) so a "
          "stale module degrades to the arrow.");

    m.def("key_pressed",
          [](int key) {
              if (!g_window) {
                  throw std::runtime_error("key_pressed: init must be called first");
              }
              const bool now = g_window->key_state(key);
              auto it = g_prev_key_state.find(key);
              const bool prev = (it != g_prev_key_state.end()) && it->second;
              if (it == g_prev_key_state.end()) {
                  // First query: register the key for tracking. Initial prev
                  // is the current state, so a key already held when the
                  // caller starts polling does NOT count as a rising edge.
                  g_prev_key_state[key] = now;
              }
              return now && !prev;
          },
          py::arg("key"),
          "Returns true on the first frame the key is pressed (rising edge).");

    // Edge detection is split across mouse_button_pressed (read-only) and
    // mouse_button_released (which also writes the new prev). The host
    // loop's _poll_mouse_buttons calls pressed first, then released — so
    // both observe the same prev within a frame and prev advances exactly
    // once per frame.  Prior to this split prev was only ever initialised,
    // never updated, so mouse_button_pressed returned true every frame the
    // button stayed down — the cause of the "staccato fire" symptom.
    m.def("mouse_button_pressed",
          [](int button) {
              if (!g_window) {
                  throw std::runtime_error("mouse_button_pressed: init must be called first");
              }
              const bool now = g_window->mouse_button_state(button);
              auto it = g_prev_mouse_state.find(button);
              const bool prev = (it != g_prev_mouse_state.end()) && it->second;
              return now && !prev;
          },
          py::arg("button"),
          "Returns true on the first frame the mouse button is pressed (rising edge).");

    m.def("mouse_button_released",
          [](int button) {
              if (!g_window) {
                  throw std::runtime_error("mouse_button_released: init must be called first");
              }
              const bool now = g_window->mouse_button_state(button);
              auto it = g_prev_mouse_state.find(button);
              const bool prev = (it != g_prev_mouse_state.end()) && it->second;
              g_prev_mouse_state[button] = now;
              return prev && !now;
          },
          py::arg("button"),
          "Returns true on the first frame the mouse button is released (falling edge).");

    // Raw held-state read. Unlike mouse_button_pressed/released this does
    // NOT touch g_prev_mouse_state, so callers can poll the current
    // up/down state without stealing the edge that the pause-menu CEF
    // forwarding (mouse_button_released) relies on. Used by panels that
    // do their own drag-edge tracking (e.g. the Ship Property Viewer's
    // orbit drag) while CEF still receives clicks for its own widgets.
    m.def("mouse_button_state",
          [](int button) {
              if (!g_window) {
                  throw std::runtime_error("mouse_button_state: init must be called first");
              }
              return g_window->mouse_button_state(button);
          },
          py::arg("button"),
          "Return the raw current up/down state of a mouse button without "
          "consuming any edge state.");

    // Test/debug helper: read one RGBA8 pixel from the most recently
    // presented frame. Reads GL_FRONT (the buffer that swap_buffers
    // promoted from BACK) so a single frame() + read_pixel sequence
    // returns what was just drawn. Lets headless tests programmatically
    // assert "the last frame produced non-zero pixels" instead of needing
    // visual confirmation.
    m.def("read_pixel",
          [](int x, int y) {
              if (!g_window) {
                  throw std::runtime_error("read_pixel: init must be called first");
              }
              std::uint8_t rgba[4] = {0, 0, 0, 0};
              glReadBuffer(GL_FRONT);
              glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
              glReadBuffer(GL_BACK);  // restore default
              return std::make_tuple(rgba[0], rgba[1], rgba[2], rgba[3]);
          },
          py::arg("x"), py::arg("y"));

    // Test/debug helper: return the current framebuffer size.
    m.def("framebuffer_size",
          []() {
              if (!g_window) {
                  throw std::runtime_error("framebuffer_size: init must be called first");
              }
              int fw = 0, fh = 0;
              g_window->framebuffer_size(&fw, &fh);
              return std::make_tuple(fw, fh);
          });

    // Logical window size in screen coordinates. framebuffer_size /
    // window_size gives the device-pixel ratio, used by CEF init to
    // render at native resolution on Retina.
    m.def("window_size",
          []() {
              if (!g_window) {
                  throw std::runtime_error("window_size: init must be called first");
              }
              int ww = 0, wh = 0;
              g_window->window_size(&ww, &wh);
              return std::make_tuple(ww, wh);
          });

#ifdef DAUNTLESS_ENABLE_CEF
    m.def("cef_initialize",
          [](int view_width, int view_height, const std::string& html_path,
             float device_scale_factor) {
              return dauntless::ui_cef::initialize(view_width, view_height, html_path,
                                                   device_scale_factor);
          },
          py::arg("view_width"), py::arg("view_height"), py::arg("html_path"),
          py::arg("device_scale_factor") = 1.0f,
          "Initialise CEF and create the OSR overlay browser. "
          "device_scale_factor (default 1.0) tells CEF to render at "
          "view_width*dsf × view_height*dsf so the composite pass can "
          "blit 1:1 to a high-DPI framebuffer instead of bilinear-"
          "upscaling a low-resolution bitmap. Returns true on success.");

    m.def("cef_resize",
          [](int view_width, int view_height, float device_scale_factor) {
              dauntless::ui_cef::resize(view_width, view_height,
                                        device_scale_factor);
          },
          py::arg("view_width"), py::arg("view_height"),
          py::arg("device_scale_factor") = 1.0f,
          "Re-size the OSR overlay browser to track the host window. "
          "view_width/height are logical (window-point) pixels; "
          "device_scale_factor is framebuffer/window. Forces CEF to "
          "re-layout the HTML/CSS at the new size (no stretch). Cheap when "
          "called with unchanged values; the host still guards on change.");

    m.def("cef_pump",
          []() { dauntless::ui_cef::pump(); },
          "Run one iteration of CEF's message loop. Call once per frame.");

    m.def("cef_composite",
          []() { dauntless::ui_cef::composite(); },
          "Blit the latest CEF bitmap over the current framebuffer.");

    m.def("cef_shutdown",
          []() { dauntless::ui_cef::shutdown(); },
          "Tear down CEF. Call before the GL context is destroyed.");

    m.def("cef_toggle_devtools",
          []() { dauntless::ui_cef::toggle_devtools(); },
          "Open or close the DevTools window for the overlay browser.");

    m.def("cef_devtools_open",
          []() { return dauntless::ui_cef::devtools_open(); },
          "True while the overlay browser's DevTools window is open. The host "
          "loop freezes the simulation on this.");

    m.def("cef_reload",
          []() { dauntless::ui_cef::reload(); },
          "Reload the overlay browser's current document.");

    m.def("cef_execute_javascript",
          [](const std::string& script) {
              dauntless::ui_cef::execute_javascript(script);
          },
          py::arg("script"),
          "Execute JavaScript in the main frame of the overlay browser.");

    m.def("cef_send_mouse_move",
          [](int x, int y) {
              dauntless::ui_cef::send_mouse_move(x, y);
          },
          py::arg("x"), py::arg("y"),
          "Forward a mouse-move event to the CEF overlay (drives :hover).");

    m.def("cef_send_mouse_click",
          [](int x, int y, int button, bool is_down) {
              dauntless::ui_cef::send_mouse_click(x, y, button, is_down);
          },
          py::arg("x"), py::arg("y"), py::arg("button"), py::arg("is_down"),
          "Forward a mouse button edge to the CEF overlay. "
          "button: 0=left, 1=middle, 2=right. is_down: True for press, False for release.");

    m.def("cef_send_mouse_wheel",
          [](int x, int y, int delta_y) {
              dauntless::ui_cef::send_mouse_wheel(x, y, delta_y);
          },
          py::arg("x"), py::arg("y"), py::arg("delta_y"),
          "Forward a mouse-wheel event to the CEF overlay. "
          "delta_y: positive scrolls up.");

    m.def("cef_set_event_handler",
          [](py::function callback) {
              // pybind11 manages the function's lifetime; ensure the
              // captured callable holds a strong ref so it survives
              // until the next set_event_handler call replaces it.
              dauntless::ui_cef::set_event_handler(
                  [cb = std::move(callback)](const std::string& name) {
                      py::gil_scoped_acquire gil;
                      try {
                          cb(name);
                      } catch (const py::error_already_set& e) {
                          std::fprintf(stderr,
                              "cef_set_event_handler: python callback raised: %s\n",
                              e.what());
                      }
                  });
          },
          py::arg("callback"),
          "Register a Python callback (str)->None invoked when JS "
          "navigates to dauntless://event/<name>. The handler runs on "
          "the main thread (single-threaded CEF message loop).");

    m.def("cef_set_load_end_handler",
          [](py::function callback) {
              dauntless::ui_cef::set_load_end_handler(
                  [cb = std::move(callback)]() {
                      py::gil_scoped_acquire gil;
                      try {
                          cb();
                      } catch (const py::error_already_set& e) {
                          std::fprintf(stderr,
                              "cef_set_load_end_handler: python callback raised: %s\n",
                              e.what());
                      }
                  });
          },
          py::arg("callback"),
          "Register a Python callback ()->None invoked once when the CEF "
          "main frame finishes loading (initial load and Cmd+R reload). "
          "The handler runs on the main thread (single-threaded CEF "
          "message loop).");
#else
    // Stub the bindings out so engine.host_loop can call them
    // unconditionally regardless of build config.
    m.def("cef_initialize",
          [](int, int, const std::string&, float) { return false; },
          py::arg("view_width"), py::arg("view_height"), py::arg("html_path"),
          py::arg("device_scale_factor") = 1.0f);
    m.def("cef_resize",
          [](int, int, float) {},
          py::arg("view_width"), py::arg("view_height"),
          py::arg("device_scale_factor") = 1.0f);
    m.def("cef_pump",            []() {});
    m.def("cef_composite",       []() {});
    m.def("cef_shutdown",        []() {});
    m.def("cef_toggle_devtools", []() {});
    m.def("cef_devtools_open",   []() { return false; });
    m.def("cef_reload",          []() {});
    m.def("cef_execute_javascript", [](const std::string&) {});
    m.def("cef_send_mouse_move",  [](int, int) {});
    m.def("cef_send_mouse_click", [](int, int, int, bool) {});
    m.def("cef_send_mouse_wheel", [](int, int, int) {});
    m.def("cef_set_event_handler",[](py::function) {});
    m.def("cef_set_load_end_handler", [](py::function) {});
#endif

    dauntless::audio::register_python_bindings(m);

    // ── Transform store ──────────────────────────────────────────────────────
    // Authoritative position/rotation for every ObjectClass. See
    // docs/superpowers/specs/2026-09-05-native-transform-ownership-design.md.
    m.def("transform_alloc", []() {
              return dauntless::transform_store().alloc();
          },
          "Allocate a transform slot. Returns (index, generation).");

    m.def("transform_free",
          [](std::uint32_t i, std::uint32_t g) {
              dauntless::transform_store().free(i, g);
          },
          py::arg("index"), py::arg("generation"),
          "Release a transform slot. Raises RuntimeError if the handle is stale.");

    m.def("transform_get_position",
          [](std::uint32_t i, std::uint32_t g) {
              return dauntless::transform_store().position(i, g);
          },
          py::arg("index"), py::arg("generation"));

    m.def("transform_set_position",
          [](std::uint32_t i, std::uint32_t g, double x, double y, double z) {
              dauntless::transform_store().set_position(i, g, x, y, z);
          },
          py::arg("index"), py::arg("generation"),
          py::arg("x"), py::arg("y"), py::arg("z"));

    m.def("transform_get_rotation",
          [](std::uint32_t i, std::uint32_t g) {
              return dauntless::transform_store().rotation(i, g);
          },
          py::arg("index"), py::arg("generation"),
          "Row-major nine doubles.");

    m.def("transform_set_rotation",
          [](std::uint32_t i, std::uint32_t g, const std::array<double, 9>& r) {
              dauntless::transform_store().set_rotation(i, g, r);
          },
          py::arg("index"), py::arg("generation"), py::arg("rot9"));

    m.def("transform_get_rotation_col",
          [](std::uint32_t i, std::uint32_t g, int col) {
              return dauntless::transform_store().rotation_col(i, g, col);
          },
          py::arg("index"), py::arg("generation"), py::arg("col"));

    m.def("transform_get_positions",
          [](const std::vector<std::pair<std::uint32_t, std::uint32_t>>& h) {
              return dauntless::transform_store().positions(h);
          },
          py::arg("handles"),
          "Bulk position read: one crossing instead of N.");

    m.def("transform_live_count", []() {
              return dauntless::transform_store().live_count();
          });

    m.def("transform_capacity", []() {
              return dauntless::transform_store().capacity();
          });
}
