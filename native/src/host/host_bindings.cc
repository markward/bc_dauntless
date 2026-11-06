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
#include "combat_effect_queue.h"
#include "combat_write_apply.h"
#include "motion_write_apply.h"
#include "subsystem_write_apply.h"

#include <algorithm>
#include <cstring>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <audio/python_binding.h>
#include "dauntless/torpedo_scan.h"
#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/damage.h"
#include "dauntless/combat/fire_gates.h"
#include "dauntless/combat/k0_charging.h"
#include "dauntless/combat/k1_fire_control.h"
#include "dauntless/combat/k2_beams.h"
#include "dauntless/combat/k3_projectiles.h"
#include "dauntless/combat/k4_eligibility.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/profile_eval.h"
#include "dauntless/combat/projectile_geometry.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/impulse.h"
#include "dauntless/combat/motion_step.h"
#include "dauntless/combat/published_poses.h"
#include "dauntless/combat/subsystem_step.h"
#include "dauntless/combat/tractor_force.h"
#include "dauntless/combat/weapon_geometry.h"
#include "dauntless/interp_buffer.h"
#include "dauntless/transform_store.h"
#include "platform/relaunch.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <renderer/window.h>
#include <renderer/text_input.h>
#include <renderer/pipeline.h>
#include <renderer/plating_damage.h>
#include <renderer/part_severance_check.h>
#include <renderer/part_severance_jobs.h>
#include <renderer/structure_parts_cache.h>
#include <renderer/bone_palette.h>
#include <renderer/head_center.h>
#include <renderer/animation_update.h>
#include <renderer/channel_binder.h>
#include <renderer/frame.h>
#include <renderer/scuff_texture.h>
#include <renderer/frame_timer.h>
#include <renderer/lighting.h>
#include <renderer/dynamic_lights.h>
#include <renderer/backdrop_pass.h>
#include <renderer/sun_pass.h>
#include <renderer/atmosphere_pass.h>
#include <renderer/planet_detail_pass.h>
#include <renderer/dust_pass.h>
#include <renderer/minor_field.h>
#include <renderer/minor_pass.h>
#include <renderer/far_field.h>
#include <renderer/far_pass.h>
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
#include <atomic>
#include <chrono>
#include <thread>
#include <renderer/running_light_pass.h>
#include <renderer/running_light_store.h>
#include <renderer/nebula_wake_pass.h>
#include <renderer/shockwave_pass.h>
#include <renderer/warp_in_flash_pass.h>
#include <renderer/particle_pass.h>
#include <renderer/phaser_pass.h>
#include <renderer/hologram_pass.h>
#include <renderer/cloak_pass.h>
#include <renderer/breach_venting.h>  // venting descriptor builder
#include <renderer/breach_debris.h>  // debris descriptor builder
#include <renderer/hull_fill_cache.h>
#include <renderer/subsystem_pin_pass.h>
#include <renderer/debug_volume_pass.h>
#include <renderer/gizmo_pass.h>
#include <renderer/target_reticle_pass.h>
#include <renderer/starmap_pass.h>
#include <renderer/letterbox_pass.h>
#include <renderer/bridge_pass.h>
#include <renderer/bridge_quality.h>
#include <renderer/viewscreen_bars_pass.h>
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
#include <renderer/viewscreen_rtt_size.h>
#include <renderer/shadow_light.h>
#include <renderer/shadow_map_target.h>
#include <renderer/asset_path.h>
#include <renderer/ray_trace.h>
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
#include <assets/smoothing_probe.h>
#include <assets/texture.h>
#include <nif/file.h>
#include <nif/scene_camera.h>
#include <platform/folder_picker.h>

#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/matrix_inverse.hpp>
#include <array>
#include <cstdio>
#include <unordered_set>
#include "bridge_highlight.h"
#include "developer_mode.h"
#include "model_identity_maps.h"

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
#include <variant>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <functional>
#include <vector>

// Pending request_frame_png path; empty = none. Read and cleared in frame().
static std::string g_frame_png_path;

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
// The structure-severance checks running off the main thread
// (hull_split_parts; part_severance_jobs.h). Keyed by g_world's ids: cleared
// (without waiting) wherever g_world is reset, and an instance's job is
// forgotten when it is destroyed.
renderer::SeveranceJobs g_severance_jobs;
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
// Ambient multiplier for the bridge INTERIOR only: the alert-level scale
// (engine/bridge_lighting.py -- green x1.5, yellow/red x1.0). Applied
// where the main bridge pass renders, never to the comm-set RTT feed — the
// viewscreen shows another ship's room, whose lighting must not follow our
// alert level.
float g_bridge_ambient_scale = 1.0f;
// Player alert level (0 green, 1 yellow, 2 red) choosing the bridge's
// emissive sibling-map variant (BridgePass::set_alert_level). Per-frame
// state like g_bridge_ambient_scale: pushed every frame by host_loop, reset
// to green by reset_frame_state() (init and shutdown).
int g_bridge_alert_level = 0;
// Bridge AO quality preset (Low/Medium/High), set via set_bridge_quality().
// Applied to g_bridge_pass's AO settings both where it is constructed and on
// every set_bridge_quality() call, so a quality change takes effect even
// mid-mission without waiting for the next init().
renderer::BridgeQuality g_bridge_quality = renderer::kDefaultBridgeQuality;
// Bridge AO kernel look, from the developer dials (engine/bridge_ao_dials.py)
// via set_bridge_ao_tuning(). Applied where g_bridge_pass is constructed and
// on every call. Session-wide like the dials themselves: init() keeps it.
renderer::BridgeAoTuning g_bridge_ao_tuning;
// Developer Options -> Lighting tab "Bridge Debug View" (see
// renderer::BridgeDebugView). set_bridge_debug_view is a no-op without
// --developer, so this stays 0 (Off) in production regardless of what
// Python sends.
int g_bridge_debug_view = 0;
// Developer-only bridge editor selection tint (set_bridge_highlight). Held
// here, not only on the pass, so it survives the pass being (re)created and
// is readable headless (bridge_highlight()). model 0 = none.
dauntless::BridgeHighlight g_bridge_highlight;
// Bridge reflection probes (set_bridge_probe_*; production, NOT developer-
// gated). Held here as well as on the pass, so values set before init() --
// or across a pass re-creation -- are applied when the pass is constructed
// (the g_bridge_highlight pattern). `capture_pending` is a request made while
// no pass existed; init() hands it on and clears it. reset_frame_state() does
// NOT touch this stash -- it runs at the start of init(), and clearing here
// would drop exactly the values init() exists to apply.
struct BridgeProbeSettings {
    glm::vec3 origin{0.0f};
    std::array<float, renderer::kBridgeStates> scales{1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
    bool capture_pending = false;
};
BridgeProbeSettings g_bridge_probe;
std::vector<renderer::Backdrop> g_backdrops;
bool g_sky_dirty = true;            // cubemap needs (re)baking
bool g_sky_last_procedural = false; // procedural-toggle state at the last frame
std::unique_ptr<renderer::BackdropPass> g_backdrop_pass;
std::vector<renderer::SunDescriptor> g_suns;
std::vector<glm::vec4> g_dust_planets;   // xyz = world pos, w = radius
float g_dust_profile = 0.0f;   // radial-profile `dust` column at the camera, 0-1
std::unique_ptr<renderer::SunPass> g_sun_pass;
// Planet atmosphere shells (docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §5).
std::unique_ptr<renderer::AtmospherePass> g_atmosphere_pass;
// Planet surface detail (spec 2026-10-08 §5.5): one target planet's clipmap,
// baked once per frame from g_camera; sampled by every space render.
std::unique_ptr<renderer::planet_detail::PlanetDetailPass> g_planet_detail;
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
// Rock-field puffs: soft lit billboards placed by the field density,
// drawn in the MSAA pass after every opaque writer.
bool g_rock_puffs_enabled = true;
renderer::rockfield::PuffField g_puff_field;
int g_rock_puffs_drawn = 0;
// Rock-field speck band (2026-10-04): the near
// band's large rocks past their billboard edge as GPU-faded specks.
bool g_rock_specks_enabled = true;
renderer::rockfield::SpeckBand g_speck_band;
// The SpeckBand::version() last uploaded: a swap or a clear() moves the
// band's version, so a cleared band uploads (and draws) nothing at once.
std::uint64_t g_speck_uploaded_version = 0;
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
// The last frame's shadow-caster load (frame profiler `hulls:` line); the
// opaque half lives on g_submitter (opaque_stats), reset beside this.
renderer::HullDrawStats g_shadow_hull_stats;
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
std::vector<renderer::NebulaVolume> g_nebulae;
std::vector<renderer::NebulaWakePoint> g_nebula_wake;   // world pos, faded strength, pod size
std::unique_ptr<renderer::NebulaPass> g_nebula_pass;
std::unique_ptr<renderer::NebulaVolumetricPass> g_nebula_volumetric_pass;
// System-scale nebula (star-centred atmosphere). On in production: frame()
// runs it whenever Volumetric Nebulae is on and a profile is pushed.
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
// Warp-in flashes (warp-in spec 6.3): full-replace per-frame list and the
// "warp in" dial look, both pushed by host_loop every frame.
std::vector<renderer::WarpInFlashDescriptor> g_warp_in_flashes;
renderer::WarpInFlashParams                  g_warp_in_flash_params;
std::unique_ptr<renderer::WarpInFlashPass>   g_warp_in_flash_pass;
std::vector<renderer::HitVfxDescriptor>    g_hit_vfx;
std::unique_ptr<renderer::HitVfxPass>      g_hit_vfx_pass;
std::vector<renderer::HullDischarge>       g_hull_discharges;
std::unique_ptr<renderer::HullDischargePass> g_hull_discharge_pass;

// Ship running lights (running-lights spec §4.4). The store is per-instance
// and Python-fed at spawn; levels arrive every frame.
renderer::RunningLightStore                  g_running_lights;
renderer::RunningLightDials                  g_running_light_dials;
bool                                         g_running_lights_enabled = true;
std::unique_ptr<renderer::RunningLightPass>  g_running_light_pass;
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
// Shared static hull fill cache: each hull's ORIGINAL fill volume (its
// _vox.nif) as a GL_R8 3D texture, built once per hull source path. Read by
// the hull interior pass (the left-the-ship test behind a plating cut). Owns
// GL textures; lives/dies with the GL context.
std::unique_ptr<renderer::HullFillCache>     g_fill_cache;
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

// The viewscreen render-to-texture feed (16:9) is sized each frame to the
// viewscreen mesh's on-screen pixel height (renderer/viewscreen_rtt_size.h),
// so it sharpens with the window instead of staying 640x360. The model box is
// cached for the one viewscreen handle; cleared in reset_frame_state because
// handles are reissued.
renderer::viewscreen_rtt::Sizer g_viewscreen_rtt_sizer;
std::optional<std::pair<unsigned long long, renderer::Aabb>> g_viewscreen_aabb;

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

// The viewscreen feed's target (set_viewscreen_target_instance, pushed every
// frame by host_loop): on the viewscreen render only this hull gets decks and
// rooms behind its holes (renderer/hull_interior_policy.h). nullopt = none.
std::optional<scenegraph::InstanceId> g_viewscreen_target;

// Rooms near distance (InteriorPolicy::near_gu) for the main view: the
// policy is rebuilt per render from this. Only Developer Options -> "Hull
// damage" writes it (set_interior_near_gu); production keeps the default.
float g_interior_near_gu = renderer::InteriorPolicy{}.near_gu;

// Viewscreen static/"snow" overlay: composited over the viewscreen RTT after
// the feed (comm or forward) is rendered. on/intensity are pushed per frame by
// host_loop (intensity = SDK fMin/fMax flicker); textures come from the
// "View Screen Static" icon group paths resolved in Python.
struct ViewscreenStatic { bool on = false; float intensity = 0.0f; };
ViewscreenStatic g_viewscreen_static;
std::unique_ptr<renderer::ViewscreenStaticPass> g_viewscreen_static_pass;

// Target name / range bands drawn INTO the viewscreen RTT on the scene (target)
// feed only. Pushed per frame by host_loop; font loaded once at init.
renderer::ViewscreenBars g_viewscreen_bars;
std::unique_ptr<renderer::ViewscreenBarsPass> g_viewscreen_bars_pass;

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

// get_instance_head_center's memo. Keyed by model handle, which init() and
// shutdown() reissue, so both clear it beside g_loaded_models.
renderer::HeadCenterCache g_head_center_cache;

// Resolve a model handle to its loaded asset (or nullptr). File-scope so both
// frame()'s draw lookup and the get_instance_bounds binding share one path.
const assets::Model* resolve_model(scenegraph::ModelHandle h) {
    if (h == 0 || h > g_loaded_models.size()) return nullptr;
    return g_loaded_models[h - 1].handle.get();
}

// The pose every gameplay point query reads (native motion phase 3a): the
// SIM pose, composed from the live transform store through the instance's
// sim source plus its per-set VIEW offset -- never the drawn (possibly
// interpolated) world_linear/world_translation_d. drawn=true, no source, or
// a stale source (the object was collected; a recycled slot is never read)
// gives the drawn pose. Inside the published-pose read window (phase 4,
// published_poses.h) the slot's published pose stands in for the store
// read, the rule detail::xform follows; a slot not published reads live.
struct HitPose {
    glm::mat3 linear;
    glm::dvec3 translation;
};
HitPose hit_pose_of(const scenegraph::Instance& inst, bool drawn) {
    if (!drawn && inst.sim_xform_index >= 0) {
        const auto& store = dauntless::transform_store();
        const auto i = static_cast<std::uint32_t>(inst.sim_xform_index);
        if (store.valid(i, inst.sim_xform_generation)) {
            HitPose p;
            dauntless::compose_world_linear_translation(
                dauntless::combat::read_pose(store, i,
                                             inst.sim_xform_generation),
                inst.sim_scale, p.linear, p.translation);
            p.translation += inst.sim_view_offset;
            return p;
        }
    }
    return {inst.world_linear, inst.world_translation_d};
}

// Native render interpolation (phase 3c). Snapshots are keyed by the render
// instance's id (index << 32 | generation), so a recycled instance slot never
// inherits one; the poses are set-local and unscaled (the sim source's scale
// and view offset are applied at compose). Cleared by reset_frame_state().
dauntless::InterpBuffer g_interp;
// The pose interp_compose last drew for each instance: what a handover freezes.
std::unordered_map<dauntless::InterpBuffer::Key, dauntless::Pose> g_interp_drawn;
// The one handover blend (the player's) and the instance it eases.
dauntless::HandoverBlend g_handover;
dauntless::InterpBuffer::Key g_handover_key = 0;

dauntless::InterpBuffer::Key interp_key(scenegraph::InstanceId id) {
    return (static_cast<std::uint64_t>(id.index) << 32) | id.generation;
}

// The instance's live sim-source pose; false for no source or a stale one.
bool sim_source_pose(const scenegraph::Instance& inst, dauntless::Pose& out) {
    if (inst.sim_xform_index < 0) return false;
    const auto& store = dauntless::transform_store();
    const auto i = static_cast<std::uint32_t>(inst.sim_xform_index);
    if (!store.valid(i, inst.sim_xform_generation)) return false;
    out = store.at(i);
    return true;
}

// Drop an instance's snapshots, last drawn pose and (if it is the eased one)
// the handover.
void interp_forget(dauntless::InterpBuffer::Key k) {
    g_interp.erase(k);
    g_interp_drawn.erase(k);
    if (k == g_handover_key) g_handover.cancel();
}

// The DRAWN pose of a tracked instance, the one interp_sample returns and
// interp_compose draws: the live store pose for an interp_live instance (when
// its source is valid), else lerp(prev, cur, alpha), then the handover blend
// for the eased instance. A tracked instance with no snapshot yet seeds from
// its source first. False when there is nothing to draw.
bool interp_drawn_pose(const scenegraph::Instance& inst, double alpha,
                       dauntless::Pose& out) {
    if (!inst.interp_track) return false;
    const auto k = interp_key(inst.id);
    dauntless::Pose truth{};
    if (!(inst.interp_live && sim_source_pose(inst, truth))) {
        if (!g_interp.has(k)) {
            dauntless::Pose seed{};
            if (!sim_source_pose(inst, seed)) return false;
            g_interp.capture(k, seed);
        }
        g_interp.sample(k, alpha, truth);
    }
    out = (k == g_handover_key && g_handover.active()) ? g_handover.blend(truth)
                                                       : truth;
    return true;
}

// The instance_translation binding's body: the instance's double VIEW-space
// hit-pose translation, or nullopt for a stale id. Shared with K2's trace
// hooks (install_combat_trace_hooks).
std::optional<glm::dvec3> instance_translation_for_python(
    scenegraph::InstanceId id, bool drawn = false) {
    const auto* inst = g_world.get(id);
    if (inst == nullptr) return std::nullopt;
    return hit_pose_of(*inst, drawn).translation;
}

// The shield_hit binding's body: ONE implementation, two callers -- the
// binding (pybind has already narrowed its Python floats) and the K2
// drain's native presentation (combat_k2_drain; it narrows the same way).
// Callers pass an INSTANCE-RELATIVE point (the world hit minus
// instance_translation, formed in double), but the state stores BODY so the
// splash rides the hull instead of being left behind as the ship flies on.
// Convert here, once, inverting only rotation*scale — never a large
// translation (the floating render origin). No shield pass (headless) or an
// unknown instance drops the hit — the pass would drop it anyway.
void push_shield_hit(scenegraph::InstanceId id, const glm::vec3& point,
                     const glm::vec4& rgba, float intensity, float radius) {
    if (!g_shield_pass) return;
    const auto* inst = g_world.get(id);
    if (inst == nullptr) return;
    const glm::vec3 body = scenegraph::relative_to_body(
        hit_pose_of(*inst, /*drawn=*/false).linear, point);
    g_shield_pass->shield_hit(id, body, rgba, intensity, glfwGetTime(),
                              radius);
}

// The ray_trace_mesh binding's body: ONE implementation, two callers -- the
// binding (pybind has already narrowed its Python floats) and the K2 kernel's
// trace hook (install_combat_trace_hooks; the kernel narrows the same way).
// Native combat spec 2026-10-31-native-combat-k2-beams §4.2: the kernel gets
// the renderer's own compiled trace, at this TU's flags, never a recompile.
// nullopt is the binding's None. Throws combat::StaleInstance (a
// std::runtime_error: the binding still raises RuntimeError with the same
// message) for a stale id, std::runtime_error for no model handle.
std::optional<renderer::RayHit> trace_instance_for_python(
    scenegraph::InstanceId id, const glm::vec3& o, glm::vec3 d, float max_dist,
    bool rest_pose, bool drawn = false) {
    auto* inst = g_world.get(id);
    if (inst == nullptr) {
        throw dauntless::combat::StaleInstance(
            "ray_trace_mesh: invalid InstanceId");
    }
    const auto h = inst->model_handle;
    if (h == 0 || h > g_loaded_models.size()) {
        throw std::runtime_error("ray_trace_mesh: instance has no model");
    }
    const assets::Model* model = g_loaded_models[h - 1].handle.get();
    if (model == nullptr) return std::nullopt;

    const float dlen = glm::length(d);
    if (dlen < 1e-9f) return std::nullopt;
    d /= dlen;
    if (!std::isfinite(max_dist) || max_dist <= 0.0f) return std::nullopt;

    // Trace against the pose the instance is DRAWN at, not its rest pose.
    // Without &inst->node_overrides a raised Bird of Prey wing is visible but
    // unhittable, and -- because combat._resolve_impact_point runs this trace
    // and part_severance attributes damage from the point it returns -- a
    // wing shot while raised would accumulate nothing and never come off.
    // Instance-relative ray, rotation*scale inverted only: a ship 1e6 GU out
    // traces with the precision of one at the origin. rest_pose: the NIF's
    // rest geometry instead (authored, rest-frame content such as DamageTool
    // volumes). The pose is whatever g_world was last synced to; nothing
    // here re-syncs it (K2 map 8.3.9). The pose is the hit pose (sim unless
    // drawn), whose translation instance_translation_for_python returns.
    return renderer::ray_trace_instance_linear(
        *model, hit_pose_of(*inst, drawn).linear, o, d, max_dist,
        rest_pose ? nullptr : &inst->node_overrides);
}

// K2's trace hooks: the two bodies above on g_world, touching no Python
// (the kernel calls them inside its compute, with the GIL released).
dauntless::combat::TraceHooks combat_trace_hooks() {
    namespace cb = dauntless::combat;
    cb::TraceHooks hooks;
    hooks.translation = [](cb::InstanceId id) -> std::optional<cb::Vec3> {
        const auto t = instance_translation_for_python({id.index, id.generation});
        if (!t) return std::nullopt;
        return cb::Vec3{t->x, t->y, t->z};
    };
    hooks.trace = [](cb::InstanceId id, const float o[3], const float d[3],
                     float max_dist) -> std::optional<cb::TraceHit> {
        const auto hit = trace_instance_for_python(
            {id.index, id.generation}, glm::vec3(o[0], o[1], o[2]),
            glm::vec3(d[0], d[1], d[2]), max_dist, /*rest_pose=*/false);
        if (!hit) return std::nullopt;
        return cb::TraceHit{{hit->point.x, hit->point.y, hit->point.z},
                            {hit->normal.x, hit->normal.y, hit->normal.z},
                            hit->t};
    };
    return hooks;
}

// Shared by set_bridge_spots and set_bridge_area_lights: a float3 tuple as a
// glm::vec3, and a finite-components check used to drop a row whose
// position/direction/colour carries a NaN or Inf -- one reaching the shader
// becomes a NaN bloom square.
glm::vec3 bridge_v3(const std::tuple<float, float, float>& t) {
    return glm::vec3(std::get<0>(t), std::get<1>(t), std::get<2>(t));
}
bool bridge_finite3(const glm::vec3& a) {
    return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z);
}

// One light's per-state probe-capture data (spec 2026-10-17 §4.1): five
// LINEAR colours in state order (what the base probe of each state sees),
// the animation layer each state's member belongs to (-1 = none) and the
// at-peak colour it adds to that layer.
struct BridgeCaptureRow {
    glm::vec3 caps[renderer::kBridgeStates] = {};
    int layers[renderer::kBridgeStates] = {-1, -1, -1, -1, -1};
    glm::vec3 layer_rgbs[renderer::kBridgeStates] = {};
};

using BridgeV3 = std::tuple<float, float, float>;

// Parses one (caps5, layers5, layer_rgbs5) triple, shared by the light rows
// and the glow rows. False on a cast failure or any list not of length 5.
bool parse_bridge_capture_row(py::handle item, BridgeCaptureRow* out) {
    try {
        auto t = item.cast<std::tuple<std::vector<BridgeV3>, std::vector<int>,
                                      std::vector<BridgeV3>>>();
        const auto& caps = std::get<0>(t);
        const auto& layers = std::get<1>(t);
        const auto& rgbs = std::get<2>(t);
        const std::size_t n = static_cast<std::size_t>(renderer::kBridgeStates);
        if (caps.size() != n || layers.size() != n || rgbs.size() != n) return false;
        for (std::size_t i = 0; i < n; ++i) {
            out->caps[i] = bridge_v3(caps[i]);
            out->layers[i] = layers[i];
            out->layer_rgbs[i] = bridge_v3(rgbs[i]);
        }
        return true;
    } catch (const py::cast_error&) {
        return false;
    }
}

// Parses the optional per-light probe-capture rows shared by set_bridge_spots
// and set_bridge_area_lights (spec 2026-10-08-bridge-emitters §11.4 / §16.3,
// 2026-10-17 §4.1): one (caps5, layers5, layer_rgbs5) per light row, in row
// order. Returns an empty vector for None, a cast failure, or a length
// mismatch against `n` -- in every one of those cases the caller's rule is
// "no captures: the probes see the live colour", so an empty return means
// exactly that to both bindings.
std::vector<BridgeCaptureRow> parse_bridge_captures(py::object captures, std::size_t n) {
    std::vector<BridgeCaptureRow> rows;
    if (captures.is_none()) return rows;
    try {
        for (auto item : captures) {
            BridgeCaptureRow r;
            if (!parse_bridge_capture_row(item, &r)) return {};
            rows.push_back(r);
        }
    } catch (const py::error_already_set&) {
        return {};
    }
    if (rows.size() != n) return {};
    return rows;
}

// True when every colour of the row, scaled by `k`, is finite.
bool bridge_capture_finite(const BridgeCaptureRow& r, float k) {
    for (int i = 0; i < renderer::kBridgeStates; ++i)
        if (!bridge_finite3(r.caps[i] * k) || !bridge_finite3(r.layer_rgbs[i] * k)) return false;
    return true;
}

// Copies a parsed row onto a light's capture fields, colours x `k`.
template <typename Light>
void apply_bridge_capture(Light& l, const BridgeCaptureRow& r, float k) {
    l.has_capture = true;
    for (int i = 0; i < renderer::kBridgeStates; ++i) {
        l.capture_radiance[i] = r.caps[i] * k;
        l.layer[i] = r.layers[i];
        l.layer_radiance[i] = r.layer_rgbs[i] * k;
    }
}

// Tracks key state from the previous frame() so key_pressed can detect
// rising edges. Only keys that have been queried via key_pressed appear
// here; lookup misses (key never queried) are treated as "previously up".
std::unordered_map<int, bool> g_prev_key_state;
// One translator for the whole process: the OSR browser is a singleton
// (ui_cef's own statics), so there is exactly one key-capture stream to
// pair. cef_send_text_events feeds every drained frame's events through it
// in order; cef_reset_text_translator forgets held keys at a capture
// boundary (engine/ui/text_capture.py calls it on both focus gain and
// release) so a key still down across that boundary can never emit an
// orphaned KEYUP into a page that never saw its KEYDOWN.
renderer::TextEventTranslator g_text_translator;
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
    float scale,
    bool geosphere,
    bool interior,
    const std::vector<std::string>& sibling_overlay_dirs) {
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

    // Planet geosphere LOD replacement (spec
    // docs/superpowers/specs/2026-10-06-planet-geosphere-design.md): folded
    // into rep_key like scale, so a plain and a geosphere load of the same
    // NIF are distinct cached handles.
    if (geosphere) {
        rep_key += "|geosphere";
    }

    // Interior load flag (spec 2026-10-08-bridge-lighting-baseline-design.md
    // §3): folded into rep_key like geosphere, so a plain and an interior
    // load of the same NIF are distinct cached handles.
    if (interior) {
        rep_key += "|interior";
    }

    // Sibling-overlay search list for the bridge PBR roughness/metalness/
    // normal maps (spec 2026-10-09-bridge-pbr §9.2/§9.3): folded into rep_key
    // like interior, so two loads differing only in this list are distinct
    // cached entries.
    std::vector<std::filesystem::path> overlay_dirs;
    overlay_dirs.reserve(sibling_overlay_dirs.size());
    for (const auto& d : sibling_overlay_dirs) {
        overlay_dirs.emplace_back(d);
        rep_key += "|overlay:" + d;
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
    auto handle = g_cache->load(nif_path, search_paths, replacements, decal_requests, scale, geosphere, interior, overlay_dirs);
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
    g_interp.clear();
    g_interp_drawn.clear();
    g_handover.cancel();
    g_viewscreen_target.reset();
    g_viewscreen_aabb.reset();
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_ambient_scale = 1.0f;
    g_bridge_alert_level = 0;
    g_bridge_quality = renderer::kDefaultBridgeQuality;
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

    // Sixteen per-frame descriptor lists: twelve VFX + four debug volumes.
    g_torpedoes.clear();
    g_phaser_beams.clear();
    g_tractor_beams.clear();
    g_hit_vfx.clear();
    g_shockwaves.clear();
    g_warp_in_flashes.clear();
    g_warp_in_flash_params = renderer::WarpInFlashParams{};
    g_particle_emitters.clear();
    g_dynamic_lights.clear();
    g_lens_flares.clear();
    g_hull_discharges.clear();
    g_running_lights.clear();
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

    // Bridge editor tint: its model handle dies with this session's models.
    g_bridge_highlight = dauntless::BridgeHighlight{};
    // Bridge PBR state (material overrides, spots, probe captures) lives in
    // g_bridge_pass, which is null at BOTH call sites: shutdown() destroys it
    // before calling this, and init() calls this before building a fresh one.
    // So nothing here resets it -- a new session gets a new BridgePass, and
    // a mid-session bridge swap is BridgeRuntime.attach()'s job (it clears
    // and re-pushes). The g_bridge_probe stash is deliberately kept -- see
    // its declaration.

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
    g_rock_specks_enabled = true;
    g_rock_puffs_enabled = true;
    g_puff_field.clear();
    g_puff_field.set_dials({});
    g_rock_puffs_drawn = 0;
    g_speck_band.set_catalogue({}, {});
    g_speck_band.set_sources({});
    g_speck_band.set_dials({});
    g_speck_band.set_near_dials({});
    g_speck_uploaded_version = 0;   // a fresh FarPass: upload whatever the band holds
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
    g_severance_jobs.clear();
    g_loaded_models.clear();
    // ModelHandles are reissued from 1 after every g_loaded_models.clear();
    // drop the renderer's per-handle bounding-radius cache in lockstep or a
    // new model recycled onto an old handle inherits the old model's radius.
    renderer::reset_model_radius_cache();
    g_head_center_cache.clear();
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
    // Everything frame() consumes and Python can push: see reset_frame_state().
    reset_frame_state();
    // Empty after any shutdown(); cleared here too so the two ends agree.
    g_decal_mask_cache.clear();
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_sun_pass = std::make_unique<renderer::SunPass>();
    g_atmosphere_pass = std::make_unique<renderer::AtmospherePass>();
    g_planet_detail = std::make_unique<renderer::planet_detail::PlanetDetailPass>();
    g_dust_pass = std::make_unique<renderer::DustPass>();
    g_minor_pass = std::make_unique<renderer::MinorPass>();
    g_far_pass = std::make_unique<renderer::FarPass>();
    g_far_pass->set_atlas_paths(g_far_atlas_paths);
    g_nebula_pass = std::make_unique<renderer::NebulaPass>();
    g_nebula_volumetric_pass = std::make_unique<renderer::NebulaVolumetricPass>();
    g_system_nebula_pass = std::make_unique<renderer::SystemNebulaPass>();
    g_nebula_godray_pass = std::make_unique<renderer::NebulaGodrayPass>();
    g_shockwave_pass = std::make_unique<renderer::ShockwavePass>();
    g_warp_in_flash_pass = std::make_unique<renderer::WarpInFlashPass>();
    g_shield_pass = std::make_unique<renderer::ShieldPass>();
    g_lens_flare_pass = std::make_unique<renderer::LensFlarePass>();
    g_torpedo_pass = std::make_unique<renderer::TorpedoPass>();
    g_hit_vfx_pass = std::make_unique<renderer::HitVfxPass>();
    g_hull_discharge_pass = std::make_unique<renderer::HullDischargePass>();
    g_running_light_pass = std::make_unique<renderer::RunningLightPass>();
    g_nebula_wake_pass = std::make_unique<renderer::NebulaWakePass>();
    g_particle_pass = std::make_unique<renderer::ParticlePass>();
    g_phaser_pass        = std::make_unique<renderer::PhaserPass>();
    g_hologram_pass      = std::make_unique<renderer::HologramPass>();
    g_cloak_pass         = std::make_unique<renderer::CloakRefractionPass>();
    g_fill_cache         = std::make_unique<renderer::HullFillCache>();
    g_subsystem_pin_pass  = std::make_unique<renderer::SubsystemPinPass>();
    g_debug_volume_pass   = std::make_unique<renderer::DebugVolumePass>();
    g_gizmo_pass          = std::make_unique<renderer::GizmoPass>();
    g_target_reticle_pass = std::make_unique<renderer::TargetReticlePass>();
    g_starmap_pass        = std::make_unique<renderer::StarMapPass>();
    g_bridge_pass         = std::make_unique<renderer::BridgePass>();
    g_bridge_pass->set_ao_settings(renderer::ao_settings_for(g_bridge_quality));
    g_bridge_pass->set_ao_tuning(g_bridge_ao_tuning);
    g_bridge_pass->set_highlight(g_bridge_highlight.model,
                                 g_bridge_highlight.selected,
                                 g_bridge_highlight.hover);
    g_bridge_pass->set_alert_ambient_scale(g_bridge_ambient_scale);
    g_bridge_pass->set_alert_level(g_bridge_alert_level);
    g_bridge_pass->set_probe_origin(g_bridge_probe.origin);
    g_bridge_pass->set_probe_scales(g_bridge_probe.scales);
    if (g_bridge_probe.capture_pending) g_bridge_pass->request_probe_capture();
    g_bridge_probe.capture_pending = false;
    g_viewscreen_static_pass = std::make_unique<renderer::ViewscreenStaticPass>();
    g_viewscreen_bars_pass = std::make_unique<renderer::ViewscreenBarsPass>();
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
    // Release the session-scoped collision-scuff normal map
    // (renderer/scuff_texture.h) while this context is still current;
    // otherwise its id leaks into the next init()'s context and collides with
    // a texture of another type there (GL_INVALID_OPERATION).
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
    g_head_center_cache.clear();
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_severance_jobs.clear();
    g_backdrop_pass.reset();  // releases sphere + texture caches while the
                              // GL context is still alive.
    g_sun_pass.reset();
    g_atmosphere_pass.reset();   // releases the shell mesh (GL alive)
    g_planet_detail.reset();     // releases the clipmap atlas (GL alive)
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
    g_warp_in_flash_pass.reset();
    g_hit_vfx_pass.reset();
    g_hull_discharge_pass.reset();
    g_running_light_pass.reset();
    g_nebula_wake_pass.reset();
    g_particle_pass.reset();
    g_phaser_pass.reset();
    g_hologram_pass.reset();
    g_cloak_pass.reset();
    g_fill_cache.reset();    // releases the hull fill 3D textures (GL alive)
    g_subsystem_pin_pass.reset();
    g_debug_volume_pass.reset();
    g_gizmo_pass.reset();
    g_target_reticle_pass.reset();
    g_starmap_pass.reset();
    g_bridge_pass.reset();
    g_viewscreen_static_pass.reset();
    g_viewscreen_bars_pass.reset();
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

// The viewscreen feed height wanted this frame: the viewscreen mesh's
// on-screen footprint through the bridge camera at fw x fh. nullopt when no
// viewscreen mesh is drawn or none of it is on screen, so the sizer keeps
// the size it has.
std::optional<int> viewscreen_wanted_height(int fw, int fh) {
    if (!g_bridge_pass || fw <= 0 || fh <= 0) return std::nullopt;
    const unsigned long long handle = g_bridge_pass->viewscreen_model();
    if (handle == 0) return std::nullopt;
    if (!g_viewscreen_aabb || g_viewscreen_aabb->first != handle) {
        const assets::Model* m = resolve_model(handle);
        if (m == nullptr) return std::nullopt;
        g_viewscreen_aabb.emplace(handle, renderer::compute_model_aabb(*m));
    }
    const renderer::Aabb& box = g_viewscreen_aabb->second;
    scenegraph::Camera cam = g_bridge_camera;
    cam.aspect = static_cast<float>(fw) / static_cast<float>(fh);
    const glm::mat4 view_proj = cam.proj_matrix() * cam.view_matrix();
    std::optional<renderer::viewscreen_rtt::PixelExtent> px;
    g_world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            if (inst.model_handle != handle) return;
            const auto e = renderer::viewscreen_rtt::projected_extent_px(
                view_proj, inst.world, box.center - box.half_extents,
                box.center + box.half_extents, fw, fh);
            if (!e) return;
            if (!px) px = e;
            else px = renderer::viewscreen_rtt::PixelExtent{
                std::max(px->w, e->w), std::max(px->h, e->h)};
        });
    if (!px) return std::nullopt;
    return renderer::viewscreen_rtt::height_for_extent(*px);
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
// origin + render position + the far frame's anchor. A player that vanished is not swept from its last pose
// (NearField::step resets the sweep on an unset player).
void step_near_field() {
    const auto player = player_box_of(g_near_player);
    const glm::dvec3 to_sys = g_world.render_origin() + g_far_field.anchor();
    const glm::dvec3 centre_render = player
        ? glm::dvec3(player->world * glm::vec4(player->center_mu, 1.0f))
        : glm::dvec3(g_camera.eye);
    g_near_field.stream(centre_render + to_sys);
    if (g_rock_specks_enabled)
        g_speck_band.stream(centre_render + to_sys, g_near_field.dials().dash_collapse_step_gu);
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
        g_shadow_hull_stats = renderer::HullDrawStats{};
        if (g_submitter) g_submitter->reset_opaque_stats();
        g_near_meshes = 0;
        g_near_billboards = 0;
        g_near_fading = 0;
        g_rock_specks_drawn = 0;
        g_rock_puffs_drawn = 0;
        if (g_minors_enabled) {
            DAUNTLESS_FRAME_SCOPE("space.minors.step");
            step_minor_field(static_cast<float>(fh));
        }
        if (g_far_enabled) {
            DAUNTLESS_FRAME_SCOPE("rock.near.stream");
            step_near_field();
        }
    }

    const bool bridge_active = !viewer_mode && g_bridge_pass_enabled && g_bridge_pass;
    const bool viewscreen_on = bridge_active && g_viewscreen_enabled;

    {
        DAUNTLESS_FRAME_SCOPE("anim");
        g_world.propagate();
        // SP2: rebuild each animated instance's bone palette for this frame BEFORE
        // anything consumes it (the space skinned draw and the bridge pass). Shares
        // the `now` wall clock with draw_model / flip controllers.
        //
        // Only for instances a pass draws THIS frame: in the exterior view the
        // crew and every realized comm set's faces are not drawn, and re-posing
        // them cost a flat ~1.5 ms a frame (Debug). The draws below must stay in
        // step with these flags: the bridge pass runs iff bridge_active, a comm
        // set only through the viewscreen's comm feed.
        renderer::DrawnPasses drawn;
        drawn.bridge = bridge_active;
        drawn.comm = viewscreen_on && g_comm_source.active;
        drawn.comm_set_id = g_comm_source.set_id;
        {
            DAUNTLESS_FRAME_SCOPE("anim.skin");
            renderer::update_animations(g_world, lookup, now, drawn);
        }
        {
            DAUNTLESS_FRAME_SCOPE("anim.node_clips");
            update_bridge_node_anims(now);
        }
    }

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
    // This is a CPU saving, not a fill saving. The RTT is small (footprint-sized), but
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
        // sized this frame (g_viewscreen_rtt_sizer); the main view (plain or
        // MSAA) is fw x fh.
        const bool to_viewscreen = hdr != nullptr && hdr == g_viewscreen_hdr.get();
        // Which hulls get rooms behind their holes in THIS render: on the
        // viewscreen only its target; the main view by distance (the default).
        if (g_submitter) {
            renderer::InteriorPolicy interior_policy;
            interior_policy.near_gu = g_interior_near_gu;
            if (to_viewscreen) {
                interior_policy.viewscreen = true;
                interior_policy.viewscreen_target = g_viewscreen_target;
            }
            g_submitter->set_interior_policy(interior_policy);
        }
        const float target_h = to_viewscreen ? static_cast<float>(hdr->height())
                                             : static_cast<float>(fh);
        const int target_w = to_viewscreen ? hdr->width() : fw;
        // Instance::rim_strength's 0.1 default, gated + scaled as
        // FrameSubmitter does for every opaque instance (minors + impostors).
        const float rim = dauntless_rim::enabled()
            ? 0.1f * dauntless_rim::strength_scale() : 0.0f;
        if (g_far_pass) g_far_pass->reset_counts();
        // The translucent lists are drawn by render_space_vfx (rock.fade.draw)
        // for THIS camera: never replay a list a skipped build left behind.
        g_near_out.billboards_fading.clear();
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
            // The hull draw. Hulls wholly outside THIS camera's frustum are
            // skipped (phase 5a, renderer/hull_cull.h; DAUNTLESS_HULL_CULL=0
            // submits every one); no distance cull. The profiler's `hulls:`
            // line shows drawn vs culled against this scope's cost.
            DAUNTLESS_FRAME_SCOPE("space.opaque");
            g_submitter->submit_opaque_in_pass(
                g_world, cam, *g_pipeline, lookup, g_lighting,
                scenegraph::Pass::Space, g_decal_game_time,
                ambient_scale, dyn_lights, &g_suns, g_planet_detail.get());
        }
        // Minor rocks. The step culled against g_camera; this target may be
        // the bridge viewscreen RTT (its own camera and size) --
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
            {
                DAUNTLESS_FRAME_SCOPE("rock.near.build");
                g_near_field.build(in, g_near_out);
            }
            {
                DAUNTLESS_FRAME_SCOPE("rock.near.mesh_draw");
                g_minor_pass->render(near_fragment, g_near_out.meshes, cam, *g_pipeline,
                                     [](std::uint64_t h) { return resolve_model(h); },
                                     g_lighting, ambient_scale, rim);
            }
            g_far_draw_calls += g_minor_pass->last_draw_calls();
            {
                DAUNTLESS_FRAME_SCOPE("rock.impostor.draw");
                g_far_pass->render_impostors(g_near_out.billboards, cam, *g_pipeline, g_lighting,
                                             ambient_scale, rim);
            }
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
        if (g_far_enabled && g_far_pass) {
            DAUNTLESS_FRAME_SCOPE("space.far.impostors");
            g_far_pass->render_impostors(g_far_out.impostors, cam, *g_pipeline, g_lighting,
                                         ambient_scale, rim);
        }
        // Hull interior under the plating tear: stencil-marks where the hull is
        // cut through and draws the deck-and-room interior there. One marking
        // draw plus one interior draw per hull that can tear; nothing
        // otherwise. Both are issued inside this scope, so the marking draw's
        // cost is part of space.hull_interior, not space.opaque.
        if (g_submitter && g_fill_cache) {
            DAUNTLESS_FRAME_SCOPE("space.hull_interior");
            g_submitter->submit_plating_interior(g_world, cam, *g_pipeline, lookup,
                                                 g_fill_cache.get(), g_lighting,
                                                 ambient_scale, g_decal_game_time);
        }
        // Far + minor specks in ONE instanced draw, after every opaque writer
        // (hull, minors, impostors, hull interior) so they depth-test against all of
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
        // Puffs: soft lit billboards, depth-tested in the MSAA pass so
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
        // Speck band: one instanced draw, radius + alpha on the GPU.
        // Phase 1, after every opaque writer AND the puffs: a speck writes no
        // depth, so drawn first every puff blended over it, nearer or not.
        if (g_far_enabled && g_far_pass && g_rock_specks_enabled && !g_speck_band.hidden()) {
            DAUNTLESS_FRAME_SCOPE("rock.specks.draw");
            if (g_speck_band.version() != g_speck_uploaded_version) {
                g_far_pass->upload_rock_specks(g_speck_band.instances());
                g_speck_uploaded_version = g_speck_band.version();
            }
            renderer::FarPass::RockSpeckDraw d;
            d.offset = glm::vec3(g_speck_band.origin_sys() -
                                 (g_world.render_origin() + g_far_field.anchor()));
            d.in_gu = g_near_field.effective_dials().large.billboard_gu;
            d.in_fade_gu = g_near_field.effective_dials().fade_gu;
            const auto& sd = g_speck_band.dials();
            d.out_gu = sd.out_gu;
            d.out_fade_gu = sd.out_fade_gu;
            d.keep_d0_gu = renderer::rockfield::speck_keep_d0(sd, d.in_gu, d.in_fade_gu);
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
        // Planet atmosphere shells: first in phase 2, additive, depth test
        // off, the march ended by this target's resolved depth (plan
        // deviation D1). Draws nothing -- and touches no GL state -- unless
        // an instance has an enabled atmosphere on a sphere-mapped model.
        if (g_atmosphere_pass) {
            DAUNTLESS_FRAME_SCOPE("space.atmosphere");
            g_atmosphere_pass->render(g_world, cam, *g_pipeline, lookup, g_lighting,
                                      g_suns, target.depth_texture(),
                                      target.width(), target.height());   // gl_FragCoord space
        }
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
        // Rock fade (2026-10-03): the near impostors fading in from
        // (or out to) nothing, TRANSLUCENT, built for THIS camera by
        // render_space_geometry. Here in phase 2, into the resolved
        // single-sample target against its depth (depth test on, no depth
        // writes, premultiplied). Every phase-1 writer (hull, rocks, impostors, breach, specks,
        // shields) is underneath; dust (drawn above) is attenuated where a
        // fading rock lies behind it (accepted). No MSAA (accepted). The list
        // is already sorted far to near by its build. Leaves blending off,
        // depth test/writes on.
        if (g_far_enabled && g_far_pass) {
            DAUNTLESS_FRAME_SCOPE("rock.fade.draw");
            g_far_pass->reset_counts();
            const float rim = dauntless_rim::enabled()
                ? 0.1f * dauntless_rim::strength_scale() : 0.0f;   // as render_space_geometry
            g_far_pass->render_impostors_blended(g_near_out.billboards_fading, cam, *g_pipeline,
                                                 g_lighting, ambient_scale, rim);
            g_far_draw_calls += g_far_pass->last_draw_calls();
        }
        // System-scale nebula: follows the Volumetric Nebulae setting. With it
        // off (or no profile pushed) the legacy branch runs.
        const renderer::NebulaDrawPlan neb_plan = renderer::plan_nebula_draws(
            dauntless_volumetric_nebulae::enabled(),
            g_system_nebula_pass && g_system_nebula_pass->has_profile(),
            !g_nebulae.empty(), !g_nebula_wake.empty());
        if (neb_plan.system && g_system_nebula_pass) {
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
                                         target.color_texture(),
                                         target.depth_texture());
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
        if (g_running_lights_enabled && g_running_light_pass && g_running_lights.size() > 0) {
            DAUNTLESS_FRAME_SCOPE("space.running_lights");
            const auto sprites = g_running_lights.build_sprites(
                g_world, g_decal_game_time, g_running_light_dials,
                cam.eye, cam.proj_matrix()[1][1], vh);
            g_running_light_pass->render(cam, *g_pipeline, sprites);
        }
        if (dauntless_nebula_lightning::enabled()
                && g_hull_discharge_pass && !g_hull_discharges.empty())
            g_hull_discharge_pass->render(cam, *g_pipeline, g_hull_discharges);
        if (g_shockwave_pass)
            g_shockwave_pass->render(cam, g_shockwaves, *g_pipeline);
        if (g_warp_in_flash_pass)
            g_warp_in_flash_pass->render(cam, g_warp_in_flashes,
                                         g_warp_in_flash_params, *g_pipeline);
        // Venting jets: build per-frame descriptors from active breach events
        // and append to a combined emitter list for the particle pass.
        // Never mutate g_particle_emitters in place (Python-owned).
        if (g_particle_pass) {
            DAUNTLESS_FRAME_SCOPE("space.particles");
            std::vector<renderer::ParticleEmitterDescriptor> all_emitters = g_particle_emitters;
            // Venting jets and debris for every instance with live breach
            // events; an instance with none builds nothing.
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
        // The focus: the hull nearest the camera target, its radius from the
        // per-model cache (an uncached compute_model_aabb here walked every
        // vertex of each nearer hull, every frame: ~3 ms at 17 ships, Debug).
        renderer::frame_timer().push("shadow.fit");
        const renderer::ShadowFocus sf =
            renderer::pick_shadow_focus(g_world, g_camera.target, lookup);
        renderer::frame_timer().pop();
        const scenegraph::Instance* player = sf.instance;
        const float player_radius_gu = sf.radius_gu;

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
            renderer::submit_shadow_depth(g_world, sl, *g_pipeline, lookup,
                                          &g_shadow_hull_stats);
            glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));

            renderer::set_active_shadow(sl, g_shadow_target->depth_texture(), true);
        } else {
            renderer::set_active_shadow({}, 0, false);
        }
    } else {
        renderer::set_active_shadow({}, 0, false);
    }

    // ── Planet surface detail (spec 2026-10-08 §5.5) ───────────────────────
    // Top-level (GPU-timed), main camera only: pick the target planet and bake
    // this frame's budgeted strips BEFORE any space render samples them. Every
    // space render (main view, viewscreen RTT) samples the same clipmap; none
    // of them bakes. Skipped when no space scene is drawn at all.
    if (g_planet_detail && !viewer_mode && (!bridge_active || viewscreen_on)) {
        DAUNTLESS_FRAME_SCOPE("planet_detail");
        g_planet_detail->update(g_world, g_camera, fh, lookup);
    }

    // ── Bridge Lottie panels (spec 2026-10-28-bridge-lottie-panels §6-7) ────
    // Once per frame, before ANY bridge render (the viewscreen's comm set
    // below, the main bridge later): upload the frames the worker finished
    // and queue the next ones for the panels last frame drew. Never waits on
    // a raster; a bridge with no panel files does nothing here.
    if (g_bridge_pass) {
        DAUNTLESS_FRAME_SCOPE("bridge_lottie");
        g_bridge_pass->update_panels(g_bridge_quality);
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
        // Sized to the viewscreen's on-screen footprint (see
        // viewscreen_wanted_height); held while it is off screen.
        const int vs_h = g_viewscreen_rtt_sizer.update(
            viewscreen_wanted_height(fw, fh), now);
        const int vs_w = renderer::viewscreen_rtt::width_for_height(vs_h);
        g_viewscreen_hdr->resize(vs_w, vs_h);
        g_viewscreen_hdr->bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        if (g_comm_source.active && g_bridge_pass) {
            scenegraph::Camera ccam = g_comm_source.cam;
            ccam.aspect = static_cast<float>(vs_w)
                        / static_cast<float>(vs_h);
            g_bridge_pass->render(g_world, ccam, *g_pipeline, lookup,
                                  g_bridge_lighting, scenegraph::Pass::Comm,
                                  g_comm_source.set_id);
        } else if (g_scene_source.active) {
            scenegraph::Camera scam = g_scene_source.cam;
            scam.aspect = static_cast<float>(vs_w)
                        / static_cast<float>(vs_h);
            // The viewscreen RTT is deliberately never multisampled: it is a
            // small in-world surface where edge quality barely reads.
            const float vs_ambient = dauntless_filmic::ambient_scale();
            render_space_geometry(scam, g_viewscreen_hdr.get(), nullptr,
                                  vs_ambient, /*dyn_lights=*/nullptr);
            render_space_vfx(scam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        vs_w, vs_h, vs_ambient);
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(vs_w)
                        / static_cast<float>(vs_h);
            const float vs_ambient = dauntless_filmic::ambient_scale();
            render_space_geometry(vcam, g_viewscreen_hdr.get(), nullptr,
                                  vs_ambient, /*dyn_lights=*/nullptr);
            render_space_vfx(vcam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        vs_w, vs_h, vs_ambient);
        }
        // Static/"snow" overlay over the feed (degraded-signal hail look).
        if (g_viewscreen_static.on && g_viewscreen_static_pass
                && g_viewscreen_static_pass->has_textures()) {
            g_viewscreen_static_pass->render(
                g_pipeline->viewscreen_static_shader(),
                g_viewscreen_static.intensity, now);
        }
        // Target readout (dot + name, detail line): scene (target) feed only,
        // over the static.
        // The space passes above may have changed the viewport; restore the RTT's.
        if (!g_comm_source.active && g_scene_source.active
                && g_viewscreen_bars.visible && g_viewscreen_bars_pass) {
            g_viewscreen_hdr->bind();
            glViewport(0, 0, vs_w, vs_h);
            g_viewscreen_bars_pass->ensure_font(renderer::project_asset_root());
            g_viewscreen_bars_pass->render(
                g_pipeline->viewscreen_bars_shader(), g_viewscreen_bars,
                vs_w, vs_h);
        }
        g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
    } else if (g_bridge_pass) {
        // Off -> the bridge pass falls back to the SDK's SetOffTexture image
        // (the mission loading screen), or to the NIF material if none is set.
        g_bridge_pass->set_viewscreen_texture(0);
    }

    // ── Main HDR target ────────────────────────────────────────────────────
    {
        DAUNTLESS_FRAME_SCOPE("hdr.clear");
        g_hdr_target->resize(fw, fh);
        g_hdr_target->bind();   // sets viewport to fw x fh
        if (viewer_mode) {
            glClearColor(g_hologram_bg.r, g_hologram_bg.g, g_hologram_bg.b, 1.0f);
        } else {
            glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
        }
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    }
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
                g_lighting, g_decal_game_time, &g_dynamic_lights);
        } else if (g_hologram_pass) {
            g_hologram_pass->render(g_hologram_ship, g_world, g_camera,
                                    *g_pipeline, lookup);
        }
    }
    if (viewer_mode && g_hologram_ship.active && g_running_lights_enabled
            && g_running_light_pass) {
        // The viewer freezes the sim, so blink on wall-clock time. Lights are
        // forced fully on (no power-plant state in the viewer). The hologram
        // pass writes no depth: in hull mode the opaque hull did, so keep the
        // pass's depth test; otherwise test nothing (like the pins).
        static const auto t0 = std::chrono::steady_clock::now();
        const float t = std::chrono::duration<float>(
            std::chrono::steady_clock::now() - t0).count();
        const auto sprites = g_running_lights.build_sprites_for(
            g_hologram_ship.instance, g_world, t, g_running_light_dials,
            g_camera.eye, g_camera.proj_matrix()[1][1], fh, 1.0f);
        g_running_light_pass->render(g_camera, *g_pipeline, sprites,
                                     /*depth_test=*/g_spv_hull_mode);
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
        DAUNTLESS_FRAME_SCOPE("pins");
        // Device-pixel ratio = framebuffer / logical window height, so pins
        // keep a constant apparent size on HiDPI/Retina displays.
        int fb_w = 0, fb_h = 0, win_w = 0, win_h = 0;
        g_window->framebuffer_size(&fb_w, &fb_h);
        g_window->window_size(&win_w, &win_h);
        const float dsf = (win_h > 0) ? static_cast<float>(fb_h) / static_cast<float>(win_h) : 1.0f;
        g_subsystem_pin_pass->render(g_subsystem_pins, g_camera, *g_pipeline, dsf);
    }
    if (g_target_reticle_pass && g_target_reticle.visible) {
        DAUNTLESS_FRAME_SCOPE("reticle");
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
        // The alert-level ambient scale applies to the interior render only;
        // the comm-set RTT above uses the unscaled g_bridge_lighting so the viewscreen
        // feed's brightness stays constant across alert levels.
        // UNSCALED: the pass applies the alert scale to the main view itself
        // (set_alert_ambient_scale), so its probe captures stay unscaled.
        g_bridge_pass->render(g_world, g_bridge_camera, *g_pipeline,
                              lookup, g_bridge_lighting);
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
        DAUNTLESS_FRAME_SCOPE("lens_flare");
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
        // Through the gate, like every other key read: a raw glfwGetKey here
        // would make prev disagree with key_pressed's gated `now`.
        prev = g_window->key_state(k);
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
        // By default the composite uploads the ENTIRE CEF surface every
        // frame — no dirty-rect, no PBO. At 2560x1440 BGRA that is ~14.7 MB
        // of glTexSubImage2D per frame. Upload and draw are timed separately
        // because the upload is where the CPU appears to wait for the GPU
        // (docs/reference/engine/perf-register.md, A-1); DAUNTLESS_CEF_UPLOAD switches
        // the upload policy for that experiment.
        DAUNTLESS_FRAME_SCOPE("cef.composite");
        {
            DAUNTLESS_FRAME_SCOPE("cef.upload");
            dauntless::ui_cef::composite_upload();
        }
        {
            DAUNTLESS_FRAME_SCOPE("cef.draw");
            dauntless::ui_cef::composite_draw();
        }
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

    // A requested frame PNG (request_frame_png): the finished frame, overlay
    // included, read from the back buffer before the swap makes it undefined.
    if (!g_frame_png_path.empty()) {
        if (dauntless::dump_default_framebuffer_png(g_frame_png_path, fw, fh))
            std::fprintf(stderr, "[frame-png] wrote %s (%dx%d)\n",
                         g_frame_png_path.c_str(), fw, fh);
        else
            std::fprintf(stderr, "[frame-png] FAILED to write %s\n",
                         g_frame_png_path.c_str());
        g_frame_png_path.clear();
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
// SPIKE (damage redesign): hull-plating layer params. Defined in frame.cc.
namespace dauntless_plating {
    extern float g_params[renderer::plating::kParamCount];
    const float* param_defaults();  // kParamCount shipped values, never written
}

// Surface tear that first crosses the breach wear pushes ONE BreachEvent
// (venting + debris readers); Internal blasts already call breach_burst.
static std::uint64_t next_breach_seed() {
    static std::uint64_t s_counter = 0;
    return ++s_counter * 6364136223846793005ull;
}
// The record is in its node's REST frame; `rest_to_posed` (the inverse of
// that node's rest fix, identity for the body) puts the event back where the
// part is DRAWN now: venting is placed through the instance world, i.e. in the
// posed body frame. The event does not follow the part afterwards. The molten
// rim does: it is drawn from the record's node and REST centre, which the
// event carries too (BreachEvent::node / center_rest).
static void vent_on_breach_crossing(scenegraph::Instance& inst,
                                    const scenegraph::HullDamageAddResult& r,
                                    std::uint32_t kind, const glm::mat4& rest_to_posed) {
    if (kind != 1u || r.index < 0) return;
    const float breach = dauntless_plating::g_params[16];
    if (!(r.wear_before < breach && breach <= r.wear_after)) return;
    const auto& rec = inst.hull_damage.records()[static_cast<std::size_t>(r.index)];
    inst.breach_events.push(glm::vec3(rest_to_posed * glm::vec4(rec.centre_body, 1.0f)),
                            0.5f * rec.reach,
                            glm::mat3(rest_to_posed) * rec.normal_body,
                            g_decal_game_time, next_breach_seed(),
                            rec.node, rec.centre_body);
}

// The node a wear hit is recorded on, and the map from the POSED body frame
// into that node's REST frame (layered damage phase 4 §2.1), found by
// GEOMETRY (renderer::attribute_to_rest_frame: the nearest rest triangle
// under each part's rest correction). An unposed instance (no node
// overrides) that is not rigged is the body with no work at all. `rest_frame`
// -- a point the writer already holds in the rest frame (authored DamageTool
// volumes) -- and any point on a RIGGED instance at the identity pose are
// attributed in REST space (renderer::attribute_rest_point: the nearest rest
// triangle's own node) and never converted. On a rigged instance in a
// partial pose, a hit on a chain with no override also takes its triangle's
// own node (Ruling 7).
struct WearNode {
    int       node = -1;
    glm::mat4 to_rest{1.0f};
    glm::mat4 to_posed{1.0f};
};
// `posed_point`: the body-frame point as given (rest-frame when rest_frame).
static WearNode wear_node_for(const scenegraph::Instance& inst, const glm::vec3& posed_point,
                              bool rest_frame) {
    WearNode w;
    // Unposed and unrigged: the body, with no work at all.
    if (!rest_frame && inst.node_overrides.empty() && !inst.rigged) return w;
    const assets::Model* m = resolve_model(inst.model_handle);
    if (m == nullptr) return w;
    // A rigged hull at the identity pose (no overrides): posed == rest, so
    // the rest-space answer is exact -- and it keeps the hit on its part's
    // own node for when the part swings later.
    if (rest_frame || inst.node_overrides.empty()) {
        w.node = renderer::attribute_rest_point(*m, inst.node_overrides, posed_point).node;
        return w;                                // identity both ways
    }
    const renderer::RestAttribution a =
        renderer::attribute_to_rest_frame(*m, inst.node_overrides, posed_point);
    // A rigged hull in a PARTIAL pose (Ruling 7): a hit on a part whose chain
    // has no override right now (owner -1, so posed == rest there and to_rest
    // is identity) is filed on the struck triangle's own node, exactly as at
    // the identity pose above, so it stays on the part when the part swings.
    // An unrigged (SPV-posed) hull keeps the body.
    w.node = (a.node < 0 && inst.rigged) ? a.own_node : a.node;
    w.to_rest = a.to_rest;
    w.to_posed = glm::inverse(a.to_rest);
    return w;
}



/// The dict -> (profile, look) parse shared by set_system_nebula_profile,
/// system_nebula_prebuild and system_nebula_prebuilt, so all three key the
/// table cache identically. Throws ValueError on mismatched rows.
static std::pair<renderer::atmosphere::RadialProfile,
                 renderer::atmosphere::LookParams>
parse_system_nebula_profile(const py::dict& d) {
    renderer::atmosphere::RadialProfile p;
    p.r = d["r"].cast<std::vector<float>>();
    p.nebula = d["nebula"].cast<std::vector<float>>();
    if (p.r.empty() || p.r.size() != p.nebula.size())
        throw py::value_error(
            "system nebula profile: 'r' and 'nebula' must be "
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
    return {std::move(p), look};
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

/// Block-array index of the NiNode whose child_links resolves to `idx`, or
/// npos if `idx` is unparented. Mirrors mesh_fix.cc's local parent_of (not
/// exported); nif_shapes needs its own copy for the ancestor texture walk.
std::size_t nif_shapes_parent_of(const nif::File& file, std::size_t idx) {
    for (std::size_t i = 0; i < file.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&file.blocks[i]);
        if (!node) continue;
        for (std::uint32_t link : node->child_links)
            if (nif_shapes_index_of(file, link) == idx) return i;
    }
    return std::string::npos;
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


/// The NiImage link `tp` draws as its static Base: its own image_link, or --
/// when that is 0 and its controller is a NiFlipController (BC's stock
/// EBridge authoring, and the mesh-fix flipbook op) -- the controller's
/// source 0, mirroring model_build.cc's flip_image_override_for_prop.
std::uint32_t nif_shapes_property_image(const nif::File& file,
                                        const nif::NiTextureProperty& tp) {
    if (tp.image_link != 0 || tp.obj.controller_link == 0) return tp.image_link;
    std::size_t idx = nif_shapes_index_of(file, tp.obj.controller_link);
    if (idx == std::string::npos || idx >= file.blocks.size()) return 0;
    const auto* ctrl = std::get_if<nif::NiFlipController>(&file.blocks[idx]);
    return ctrl && !ctrl->image_links.empty() ? ctrl->image_links[0] : 0;
}

/// The loader's own parse + fix path, in memory (shared by nif_shapes and
/// set_smoothing_report). None-equivalent: returns false when the file is
/// missing or unparsable; throws on a fix parse failure or refusal.
bool load_nif_with_fix(const std::string& nif_abs_path,
                       const std::optional<std::string>& fix_json, nif::File* out) {
    std::filesystem::path path = nif_abs_path;
    if (!std::filesystem::exists(path)) return false;
    try {
        *out = nif::load(path);
    } catch (const std::exception&) {
        return false;
    }
    if (fix_json) {
        std::string err;
        auto fix = assets::parse_mesh_fix(*fix_json, &err);
        if (!fix) throw std::runtime_error("mesh fix parse failed: " + err);
        err = assets::apply_mesh_fix(*out, *fix);
        if (!err.empty()) throw std::runtime_error("mesh fix refused: " + err);
    }
    return true;
}

}  // namespace

py::object set_smoothing_report_impl(const std::string& nif_abs_path,
                                     const std::string& fix_json) {
    nif::File f;
    if (!load_nif_with_fix(nif_abs_path, fix_json, &f)) return py::none();
    py::list out;
    for (const auto& r : assets::probe_smoothing(f)) {
        py::dict d;
        d["block"] = r.block;
        d["a"] = r.a;
        d["b"] = r.b;
        d["found"] = r.found;
        d["joined_a"] = r.joined_a;
        d["joined_b"] = r.joined_b;
        out.append(std::move(d));
    }
    return std::move(out);
}

// Read-only geometry dump for the mesh-fix generator (tools/gen_mesh_fixes.py):
// one dict per NiTriShape, in block order, with world-space vertices/normals,
// UV set 0, triangles, texture basenames and the hidden flag. Parse-only, no
// GL context, and applies no mesh fix -- callers see the raw stock geometry.
py::object nif_shapes_impl(const std::string& nif_abs_path,
                           const std::optional<std::string>& fix_json) {
    nif::File f;
    // The loader's own path (AssetCache::load), in memory: lets the
    // shape-diff tool verify a fix before it is written.
    if (!load_nif_with_fix(nif_abs_path, fix_json, &f)) return py::none();

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
                nif_shapes_collect_image(f, nif_shapes_property_image(f, *tp), &textures);
            } else if (const auto* mtp = std::get_if<nif::NiMultiTextureProperty>(&b)) {
                for (const auto& elem : mtp->elements) {
                    if (elem.has_image) nif_shapes_collect_image(f, elem.image_link, &textures);
                }
            }
        }
        // DBridge's NiTextureProperty sits on an ancestor NiNode, inherited
        // rather than owned by the shape (final-review F1). Mirror the
        // renderer's own ancestor walk (model_build.cc:gather_material_inputs):
        // walk up, nearest ancestor with any texture wins. Never touches
        // `textures` when the shape already has its own (gen_mesh_fixes.py's
        // "ID" lookup and its drift test depend on that).
        if (textures.empty()) {
            std::size_t cur = i;
            while (true) {
                const std::size_t parent_idx = nif_shapes_parent_of(f, cur);
                if (parent_idx == std::string::npos || parent_idx >= f.blocks.size()) break;
                const auto* parent_node = std::get_if<nif::NiNode>(&f.blocks[parent_idx]);
                if (!parent_node) break;
                std::vector<std::string> ancestor_textures;
                for (std::uint32_t link : parent_node->av.property_links) {
                    std::size_t idx = nif_shapes_index_of(f, link);
                    if (idx == std::string::npos || idx >= f.blocks.size()) continue;
                    const auto& b = f.blocks[idx];
                    if (const auto* tp = std::get_if<nif::NiTextureProperty>(&b)) {
                        nif_shapes_collect_image(f, nif_shapes_property_image(f, *tp), &ancestor_textures);
                    } else if (const auto* mtp = std::get_if<nif::NiMultiTextureProperty>(&b)) {
                        for (const auto& elem : mtp->elements) {
                            if (elem.has_image) nif_shapes_collect_image(f, elem.image_link, &ancestor_textures);
                        }
                    }
                }
                if (!ancestor_textures.empty()) { textures = std::move(ancestor_textures); break; }
                cur = parent_idx;
            }
        }
        d["textures"] = textures;

        const nif::NiTriShapeData* data = nullptr;
        std::size_t data_idx = nif_shapes_index_of(f, shape->data_link);
        if (data_idx != std::string::npos && data_idx < f.blocks.size())
            data = std::get_if<nif::NiTriShapeData>(&f.blocks[data_idx]);

        // Parent NiNode name (label only; identity is the block index).
        std::string parent_name;
        for (std::size_t p = 0; p < f.blocks.size() && parent_name.empty(); ++p) {
            const auto* node = std::get_if<nif::NiNode>(&f.blocks[p]);
            if (!node) continue;
            for (std::uint32_t link : node->child_links)
                if (nif_shapes_index_of(f, link) == i) { parent_name = node->av.obj.name; break; }
        }
        d["parent"] = parent_name;
        d["data_block"] = (data_idx != std::string::npos && data_idx < f.blocks.size())
                              ? static_cast<int>(data_idx) : -1;
        {
            const glm::mat4 w = assets::nif_block_world(f, i);
            py::list wl;
            for (int c = 0; c < 4; ++c)
                for (int r = 0; r < 4; ++r) wl.append(w[c][r]);
            d["world"] = wl;
        }

        py::list vertices, normals, uvs, triangles, colors, uvs1;
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
            if (data->has_vertex_colors) {
                for (const auto& c : data->vertex_colors)
                    colors.append(py::make_tuple(c.r, c.g, c.b, c.a));
            }
            if (data->uv_sets.size() >= 2) {
                for (const auto& uv : data->uv_sets[1]) uvs1.append(py::make_tuple(uv.u, uv.v));
            }
        }
        d["vertices"] = vertices;
        d["normals"] = normals;
        d["uvs"] = uvs;
        d["triangles"] = triangles;
        d["colors"] = colors;
        d["uvs1"] = uvs1;
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
    f("shove_lateral", o.shove_lateral);
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
    d["shove_lateral"] = py_float(o.shove_lateral);
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
// Optional (tile fields, 2026-10-02): shape ("disc" | "sphere"),
// procedural, view_space, sphere_radius_gu, sphere_edge_frac -- a missing
// key keeps the DiscSource default (a disc source as before).
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
    // Field noise (every shape, 2026-10-02): omitted = off.
    if (d.contains("noise_scale_gu")) s.noise_scale_gu = d["noise_scale_gu"].cast<float>();
    // Contrast lives in [0, 1] (rock-fields R1): noise_m_bound = 1 + contrast.
    if (d.contains("noise_contrast"))
        s.noise_contrast = std::clamp(d["noise_contrast"].cast<float>(), 0.0f, 1.0f);
    if (d.contains("noise_octaves")) s.noise_octaves = d["noise_octaves"].cast<int>();
    if (d.contains("noise_sharpness")) s.noise_sharpness = std::max(0.0f, d["noise_sharpness"].cast<float>());
    if (d.contains("shape_warp")) s.shape_warp = std::clamp(d["shape_warp"].cast<float>(), 0.0f, 0.9f);
    if (d.contains("shape_warp_scale_gu")) s.shape_warp_scale_gu = d["shape_warp_scale_gu"].cast<float>();
    return s;
}

// An omitted key resets to its default (dials_of's convention).
rf::FarDials far_dials_of(const py::dict& d) {
    rf::FarDials o;
    auto f = [&](const char* k, float& v) { if (d.contains(k)) v = d[k].cast<float>(); };
    f("imp_hi", o.tiers.imp_hi);
    f("imp_lo", o.tiers.imp_lo);
    f("speck_hi", o.tiers.speck_hi);
    f("speck_lo", o.tiers.speck_lo);
    f("p_min", o.tiers.p_min);
    f("speck_gain", o.speck_gain);
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
    f("near_tumble_scale", o.tumble_scale);
    f("large_ramp_lo", o.large_ramp_lo);
    f("large_ramp_hi", o.large_ramp_hi);
    f("near_dash_collapse_step_gu", o.dash_collapse_step_gu);
    f("near_large_min_px", o.large_min_px);
    f("near_small_min_px", o.small_min_px);
    f("near_stream_margin_gu", o.stream_margin_gu);
    f("collide_cooldown_s", o.collide_cooldown_s);
    return o;
}

// The speck band's keys of the same dict (far_dials.py speck_*).
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

// The puffs' keys of the same dict (far_dials.py puff_*).
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
    if (d.contains("puff_belt_count")) o.belt_count = std::clamp(d["puff_belt_count"].cast<int>(), 0, 50000);
    f("puff_belt_size_h", o.belt_size_h);
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

// ── Planet surface-detail type table: Python <-> TypeParams (spec 2026-10-08
// §7 dev tuning). get/set each hand-list the same 16 field names side by
// side, in the same order -- NOT one genuinely shared table, so nothing
// here stops them drifting apart on their own; what actually guards that is
// tests/unit/test_planet_surface_type_params_binding.py's
// test_get_set_round_trip_for_every_type (fix round 1, M1).
// `ridged` is included (the binding is a generic struct accessor) even
// though the "surface" dial group never dials it.
py::dict type_params_to_dict(const renderer::planet_detail::TypeParams& p) {
    py::dict d;
    d["base_wavelength_gu"] = p.base_wavelength_gu;
    d["max_octaves"] = p.max_octaves;
    d["gain"] = p.gain;
    d["ridged"] = p.ridged;
    d["amplitude"] = p.amplitude;
    d["bump"] = p.bump;
    d["albedo"] = p.albedo;
    d["roughness"] = p.roughness;
    d["roughness_var"] = p.roughness_var;
    d["crack_width"] = p.crack_width;
    d["stretch"] = p.stretch;
    d["warp"] = p.warp;
    d["gas_rate_gups"] = p.gas_rate_gups;
    d["gas_period_s"] = p.gas_period_s;
    d["coast_k"] = p.coast_k;
    d["coast_a"] = p.coast_a;
    return d;
}

void apply_type_params_from_dict(renderer::planet_detail::TypeParams& p, const py::dict& params) {
    for (auto item : params) {
        const std::string key = item.first.cast<std::string>();
        const float v = item.second.cast<float>();
        if (key == "base_wavelength_gu") p.base_wavelength_gu = v;
        else if (key == "max_octaves") p.max_octaves = static_cast<int>(v);
        else if (key == "gain") p.gain = v;
        else if (key == "ridged") p.ridged = v;
        else if (key == "amplitude") p.amplitude = v;
        else if (key == "bump") p.bump = v;
        else if (key == "albedo") p.albedo = v;
        else if (key == "roughness") p.roughness = v;
        else if (key == "roughness_var") p.roughness_var = v;
        else if (key == "crack_width") p.crack_width = v;
        else if (key == "stretch") p.stretch = v;
        else if (key == "warp") p.warp = v;
        else if (key == "gas_rate_gups") p.gas_rate_gups = v;
        else if (key == "gas_period_s") p.gas_period_s = v;
        else if (key == "coast_k") p.coast_k = v;
        else if (key == "coast_a") p.coast_a = v;
        else throw py::value_error("set_surface_type_params: unknown field '" + key + "'");
    }
}

}  // namespace

namespace {
// Body-frame conversion shared by damage_decal_add and hull_damage_add so the
// two cannot drift: point is INSTANCE-RELATIVE, radius game units -> model
// units (s = |world's X column|, the uniform NIF->world scale).
struct BodyFramePoint {
    glm::vec3 point;
    glm::vec3 normal;
    float     radius_model;
};
// Game units -> model units; also used by hull_damage_add_body, whose point is
// already in the body frame but whose radius is still game units.
// Both read the SIM hit pose: their points are gameplay hit points.
float radius_to_model(const scenegraph::Instance& inst, float radius) {
    const float s = glm::length(hit_pose_of(inst, /*drawn=*/false).linear[0]);
    return (s > 0.0f) ? radius / s : radius;
}
BodyFramePoint to_body_frame(const scenegraph::Instance& inst,
                             const glm::vec3& world_point,
                             const glm::vec3& world_normal, float radius) {
    const glm::mat3 linear = hit_pose_of(inst, /*drawn=*/false).linear;
    return {scenegraph::relative_to_body(linear, world_point),
            scenegraph::dir_to_body(linear, world_normal),
            radius_to_model(inst, radius)};
}
}  // namespace

namespace {

// ── combat_k2_scan_ships ─────────────────────────────────────────────────────
// The K2 driver's per-ship, per-bank clean check before begin
// (native_combat._k2_ship_handles), a C loop over the instance dicts: it runs
// every tick over every bank. Raw CPython calls only, so it stays cheap in a
// Debug build too.
//
// Returns (handles, unclean). Each ship's handle is its __dict__["_nslot"]
// when that is an Object handle (`(h >> kind_shift) == obj_kind`), else -1
// (no row, never checked). A ship with a row is CLEAN when its class is in
// `seen`, its dict holds none of `ship_patches`, and, when it has a
// "_phaser_system" that is not None, that system's class is exactly
// `stock_system` and its dict holds none of `system_patches`, and every bank
// in its "_children" has exactly `stock_bank` as class, holds none of
// `bank_patches`, and has a "_target" that is None or of a class in `seen`.
// Every other ship is in `unclean` as (ship, handle), in order, for
// _k2_python_ship to decide. Anything unexpected (no __dict__, a non-dict
// one, a "_children" that is not a sequence) is "not clean": the Python check
// is the authority, this is its fast path.

// The object's instance dict, borrowed, or nullptr (no error set) when it
// has none. The materialized dict the Python driver's `obj.__dict__` reads.
PyObject* k2_dict_of(PyObject* o) {
    PyObject** dp = _PyObject_GetDictPtr(o);
    if (dp == nullptr) return nullptr;
    PyObject* d = *dp;
    return (d != nullptr && PyDict_CheckExact(d)) ? d : nullptr;
}

// 1: `d` holds one of names[0..n); 0: none; -1: error.
int k2_holds(PyObject* d, PyObject* const* names, Py_ssize_t n) {
    for (Py_ssize_t i = 0; i < n; ++i) {
        const int r = PyDict_Contains(d, names[i]);
        if (r != 0) return r;
    }
    return 0;
}

// 1: type(o) is in `seen`; 0: not; -1: error.
int k2_in_seen(PyObject* seen, PyObject* o) {
    PyObject* t = reinterpret_cast<PyObject*>(Py_TYPE(o));
    return PyAnySet_Check(seen) ? PySet_Contains(seen, t)
                                : PySequence_Contains(seen, t);
}

struct K2ScanNames {
    PyObject* nslot;
    PyObject* system;
    PyObject* children;
    PyObject* target;
};

const K2ScanNames& k2_scan_names() {
    static const K2ScanNames n{PyUnicode_InternFromString("_nslot"),
                               PyUnicode_InternFromString("_phaser_system"),
                               PyUnicode_InternFromString("_children"),
                               PyUnicode_InternFromString("_target")};
    return n;
}

// How many systems and banks k2_scan_ships probed (their instance dict
// against the names) and answered from THE SCAN CACHE.
struct K2ScanCounts {
    std::uint64_t probed = 0, cached = 0;
};

K2ScanCounts& k2_scan_counts() {
    static K2ScanCounts c;
    return c;
}

// 1 clean, 0 not, -1 error: the phaser system `sys` (the scan's ship
// `pos`) and its banks. Defined below, with THE SCAN CACHE.
int k2_clean_system(PyObject* sys, size_t pos, PyObject* seen,
                    PyObject* stock_system, PyObject* stock_bank,
                    PyObject* sys_names, PyObject* bank_names,
                    PyObject* sys_patches, PyObject* bank_patches);

// Is `h` an Object handle: Python's `(h >> kind_shift) == obj_kind`.
// 1 yes, 0 no, -1 error.
int k2_is_object_handle(PyObject* h, PyObject* obj_kind,
                        PyObject* kind_shift) {
    PyObject* s = PyNumber_Rshift(h, kind_shift);
    if (s == nullptr) return -1;
    const int eq = PyObject_RichCompareBool(s, obj_kind, Py_EQ);
    Py_DECREF(s);
    return eq;
}

PyObject* k2_scan_ships(PyObject* ships, PyObject* obj_kind,
                        PyObject* kind_shift, PyObject* seen,
                        PyObject* stock_system, PyObject* stock_bank,
                        PyObject* ship_patches, PyObject* system_patches,
                        PyObject* bank_patches) {
    const K2ScanNames& names = k2_scan_names();
    PyObject* ship_n = PySequence_List(ship_patches);
    PyObject* sys_n = PySequence_List(system_patches);
    PyObject* bank_n = PySequence_List(bank_patches);
    PyObject* seq = PySequence_Fast(ships, "ships must be iterable");
    PyObject* handles = seq ? PyList_New(PySequence_Fast_GET_SIZE(seq))
                            : nullptr;
    PyObject* unclean = PyList_New(0);
    PyObject* none_ref = PyLong_FromLong(-1);
    PyObject* result = nullptr;
    if (ship_n && sys_n && bank_n && seq && handles && unclean && none_ref) {
        const Py_ssize_t n = PySequence_Fast_GET_SIZE(seq);
        PyObject* const* items = PySequence_Fast_ITEMS(seq);
        bool failed = false;
        for (Py_ssize_t i = 0; i < n && !failed; ++i) {
            PyObject* ship = items[i];
            PyObject* d = k2_dict_of(ship);
            PyObject* h = d ? PyDict_GetItemWithError(d, names.nslot) : nullptr;
            if (h == nullptr && PyErr_Occurred()) {
                failed = true;
                break;
            }
            int obj = 0;
            if (h != nullptr && h != Py_None) {
                obj = k2_is_object_handle(h, obj_kind, kind_shift);
                if (obj < 0) {
                    failed = true;
                    break;
                }
            }
            if (obj == 0) {
                Py_INCREF(none_ref);
                PyList_SET_ITEM(handles, i, none_ref);
                continue;
            }
            Py_INCREF(h);
            PyList_SET_ITEM(handles, i, h);
            int clean = k2_in_seen(seen, ship);
            if (clean == 1) {
                const int r = k2_holds(d, PySequence_Fast_ITEMS(ship_n),
                                       PySequence_Fast_GET_SIZE(ship_n));
                clean = r != 0 ? (r < 0 ? -1 : 0) : 1;
            }
            if (clean == 1) {
                PyObject* sys = PyDict_GetItemWithError(d, names.system);
                if (sys == nullptr && PyErr_Occurred())
                    clean = -1;
                else if (sys != nullptr && sys != Py_None)
                    clean = k2_clean_system(
                        sys, static_cast<size_t>(i), seen, stock_system,
                        stock_bank, sys_n, bank_n, system_patches,
                        bank_patches);
            }
            if (clean < 0) {
                failed = true;
                break;
            }
            if (clean == 0) {
                PyObject* pair = PyTuple_Pack(2, ship, h);
                if (pair == nullptr || PyList_Append(unclean, pair) < 0)
                    failed = true;
                Py_XDECREF(pair);
            }
        }
        if (!failed) result = PyTuple_Pack(2, handles, unclean);
    }
    Py_XDECREF(none_ref);
    Py_XDECREF(unclean);
    Py_XDECREF(handles);
    Py_XDECREF(seq);
    Py_XDECREF(bank_n);
    Py_XDECREF(sys_n);
    Py_XDECREF(ship_n);
    return result;
}

// ── combat_step_scan ─────────────────────────────────────────────────────────
// The per-step ship scan K4 and K3 share (step_scan.h; spec 2026-11-01 §4.1),
// a C loop over the instance dicts like k2_scan_ships (raw CPython calls: a
// pybind loop was slower than the Python it replaced).
//
// Fills cb::step_scan().ships with each entry's __dict__["_nslot"] in list
// order while every entry is representable: an int Object handle (`(h >>
// kind_shift) == obj_kind`), its class in `seen` (K2's seen classes), its
// dict holding none of `patches`. The first entry that is not ends the scan
// with its reason; otherwise cb::check_rows checks the rows. Returns
// (representable, reason or None, [set handle, ...]).
PyObject* step_scan_ships(PyObject* ships, long long obj_kind, int kind_shift,
                          PyObject* seen, PyObject* patches) {
    namespace cb = dauntless::combat;
    cb::StepScan& s = cb::step_scan();
    s.begin();
    PyObject* names = PySequence_List(patches);
    PyObject* seq = names ? PySequence_Fast(ships, "ships must be a sequence")
                          : nullptr;
    if (seq == nullptr) {
        Py_XDECREF(names);
        return nullptr;
    }
    PyObject* nslot = k2_scan_names().nslot;
    const Py_ssize_t n = PySequence_Fast_GET_SIZE(seq);
    PyObject* const* items = PySequence_Fast_ITEMS(seq);
    PyObject* const* pn = PySequence_Fast_ITEMS(names);
    const Py_ssize_t npn = PySequence_Fast_GET_SIZE(names);
    s.ships.reserve(static_cast<size_t>(n));
    cb::ScanWhy why = cb::ScanWhy::ok;
    bool failed = false;
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject* ship = items[i];
        PyObject* d = k2_dict_of(ship);
        PyObject* h = d ? PyDict_GetItemWithError(d, nslot) : nullptr;
        if (h == nullptr && PyErr_Occurred()) {
            failed = true;
            break;
        }
        if (h == nullptr || !PyLong_CheckExact(h)) {
            why = cb::ScanWhy::no_row;
            break;
        }
        int overflow = 0;
        const long long hv = PyLong_AsLongLongAndOverflow(h, &overflow);
        if (overflow != 0 || (hv >> kind_shift) != obj_kind) {
            why = cb::ScanWhy::no_row;
            break;
        }
        int r = k2_in_seen(seen, ship);
        if (r < 0) {
            failed = true;
            break;
        }
        if (r == 0) {
            why = cb::ScanWhy::unseen;
            break;
        }
        r = k2_holds(d, pn, npn);
        if (r < 0) {
            failed = true;
            break;
        }
        if (r == 1) {
            why = cb::ScanWhy::instance_patch;
            break;
        }
        s.ships.push_back(static_cast<std::int64_t>(hv));
    }
    Py_DECREF(seq);
    Py_DECREF(names);
    if (failed) {
        s.begin();
        return nullptr;
    }
    if (why == cb::ScanWhy::ok) {
        why = cb::check_rows(cb::mirror(), s);
    } else {
        s.representable = false;
        s.why = why;
    }
    PyObject* sets = PyList_New(static_cast<Py_ssize_t>(s.sets.size()));
    if (sets == nullptr) return nullptr;
    for (size_t i = 0; i < s.sets.size(); ++i) {
        PyObject* v = PyLong_FromLongLong(s.sets[i]);
        if (v == nullptr) {
            Py_DECREF(sets);
            return nullptr;
        }
        PyList_SET_ITEM(sets, static_cast<Py_ssize_t>(i), v);
    }
    PyObject* ok = s.representable ? Py_True : Py_False;
    PyObject* reason = s.representable
                           ? Py_None
                           : PyUnicode_FromString(cb::scan_why_name(why));
    if (reason == nullptr) {
        Py_DECREF(sets);
        return nullptr;
    }
    PyObject* result = PyTuple_Pack(3, ok, reason, sets);
    if (!s.representable) Py_DECREF(reason);
    Py_DECREF(sets);
    return result;
}

// ── C-applied write logs (combat_write_apply.h) ───────────────────────────
// True while combat_k2_next applies a record's writes: the Python the apply
// runs (wake hooks, setters) must not reach combat_k2_next / _end /
// _abandon / _drain, which would step, free or drain the session under the
// apply -- each throws instead (K0's delivery guard, k0_charging.h THE
// DELIVERY).
bool& k2_delivering() {
    static bool delivering = false;
    return delivering;
}

// The (bank, target, bubble entry, trace tier) of each damage pulse the last
// combat_k2_next record carried (k2_beams.h THE DAMAGE PULSE;
// combat_k2_last_hits).
using K2LastHit = std::tuple<std::int64_t, std::int64_t, bool, int>;
std::vector<K2LastHit>& k2_last_hits() {
    static std::vector<K2LastHit> hits;
    return hits;
}

void k2_not_delivering(const char* call) {
    if (k2_delivering())
        throw std::runtime_error(
            std::string("combat K2: ") + call +
            " while a record's writes are being delivered (re-entered from "
            "the Python they run)");
}

// A K2 contact's fields, CONTACT's layout from `bank` to `flush_dwell`
// (k2_beams.h, RECORDS); `vec` makes an xyz tuple. A CONTACT record's
// shields_block is None when the loop had none or Python answered it (an
// ASK); a drained rest carries the answer either way (`rest`, K2Rest).
template <class Vec>
void k2_contact_fields(py::list& items, const dauntless::combat::K2Contact& c,
                       const Vec& vec, bool rest) {
    static constexpr const char* kTiers[] = {"mesh", "sphere", "fallback",
                                             "origin"};
    auto opt = [&vec](const std::optional<dauntless::combat::Vec3>& v) {
        return v ? py::object(vec(*v)) : py::object(py::none());
    };
    py::object shields = py::none();
    if (c.shields_block && (rest || !c.shields_asked))
        shields = py::bool_(*c.shields_block);
    items.append(c.bank);
    items.append(c.target);
    items.append(c.ship);
    items.append(c.system);
    items.append(vec(c.emitter));
    items.append(vec(c.target_pos));
    items.append(c.dist);
    items.append(opt(c.aim_unit));
    items.append(vec(c.hit.point));
    items.append(opt(c.hit.normal));
    items.append(kTiers[static_cast<int>(c.hit.tier)]);
    items.append(opt(c.bubble));
    items.append(shields);
    items.append(c.flush_dwell);
}

// ── K2's native presentation at the drain (spec 2026-11-02 §4.4) ─────────
// What Python sends once per change (combat_k2_present_constants), the test
// capture (combat_present_capture) and the rests presented here
// ("k2_present_native", combat_k2_counts).
struct K2Present {
    bool have_consts = false;     // nothing is presented natively until sent
    double intensity = 0.0;       // hit_feedback.shield_impact_intensity("phaser")
    double default_radius = 0.0;  // combat.PHASER_DEFAULT_DAMAGE_RADIUS
    PyObject* capture = nullptr;  // owned: a list, or nullptr (off)
    std::int64_t presented = 0;
};

K2Present& k2_present() {
    static K2Present* p = new K2Present;  // never destroyed: owns a reference
    return *p;
}

// A Python error on the native-presentation path: an Exception is cleared
// (the caller then routes the entry to the Python batch, which meets the
// same call again in Python -- a raising or side-effecting
// GetDamageRadiusFactor runs twice; accepted under ruling Q2); anything
// else (KeyboardInterrupt, SystemExit) propagates out of the drain.
void k2_present_clear_or_raise() {
    if (!PyErr_ExceptionMatches(PyExc_Exception))
        throw py::error_already_set();
    PyErr_Clear();
}

// combat.weapon_splash_radius(bank, None): the bank's own
// GetDamageRadiusFactor() when > 0 (as float()), else the default. nullopt,
// the Exception cleared (k2_present_clear_or_raise), when any step raises:
// the entry then goes to the Python batch, which repeats the call
// (hasattr included) in Python.
std::optional<double> k2_splash_radius(PyObject* bank, double fallback) {
    py::object r = py::reinterpret_steal<py::object>(
        PyObject_CallMethod(bank, "GetDamageRadiusFactor", nullptr));
    if (!r) {
        k2_present_clear_or_raise();
        return std::nullopt;
    }
    if (PyFloat_CheckExact(r.ptr())) {
        const double d = PyFloat_AS_DOUBLE(r.ptr());
        return d > 0.0 ? d : fallback;
    }
    const py::float_ zero(0.0);
    const int gt = PyObject_RichCompareBool(r.ptr(), zero.ptr(), Py_GT);
    if (gt < 0) {
        k2_present_clear_or_raise();
        return std::nullopt;
    }
    if (!gt) return fallback;
    py::object f = py::reinterpret_steal<py::object>(PyNumber_Float(r.ptr()));
    if (!f) {
        k2_present_clear_or_raise();
        return std::nullopt;
    }
    return PyFloat_AS_DOUBLE(f.ptr());
}

// hit_feedback.beam_contact's shield branch for one drained rest, here,
// when it can be: the shields answer True, the target's instance id and its
// set's view offset known at contact time, the constants sent, the four
// objects it names still live (walk.live, through the session's applier
// context: else the Python batch counts it gone) and the bank's radius
// factor read cleanly. Then exactly what Python pushes: the anchor (the
// bubble entry, else the impact point) shifted into VIEW coordinates in
// double (hit_feedback._mesh_xyz: frames.shifted keeps the point itself for
// a zero offset), minus the instance's double translation
// (host_io._instance_relative; a stale instance pushes nothing), narrowed as
// the binding narrows, through push_shield_hit. rgba (0, 0, 0, 0): the
// ship's default ShieldGlowColor. False: the entry goes to Python.
template <class Vec>
bool k2_present_rest(const dauntless::combat::K2Rest& e, const Vec& vec) {
    namespace cb = dauntless::combat;
    K2Present& st = k2_present();
    const cb::K2Contact& c = e.contact;
    if (!st.have_consts || !c.shields_block || !*c.shields_block || !e.iid ||
        !e.view_known)
        return false;
    auto& applier = dauntless::host::write_applier();
    if (!applier.has_context()) return false;
    py::object bank;
    for (const std::int64_t h : {c.bank, c.target, c.ship, c.system}) {
        py::object o = py::reinterpret_steal<py::object>(applier.live(h));
        if (!o) {
            // To the Python batch, whose walk.live meets it again.
            k2_present_clear_or_raise();
            return false;
        }
        if (o.is_none()) return false;
        if (!bank) bank = std::move(o);
    }
    const std::optional<double> radius =
        k2_splash_radius(bank.ptr(), st.default_radius);
    if (!radius) return false;
    const cb::Vec3& a = c.bubble ? *c.bubble : c.hit.point;
    cb::Vec3 p = a;
    if (e.view_offset) {
        const cb::Vec3& o = *e.view_offset;
        if (!(o[0] == 0.0 && o[1] == 0.0 && o[2] == 0.0))
            p = {a[0] + o[0], a[1] + o[1], a[2] + o[2]};
    }
    const scenegraph::InstanceId id{e.iid->index, e.iid->generation};
    std::optional<cb::Vec3> rel;
    if (const auto t = instance_translation_for_python(id))
        rel = cb::Vec3{p[0] - t->x, p[1] - t->y, p[2] - t->z};
    // The capture first: an append that raises (a test's list) leaves this
    // splash unpushed and uncounted; the drain then raises, run_k2 abandons
    // the step, and the later rests it had taken are not presented.
    if (st.capture != nullptr) {
        py::tuple item = py::make_tuple(
            c.bank, c.target, id, vec(p),
            rel ? py::object(vec(*rel)) : py::object(py::none()),
            py::make_tuple(0.0, 0.0, 0.0, 0.0), st.intensity, *radius);
        if (PyList_Append(st.capture, item.ptr()) < 0)
            throw py::error_already_set();
    }
    if (rel)
        push_shield_hit(id,
                        glm::vec3(static_cast<float>((*rel)[0]),
                                  static_cast<float>((*rel)[1]),
                                  static_cast<float>((*rel)[2])),
                        glm::vec4(0.0f), static_cast<float>(st.intensity),
                        static_cast<float>(*radius));
    ++st.presented;
    return true;
}

// Marks the delivery for its scope (cleared on a throw too).
struct K2Delivering {
    K2Delivering() { k2_delivering() = true; }
    ~K2Delivering() { k2_delivering() = false; }
    K2Delivering(const K2Delivering&) = delete;
    K2Delivering& operator=(const K2Delivering&) = delete;
};

// THE COMPUTE TIMERS (kernels off the lock, Task 1; spec
// 2026-11-03-kernels-off-the-lock-design.md goal 1): a steady_clock span
// around exactly each kernel's compute call -- K0-K3's next(), K3's
// apply_hits (counted as K3's) and K4's k4_eligible -- accumulated per
// kernel (index 0-4; 5 is kernel M, the motion step) and read-and-reset by
// combat_compute_take. Pure C++
// inside the span (no CPython): the GIL release (THE GIL RELEASE, below)
// encloses it. A throwing compute still closes its span (RAII) and counts.
struct ComputeTimer {
    std::int64_t ns = 0;
    std::int64_t calls = 0;
};
constexpr int kComputeKernels = 6;

std::array<ComputeTimer, kComputeKernels>& compute_timers() {
    static std::array<ComputeTimer, kComputeKernels> t;
    return t;
}

class ComputeSpan {
public:
    explicit ComputeSpan(int kernel)
        : t_(compute_timers()[static_cast<size_t>(kernel)]),
          t0_(std::chrono::steady_clock::now()) {}
    ~ComputeSpan() {
        t_.ns += std::chrono::duration_cast<std::chrono::nanoseconds>(
                     std::chrono::steady_clock::now() - t0_)
                     .count();
        ++t_.calls;
    }
    ComputeSpan(const ComputeSpan&) = delete;
    ComputeSpan& operator=(const ComputeSpan&) = delete;

private:
    ComputeTimer& t_;
    std::chrono::steady_clock::time_point t0_;
};

// THE GIL RELEASE (kernels off the lock, Task 3; spec goal 3): a kernel's
// compute -- K0-K3's next() and K3's apply_hits (its hits' native damage) --
// runs with the GIL released, and only the compute: everything before and
// after it in a binding is CPython (the scans, the
// applier, the queue appends, the record build) and keeps the lock. Each
// site is one released_compute call whose lambda is the kernel call alone
// (tests/unit/test_native_k1_holds_gil.py guards the source). K4 and
// can_detect keep the GIL: single short calls (lock map 5.2).
//
// Safe because no Python another thread runs meanwhile mutates what compute
// reads: a finalizer's free waits for a drain, and a push made off the main
// thread is queued (native_combat, "Deferred frees and off-main pushes");
// the main thread itself is in compute. The combat library has no CPython
// (lock map 0), and its hooks (the trace hooks, K0's weapon check) read C++
// state only.
//
// The release is declared BEFORE the span, so the compute timer closes
// before the GIL is re-acquired and never counts the wait for it. A throw
// re-acquires the GIL as it unwinds (the release's destructor), before
// pybind translates it; the driver then abandons its session as for any
// exception.
enum class ComputeSite : int { K0, K1, K2, K3, K3Hits, Motion, kCount };
constexpr int kComputeSites = static_cast<int>(ComputeSite::kCount);

// The timer index: K0-K3 0-3 (K3Hits is K3's), K4 4, kernel M 5.
constexpr int compute_kernel(ComputeSite s) {
    if (s == ComputeSite::K3Hits) return 3;
    if (s == ComputeSite::Motion) return 5;
    return static_cast<int>(s);
}

// THE GIL PROBE (test only; tests/unit/test_native_gil_release.py,
// tests/integration/test_native_off_lock_stress.py). Unarmed -- always, in
// play -- a released compute pays one relaxed load. Armed, each released
// compute call counts itself per site, and whether PyGILState_Check() read 0
// inside it (callable without the GIL). Armed, it can also:
//   hold   the next `holds` calls each wait, GIL released, until another
//          thread's Python steps (combat_gil_probe_step) or `hold_ns`
//          passes: a churning thread then provably runs while compute does;
//          `ran` counts calls during whose release a step arrived, `during`
//          those with one across the compute call itself;
//   throw  std::runtime_error from inside the released region of the next
//          call at `throw_site` (Review Focus 3).
// The counters are the main thread's (it computes and takes them); `steps`
// is the only one another thread writes.
struct GilProbe {
    std::atomic<bool> armed{false};
    std::atomic<std::int64_t> steps{0};
    int holds = 0;
    std::int64_t hold_ns = 0;
    int throw_site = -1;
    std::int64_t thrown = 0;
    std::array<std::int64_t, kComputeSites> calls{}, released{}, ran{},
        during{};
};

GilProbe& gil_probe() {
    static GilProbe p;
    return p;
}

template <class F>
auto gil_probe_compute(ComputeSite site, F& compute) {
    GilProbe& p = gil_probe();
    const auto i = static_cast<size_t>(site);
    ++p.calls[i];
    if (PyGILState_Check() == 0) ++p.released[i];
    const std::int64_t entered = p.steps.load();
    if (p.holds > 0) {
        --p.holds;
        const auto until = std::chrono::steady_clock::now() +
                           std::chrono::nanoseconds(p.hold_ns);
        while (p.steps.load() == entered &&
               std::chrono::steady_clock::now() < until)
            std::this_thread::yield();
    }
    if (p.throw_site == static_cast<int>(site)) {
        p.throw_site = -1;
        ++p.thrown;
        throw std::runtime_error("combat GIL probe: thrown in compute");
    }
    const std::int64_t before = p.steps.load();
    auto r = compute();
    const std::int64_t after = p.steps.load();
    if (after != entered) ++p.ran[i];
    if (after != before) ++p.during[i];
    return r;
}

template <class F>
auto released_compute(ComputeSite site, F&& compute) {
    const py::gil_scoped_release release;
    const ComputeSpan span(compute_kernel(site));
    if (gil_probe().armed.load(std::memory_order_relaxed)) [[unlikely]]
        return gil_probe_compute(site, compute);
    return compute();
}

// True when the last combat_k1_next raised from applying its record's
// writes rather than from the kernel (combat_apply_raised): run_k1 reads
// it before treating a ValueError / RuntimeError as the kernel's.
bool& k1_apply_raised() {
    static bool raised = false;
    return raised;
}

// A K1 write value in the Python encoding (combat_write_apply.h): None,
// bool, int, float, a handle list, ("walk_offset", walk, system) or
// ("slot", index, value).
py::object k1_value_py(const dauntless::combat::K1Value& value) {
    namespace cb = dauntless::combat;
    return std::visit(
        [](const auto& x) -> py::object {
            using T = std::decay_t<decltype(x)>;
            if constexpr (std::is_same_v<T, std::monostate>)
                return py::none();
            else if constexpr (std::is_same_v<T, cb::K1WalkOffset>)
                return py::make_tuple("walk_offset", x.walk, x.system);
            else if constexpr (std::is_same_v<T, cb::SlotWrite>)
                return py::make_tuple(
                    "slot", x.index,
                    std::visit(
                        [](const auto& v) -> py::object {
                            using V = std::decay_t<decltype(v)>;
                            if constexpr (std::is_same_v<V, std::monostate>)
                                return py::none();
                            else
                                return py::cast(v);
                        },
                        x.value));
            else
                return py::cast(x);  // a scalar, or a handle list
        },
        value);
}

// The module each row's launch resolved to (launch deferral, M1): an OWNED
// reference per row handle -- an Ammo row's (native_combat.push_ammo_launch,
// beside its cached state) or a pulse cannon's (push_pulse_params, beside
// its P6 params, Task 3) -- set by combat_set_launch_module, so a kernel
// SPAWN carries the module resolved at fire time, as Python's own SPAWN
// does. Released when its row is unregistered (combat_unregister), by
// combat_clear and by a None set.
std::unordered_map<std::int64_t, PyObject*>& k1_launch_modules() {
    static auto* m = new std::unordered_map<std::int64_t, PyObject*>();
    return *m;  // never destroyed: it may own references at exit
}

void k1_launch_modules_clear() {
    std::unordered_map<std::int64_t, PyObject*> old;
    old.swap(k1_launch_modules());
    for (auto& [h, o] : old) Py_DECREF(o);
}

// Drop row `h`'s module, if it has one (the map is consistent before the
// reference goes: a module's finaliser may re-enter).
void k1_launch_module_release(std::int64_t h) {
    auto& t = k1_launch_modules();
    const auto it = t.find(h);
    if (it == t.end()) return;
    PyObject* const old = it->second;
    t.erase(it);
    Py_DECREF(old);
}

// The objects a launch's queue entries hold from fire time (final review
// 1): each operand the object its handle names now, when the session's
// applier can name it (WriteApplier::live), owned here until the queue
// takes it (release()), else dropped with this. So a row freed between the
// fire and the boundary loses neither the spawn nor its events, whose
// launcher writes already applied: the launcher, ship and set as the
// target and the shot's target always were (Review Focus 5).
class K1Held {
public:
    K1Held() = default;
    K1Held(const K1Held&) = delete;
    K1Held& operator=(const K1Held&) = delete;
    ~K1Held() {
        for (PyObject* o : owned_) Py_DECREF(o);
    }

    // `h` (-1 kept). A handle naming no live object: -1 (None) for a
    // target (`none_ok`: the torpedo's target is None, not a skipped
    // spawn), else the handle (skipped at delivery if gone).
    dauntless::host::NativeOperand operator()(std::int64_t h, bool none_ok) {
        namespace hq = dauntless::host;
        hq::WriteApplier& applier = hq::write_applier();
        if (h == -1 || !applier.has_context()) return h;
        PyObject* o = applier.live(h);
        if (o == nullptr) throw py::error_already_set();
        if (o == Py_None) {
            Py_DECREF(o);
            return none_ok ? std::int64_t{-1} : h;
        }
        owned_.push_back(o);
        return hq::OwnedObject{o};
    }

    // The queue took every reference handed out.
    void release() { owned_.clear(); }

private:
    std::vector<PyObject*> owned_;
};

// A SPAWN's operands (combat_effect_queue.h; effect_queue._spawn): the
// record in order, flags and the kind as numbers (a handle is an int), the
// launcher, ship, set, target and the shot's target held (K1Held).
void k1_append_spawn(const dauntless::combat::K1Entry& e) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    const cb::K1Spawn& s = *e.spawn;
    // The module the launch resolved to (k1_launch_modules): an ammo
    // type's, or a cannon's own (K1Spawn::ammo names the row), set with the
    // cached state the kernel launched on, so always present.
    const auto mi = k1_launch_modules().find(s.ammo);
    if (mi == k1_launch_modules().end())
        throw std::logic_error(
            "combat K1: a SPAWN's row has no module (push_ammo_launch, "
            "push_pulse_params)");
    PyObject* const module = mi->second;
    K1Held held;
    const hq::NativeOperand launcher = held(e.a, false);
    const hq::NativeOperand ship = held(s.ship, false);
    const hq::NativeOperand set = held(s.set, false);
    // The shot's target (a pulse's ET_WEAPON_FIRED pointer) too.
    const hq::NativeOperand target = held(s.target, true);
    const hq::NativeOperand fired_at = held(s.fired_at, true);
    const hq::NativeOperand ops[] = {
        launcher,
        static_cast<double>(static_cast<int32_t>(s.kind)),
        ship,
        set,
        hq::OwnedObject{Py_NewRef(module)},
        target,
        s.position[0], s.position[1], s.position[2],
        s.has_velocity ? 1.0 : 0.0,
        s.velocity[0], s.velocity[1], s.velocity[2],
        s.has_offset ? 1.0 : 0.0,
        s.offset[0], s.offset[1], s.offset[2],
        s.drf_override,
        s.damage_scale,
        fired_at,
    };
    static_assert(std::size(ops) <= hq::EffectEntry::kMaxOperands);
    hq::effect_queue().append_native_span(hq::EffectKind::SPAWN, ops);
    held.release();  // the queue owns the module and every held reference
}

// A K1 record's queue entries (k1_fire_control.h, THE EFFECT QUEUE) into
// the combat effect queue, in walk order: K1Effect names the kinds of the
// same names (the combat library does not link the host layer).
void k1_append_entries(std::span<const dauntless::combat::K1Entry> entries) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    for (const cb::K1Entry& e : entries) {
        switch (e.kind) {
            case cb::K1Effect::SPAWN:
                if (!e.spawn) throw std::logic_error("combat K1: SPAWN, no record");
                k1_append_spawn(e);
                break;
            case cb::K1Effect::AMMO_CONSUMED: {
                // A launch's event: held like its SPAWN (K1Held).
                K1Held held;
                hq::effect_queue().append_native(hq::EffectKind::AMMO_CONSUMED,
                                                 held(e.a, false));
                held.release();
                break;
            }
            case cb::K1Effect::FIRE_SOUND:
                hq::effect_queue().append_native(hq::EffectKind::FIRE_SOUND, e.a);
                break;
            case cb::K1Effect::LOOP_STOP:
                hq::effect_queue().append_native(hq::EffectKind::LOOP_STOP, e.a);
                break;
            case cb::K1Effect::WEAPON_FIRED: {
                // A launch's (or an edge's) event: held like a SPAWN.
                K1Held held;
                const hq::NativeOperand weapon = held(e.a, false);
                const hq::NativeOperand target = held(e.b, true);
                hq::effect_queue().append_native(hq::EffectKind::WEAPON_FIRED,
                                                 weapon, target);
                held.release();
                break;
            }
            case cb::K1Effect::WEAPON_FIRE_FAILED:
                hq::effect_queue().append_native(
                    hq::EffectKind::WEAPON_FIRE_FAILED, e.a);
                break;
            case cb::K1Effect::TRACTOR_STARTED:
                hq::effect_queue().append_native(
                    hq::EffectKind::TRACTOR_STARTED, e.a, e.b);
                break;
            case cb::K1Effect::TRACTOR_STOPPED:
                hq::effect_queue().append_native(
                    hq::EffectKind::TRACTOR_STOPPED, e.a, e.b);
                break;
            case cb::K1Effect::kCount:
                throw std::logic_error("combat K1: unknown queue entry");
        }
    }
}

// A K0 record's queue entries (k0_charging.h, THE EFFECT QUEUE) into the
// combat effect queue, in walk order: K0Effect names the kinds of the same
// names. A WATCH names the WEAPON (delivery fires its charge watcher).
void k0_append_entries(std::span<const dauntless::combat::K0Entry> entries) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    for (const cb::K0Entry& e : entries) {
        switch (e.kind) {
            case cb::K0Effect::LOOP_STOP:
                hq::effect_queue().append_native(hq::EffectKind::LOOP_STOP, e.a);
                break;
            case cb::K0Effect::TORPEDO_RELOAD:
                hq::effect_queue().append_native(
                    hq::EffectKind::TORPEDO_RELOAD, e.a);
                break;
            case cb::K0Effect::WATCH:
                hq::effect_queue().append_native(hq::EffectKind::WATCH, e.a,
                                                 e.old_value, e.new_value);
                break;
            case cb::K0Effect::kCount:
                throw std::logic_error("combat K0: unknown queue entry");
        }
    }
}

// ── Native damage (spec 2026-11-02-native-damage-design.md §4.2) ─────────
// damage.h computes a hit or a condition write on the mirror; these turn
// its result into Python's: the writes applied by the session's applier
// (combat_write_apply.h), the entries appended to the effect queue under
// THE FROZEN ENTRY CONTRACT (combat_effect_queue.h, effect_queue.py).

// The combat library's damage kinds and codes are the queue's.
static_assert(dauntless::combat::kWatchCondition ==
                  static_cast<int>(dauntless::host::CondWatch::CONDITION) &&
              dauntless::combat::kWatchCombined ==
                  static_cast<int>(dauntless::host::CondWatch::COMBINED));
static_assert(
    dauntless::combat::kSubsysDestroyed ==
        static_cast<int>(dauntless::host::SubsysEvent::DESTROYED) &&
    dauntless::combat::kSubsysDisabled ==
        static_cast<int>(dauntless::host::SubsysEvent::DISABLED) &&
    dauntless::combat::kSubsysOperational ==
        static_cast<int>(dauntless::host::SubsysEvent::OPERATIONAL));
static_assert(
    dauntless::combat::kTransitionNone ==
        static_cast<int>(dauntless::host::HitTransition::NONE) &&
    dauntless::combat::kTransitionDisabled ==
        static_cast<int>(dauntless::host::HitTransition::DISABLED) &&
    dauntless::combat::kTransitionDestroyed ==
        static_cast<int>(dauntless::host::HitTransition::DESTROYED));

dauntless::host::EffectKind damage_effect_kind(dauntless::combat::DamageKind k) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    switch (k) {
        case cb::DamageKind::COND_WATCH: return hq::EffectKind::COND_WATCH;
        case cb::DamageKind::SUBSYS_EVENT: return hq::EffectKind::SUBSYS_EVENT;
        case cb::DamageKind::REPAIR_ADD: return hq::EffectKind::REPAIR_ADD;
        case cb::DamageKind::ZERO_CROSS: return hq::EffectKind::ZERO_CROSS;
        case cb::DamageKind::HIT_PRESENT: return hq::EffectKind::HIT_PRESENT;
        case cb::DamageKind::WEAPON_HIT: return hq::EffectKind::WEAPON_HIT;
        case cb::DamageKind::kCount: break;
    }
    throw std::logic_error("combat damage: unknown entry kind");
}

// A native damage call's entries into the effect queue, in order. Each R
// operand is held as the object its handle names now (K1Held: the entry
// holds its subject from emission, as the Python reference's does, so a
// row freed before the boundary loses nothing); every H operand is the
// call's `held` object (damage.h, Held: the hit's source, the write's
// killer), or -1 for None.
void damage_append_entries(const std::vector<dauntless::combat::DamageEntry>& entries,
                           PyObject* held) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    // Each entry is built in place (append_native_entry): the operands a
    // NativeOperand span would carry, typed as append_native_span types
    // them, without building a std::variant per operand (at -O0 that was
    // half of a native condition write). The references taken for one
    // entry are released if it cannot be completed; the queue owns them
    // once it is appended.
    hq::WriteApplier& applier = hq::write_applier();
    hq::EffectEntry out;
    for (const cb::DamageEntry& e : entries) {
        PyObject* owned[cb::DamageEntry::kMaxOperands];
        int n_owned = 0;
        struct Release {
            PyObject** refs;
            int& n;
            ~Release() {
                for (int i = 0; i < n; ++i) Py_DECREF(refs[i]);
            }
        } release{owned, n_owned};
        out.kind = damage_effect_kind(e.kind);
        out.count = e.count;
        for (int i = 0; i < e.count; ++i) {
            const cb::DamageOperand& o = e.ops[i];
            hq::EffectOperand& x = out.ops[i];
            switch (o.type) {
                case cb::DamageOperand::Type::Handle: {
                    // K1Held(h, false): the object the handle names now,
                    // else the handle (skipped at delivery if gone).
                    x.type = hq::EffectOperand::Type::Handle;
                    x.handle = o.handle;
                    if (o.handle == -1 || !applier.has_context()) break;
                    PyObject* obj = applier.live(o.handle);
                    if (obj == nullptr) throw py::error_already_set();
                    if (obj == Py_None) {
                        Py_DECREF(obj);
                        break;
                    }
                    owned[n_owned++] = obj;
                    x.type = hq::EffectOperand::Type::Object;
                    x.object = obj;
                    break;
                }
                case cb::DamageOperand::Type::Held:
                    if (held == nullptr || held == Py_None) {
                        x.type = hq::EffectOperand::Type::Handle;
                        x.handle = -1;
                    } else {
                        owned[n_owned++] = Py_NewRef(held);
                        x.type = hq::EffectOperand::Type::Object;
                        x.object = held;
                    }
                    break;
                case cb::DamageOperand::Type::Number:
                    x.type = hq::EffectOperand::Type::Number;
                    x.number = o.number;
                    break;
                case cb::DamageOperand::Type::Int:
                    x.type = hq::EffectOperand::Type::Int;
                    x.integer = o.integer;
                    break;
                case cb::DamageOperand::Type::Bool:
                    x.type = hq::EffectOperand::Type::Bool;
                    x.boolean = o.boolean;
                    break;
            }
        }
        hq::effect_queue().append_native_entry(out);
        n_owned = 0;   // the queue owns every reference now
    }
}

// The DamageOut buffers damage_run reuses: one per nesting depth (an
// applied write's Python may make another native damage call), each
// cleared before use and keeping its capacity, so a call allocates (and
// moves its writes through a vector's regrowth) only the first time.
struct DamageOutPool {
    std::vector<std::unique_ptr<dauntless::combat::DamageOut>> outs;
    size_t depth = 0;
};

DamageOutPool& damage_out_pool() {
    static DamageOutPool p;
    return p;
}

// Run a damage.h call: false when it fell back (the mirror is as it was,
// nothing applied, nothing queued: the caller runs the Python); else its
// writes applied through the session's applier, then its entries queued.
template <class Fn>
bool damage_run(Fn&& fn, PyObject* held) {
    namespace cb = dauntless::combat;
    namespace hq = dauntless::host;
    DamageOutPool& pool = damage_out_pool();
    if (pool.depth == pool.outs.size())
        pool.outs.push_back(std::make_unique<cb::DamageOut>());
    cb::DamageOut& out = *pool.outs[pool.depth];
    out.clear();
    struct Depth {
        DamageOutPool& p;
        ~Depth() { --p.depth; }
    } depth{pool};
    ++pool.depth;
    try {
        fn(out);
    } catch (const std::invalid_argument&) {
        return false;
    }
    if (!out.writes.empty() &&
        !hq::write_applier().apply(out.writes, 0, out.writes.size()))
        throw py::error_already_set();
    damage_append_entries(out.entries, held);
    return true;
}

// A kernel's damage entries (K2's pulse, K3's hit: native damage Task 4):
// every H operand is the object handle `held` names now, resolved through
// the session's applier (the firing ship, the torpedo's source ship; -1
// None), as K1Held resolves a launch's.
void damage_append_held(const std::vector<dauntless::combat::DamageEntry>& entries,
                        std::int64_t held) {
    namespace hq = dauntless::host;
    if (held == -1) {
        damage_append_entries(entries, nullptr);
        return;
    }
    PyObject* o = hq::write_applier().live(held);
    if (o == nullptr) throw py::error_already_set();
    struct Drop {
        PyObject* o;
        ~Drop() { Py_DECREF(o); }
    } drop{o};
    damage_append_entries(entries, o);
}

// A kernel's damage context (k2_beams.h K2PulseCtx: THE DAMAGE PULSE; K3's
// THE HITS), from the driver's dict: "ok", "player", "god_mode",
// "double_damage", "npc_shields_off", "intensity" (3 floats),
// "default_radius", "pp_low", "hit_weapon", "weapon_hit_type",
// "has_instances", "clean" (Object handles); K2's also "python_banks"
// (Subsystem handles whose pulses are Python's; absent: none).
dauntless::combat::K2PulseCtx k2_pulse_ctx(const py::dict& d) {
    dauntless::combat::K2PulseCtx p;
    p.ok = d["ok"].cast<bool>();
    p.dc.player = d["player"].cast<std::int64_t>();
    p.dc.god_mode = d["god_mode"].cast<bool>();
    p.dc.double_damage = d["double_damage"].cast<bool>();
    p.dc.npc_shields_off = d["npc_shields_off"].cast<bool>();
    p.intensity = d["intensity"].cast<std::array<double, 3>>();
    p.default_radius = d["default_radius"].cast<double>();
    p.pp_low = d["pp_low"].cast<std::int64_t>();
    p.hit_weapon = d["hit_weapon"].cast<std::int64_t>();
    p.weapon_hit_type = d["weapon_hit_type"].cast<std::int64_t>();
    p.has_instances = d["has_instances"].cast<bool>();
    for (auto h : d["clean"]) p.clean.insert(h.cast<std::int64_t>());
    if (d.contains("python_banks"))
        for (auto h : d["python_banks"])
            p.python_banks.insert(h.cast<std::int64_t>());
    return p;
}


// An optional point argument: None, or three floats.
void damage_point(const py::object& o, bool& has, dauntless::combat::Vec3& v) {
    has = !o.is_none();
    if (has) {
        const auto a = o.cast<std::array<double, 3>>();
        v = {a[0], a[1], a[2]};
    }
}

// ── The one-call scalar push (combat_push_scalar; spec 2026-11-02 §4.2) ───
// NativeField._encode's scalar branches, in C++: float(value), int(value),
// truthiness, `is True`, None -> -1. The codes are combat_push_codes().
enum class PushCode : int {
    kFloat, kInt, kBool, kIsTrue, kOptInt, kCount
};

constexpr const char* kPushCodeNames[] = {
    "PUSH_FLOAT", "PUSH_INT", "PUSH_BOOL", "PUSH_IS_TRUE", "PUSH_OPT_INT"};
static_assert(sizeof(kPushCodeNames) / sizeof(kPushCodeNames[0]) ==
              static_cast<size_t>(PushCode::kCount));

// Pushes the binding stored (counts()["fast_pushes"]).
std::uint64_t& fast_pushes() {
    static std::uint64_t n = 0;
    return n;
}

// int(value) as an int64 into *out: false with int(value)'s own exception
// set, or OverflowError for an int the int64 row cannot hold.
bool push_int(PyObject* value, std::int64_t* out) {
    PyObject* r = PyNumber_Long(value);
    if (r == nullptr) return false;
    int overflow = 0;
    const long long v = PyLong_AsLongLongAndOverflow(r, &overflow);
    Py_DECREF(r);
    if (v == -1 && PyErr_Occurred()) return false;
    if (overflow != 0) {
        PyErr_SetString(PyExc_OverflowError,
                        "combat_push_scalar: int does not fit the int64 row");
        return false;
    }
    *out = v;
    return true;
}

// combat_push_scalar(h, fid, code, value): NativeField._push for a scalar
// field in one call. A raw METH_FASTCALL function, not an m.def: pybind11's
// argument dispatch cost more than the encode and the store together (the
// push runs ~244 times a tick). Encodes FIRST, exactly as _push, so an
// encoding error raises before the handle is looked at; then the store,
// whose std::invalid_argument (stale handle, unknown or mistyped field) is
// pybind's ValueError. A CALLER bug -- the wrong argument count, an unknown
// push code, a field id out of range -- raises SystemError instead: never
// one of the three _push_scalar turns into a silent row drop.
PyObject* combat_push_scalar(PyObject*, PyObject* const* args,
                             Py_ssize_t nargs) {
    namespace cb = dauntless::combat;
    if (nargs != 4) {
        PyErr_Format(PyExc_SystemError,
                     "combat_push_scalar() takes 4 arguments (%zd given)",
                     nargs);
        return nullptr;
    }
    const long long h = PyLong_AsLongLong(args[0]);
    if (h == -1 && PyErr_Occurred()) return nullptr;
    const long f = PyLong_AsLong(args[1]);
    if (f == -1 && PyErr_Occurred()) return nullptr;
    const long code = PyLong_AsLong(args[2]);
    if (code == -1 && PyErr_Occurred()) return nullptr;
    PyObject* v = args[3];
    bool is_float = false;
    double d = 0.0;
    std::int64_t i = 0;
    switch (static_cast<PushCode>(code)) {
        case PushCode::kFloat: {                    // float(value)
            PyObject* r = PyNumber_Float(v);
            if (r == nullptr) return nullptr;
            d = PyFloat_AS_DOUBLE(r);
            Py_DECREF(r);
            is_float = true;
            break;
        }
        case PushCode::kInt:                        // int(value)
            if (!push_int(v, &i)) return nullptr;
            break;
        case PushCode::kBool: {                     // 1 if value else 0
            const int t = PyObject_IsTrue(v);
            if (t < 0) return nullptr;
            i = t;
            break;
        }
        case PushCode::kIsTrue:                     // 1 if value is True
            i = v == Py_True ? 1 : 0;
            break;
        case PushCode::kOptInt:                     // -1 for None, int()
            if (v == Py_None) i = -1;
            else if (!push_int(v, &i)) return nullptr;
            break;
        default:
            PyErr_Format(PyExc_SystemError,
                         "combat_push_scalar: unknown push code %ld", code);
            return nullptr;
    }
    if (f < 0 || f >= static_cast<long>(cb::Field::kCount)) {
        PyErr_Format(PyExc_SystemError,
                     "combat_push_scalar: unknown field id %ld", f);
        return nullptr;
    }
    const auto field = static_cast<cb::Field>(f);
    try {
        if (is_float) cb::mirror().set_f(h, field, d);
        else cb::mirror().set_i(h, field, i);
    } catch (const std::invalid_argument& e) {
        PyErr_SetString(PyExc_ValueError, e.what());
        return nullptr;
    } catch (const std::exception& e) {
        PyErr_SetString(PyExc_RuntimeError, e.what());
        return nullptr;
    }
    ++fast_pushes();
    Py_RETURN_NONE;
}

PyMethodDef g_push_scalar_def = {
    "combat_push_scalar",
    reinterpret_cast<PyCFunction>(
        reinterpret_cast<void (*)()>(&combat_push_scalar)),
    METH_FASTCALL,
    "combat_push_scalar(h, fid, code, value): NativeField._push for a "
    "scalar field in one call. Encodes `value` by `code` "
    "(combat_push_codes) with _encode's rules and raises where it raises "
    "(TypeError / ValueError / OverflowError, and OverflowError for an int "
    "beyond int64); a stale handle raises ValueError. A wrong argument "
    "count, an unknown code or a field id out of range raises "
    "SystemError."};

// ── Registry lookups (K0's scan, THE CLEAN CACHE) ─────────────────────────
// These scans run no Python bytecode and allocate nothing GC-tracked (a
// GC-tracked allocation can run cyclic GC, whose weakref.finalize ->
// native_combat.unregister_handle frees mirror rows): they never BUILD an
// instance dict (k1_built_dict); their only allocation is a registry
// lookup's int key, which is not GC-tracked.

// The registry's KeyedRef for handle `h`, borrowed, or nullptr (no error
// set): native_combat._registry is a WeakValueDictionary, `data` its dict of
// KeyedRef.
PyObject* k1_registry_ref(PyObject* registry, std::int64_t h) {
    PyObject* key = PyLong_FromLongLong(h);
    if (key == nullptr) {
        PyErr_Clear();
        return nullptr;
    }
    PyObject* ref = PyDict_GetItemWithError(registry, key);
    Py_DECREF(key);
    if (ref == nullptr || !PyWeakref_Check(ref)) {
        PyErr_Clear();
        return nullptr;
    }
    return ref;
}

// `o`'s instance dict, borrowed, if it already exists as a dict; nullptr
// (no error set) otherwise -- WITHOUT building one. On CPython 3.11+ an
// ordinary class's instance (Py_TPFLAGS_MANAGED_DICT) keeps its attributes
// in a values array until something asks for its __dict__, and
// _PyObject_GetDictPtr (k2_dict_of) then BUILDS the dict: a GC-tracked
// allocation, which the scans must never make (see above). The managed
// dict slot sits three pointers before the object: 3.11 and 3.13 the dict
// pointer (NULL until built), 3.12 the dict or the values pointer tagged
// with bit 0. Any other version answers nullptr. In practice a registered
// object's dict is built at registration (the mirror fields write
// obj.__dict__), so the nullptr is a guard, not a cost.
PyObject* k1_built_dict(PyObject* o) {
#if PY_VERSION_HEX >= 0x030B0000
    if (PyType_HasFeature(Py_TYPE(o), Py_TPFLAGS_MANAGED_DICT)) {
#if PY_VERSION_HEX < 0x030E0000
        const std::uintptr_t slot = reinterpret_cast<std::uintptr_t*>(o)[-3];
        if (slot == 0 || (slot & 1u) != 0) return nullptr;
        PyObject* d = reinterpret_cast<PyObject*>(slot);
        return PyDict_CheckExact(d) ? d : nullptr;
#else
        return nullptr;
#endif
    }
#endif
    return k2_dict_of(o);  // a tp_dictoffset slot: read, never built
}

// The scan reads PyDictObject::ma_version_tag, and only where kK0ObjectCache
// allows (CPython 3.11, the one version verified; see below): elsewhere it
// is never read. The pragmas keep the field's deprecation quiet.
#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
#elif defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
// ── The K0 session's begin (combat_k0_begin; k0_charging.h) ───────────────
// One pass over the Python ship list, made before the kernel's begin: each
// ship's Object handle (its "_nslot"; -1 without one). There is no override
// guard (phase 6 A2; spec 2026-11-05-phase6-engine-stages-native-design.md
// §3, Part A: a stage never falls back to Python because an App method was
// patched), so nothing else is read. No Python code runs and nothing
// GC-tracked is allocated.
//
// What follows is also K1's, K2's and native damage's: the instance-dict
// read (k0_dict_of), the exact per-object caches' key (K0ObjKey, k0_same:
// an object's type and its dict STATE, the dict and its PEP 509
// ma_version_tag -- a process-wide counter bumped by every insert, replace
// and delete, so an unchanged (dict, version) is an unchanged dict; a
// `__class__` assignment changes the type, which is compared too) and a
// type's version tag (k0_type_tag).

// What one object's answer was computed on (type == nullptr: nothing).
struct K0ObjKey {
    PyTypeObject* type = nullptr;
    PyObject* dict = nullptr;
    std::uint64_t version = 0;
};

struct K0ScanNames {
    PyObject* nslot;
    PyObject* tag_probe;  // any interned name: _PyType_Lookup assigns a tag
};

const K0ScanNames& k0_scan_names() {
    static const K0ScanNames n{PyUnicode_InternFromString("_nslot"),
                               PyUnicode_InternFromString("__init__")};
    return n;
}


// The per-object helpers are forced inline: the scans run every tick over
// every object, and a Debug (-O0) build otherwise pays a call for each
// helper and each CPython accessor (Py_TYPE, PyType_HasFeature are calls
// there too, so fields are read directly).
#if defined(__clang__) || defined(__GNUC__)
#define K0_INLINE inline __attribute__((always_inline))
#else
#define K0_INLINE inline
#endif

// k1_built_dict, the managed-dict case read in place (3.11-3.13).
K0_INLINE PyObject* k0_dict_of(PyObject* o) {
#if PY_VERSION_HEX >= 0x030B0000 && PY_VERSION_HEX < 0x030E0000
    if (o->ob_type->tp_flags & Py_TPFLAGS_MANAGED_DICT) {
        const std::uintptr_t sl = reinterpret_cast<std::uintptr_t*>(o)[-3];
        if (sl == 0 || (sl & 1u) != 0) return nullptr;
        PyObject* d = reinterpret_cast<PyObject*>(sl);
        return d->ob_type == &PyDict_Type ? d : nullptr;
    }
#endif
    return k1_built_dict(o);
}

// The per-object answer caches rest on PEP 509's ma_version_tag changing on
// every insert, replace and delete. Verified on CPython 3.11 only (3.12
// repurposes its low bits for dict watchers, 3.14 drops the field): any
// other version takes the uncached path -- every object's answer computed
// at every scan, the same answers, slower.
#if PY_VERSION_HEX >= 0x030B0000 && PY_VERSION_HEX < 0x030C0000
constexpr bool kK0ObjectCache = true;
#else
constexpr bool kK0ObjectCache = false;
#endif

// The dict's mutation version (PEP 509): every insert, replace and delete
// takes a new value from a process-wide counter, so it never repeats.
K0_INLINE std::uint64_t k0_dict_version(PyObject* d) {
#if PY_VERSION_HEX >= 0x030B0000 && PY_VERSION_HEX < 0x030C0000
    return reinterpret_cast<PyDictObject*>(d)->ma_version_tag;
#else
    (void)d;
    return 0;
#endif
}

// `o` is in the state `k` was computed on (`d` its dict, or nullptr). Never
// on an unverified Python (kK0ObjectCache).
K0_INLINE bool k0_same(const K0ObjKey& k, PyObject* o, PyObject* d) {
    return kK0ObjectCache && d != nullptr && o->ob_type == k.type &&
           d == k.dict && k0_dict_version(d) == k.version;
}

// `t`'s version tag, assigned if it has none (0: none can be).
unsigned int k0_type_tag(PyTypeObject* t) {
    if ((t->tp_flags & Py_TPFLAGS_VALID_VERSION_TAG) == 0)
        (void)_PyType_Lookup(t, k0_scan_names().tag_probe);
    return (t->tp_flags & Py_TPFLAGS_VALID_VERSION_TAG) != 0
               ? t->tp_version_tag
               : 0u;
}

// `d`'s "_nslot" as a handle of `kind`, or -1.
std::int64_t k0_handle(PyObject* d, std::int64_t kind) {
    PyObject* hs = PyDict_GetItemWithError(d, k0_scan_names().nslot);
    if (hs == nullptr || !PyLong_Check(hs)) {
        PyErr_Clear();
        return -1;
    }
    const long long v = PyLong_AsLongLong(hs);
    if (v == -1 && PyErr_Occurred()) {
        PyErr_Clear();
        return -1;
    }
    return (v >= 0 && (v >> 60) == kind) ? v : -1;
}

// The begin's ship handles: each ship's "_nslot" as an Object handle, -1
// for a ship with no built dict or no row (the kernel's no_row). `ships` a
// list or tuple; false: a Python error is set.
bool k0_ship_handles(PyObject* ships, std::vector<std::int64_t>& out) {
    namespace cb = dauntless::combat;
    if (!PyList_CheckExact(ships) && !PyTuple_CheckExact(ships)) {
        PyErr_SetString(PyExc_TypeError, "combat_k0_begin: ships: a list");
        return false;
    }
    PyObject* const* items =
        ships->ob_type == &PyList_Type
            ? reinterpret_cast<PyListObject*>(ships)->ob_item
            : reinterpret_cast<PyTupleObject*>(ships)->ob_item;
    const Py_ssize_t count = reinterpret_cast<PyVarObject*>(ships)->ob_size;
    out.assign(static_cast<size_t>(count), -1);
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* d = k0_dict_of(items[i]);
        if (d != nullptr)
            out[static_cast<size_t>(i)] =
                k0_handle(d, static_cast<std::int64_t>(cb::Kind::Object));
    }
    return true;
}

#if defined(__clang__)
#pragma clang diagnostic pop
#elif defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

// A handle's registry entry, cached (keyed as K0ObjKey, above; exact,
// and only where kK0ObjectCache allows): its KeyedRef, while the
// registry dict is the same object at the same ma_version_tag (it then
// still holds the ref); the referent is read live. Kept by the handle's row
// index; the handle is compared.
struct K1RefEntry {
    std::int64_t h = -1;
    PyObject* registry = nullptr;
    std::uint64_t version = 0;
    PyObject* ref = nullptr;  // borrowed from the registry dict
};

// The cache entry of handle `h` (its row index), or `scratch` past a sane
// table size.
template <class E>
E& k1_entry(std::vector<E>& v, std::int64_t h, E& scratch) {
    const std::uint64_t i = static_cast<std::uint64_t>(h) & 0xffffffffu;
    if (i >= (1u << 20)) {
        scratch = E{};
        return scratch;
    }
    if (i >= v.size()) v.resize(i + 1 + 64);
    return v[i];
}

// Handle `h`'s live object in the registry, borrowed, or nullptr (no error
// set), its KeyedRef (k1_registry_ref) cached in `e`.
PyObject* k1_lookup(K1RefEntry& e, PyObject* registry, std::int64_t h) {
    if (!(kK0ObjectCache && e.ref != nullptr && e.h == h &&
          e.registry == registry &&
          e.version == k0_dict_version(registry))) {
        e = K1RefEntry{};
        PyObject* ref = k1_registry_ref(registry, h);
        if (ref == nullptr) return nullptr;
        e = K1RefEntry{h, registry, k0_dict_version(registry), ref};
    }
    PyObject* o = PyWeakref_GetObject(e.ref);
    if (o == nullptr || o == Py_None) {
        PyErr_Clear();
        return nullptr;
    }
    return o;
}

py::tuple k0_write_tuple(const dauntless::combat::K0Write& kw) {
    namespace cb = dauntless::combat;
    using T = cb::K0FieldWrite::Type;
    const cb::K0FieldWrite& w = kw.w;
    switch (w.type) {
        case T::Float:
            return py::make_tuple(kw.handle, cb::field_name(w.field), w.d);
        case T::Flag:
            return py::make_tuple(kw.handle, cb::field_name(w.field),
                                  w.i != 0);
        case T::Int:
            return py::make_tuple(kw.handle, cb::field_name(w.field), w.i);
        case T::Slot:
            return py::make_tuple(kw.handle, cb::field_name(w.field),
                                  py::make_tuple("slot", w.index, w.d));
        case T::Watcher:
            return py::make_tuple(kw.handle, "_charge_watcher",
                                  py::make_tuple("watcher", w.d));
        case T::Ref:
            return py::make_tuple(kw.handle, cb::field_name(w.field), w.i);
        case T::Null:
            return py::make_tuple(kw.handle, cb::field_name(w.field),
                                  py::none());
    }
    throw std::logic_error("combat K0: a write of no type");
}

// ── THE SCAN CACHE (k2_scan_ships; native damage perf fix) ────────────────
// K1's THE CACHES, keyed as K0ObjKey (above; exact, and only where
// kK0ObjectCache allows): each phaser system's and each bank's "holds one
// of the names" answer, with what it was computed on -- its type and its
// dict at the dict's ma_version_tag -- kept by POSITION in the scan (the
// ship's index, then each child's in "_children"). With the answer the
// dict's own reads are kept: a system's "_children" and a bank's
// "_target", borrowed from that same dict state (an unchanged dict still
// holds them). Read live at every scan: each class check (the stock
// system and bank classes), the children list (an in-place append changes
// the list, not the dict) and whether a target's class is seen. So a
// system or bank not written since the last scan costs a few compares
// (Task 4's damage-pulse names made each probe 4 names longer), and a
// patch -- an instance attribute, a `__class__` swap, a new target -- is
// seen at the next scan. Other name sets drop every answer.
struct K2ScanBankEntry {
    K0ObjKey key;
    int holds = 0;
    PyObject* target = nullptr;    // borrowed from key.dict; nullptr: none
};

struct K2ScanSysEntry {
    K0ObjKey key;
    int holds = 0;
    PyObject* children = nullptr;  // borrowed from key.dict; nullptr: none
    std::vector<K2ScanBankEntry> banks;
};

struct K2ScanCaches {
    std::vector<K2ScanSysEntry> systems;
    PyObject* names[2] = {nullptr, nullptr};  // owned: the patch sets
    void clear() {
        systems.clear();
        PyObject* a = names[0];
        PyObject* b = names[1];
        names[0] = names[1] = nullptr;
        Py_XDECREF(a);
        Py_XDECREF(b);
    }
};

K2ScanCaches& k2_scan_caches() {
    static K2ScanCaches c;
    return c;
}

int k2_clean_system(PyObject* sys, size_t pos, PyObject* seen,
                    PyObject* stock_system, PyObject* stock_bank,
                    PyObject* sys_names, PyObject* bank_names,
                    PyObject* sys_patches, PyObject* bank_patches) {
    if (reinterpret_cast<PyObject*>(Py_TYPE(sys)) != stock_system) return 0;
    PyObject* sd = k2_dict_of(sys);
    if (sd == nullptr) return 0;
    K2ScanCaches& c = k2_scan_caches();
    if (c.names[0] != sys_patches || c.names[1] != bank_patches) {
        c.clear();
        c.names[0] = Py_NewRef(sys_patches);
        c.names[1] = Py_NewRef(bank_patches);
    }
    K2ScanSysEntry scratch;
    K2ScanSysEntry* ep = &scratch;
    if (pos < (1u << 20)) {
        if (pos >= c.systems.size()) c.systems.resize(pos + 1 + 16);
        ep = &c.systems[pos];
    }
    K2ScanSysEntry& e = *ep;
    if (k0_same(e.key, sys, sd)) {
        ++k2_scan_counts().cached;
    } else {
        e.key = K0ObjKey{};
        ++k2_scan_counts().probed;
        const int r = k2_holds(sd, PySequence_Fast_ITEMS(sys_names),
                               PySequence_Fast_GET_SIZE(sys_names));
        if (r < 0) return -1;
        PyObject* kids = nullptr;
        if (r == 0) {
            kids = PyDict_GetItemWithError(sd, k2_scan_names().children);
            if (kids == nullptr && PyErr_Occurred()) return -1;
        }
        e.holds = r;
        e.children = kids;
        e.key = K0ObjKey{sys->ob_type, sd, k0_dict_version(sd)};
    }
    if (e.holds != 0) return 0;
    if (e.children == nullptr) return 1;
    PyObject* seq = PySequence_Fast(e.children, "");
    if (seq == nullptr) {
        PyErr_Clear();
        return 0;
    }
    PyObject* const* banks = PySequence_Fast_ITEMS(seq);
    const Py_ssize_t nbanks = PySequence_Fast_GET_SIZE(seq);
    PyObject* const* bn = PySequence_Fast_ITEMS(bank_names);
    const Py_ssize_t nbn = PySequence_Fast_GET_SIZE(bank_names);
    PyObject* target_key = k2_scan_names().target;
    if (e.banks.size() < static_cast<size_t>(nbanks))
        e.banks.resize(static_cast<size_t>(nbanks));
    int clean = 1;
    for (Py_ssize_t i = 0; i < nbanks && clean == 1; ++i) {
        PyObject* b = banks[i];
        if (reinterpret_cast<PyObject*>(Py_TYPE(b)) != stock_bank) {
            clean = 0;
            break;
        }
        PyObject* bd = k2_dict_of(b);
        if (bd == nullptr) {
            clean = 0;
            break;
        }
        K2ScanBankEntry& be = e.banks[static_cast<size_t>(i)];
        if (k0_same(be.key, b, bd)) {
            ++k2_scan_counts().cached;
        } else {
            be.key = K0ObjKey{};
            ++k2_scan_counts().probed;
            const int r = k2_holds(bd, bn, nbn);
            if (r < 0) {
                clean = -1;
                break;
            }
            PyObject* target = nullptr;
            if (r == 0) {
                target = PyDict_GetItemWithError(bd, target_key);
                if (target == nullptr && PyErr_Occurred()) {
                    clean = -1;
                    break;
                }
            }
            be.holds = r;
            be.target = target;
            be.key = K0ObjKey{b->ob_type, bd, k0_dict_version(bd)};
        }
        if (be.holds != 0) {
            clean = 0;
            break;
        }
        if (be.target == nullptr || be.target == Py_None) continue;
        const int r = k2_in_seen(seen, be.target);
        if (r != 1) clean = r < 0 ? -1 : 0;
    }
    Py_DECREF(seq);
    return clean;
}

// ── combat_dmg_clean (native damage Task 4; override-guard gap 1) ────────
// Which `targets` a kernel may hit natively: a ship whose instance dict
// holds none of `ship_names` and each of whose subsystems the hit can reach
// -- its mount order (combat._iter_subsystems: the overlap walk, children
// included), its hull and its shield generator, by their mirror handles,
// each object found through `registry_data` (native_combat._registry's
// handle -> weakref dict) -- holds none of `sub_names` (the methods the
// hit and the condition chain stand in for: an instance attribute
// shadowing one must be obeyed, so that ship's hit goes to Python). A ship
// with no row, a handle the mirror cannot name, a subsystem not in the
// registry or freed: not clean. Raw CPython calls; no Python code runs.
//
// THE CLEAN CACHE (native damage perf fix; K1's THE CACHES, keyed as
// K0ObjKey, exact, and only where kK0ObjectCache allows): each ship's
// and each subsystem's "holds one of the names" answer, by its handle's
// row index (the handle compared), with what it was computed on -- its
// type and its dict at the dict's ma_version_tag -- so an unchanged
// object is never probed again; any insert, replace or delete in its dict
// (a write, a patch, a del) moves the version and it is probed at the
// next scan. A subsystem's KeyedRef is kept while the registry dict is
// the same object at the same version (k1_lookup); its referent is read
// live. Other name tuples drop every answer.
struct DmgCleanCounts {
    std::uint64_t probed = 0, cached = 0;
};

DmgCleanCounts& dmg_clean_counts() {
    static DmgCleanCounts c;
    return c;
}

struct DmgCleanEntry {
    std::int64_t h = -1;
    K1RefEntry ref;      // subsystems: the registry's KeyedRef
    K0ObjKey key;
    int holds = 0;
};

struct DmgCleanCaches {
    std::vector<DmgCleanEntry> ships, subs;
    PyObject* names[2] = {nullptr, nullptr};  // owned: the tuples answered
    void clear() {
        ships.clear();
        subs.clear();
        PyObject* a = names[0];
        PyObject* b = names[1];
        names[0] = names[1] = nullptr;
        Py_XDECREF(a);
        Py_XDECREF(b);
    }
};

DmgCleanCaches& dmg_clean_caches() {
    static DmgCleanCaches c;
    return c;
}

// The entry for handle `h` (its row index), reset when it held another.
DmgCleanEntry& dmg_clean_entry(std::vector<DmgCleanEntry>& v,
                               std::int64_t h, DmgCleanEntry& scratch) {
    DmgCleanEntry& e = k1_entry(v, h, scratch);
    if (e.h != h) {
        e = DmgCleanEntry{};
        e.h = h;
    }
    return e;
}

// 1: `o`'s dict `d` holds one of `names`; 0: not; -1: error. Answered
// from `e` when `o` is in the state it was computed on.
int dmg_clean_holds(DmgCleanEntry& e, PyObject* o, PyObject* d,
                    PyObject* names) {
    if (k0_same(e.key, o, d)) {
        ++dmg_clean_counts().cached;
        return e.holds;
    }
    e.key = K0ObjKey{};
    ++dmg_clean_counts().probed;
    const int r = k2_holds(d, PySequence_Fast_ITEMS(names),
                           PySequence_Fast_GET_SIZE(names));
    if (r < 0) return -1;
    e.holds = r;
    e.key = K0ObjKey{o->ob_type, d, k0_dict_version(d)};
    return r;
}

// One target: 1 clean, 0 not, -1 error (set).
int dmg_clean_one(PyObject* t, PyObject* registry_data, PyObject* sn,
                  PyObject* un, DmgCleanCaches& c) {
    namespace cb = dauntless::combat;
    const cb::Mirror& mi = cb::mirror();
    PyObject* nslot = k2_scan_names().nslot;
    // 1 clean, 0 not, -1 error: one subsystem handle.
    auto sub_clean = [&](std::int64_t h) -> int {
        if (h == -1) return 1;
        if (h == cb::kRefUnrepresentable || mi.subsystem(h) == nullptr)
            return 0;
        DmgCleanEntry scratch;
        DmgCleanEntry& e = dmg_clean_entry(c.subs, h, scratch);
        PyObject* obj = k1_lookup(e.ref, registry_data, h);  // borrowed
        if (obj == nullptr) return 0;
        PyObject* d = k2_dict_of(obj);
        if (d == nullptr) return 0;
        const int r = dmg_clean_holds(e, obj, d, un);
        return r < 0 ? -1 : (r == 1 ? 0 : 1);
    };
    PyObject* d = t == Py_None ? nullptr : k2_dict_of(t);
    if (d == nullptr) return 0;
    PyObject* h = PyDict_GetItemWithError(d, nslot);
    if (h == nullptr && PyErr_Occurred()) return -1;
    long long hv = -1;
    const bool has_row = h != nullptr && PyLong_CheckExact(h);
    if (has_row) {
        hv = PyLong_AsLongLong(h);
        if (hv == -1 && PyErr_Occurred()) return -1;
    }
    int r;
    if (has_row && hv >= 0) {
        DmgCleanEntry scratch;
        r = dmg_clean_holds(dmg_clean_entry(c.ships, hv, scratch), t, d, sn);
    } else {
        ++dmg_clean_counts().probed;
        r = k2_holds(d, PySequence_Fast_ITEMS(sn),
                     PySequence_Fast_GET_SIZE(sn));
    }
    if (r < 0) return -1;
    if (r != 0 || !has_row) return 0;
    // mi.object answers nullptr for a handle of another kind, or none.
    const cb::ObjectRow* row = hv < 0 ? nullptr : mi.object(hv);
    if (row == nullptr) return 0;
    for (const std::int64_t sh : row->mount_order) {
        const int k = sub_clean(sh);
        if (k != 1) return k;
    }
    for (const std::int64_t sh : {row->_hull, row->_shield_subsystem}) {
        const int k = sub_clean(sh);
        if (k != 1) return k;
    }
    return 1;
}

// The scan's name tuples (PySequence_Fast of each, new references) and
// the cache, dropped when they are other tuples than its answers'.
bool dmg_clean_setup(PyObject* ship_names, PyObject* sub_names,
                     PyObject** sn, PyObject** un, DmgCleanCaches*& c) {
    *sn = PySequence_Fast(ship_names, "ship_names");
    *un = *sn ? PySequence_Fast(sub_names, "sub_names") : nullptr;
    if (*un == nullptr) {
        Py_XDECREF(*sn);
        return false;
    }
    c = &dmg_clean_caches();
    if (c->names[0] != ship_names || c->names[1] != sub_names) {
        c->clear();
        c->names[0] = Py_NewRef(ship_names);
        c->names[1] = Py_NewRef(sub_names);
    }
    return true;
}

// Returns a list of bools, one per target.
PyObject* dmg_clean(PyObject* targets, PyObject* registry_data,
                    PyObject* ship_names, PyObject* sub_names) {
    if (!PyDict_Check(registry_data)) {
        PyErr_SetString(PyExc_TypeError, "registry_data must be a dict");
        return nullptr;
    }
    PyObject *sn = nullptr, *un = nullptr;
    DmgCleanCaches* c = nullptr;
    if (!dmg_clean_setup(ship_names, sub_names, &sn, &un, c)) return nullptr;
    PyObject* seq = PySequence_Fast(targets, "targets");
    if (seq == nullptr) {
        Py_DECREF(un);
        Py_DECREF(sn);
        return nullptr;
    }
    const Py_ssize_t n = PySequence_Fast_GET_SIZE(seq);
    PyObject* out = PyList_New(n);
    bool failed = out == nullptr;
    for (Py_ssize_t i = 0; i < n && !failed; ++i) {
        const int clean = dmg_clean_one(PySequence_Fast_GET_ITEM(seq, i),
                                        registry_data, sn, un, *c);
        if (clean < 0) {
            failed = true;
            break;
        }
        PyObject* b = clean == 1 ? Py_True : Py_False;
        Py_INCREF(b);
        PyList_SET_ITEM(out, i, b);
    }
    Py_DECREF(seq);
    Py_DECREF(un);
    Py_DECREF(sn);
    if (failed) {
        Py_XDECREF(out);
        return nullptr;
    }
    return out;
}

// dmg_clean over `handles` (Object handles, each resolved as
// `_registry.get(h)` -- the registry dict's KeyedRef, its referent or
// None): the list of the clean handles, in order.
PyObject* dmg_clean_handles(PyObject* handles, PyObject* registry_data,
                            PyObject* ship_names, PyObject* sub_names) {
    if (!PyDict_Check(registry_data)) {
        PyErr_SetString(PyExc_TypeError, "registry_data must be a dict");
        return nullptr;
    }
    PyObject *sn = nullptr, *un = nullptr;
    DmgCleanCaches* c = nullptr;
    if (!dmg_clean_setup(ship_names, sub_names, &sn, &un, c)) return nullptr;
    PyObject* seq = PySequence_Fast(handles, "handles");
    PyObject* out = seq ? PyList_New(0) : nullptr;
    bool failed = out == nullptr;
    for (Py_ssize_t i = 0; !failed && i < PySequence_Fast_GET_SIZE(seq);
         ++i) {
        PyObject* key = PySequence_Fast_GET_ITEM(seq, i);
        PyObject* obj = Py_None;
        PyObject* ref = PyDict_GetItemWithError(registry_data, key);
        if (ref == nullptr && PyErr_Occurred()) {
            failed = true;
            break;
        }
        if (ref != nullptr && PyWeakref_CheckRef(ref)) {
            obj = PyWeakref_GetObject(ref);   // borrowed; None when dead
            if (obj == nullptr) {
                failed = true;
                break;
            }
        }
        Py_INCREF(obj);   // held for the probe
        const int clean = dmg_clean_one(obj, registry_data, sn, un, *c);
        Py_DECREF(obj);
        if (clean < 0 || (clean == 1 && PyList_Append(out, key) < 0))
            failed = true;
    }
    Py_XDECREF(seq);
    Py_DECREF(un);
    Py_DECREF(sn);
    if (failed) {
        Py_XDECREF(out);
        return nullptr;
    }
    return out;
}

// ── THE FAST DAMAGE ENTRIES (native damage perf fix) ─────────────────────
// native_combat.set_condition / damage_system's whole common case in one
// raw METH_FASTCALL call (pybind11's dispatch, at -O0, cost more than the
// native condition write itself): the instance-patch check, the handles,
// float(value), the applier context and the native chain (no module or
// class patch guard: spec Part A, phase 6 A3). Exactly the Python wrapper's
// steps, in its order. Answers True (done natively), False (hand back to
// the reference: an instance patch, an object the mirror cannot name, a
// value float() refuses, the native chain fell back -- nothing changed) or
// None: anything this path does not decide exactly (an object with no
// plain instance dict, a non-int `_nslot`, the reused context already in
// use by an enclosing call), for the Python wrapper's own path, which then
// decides as before.
//
// THE REUSED CONTEXT. `ctx` is native_combat's one damage applier context
// (_dmg_context: a _K1Walk's pins, the registry, the kinds), installed for
// the call and the caller's restored after, as _dmg_call does; its pins
// are emptied after every call, so it holds nothing alive between calls
// and every call resolves its handles afresh, as a fresh walk would.

// _dmg_handle(o, kind): 1 with `*h` (-1 for None); 0 the mirror cannot
// name it (None in Python); -1 not decided here (no error set).
int dmg_fast_handle(PyObject* o, dauntless::combat::Kind kind,
                    std::int64_t* h) {
    if (o == Py_None) {
        *h = -1;
        return 1;
    }
    if (_PyObject_GetDictPtr(o) == nullptr) return -1;
    PyObject* d = k2_dict_of(o);
    if (d == nullptr) return -1;
    PyObject* s = PyDict_GetItemWithError(d, k2_scan_names().nslot);
    if (s == nullptr) {
        if (PyErr_Occurred()) {
            PyErr_Clear();
            return -1;
        }
        return 0;
    }
    if (!PyLong_CheckExact(s)) return -1;
    int overflow = 0;
    const long long v = PyLong_AsLongLongAndOverflow(s, &overflow);
    if (overflow != 0 || (v == -1 && PyErr_Occurred())) {
        PyErr_Clear();
        return -1;
    }
    if (v < 0 || ((v >> 60) & 7) != static_cast<long long>(kind)) return 0;
    *h = v;
    return 1;
}

// _dmg_held(o): 1 with `*h` (-1 None, -2 unnamed); -1 not decided here.
int dmg_fast_held(PyObject* o, std::int64_t* h) {
    if (o == Py_None) {
        *h = -1;
        return 1;
    }
    if (_PyObject_GetDictPtr(o) == nullptr) return -1;
    PyObject* d = k2_dict_of(o);
    if (d == nullptr) return -1;
    PyObject* s = PyDict_GetItemWithError(d, k2_scan_names().nslot);
    if (s == nullptr) {
        if (PyErr_Occurred()) {
            PyErr_Clear();
            return -1;
        }
        *h = dauntless::combat::kRefUnrepresentable;
        return 1;
    }
    if (!PyLong_CheckExact(s)) return -1;
    int overflow = 0;
    const long long v = PyLong_AsLongLongAndOverflow(s, &overflow);
    if (overflow != 0 || (v == -1 && PyErr_Occurred())) {
        PyErr_Clear();
        return -1;
    }
    *h = v;
    return 1;
}

// _dmg_patched(o, names): 1 patched, 0 not, -1 not decided here.
int dmg_fast_patched(PyObject* o, PyObject* names) {
    if (!PyTuple_CheckExact(names) || _PyObject_GetDictPtr(o) == nullptr)
        return -1;
    PyObject* d = k2_dict_of(o);
    if (d == nullptr) return -1;
    const int r = k2_holds(d, &PyTuple_GET_ITEM(names, 0),
                           PyTuple_GET_SIZE(names));
    if (r < 0) {
        PyErr_Clear();
        return -1;
    }
    return r;
}

// Run `fn` (a damage_run call) under the reused context `ctx`; the
// caller's context restored and the pins emptied after, whatever happens.
// A Python object (True / False), or nullptr with an error set.
template <class Fn>
PyObject* dmg_fast_run(PyObject* ctx, Fn&& fn) {
    namespace hq = dauntless::host;
    PyObject* prev = hq::write_applier().set_context(ctx);
    if (prev == nullptr) return nullptr;
    bool done = false;
    std::optional<py::error_already_set> err;
    const char* what = nullptr;
    try {
        done = fn();
    } catch (py::error_already_set& e) {
        err.emplace(std::move(e));      // fetched: no error is set now
    } catch (const std::exception& e) {
        what = e.what();
    }
    PyObject* back = hq::write_applier().set_context(prev);
    Py_DECREF(prev);
    Py_XDECREF(back);
    PyObject* pins = PyTuple_GET_ITEM(ctx, 0);
    if (PyDict_GET_SIZE(pins) != 0) PyDict_Clear(pins);
    if (back == nullptr) {
        // Restoring a context it held a moment ago cannot fail; if it did,
        // its error wins.
        return nullptr;
    }
    if (err) {
        err->restore();
        return nullptr;
    }
    if (what != nullptr) {
        PyErr_SetString(PyExc_RuntimeError, what);
        return nullptr;
    }
    return Py_NewRef(done ? Py_True : Py_False);
}

// float(value) as set_condition's `float(value)`: 1 with `*v`; 0 it
// refused (TypeError / ValueError / OverflowError: the caller hands back,
// the reference raises it); -1 another error, set (it propagates).
int dmg_fast_float(PyObject* value, double* v) {
    if (PyFloat_CheckExact(value)) {
        *v = PyFloat_AS_DOUBLE(value);
        return 1;
    }
    PyObject* f = PyNumber_Float(value);
    if (f == nullptr) {
        if (PyErr_ExceptionMatches(PyExc_TypeError) ||
            PyErr_ExceptionMatches(PyExc_ValueError) ||
            PyErr_ExceptionMatches(PyExc_OverflowError)) {
            PyErr_Clear();
            return 0;
        }
        return -1;
    }
    *v = PyFloat_AS_DOUBLE(f);
    Py_DECREF(f);
    return 1;
}

bool dmg_fast_ctx_ok(PyObject* ctx) {
    return PyTuple_CheckExact(ctx) && PyTuple_GET_SIZE(ctx) == 6 &&
           PyDict_CheckExact(PyTuple_GET_ITEM(ctx, 0)) &&
           dauntless::host::write_applier().context() != ctx;
}

// combat_dmg_set_condition(sub, value, killer, ship, ctx, sub_names):
// native_combat.set_condition(sub, value, killer, ship).
PyObject* combat_dmg_set_condition(PyObject*, PyObject* const* args,
                                   Py_ssize_t nargs) {
    namespace cb = dauntless::combat;
    if (nargs != 6) {
        PyErr_Format(PyExc_SystemError,
                     "combat_dmg_set_condition() takes 6 arguments (%zd "
                     "given)",
                     nargs);
        return nullptr;
    }
    PyObject *sub = args[0], *value = args[1], *killer = args[2],
             *ship = args[3], *ctx = args[4], *names = args[5];
    if (!dmg_fast_ctx_ok(ctx)) Py_RETURN_NONE;
    const int p = dmg_fast_patched(sub, names);
    if (p < 0) Py_RETURN_NONE;
    if (p > 0) Py_RETURN_FALSE;
    std::int64_t sub_h = -1, ship_h = -1, killer_h = -1;
    const int sh = dmg_fast_handle(sub, cb::Kind::Subsystem, &sub_h);
    const int oh = dmg_fast_handle(ship, cb::Kind::Object, &ship_h);
    const int kh = dmg_fast_held(killer, &killer_h);
    if (sh < 0 || oh < 0 || kh < 0) Py_RETURN_NONE;
    double v = 0.0;
    const int f = dmg_fast_float(value, &v);
    if (f < 0) return nullptr;
    if (f == 0) Py_RETURN_FALSE;
    if (sh == 0 || sub_h == -1 || oh == 0) Py_RETURN_FALSE;
    return dmg_fast_run(ctx, [&] {
        return damage_run(
            [&](cb::DamageOut& out) {
                cb::set_condition(cb::mirror(), sub_h, v, killer_h, ship_h,
                                  out);
            },
            killer);
    });
}

PyMethodDef g_dmg_set_condition_def = {
    "combat_dmg_set_condition",
    reinterpret_cast<PyCFunction>(
        reinterpret_cast<void (*)()>(&combat_dmg_set_condition)),
    METH_FASTCALL,
    "combat_dmg_set_condition(sub, value, killer, ship, ctx, sub_names): "
    "native_combat.set_condition's common case in one call (THE FAST "
    "DAMAGE ENTRIES). True done, False hand back, None: decide in "
    "Python."};

// combat_dmg_damage_system(ship, sub, amount, source, ctx, sub_names,
// ship_subsystem): native_combat.damage_system(ship, sub, amount, source).
PyObject* combat_dmg_damage_system(PyObject*, PyObject* const* args,
                                   Py_ssize_t nargs) {
    namespace cb = dauntless::combat;
    if (nargs != 7) {
        PyErr_Format(PyExc_SystemError,
                     "combat_dmg_damage_system() takes 7 arguments (%zd "
                     "given)",
                     nargs);
        return nullptr;
    }
    PyObject *ship = args[0], *sub = args[1], *amount = args[2],
             *source = args[3], *ctx = args[4], *names = args[5],
             *ship_subsystem = args[6];
    if (!dmg_fast_ctx_ok(ctx) || !PyFloat_CheckExact(amount) ||
        !PyType_Check(ship_subsystem))
        Py_RETURN_NONE;
    // isinstance(sub, ShipSubsystem): decided here only when it is.
    if (!PyObject_TypeCheck(sub,
                            reinterpret_cast<PyTypeObject*>(ship_subsystem)))
        Py_RETURN_NONE;
    const int p = dmg_fast_patched(sub, names);
    if (p < 0) Py_RETURN_NONE;
    if (p > 0) Py_RETURN_FALSE;
    std::int64_t ship_h = -1, sub_h = -1, source_h = -1;
    const int oh = dmg_fast_handle(ship, cb::Kind::Object, &ship_h);
    const int sh = dmg_fast_handle(sub, cb::Kind::Subsystem, &sub_h);
    const int kh = dmg_fast_held(source, &source_h);
    if (sh < 0 || oh < 0 || kh < 0) Py_RETURN_NONE;
    if (oh == 0 || ship_h == -1 || sh == 0) Py_RETURN_FALSE;
    const double amt = PyFloat_AS_DOUBLE(amount);
    return dmg_fast_run(ctx, [&] {
        return damage_run(
            [&](cb::DamageOut& out) {
                cb::damage_system(cb::mirror(), ship_h, sub_h, amt,
                                  source_h, out);
            },
            source);
    });
}

PyMethodDef g_dmg_damage_system_def = {
    "combat_dmg_damage_system",
    reinterpret_cast<PyCFunction>(
        reinterpret_cast<void (*)()>(&combat_dmg_damage_system)),
    METH_FASTCALL,
    "combat_dmg_damage_system(ship, sub, amount, source, ctx, sub_names, "
    "ship_subsystem): native_combat.damage_system's common case in one "
    "call (THE FAST DAMAGE ENTRIES). True done, False hand back, None: "
    "decide in Python."};

}  // namespace

// benchmark-only (phase 6 B0): the TGPoint3 class bench_new_point builds.
// Intentionally leaked (never destroyed): a static py::object destructing at
// interpreter shutdown would touch a finalized interpreter.
static py::object& bench_point_class() {
    static py::object* cls = new py::object();
    return *cls;
}

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

    m.def("prewarm_scuff_normal_texture",
          []() { renderer::ensure_scuff_normal_texture(); },
          "Load the collision-scuff normal map now rather than on the first "
          "scuff drawn: 12.6 MB, ~0.6 s in that frame in Debug "
          "(perf-register P-11). Call after set_project_asset_root, with the "
          "GL context current.");

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
              d["warp_in_flashes"]    = g_warp_in_flashes.size();
              d["warp_in_flash_intensity"] = py_float(g_warp_in_flash_params.intensity);
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
              // The legacy volumetric pass only; the system pass (which draws
              // the volumes with Volumetric Nebulae on) keeps no history
              // since 2026-10-19.
              d["nebula_history"] =
                  g_nebula_volumetric_pass
                  && g_nebula_volumetric_pass->has_history();
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
          py::arg("scale") = 1.0f,
          py::arg("geosphere") = false,
          py::arg("interior") = false,
          py::arg("sibling_overlay_dirs") = std::vector<std::string>{});
    m.def("parse_set_camera", &parse_set_camera_impl,
          "Extract the embedded camera (frustum + world transform) from a set "
          "NIF, or None. Parse-only; no GL context required.");
    m.def("set_smoothing_report", &set_smoothing_report_impl,
          py::arg("abs_path"), py::arg("fix_json"),
          "Parse a set NIF, apply the mesh fix (fix_json is the file's text), "
          "build it as an interior set loads (normals generated, no GL), and "
          "return one dict per authored smoothing edge: block, a, b, found, "
          "joined_a, joined_b. None if the file is missing or unparsable; a "
          "fix that fails to parse or is refused raises RuntimeError.");
    m.def("nif_shapes", &nif_shapes_impl,
          py::arg("abs_path"), py::arg("fix_json") = py::none(),
          "Every NiTriShape in a NIF, in block order: block index, name, "
          "texture basenames, world-space vertices/normals, UV set 0, "
          "triangles, hidden flag. None if the file is missing or fails to "
          "parse. Parse-only, no GL context; applies no mesh fix. Feeds "
          "tools/gen_mesh_fixes.py. Also: world (16 floats, column-major, "
          "data frame -> model), parent node name, data_block, per-vertex "
          "colors (or []), UV set 1 (or []). With fix_json (a mesh-fix file's "
          "text), the fix is parsed and applied in memory first, exactly as the "
          "loader does; a parse failure or refusal raises RuntimeError.");

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
                  g_running_lights.erase(id);
                  g_severance_jobs.forget(id);   // its result is never applied
                  interp_forget(interp_key(id));  // never inherited
                  // Purge any bridge node-anim state keyed on this index BEFORE
                  // it can be recycled by a new instance in the same Python step
                  // (the lazy per-frame sweep in update_bridge_node_anims runs
                  // too late if teardown+reload happen inside a single frame).
                  g_bridge_node_anims.stop(id.index);
                  g_bridge_node_ids.erase(id.index);
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
              g_have_prev_viewproj = false;
          },
          "Reset the floating render origin to (0,0,0) for a new mission, and "
          "drop the origin-dependent history of the dust, volumetric-nebula "
          "and motion-blur passes. Use set_render_origin for per-frame moves.");
    m.def("instance_translation",
          [](scenegraph::InstanceId id, bool drawn) -> py::object {
              const auto t = instance_translation_for_python(id, drawn);
              if (!t) return py::none();
              return py::make_tuple(t->x, t->y, t->z);
          },
          py::arg("iid"), py::arg("drawn") = false,
          "The instance's VIEW-space hit-pose translation (x, y, z) in double, "
          "or None for a stale id: the SIM pose when a sim source is set "
          "(set_instance_sim_source), else -- or with drawn=True -- the drawn "
          "pose. Subtract it (in double) from a world point to form the "
          "INSTANCE-RELATIVE points the mesh queries take (ray_trace_mesh, "
          "shield_hit, hull_damage_add, world_to_body, damage_decal_add), "
          "and add it back to ray_trace_mesh's hit; pass the same drawn flag "
          "to both.");
    m.def("set_instance_sim_source",
          [](scenegraph::InstanceId id, int index, std::uint32_t generation,
             double scale, std::tuple<double, double, double> view_offset) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              inst->sim_xform_index = index < 0 ? -1 : index;
              inst->sim_xform_generation = generation;
              inst->sim_scale = scale;
              inst->sim_view_offset = glm::dvec3(std::get<0>(view_offset),
                                                 std::get<1>(view_offset),
                                                 std::get<2>(view_offset));
          },
          py::arg("iid"), py::arg("index"), py::arg("generation"),
          py::arg("scale"), py::arg("view_offset"),
          "Give a render instance its SIM pose source: a transform-store slot, "
          "uniform scale and per-set VIEW offset. Gameplay point queries "
          "(instance_translation, ray_trace_mesh, world_to_body, shield_hit, "
          "damage_decal_add, hull_damage_add, instance_surface_points) then "
          "compose the pose from the live store instead of the drawn matrix. "
          "index < 0 clears; a stale handle reads the drawn pose.");
    m.def("set_instance_transform_slot",
          [](scenegraph::InstanceId id, int index, std::uint32_t generation,
             double scale) {
              // Compose once now, so an instance realized between frames is
              // already in place for everything that reads inst->world outside
              // frame() (world_to_body, damage_decal_add, hull_damage_add,
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

    // Native render interpolation (phase 3c): the frame-end capture, the
    // compose and the player's live mode + handover. All no-ops on a stale
    // iid. Composed from Python at the end of _sync_instance_transforms,
    // never inside frame() (tests/host/test_attached_lights_resolve_ordering).
    m.def("interp_track",
          [](scenegraph::InstanceId id, bool track, bool compose) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              const auto k = interp_key(id);
              if (!track) {
                  inst->interp_track = false;
                  inst->interp_compose = false;
                  inst->interp_live = false;
                  interp_forget(k);
                  return;
              }
              inst->interp_track = true;
              inst->interp_compose = compose;
              dauntless::Pose p{};
              if (!g_interp.has(k) && sim_source_pose(*inst, p)) {
                  g_interp.capture(k, p);  // new: prev = cur = live
              }
          },
          py::arg("iid"), py::arg("track"), py::arg("compose"),
          "Track a render instance in the native interpolation buffer (its "
          "sim source is snapshotted by interp_capture); compose=True also "
          "draws it in interp_compose. A newly tracked instance captures at "
          "once (prev = cur = live). track=False erases it.");
    m.def("interp_roll", []() { g_interp.roll(); },
          "Start a tick batch: prev = cur for every tracked instance.");
    m.def("interp_reseat",
          []() {
              g_world.for_each_alive([](scenegraph::Instance& inst) {
                  dauntless::Pose p{};
                  if (inst.interp_track && sim_source_pose(inst, p)) {
                      g_interp.set_previous(interp_key(inst.id), p);
                  }
              });
          },
          "prev = the live store pose for every tracked instance with a "
          "valid sim source (a multi-tick frame, before its last tick).");
    m.def("interp_capture",
          []() {
              g_world.for_each_alive([](scenegraph::Instance& inst) {
                  dauntless::Pose p{};
                  if (inst.interp_track && sim_source_pose(inst, p)) {
                      g_interp.capture(interp_key(inst.id), p);
                  }
              });
          },
          "The frame-end publish: cur = the live store pose for every tracked "
          "instance with a valid sim source; a stale source is skipped (its "
          "last snapshot is kept).");
    m.def("interp_snap",
          [](scenegraph::InstanceId id) {
              const auto* inst = g_world.get(id);
              dauntless::Pose p{};
              if (inst != nullptr && inst->interp_track &&
                  sim_source_pose(*inst, p)) {
                  g_interp.snap(interp_key(id), p);
              }
          },
          py::arg("iid"),
          "prev = cur = the live store pose: a discontinuity for one instance.");
    m.def("interp_reset_all",
          []() {
              g_interp.clear();
              g_interp_drawn.clear();
              g_handover.cancel();
          },
          "Drop every snapshot, last drawn pose and the handover (scene "
          "discontinuity). Tracked flags stay; the next capture re-seeds.");
    m.def("interp_set_live",
          [](scenegraph::InstanceId id, bool live) {
              if (auto* inst = g_world.get(id)) inst->interp_live = live;
          },
          py::arg("iid"), py::arg("live"),
          "A live instance is drawn from its sim source's store pose instead "
          "of the lerp (the manually flown player).");
    m.def("interp_handover_begin",
          [](scenegraph::InstanceId id) {
              if (!g_world.is_valid(id)) return;
              const auto k = interp_key(id);
              const auto it = g_interp_drawn.find(k);
              if (it == g_interp_drawn.end()) return;
              g_handover.begin(it->second);
              g_handover_key = k;
          },
          py::arg("iid"),
          "Freeze the pose interp_compose last drew for iid and ease from it "
          "to the true drawn pose over 0.36 s (re-freezes when active). One "
          "blend, one instance; a no-op when iid was never composed.");
    m.def("interp_handover_advance",
          [](double dt) { g_handover.advance(dt); }, py::arg("dt"),
          "Move the handover window on by dt seconds.");
    m.def("interp_handover_cancel", []() { g_handover.cancel(); },
          "Drop the handover: the eased instance is drawn at its true pose.");
    m.def("interp_handover_active", []() { return g_handover.active(); },
          "True while a handover is still being eased out.");
    m.def("interp_sample",
          [](scenegraph::InstanceId id, double alpha) -> py::object {
              const auto* inst = g_world.get(id);
              dauntless::Pose p{};
              if (inst == nullptr || !interp_drawn_pose(*inst, alpha, p)) {
                  return py::none();
              }
              return py::make_tuple(
                  py::make_tuple(p.pos[0], p.pos[1], p.pos[2]),
                  py::make_tuple(p.rot[0], p.rot[1], p.rot[2], p.rot[3],
                                 p.rot[4], p.rot[5], p.rot[6], p.rot[7],
                                 p.rot[8]));
          },
          py::arg("iid"), py::arg("alpha"),
          "The DRAWN pose interp_compose draws: live or lerp, then the "
          "handover blend. Set-local, no scale, no view offset: "
          "((x, y, z), row-major rot9), or None for an untracked or stale "
          "iid or one with nothing to draw.");
    m.def("interp_compose",
          [](double alpha) {
              g_world.for_each_alive([alpha](scenegraph::Instance& inst) {
                  if (!inst.interp_compose) return;
                  dauntless::Pose p{};
                  if (!interp_drawn_pose(inst, alpha, p)) return;
                  glm::mat3 linear;
                  glm::dvec3 translation;
                  dauntless::compose_world_linear_translation(
                      p, inst.sim_scale, linear, translation);
                  // The push clears interp_compose (a push wins); restore it.
                  g_world.set_world_transform_d(
                      inst.id, linear, translation + inst.sim_view_offset);
                  inst.interp_compose = true;
                  g_interp_drawn[interp_key(inst.id)] = p;
              });
          },
          py::arg("alpha"),
          "Draw every compose-tracked instance at its drawn pose "
          "(interp_sample) times its sim scale plus its view offset, and keep "
          "that pose as its last drawn one (what a handover freezes). Call "
          "before frame(), never from it.");

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

    // TEST-ONLY: the render interpolation twins (dauntless/interp_buffer.h),
    // so tests/host/test_native_interp_twin.py can pin them against
    // engine/core/interpolate.py and handover_smoother.py element for element.
    m.def("_test_only_interp_lerp",
          [](const std::array<double, 3>& prev_pos,
             const std::array<double, 9>& prev_rot,
             const std::array<double, 3>& cur_pos,
             const std::array<double, 9>& cur_rot, double alpha) {
              dauntless::Pose prev{}, cur{};
              std::copy(prev_pos.begin(), prev_pos.end(), prev.pos);
              std::copy(prev_rot.begin(), prev_rot.end(), prev.rot);
              std::copy(cur_pos.begin(), cur_pos.end(), cur.pos);
              std::copy(cur_rot.begin(), cur_rot.end(), cur.rot);
              const dauntless::Pose out = dauntless::lerp_pose(prev, cur, alpha);
              std::array<double, 3> pos{};
              std::array<double, 9> rot{};
              std::copy(out.pos, out.pos + 3, pos.begin());
              std::copy(out.rot, out.rot + 9, rot.begin());
              return std::make_pair(pos, rot);
          },
          py::arg("prev_pos"), py::arg("prev_rot9"), py::arg("cur_pos"),
          py::arg("cur_rot9"), py::arg("alpha"),
          "TEST ONLY: dauntless::lerp_pose, interpolate.lerp_transform's twin. "
          "Rotations are row-major nine doubles. Returns (pos3, rot9).");
    m.def("_test_only_handover_blend",
          [](const std::array<double, 3>& frozen_pos,
             const std::array<double, 9>& frozen_rot,
             const std::array<double, 3>& truth_pos,
             const std::array<double, 9>& truth_rot, double elapsed) {
              dauntless::Pose frozen{}, truth{};
              std::copy(frozen_pos.begin(), frozen_pos.end(), frozen.pos);
              std::copy(frozen_rot.begin(), frozen_rot.end(), frozen.rot);
              std::copy(truth_pos.begin(), truth_pos.end(), truth.pos);
              std::copy(truth_rot.begin(), truth_rot.end(), truth.rot);
              dauntless::HandoverBlend blend;
              blend.begin(frozen);
              blend.advance(elapsed);
              const dauntless::Pose out = blend.blend(truth);
              std::array<double, 3> pos{};
              std::array<double, 9> rot{};
              std::copy(out.pos, out.pos + 3, pos.begin());
              std::copy(out.rot, out.rot + 9, rot.begin());
              return std::make_pair(pos, rot);
          },
          py::arg("frozen_pos"), py::arg("frozen_rot9"), py::arg("truth_pos"),
          py::arg("truth_rot9"), py::arg("elapsed"),
          "TEST ONLY: dauntless::HandoverBlend after begin(frozen) and "
          "advance(elapsed), blended toward truth. Returns (pos3, rot9).");

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

    m.def("model_nearest_part",
          [](scenegraph::ModelHandle h,
             std::tuple<float, float, float> point) -> std::string {
              // SHIP units in, like model_nodes' bounds out.
              constexpr float kShipToModel = 100.0f;
              const assets::Model* model = resolve_model(h);
              if (model == nullptr) return "";
              const glm::vec3 p(std::get<0>(point) * kShipToModel,
                                std::get<1>(point) * kShipToModel,
                                std::get<2>(point) * kShipToModel);
              return renderer::nearest_model_part(*model, p);
          },
          py::arg("model"), py::arg("point"),
          "The candidate part (renderer::model_parts) whose rest-pose "
          "triangles lie nearest `point` (SHIP units, rest pose), or '' when "
          "the model is not loaded or has no part geometry. Which part an "
          "AUTHORED point -- a hardpoint mount, an emitter or running light -- "
          "is on; see part_severance.part_for_mount.");

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
          [](scenegraph::InstanceId id, bool drawn) -> py::object {
              auto* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* mdl = resolve_model(in->model_handle);
              if (!mdl) return py::none();
              std::vector<std::tuple<double, double, double>> out;
              out.reserve(mdl->surface_points.size());
              if (!drawn && in->sim_xform_index >= 0) {
                  // The hit pose (sim unless its source is stale): its
                  // translation is already VIEW space, in double.
                  const HitPose hp = hit_pose_of(*in, false);
                  for (const glm::vec3& p : mdl->surface_points) {
                      const glm::dvec3 w =
                          glm::dvec3(hp.linear * p) + hp.translation;
                      out.emplace_back(w.x, w.y, w.z);
                  }
                  return py::cast(out);
              }
              const glm::dvec3 o = view_offset_of(*in);
              for (const glm::vec3& p : mdl->surface_points) {
                  glm::vec4 w = in->world * glm::vec4(p, 1.0f);  // model -> render
                  out.emplace_back(w.x + o.x, w.y + o.y, w.z + o.z);
              }
              return py::cast(out);
          },
          py::arg("iid"), py::arg("drawn") = false,
          "VIEW-space sample of the instance model's hull surface points "
          "(spread across the hull) for VFX anchoring and "
          "GetRandomPointOnModel: on the SIM pose when a sim source is set, "
          "else -- or with drawn=True -- on the drawn pose.");

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
    m.def("set_instance_rigged",
          [](scenegraph::InstanceId id, bool rigged) -> bool {
              auto* in = g_world.get(id);
              if (in == nullptr) return false;
              in->rigged = rigged;
              return true;
          },
          py::arg("iid"), py::arg("rigged"),
          "Flag an instance as carrying an articulation rig. A rigged hull at "
          "the identity pose (no node overrides) still files each wear hit on "
          "the part it struck, so the damage follows the part when it swings "
          "(layered damage phase 4). False for a stale id.");
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
    m.def("set_instance_atmosphere",
          [](scenegraph::InstanceId id, py::object params) {
              scenegraph::Instance::Atmosphere a;
              if (!params.is_none()) {
                  auto t = params.cast<py::tuple>();
                  auto c = t[0].cast<std::array<float, 3>>();
                  auto s = t[1].cast<std::array<float, 3>>();
                  a.enabled = true;
                  a.color = {c[0], c[1], c[2]};
                  a.sunset_color = {s[0], s[1], s[2]};
                  a.thickness = t[2].cast<float>();
                  a.density = t[3].cast<float>();
                  a.limb = t[4].cast<float>();
                  // intensity (shell-halo brightness multiplier only) is an
                  // OPTIONAL 6th element added after this binding shipped;
                  // a 5-tuple caller keeps the struct default (9.0).
                  if (t.size() >= 6) a.intensity = t[5].cast<float>();
                  // mie (grey Mie strength) is an OPTIONAL 7th element;
                  // 5- and 6-tuple callers keep the struct default (0.2).
                  if (t.size() >= 7) a.mie = t[6].cast<float>();
              }
              g_world.set_atmosphere(id, a);
          },
          py::arg("id"), py::arg("params"),
          "Planet atmosphere (spec 2026-10-07): None disables; else "
          "(color, sunset_color, thickness, density, limb[, intensity[, mie]]), "
          "colours linear RGB; intensity defaults to 9.0 and mie to 0.2 "
          "when omitted.");
    m.def("set_instance_surface",
          [](scenegraph::InstanceId id, py::object params) {
              scenegraph::Instance::Surface s;
              if (!params.is_none()) {
                  auto t = params.cast<py::tuple>();
                  if (t.size() != 8) throw py::value_error("set_instance_surface: expected an 8-tuple");
                  s.type = t[0].cast<int>();
                  // type indexes the 6-entry live-params table (0 none .. 5 ocean).
                  if (s.type < 0 || s.type > 5)
                      throw py::value_error("set_instance_surface: type must be in [0, 5]");
                  auto o = t[1].cast<std::array<float, 3>>();
                  s.ocean = {o[0], o[1], o[2]};
                  s.has_ocean = t[2].cast<bool>();
                  s.ocean_tol = t[3].cast<float>();
                  s.strength = t[4].cast<float>();
                  s.albedo = t[5].cast<float>();
                  s.scale = t[6].cast<float>();
                  s.seed = t[7].cast<std::uint32_t>();
              }
              g_world.set_surface(id, s);
          },
          py::arg("id"), py::arg("params"),
          "Planet surface detail (spec 2026-10-08): None disables; else "
          "(type, ocean_rgb, has_ocean, ocean_tolerance, strength, albedo, scale, seed).");

    // ── Planet surface-detail developer tuning (spec 2026-10-08 §7) ────────
    m.def("planet_detail_target_type",
          []() -> int {
              if (!g_planet_detail) return 0;
              auto target = g_planet_detail->target();
              if (!target) return 0;
              const scenegraph::Instance* inst = g_world.get(*target);
              return inst ? inst->surface.type : 0;
          },
          "The planet surface-detail clipmap's current target's Surface.type, "
          "or 0 (none) with no target.");
    m.def("get_surface_type_params",
          [](int type) {
              if (type < 0 || type > 5)
                  throw py::value_error("get_surface_type_params: type out of range");
              return type_params_to_dict(renderer::planet_detail::live_params(
                  static_cast<renderer::planet_detail::SurfaceType>(type)));
          },
          py::arg("type"),
          "The live (dev-tunable) TypeParams for one surface type, as a dict.");
    m.def("set_surface_type_params",
          [](int type, py::dict params) {
              if (type < 0 || type > 5)
                  throw py::value_error("set_surface_type_params: type out of range");
              apply_type_params_from_dict(renderer::planet_detail::live_params(
                  static_cast<renderer::planet_detail::SurfaceType>(type)), params);
          },
          py::arg("type"), py::arg("params"),
          "Write named fields into live_params(type); unknown keys raise. Shape "
          "fields (base_wavelength_gu, max_octaves, gain, ridged, amplitude, "
          "crack_width, stretch, warp) change the baked field's shape_hash, "
          "which PlanetDetailPass detects and cold-refills; the other fields "
          "apply at the next bake with no extra wiring.");
    m.def("set_planet_detail_budget",
          [](long long cost) { if (g_planet_detail) g_planet_detail->set_budget(cost); },
          py::arg("cost"),
          "Per-frame bake cost budget for the planet surface-detail clipmap "
          "(spec default 65536*8).");
    m.def("set_planet_detail_debug",
          [](bool on) { if (g_planet_detail) g_planet_detail->set_debug(on); },
          py::arg("on"), "Tint the sampled clipmap level (debug visualisation).");

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
                                            py::none(), py::none(), 1.0f, false, false,
                                            {});
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
    m.def("set_viewscreen_target_instance",
          [](py::object iid) {
              if (py::isinstance<scenegraph::InstanceId>(iid)) {
                  g_viewscreen_target = iid.cast<scenegraph::InstanceId>();
              } else if (py::isinstance<py::int_>(iid) && iid.cast<long long>() == -1) {
                  g_viewscreen_target.reset();
              } else {
                  throw py::type_error(
                      "set_viewscreen_target_instance: an InstanceId, or -1 for none");
              }
          },
          py::arg("iid"),
          "The viewscreen feed's target hull (an InstanceId), or -1 for none. On "
          "the viewscreen render only this hull draws decks and rooms behind its "
          "holes; every other hull's holes are painted as far wreckage.");
    m.def("set_viewscreen_static_source",
          [](std::vector<std::string> paths) {
              if (g_viewscreen_static_pass)
                  g_viewscreen_static_pass->set_textures(paths);
          }, py::arg("paths"));
    m.def("set_viewscreen_bars",
          [](const std::string& name, const std::string& detail,
             std::tuple<int,int,int> dot) {
              g_viewscreen_bars.visible = true;
              g_viewscreen_bars.name = name;
              g_viewscreen_bars.detail = detail;
              g_viewscreen_bars.dot_rgb = {std::get<0>(dot) / 255.0f,
                                           std::get<1>(dot) / 255.0f,
                                           std::get<2>(dot) / 255.0f};
          }, py::arg("name"), py::arg("detail"), py::arg("dot_rgb"));
    m.def("clear_viewscreen_bars",
          []() { g_viewscreen_bars.visible = false; });
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
          [](float s) {
              g_bridge_ambient_scale = s;
              if (g_bridge_pass) g_bridge_pass->set_alert_ambient_scale(s);
          },
          py::arg("scale"),
          "Ambient multiplier for the bridge INTERIOR render only: the "
          "alert-level scale (engine/bridge_lighting.py: green x1.5, "
          "yellow/red x1.0). The comm-set viewscreen feed always renders with the "
          "unscaled bridge lighting, so viewscreen brightness stays constant "
          "across alert levels. Default 1.0.");

    m.def("set_bridge_alert_level",
          [](int level) {
              g_bridge_alert_level = level;
              if (g_bridge_pass) g_bridge_pass->set_alert_level(level);
          },
          py::arg("level"),
          "Bridge state (0 green, 1 yellow, 2 red, 3 offline, 4 special; anything else reads as "
          "green) choosing each bridge material's emissive sibling map "
          "(<stem>_emissive / _emissive_y / _emissive_r, falling back to the "
          "default). Main bridge view only; comm sets show the default. Hard "
          "switch. Default 0; init() and shutdown() reset it.");

    m.def("set_bridge_quality",
          [](int q) {
              g_bridge_quality = renderer::clamp_bridge_quality(q);
              if (g_bridge_pass)
                  g_bridge_pass->set_ao_settings(renderer::ao_settings_for(g_bridge_quality));
          },
          py::arg("level"),
          "Bridge rendering quality: 0 Low, 1 Medium (default), 2 High. "
          "Out-of-range clamps. Drives the bridge AO's sample count and "
          "target resolution scale.");

    m.def("reload_bridge_panels",
          [] {
              if (g_bridge_pass) g_bridge_pass->reload_panels();
          },
          "Developer reload: re-probe every Lottie bridge panel's files and "
          "clear the warning set. No-op before the bridge pass exists.");

    m.def("set_bridge_ao_tuning",
          [](float radius, float strength, float bias, float bias_dist,
             float bias_facing, float min_len, float main_direct,
             float main_final, int detail_samples,
             float detail_radius, float detail_strength, float detail_bias,
             float detail_direct, float detail_final) {
              g_bridge_ao_tuning = {radius, strength, bias, bias_dist,
                                    bias_facing, min_len, main_direct,
                                    main_final, detail_samples,
                                    detail_radius, detail_strength, detail_bias,
                                    detail_direct, detail_final};
              if (g_bridge_pass) g_bridge_pass->set_ao_tuning(g_bridge_ao_tuning);
          },
          py::arg("radius"), py::arg("strength"), py::arg("bias"),
          py::arg("bias_dist"), py::arg("bias_facing"), py::arg("min_len"),
          py::arg("main_direct"), py::arg("main_final"),
          py::arg("detail_samples"), py::arg("detail_radius"),
          py::arg("detail_strength"), py::arg("detail_bias"),
          py::arg("detail_direct"), py::arg("detail_final"),
          "Bridge AO kernel look (renderer::BridgeAoTuning): the main kernel's "
          "radius/strength/bias, its distance bias and how far that is scaled "
          "by grazing (0..1), its shortest sample as a fraction of the radius, "
          "how much of it darkens spot/area diffuse or applies after the "
          "diffuse ceiling (0..1), the small detail kernel (0 samples = off) and how much of it also "
          "darkens spot/area diffuse or applies after the diffuse ceiling (0..1). "
          "Developer dials.");

    m.def("bridge_quality",
          [] { return static_cast<int>(g_bridge_quality); },
          "Current bridge rendering quality level (see set_bridge_quality).");

    m.def("set_bridge_debug_view",
          [](int v) {
              if (!dauntless::is_developer_mode()) return;
              v = std::clamp(v, 0, 11);
              g_bridge_debug_view = v;
              if (g_bridge_pass)
                  g_bridge_pass->set_debug_view(
                      static_cast<renderer::BridgeDebugView>(v));
          },
          py::arg("view"),
          "DEV ONLY (--developer; no-op otherwise): Developer Options -> "
          "Lighting tab's Bridge Debug View row. 0 Off, 1 Normals, "
          "2 Light Only, 3 AO Only, 4 Triangle ID, 5 Mesh ID, 6 Roughness, "
          "7 Metalness, 8 Specular Only, 9 Probe Mirror, 10 Map Normals, "
          "11 Reflection Layers (6-11 show only where bridge PBR runs).");

    // Bridge PBR per-shape material overrides (spec 2026-10-08-bridge-emitters
    // §9.2 source B). Production data: NOT developer-gated. None / stale clears.
    m.def("set_bridge_material_overrides",
          [](py::object instance_id, std::vector<std::tuple<int, float, float>> overrides) {
              if (!g_bridge_pass) return;
              if (instance_id.is_none()) { g_bridge_pass->clear_material_overrides(); return; }
              scenegraph::Instance* inst = nullptr;
              try {
                  inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
              } catch (const py::cast_error&) {
                  inst = nullptr;   // not an InstanceId: treated as stale
              }
              if (inst == nullptr) { g_bridge_pass->clear_material_overrides(); return; }
              std::vector<renderer::BridgeMaterialOverride> v;
              v.reserve(overrides.size());
              for (const auto& [mesh, r, mt] : overrides) v.push_back({mesh, r, mt});
              g_bridge_pass->set_material_overrides(inst->model_handle, std::move(v));
          },
          py::arg("instance_id"), py::arg("overrides"),
          "Per-mesh roughness/metalness overrides for the bridge (mesh, rough, metal; "
          "< 0 = none). None or a stale id clears. Never raises.");

    // Bridge static spot lights (spec 2026-10-08-bridge-emitters §9.6, plan
    // 2026-10-09-bridge-pbr Task 7). Production: NOT developer-gated. Each
    // spot is (pos3, dir3, inner_deg, outer_deg, range, (r, g, b), intensity);
    // inner_deg / outer_deg are HALF-angles from the axis. Degrees ->
    // cosines, direction normalised, colour x intensity -> radiance. A spot
    // with ANY non-finite input (position, direction before normalising,
    // angles, range, colour, intensity) is dropped -- a NaN reaching the
    // shader becomes a NaN bloom square. Returns the dropped count: invalid
    // spots PLUS valid ones beyond kBridgeMaxSpots (also before init(), when
    // nothing is stored: the spots are pushed at bridge load, after the pass
    // exists). BridgePass::set_spots marks the probes dirty itself when the
    // list changed. Never raises for a stale/empty state.
    m.def("set_bridge_spots",
          [](const std::vector<std::tuple<std::tuple<float, float, float>,
                                          std::tuple<float, float, float>,
                                          float, float, float,
                                          std::tuple<float, float, float>,
                                          float>>& spots,
             py::object captures) -> std::size_t {
              // Spec 2026-10-08-bridge-emitters §11.4: per-spot probe-capture
              // colours (green, yellow/red), in input order, x that spot's
              // intensity. A length mismatch ignores them (the PBR-step rule:
              // the captures see the radiance).
              const std::vector<BridgeCaptureRow> caps =
                  parse_bridge_captures(captures, spots.size());
              std::vector<renderer::BridgeSpot> v;
              v.reserve(spots.size());
              std::size_t invalid = 0;
              std::size_t index = 0;
              for (const auto& s : spots) {
                  const std::size_t i = index++;
                  const auto& [pos, dir, inner_deg, outer_deg, range, rgb, intensity] = s;
                  if (!bridge_finite3(bridge_v3(pos)) || !bridge_finite3(bridge_v3(dir)) ||
                      !bridge_finite3(bridge_v3(rgb)) ||
                      !std::isfinite(inner_deg) || !std::isfinite(outer_deg) ||
                      !std::isfinite(range) || !std::isfinite(intensity) ||
                      !bridge_finite3(bridge_v3(rgb) * intensity) ||
                      (!caps.empty() && !bridge_capture_finite(caps[i], intensity))) {
                      ++invalid;
                      continue;
                  }
                  renderer::BridgeSpot sp;
                  sp.position = bridge_v3(pos);
                  const glm::vec3 d = bridge_v3(dir);
                  const float len = glm::length(d);
                  // A zero / non-finite axis points straight down (-Z, the
                  // bridge's floor) rather than feeding NaN to the shader.
                  sp.direction = (std::isfinite(len) && len > 1e-6f)
                      ? d / len : glm::vec3(0.0f, 0.0f, -1.0f);
                  // The outer edge is never inside the inner one.
                  const float inner = std::clamp(inner_deg, 0.0f, 180.0f);
                  const float outer = std::clamp(std::max(outer_deg, inner), 0.0f, 180.0f);
                  sp.cos_inner = std::cos(glm::radians(inner));
                  sp.cos_outer = std::cos(glm::radians(outer));
                  sp.range = std::max(range, 0.0f);
                  sp.radiance = bridge_v3(rgb) * intensity;
                  if (!caps.empty()) apply_bridge_capture(sp, caps[i], intensity);
                  v.push_back(sp);
              }
              const std::size_t cap = static_cast<std::size_t>(renderer::kBridgeMaxSpots);
              if (!g_bridge_pass) return invalid + (v.size() > cap ? v.size() - cap : 0);
              return invalid + g_bridge_pass->set_spots(std::move(v));
          },
          py::arg("spots"), py::arg("captures") = py::none(),
          "Static bridge spot lights: [(pos3, dir3, inner_deg, outer_deg, range, "
          "(r, g, b), intensity)]; inner_deg/outer_deg are HALF-angles from the "
          "axis. Spots with any non-finite value are dropped; the rest keep the "
          "first 32. Returns the dropped count (invalid + over the cap). Marks "
          "the reflection probes dirty when the list differs from the current "
          "one (never for an identical list). Never raises for a stale state. "
          "captures (optional): [((r,g,b) green, (r,g,b) yellow/red)] per spot, x "
          "its intensity: what each probe capture sees; the live colour "
          "(set_bridge_spot_colours) then never recaptures (spec "
          "2026-10-08-bridge-emitters §11.4). A length mismatch ignores them.");

    m.def("set_bridge_spot_colours",
          [](const std::vector<std::tuple<float, float, float>>& radiance) {
              if (!g_bridge_pass) return;
              std::vector<glm::vec3> v;
              v.reserve(radiance.size());
              for (const auto& [r, g, b] : radiance) v.emplace_back(r, g, b);
              g_bridge_pass->set_spot_radiance(v);
          },
          py::arg("radiance"),
          "Live LINEAR radiance per bridge spot, in set_bridge_spots order (spec "
          "2026-10-08-bridge-emitters §11.4). Extra entries ignored, missing kept, "
          "non-finite -> 0. Never dirties the probes; no-op before init.");

    // Static bridge area lights (spec 2026-10-08-bridge-emitters §16.3): rows
    // (centre, half_u, half_v, range, rgb, intensity); each emits toward
    // cross(half_u, half_v). A row with any non-finite value, a zero-size
    // rectangle (|half_u x half_v| < 1e-8) or range <= 0 is dropped -- a NaN
    // normal reaching the shader becomes a NaN bloom square. Returns the
    // dropped count (invalid + over kBridgeMaxAreaLights; also before init).
    // Captures as set_bridge_spots. BridgePass marks the probes dirty itself.
    m.def("set_bridge_area_lights",
          [](const std::vector<std::tuple<std::tuple<float, float, float>,
                                          std::tuple<float, float, float>,
                                          std::tuple<float, float, float>,
                                          float,
                                          std::tuple<float, float, float>,
                                          float>>& areas,
             py::object captures, py::object joins) -> std::size_t {
              const std::vector<BridgeCaptureRow> caps =
                  parse_bridge_captures(captures, areas.size());
              // Spec §16.8: per-row join bits (pbr::area_join_weight), in
              // input order; anything unusable means no joins.
              std::vector<int> join_bits;
              if (!joins.is_none()) {
                  try {
                      join_bits = joins.cast<std::vector<int>>();
                  } catch (const py::cast_error&) {
                      join_bits.clear();
                  }
                  if (join_bits.size() != areas.size()) join_bits.clear();
              }
              std::vector<renderer::BridgeAreaLight> v;
              v.reserve(areas.size());
              std::size_t invalid = 0, index = 0;
              for (const auto& a : areas) {
                  const std::size_t i = index++;
                  const auto& [c, u, w, range, rgb, intensity] = a;
                  const glm::vec3 hu = bridge_v3(u), hv = bridge_v3(w);
                  if (!bridge_finite3(bridge_v3(c)) || !bridge_finite3(hu) ||
                      !bridge_finite3(hv) || !bridge_finite3(bridge_v3(rgb)) ||
                      !std::isfinite(range) || !(range > 0.0f) || !std::isfinite(intensity) ||
                      !bridge_finite3(bridge_v3(rgb) * intensity) ||
                      !(glm::length(glm::cross(hu, hv)) >= 1e-8f) ||
                      (!caps.empty() && !bridge_capture_finite(caps[i], intensity))) {
                      ++invalid;
                      continue;
                  }
                  renderer::BridgeAreaLight al;
                  al.center = bridge_v3(c);
                  al.half_u = hu;
                  al.half_v = hv;
                  al.range = range;
                  al.radiance = bridge_v3(rgb) * intensity;
                  if (!caps.empty()) apply_bridge_capture(al, caps[i], intensity);
                  if (!join_bits.empty()) al.joins = join_bits[i] & 3;
                  v.push_back(al);
              }
              const std::size_t cap = static_cast<std::size_t>(renderer::kBridgeMaxAreaLights);
              if (!g_bridge_pass) return invalid + (v.size() > cap ? v.size() - cap : 0);
              return invalid + g_bridge_pass->set_area_lights(std::move(v));
          },
          py::arg("areas"), py::arg("captures") = py::none(), py::arg("joins") = py::none(),
          "Static bridge area lights (strips / panels): [(centre3, half_u3, half_v3, "
          "range, (r, g, b), intensity)], emitting toward cross(half_u, half_v). "
          "Invalid rows (non-finite, zero size, range <= 0) are dropped; the rest "
          "keep the first 32. Returns the dropped count. captures as "
          "set_bridge_spots. joins: per-row join bits, bit 0 = joined at -u, bit 1 = "
          "at +u, spec §16.8; a wrong length is ignored. Never raises for a stale "
          "state.");

    m.def("set_bridge_area_colours",
          [](const std::vector<std::tuple<float, float, float>>& radiance) {
              if (!g_bridge_pass) return;
              std::vector<glm::vec3> v;
              v.reserve(radiance.size());
              for (const auto& [r, g, b] : radiance) v.emplace_back(r, g, b);
              g_bridge_pass->set_area_radiance(v);
          },
          py::arg("radiance"),
          "Live LINEAR radiance per bridge area light, in set_bridge_area_lights "
          "order. Extra entries ignored, missing kept, non-finite -> 0. Never "
          "dirties the probes; no-op before init.");

    m.def("set_bridge_glow",
          [](py::object instance_id,
             const std::vector<std::tuple<int, int, std::tuple<float, float, float>, float>>& glow) {
              if (!g_bridge_pass) return;
              scenegraph::Instance* inst = nullptr;
              if (!instance_id.is_none()) {
                  try {
                      inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
                  } catch (const py::cast_error&) {
                      inst = nullptr;   // not an InstanceId: treated as stale
                  }
              }
              if (inst == nullptr) { g_bridge_pass->clear_glow(); return; }
              std::vector<renderer::BridgeGlow> v;
              v.reserve(glow.size());
              for (const auto& [mesh, src, rgb, level] : glow) {
                  const glm::vec3 c(std::get<0>(rgb), std::get<1>(rgb), std::get<2>(rgb));
                  if (src < 0 || src > 2 || !std::isfinite(c.x) || !std::isfinite(c.y) ||
                      !std::isfinite(c.z) || !std::isfinite(level))
                      continue;
                  v.push_back({mesh, src, c, level});
              }
              g_bridge_pass->set_glow(inst->model_handle, std::move(v));
          },
          py::arg("instance_id"), py::arg("glow"),
          "Per-mesh emitter glow for the bridge (spec 2026-10-08-bridge-emitters "
          "§11.2): [(mesh, src 0 emissive map / 1 albedo / 2 flat, (r,g,b) display "
          "space, level)]. None or a stale id clears; invalid entries are dropped. "
          "Never dirties the probes; never raises.");

    m.def("set_bridge_pbr_enabled",
          [](bool on) {
              if (!dauntless::is_developer_mode() || !g_bridge_pass) return;
              g_bridge_pass->set_pbr_enabled(on);
          },
          py::arg("on"), "Developer-only A/B: bridge PBR on/off (default on).");

    // Bridge reflection probes (spec 2026-10-08-bridge-emitters §9.3, plan
    // 2026-10-09-bridge-pbr Task 6). Production: NOT developer-gated. Before
    // init() they only stash their values, which init() applies.
    m.def("set_bridge_probe_origin",
          [](std::tuple<float, float, float> p) {
              g_bridge_probe.origin = glm::vec3(std::get<0>(p), std::get<1>(p),
                                                std::get<2>(p));
              if (g_bridge_pass) g_bridge_pass->set_probe_origin(g_bridge_probe.origin);
          },
          py::arg("origin"),
          "Bridge reflection probe capture point (x, y, z), bridge world space "
          "(the captain's-chair eye). Takes effect at the next capture.");

    m.def("set_bridge_probe_scales",
          [](const std::vector<float>& scales) {
              if (scales.size() != static_cast<std::size_t>(renderer::kBridgeStates))
                  throw py::value_error("set_bridge_probe_scales needs 5 values");
              for (int i = 0; i < renderer::kBridgeStates; ++i)
                  g_bridge_probe.scales[static_cast<std::size_t>(i)] =
                      scales[static_cast<std::size_t>(i)];
              if (g_bridge_pass) g_bridge_pass->set_probe_scales(g_bridge_probe.scales);
          },
          py::arg("scales"),
          "Ambient multipliers the five state probes (green, yellow, red, "
          "offline, special) are captured with (x the bridge lighting's "
          "ambient). Take effect at the next capture.");

    m.def("set_bridge_probe_layers",
          [](const std::vector<int>& states,
             const std::vector<std::uint64_t>& identities) -> std::size_t {
              if (identities.size() != states.size())
                  throw py::value_error(
                      "set_bridge_probe_layers needs one identity per state");
              if (!g_bridge_pass) return 0;
              return g_bridge_pass->set_probe_layers(states, identities);
          },
          py::arg("states"), py::arg("identities"),
          "The state each animation layer's probe belongs to (spec 2026-10-17 "
          "§4.4), layer k = probe 5+k, and each layer's identity (a stable "
          "uint64 of its state and wave key): a layer whose identity at its "
          "index changed reads as absent until its own capture lands. States "
          "outside 0-4 are dropped with their identity; returns how many. "
          "Raises ValueError when the lists differ in length; otherwise a "
          "no-op before init.");

    m.def("set_bridge_glow_captures",
          [](py::object instance_id, py::object rows) {
              if (!g_bridge_pass) return;
              scenegraph::Instance* inst = nullptr;
              if (!instance_id.is_none()) {
                  try {
                      inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
                  } catch (const py::cast_error&) {
                      inst = nullptr;   // not an InstanceId: treated as stale
                  }
              }
              if (inst == nullptr) { g_bridge_pass->clear_glow_captures(); return; }
              std::vector<renderer::BridgeGlowCapture> v;
              try {
                  for (auto item : rows) {
                      auto t = item.cast<std::tuple<int, int, std::vector<BridgeV3>,
                                                    std::vector<int>, std::vector<BridgeV3>>>();
                      const auto& caps = std::get<2>(t);
                      const auto& layers = std::get<3>(t);
                      const auto& rgbs = std::get<4>(t);
                      const std::size_t n = static_cast<std::size_t>(renderer::kBridgeStates);
                      const int src = std::get<1>(t);
                      if (caps.size() != n || layers.size() != n || rgbs.size() != n ||
                          src < 0 || src > 2)
                          continue;
                      renderer::BridgeGlowCapture gc;
                      gc.mesh = std::get<0>(t);
                      gc.src = src;
                      bool finite = true;
                      for (std::size_t i = 0; i < n; ++i) {
                          gc.base[i] = bridge_v3(caps[i]);
                          gc.layer[i] = layers[i];
                          gc.layer_rgb[i] = bridge_v3(rgbs[i]);
                          finite = finite && bridge_finite3(gc.base[i]) &&
                                   bridge_finite3(gc.layer_rgb[i]);
                      }
                      if (finite) v.push_back(gc);
                  }
              } catch (const py::cast_error&) {
                  g_bridge_pass->clear_glow_captures();
                  return;
              }
              g_bridge_pass->set_glow_captures(inst->model_handle, std::move(v));
          },
          py::arg("instance_id"), py::arg("rows"),
          "Per-mesh glow contribution to the probes (spec 2026-10-17 §4.5): "
          "[(mesh, src, caps5, layers5, layer_rgbs5)], display space (the pass "
          "decodes). None or a stale id clears; non-finite rows are dropped. "
          "Signature input only; never raises.");

    m.def("set_bridge_probe_state",
          [](int state, float dt) {
              // Spec 2026-10-17 §4.2: the base cross-fade runs in the pass.
              // No pass yet: nothing to fade, the next frame pushes again.
              if (g_bridge_pass) g_bridge_pass->set_probe_state(state, dt);
          },
          py::arg("state"), py::arg("dt"),
          "Shown bridge state (0-4) and the paused-aware bridge dt; the pass "
          "cross-fades the base probe weights (dt <= 0 freezes). Never raises.");

    m.def("set_bridge_layer_values",
          [](const std::vector<float>& values) {
              std::vector<float> v;
              v.reserve(values.size());
              for (float x : values)
                  v.push_back(std::isfinite(x) ? std::clamp(x, 0.0f, 1.0f) : 0.0f);
              if (g_bridge_pass) g_bridge_pass->set_layer_values(std::move(v));
          },
          py::arg("values"),
          "Live value per reflection layer (w^2.2), clamped to [0, 1]; "
          "non-finite -> 0. Never raises.");

    m.def("bridge_probe_stash",
          [] {
              py::dict d;
              const glm::vec3 o = g_bridge_probe.origin;
              d["origin"] = py::make_tuple(o.x, o.y, o.z);
              py::tuple sc(renderer::kBridgeStates);
              for (int i = 0; i < renderer::kBridgeStates; ++i)
                  sc[static_cast<std::size_t>(i)] = g_bridge_probe.scales[static_cast<std::size_t>(i)];
              d["scales"] = sc;
              d["capture_pending"] = g_bridge_probe.capture_pending;
              return d;
          },
          "Read-only test snapshot of the process-wide probe stash the "
          "set_bridge_probe_* bindings write (it survives shutdown()/init() by "
          "design): origin, scales, capture_pending.");

    m.def("bridge_probe_state",
          []() -> py::object {
              if (!g_bridge_pass) return py::none();
              py::dict d;
              const glm::vec3 o = g_bridge_pass->probe_origin();
              d["origin"] = py::make_tuple(o.x, o.y, o.z);
              py::tuple sc(renderer::kBridgeStates);
              for (int i = 0; i < renderer::kBridgeStates; ++i)
                  sc[static_cast<std::size_t>(i)] = g_bridge_pass->probe_scale(i);
              d["scales"] = sc;
              d["probe_count"] = g_bridge_pass->probe_count();
              d["capture_pending"] = !g_bridge_pass->probes_settled();
              d["probes_valid"] = g_bridge_pass->probes_valid();
              d["alert_ambient_scale"] = g_bridge_pass->alert_ambient_scale();
              d["alert_level"] = g_bridge_pass->alert_level();
              py::tuple bw(renderer::kBridgeStates);
              for (int i = 0; i < renderer::kBridgeStates; ++i)
                  bw[static_cast<std::size_t>(i)] = g_bridge_pass->base_weight(i);
              d["base_weights"] = bw;
              return d;
          },
          "Test/diagnostic snapshot of the bridge pass's probe state: origin, "
          "scales, probe_count (5 bases + one per layer), capture_pending "
          "(the time-sliced capture queue has work or a probe in flight), "
          "probes_valid (the shown state's base holds a capture), "
          "alert_ambient_scale, alert_level, base_weights (each state base's "
          "cross-fade weight); None before init().");

    m.def("bridge_probe_signatures",
          []() -> py::object {
              if (!g_bridge_pass) return py::none();
              py::list l;
              for (int i = 0; i < g_bridge_pass->probe_count(); ++i)
                  l.append(py::int_(g_bridge_pass->probe_signature(i)));
              return l;
          },
          "Test/diagnostic: the input signature of every probe (kBridgeStates "
          "bases, then one per layer); None before init().");

    m.def("request_bridge_probe_capture",
          [] {
              if (g_bridge_pass) g_bridge_pass->request_probe_capture();
              else g_bridge_probe.capture_pending = true;
          },
          "Recapture every bridge reflection probe, time-sliced over the "
          "following main-bridge frames (bridge load); nothing is captured "
          "before the first request. Afterwards an input change (spots, "
          "overrides, scales, ...) queues the probes it touches by itself. "
          "Never per frame.");

    m.def("bridge_debug_view",
          [] { return g_bridge_debug_view; },
          "Active bridge debug view (see set_bridge_debug_view); 0 when "
          "not under --developer.");

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
              const auto [p, look] =
                  parse_system_nebula_profile(desc.cast<py::dict>());
              // Validated above even with the host down; the upload needs GL.
              if (!g_system_nebula_pass) return;
              g_system_nebula_pass->set_profile(p, look);
          },
          py::arg("profile"),
          "Set (dict) or clear (None) the system-scale nebula profile: keys "
          "r, nebula (lists, GU / 0-1), k_sys, star_radius, cloud_rgb, "
          "star_rgb (3-tuples), optional g, floor, scatter, far_gu. Builds "
          "(CPU, seconds; cached per session, see system_nebula_prebuild) "
          "and uploads the far-field table. Drawn "
          "whenever Volumetric Nebulae is on.");
    m.def("system_nebula_prebuild",
          [](py::dict d) {
              const auto [p, look] = parse_system_nebula_profile(d);
              // Validated even with the host down; the cache lives in the pass.
              if (!g_system_nebula_pass) return;
              g_system_nebula_pass->prebuild(p, look);
          },
          py::arg("profile"),
          "Start building the system nebula far-field table for `profile` "
          "(same keys as set_system_nebula_profile) on a worker thread and "
          "return at once; a later set_system_nebula_profile with the same "
          "dict then costs only the upload. No-op if already built/building.");
    m.def("system_nebula_prebuilt",
          [](py::dict d) {
              const auto [p, look] = parse_system_nebula_profile(d);
              if (!g_system_nebula_pass) return false;
              return g_system_nebula_pass->prebuilt(p, look);
          },
          py::arg("profile"),
          "True once `profile`'s far-field table is built (by a prebuild or "
          "an earlier set_system_nebula_profile). Never blocks. False with "
          "the host down.");
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
          "g or floor rebuilds the far-field table when a profile is "
          "already uploaded (measured ~7 s for Vesuvi, 15 rows, on the Debug "
          "build; ~0.2 s for 3-row systems; cached per session and prebuilt "
          "during the warp tunnel); lane_size/lane_contrast/near_range never "
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
          [](py::list entries, const std::vector<std::tuple<float, float, float>>& view_dirs) {
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
              // A view set that is not the octahedral bake layout draws no
              // billboards at all (far::make_impostor_views): say so once.
              if (!dirs.empty() && renderer::far::make_impostor_views(dirs).grid < 2)
                  std::fprintf(stderr,
                               "[far] %zu impostor view dirs are not an octahedral N x N "
                               "layout: rock billboards disabled\n",
                               dirs.size());
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
          py::arg("entries"), py::arg("view_dirs"),
          "Catalogue for the far tier: [{'albedo', 'normal' (atlas paths, empty "
          "or None = no impostor), 'avg_albedo': (r, g, b)}, ...] by catalogue "
          "index, and the impostor bake's view directions (glTF axes). "
          "Optional per entry: 'kind' ('fragment' | 'major'), 'family', "
          "'lod0'/'lod1' model handles, 'bound_radius_mu' -- a silicate "
          "fragment / major with both handles streams in the near band.");
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
              }
              g_minor_field.set_specks(on, g_far_field.dials().tiers.p_min);
          },
          py::arg("enabled"),
          "Turn the far tier on or off. Off: no build, no draws, every flagged "
          "rock back to mesh-only, minors stop emitting specks, and the near "
          "band drops its cells.");
    m.def("far_enabled", []() { return g_far_enabled; });
    m.def("rock_specks_set_enabled",
          [](bool on) { g_rock_specks_enabled = on; if (!on) g_speck_band.clear(); },
          py::arg("enabled"), "The rock-field speck band on or off.");
    m.def("rock_specks_enabled", []() { return g_rock_specks_enabled; });
    m.def("rock_puffs_set_enabled", [](bool on) { g_rock_puffs_enabled = on; },
          py::arg("enabled"), "The rock-field puffs on or off.");
    m.def("rock_puffs_enabled", []() { return g_rock_puffs_enabled; });
    m.def("hull_stats",
          []() {
              // The last frame's hull load: the opaque submit summed over
              // every camera it drew (main view + viewscreen feed), and the
              // shadow casters. Read by frame_profiler.hull_summary.
              py::dict d;
              const renderer::HullDrawStats none;
              const renderer::HullDrawStats& o = g_submitter ? g_submitter->opaque_stats() : none;
              d["opaque_instances"] = o.instances;
              d["opaque_culled"] = o.culled;
              d["opaque_mesh_draws"] = o.mesh_draws;
              d["shadow_instances"] = g_shadow_hull_stats.instances;
              d["shadow_culled"] = g_shadow_hull_stats.culled;
              d["shadow_mesh_draws"] = g_shadow_hull_stats.mesh_draws;
              return d;
          });
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
              return d;
          },
          "{'sources', 'rocks', 'near_cells', 'near_small', 'near_large', "
          "'near_ghosted'} now; {'near_meshes', 'near_billboards', "
          "'near_fading' (of the billboards, translucent)} built, "
          "{'speck_cells'} now, {'band_specks', 'puffs'} submitted, and "
          "{'impostors', 'specks' (far + minor), "
          "'draw_calls'} summed over the cameras the last frame drew.");
    m.def("far_prefetch_atlases",
          []() {
              if (g_far_pass) g_far_pass->prefetch_atlases();
          },
          "Queue every impostor atlas the far pass has not loaded, failed "
          "or queued for decoding on worker threads (at most "
          "kMaxAtlasDecodesInFlight, which take queued atlases themselves "
          "until none is left). No GL work; a no-op with no far pass.");
    m.def("far_pump_atlas_uploads",
          [](int max_uploads) {
              return g_far_pass ? g_far_pass->pump_atlas_uploads(max_uploads) : 0;
          },
          py::arg("max_uploads"),
          "Upload at most `max_uploads` prefetched atlases whose decode has "
          "finished (never waits) and return how many are still pending "
          "(queued, decoding, or decoded and not uploaded); 0 with no far "
          "pass.");
    m.def("far_clear",
          []() {
              far_zero_fades(g_far_flagged_keys);
              g_far_flagged_keys.clear();
              g_far_field.clear();
              g_near_field.set_sources(g_far_field.active_sources());
              g_near_field.clear();
              g_near_field.reset_player();
              g_near_player.reset();
              g_speck_band.set_sources(g_far_field.active_sources());
              g_speck_band.clear();
              g_puff_field.clear();
          },
          "Drop sources, flagged rocks (back to mesh-only), frame, the near "
          "band's cells, contacts, sweep state and player, the speck band's "
          "cells and drawn set, and the puffs; keeps the catalogue.");
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
    m.def("rockfield_set_promoted",
          [](py::list keys) {
              std::unordered_set<std::uint64_t> s;
              for (const auto& k : keys) s.insert(k.cast<std::uint64_t>());
              g_speck_band.set_excluded(s);   // copied: its rebuild runs on a worker
              g_near_field.set_excluded(std::move(s));
          },
          py::arg("keys"),
          "Large near-rock keys promoted to real objects or destroyed "
          "(rock-promotion): the near band draws nothing and reports no contact "
          "for them, and the speck band draws no speck. Replaces the list.");
    m.def("rockfield_query_large",
          [](std::tuple<double, double, double> c, double radius, float min_r) {
              py::list out;
              for (const auto& h : g_near_field.query_large(
                       {std::get<0>(c), std::get<1>(c), std::get<2>(c)}, radius, min_r)) {
                  py::dict d;
                  d["key"] = h.key;
                  d["pos"] = py::make_tuple(h.rock.pos_sys.x, h.rock.pos_sys.y, h.rock.pos_sys.z);
                  d["radius"] = h.rock.radius;
                  d["rock"] = h.rock.rock;
                  d["axis"] = py::make_tuple(h.rock.tumble_axis.x, h.rock.tumble_axis.y, h.rock.tumble_axis.z);
                  d["rate"] = h.rock.tumble_rate;
                  d["phase"] = h.rock.phase;
                  out.append(d);
              }
              return out;
          },
          py::arg("centre_sys"), py::arg("radius_gu"), py::arg("min_radius_gu"),
          "Large near rocks (every current source) with radius >= min_radius_gu "
          "within radius_gu of centre_sys (SYSTEM coords), nearest first: "
          "[{'key', 'pos' (system), 'radius', 'rock' (catalogue index), 'axis', "
          "'rate', 'phase'}, ...]. Includes promoted keys. Camera-independent.");
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
                  d["noise_scale_gu"] = src.noise_scale_gu;
                  d["noise_contrast"] = src.noise_contrast;
                  d["noise_octaves"] = src.noise_octaves;
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
    m.def("atmosphere_debug",
          [](scenegraph::InstanceId id) -> py::object {
              const auto* inst = g_world.get(id);
              if (inst == nullptr) throw py::value_error("unknown instance");
              const auto& a = inst->atmosphere;
              if (!a.enabled) return py::none();
              return py::make_tuple(py::make_tuple(a.color.r, a.color.g, a.color.b),
                                    py::make_tuple(a.sunset_color.r, a.sunset_color.g, a.sunset_color.b),
                                    a.thickness, a.density, a.limb, a.intensity, a.mie);
          },
          py::arg("id"), "Test-only read-back of an instance's atmosphere.");

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
                  // Optional: the light's body distance (the star). Absent =
                  // a lightning flash, whose shafts only the sky casts.
                  if (d.contains("distance"))
                      g.distance = d["distance"].cast<float>();
                  g_nebula_godrays.push_back(g);
              }
          },
          py::arg("flashes"),
          "Set the god-ray lights: lightning flashes and the star (with its "
          "render-space \"distance\").");

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
                  if (d.contains("tint")) {
                      auto t = d["tint"].cast<std::tuple<float, float, float>>();
                      s.tint = {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
                  }
                  g_shockwaves.push_back(std::move(s));
              }
          },
          py::arg("shockwaves"),
          "Replace the active warp-core breach shockwaves: a list of dicts with "
          "keys world_center (a (cx,cy,cz) tuple), max_radius, age, lifetime.");

    m.def("set_warp_in_flashes",
          [](const std::vector<py::dict>& descs) {
              g_warp_in_flashes.clear();
              g_warp_in_flashes.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::WarpInFlashDescriptor f;
                  auto c = d["world_center"].cast<std::tuple<float, float, float>>();
                  f.world_center = {std::get<0>(c), std::get<1>(c), std::get<2>(c)};
                  auto fw = d["forward"].cast<std::tuple<float, float, float>>();
                  f.forward  = {std::get<0>(fw), std::get<1>(fw), std::get<2>(fw)};
                  f.radius   = d["radius"].cast<float>();
                  f.age      = d["age"].cast<float>();
                  f.lifetime = d["lifetime"].cast<float>();
                  g_warp_in_flashes.push_back(f);
              }
          },
          py::arg("flashes"),
          "Replace the active warp-in flashes (warp-in spec 6.3; NOT the "
          "screen-space set_warp_flash_intensity): a list of dicts with keys "
          "world_center (render-space (x,y,z)), forward (unit (x,y,z)), "
          "radius (GU), age, lifetime.");

    m.def("set_warp_in_flash_params",
          [](const py::dict& d) {
              auto& p = g_warp_in_flash_params;
              if (d.contains("core_radii"))   p.core_radii   = d["core_radii"].cast<float>();
              if (d.contains("streak_radii")) p.streak_radii = d["streak_radii"].cast<float>();
              if (d.contains("ring_radii"))   p.ring_radii   = d["ring_radii"].cast<float>();
              if (d.contains("intensity"))    p.intensity    = d["intensity"].cast<float>();
              if (d.contains("streak_end"))   p.streak_end   = d["streak_end"].cast<float>();
              if (d.contains("ring_rise"))    p.ring_rise    = d["ring_rise"].cast<float>();
              if (d.contains("tint")) {
                  auto t = d["tint"].cast<std::tuple<float, float, float>>();
                  p.tint = {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
              }
          },
          py::arg("params"),
          "Warp-in flash look (the \"warp in\" dials): dict with any of "
          "core_radii, streak_radii, ring_radii, intensity, streak_end, "
          "ring_rise (fractions of the life), tint ((r,g,b)). "
          "Absent keys keep their value.");

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
                  // Sprite library (spec 2026-10-16 §7.4); defaults = today.
                  e.playback  = d.contains("playback")  ? d["playback"].cast<int>()    : 0;
                  e.fps       = d.contains("fps")       ? d["fps"].cast<float>()       : 0.0f;
                  e.orient    = d.contains("orient")    ? d["orient"].cast<int>()      : 0;
                  e.roll_rate = d.contains("roll_rate") ? d["roll_rate"].cast<float>() : 0.0f;
                  if (d.contains("pivot")) {
                      auto p = d["pivot"].cast<std::tuple<float, float>>();
                      e.pivot = glm::vec2(std::get<0>(p), std::get<1>(p));
                  }
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
    m.def("set_running_lights",
          [](scenegraph::InstanceId id,
             const std::vector<std::array<float, 9>>& lights, float phase) {
              std::vector<renderer::RunningLight> out;
              out.reserve(lights.size());
              for (const auto& a : lights) {
                  renderer::RunningLight l;
                  l.body_pos = {a[0], a[1], a[2]};
                  l.rgb      = {a[3], a[4], a[5]};
                  l.size = a[6]; l.period = a[7]; l.duration = a[8];
                  out.push_back(l);
              }
              g_running_lights.set(id, std::move(out), phase);
          },
          py::arg("instance_id"), py::arg("lights"), py::arg("phase"),
          "Set a ship's running lights: each (px,py,pz, r,g,b, size, period, "
          "duration), body frame, unscaled GU. An empty list removes the ship.");
    m.def("set_running_light_levels",
          [](const std::vector<std::pair<scenegraph::InstanceId, float>>& levels) {
              g_running_lights.set_levels(levels);
          },
          py::arg("levels"),
          "Per-frame brightness (instance_id, level in [0,1]). Ships not listed "
          "draw dark this frame.");
    m.def("set_running_light_dials",
          [](float size_gu_per_radius, float min_px, float intensity) {
              g_running_light_dials = {size_gu_per_radius, min_px, intensity};
          },
          py::arg("size_gu_per_radius"), py::arg("min_px"), py::arg("intensity"));
    m.def("set_plating_params",
          [](const std::vector<float>& params) {
              const std::size_t n = std::min<std::size_t>(params.size(), renderer::plating::kParamCount);
              for (std::size_t i = 0; i < n; ++i)
                  dauntless_plating::g_params[i] = params[i];
          },
          py::arg("params"),
          "SPIKE: hull-plating layer params (engine/appc/plating_dials.py).");
    m.def("plating_param_defaults",
          []() {
              const float* d = dauntless_plating::param_defaults();
              return std::vector<float>(d, d + renderer::plating::kParamCount);
          },
          "The kParamCount shipped plating params (frame.cc's g_params "
          "initializer), unaffected by set_plating_params.");
    m.def("set_interior_near_gu",
          [](float gu) { g_interior_near_gu = gu; }, py::arg("gu"),
          "Rooms near distance (InteriorPolicy::near_gu) for the main view. "
          "Developer Options -> Hull damage only.");
    m.def("interior_near_gu", []() { return g_interior_near_gu; });
    m.def("interior_near_gu_default",
          []() { return renderer::InteriorPolicy{}.near_gu; });
    m.def("running_lights_set_enabled",
          [](bool v) { g_running_lights_enabled = v; }, py::arg("enabled"));
    m.def("running_lights_enabled", []() { return g_running_lights_enabled; });
    m.def("running_light_count",
          []() { return static_cast<int>(g_running_lights.size()); });
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
              // World-space centre of a posed character's HEAD -- the officer
              // zoom look-at point. The skinning and the head/body partition
              // live in renderer::skinned_head_center (renderer/head_center.h);
              // this adds inst.world and the view offset. Returns None for an
              // unskinned / not-yet-posed instance (caller -> captain view).
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
              // Memoised on its exact inputs (renderer/head_center.h): the
              // tooltip pick, the zoom look-at and the watch all ask for the
              // same officer in one frame (perf-register SIG-183).
              const std::optional<glm::vec3> local = g_head_center_cache.get(
                  iid, inst->model_handle, *model, inst->bone_palette);
              if (!local) return py::none();
              const glm::vec3 center = *local;
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
                                          float, float, float, float>>& discs,
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
                  d.hatch_opacity  = std::get<5>(t);
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
    m.def("profiler_set_gpu_enabled",
          [](bool enabled) {
              renderer::frame_timer().set_gpu_requested(enabled);
          },
          py::arg("enabled"),
          "Opt in to GPU timer queries. Off by default: on Apple's GL they "
          "make the CPU wait for the GPU, adding about the GPU frame time, "
          "so a GPU-timed capture is not a frame-time measurement "
          "(docs/reference/engine/perf-register.md, M-6).");
    m.def("profiler_gpu_enabled",
          []() { return renderer::frame_timer().gpu_requested(); },
          "True when GPU timing has been requested.");
    m.def("profiler_set_gpu_focus",
          [](std::vector<std::string> names) {
              renderer::frame_timer().set_gpu_focus(std::move(names));
          },
          py::arg("names"),
          "Nested scopes to GPU-time under GL_TIME_ELAPSED, which otherwise "
          "times only the top-level passes (perf-register.md M-1). The "
          "enclosing top-level pass's query is split around each one, so its "
          "own total is unchanged. Empty = top-level only (the default).");
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
                  // False: no GPU query covered this scope (nested under
                  // GL_TIME_ELAPSED, or no timer). gpu_ms is then NOT MEASURED.
                  d["gpu_measured"] = r.gpu_measured;
                  d["calls"]  = r.calls;
                  d["depth"]  = r.depth;
                  out.append(std::move(d));
              }
              return out;
          },
          "Per-pass render timings from the last resolved frame.");
    m.def("profiler_last_frame_raw",
          []() {
              // RAW CPU ms of the frame just closed -- not smoothed, not
              // lagged. The spike log reads one long frame's own numbers.
              py::list scopes;
              const auto& t = renderer::frame_timer();
              for (const auto& r : t.last_frame_raw()) {
                  py::dict d;
                  d["name"]   = r.name;
                  d["cpu_ms"] = r.cpu_ms;
                  d["calls"]  = r.calls;
                  d["depth"]  = r.depth;
                  scopes.append(std::move(d));
              }
              py::dict out;
              out["cpu_ms"] = t.last_frame_raw_cpu_ms();
              out["scopes"] = scopes;
              return out;
          },
          "The last frame's raw (un-smoothed) render CPU times, no GPU.");
    m.def("profiler_frame",
          []() {
              py::dict d;
              const auto& t = renderer::frame_timer();
              d["cpu_ms"] = t.frame_cpu_ms();
              // Whole-frame GPU: first-timestamp-to-last under GL_TIMESTAMP
              // (scopes nest, so a sum would double-count); the sum of the
              // sequential top-level spans under GL_TIME_ELAPSED.
              d["gpu_ms"] = t.frame_gpu_ms();
              using GpuTimer = renderer::FrameTimer::GpuTimer;
              const GpuTimer timer = t.gpu_timer();
              d["gpu_timer"] = timer == GpuTimer::Timestamp ? "timestamp"
                             : timer == GpuTimer::Elapsed   ? "elapsed"
                                                            : "none";
              d["gpu_queries"] = t.gpu_queries_active();
              // False = CPU-only by choice (the default), not a dead driver.
              d["gpu_requested"] = t.gpu_requested();
              // Nested scopes timed by splitting their top-level pass's query.
              py::list focus;
              for (const auto& f : t.gpu_focus()) focus.append(f);
              d["gpu_focus"] = focus;
              // What the driver declared (GL_QUERY_COUNTER_BITS), -1 until the
              // first enabled frame has read it.
              d["timestamp_bits"] = t.timestamp_bits();
              d["elapsed_bits"] = t.elapsed_bits();
              d["timestamp_queries"] = t.timestamp_queries_issued();
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
              const glm::vec3 p(std::get<0>(point),
                                 std::get<1>(point),
                                 std::get<2>(point));
              const glm::vec4 c(std::get<0>(rgba),
                                 std::get<1>(rgba),
                                 std::get<2>(rgba),
                                 std::get<3>(rgba));
              push_shield_hit(id, p, c, intensity, radius);
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
             float max_dist, bool rest_pose, bool drawn) -> py::object {
              // The body is trace_instance_for_python, shared with K2.
              const auto hit = trace_instance_for_python(
                  id,
                  glm::vec3(std::get<0>(origin), std::get<1>(origin),
                            std::get<2>(origin)),
                  glm::vec3(std::get<0>(direction), std::get<1>(direction),
                            std::get<2>(direction)),
                  max_dist, rest_pose, drawn);
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
          py::arg("rest_pose") = false,
          py::arg("drawn") = false,
          "Ray-cast a ray against an instance's loaded mesh, at its hit pose "
          "(the SIM pose when a sim source is set; drawn=True or no source: "
          "the drawn pose; pass the same flag to instance_translation) -- "
          "the instance's node overrides "
          "(articulation / severance) are applied, so a moved part is hit "
          "where it appears and a severed one cannot be hit at all "
          "(rest_pose=True: the rest geometry, overrides ignored). origin "
          "is INSTANCE-RELATIVE (world origin minus instance_translation); "
          "direction is a world direction, auto-normalised. Returns "
          "((point), (normal), t) on hit or None on miss; point is "
          "instance-relative too (add instance_translation back). t is the "
          "world-space distance from origin.");

    // Bridge editor pick (spec 2026-10-08-bridge-emitters §4): ray_trace_mesh
    // plus WHICH mesh and triangle were hit, with meshes to see through (the
    // "pick the surface behind" click). Same instance-relative convention.
    m.def("ray_trace_mesh_pick",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> origin,
             std::tuple<float, float, float> direction,
             float max_dist,
             std::vector<int> exclude_meshes) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return py::none();
              const glm::vec3 o(std::get<0>(origin), std::get<1>(origin),
                                std::get<2>(origin));
              glm::vec3 d(std::get<0>(direction), std::get<1>(direction),
                          std::get<2>(direction));
              const float dlen = glm::length(d);
              if (dlen < 1e-9f) return py::none();
              d /= dlen;
              if (!std::isfinite(max_dist) || max_dist <= 0.0f) return py::none();
              auto hit = renderer::ray_trace_instance_linear(
                  *model, inst->world_linear, o, d, max_dist,
                  &inst->node_overrides, &exclude_meshes);
              if (!hit) return py::none();
              return py::make_tuple(
                  py::make_tuple(hit->point.x, hit->point.y, hit->point.z),
                  py::make_tuple(hit->normal.x, hit->normal.y, hit->normal.z),
                  hit->t, hit->mesh_index, hit->triangle);
          },
          py::arg("instance_id"), py::arg("origin"), py::arg("direction"),
          py::arg("max_dist"), py::arg("exclude_meshes") = std::vector<int>{},
          "ray_trace_mesh plus (mesh_index, triangle) of the hit; triangles of "
          "exclude_meshes are never hit. Instance-relative origin/point. None "
          "on a miss or a stale id (never raises: the editor polls it).");

    // One mesh's triangles for the bridge editor's light shapes (spec
    // 2026-10-08-bridge-emitters §16.2): (vertices -- three per triangle,
    // instance-relative --, the area-weighted normal sum, the total area).
    // None for a stale id or an unknown / empty mesh; never raises.
    m.def("bridge_mesh_geometry",
          [](scenegraph::InstanceId id, int mesh) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || mesh < 0 ||
                  mesh >= static_cast<int>(model->meshes.size()))
                  return py::none();
              const auto tris = renderer::mesh_triangles_linear(*model, inst->world_linear, mesh);
              if (tris.empty()) return py::none();
              py::list verts;
              glm::vec3 nsum(0.0f);
              float area = 0.0f;
              for (const auto& t : tris) {
                  for (const auto& p : t) verts.append(py::make_tuple(p.x, p.y, p.z));
                  const glm::vec3 c = glm::cross(t[1] - t[0], t[2] - t[0]) * 0.5f;
                  nsum += c;
                  area += glm::length(c);
              }
              return py::make_tuple(verts, py::make_tuple(nsum.x, nsum.y, nsum.z), area);
          },
          py::arg("instance_id"), py::arg("mesh"),
          "One mesh's rest-pose triangles: (vertices, normal_sum, area), "
          "instance-relative; None for a stale id or unknown mesh.");

    // Per-mesh shape identity of an instance's model (spec
    // 2026-10-08-bridge-emitters §4): NIF block, shape name, node chain
    // (root -> owning node), material index; plus the model's source path and
    // content hash (empty unless loaded as an interior).
    m.def("model_identity",
          [](scenegraph::InstanceId id) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return py::none();
              std::vector<int> owner(model->meshes.size(), -1);
              for (std::size_t n = 0; n < model->nodes.size(); ++n)
                  for (int mi : model->nodes[n].meshes)
                      if (mi >= 0 && mi < static_cast<int>(owner.size()))
                          owner[mi] = static_cast<int>(n);
              py::list meshes;
              for (std::size_t i = 0; i < model->meshes.size(); ++i) {
                  const auto& mesh = model->meshes[i];
                  std::vector<std::string> chain;
                  for (int n = owner[i]; n >= 0 &&
                       n < static_cast<int>(model->nodes.size());
                       n = model->nodes[n].parent_index) {
                      chain.push_back(model->nodes[n].name);
                      if (chain.size() > model->nodes.size()) break;  // cycle guard
                  }
                  std::reverse(chain.begin(), chain.end());
                  // Names cross as BYTES: a NIF name is whatever the exporter
                  // wrote, and pybind's str conversion raises on non-UTF-8.
                  // host_io.model_identity decodes with errors="replace".
                  py::list chain_b;
                  for (const auto& c : chain) chain_b.append(py::bytes(c));
                  // The Base-stage texture as BUILT (property inheritance
                  // resolved), not nif_shapes' per-shape property walk.
                  py::list textures;
                  const int mi = mesh.material_index();
                  // safe_material_index is the SAME bounds check
                  // mesh_identity_maps uses below -- material_or_default
                  // requires a non-negative index to already be in range (it
                  // indexes with operator[], no bounds check of its own), so
                  // both lookups here must agree on what counts as safe.
                  const int safe_mi = dauntless::safe_material_index(*model, mi);
                  if (safe_mi >= 0 &&
                      !model->materials[safe_mi].base_texture_name.empty())
                      textures.append(py::bytes(model->materials[safe_mi].base_texture_name));
                  py::dict d;
                  d["mesh"] = static_cast<int>(i);
                  d["block"] = mesh.source_block();
                  d["name"] = py::bytes(mesh.shape_name());
                  d["node_chain"] = std::move(chain_b);
                  d["textures"] = std::move(textures);
                  d["material"] = mi;
                  const dauntless::MeshMaps mm = dauntless::mesh_identity_maps(*model, mi);
                  py::dict maps;
                  maps["roughness"] = mm.roughness;
                  maps["metalness"] = mm.metalness;
                  maps["normal"]    = mm.normal;
                  maps["emissive"]  = mm.emissive;
                  d["maps"] = std::move(maps);
                  meshes.append(std::move(d));
              }
              py::dict out;
              out["source"] = model->source.string();
              out["content_hash"] = model->content_hash;
              out["meshes"] = std::move(meshes);
              return out;
          },
          py::arg("instance_id"),
          "{source, content_hash, meshes:[{mesh, block, name, node_chain, "
          "textures, material, maps}]} for an instance's model, or None for a "
          "stale id. name / node_chain / textures are BYTES (decode with "
          "errors='replace'; host_io.model_identity does). maps is "
          "{roughness, metalness, normal, emissive}: whether the mesh's material has "
          "that texture stage populated (spec 2026-10-09-bridge-pbr).");

    // Developer-only selection tint on the bridge (spec
    // 2026-10-08-bridge-emitters §4).
    m.def("set_bridge_highlight",
          [](py::object instance_id, int selected, int hover) {
              if (!dauntless::is_developer_mode()) return;
              scenegraph::Instance* inst = nullptr;
              if (!instance_id.is_none())
                  inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
              // None or a stale id -> handle 0, which clears.
              dauntless::apply_bridge_highlight(
                  g_bridge_highlight, g_bridge_pass.get(),
                  inst ? inst->model_handle : 0ull, selected, hover);
          },
          py::arg("instance_id"), py::arg("selected"), py::arg("hover"),
          "Developer-only bridge editor selection tint: mesh indices into the "
          "instance's model, -1 = none; None or a stale id clears. No-op "
          "without --developer.");

    // Read-only: lets the pytest host tests observe that set_bridge_highlight
    // is a no-op without --developer. Exposes no way to change anything.
    m.def("bridge_highlight",
          [] {
              return py::make_tuple(g_bridge_highlight.model != 0,
                                    g_bridge_highlight.selected,
                                    g_bridge_highlight.hover);
          },
          "(active, selected_mesh, hover_mesh) of the bridge editor tint "
          "(see set_bridge_highlight); (False, -1, -1) when none.");

    m.def("hull_damage_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float radius, float wear, std::uint32_t kind, bool rest_frame) {
              if (kind != 1u && kind != 3u) return;  // only Surface/Internal
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id -- drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              // Same body-frame conversion as damage_decal_add: pw is
              // INSTANCE-RELATIVE; radius game-units -> model units. Then
              // into the struck part's REST frame.
              const auto bf = to_body_frame(*inst, pw, nw, radius);
              const WearNode wn = wear_node_for(*inst, bf.point, rest_frame);
              const auto r = inst->hull_damage.add(
                  glm::vec3(wn.to_rest * glm::vec4(bf.point, 1.0f)),
                  glm::mat3(wn.to_rest) * bf.normal, bf.radius_model, wear,
                  static_cast<scenegraph::HullDamageKind>(kind), wn.node);
              vent_on_breach_crossing(*inst, r, kind, wn.to_posed);
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("radius"), py::arg("wear"), py::arg("kind"),
          py::arg("rest_frame") = false,
          "Add a record to the instance's HullDamageStore. Point is "
          "INSTANCE-RELATIVE; point/normal/radius are converted to the body "
          "frame exactly as damage_decal_add does. kind: 1=Surface, 3=Internal. "
          "On a posed (articulated) instance the hit is attributed by geometry "
          "to the part it lies on and stored on that node, in its REST frame, "
          "so the damage moves with the part. rest_frame=True: the point is "
          "already rest-frame (authored damage): attributed in rest space to "
          "the nearest rest triangle's node, never converted.");

    m.def("hull_damage_add_body",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> body_point,
             std::tuple<float, float, float> body_normal,
             float radius, float wear, std::uint32_t kind, bool rest_frame) {
              if (kind != 1u && kind != 3u) return;  // only Surface/Internal
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id -- drop silently
              const glm::vec3 pb(std::get<0>(body_point), std::get<1>(body_point),
                                 std::get<2>(body_point));
              const glm::vec3 nb(std::get<0>(body_normal), std::get<1>(body_normal),
                                 std::get<2>(body_normal));
              const WearNode wn = wear_node_for(*inst, pb, rest_frame);
              const auto r = inst->hull_damage.add(
                  glm::vec3(wn.to_rest * glm::vec4(pb, 1.0f)), glm::mat3(wn.to_rest) * nb,
                  radius_to_model(*inst, radius), wear,
                  static_cast<scenegraph::HullDamageKind>(kind), wn.node);
              vent_on_breach_crossing(*inst, r, kind, wn.to_posed);
          },
          py::arg("instance_id"), py::arg("body_point"), py::arg("body_normal"),
          py::arg("radius"), py::arg("wear"), py::arg("kind"),
          py::arg("rest_frame") = false,
          "hull_damage_add for a point/normal ALREADY in the (POSED) body frame "
          "(model units, e.g. from world_to_body). radius is still game units "
          "and is converted with the same scale as hull_damage_add. kind: "
          "1=Surface, 3=Internal. Attributed and stored like hull_damage_add; "
          "rest_frame=True as there.");

    m.def("_test_only_posed_owner",
          [](scenegraph::InstanceId id, int node) -> int {
              const auto* inst = g_world.get(id);
              if (inst == nullptr || node < 0) return -1;
              const assets::Model* m = resolve_model(inst->model_handle);
              if (m == nullptr) return -1;
              const std::vector<int> owners = renderer::posed_owners(*m, inst->node_overrides);
              return static_cast<std::size_t>(node) < owners.size()
                         ? owners[static_cast<std::size_t>(node)] : -1;
          },
          py::arg("instance_id"), py::arg("node"),
          "TEST ONLY: renderer::posed_owners for `node` under the instance's "
          "current overrides -- the frame a record on that node is drawn in "
          "(a mesh draws a record when their posed owners agree). -1: no "
          "override on its chain, or a bad id/node.");

    m.def("_test_only_breach_events",
          [](scenegraph::InstanceId id) {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) return out;
              for (const auto& e : inst->breach_events.slots()) {
                  if (!e.active) continue;
                  py::dict d;
                  d["center"] = py::make_tuple(e.center_body.x, e.center_body.y,
                                               e.center_body.z);
                  d["normal"] = py::make_tuple(e.surface_normal.x, e.surface_normal.y,
                                               e.surface_normal.z);
                  d["radius"] = e.radius;
                  d["birth_time"] = e.birth_time;
                  d["center_rest"] = py::make_tuple(e.center_rest.x, e.center_rest.y,
                                                    e.center_rest.z);
                  d["node"] = e.node;
                  out.append(d);
              }
              return out;
          },
          py::arg("instance_id"),
          "Test hook: the instance's active BreachEvents (model units) as dicts "
          "center/normal (posed body frame), radius, birth_time, node and "
          "center_rest (the molten rim's frame: node's REST frame, -1 = body).");

    m.def("_test_only_hull_damage_records",
          [](scenegraph::InstanceId id) {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) return out;
              for (const auto& r : inst->hull_damage.records()) {
                  if (!r.active) continue;
                  py::dict d;
                  d["centre"] = py::make_tuple(r.centre_body.x, r.centre_body.y,
                                               r.centre_body.z);
                  d["normal"] = py::make_tuple(r.normal_body.x, r.normal_body.y,
                                               r.normal_body.z);
                  d["reach"] = r.reach;
                  d["wear"] = r.wear;
                  d["kind"] = static_cast<int>(r.kind);
                  d["node"] = r.node;
                  out.append(d);
              }
              return out;
          },
          py::arg("instance_id"),
          "Test hook: the instance's active HullDamageStore records (each in "
          "its node's REST frame, model units) as dicts "
          "centre/normal/reach/wear/kind/node (-1 = the hull body).");

    m.def("_test_only_hull_damage_constants",
          []() {
              py::dict d;
              d["merge_factor"] = scenegraph::HullDamageStore::kMergeFactor;
              d["capacity"] = scenegraph::HullDamageStore::kCapacity;
              return d;
          },
          "Test hook: HullDamageStore::kMergeFactor / kCapacity, so the Python "
          "hull_wear twin can be pinned against the native values.");

    m.def("_test_only_damage_decals",
          [](scenegraph::InstanceId id) {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) return out;
              for (const auto& dc : inst->decals.slots()) {
                  if (!dc.active) continue;
                  py::dict d;
                  d["point"] = py::make_tuple(dc.point_body.x, dc.point_body.y,
                                              dc.point_body.z);
                  d["radius"] = dc.radius;
                  d["weapon_class"] = static_cast<int>(dc.weapon_class);
                  out.append(d);
              }
              return out;
          },
          py::arg("instance_id"),
          "Test hook: the instance's active damage decals (body frame, model "
          "units) as dicts point/radius/weapon_class.");

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
              const auto bf = to_body_frame(*inst, pw, nw, radius);
              const glm::vec3 pb = bf.point;
              const glm::vec3 nb = bf.normal;
              const glm::vec3 tw(std::get<0>(world_tangent),
                                 std::get<1>(world_tangent),
                                 std::get<2>(world_tangent));
              // Zero stays zero (dir_to_body returns a length-0 input
              // unchanged); the ring then derives a perpendicular.
              const glm::vec3 tb = scenegraph::dir_to_body(
                  hit_pose_of(*inst, /*drawn=*/false).linear, tw);
              // Convert radius game-units -> NIF/model units here (the same
              // space as pb), so the ring's merge test and the shader both work
              // in model units. s = |world's X column| = the uniform NIF->world
              // scale baked into inst->world.
              const float radius_model = bf.radius_model;
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

    m.def("hull_split_parts",
          [](scenegraph::InstanceId id) -> py::object {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr) {
                  g_severance_jobs.forget(id);
                  return std::move(out);
              }
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return std::move(out);
              // nullptr until the background detection lands: try next check.
              std::shared_ptr<const voxel::StructureSegmentation> seg =
                  renderer::structure_segmentation_shared(model->source);
              if (seg == nullptr) return std::move(out);
              // The check itself runs on a worker (Ruling 10): the first call
              // queues it, later calls answer None until it lands, then apply it
              // here on the main thread -- or drop it and re-queue if the
              // damage or the severed mask moved meanwhile.
              const renderer::SplitPoll poll = g_severance_jobs.poll(
                  g_world, id, std::move(seg),
                  [](const scenegraph::Instance& i) {
                      return renderer::plating::build_damage_list(i.hull_damage,
                                                                  dauntless_plating::g_params);
                  },
                  dauntless_plating::g_params[24],
                  /*skinned=*/!model->skeleton.bones.empty());
              if (poll.pending) return py::none();
              inst = g_world.get(id);   // the chunks may have grown the store
              if (inst == nullptr) return std::move(out);
              const float s = glm::length(glm::vec3(inst->world[0]));   // model->GU
              auto gu = [s](const glm::vec3& v) {
                  return py::make_tuple(v.x * s, v.y * s, v.z * s);
              };
              for (const renderer::SeveredSplit& sp : poll.split) {
                  py::dict d;
                  py::list parts;
                  for (int i = 0; i < 32; ++i)
                      if ((sp.piece.parts >> i) & 1u) parts.append(i);
                  d["parts"] = parts;
                  d["instance_id"] = sp.chunk;
                  d["voxels"] = sp.piece.voxels;
                  d["total_voxels"] = sp.total_voxels;
                  d["centroid"] = gu(sp.piece.centroid_body);
                  d["bounds_min"] = gu(sp.piece.min_body);
                  d["bounds_max"] = gu(sp.piece.max_body);
                  d["radius_gu"] =
                      0.5f * glm::length(sp.piece.max_body - sp.piece.min_body) * s;
                  out.append(std::move(d));
              }
              return std::move(out);
          },
          py::arg("instance_id"),
          "Break off every piece the plating wear has cut from the main body "
          "(renderer::find_severed_parts, run on a WORKER: "
          "renderer/part_severance_jobs.h): a piece's structure parts are "
          "hidden on the parent and a new instance draws only them. None = the "
          "check is running (or was just re-queued because the damage moved): "
          "call again to collect it. Rocks, articulated hulls and hulls whose "
          "parts are not detected yet never sever. Otherwise one dict per newly "
          "severed piece, body-frame GAME UNITS: parts (list of part indices), "
          "instance_id, voxels, total_voxels, centroid, bounds_min, bounds_max, "
          "radius_gu.");

    m.def("structure_part_at",
          [](scenegraph::InstanceId id, std::tuple<float, float, float> body_point_gu) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return -1;
              const voxel::StructureSegmentation* seg =
                  renderer::structure_segmentation_for(model->source);
              if (seg == nullptr) return -1;
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 pb(std::get<0>(body_point_gu) * inv_s,
                                 std::get<1>(body_point_gu) * inv_s,
                                 std::get<2>(body_point_gu) * inv_s);
              return renderer::structure_part_at(*seg, pb);
          },
          py::arg("instance_id"), py::arg("body_point_gu"),
          "The structure part (index) whose voxel holds a BODY-frame point in "
          "GAME UNITS, or -1: outside the hull's voxels, a stale id, or parts "
          "not detected yet. Read-only.");

    m.def("instance_severed_parts",
          [](scenegraph::InstanceId id) -> std::uint32_t {
              const auto* inst = g_world.get(id);
              return inst == nullptr ? 0u : inst->severed_parts;
          },
          py::arg("instance_id"),
          "The structure parts that have broken off this hull "
          "(Instance::severed_parts): bit i set = part i (structure_part_at's "
          "index) has left as a chunk. 0 for an intact hull or a stale id. "
          "Read-only.");

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
              // The body (node -1): its rest frame is the body frame. The rim
              // is therefore drawn in the BODY frame: a burst on a POSED part
              // glows on body meshes near that point, or nowhere (accepted:
              // a sub-floor component's transient VFX; venting and debris use
              // the posed point as given).
              inst->breach_events.push(pb, radius_gu * inv_s, nb, g_decal_game_time,
                                       next_breach_seed(), /*node=*/-1, pb);
          },
          py::arg("instance_id"), py::arg("body_point_gu"), py::arg("radius_gu"),
          "Transient breach VFX (debris, venting, rim) at a body-frame point, "
          "for a sub-floor severed component that becomes no chunk.");

    // Build a loaded model's ray-trace BVH now (renderer::prewarm_trace_accel)
    // instead of on its first trace, which otherwise pays for it in combat
    // (perf-register SIG-039/040: 7.7 ms on a station). From a MODEL handle:
    // the warp-tunnel preload warms hulls before any ship is realised.
    m.def("prewarm_trace_accel",
          [](scenegraph::ModelHandle model_handle) {
              const assets::Model* model = resolve_model(model_handle);
              if (model == nullptr) return;
              renderer::prewarm_trace_accel(*model);
          },
          pybind11::arg("model"),
          "Build this model's ray-trace BVH now, without creating an "
          "instance. No-op for an unknown handle.");

    m.def("_test_only_trace_accel_built",
          [](scenegraph::ModelHandle model_handle) {
              const assets::Model* model = resolve_model(model_handle);
              return model != nullptr && model->trace_accel != nullptr;
          },
          pybind11::arg("model"),
          "TEST ONLY: whether this model's ray-trace BVH has been built. "
          "False for an unknown handle.");

    // Start the background decode of this hull's fill volume (the left-the-ship
    // test's 3D texture) so the first cut does not hitch. Never blocks.
    m.def("prefetch_hull_fill",
          [](scenegraph::ModelHandle model_handle) {
              if (!g_fill_cache) return;
              const assets::Model* model = resolve_model(model_handle);
              if (model == nullptr || model->source.empty()) return;
              g_fill_cache->prefetch(model->source);
          },
          pybind11::arg("model"),
          "Queue this model's hull fill volume for background decode. No-op "
          "for an unknown handle or an empty source.");

    // Start this hull's structure-part detection (severance's regions) now,
    // not at its first damaged draw (layered damage phase 4 §2.2). Never blocks.
    m.def("prefetch_structure_parts",
          [](scenegraph::ModelHandle model_handle) {
              const assets::Model* model = resolve_model(model_handle);
              if (model == nullptr || model->source.empty()) return;
              renderer::prefetch_structure_parts(model->source);
          },
          pybind11::arg("model"),
          "Start this model's structure-part detection on a worker (read from "
          "the .sps disk cache when it holds it). No-op for an unknown handle, "
          "an empty source or a glTF rock.");

    m.def("structure_parts_set_cache_root",
          [](const std::string& root) {
              renderer::set_structure_parts_cache_root(std::filesystem::path(root));
          },
          pybind11::arg("root"),
          "Where structure-part segmentations are cached on disk "
          "(paths.structure_parts_cache_root()). Empty = no disk I/O.");

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
             std::tuple<float, float, float> world_normal, bool drawn)
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
              const glm::mat3 linear = hit_pose_of(*inst, drawn).linear;
              const glm::vec3 pb = scenegraph::relative_to_body(linear, pw);
              const glm::vec3 nb = scenegraph::dir_to_body(linear, nw);
              return py::make_tuple(
                  py::make_tuple(pb.x, pb.y, pb.z),
                  py::make_tuple(nb.x, nb.y, nb.z));
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("drawn") = false,
          "Convert an INSTANCE-RELATIVE hit point (world point minus "
          "instance_translation, same drawn flag) + world normal into the "
          "ship instance's body frame (model units), inverting the hit pose "
          "(sim unless drawn=True). Returns ((bx,by,bz),(nx,ny,nz)) or None "
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

    m.def("set_fullscreen",
          [](bool on) {
              if (!g_window) {
                  throw std::runtime_error("set_fullscreen: init must be called first");
              }
              g_window->set_fullscreen(on);
          },
          py::arg("on"),
          "Put the window full-screen on the monitor it currently occupies, "
          "or restore its previous position and size. Full screen uses that "
          "monitor's CURRENT video mode, so no resolution change. Idempotent.");

    m.def("fullscreen",
          []() {
              return g_window ? g_window->is_fullscreen() : false;
          },
          "True while the window is full-screen. False before init, so a "
          "caller polling this during boot reads 'windowed' rather than "
          "raising.");

    m.def("set_key_capture",
          [](bool on) {
              if (!g_window) {
                  throw std::runtime_error("set_key_capture: init must be called first");
              }
              g_window->set_key_capture(on);
          },
          py::arg("on"),
          "Hand the keyboard to a focused CEF text field (True) or give it back "
          "(False). While captured every key_state/key_pressed reads False.");

    m.def("key_capture_active",
          []() { return g_window ? g_window->key_capture_active() : false; },
          "True while a CEF text field holds the keyboard. Native resets it on "
          "page load and on renderer crash.");

    m.def("consume_scroll_y",
          []() {
              if (!g_window) {
                  throw std::runtime_error("consume_scroll_y: init must be called first");
              }
              return g_window->consume_scroll_y();
          },
          "Return the accumulated mouse-wheel Y delta since the last call "
          "and reset the accumulator. Positive = scroll up.");

    m.def("drain_text_events",
          []() {
              if (!g_window) {
                  throw std::runtime_error("drain_text_events: init must be called first");
              }
              py::list out;
              for (const auto& e : g_window->drain_text_events()) {
                  out.append(py::make_tuple(e.kind, e.code, e.scancode, e.action, e.mods));
              }
              return out;
          },
          "Typed characters and key events since the last call, oldest first, "
          "as (kind, code, scancode, action, mods); kind 0 = char (code = "
          "codepoint), 1 = key (code = GLFW key, every key not just editing "
          "keys), 2 = edit command.");

    m.def("request_relaunch",
          [](std::vector<std::string> extra_args) {
              dauntless::platform::set_relaunch_request(std::move(extra_args));
          },
          py::arg("extra_args"),
          "Ask host_main to re-execute the game after a clean shutdown, with the "
          "original arguments plus `extra_args` (Quit and Manage Mods). Last call "
          "wins. Only the dauntless binary honours it; the pytest .so just stores it.");

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
    m.def("request_frame_png",
          [](const std::string& path) { g_frame_png_path = path; },
          py::arg("path"),
          "Write the next finished frame (default framebuffer, overlay "
          "included) to `path` as a PNG, once. Developer diagnostics: the "
          "unattended runs' before/after screenshots (dev_scripted_run).");
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
    // A focused CEF text field holds the keyboard (Window::set_key_capture).
    // If its page reloads or its renderer dies, take the keyboard back
    // natively -- Python learns of it via key_capture_active().
    dauntless::ui_cef::set_capture_reset_handler([]() {
        if (g_window) g_window->set_key_capture(false);
    });

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

    m.def("cef_send_text_events",
          [](const std::vector<std::tuple<int, int, int, int, int>>& events) {
              static_assert(static_cast<int>(renderer::EditCommand::Redo) == 6,
                            "ui_cef::edit_command's numbering");
              // renderer::build_text_event_steps keeps edit commands (kind
              // 2) and translated key/char runs (kind 0/1) in the SAME
              // relative order the events were queued in -- NOT a two-pass
              // "all edits, then all keys" split, which reordered a frame
              // holding both (e.g. a typed character immediately followed
              // by Cmd+Z would undo before the type it was meant to undo).
              std::vector<renderer::TextEvent> text_events;
              text_events.reserve(events.size());
              for (const auto& [kind, code, scancode, action, mods] : events) {
                  text_events.push_back({kind, code, scancode, action, mods});
              }
              for (auto& step : renderer::build_text_event_steps(text_events, g_text_translator)) {
                  if (step.is_edit_command) {
                      dauntless::ui_cef::edit_command(static_cast<int>(step.command));
                      continue;
                  }
                  for (const auto& intent : step.intents) {
                      dauntless::ui_cef::send_key_intent(
                          static_cast<int>(intent.type), intent.windows_key_code,
                          intent.native_key_code, intent.character,
                          intent.unmodified_character, intent.glfw_mods);
                  }
              }
          },
          py::arg("events"),
          "Forward one drain_text_events() batch to the CEF overlay, in "
          "order. Kind 2 (edit command) events run directly on the "
          "focused frame; every kind 0/1 run between them feeds the "
          "process's single TextEventTranslator, whose output (real "
          "KEYDOWN+CHAR / KEYUP pairs) is sent as CEF key events -- "
          "relative order against the edit commands is preserved. No-op "
          "with no browser.");

    m.def("cef_reset_text_translator",
          []() { g_text_translator.reset(); },
          "Forget every key TextEventTranslator currently believes is "
          "held. Call at a key-capture boundary (gained or released) so a "
          "key still down across it cannot emit an orphaned KEYUP into a "
          "page that never saw its KEYDOWN.");

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
    m.def("cef_send_text_events",
          [](const std::vector<std::tuple<int, int, int, int, int>>&) {});
    m.def("cef_reset_text_translator", []() {});
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

    // ── benchmark-only (phase 6 B0) ─────────────────────────────────────────
    // Bindings for tools/bench/boundary_bench.py (SIG-198): each crosses the
    // Python/C++ boundary a different way for the same three doubles. Nothing
    // in the game calls them.
    m.def("bench_noop", []() {});
    m.def("bench_get_pos_tuple",
          [](std::uint32_t i, std::uint32_t g) {
              const auto p = dauntless::transform_store().position(i, g);
              return py::make_tuple(p[0], p[1], p[2]);
          });
    m.def("bench_set_point_class",
          [](py::object cls) { bench_point_class() = std::move(cls); });
    m.def("bench_new_point",
          [](std::uint32_t i, std::uint32_t g) {
              const auto p = dauntless::transform_store().position(i, g);
              return bench_point_class()(p[0], p[1], p[2]);
          });
    m.def("bench_fill_point",
          [](std::uint32_t i, std::uint32_t g, py::object pt) {
              const auto p = dauntless::transform_store().position(i, g);
              pt.attr("x") = p[0];
              pt.attr("y") = p[1];
              pt.attr("z") = p[2];
          });
    struct BenchPoint {
        double x, y, z;
    };
    py::class_<BenchPoint>(m, "bench_NativePoint")
        .def_readonly("x", &BenchPoint::x)
        .def_readonly("y", &BenchPoint::y)
        .def_readonly("z", &BenchPoint::z);
    m.def("bench_native_point",
          [](std::uint32_t i, std::uint32_t g) {
              const auto p = dauntless::transform_store().position(i, g);
              return BenchPoint{p[0], p[1], p[2]};
          });
    m.def("bench_position_view",
          [](std::uint32_t i, std::uint32_t g) {
              dauntless::transform_store().position(i, g);  // validates
              double* pos = dauntless::transform_store().at(i).pos;
              // A typed view (format 'd', 3 items), not raw bytes.
              return py::memoryview::from_buffer(
                  pos, {3},
                  {static_cast<py::ssize_t>(sizeof(double))}, true);
          });
    // ── end benchmark-only ──────────────────────────────────────────────────

    // ProximityManager.GetNearObjects: `handles` is a buffer of uint32
    // (index, generation) pairs; returns one byte per handle, 1 inside or on
    // the sphere. Taking a buffer and returning bytes keeps the crossing to
    // two conversions, where a list of tuples cost ~0.4 us per handle.
    m.def("transform_within_radius",
          [](py::buffer handles, double x, double y, double z, double r2) {
              const py::buffer_info info = handles.request();
              if (info.itemsize != sizeof(std::uint32_t) || info.ndim != 1 ||
                  info.shape[0] % 2 != 0)
                  throw py::value_error("handles: flat uint32 (index, generation) pairs");
              const std::size_t n = static_cast<std::size_t>(info.shape[0]) / 2;
              std::string out(n, '\0');
              const double p[3] = {x, y, z};
              dauntless::transform_store().within_radius(
                  static_cast<const std::uint32_t*>(info.ptr), n, p, r2,
                  reinterpret_cast<std::uint8_t*>(out.data()));
              return py::bytes(out);
          },
          py::arg("handles"), py::arg("x"), py::arg("y"), py::arg("z"),
          py::arg("r2"));

    // Hit positions (ascending) of the packed (index, generation) handles
    // within or on the sphere. Holds the GIL, as transform_within_radius does
    // (controller ruling R3: a ~65-handle loop is cheaper than a release).
    m.def("transform_near_indices",
          [](py::buffer handles, double x, double y, double z, double r2) {
              const py::buffer_info info = handles.request();
              if (info.itemsize != sizeof(std::uint32_t) || info.ndim != 1 ||
                  info.shape[0] % 2 != 0)
                  throw py::value_error("handles: flat uint32 (index, generation) pairs");
              const std::size_t n = static_cast<std::size_t>(info.shape[0]) / 2;
              std::vector<std::uint32_t> hits;
              const double p[3] = {x, y, z};
              dauntless::transform_store().near_indices(
                  static_cast<const std::uint32_t*>(info.ptr), n, p, r2, hits);
              py::list out;
              for (std::uint32_t k : hits) out.append(k);
              return out;
          },
          py::arg("handles"), py::arg("x"), py::arg("y"), py::arg("z"),
          py::arg("r2"));

    // BC's size rule (ruling 4): hit positions (ascending) of the packed
    // handles whose surface is within or on the sphere, reach = r +
    // max(radii[k], 0). `radii` is a float64 buffer, one per handle pair.
    // Holds the GIL, as transform_near_indices does (ruling R3).
    m.def("transform_near_indices_sized",
          [](py::buffer handles, py::buffer radii, double x, double y,
             double z, double r) {
              const py::buffer_info info = handles.request();
              if (info.itemsize != sizeof(std::uint32_t) || info.ndim != 1 ||
                  info.shape[0] % 2 != 0)
                  throw py::value_error("handles: flat uint32 (index, generation) pairs");
              const std::size_t n = static_cast<std::size_t>(info.shape[0]) / 2;
              const py::buffer_info rinfo = radii.request();
              if (rinfo.itemsize != sizeof(double) || rinfo.ndim != 1 ||
                  rinfo.format != py::format_descriptor<double>::format())
                  throw py::value_error("radii: flat float64 buffer");
              if (static_cast<std::size_t>(rinfo.shape[0]) != n)
                  throw py::value_error("radii: one per handle pair");
              std::vector<std::uint32_t> hits;
              const double p[3] = {x, y, z};
              dauntless::transform_store().near_indices_sized(
                  static_cast<const std::uint32_t*>(info.ptr), n,
                  static_cast<const double*>(rinfo.ptr), p, r, hits);
              py::list out;
              for (std::uint32_t k : hits) out.append(k);
              return out;
          },
          py::arg("handles"), py::arg("radii"), py::arg("x"), py::arg("y"),
          py::arg("z"), py::arg("r"));

    // Backs engine/appc/proximity_table.py: the per-tick ProximityCheck pass
    // keeps its pairs packed between ticks and asks once which few need
    // Python. Returns a list because it is nearly always empty.
    m.def("transform_proximity_report",
          [](py::buffer anchors, py::buffer objects, py::buffer r2,
             py::buffer want, std::size_t start) {
              const py::buffer_info a = anchors.request();
              const py::buffer_info o = objects.request();
              const py::buffer_info r = r2.request();
              const py::buffer_info w = want.request();
              const std::size_t n = static_cast<std::size_t>(w.size);
              if (w.itemsize != 1 || r.itemsize != sizeof(double) ||
                  a.itemsize != sizeof(std::uint32_t) ||
                  o.itemsize != sizeof(std::uint32_t) ||
                  static_cast<std::size_t>(r.size) != n ||
                  static_cast<std::size_t>(a.size) != 2 * n ||
                  static_cast<std::size_t>(o.size) != 2 * n)
                  throw py::value_error(
                      "proximity pairs: uint32 anchor and object handle "
                      "pairs, one double r2 and one want byte per pair");
              std::vector<std::uint32_t> out;
              dauntless::transform_store().proximity_report(
                  static_cast<const std::uint32_t*>(a.ptr),
                  static_cast<const std::uint32_t*>(o.ptr),
                  static_cast<const double*>(r.ptr),
                  static_cast<const std::uint8_t*>(w.ptr), n, start, out);
              py::list res(out.size());
              for (std::size_t k = 0; k < out.size(); ++k)
                  res[k] = py::int_(out[k]);
              return res;
          },
          py::arg("anchors"), py::arg("objects"), py::arg("r2"),
          py::arg("want"), py::arg("start"));

    // Torpedo flight's broadphase (engine/appc/projectiles.py update_all):
    // every torpedo against every ship in one call, so Python only meets the
    // few pairs close enough for its narrow hit tests. Flat [t, s, ...].
    m.def("transform_sweep_candidates",
          [](py::buffer starts, py::buffer seg_lens, py::buffer skips,
             py::buffer centres, py::buffer bounds) {
              const py::buffer_info p = starts.request();
              const py::buffer_info l = seg_lens.request();
              const py::buffer_info k = skips.request();
              const py::buffer_info c = centres.request();
              const py::buffer_info b = bounds.request();
              const std::size_t nt = static_cast<std::size_t>(l.size);
              const std::size_t ns = static_cast<std::size_t>(b.size);
              if (p.itemsize != sizeof(double) || l.itemsize != sizeof(double) ||
                  c.itemsize != sizeof(double) || b.itemsize != sizeof(double) ||
                  k.itemsize != sizeof(std::int32_t) ||
                  static_cast<std::size_t>(p.size) != 3 * nt ||
                  static_cast<std::size_t>(k.size) != nt ||
                  static_cast<std::size_t>(c.size) != 3 * ns)
                  throw py::value_error(
                      "sweep: three double start coordinates, one double "
                      "length and one int32 skip per torpedo; three double "
                      "centre coordinates and one double bound per ship");
              std::vector<std::uint32_t> out;
              dauntless::sweep_candidates(
                  static_cast<const double*>(p.ptr),
                  static_cast<const double*>(l.ptr),
                  static_cast<const std::int32_t*>(k.ptr), nt,
                  static_cast<const double*>(c.ptr),
                  static_cast<const double*>(b.ptr), ns, out);
              py::list res(out.size());
              for (std::size_t i = 0; i < out.size(); ++i)
                  res[i] = py::int_(out[i]);
              return res;
          },
          py::arg("starts"), py::arg("seg_lens"), py::arg("skips"),
          py::arg("centres"), py::arg("bounds"));

    m.def("transform_live_count", []() {
              return dauntless::transform_store().live_count();
          });

    m.def("transform_capacity", []() {
              return dauntless::transform_store().capacity();
          });

    // ── Incoming-torpedo table ───────────────────────────────────────────────
    // Backs App.AIScriptAssist_GetIncomingTorpIDsInSet. Kept in step with
    // projectiles._active by engine/appc/torpedo_scan.py; see torpedo_scan.h.
    m.def("torpedo_scan_add",
          [](std::int64_t id, std::uint32_t xi, std::uint32_t xg, double vx,
             double vy, double vz, bool has_source, std::int64_t source,
             std::int64_t group) {
              dauntless::torpedo_scan().add(id, xi, xg, vx, vy, vz,
                                            has_source, source, group);
          });
    m.def("torpedo_scan_remove", [](std::int64_t id) {
              return dauntless::torpedo_scan().remove(id);
          });
    m.def("torpedo_scan_set_velocity",
          [](std::int64_t id, double vx, double vy, double vz) {
              dauntless::torpedo_scan().set_velocity(id, vx, vy, vz);
          });
    m.def("torpedo_scan_set_source",
          [](std::int64_t id, bool has_source, std::int64_t source) {
              dauntless::torpedo_scan().set_source(id, has_source, source);
          });
    m.def("torpedo_scan_set_group", [](std::int64_t id, std::int64_t group) {
              dauntless::torpedo_scan().set_group(id, group);
          });
    m.def("torpedo_scan_clear", []() { dauntless::torpedo_scan().clear(); });
    m.def("torpedo_scan_size", []() { return dauntless::torpedo_scan().size(); });
    m.def("torpedo_scan_incoming",
          [](const std::array<double, 3>& obs,
             const std::array<double, 3>& obs_vel, double threshold,
             bool match_source, std::int64_t firing_id,
             const std::vector<std::tuple<std::int64_t, double, double, double>>&
                 offsets) {
              std::vector<dauntless::TorpedoScan::GroupOffset> offs;
              offs.reserve(offsets.size());
              for (const auto& [g, x, y, z] : offsets) offs.push_back({g, {x, y, z}});
              return dauntless::torpedo_scan().incoming(
                  obs.data(), obs_vel.data(), threshold, match_source,
                  firing_id, offs);
          },
          py::arg("obs"), py::arg("obs_vel"), py::arg("threshold"),
          py::arg("match_source"), py::arg("firing_id"), py::arg("offsets"),
          "Ids of the torpedoes incoming on the observer, in table order. "
          "offsets: (group, dx, dy, dz) per set visible from the observer's.");

    // ── Native combat: Python-exact math (test bindings) ────────────────────
    // The combat library's primitives, exposed only so
    // tests/unit/test_native_combat_math.py (and native_combat's interpreter
    // self-check) can compare them with the Python they replace, bit for bit.
    // Not a gameplay surface.
    m.def("combat_test_dist3",
          [](const std::array<double, 3>& a, const std::array<double, 3>& b) {
              return dauntless::combat::dist3(a.data(), b.data());
          },
          py::arg("a"), py::arg("b"),
          "math.dist(a, b) for 3-D points, as CPython 3.11.15 computes it.");
    m.def("combat_test_fbm",
          [](double x, double y, double z) {
              return dauntless::combat::fbm(x, y, z);
          },
          "engine.appc.nebula_density.fbm(x, y, z).");
    m.def("combat_test_density",
          [](double px, double py, double pz,
             const std::vector<std::tuple<double, double, double, double>>& spheres,
             const std::array<double, 3>& seed, double freq, double gain,
             double floor, double drift_t) {
              std::vector<dauntless::combat::Sphere> s;
              s.reserve(spheres.size());
              for (const auto& [x, y, z, r] : spheres) s.push_back({x, y, z, r});
              return dauntless::combat::density(px, py, pz, s.data(), s.size(),
                                                seed.data(), freq, gain, floor,
                                                drift_t);
          },
          py::arg("px"), py::arg("py"), py::arg("pz"), py::arg("spheres"),
          py::arg("seed"), py::arg("freq"), py::arg("gain"), py::arg("floor"),
          py::arg("drift_t"),
          "engine.appc.nebula_density.density(...); spheres: (x, y, z, r).");
    m.def("combat_test_profile_sensors",
          [](const std::vector<std::tuple<double, double>>& rows, double r) {
              std::vector<dauntless::combat::ProfileRow> v;
              v.reserve(rows.size());
              for (const auto& [d, sensors] : rows) v.push_back({d, sensors});
              return dauntless::combat::evaluate_sensors(v.data(), v.size(), r);
          },
          py::arg("rows"), py::arg("r"),
          "profile.evaluate(prof, r).sensors; rows: (distance_gu, sensors).");
    m.def("combat_test_segment_hits",
          [](double ax, double ay, double az, double bx, double by, double bz,
             double cx, double cy, double cz, double r) {
              return dauntless::combat::segment_hits(ax, ay, az, bx, by, bz,
                                                     cx, cy, cz, r);
          },
          "engine.appc.sensor_occlusion._segment_hits(...).");
    m.def("combat_test_contains",
          [](double x, double y, double z, double cx, double cy, double cz,
             double r) {
              return dauntless::combat::contains(x, y, z, cx, cy, cz, r);
          },
          "engine.appc.sensor_occlusion._contains(...).");

    // ── Native combat: the mirror store ─────────────────────────────────────
    // Rows Python keeps in sync and the detection kernel reads (spec §7.1).
    // Handles are generation-checked int64; a stale or wrong-kind handle
    // raises ValueError (std::invalid_argument).
    {
        namespace cb = dauntless::combat;
        auto fld = [](int f) {
            if (f < 0 || f >= static_cast<int>(cb::Field::kCount))
                throw std::invalid_argument("combat mirror: unknown field");
            return static_cast<cb::Field>(f);
        };
        m.def("combat_register",
              [](int kind, std::int64_t xi, std::int64_t xg, std::int64_t id,
                 std::uint64_t py_id) {
                  if (kind < 0 || kind >= static_cast<int>(cb::Kind::kCount))
                      throw std::invalid_argument("combat mirror: bad kind");
                  return cb::mirror().register_row(static_cast<cb::Kind>(kind),
                                                   xi, xg, id, py_id);
              },
              py::arg("kind"), py::arg("xform_index") = -1,
              py::arg("xform_gen") = -1, py::arg("obj_id") = -1,
              py::arg("py_id") = 0,
              "py_id: the Python object's id() (Object rows; read back as "
              "combat_dump's 'py_id').");
        m.def("combat_unregister",
              [](std::int64_t h) {
                  // Its launch module first, so a throwing unregister (a
                  // freed or stale handle) cannot keep the reference.
                  k1_launch_module_release(h);
                  cb::mirror().unregister_row(h);
              });
        m.def("combat_set_f", [fld](std::int64_t h, int f, double v) {
            cb::mirror().set_f(h, fld(f), v);
        });
        m.def("combat_set_i", [fld](std::int64_t h, int f, std::int64_t v) {
            cb::mirror().set_i(h, fld(f), v);
        });
        m.def("combat_push_codes", [] {
            py::dict d;
            for (int i = 0; i < static_cast<int>(PushCode::kCount); ++i)
                d[kPushCodeNames[i]] = i;
            return d;
        });
        m.add_object("combat_push_scalar",
                     py::reinterpret_steal<py::object>(PyCFunction_NewEx(
                         &g_push_scalar_def, nullptr,
                         m.attr("__name__").ptr())));
        m.def("combat_push_counts", [] {
            py::dict d;
            d["fast_pushes"] = fast_pushes();
            return d;
        });
        m.def("combat_push_reset_counts", [] { fast_pushes() = 0; });
        m.def("combat_set_ref", [fld](std::int64_t h, int f, std::int64_t t) {
            cb::mirror().set_ref(h, fld(f), t);
        });
        m.def("combat_set_ids",
              [fld](std::int64_t h, int f, const std::vector<std::int64_t>& v) {
                  cb::mirror().set_ids(h, fld(f), v);
              });
        m.def("combat_set_fv",
              [fld](std::int64_t h, int f, const std::vector<double>& v) {
                  cb::mirror().set_fv(h, fld(f), v);
              });
        m.def("combat_set_floats",
              [fld](std::int64_t h, int f, const std::vector<double>& v) {
                  cb::mirror().set_floats(h, fld(f), v);
              },
              py::arg("handle"), py::arg("field"), py::arg("values"),
              "A FloatList field (a tube's _reload_timers / "
              "_reload_advanced_at): the whole list, every bit kept.");
        m.def("combat_set_id_lists",
              [fld](std::int64_t h, int f,
                    const std::vector<std::vector<std::int64_t>>& v) {
                  cb::mirror().set_id_lists(h, fld(f), v);
              });
        m.def("combat_set_spheres",
              [](std::int64_t h,
                 const std::vector<std::tuple<double, double, double, double>>& sp) {
                  std::vector<cb::Sphere> v;
                  v.reserve(sp.size());
                  for (const auto& [x, y, z, r] : sp) v.push_back({x, y, z, r});
                  cb::mirror().set_spheres(h, std::move(v));
              });
        m.def("combat_set_profile_rows",
              [](std::int64_t h,
                 const std::vector<std::tuple<double, double>>& rows, double fc) {
                  std::vector<cb::ProfileRow> v;
                  v.reserve(rows.size());
                  for (const auto& [d, s] : rows) v.push_back({d, s});
                  cb::mirror().set_profile_rows(h, std::move(v), fc);
              });
        m.def("combat_set_frame",
              [](std::int64_t h, std::int64_t profile,
                 const std::array<double, 3>& anchor,
                 const std::array<double, 3>& star) {
                  cb::mirror().set_frame(h, profile, anchor, star);
              },
              py::arg("set_handle"), py::arg("profile"), py::arg("anchor"),
              py::arg("star"),
              "A set's RESOLVED profile frame: profile handle (-1 unmapped, "
              "-2 unrepresentable), anchor_gu and star position_gu.");
        // Posed parts (spec 2026-11-01 §4.1): a ship's pose table, a
        // subsystem's part slot, a ship's mount order and the global
        // part-map generation. Pushed by engine/appc/native_combat.py.
        m.def("combat_set_part_poses",
              [](std::int64_t h,
                 const std::vector<std::tuple<std::array<double, 9>,
                                              std::array<double, 3>, bool,
                                              bool>>& entries) {
                  std::vector<cb::PartPose> v;
                  v.reserve(entries.size());
                  for (const auto& [r, t, identity, detached] : entries) {
                      cb::PartPose p;
                      for (int i = 0; i < 9; ++i) p.r[i] = r[i];
                      for (int i = 0; i < 3; ++i) p.t[i] = t[i];
                      p.identity = identity;
                      p.detached = detached;
                      v.push_back(p);
                  }
                  cb::mirror().set_part_poses(h, std::move(v));
              },
              py::arg("handle"), py::arg("entries"),
              "A ship's pose table: one (r9 row-major, t3, identity, "
              "detached) per articulation.posed_part_names name, in order.");
        m.def("combat_set_part_slot",
              [](std::int64_t h, std::int32_t slot, std::uint64_t gen) {
                  cb::mirror().set_part_slot(h, slot, gen);
              },
              py::arg("handle"), py::arg("slot"), py::arg("gen"),
              "A subsystem's part slot (-1: no posable part) and the "
              "part-map generation it was resolved at.");
        m.def("combat_set_mount_order",
              [](std::int64_t h, const std::vector<std::int64_t>& order) {
                  cb::mirror().set_mount_order(h, order);
              },
              py::arg("handle"), py::arg("order"),
              "A ship's subsystems in combat._iter_subsystems order "
              "(-2 for one the mirror cannot name).");
        m.def("combat_set_part_gen",
              [](std::uint64_t gen) { cb::mirror().set_part_gen(gen); },
              py::arg("gen"));
        m.def("combat_part_gen", [] { return cb::mirror().part_gen(); });
        m.def("combat_set_globals",
              [](const py::dict& d) {
                  // Every key is checked before any value is stored.
                  std::vector<std::pair<cb::Global, py::handle>> parsed;
                  for (auto item : d)
                      parsed.emplace_back(
                          cb::global_by_name(py::cast<std::string>(item.first)),
                          item.second);
                  auto& mi = cb::mirror();
                  for (const auto& [g, v] : parsed) {
                      if (cb::global_is_int(g))
                          mi.set_global_i(g, py::cast<std::int64_t>(v));
                      else
                          mi.set_global_f(g, py::cast<double>(v));
                  }
              },
              "Dials, flags and constants by Python name; an unknown name "
              "raises ValueError.");
        m.def("combat_dump_globals", [] {
            auto& mi = cb::mirror();
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::Global::kCount); ++i) {
                auto g = static_cast<cb::Global>(i);
                py::str n(cb::global_name(g));
                if (cb::global_is_int(g)) d[n] = mi.get_global_i(g);
                else d[n] = mi.get_global_f(g);
            }
            return d;
        });
        m.def("combat_clear",
              [] {
                  cb::k1_kernel().clear();
                  cb::k2_kernel().clear();
                  cb::k3_kernel().clear();
                  cb::mirror().clear();
                  k1_launch_modules_clear();
              },
              "Drop every row (tests only; rows normally live as long as their "
              "Python object).");
        m.def("combat_epoch", [] { return cb::mirror().epoch(); });
        m.def("combat_find_by_obj_id",
              [](std::int64_t id) { return cb::mirror().find_by_obj_id(id); },
              "The live Object handle for a Python object id, or -1.");
        m.def("combat_set_obj_id_findable",
              [](std::int64_t h, bool findable) {
                  cb::mirror().set_obj_id_findable(h, findable);
              },
              "Whether combat_find_by_obj_id finds Object row h: off while "
              "its Python id is unregistered (engine.core.ids), on again at "
              "ids.register. ValueError for a stale or non-Object handle.");
        m.def("combat_kinds", [] {
            // Row kind name -> the int combat_register takes.
            static constexpr const char* kNames[] = {
                "Object", "Subsystem", "Property", "Set", "Profile", "Ammo"};
            static_assert(std::size(kNames) ==
                          static_cast<size_t>(cb::Kind::kCount));
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::Kind::kCount); ++i)
                d[py::str(kNames[i])] = i;
            return d;
        });
        m.def("combat_field_names", [] {
            // Python attribute name -> field id. Subsystem._radius shares the
            // name of Object._radius, so it is keyed "Subsystem._radius";
            // Object._invincible shares Subsystem._invincible's, so it is
            // keyed "Object._invincible".
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::Field::kCount); ++i) {
                auto f = static_cast<cb::Field>(i);
                std::string n = cb::field_name(f);
                if (f == cb::Field::s_radius) n = "Subsystem._radius";
                if (f == cb::Field::o_invincible) n = "Object._invincible";
                d[py::str(n)] = i;
            }
            return d;
        });
        m.def("combat_dump", [](std::int64_t h) {
            auto& mi = cb::mirror();
            cb::Kind kind = cb::Mirror::kind_of(h);
            if (!mi.valid(h))
                throw std::invalid_argument("combat mirror: stale handle");
            py::dict d;
            if (kind == cb::Kind::Object) {
                const cb::ObjectRow& row = *mi.object(h);
                d["py_id"] = row.py_id;
                py::list poses;
                for (const auto& p : row.part_poses)
                    poses.append(py::make_tuple(
                        py::make_tuple(p.r[0], p.r[1], p.r[2], p.r[3], p.r[4],
                                       p.r[5], p.r[6], p.r[7], p.r[8]),
                        py::make_tuple(p.t[0], p.t[1], p.t[2]), p.identity,
                        p.detached));
                d["part_poses"] = poses;
                // A since-freed entry reads -2: the ship holds its
                // subsystems strongly, so a dead handle means the row was
                // dropped, never that the subsystem is gone.
                py::list order;
                for (std::int64_t x : row.mount_order)
                    order.append(x == cb::kRefUnrepresentable ||
                                         mi.subsystem(x) != nullptr
                                     ? x
                                     : cb::kRefUnrepresentable);
                d["mount_order"] = order;
            } else if (kind == cb::Kind::Subsystem) {
                const cb::SubsystemRow& row = *mi.subsystem(h);
                d["part_slot"] = row.part_slot;
                d["part_gen"] = row.part_gen;
            }
            for (int i = 0; i < static_cast<int>(cb::Field::kCount); ++i) {
                auto f = static_cast<cb::Field>(i);
                if (cb::field_kind(f) != kind) continue;
                py::str n(cb::field_name(f));
                switch (cb::field_type(f)) {
                    case cb::FieldType::F: d[n] = mi.get_f(h, f); break;
                    case cb::FieldType::I: d[n] = mi.get_i(h, f); break;
                    case cb::FieldType::Ref: d[n] = mi.get_ref(h, f); break;
                    case cb::FieldType::Ids: d[n] = mi.get_ids(h, f); break;
                    case cb::FieldType::IdLists:
                        d[n] = mi.get_id_lists(h, f);
                        break;
                    case cb::FieldType::FloatList:
                        d[n] = mi.get_floats(h, f);
                        break;
                    case cb::FieldType::Vec3: {
                        auto v = mi.get_fv(h, f);
                        if (v.empty()) d[n] = py::none();
                        else if (v.size() == 4)  // point-or-none, state 2
                            d[n] = py::make_tuple(v[0], v[1], v[2], v[3]);
                        else d[n] = py::make_tuple(v[0], v[1], v[2]);
                        break;
                    }
                    case cb::FieldType::Spheres: {
                        py::list l;
                        for (const auto& s : mi.object(h)->spheres)
                            l.append(py::make_tuple(s.x, s.y, s.z, s.r));
                        d[n] = l;
                        break;
                    }
                    case cb::FieldType::Rows: {
                        py::list l;
                        for (const auto& r : mi.profile(h)->rows)
                            l.append(py::make_tuple(r.distance_gu, r.sensors));
                        d[n] = l;
                        break;
                    }
                }
            }
            return d;
        });

        // ── The K3 torpedo table (torpedo_table.h) ───────────────────────
        // One row per in-flight torpedo in projectiles._active order, synced
        // by engine/appc/native_combat.py (torpedo_row_add / _drop /
        // torpedo_table_rebuild). Fields are named by the Python attribute
        // (combat_torp_field_names). A stale handle raises ValueError.
        {
            auto tfld = [](int f) {
                if (f < 0 || f >= static_cast<int>(cb::TorpField::kCount))
                    throw std::invalid_argument("torpedo table: unknown field");
                return static_cast<cb::TorpField>(f);
            };
            m.def("combat_torp_field_names", [] {
                py::dict d;
                for (int i = 0; i < static_cast<int>(cb::TorpField::kCount);
                     ++i)
                    d[py::str(cb::torp_field_name(
                        static_cast<cb::TorpField>(i)))] = i;
                return d;
            });
            m.def("combat_torp_add",
                  [](std::int64_t xi, std::int64_t xg) {
                      return cb::mirror().torpedoes().add(xi, xg);
                  },
                  py::arg("xform_index"), py::arg("xform_gen"),
                  "Append a row (the torpedo's transform handle); returns "
                  "its handle.");
            m.def("combat_torp_drop", [](std::int64_t h) {
                return cb::mirror().torpedoes().drop(h);
            });
            m.def("combat_torp_clear",
                  [] { cb::mirror().torpedoes().clear(); });
            m.def("combat_torp_size",
                  [] { return cb::mirror().torpedoes().size(); });
            m.def("combat_torp_handles",
                  [] { return cb::mirror().torpedoes().handles(); },
                  "Live row handles, in table (= _active) order.");
            m.def("combat_torp_set_f",
                  [tfld](std::int64_t h, int f, double v) {
                      cb::mirror().torpedoes().set_f(h, tfld(f), v);
                  });
            m.def("combat_torp_set_v",
                  [tfld](std::int64_t h, int f, bool is_set, double x,
                         double y, double z) {
                      cb::mirror().torpedoes().set_v(h, tfld(f), is_set,
                                                     {x, y, z});
                  });
            m.def("combat_torp_set_ref",
                  [tfld](std::int64_t h, int f, std::int64_t ref) {
                      cb::mirror().set_torpedo_ref(h, tfld(f), ref);
                  });
            m.def("combat_torp_set_mount",
                  [](std::int64_t h, bool attributed, std::int64_t sub,
                     double x, double y, double z) {
                      cb::mirror().set_torpedo_mount(h, attributed, sub,
                                                     {x, y, z});
                  });
            m.def("combat_torp_set_unrepresentable",
                  [tfld](std::int64_t h, int f) {
                      cb::mirror().torpedoes().set_unrepresentable(h, tfld(f));
                  });
            m.def("combat_torp_dump", [](std::int64_t h) {
                auto& mi = cb::mirror();
                const cb::TorpedoRow& r = mi.torpedoes().checked(h);
                auto vec = [](const cb::TorpedoRow::Vec3& v) {
                    return py::make_tuple(v[0], v[1], v[2]);
                };
                auto opt = [&](bool set, const cb::TorpedoRow::Vec3& v)
                    -> py::object {
                    if (!set) return py::none();
                    return vec(v);
                };
                py::dict d;
                d["xform"] = py::make_tuple(r.xform_index, r.xform_gen);
                d["age"] = r.age;
                d["ttl"] = r.ttl;
                d["guidance_lifetime"] = r.guidance_lifetime;
                d["guidance_initial"] = r.guidance_initial;
                d["max_angular_accel"] = r.max_angular_accel;
                d["damage"] = r.damage;
                d["damage_radius_factor"] = r.damage_radius_factor;
                d["vel"] = vec(r.vel);
                d["target"] = mi.torpedo_ref(r, cb::TorpField::_target_ship);
                d["target_offset"] = opt(r.target_offset_set, r.target_offset);
                d["source"] = mi.torpedo_ref(r, cb::TorpField::_source_ship);
                d["cset"] = mi.torpedo_ref(r, cb::TorpField::_containing_set);
                d["last_seen"] = opt(r.last_seen_set, r.last_seen);
                d["last_tvel"] = opt(r.last_tvel_set, r.last_tvel);
                d["mount_sub"] = mi.torpedo_ref(r, cb::TorpField::_mount_key);
                d["mount_attributed"] = r.mount_attributed ? 1 : 0;
                d["mount_offset"] = vec(r.mount_offset);
                py::list bad;
                for (int i = 0; i < static_cast<int>(cb::TorpField::kCount);
                     ++i)
                    if (r.unrepresentable & (1u << i))
                        bad.append(py::str(cb::torp_field_name(
                            static_cast<cb::TorpField>(i))));
                d["unrepresentable"] = bad;
                return d;
            });
        }

        // subsystems.impulse_fractions from the mirror (impulse.h). Used by
        // tests and by nothing in play (kernel M calls the C++ directly).
        // ValueError means "ask the Python".
        m.def("combat_impulse_fractions",
              [](std::int64_t ies) {
                  const cb::ImpulseFractions f =
                      cb::impulse_fractions(cb::mirror(), ies);
                  return py::make_tuple(f.online, f.output);
              },
              py::arg("ies_handle"),
              "(online, output) of subsystems.impulse_fractions; -1 is no IES.");

        // Kernel M, the ship-motion step (motion_step.h): one
        // released_compute around motion_step alone; the write tuples are
        // built after it, with the GIL held. ValueError: `begin` out of
        // range.
        m.def("combat_motion_constants",
              [] {
                  return py::make_tuple(cb::kFallbackMaxAccel,
                                        cb::kBcImpulseTau);
              },
              "(kFallbackMaxAccel, kBcImpulseTau): motion_step.h's twins of "
              "ship_motion.FALLBACK_MAX_ACCEL and BC_IMPULSE_TAU (pinned "
              "equal by tests/unit/test_native_motion_kernel.py).");
        m.def("combat_motion_compute",
              [](const std::vector<std::int64_t>& rows, std::int64_t player,
                 double dt, std::int64_t begin, bool resume) {
                  cb::MotionResult r =
                      released_compute(ComputeSite::Motion, [&] {
                          return cb::motion_step(cb::mirror(), dauntless::transform_store(), rows, player, dt, begin, resume);
                      });
                  py::list writes;
                  for (const cb::MotionWrite& w : r.writes) {
                      auto v3 = [](const cb::Vec3& v) {
                          return py::make_tuple(v[0], v[1], v[2]);
                      };
                      const auto& mv = w.motion_vel;
                      writes.append(py::make_tuple(
                          w.row, static_cast<int>(w.what), w.speed, v3(w.cav),
                          v3(w.velocity), v3(w.drift),
                          py::make_tuple(mv[0], mv[1], mv[2], mv[3]),
                          v3(w.accel), v3(w.setpoint)));
                  }
                  return py::make_tuple(static_cast<int>(r.stop), r.at,
                                        static_cast<int>(r.reason), writes);
              },
              py::arg("handles"), py::arg("player"), py::arg("dt"),
              py::arg("begin"), py::arg("resume_past_warp"),
              "Kernel M from rows[begin]: (stop, at, reason, writes), writes "
              "[(row, what, speed, cav, velocity, drift, motion_vel, accel, "
              "setpoint), ...] for "
              "native_motion's applier. stop 0 done, 1 a warp row, 2 a "
              "Python row (native_motion.DONE / WARP_ROW / PYTHON_ROW).");

        // Kernel M driven (native motion phase 2, Task 5): the compute
        // released, as combat_motion_compute's, then the write log applied
        // by C under the GIL (motion_write_apply.h), so no write tuple is
        // ever built. `ships` is the Python list the handles were read from
        // (ships[i] is rows[i]'s object). ValueError: `begin` out of range,
        // or `ships` and `handles` of different lengths (checked before the
        // kernel runs). A store that raised: every other store applied, the
        // first exception raised (native_motion's driver resyncs then).
        m.def("combat_motion_step",
              [](py::object ships, const std::vector<std::int64_t>& rows,
                 std::int64_t player, double dt, std::int64_t begin,
                 bool resume) {
                  const Py_ssize_t n = PySequence_Size(ships.ptr());
                  if (n < 0) throw py::error_already_set();
                  if (static_cast<std::size_t>(n) != rows.size())
                      throw py::value_error(
                          "combat_motion_step: " + std::to_string(n) +
                          " ships for " + std::to_string(rows.size()) +
                          " handles");
                  cb::MotionResult r =
                      released_compute(ComputeSite::Motion, [&] {
                          return cb::motion_step(cb::mirror(), dauntless::transform_store(), rows, player, dt, begin, resume);
                      });
                  if (!dauntless::host::apply_motion_writes(ships.ptr(),
                                                            r.writes))
                      throw py::error_already_set();
                  return py::make_tuple(static_cast<int>(r.stop), r.at,
                                        static_cast<int>(r.reason));
              },
              py::arg("ships"), py::arg("handles"), py::arg("player"),
              py::arg("dt"), py::arg("begin"), py::arg("resume_past_warp"),
              "Kernel M from rows[begin], its writes applied into `ships` by "
              "C: (stop, at, reason) (native_motion.DONE / WARP_ROW / "
              "PYTHON_ROW, native_motion.REASONS).");
        // The published-pose buffer (published_poses.h): the motion stage's
        // last act copies each ship row's pose and velocity here, tagged
        // with the tick. GIL held: one short copy, mirror unwritten.
        m.def("combat_motion_publish",
              [](const std::vector<std::int64_t>& handles,
                 std::int64_t tick) {
                  cb::published_poses().publish(
                      cb::mirror(), dauntless::transform_store(), handles,
                      tick);
              },
              py::arg("handles"), py::arg("tick"),
              "Replace the published-pose buffer with these Object handles' "
              "poses, tagged `tick` (-1 and stale handles skipped).");
        m.def("combat_motion_published",
              [] {
                  const cb::PublishedPoses& pp = cb::published_poses();
                  py::list out;
                  for (const cb::PublishedPose& p : pp.all())
                      out.append(py::make_tuple(
                          p.object,
                          py::make_tuple(p.pos[0], p.pos[1], p.pos[2]),
                          py::make_tuple(p.rot[0], p.rot[1], p.rot[2],
                                         p.rot[3], p.rot[4], p.rot[5],
                                         p.rot[6], p.rot[7], p.rot[8]),
                          py::make_tuple(p.vel[0], p.vel[1], p.vel[2])));
                  return py::make_tuple(pp.tick(), out);
              },
              "(tick, [(handle, pos3, rot9, vel3), ...]): the published "
              "buffer (tests).");
        m.def("combat_motion_published_clear",
              [] { cb::published_poses().clear(); });
        // The read window (published_poses.h): publish opens it, this
        // closes it (native_motion.close_published).
        m.def("combat_motion_published_close",
              [] { cb::published_poses().close(); });
        m.def("combat_motion_published_open",
              [] { return cb::published_poses().is_open(); });
        m.def("combat_pose_read",
              [](std::int64_t h) {
                  const auto& t = cb::combat_pose(cb::mirror(), h);
                  return py::make_tuple(
                      py::make_tuple(t.pos[0], t.pos[1], t.pos[2]),
                      py::make_tuple(t.rot[0], t.rot[1], t.rot[2], t.rot[3],
                                     t.rot[4], t.rot[5], t.rot[6], t.rot[7],
                                     t.rot[8]));
              },
              py::arg("h"),
              "(pos3, rot9): the pose the combat kernels read for Object "
              "handle h right now -- published inside the read window, "
              "else live (tests).");
        // Test only: the C applier alone on a Python-encoded log
        // (combat_motion_compute's: [(row, what, speed, cav3, vel3,
        // drift3, motion_vel4, accel3, setpoint3), ...]; a 6-tuple leaves
        // the last three zero, an 8-tuple the setpoint), for
        // tests/unit/test_native_motion_apply.py.
        m.def("combat_motion_apply",
              [](py::object ships, py::list log) {
                  std::vector<cb::MotionWrite> w;
                  w.reserve(log.size());
                  for (py::handle e : log) {
                      auto t = e.cast<py::tuple>();
                      if (t.size() != 6 && t.size() != 8 && t.size() != 9)
                          throw py::value_error(
                              "combat_motion_apply: a write is a 6-, 8- or "
                              "9-tuple");
                      auto v3 = [](py::handle o) {
                          auto v = o.cast<py::tuple>();
                          return cb::Vec3{v[0].cast<double>(),
                                          v[1].cast<double>(),
                                          v[2].cast<double>()};
                      };
                      cb::MotionWrite x{};
                      x.row = t[0].cast<std::uint32_t>();
                      x.what = t[1].cast<std::uint8_t>();
                      x.speed = t[2].cast<double>();
                      x.cav = v3(t[3]);
                      x.velocity = v3(t[4]);
                      x.drift = v3(t[5]);
                      if (t.size() >= 8) {
                          auto mv = t[6].cast<py::tuple>();
                          for (std::size_t i = 0; i < 4; ++i)
                              x.motion_vel[i] = mv[i].cast<double>();
                          x.accel = v3(t[7]);
                      }
                      if (t.size() == 9) x.setpoint = v3(t[8]);
                      w.push_back(x);
                  }
                  if (!dauntless::host::apply_motion_writes(ships.ptr(), w))
                      throw py::error_already_set();
              },
              py::arg("ships"), py::arg("writes"),
              "Test only: apply a kernel M write log by the C path.");

        // ── The detection kernel (sensor_detect.h) ───────────────────────
        // Each answers from the mirror exactly as the Python function of the
        // same name would. ValueError means "ask the Python": a ref the
        // query reached is unrepresentable (-2) or gone, a set list holds
        // such an entry, a transform is invalid, the nebula noise met a
        // non-finite value, or the mirror cannot prove the Python's answer.
        // Handles are Object rows; `now` is the game time.
        m.def("combat_can_detect",
              [](std::int64_t obs, std::int64_t tgt, double now, bool use_memo,
                 std::optional<double> dist_sq, bool apply_concealment,
                 std::optional<double> concealment,
                 std::optional<double> occ_now) {
                  return cb::can_detect(cb::mirror(), obs, tgt, now, use_memo,
                                        dist_sq, apply_concealment,
                                        concealment, occ_now);
              },
              py::arg("obs"), py::arg("tgt"), py::arg("now"),
              py::arg("use_memo"), py::arg("dist_sq") = py::none(),
              py::arg("apply_concealment") = true,
              py::arg("concealment") = py::none(),
              py::arg("occ_now") = py::none(),
              "sensor_detection.can_detect; use_memo is step_memo.active(). "
              "`now` is the nebula drift clock (sensor_detection._game_time), "
              "`occ_now` the occlusion cache's (sensor_occlusion._now); "
              "absent, occ_now is now.");
        m.def("combat_concealment_at",
              [](std::int64_t obj, double now) {
                  return cb::concealment_at(cb::mirror(), obj, now);
              },
              py::arg("obj"), py::arg("now"),
              "sensor_detection.concealment_at.");
        m.def("combat_effective_sensor_range",
              [](std::int64_t obj) {
                  return cb::effective_sensor_range(cb::mirror(), obj);
              },
              py::arg("obj"), "sensor_detection.effective_sensor_range.");
        m.def("combat_in_reach",
              [](std::int64_t obs, std::int64_t tgt) {
                  return cb::in_reach(cb::mirror(), obs, tgt);
              },
              py::arg("obs"), py::arg("tgt"), "sensor_detection.in_reach.");
        m.def("combat_is_hidden_by_cloak",
              [](std::int64_t tgt) {
                  return cb::is_hidden_by_cloak(cb::mirror(), tgt);
              },
              py::arg("tgt"), "sensor_detection.is_hidden_by_cloak.");
        m.def("combat_jammed",
              [](std::int64_t obs, std::int64_t tgt) {
                  return cb::jammed(cb::mirror(), obs, tgt);
              },
              py::arg("obs"), py::arg("tgt"), "sensor_detection.jammed.");
        m.def("combat_occ_blocked",
              [](std::int64_t obs, std::int64_t tgt, double now) {
                  return cb::occ_blocked(cb::mirror(), obs, tgt, now);
              },
              py::arg("obs"), py::arg("tgt"), py::arg("now"),
              "sensor_occlusion.blocked, with its per-set caches.");
        m.def("combat_occ_begin_tick",
              [](double t) { cb::occ_begin_tick(cb::mirror(), t); },
              py::arg("t"), "sensor_occlusion.begin_tick.");
        m.def("combat_occ_reset", [] { cb::occ_reset(cb::mirror()); },
              "sensor_occlusion.reset (the caches and the tick time).");
        m.def("combat_latch_reset", [] { cb::latch_reset(cb::mirror()); },
              "sensor_detection.reset_concealment_state.");
        m.def("combat_latched",
              [](std::int64_t obs, std::int64_t tgt) {
                  return cb::latched(cb::mirror(), obs, tgt);
              },
              py::arg("obs"), py::arg("tgt"), "sensor_detection._latched.");
        m.def("combat_set_latched",
              [](std::int64_t obs, std::int64_t tgt, bool broken) {
                  cb::set_latched(cb::mirror(), obs, tgt, broken);
              },
              py::arg("obs"), py::arg("tgt"), py::arg("broken"),
              "sensor_detection._set_latched for a registered pair (R7: one "
              "latch). ValueError, writing nothing, on a stale handle.");
        m.def("combat_latch_snapshot",
              [](std::int64_t tgt) {
                  return cb::latch_snapshot(cb::mirror(), tgt);
              },
              py::arg("tgt"),
              "Observers latched against tgt, sorted (the audit's snapshot).");
        m.def("combat_latch_restore",
              [](std::int64_t tgt, const std::vector<std::int64_t>& obs) {
                  cb::latch_restore(cb::mirror(), tgt, obs);
              },
              py::arg("tgt"), py::arg("observers"),
              "Replace tgt's latch pairs with combat_latch_snapshot's list.");
        m.def("combat_latch_pairs",
              [](std::int64_t h) {
                  return cb::latch_pairs_of(cb::mirror(), h);
              },
              py::arg("h"),
              "Every latched (observer, target) pair h is in, sorted: what a "
              "row about to be dropped hands to the Python latch.");
        m.def("combat_memo_clear", [] { cb::memo_clear(cb::mirror()); },
              "step_memo.forget() for can_detect's answers and the mount memo.");

        // ── The weapon geometry (weapon_geometry.h) ──────────────────────
        // Each answers as the Python function of the same name would;
        // ValueError means "ask the Python" (a posed ship, a stale handle, an
        // unresolved pulse module, ...). Handles: Object rows for ships and
        // targets, Subsystem rows for banks, tubes and cannons; -1 is None.
        // Vectors are 3-tuples of doubles.
        auto vec = [](const cb::Vec3& v) {
            return py::make_tuple(v[0], v[1], v[2]);
        };
        auto opt_vec = [vec](const std::optional<cb::Vec3>& v) -> py::object {
            return v ? py::object(vec(*v)) : py::none();
        };
        m.def("combat_test_subsystem_world_position",
              [vec](std::int64_t sub, std::int64_t ship, bool use_memo) {
                  return vec(cb::subsystem_world_position(cb::mirror(), sub,
                                                          ship, use_memo));
              },
              py::arg("sub"), py::arg("ship"), py::arg("use_memo"));
        m.def("combat_test_mount_memo_size", [] {
            return cb::mirror().sensor_state().mounts.size();
        });
        m.def("combat_test_resolve_aim_world",
              [vec](std::int64_t ship, std::int64_t target) {
                  return vec(cb::_resolve_aim_world(cb::mirror(), ship, target));
              },
              py::arg("ship"), py::arg("target"));
        m.def("combat_test_resolve_bank_aim_world",
              [vec](std::int64_t bank, std::int64_t target, bool use_memo) {
                  return vec(cb::_resolve_bank_aim_world(cb::mirror(), bank,
                                                         target, use_memo));
              },
              py::arg("bank"), py::arg("target"), py::arg("use_memo"));
        m.def("combat_test_emitter_in_arc",
              [](std::int64_t emitter, std::int64_t ship,
                 const std::array<double, 3>& aim) {
                  return cb::_emitter_in_arc(cb::mirror(), emitter, ship, aim);
              },
              py::arg("emitter"), py::arg("ship"), py::arg("aim"));
        m.def("combat_test_emitter_forward_world",
              [vec](std::int64_t emitter, std::int64_t ship) {
                  return vec(cb::_emitter_forward_world(cb::mirror(), emitter,
                                                        ship));
              },
              py::arg("emitter"), py::arg("ship"));
        m.def("combat_test_target_offset_world",
              [vec](std::int64_t target, const std::array<double, 3>& offset,
                    std::optional<std::int64_t> mount) {
                  return vec(cb::target_offset_world(
                      cb::mirror(), target, offset,
                      mount ? *mount : cb::kNoMount));
              },
              py::arg("target"), py::arg("offset"),
              py::arg("mount") = py::none(),
              "subsystems.target_offset_world with an explicit mount_sub "
              "(None = no mount: a plain body point).");
        m.def("combat_test_authored_mount",
              [](std::int64_t target, const std::array<double, 3>& offset) {
                  const cb::ObjectRow* row = cb::mirror().object(target);
                  if (row == nullptr)
                      throw std::invalid_argument(
                          "combat_test_authored_mount: not a live Object");
                  return cb::authored_mount_subsystem(cb::mirror(), *row,
                                                      offset);
              },
              py::arg("target"), py::arg("offset"),
              "part_severance.authored_mount_subsystem: the subsystem "
              "handle, -1 (None) or -2 (the mirror cannot tell).");
        m.def("combat_test_mount_position",
              [vec](std::int64_t sub, std::int64_t ship) {
                  return vec(cb::subsystem_world_position(cb::mirror(), sub,
                                                          ship, false));
              },
              py::arg("sub"), py::arg("ship"),
              "subsystems._subsystem_world_position, unmemoised (ship -1 = "
              "None). ValueError 'part_stale' when a posed ship's part slot "
              "is not current.");
        m.def("combat_test_resolve_torpedo_aim_point",
              [opt_vec](std::int64_t tube, std::int64_t target) {
                  return opt_vec(cb::_resolve_torpedo_aim_point(cb::mirror(),
                                                                tube, target));
              },
              py::arg("tube"), py::arg("target"));
        m.def("combat_test_in_torpedo_cone",
              [](std::int64_t tube, std::int64_t ship,
                 const std::array<double, 3>& aim, bool use_memo) {
                  return cb::_in_torpedo_cone(cb::mirror(), tube, ship, aim,
                                              use_memo);
              },
              py::arg("tube"), py::arg("ship"), py::arg("aim"),
              py::arg("use_memo"));
        m.def("combat_test_solve_pulse_launch_direction",
              [opt_vec](std::int64_t cannon, std::int64_t ship,
                        std::int64_t target, bool use_memo) {
                  return opt_vec(cb::_solve_pulse_launch_direction(
                      cb::mirror(), cannon, ship, target, use_memo));
              },
              py::arg("cannon"), py::arg("ship"), py::arg("target"),
              py::arg("use_memo"));
        m.def("combat_test_target_within_range_gu",
              [](std::int64_t ship, std::int64_t target, double max_range_gu) {
                  return cb::_target_within_range_gu(cb::mirror(), ship, target,
                                                     max_range_gu);
              },
              py::arg("ship"), py::arg("target"), py::arg("max_range_gu"));
        m.def("combat_test_can_fire",
              [](std::int64_t bank, double now) {
                  const cb::CanFireResult r =
                      cb::can_fire(cb::mirror(), bank, now);
                  return py::make_tuple(r.ok, r.clear_depleted);
              },
              py::arg("bank"), py::arg("now"),
              "(ok, clear_depleted) of a leaf weapon's CanFire; writes nothing.");
        m.def("combat_test_weapon_system_offline",
              [](std::int64_t sys) {
                  return cb::weapon_system_offline(cb::mirror(), sys);
              },
              py::arg("sys"));

        // ── The K2 beam geometry (beam_geometry.h) ───────────────────────
        // Same convention as above: ValueError means "ask the Python".
        m.def("combat_test_resolve_bank_aim_world_at",
              [vec](std::int64_t bank, const std::array<double, 3>& point,
                    bool use_memo) {
                  return vec(cb::_resolve_bank_aim_world_at(cb::mirror(), bank,
                                                            point, use_memo));
              },
              py::arg("bank"), py::arg("point"), py::arg("use_memo"));
        m.def("combat_test_phaser_aim_point",
              [vec](std::int64_t ship, std::int64_t target, bool use_memo) {
                  const cb::AimPoint a =
                      cb::phaser_aim_point(cb::mirror(), ship, target, use_memo);
                  return py::make_tuple(vec(a.point), a.target_sub);
              },
              py::arg("ship"), py::arg("target"), py::arg("use_memo"),
              "((x, y, z), locked Subsystem handle or -1).");
        m.def("combat_test_strip_emit_position",
              [vec](std::int64_t bank, const std::array<double, 3>& target_world,
                    bool use_memo) {
                  return vec(cb::strip_emit_position(cb::mirror(), bank,
                                                     target_world, use_memo));
              },
              py::arg("bank"), py::arg("target_world"), py::arg("use_memo"));
        m.def("combat_test_accumulate_dwell",
              [](std::int64_t bank, double dt) {
                  const cb::DwellResult r =
                      cb::accumulate_dwell(cb::mirror(), bank, dt);
                  return py::make_tuple(r.flushed, r.new_dwell);
              },
              py::arg("bank"), py::arg("dt"),
              "(flushed, new _dwell); writes nothing.");
        m.def("combat_test_take_dwell",
              [](std::int64_t bank) {
                  const cb::DwellResult r = cb::take_dwell(cb::mirror(), bank);
                  return py::make_tuple(r.flushed, r.new_dwell);
              },
              py::arg("bank"), "(flushed, 0.0); writes nothing.");
        m.def("combat_test_ray_sphere_entry",
              [vec](const std::array<double, 3>& origin,
                    const std::array<double, 3>& dir, double max_dist,
                    const std::array<double, 3>& center,
                    double radius) -> py::object {
                  const cb::SphereEntry e = cb::ray_sphere_entry(
                      origin, dir, max_dist, center, radius);
                  switch (e.kind) {
                      case cb::SphereEntry::Kind::Point:
                          return vec(e.point);
                      case cb::SphereEntry::Kind::Origin:
                          return py::str("origin");  // Python's origin object
                      default:
                          return py::none();
                  }
              },
              py::arg("origin"), py::arg("dir"), py::arg("max_dist"),
              py::arg("center"), py::arg("radius"),
              "None, an (x, y, z) entry, or the string 'origin' (Python "
              "returned the origin object itself).");
        m.def("combat_test_world_radius",
              [](std::int64_t object) {
                  return cb::world_radius(cb::mirror(), object);
              },
              py::arg("object"));
        m.def("combat_test_shields_block",
              [](std::int64_t target, bool npc_shields_off,
                 std::int64_t player) {
                  return cb::shields_block(cb::mirror(), target,
                                           npc_shields_off, player);
              },
              py::arg("target"), py::arg("npc_shields_off"),
              py::arg("player"));
        m.def("combat_test_shield_bubble_entry",
              [opt_vec](std::int64_t target, const std::array<double, 3>& origin,
                        const std::array<double, 3>& dir, double max_dist) {
                  return opt_vec(cb::shield_bubble_entry(cb::mirror(), target,
                                                         origin, dir, max_dist));
              },
              py::arg("target"), py::arg("origin"), py::arg("dir"),
              py::arg("max_dist"));

        // ── The K3 projectile geometry (projectile_geometry.h) ───────────
        // Each answers as the Python function it ports; ValueError (from
        // bubble_bound_radius / steer_point_native) means "ask the Python".
        // guide_torpedo returns its status instead of raising.
        m.def("combat_test_bubble_bound_radius",
              [](std::int64_t ship) {
                  return cb::bubble_bound_radius(cb::mirror(), ship);
              },
              py::arg("ship"));
        m.def("combat_test_sphere_hit",
              [](const std::array<double, 3>& p, const std::array<double, 3>& c,
                 double r) { return cb::sphere_hit(p, c, r); },
              py::arg("p"), py::arg("c"), py::arg("r"));
        m.def("combat_test_advance_torpedo",
              [vec, opt_vec](const std::array<double, 3>& prev,
                             const std::array<double, 3>& vel, double dt,
                             double age, double ttl) {
                  const cb::Advance a =
                      cb::advance_torpedo(prev, vel, dt, age, ttl);
                  return py::make_tuple(vec(a.cur), a.age, a.expired,
                                        vec(a.seg), a.seg_len,
                                        opt_vec(a.aim_unit));
              },
              py::arg("prev"), py::arg("vel"), py::arg("dt"), py::arg("age"),
              py::arg("ttl"),
              "(cur, age, expired, seg, seg_len, aim_unit or None); seg, "
              "seg_len and aim_unit are meaningful only when not expired.");
        m.def("combat_test_steer_point",
              [vec](std::int64_t target, py::object offset,
                    std::int64_t mount_sub, const std::array<double, 3>& off) {
                  std::optional<cb::Vec3> o;
                  if (!offset.is_none())
                      o = offset.cast<std::array<double, 3>>();
                  return vec(cb::steer_point_native(cb::mirror(), target, o,
                                                    mount_sub, off));
              },
              py::arg("target"), py::arg("offset"), py::arg("mount_sub"),
              py::arg("off"),
              "offset: a 3-tuple or None (no target offset).");
        auto guide_result = [vec](const cb::GuideResult& r) -> py::tuple {
            using St = cb::GuideResult::Status;
            static const char* const kField[] = {
                "_last_seen_target_pos", "_last_target_vel", "_velocity"};
            switch (r.status) {
                case St::done: {
                    py::list w;
                    for (int i = 0; i < r.n_writes; ++i)
                        w.append(py::make_tuple(
                            kField[static_cast<int>(r.writes[i].field)],
                            vec(r.writes[i].value)));
                    // The mount attributed natively (-1 None), or None
                    // when the shot's `_mount_key` already matched.
                    return py::make_tuple(
                        "done", w,
                        r.attributed ? py::object(py::int_(r.mount))
                                     : py::object(py::none()));
                }
                case St::need_frame:
                    return py::make_tuple("frame", r.frame_set);
                case St::need_steer_point:
                    return py::make_tuple(
                        "steer_point",
                        py::make_tuple(r.resume.target, r.resume.speed,
                                       vec(r.resume.torp_pos)));
                default:
                    return py::make_tuple("guide",
                                          r.why ? r.why : "unknown");
            }
        };
        m.def("combat_test_guide_torpedo",
              [guide_result](std::int64_t torp, double dt, bool use_memo,
                             double drift_now, double occ_now) {
                  auto& mi = cb::mirror();
                  const cb::TorpedoRow row = mi.torpedoes().checked(torp);
                  return guide_result(cb::guide_torpedo(
                      mi, row, dt, cb::step_scan(), use_memo,
                      {drift_now, occ_now}));
              },
              py::arg("torp"), py::arg("dt"), py::arg("use_memo"),
              py::arg("drift_now"), py::arg("occ_now"),
              "('done', [(field, (x, y, z)), ...], mount) in _guide's write "
              "order, mount the subsystem handle attributed natively (-1 "
              "None) or None when nothing was attributed; "
              "('frame', set_handle); ('steer_point', (target, speed, "
              "torp_pos)) for combat_test_guide_torpedo_resume; or "
              "('guide', reason).");
        m.def("combat_test_guide_torpedo_resume",
              [guide_result](std::int64_t torp, double dt, std::int64_t target,
                             double speed,
                             const std::array<double, 3>& torp_pos,
                             const std::array<double, 3>& steer_point) {
                  auto& mi = cb::mirror();
                  const cb::TorpedoRow row = mi.torpedoes().checked(torp);
                  return guide_result(cb::guide_torpedo_resume(
                      mi, row, dt, {target, speed, torp_pos}, steer_point));
              },
              py::arg("torp"), py::arg("dt"), py::arg("target"),
              py::arg("speed"), py::arg("torp_pos"), py::arg("steer_point"),
              "The rest of _guide after a 'steer_point' answer.");

        // ── The K2 hull trace (beam_trace.h) ─────────────────────────────
        // The kernel reaches the renderer's trace only through these hooks:
        // trace_instance_for_python and instance_translation_for_python on
        // g_world, the very bodies of the ray_trace_mesh and
        // instance_translation bindings.
        cb::install_trace_hooks(combat_trace_hooks());
        m.def("combat_test_resolve_hit_point",
              [vec](std::int64_t target, py::object iid,
                    const std::array<double, 3>& origin, py::object dir,
                    double max_dist, const std::array<double, 3>& fallback,
                    py::object view_offset) {
                  std::optional<cb::InstanceId> id;
                  if (!iid.is_none()) {
                      const auto s = iid.cast<scenegraph::InstanceId>();
                      id = cb::InstanceId{s.index, s.generation};
                  }
                  std::optional<cb::Vec3> d, off;
                  if (!dir.is_none()) d = dir.cast<std::array<double, 3>>();
                  if (!view_offset.is_none())
                      off = view_offset.cast<std::array<double, 3>>();
                  const cb::ResolvedHit r = cb::resolve_hit_point(
                      cb::mirror(), cb::installed_trace_hooks(), target, id,
                      origin, d, max_dist, fallback, off);
                  static const char* const kTier[] = {"mesh", "sphere",
                                                      "fallback", "origin"};
                  return py::make_tuple(
                      vec(r.point),
                      r.normal ? py::object(vec(*r.normal)) : py::none(),
                      kTier[static_cast<int>(r.tier)]);
              },
              py::arg("target"), py::arg("iid"), py::arg("origin"),
              py::arg("dir"), py::arg("max_dist"), py::arg("fallback_point"),
              py::arg("view_offset"),
              "((x, y, z), normal (x, y, z) or None, tier): tier 'mesh', "
              "'sphere', 'fallback' (the point IS fallback_point) or 'origin' "
              "(the point IS origin). iid: an InstanceId or None (absent); "
              "dir / view_offset: a 3-tuple or None.");
        m.def("combat_test_narrow",
              [](double x) { return cb::narrow_like_pybind(x); },
              py::arg("x"), "The kernel's double -> float narrowing.");
        m.def("combat_test_pybind_narrow", [](float x) { return x; },
              py::arg("x"),
              "pybind's own narrowing of a float argument, for comparison.");

        // ── The K1 fire-control kernel (k1_fire_control.h) ───────────────
        // A stack of sessions over the mirror, each run whole by ONE
        // combat_k1_next (ONE CALL PER SESSION): its record is
        //   (DONE, writes, no_fire_new)
        // `writes` [] when an applier context is installed
        // (combat_set_applier: the binding applied them before returning;
        // combat_write_apply.h), else a list of (handle, field name, value).
        // Values: float / bool / int; `_target` an Object handle or -1
        // (None); `_target_list` a list of handles; `_target_offset` None or
        // ("walk_offset", walk, system) (that walk's own offset object,
        // ruling P5). `no_fire_new`: the K1NoFire names counted for the
        // first time since the counts were reset (the driver logs each
        // once). The record's queue entries go into the combat effect queue
        // (k1_append_entries) once its writes are applied, before it is
        // returned; a raising apply drops them.
        m.def("combat_k1_kinds", [] {
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::K1Kind::kCount); ++i)
                d[cb::k1_kind_name(static_cast<cb::K1Kind>(i))] = i;
            return d;
        });
        m.def("combat_k1_begin_pump",
              [](std::vector<std::int64_t> ships, double dt, double now,
                 bool use_memo, double drift_now) {
                  cb::k1_kernel().begin_pump(std::move(ships), dt, now,
                                             use_memo, drift_now);
              },
              py::arg("ship_handles"), py::arg("dt"), py::arg("now"),
              py::arg("use_memo"), py::arg("drift_now"),
              "_pump_held_weapons over Object handles (-1: no row). `now` is "
              "weapon_subsystems._game_time(), `drift_now` native_combat.now() "
              "(can_detect's nebula drift clock), use_memo step_memo.active().");
        m.def("combat_k1_begin_system",
              [](std::int64_t system, double dt, double now, bool use_memo,
                 double drift_now) {
                  cb::k1_kernel().begin_system(system, dt, now, use_memo,
                                               drift_now);
              },
              py::arg("system"), py::arg("dt"), py::arg("now"),
              py::arg("use_memo"), py::arg("drift_now"),
              "StartFiring's immediate update (dt 0) on one system.");
        m.def("combat_k1_begin_tractor",
              [](std::int64_t system, std::int64_t target,
                 std::optional<std::array<double, 3>> offset, double now,
                 bool use_memo, double drift_now) {
                  cb::k1_kernel().begin_tractor(system, target, offset, now,
                                                use_memo, drift_now);
              },
              py::arg("system"), py::arg("target"), py::arg("offset"),
              py::arg("now"), py::arg("use_memo"), py::arg("drift_now"),
              "TractorBeamSystem.StartFiring's engage (k1_fire_control.h, THE "
              "TRACTOR WALK), its intent already written: `target` an Object "
              "handle (-1 None, -2 unnamed), `offset` the StartFiring "
              "offset's xyz when it is a TGPoint3, else None (the session's "
              "walk 1).");
        // THE SDK ROUTES (k1_fire_control.h): the SDK's own weapon calls
        // as one-weapon sessions (driven by native_combat.run_k1 like the
        // others) and CanFire's native answer.
        m.def("combat_k1_begin_dumb",
              [](std::int64_t tube, double now, bool use_memo,
                 double drift_now) {
                  cb::k1_kernel().begin_dumb(tube, now, use_memo, drift_now);
              },
              py::arg("tube"), py::arg("now"), py::arg("use_memo"),
              py::arg("drift_now"),
              "Weapon.FireDumb(0, 1) on `tube` (its Subsystem handle).");
        m.def("combat_k1_begin_fire",
              [](std::int64_t weapon, std::int64_t target,
                 std::optional<std::array<double, 3>> offset,
                 std::optional<std::int64_t> ship_target, double now,
                 bool use_memo, double drift_now) {
                  cb::k1_kernel().begin_fire(weapon, target, offset,
                                             ship_target, now, use_memo,
                                             drift_now);
              },
              py::arg("weapon"), py::arg("target"), py::arg("offset"),
              py::arg("ship_target"), py::arg("now"), py::arg("use_memo"),
              py::arg("drift_now"),
              "weapon.Fire(target, offset): `target` an Object handle (-1 "
              "None, -2 unnamed), `offset` Fire's offset xyz when it is a "
              "TGPoint3 (else None), `ship_target` the weapon's ship's "
              "GetTarget() handle, None when not read. combat_k1_result() "
              "after DONE: 1 fired, 0 not (a no-fire included).");
        m.def("combat_k1_result", [] { return cb::k1_kernel().result(); },
              "The top session's result (combat_k1_begin_fire), read after "
              "its DONE and before combat_k1_end.");
        m.def("combat_k1_can_fire",
              [](std::int64_t weapon, double now) {
                  const cb::CanFireResult r =
                      cb::k1_kernel().sdk_can_fire(weapon, now);
                  return py::make_tuple(r.ok, r.clear_depleted);
              },
              py::arg("weapon"), py::arg("now"),
              "weapon.CanFire() from the mirror: (ok, clear_depleted). "
              "ValueError when the mirror cannot answer.");
        m.def("combat_k1_next", [] {
            // The kernel's compute runs with the GIL released, and only it
            // (THE GIL RELEASE): it makes no CPython call. The applier and
            // the appends after it keep the lock.
            // tests/unit/test_native_k1_holds_gil.py guards it.
            k1_apply_raised() = false;
            cb::K1Record r = released_compute(ComputeSite::K1, [] {
                return cb::k1_kernel().next();
            });
            py::list writes;
            dauntless::host::WriteApplier& applier =
                dauntless::host::write_applier();
            if (applier.has_context()) {
                // The record's writes applied here, in order, before it is
                // returned (combat_write_apply.h); `writes` stays [].
                if (!applier.apply(r.writes, 0, r.writes.size())) {
                    k1_apply_raised() = true;
                    // A write that raised (or a walk-offset marker skipped
                    // after its materialise raised) left Python without
                    // what K1 stamped: no offset source can be trusted
                    // (mirror.h, THE OFFSET SOURCE).
                    cb::mirror().forget_offset_sources();
                    throw py::error_already_set();
                }
            } else for (const cb::K1Write& w : r.writes) {
                writes.append(
                    py::make_tuple(w.handle, w.field, k1_value_py(w.value)));
            }
            k1_append_entries(r.entries);
            py::list fresh;
            for (size_t i = 0;
                 i < static_cast<size_t>(cb::K1NoFire::kCount); ++i)
                if ((r.no_fire_new >> i) & 1u)
                    fresh.append(cb::k1_no_fire_name(
                        static_cast<cb::K1NoFire>(i)));
            return py::make_tuple(static_cast<int>(r.kind), writes,
                                  py::tuple(fresh));
        }, "The top session's record, the whole session (see "
           "combat_k1_kinds).");
        m.def("combat_k1_walk_manual_offset",
              [](std::int64_t walk) -> py::object {
                  const std::optional<cb::Vec3> o =
                      cb::k1_kernel().walk_manual_offset(walk);
                  if (!o) return py::none();
                  return py::make_tuple((*o)[0], (*o)[1], (*o)[2]);
              },
              py::arg("walk"),
              "THE WALK OFFSET: the Manual Aim pick the top session's walk "
              "`walk` took its offset from, (x, y, z), or None when it was "
              "the system's _held_offset.");
        m.def("combat_set_launch_module",
              [](std::int64_t row, py::handle module) {
                  // A handle no longer live is ignored: nothing would ever
                  // release its entry (combat_unregister has run).
                  if (!cb::mirror().valid(row)) return;
                  auto& t = k1_launch_modules();
                  PyObject* old = nullptr;
                  if (auto it = t.find(row); it != t.end()) {
                      old = it->second;
                      t.erase(it);
                  }
                  if (!module.is_none())
                      t[row] = Py_NewRef(module.ptr());
                  Py_XDECREF(old);
              },
              py::arg("row"), py::arg("module"),
              "The module a row's launch resolved to -- an Ammo row's cached "
              "launch, a pulse cannon's P6 module -- (a kernel SPAWN carries "
              "it); None drops it. Released when the row is unregistered.");
        m.def("combat_k1_walk_offset",
              [](std::int64_t system) -> py::object {
                  const cb::Mirror& mm = cb::mirror();
                  const std::optional<cb::Vec3> o = cb::k1_live_held_offset(
                      mm, system, cb::climb_to_ship_of(mm, system));
                  if (!o) return py::none();
                  return py::make_tuple((*o)[0], (*o)[1], (*o)[2]);
              },
              py::arg("system"),
              "The walk offset K1 computes for `system` (its "
              "_live_held_offset() from the mirror): (x, y, z) or None.");
        m.def("combat_k1_end", [] { cb::k1_kernel().end(); },
              "Pop the top session (it must have returned DONE).");
        m.def("combat_k1_abandon", [] {
                  cb::k1_kernel().abandon();
                  // The exception path: whatever Python made of the
                  // session's record, trust no offset source.
                  cb::mirror().forget_offset_sources();
              },
              "Pop the top session whatever its state (exception path).");
        m.def("combat_k1_depth",
              [] { return cb::k1_kernel().depth(); });
        m.def("combat_k1_counts", [] {
            const auto& c = cb::k1_kernel().counts();
            py::dict d;
            d["k1_records"] = c.records;
            py::dict posed;
            posed["walks"] = c.posed_walks;
            posed["target_aims"] = c.posed_target_aims;
            d["k1_posed"] = posed;
            // The walk starts, and the effects logged as writes (round
            // trips): Fires on a beam already firing and stops of a bank not
            // firing.
            py::dict logged;
            logged["walk_start"] = c.logged_walk_start;
            logged["beam_sustain"] = c.logged_beam_sustain;
            // ... and the sustain stamps it skipped as changing nothing
            // (phase 6 A3).
            logged["beam_sustain_skips"] = c.logged_beam_sustain_skips;
            logged["idle_bank_stop"] = c.logged_idle_bank_stop;
            // ... and, as writes plus queue entries (spec 2026-11-02-combat-
            // fire-events §4.3): beam edges, failed aims, firing banks'
            // stops and the pump's system stops.
            logged["beam_edge"] = c.logged_beam_edge;
            logged["fire_failed"] = c.logged_fire_failed;
            logged["firing_bank_stop"] = c.logged_firing_bank_stop;
            logged["system_stop"] = c.logged_system_stop;
            // ... and launches at the boundary (spec 2026-11-02-combat-
            // launch-deferral §4.1): tube and dumb launches made as writes
            // plus a SPAWN, dumb fires refused.
            logged["tube_launch"] = c.logged_tube_launch;
            logged["dumb_launch"] = c.logged_dumb_launch;
            logged["dumb_refused"] = c.logged_dumb_refused;
            // ... and a cannon's: its drain, cooldown and SPAWN.
            logged["pulse_launch"] = c.logged_pulse_launch;
            // ... and the tractor walks (fire control native only, M4): the
            // pump's, and StartFiring's sessions.
            logged["tractor_walk"] = c.logged_tractor_walk;
            logged["tractor_start"] = c.logged_tractor_start;
            // ... and the SDK's own weapon calls (THE SDK ROUTES).
            logged["sdk_dumb_fire"] = c.logged_sdk_dumb_fire;
            logged["sdk_fire"] = c.logged_sdk_fire;
            logged["sdk_can_fire"] = c.logged_sdk_can_fire;
            d["k1_logged"] = logged;
            // Walks that did not fire that tick, by why (NO FIRE: R2, R3;
            // native_combat.counts adds the driver's own).
            py::dict no_fire;
            for (size_t i = 0; i < c.no_fire.size(); ++i)
                no_fire[cb::k1_no_fire_name(static_cast<cb::K1NoFire>(i))] =
                    c.no_fire[i];
            d["k1_no_fire"] = no_fire;
            // The launches the kernel could not make, by why.
            py::dict launch;
            for (size_t i = 0; i < c.launch_why.size(); ++i)
                launch[cb::k1_launch_why_name(static_cast<cb::K1LaunchWhy>(i))] =
                    c.launch_why[i];
            d["k1_launch_reasons"] = launch;
            // The queue entries K1 produced, by kind.
            py::dict entries;
            for (size_t i = 0; i < c.entries.size(); ++i)
                entries[cb::k1_effect_name(static_cast<cb::K1Effect>(i))] =
                    c.entries[i];
            d["k1_entries"] = entries;
            return d;
        });
        m.def("combat_k1_reset_counts",
              [] { cb::k1_kernel().reset_counts(); });

        // ── The K0 charging kernel (k0_charging.h) ───────────────────────
        // One resumable session over the mirror: host_loop._advance_weapons
        // in the per-tick model. Records are tuples
        //   (kind, a, ship_pos, group, index, reason, writes)
        // of kind RUN_PYTHON or DONE only (DEPLETE_STOP, RELOADED and WATCH
        // are writes plus queue entries since combat fire events: each
        // record's entries go into the combat effect queue as it is
        // returned, k0_append_entries).
        // kind a combat_k0_kinds() int; a the weapon (or the ship for a
        // whole-ship RUN_PYTHON, -2 for a weapon the mirror cannot name);
        // ship_pos / group / index where in the begin snapshot (group 0
        // phaser, 1 pulse, 2 tractor, 3 torpedo; -1 for a whole ship and
        // DONE); reason the K0Reason name of a RUN_PYTHON (else None);
        // writes [] when an applier context is installed (the binding
        // applied the record's log before returning, combat_write_apply.h),
        // else the log in the Python encoding.
        m.def("combat_k0_kinds", [] {
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::K0Kind::kCount); ++i)
                d[cb::k0_kind_name(static_cast<cb::K0Kind>(i))] = i;
            return d;
        });
        m.def("combat_k0_begin",
              [](py::handle ships, double dt, double now) {
                  // No override guard (phase 6 A2, Part A): each ship's
                  // Object handle, then the kernel's plan.
                  std::vector<std::int64_t> handles;
                  if (!k0_ship_handles(ships.ptr(), handles))
                      throw py::error_already_set();
                  cb::K0Session& k = cb::k0_session();
                  if (k.open())
                      throw std::logic_error(
                          "combat K0: a session is already open");
                  k.begin(std::move(handles), dt, now);
              },
              py::arg("ships"), py::arg("dt"), py::arg("now"),
              "Begin _advance_weapons(ships, dt) for one tick: `ships` the "
              "Python ship list (each one's Object handle read from its "
              "_nslot), `now` weapon_subsystems._game_time(). Every ship and "
              "weapon is native; only the kernel's representability reasons "
              "hand back (no override guard).");
        m.def("combat_k0_next", [] {
            // Compute with the GIL released (THE GIL RELEASE), as
            // combat_k1_next. The weapon check is a set lookup made at
            // begin: no CPython call inside the walk.
            cb::K0Session& k = cb::k0_session();
            cb::K0Record r = released_compute(ComputeSite::K0, [&k] {
                return k.next();
            });
            py::list writes;
            dauntless::host::WriteApplier& applier =
                dauntless::host::write_applier();
            if (applier.has_context()) {
                // r.writes views the session's log: the Python the apply
                // runs (wake hooks, setters) must not reach next() and
                // clear it (THE DELIVERY, k0_charging.h).
                struct Delivering {
                    cb::K0Session& k;
                    explicit Delivering(cb::K0Session& s) : k(s) {
                        k.set_delivering(true);
                    }
                    ~Delivering() { k.set_delivering(false); }
                } delivering(k);
                if (!applier.apply(r.writes)) throw py::error_already_set();
            } else {
                for (const cb::K0Write& w : r.writes)
                    writes.append(k0_write_tuple(w));
            }
            // Its queue entries, once its writes are applied (a raising
            // apply drops them, as K1's): THE EFFECT QUEUE, k0_charging.h.
            k0_append_entries(r.entries);
            // The reason names, made once and never freed (no decref
            // after the interpreter is gone).
            static PyObject** const reasons = [] {
                constexpr size_t n = static_cast<size_t>(cb::K0Reason::kCount);
                PyObject** a = new PyObject*[n];
                for (size_t i = 0; i < n; ++i)
                    a[i] = PyUnicode_InternFromString(
                        cb::k0_reason_name(static_cast<cb::K0Reason>(i)));
                return a;
            }();
            const py::object reason =
                r.reason ? py::reinterpret_borrow<py::object>(
                               reasons[static_cast<size_t>(*r.reason)])
                         : py::object(py::none());
            return py::make_tuple(static_cast<int>(r.kind), r.a, r.ship_pos,
                                  r.group, r.index, reason, writes);
        }, "The session's next record (see combat_k0_kinds).");
        m.def("combat_k0_end", [] { cb::k0_session().end(); },
              "Close the session (it must have returned DONE).");
        m.def("combat_k0_abandon", [] { cb::k0_session().abandon(); },
              "Close the session whatever its state (exception path).");
        m.def("combat_k0_open", [] { return cb::k0_session().open(); });
        m.def("combat_k0_counts", [] {
            const auto& c = cb::k0_session().counts();
            py::dict d;
            d["k0_steps"] = c.steps;
            py::dict rec, why;
            for (size_t i = 0; i < c.records.size(); ++i)
                rec[cb::k0_kind_name(static_cast<cb::K0Kind>(i))] =
                    c.records[i];
            for (size_t i = 0; i < c.python_reasons.size(); ++i)
                why[cb::k0_reason_name(static_cast<cb::K0Reason>(i))] =
                    c.python_reasons[i];
            d["k0_records"] = rec;
            d["k0_python_reasons"] = why;
            d["k0_logged_writes"] = c.logged_writes;
            // Watcher lines the mirror already held (phase 6 A2).
            d["k0_identical_writes"] = c.identical_writes;
            // Records K0 no longer returns (combat fire events §4.3): a firing
            // bank drained dry, a reload, a watcher line with checks -- and
            // the queue entries they produced, by kind.
            py::dict logged, entries;
            logged["deplete_stop"] = c.logged_deplete_stop;
            logged["reload"] = c.logged_reload;
            logged["watch"] = c.logged_watch;
            // ... and a holding tractor's stop (fire control native only).
            logged["hold_stop"] = c.logged_hold_stop;
            d["k0_logged"] = logged;
            for (size_t i = 0; i < c.entries.size(); ++i)
                entries[cb::k0_effect_name(static_cast<cb::K0Effect>(i))] =
                    c.entries[i];
            d["k0_entries"] = entries;
            return d;
        });
        // ── The subsystem stage session (subsystem_step.h) ──────────────
        // One session object per stage (no process-wide session: a stage
        // nested in a handler gets its own). Records are tuples
        //   (type, ship_pos, ship, kind, code, a, b, sub)
        // with type and kind ints named by combat_subsys_kinds() (kind a
        // piece for RUN_PYTHON, an event kind for EVENT, -1 for DONE).
        m.def("combat_subsys_kinds", [] {
            py::dict types, pieces, events, skips;
            for (int i = 0;
                 i < static_cast<int>(cb::SubsystemRecordType::kCount); ++i)
                types[cb::subsystem_record_type_name(
                    static_cast<cb::SubsystemRecordType>(i))] = i;
            for (int i = 0; i < static_cast<int>(cb::SubsystemPiece::kCount);
                 ++i)
                pieces[cb::subsystem_piece_name(
                    static_cast<cb::SubsystemPiece>(i))] = i;
            for (int i = 0; i < static_cast<int>(cb::SubsystemEvent::kCount);
                 ++i)
                events[cb::subsystem_event_name(
                    static_cast<cb::SubsystemEvent>(i))] = i;
            for (int i = 0; i < static_cast<int>(cb::SubsystemSkip::kCount);
                 ++i)
                skips[cb::subsystem_skip_name(
                    static_cast<cb::SubsystemSkip>(i))] = i;
            return py::make_tuple(types, pieces, events, skips);
        }, "(record types, pieces, event kinds, skip reasons): name -> int.");
        py::class_<cb::SubsystemSession>(m, "combat_SubsystemSession")
            .def_readonly("dt", &cb::SubsystemSession::dt)
            .def_readonly("done", &cb::SubsystemSession::done);
        m.def("combat_subsys_begin",
              [](const std::vector<std::int64_t>& ships, double dt) {
                  return cb::subsystems::begin(cb::mirror(), ships, dt);
              },
              py::arg("ships"), py::arg("dt"),
              "Begin one subsystem stage over `ships` (Object handles in "
              "roster order, -1 for a ship with no row) for a tick of `dt`.");
        m.def("combat_subsys_next",
              [](cb::SubsystemSession& s, py::object registry,
                 py::object dmg_ctx) {
                  const cb::SubsystemRecord r =
                      cb::subsystems::next(s, cb::mirror());
                  // THE WRITE LOG: into the Python objects before Python
                  // runs the record (subsystem_write_apply.h).
                  if (!dauntless::host::apply_subsystem_writes(registry.ptr(),
                                                               s.writes))
                      throw py::error_already_set();
                  s.writes.clear();
                  // The repair piece's condition writes (damage.h
                  // set_condition, killer None): applied and their entries
                  // queued as combat_dmg_set_condition applies its own,
                  // under native_combat's damage applier context.
                  if (!s.dmg.writes.empty() || !s.dmg.entries.empty()) {
                      PyObject* ctx = dmg_ctx.ptr();
                      if (!dmg_fast_ctx_ok(ctx)) {
                          s.dmg.clear();
                          throw std::runtime_error(
                              "subsystem stage: the damage applier context "
                              "is not usable (in use, or malformed)");
                      }
                      PyObject* done = dmg_fast_run(ctx, [&] {
                          if (!s.dmg.writes.empty() &&
                              !dauntless::host::write_applier().apply(
                                  s.dmg.writes, 0, s.dmg.writes.size()))
                              throw py::error_already_set();
                          damage_append_entries(s.dmg.entries, nullptr);
                          return true;
                      });
                      s.dmg.clear();
                      if (done == nullptr) throw py::error_already_set();
                      Py_DECREF(done);
                  }
                  return py::make_tuple(static_cast<int>(r.type), r.ship_pos,
                                        r.ship, r.kind, r.code, r.a, r.b,
                                        r.sub);
              },
              py::arg("session"), py::arg("registry"), py::arg("dmg_ctx"),
              "The session's next record (see combat_subsys_kinds), its "
              "write log applied first through `registry` "
              "(native_combat._registry), then the repair piece's condition "
              "writes and effect-queue entries under `dmg_ctx` "
              "(native_combat._dmg_context()).");
        m.def("combat_subsys_repair_state",
              [](const cb::SubsystemSession& s) {
                  return py::make_tuple(s.repair_teams, s.repair_points,
                                        s.repair_index, s.repair_worked,
                                        s.repair_completed);
              },
              py::arg("session"),
              "The repair piece's locals (subsystem_step.h THE REPAIR "
              "PIECE): (teams, points, queue index, worked item handles, "
              "completed item handles), for REPAIR_CANNOT's, REPAIR_SET's "
              "and REPAIR_DONE's handlers.");
        m.def("combat_subsys_repair_complete",
              [](cb::SubsystemSession& s, std::int64_t h) {
                  cb::subsystems::repair_complete(s, h);
              },
              py::arg("session"), py::arg("item"),
              "REPAIR_SET's answer: the item Python just repaired is "
              "complete (it joins the completions in item order).");
        m.def("combat_subsys_skips",
              [](const cb::SubsystemSession& s) {
                  py::list out;
                  for (const cb::SubsystemSkipRecord& k : s.skips)
                      out.append(py::make_tuple(
                          k.ship_pos, static_cast<int>(k.piece),
                          static_cast<int>(k.why), k.sub));
                  return out;
              },
              py::arg("session"),
              "The session's skips (subsystem_step.h THE SKIPS), in walk "
              "order: (ship_pos, piece, reason, subsystem handle or -1).");
        m.def("combat_subsys_skip_counts", [] {
            py::dict out;
            for (int p = 0; p < static_cast<int>(cb::SubsystemPiece::kCount);
                 ++p)
                for (int k = 0;
                     k < static_cast<int>(cb::SubsystemSkip::kCount); ++k) {
                    const auto n = cb::subsystems::skip_count(
                        static_cast<cb::SubsystemPiece>(p),
                        static_cast<cb::SubsystemSkip>(k));
                    if (n != 0)
                        out[py::make_tuple(
                            cb::subsystem_piece_name(
                                static_cast<cb::SubsystemPiece>(p)),
                            cb::subsystem_skip_name(
                                static_cast<cb::SubsystemSkip>(k)))] = n;
                }
            return out;
        }, "THE SKIPS, process-wide: {(piece, reason): count}, the non-zero "
           "ones, since the last combat_subsys_skip_counts_reset().");
        m.def("combat_subsys_write_stats", [] {
            const auto w = cb::subsystems::write_stats();
            py::dict out;
            out["logged"] = w.logged;
            out["identical"] = w.identical;
            return out;
        }, "Writes the subsystem stage logged and writes it skipped as "
           "bit-identical to the mirror, since the last "
           "combat_subsys_write_stats_reset().");
        m.def("combat_subsys_write_stats_reset",
              [] { cb::subsystems::reset_write_stats(); },
              "Zero the subsystem stage's write stats.");
        m.def("combat_subsys_skip_counts_reset",
              [] { cb::subsystems::reset_skip_counts(); },
              "Zero THE SKIPS' process-wide counts.");
        // ── The tractor force (tractor_force.h) ──────────────────────────
        // One step over Object handles (host order, -1 for a ship with no
        // row), writing the transform store. Returns (zero_velocity,
        // captures, applied, skipped): the targets HOLD damps (Python calls
        // SetVelocity(TGPoint3(0, 0, 0))), the engage geometry captured --
        // (system, kind 1 hold_point / 2 tow_offset, (x, y, z)), already in
        // the mirror -- the firing projectors applied and the tractors the
        // mirror could not name.
        m.def("combat_tractor_force_step",
              [](const std::vector<std::int64_t>& ships, double dt) {
                  const cb::TractorForceResult r = cb::tractor_force_step(
                      cb::mirror(), dauntless::transform_store(), ships, dt);
                  py::list captures;
                  for (const cb::TractorEngageCapture& c : r.captures)
                      captures.append(py::make_tuple(
                          c.system, c.kind,
                          py::make_tuple(c.point[0], c.point[1], c.point[2])));
                  return py::make_tuple(r.zero_velocity, captures, r.applied,
                                        r.skipped);
              },
              py::arg("ship_handles"), py::arg("dt"),
              "One tractor force step (motion.tractors).");
        m.def("combat_k0_reset_counts", [] {
            cb::k0_session().reset_counts();
            dauntless::host::k0_apply_stats() = {};
        });
        m.def("combat_k0_apply_stats", [] {
            const dauntless::host::K0ApplyStats& s =
                dauntless::host::k0_apply_stats();
            py::dict d;
            d["writes"] = s.writes;
            d["runs"] = s.runs;
            d["identical"] = s.identical;
            d["general"] = s.general;
            return d;
        }, "The lean K0 apply's tallies since combat_k0_reset_counts "
           "(combat_write_apply.h THE LEAN K0 APPLY).");

        // ── The K2 beam kernel (k2_beams.h) ──────────────────────────────
        // One resumable session over the mirror: the `cb.phasers` loop. Each
        // record is a tuple whose first element is a kind int
        // (combat_k2_kinds) and whose LAST element is the write log since the
        // previous record: with an applier context, [] (applied); else a
        // list of (handle, field, value). After DONE, combat_k2_drain
        // presents the resting contacts queued for the drain that it can
        // (the shield splash, k2_present_rest) and hands over the rest
        // (k2_beams.h, RESTING CONTACTS). A record's queue entries (a
        // firing bank's LOOP_STOP) go into the combat effect queue as it is
        // returned; SYSTEM_STOP / BANK_STOP come back only for a stop the
        // kernel cannot log (k2_beams.h, THE EFFECT QUEUE).
        // Layouts
        // (handles -1 = None, xyz = a 3-tuple):
        //   (DONE, writes)
        //   (SYSTEM_STOP, system, writes)
        //   (BANK_STOP, bank, writes)
        //   (CONTACT, bank, target, ship, system, emitter_xyz,
        //    target_pos_xyz, dist, aim_unit_xyz | None, impact_xyz,
        //    normal_xyz | None, tier, bubble_xyz | None,
        //    shields_block True / False / None, flush_dwell, writes)
        //       tier: "mesh", "sphere", "fallback", "origin"
        //   (RUN_PYTHON, ship, ship_pos, writes)
        //   (ASK, query, *args, writes)    -> reply combat_k2_answer
        // The context dict (combat_k2_begin: every key optional, defaults
        // below, except that a begin without "iids" keeps the previous
        // session's table; combat_k2_set_ctx: only the keys given are
        // replaced):
        //   "npc_shields_off": bool (False)
        //   "player": Object handle or -1 (-1)
        //   "view_offsets": {Set handle: (x, y, z) or None} ({})
        //   "iids": {Object handle: ship_instances value} ({}): None is
        //       absent, an InstanceId traces, anything else is "not an
        //       InstanceId" (the sphere tier)
        //   "trace": bool (True): the installed hooks; False when
        //       host_io._h is None (every trace a miss)
        //   "python_ships": iterable of Object handles to RUN_PYTHON (())
        //   "pulse": THE DAMAGE PULSE's context (k2_pulse_ctx's dict; absent:
        //       every damage pulse is a CONTACT record)
        // A record also carries the damage pulses the kernel applied since
        // the last one (k2_beams.h K2Hit): applied and appended here, each
        // where the walk made it among the record's own writes and entries.
        static constexpr const char* kK2Tiers[] = {"mesh", "sphere",
                                                   "fallback", "origin"};
        auto k2_apply_ctx = [](cb::K2Context& c, const py::dict& d) {
            if (d.contains("npc_shields_off"))
                c.npc_shields_off = d["npc_shields_off"].cast<bool>();
            if (d.contains("player"))
                c.player = d["player"].cast<std::int64_t>();
            if (d.contains("view_offsets")) {
                c.view_offsets.clear();
                for (auto kv : d["view_offsets"].cast<py::dict>()) {
                    std::optional<cb::Vec3> off;
                    if (!kv.second.is_none())
                        off = kv.second.cast<std::array<double, 3>>();
                    c.view_offsets[kv.first.cast<std::int64_t>()] = off;
                }
            }
            if (d.contains("iids")) {
                c.iids.clear();
                for (auto kv : d["iids"].cast<py::dict>()) {
                    if (kv.second.is_none()) continue;  // dict.get -> None
                    cb::K2Context::Iid e;
                    if (py::isinstance<scenegraph::InstanceId>(kv.second)) {
                        const auto id = kv.second.cast<scenegraph::InstanceId>();
                        e.id = cb::InstanceId{id.index, id.generation};
                    } else {
                        e.bad = true;
                    }
                    c.iids[kv.first.cast<std::int64_t>()] = e;
                }
            }
            if (d.contains("trace"))
                c.hooks = d["trace"].cast<bool>() ? cb::installed_trace_hooks()
                                                  : cb::TraceHooks{};
            if (d.contains("python_ships")) {
                c.python_ships.clear();
                for (auto h : d["python_ships"])
                    c.python_ships.insert(h.cast<std::int64_t>());
            }
            // THE DAMAGE PULSE (k2_beams.h; k2_pulse_ctx's keys).
            if (d.contains("pulse"))
                c.pulse = k2_pulse_ctx(d["pulse"].cast<py::dict>());
        };
        m.def("combat_k2_kinds", [] {
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::K2Kind::kCount); ++i)
                d[cb::k2_kind_name(static_cast<cb::K2Kind>(i))] = i;
            return d;
        });
        m.def("combat_k2_begin",
              [k2_apply_ctx](std::vector<std::int64_t> ships, double dt,
                             double now, bool use_memo, double drift_now,
                             const py::dict& ctx) {
                  cb::K2Context c;
                  c.hooks = cb::installed_trace_hooks();
                  k2_apply_ctx(c, ctx);
                  // No "iids": the last session's table stands (the driver
                  // sends it only when its key changed).
                  cb::k2_kernel().begin(std::move(ships), dt, now, use_memo,
                                        drift_now, std::move(c),
                                        !ctx.contains("iids"));
              },
              py::arg("ship_handles"), py::arg("dt"), py::arg("now"),
              py::arg("use_memo"), py::arg("drift_now"), py::arg("ctx"),
              "The cb.phasers loop over Object handles (-1: no row). `now` "
              "and `drift_now` are K1's can_detect clocks "
              "(weapon_subsystems._game_time(), native_combat.now()); "
              "use_memo step_memo.active(); ctx as above.");
        m.def("combat_k2_set_ctx",
              [k2_apply_ctx](const py::dict& ctx) {
                  cb::K2Context c = cb::k2_kernel().context();
                  k2_apply_ctx(c, ctx);
                  cb::k2_kernel().set_context(std::move(c));
              },
              py::arg("ctx"), "Replace the given context keys (on resume).");
        // The driver's per-ship, per-bank clean check (k2_scan_ships).
        m.def("combat_k2_scan_ships",
              [](py::handle ships, py::handle obj_kind, py::handle kind_shift,
                 py::handle seen, py::handle stock_system,
                 py::handle stock_bank, py::handle ship_patches,
                 py::handle system_patches, py::handle bank_patches) {
                  PyObject* r = k2_scan_ships(
                      ships.ptr(), obj_kind.ptr(), kind_shift.ptr(),
                      seen.ptr(), stock_system.ptr(), stock_bank.ptr(),
                      ship_patches.ptr(), system_patches.ptr(),
                      bank_patches.ptr());
                  if (r == nullptr) throw py::error_already_set();
                  return py::reinterpret_steal<py::tuple>(r);
              },
              py::arg("ships"), py::arg("obj_kind"), py::arg("kind_shift"),
              py::arg("seen"), py::arg("stock_system"), py::arg("stock_bank"),
              py::arg("ship_patches"), py::arg("system_patches"),
              py::arg("bank_patches"),
              "(handles, [(ship, handle), ...]): see k2_scan_ships.");
        m.def("combat_k2_next", [vec] {
            // Compute with the GIL released (THE GIL RELEASE), as
            // combat_k1_next: the kernel and the trace hooks touch no Python
            // object.
            k2_not_delivering("next()");
            cb::K2Record r = released_compute(ComputeSite::K2, [] {
                return cb::k2_kernel().next();
            });
            // The write log. With an applier context (combat_write_apply.h)
            // the writes are applied here and the record carries []. With
            // none, K1's value encoding (None, bool, int, float, a handle
            // list) -- native_combat.apply_writes applies both.
            py::list log;
            dauntless::host::WriteApplier& applier =
                dauntless::host::write_applier();
            if (!r.hits.empty() && !applier.has_context())
                throw std::logic_error(
                    "combat K2: a damage pulse needs the applier context");
            if (applier.has_context()) {
                const K2Delivering delivering;
                // THE DAMAGE PULSE: each pulse's writes after the record's
                // writes the walk made before it.
                size_t done = 0;
                for (const cb::K2Hit& h : r.hits) {
                    if (!applier.apply(r.writes, done, h.at_write) ||
                        !applier.apply(h.out.writes, 0, h.out.writes.size()))
                        throw py::error_already_set();
                    done = h.at_write;
                }
                if (!applier.apply(r.writes, done, r.writes.size()))
                    throw py::error_already_set();
            } else for (const cb::K2Write& w : r.writes) {
                py::object v = std::visit(
                    [](const auto& x) -> py::object {
                        using T = std::decay_t<decltype(x)>;
                        if constexpr (std::is_same_v<T, std::monostate>)
                            return py::none();
                        else if constexpr (std::is_same_v<T, cb::K1WalkOffset>)
                            throw std::logic_error(
                                "combat K2: a walk-offset write");
                        else if constexpr (std::is_same_v<T, cb::SlotWrite>)
                            throw std::logic_error("combat K2: a slot write");
                        else
                            return py::cast(x);
                    },
                    w.value);
                log.append(py::make_tuple(w.handle, w.field, v));
            }
            // Its queue entries (a firing bank's LOOP_STOP: k2_beams.h, THE
            // EFFECT QUEUE), once its writes are applied, as K1's, with each
            // damage pulse's after the entries made before it.
            k2_last_hits().clear();
            for (const cb::K2Hit& h : r.hits) {
                // HIT_PRESENT's has_shield_point (op 20): a bubble entry.
                bool bubble = false;
                for (const cb::DamageEntry& e : h.out.entries)
                    if (e.kind == cb::DamageKind::HIT_PRESENT)
                        bubble = e.ops[20].boolean;
                k2_last_hits().push_back(
                    {h.bank, h.target, bubble, static_cast<int>(h.tier)});
            }
            {
                const std::span<const cb::K1Entry> all(r.entries);
                size_t done = 0;
                for (const cb::K2Hit& h : r.hits) {
                    k1_append_entries(all.subspan(done, h.at_entry - done));
                    damage_append_held(h.out.entries, h.source);
                    done = h.at_entry;
                }
                k1_append_entries(all.subspan(done));
            }
            const int kind = static_cast<int>(r.kind);
            switch (r.kind) {
                case cb::K2Kind::DONE:
                    return py::make_tuple(kind, log);
                case cb::K2Kind::RUN_PYTHON:
                    return py::make_tuple(kind, r.a, r.b, log);
                case cb::K2Kind::CONTACT: {
                    py::list items;
                    items.append(kind);
                    k2_contact_fields(items, r.contact, vec, false);
                    items.append(log);
                    return py::tuple(items);
                }
                case cb::K2Kind::ASK: {
                    py::list items;
                    items.append(kind);
                    items.append(cb::k2_query_name(r.query));
                    for (const cb::K2Arg& a : r.args) {
                        items.append(std::visit(
                            [&vec](const auto& x) -> py::object {
                                using T = std::decay_t<decltype(x)>;
                                if constexpr (std::is_same_v<T, std::monostate>)
                                    return py::none();
                                else if constexpr (std::is_same_v<T, cb::Vec3>)
                                    return vec(x);
                                else
                                    return py::cast(x);
                            },
                            a));
                    }
                    items.append(log);
                    return py::tuple(items);
                }
                default:  // SYSTEM_STOP, BANK_STOP
                    return py::make_tuple(kind, r.a, log);
            }
        }, "The session's next record (see combat_k2_kinds).");
        m.def("combat_k2_answer",
              [](py::object v) {
                  cb::K2Answer a;
                  switch (cb::k2_kernel().awaiting()) {
                      case cb::K2Query::is_dead:
                      case cb::K2Query::can_detect:
                      case cb::K2Query::shields_block:
                          a.flag = static_cast<bool>(py::bool_(v));
                          break;
                      case cb::K2Query::aim_point: {
                          const auto t = v.cast<py::tuple>();
                          a.point = t[0].cast<std::array<double, 3>>();
                          a.flag = static_cast<bool>(py::bool_(t[1]));
                          break;
                      }
                      case cb::K2Query::bubble:
                          if (v.is_none())
                              a.none = true;
                          else
                              a.point = v.cast<std::array<double, 3>>();
                          break;
                      case cb::K2Query::resolve_hit: {
                          const auto t = v.cast<py::tuple>();
                          a.point = t[0].cast<std::array<double, 3>>();
                          if (!t[1].is_none())
                              a.normal = t[1].cast<std::array<double, 3>>();
                          const auto tier = t[2].cast<std::string>();
                          int k = 0;
                          while (k < 4 && tier != kK2Tiers[k]) ++k;
                          if (k == 4)
                              throw py::value_error("combat K2: unknown tier " +
                                                    tier);
                          a.tier = static_cast<cb::ResolvedHit::Tier>(k);
                          break;
                      }
                      default:  // bank_step (None), or no ASK: answer() raises
                          break;
                  }
                  cb::k2_kernel().answer(a);
              },
              py::arg("value"),
              "ASK's reply, shaped per query (k2_beams.h): a bool; "
              "aim_point ((x, y, z), has_sub); bubble (x, y, z) or None; "
              "resolve_hit ((x, y, z), normal or None, tier); bank_step None.");
        m.def("combat_k2_drain",
              [vec] {
                  k2_not_delivering("drain()");
                  // A shielded rest whose instance and view offset the
                  // kernel knew is presented here, in queue order
                  // (k2_present_rest); every other one is returned, in
                  // queue order, for the Python batch: CONTACT's fields
                  // from `bank` to `flush_dwell`, then what the kernel took
                  // at contact time (k2_beams.h, K2Rest): level, iid (an
                  // InstanceId) or None, view offset or None.
                  std::vector<cb::K2Rest> rests = cb::k2_kernel().take_rests();
                  py::list out;
                  for (const cb::K2Rest& e : rests) {
                      if (k2_present_rest(e, vec)) continue;
                      py::list items;
                      k2_contact_fields(items, e.contact, vec, true);
                      items.append(e.level);
                      items.append(
                          e.iid ? py::cast(scenegraph::InstanceId{
                                      e.iid->index, e.iid->generation})
                                : py::object(py::none()));
                      items.append(e.view_offset
                                       ? py::object(vec(*e.view_offset))
                                       : py::object(py::none()));
                      out.append(py::tuple(items));
                  }
                  return out;
              },
              "The resting contacts queued for the drain, taken (the queue "
              "is left empty): after DONE, before combat_k2_end (k2_beams.h, "
              "RECORDS). The shielded ones whose instance and view offset "
              "the kernel knew are presented here (the shield splash, spec "
              "2026-11-02 §4.4); the rest are returned, in walk order.");
        m.def("combat_k2_present_constants",
              [](double intensity, double default_radius) {
                  K2Present& st = k2_present();
                  st.intensity = intensity;
                  st.default_radius = default_radius;
                  st.have_consts = true;
              },
              py::arg("intensity"), py::arg("default_radius"),
              "The drain's native presentation constants: "
              "hit_feedback.shield_impact_intensity(\"phaser\") and "
              "combat.PHASER_DEFAULT_DAMAGE_RADIUS (sent by k2_phasers when "
              "they change; until then the drain presents nothing).");
        m.def("combat_present_capture",
              [](py::object lst) {
                  if (!lst.is_none() && !PyList_Check(lst.ptr()))
                      throw py::type_error(
                          "combat_present_capture: a list or None");
                  K2Present& st = k2_present();
                  PyObject* old = st.capture;
                  st.capture = lst.is_none() ? nullptr : Py_NewRef(lst.ptr());
                  Py_XDECREF(old);
              },
              py::arg("lst"),
              "Tests: while set, every rest the drain presents natively is "
              "also appended to `lst` as (bank, target, iid, view_xyz, "
              "relative_xyz | None, rgba, intensity, radius) -- view_xyz "
              "the point host_io.shield_hit would be given, relative_xyz "
              "what host_io._instance_relative would make of it (None: the "
              "instance is stale, nothing pushed). None turns it off.");
        m.def("combat_k2_end",
              [] {
                  k2_not_delivering("end()");
                  cb::k2_kernel().end();
              },
              "End the session (it must have returned DONE).");
        m.def("combat_k2_abandon",
              [] {
                  k2_not_delivering("abandon()");
                  cb::k2_kernel().abandon();
              },
              "End the session whatever its state (exception path).");
        m.def("combat_k2_open", [] { return cb::k2_kernel().open(); });
        m.def("combat_k2_counts", [] {
            const auto& c = cb::k2_kernel().counts();
            py::dict d;
            d["k2_records"] = c.records;
            d["k2_python_ships"] = c.python_ships;
            d["k2_asks"] = c.asks;
            py::dict why, queries;
            for (size_t i = 0; i < c.why.size(); ++i)
                why[cb::k2_why_name(static_cast<cb::K2Why>(i))] = c.why[i];
            for (size_t i = 0; i < c.queries.size(); ++i)
                queries[cb::k2_query_name(static_cast<cb::K2Query>(i))] =
                    c.queries[i];
            d["k2_python_reasons"] = why;
            d["k2_ask_queries"] = queries;
            py::dict posed;
            posed["banks"] = c.posed_banks;
            posed["lock_aims"] = c.posed_lock_aims;
            d["k2_posed"] = posed;
            // Records K2 no longer returns (round trips): resting contacts
            // queued for the drain, offline stops logged as writes.
            d["k2_batched_contacts"] = c.batched_contacts;
            d["k2_logged_system_stop"] = c.logged_system_stop;
            // ... and (combat fire events §4.3) the logged system stops that
            // stopped a firing bank, firing banks' stops logged instead of a
            // BANK_STOP record, and the queue entries they produced.
            d["k2_logged_firing_system_stop"] = c.logged_firing_system_stop;
            d["k2_logged_bank_stop"] = c.logged_bank_stop;
            py::dict entries;
            for (size_t i = 0; i < c.entries.size(); ++i)
                entries[cb::k1_effect_name(static_cast<cb::K1Effect>(i))] =
                    c.entries[i];
            d["k2_entries"] = entries;
            // Drained rests the drain presented itself (the shield splash).
            d["k2_present_native"] = k2_present().presented;
            // THE DAMAGE PULSE: pulses applied in the walk, and those kept
            // as a CONTACT record, by why and in all.
            d["k2_native_pulses"] = c.native_pulses;
            py::dict pulse_why;
            std::int64_t pulse_python = 0;
            for (size_t i = 0; i < c.pulse_why.size(); ++i) {
                pulse_why[cb::k2_pulse_why_name(
                    static_cast<cb::K2PulseWhy>(i))] = c.pulse_why[i];
                pulse_python += c.pulse_why[i];
            }
            d["k2_pulse_python_reasons"] = pulse_why;
            d["k2_pulse_python"] = pulse_python;
            return d;
        });
        m.def("combat_k2_pulse_targets",
              [](const std::vector<std::int64_t>& ships) {
                  // The targets a damage pulse may land on this step (THE
                  // DAMAGE PULSE; the driver scans them, combat_dmg_clean):
                  // each distinct `_target` of a bank of a listed ship's
                  // phaser system that fires or holds a dwell -- the only
                  // banks whose walk can flush one -- in first-seen order.
                  // Mirror reads only.
                  const cb::Mirror& mi = cb::mirror();
                  std::vector<std::int64_t> out;
                  std::unordered_set<std::int64_t> seen;
                  for (const std::int64_t sh : ships) {
                      const cb::ObjectRow* o =
                          sh < 0 ? nullptr : mi.object(sh);
                      if (o == nullptr || o->_phaser_system < 0) continue;
                      const cb::SubsystemRow* y =
                          mi.subsystem(o->_phaser_system);
                      if (y == nullptr) continue;
                      for (const std::int64_t b : y->_children) {
                          const cb::SubsystemRow* r =
                              b < 0 ? nullptr : mi.subsystem(b);
                          if (r == nullptr || r->_target < 0) continue;
                          if (!r->_firing && !(r->_dwell > 0.0)) continue;
                          if (seen.insert(r->_target).second)
                              out.push_back(r->_target);
                      }
                  }
                  return out;
              },
              py::arg("ships"),
              "Object handles a damage pulse may land on this step.");
        m.def("combat_k2_last_hits",
              [] {
                  py::list out;
                  for (const auto& [b, t, bubble, tier] : k2_last_hits())
                      out.append(py::make_tuple(b, t, bubble, kK2Tiers[tier]));
                  return out;
              },
              "[(bank, target, bubble, tier), ...]: the damage pulses the last record "
              "carried (THE DAMAGE PULSE; for the differentials' tallies).");
        m.def("combat_k2_take_hits", [] { return cb::k2_kernel().take_hits(); },
              "The damage pulses the records returned since the last call "
              "carried (THE DAMAGE PULSE).");
        m.def("combat_dmg_clean",
              [](py::handle targets, py::handle registry_data,
                 py::handle ship_names, py::handle sub_names) {
                  PyObject* r = dmg_clean(targets.ptr(), registry_data.ptr(),
                                          ship_names.ptr(), sub_names.ptr());
                  if (r == nullptr) throw py::error_already_set();
                  return py::reinterpret_steal<py::list>(r);
              },
              py::arg("targets"), py::arg("registry_data"),
              py::arg("ship_names"), py::arg("sub_names"),
              "[bool, ...]: which targets a kernel may hit natively (see "
              "dmg_clean).");
        m.add_object("combat_dmg_set_condition",
                     py::reinterpret_steal<py::object>(PyCFunction_NewEx(
                         &g_dmg_set_condition_def, nullptr,
                         m.attr("__name__").ptr())));
        m.add_object("combat_dmg_damage_system",
                     py::reinterpret_steal<py::object>(PyCFunction_NewEx(
                         &g_dmg_damage_system_def, nullptr,
                         m.attr("__name__").ptr())));
        m.def("combat_dmg_clean_handles",
              [](py::handle handles, py::handle registry_data,
                 py::handle ship_names, py::handle sub_names) {
                  PyObject* r = dmg_clean_handles(
                      handles.ptr(), registry_data.ptr(), ship_names.ptr(),
                      sub_names.ptr());
                  if (r == nullptr) throw py::error_already_set();
                  return py::reinterpret_steal<py::list>(r);
              },
              py::arg("handles"), py::arg("registry_data"),
              py::arg("ship_names"), py::arg("sub_names"),
              "[handle, ...]: the Object `handles` a kernel may hit "
              "natively (dmg_clean on each one's registry object).");
        m.def("combat_dmg_clean_clear", [] { dmg_clean_caches().clear(); });
        m.def("combat_k2_scan_counts", [] {
            py::dict d;
            d["probed"] = k2_scan_counts().probed;
            d["cached"] = k2_scan_counts().cached;
            return d;
        }, "combat_k2_scan_ships' systems and banks probed and answered "
           "from its cache.");
        m.def("combat_k2_scan_reset_counts",
              [] { k2_scan_counts() = K2ScanCounts{}; });
        m.def("combat_k2_scan_clear", [] { k2_scan_caches().clear(); });
        m.def("combat_dmg_clean_counts", [] {
            py::dict d;
            d["probed"] = dmg_clean_counts().probed;
            d["cached"] = dmg_clean_counts().cached;
            return d;
        }, "combat_dmg_clean's objects probed and answered from its cache.");
        m.def("combat_dmg_clean_reset_counts",
              [] { dmg_clean_counts() = DmgCleanCounts{}; });
        m.def("combat_k2_reset_counts", [] {
            cb::k2_kernel().reset_counts();
            k2_present().presented = 0;
        });

        // ── C-applied write logs (combat_write_apply.h) ──────────────────
        m.def("combat_apply_kinds", [] {
            py::dict d;
            for (int i = 0;
                 i < static_cast<int>(dauntless::host::ApplyKind::kCount); ++i)
                d[dauntless::host::apply_kind_name(
                    static_cast<dauntless::host::ApplyKind>(i))] = i;
            return d;
        });
        m.def("combat_k0_field_name",
              [](long field, bool watcher) {
                  namespace cb = dauntless::combat;
                  cb::K0FieldWrite w;
                  w.type = watcher ? cb::K0FieldWrite::Type::Watcher
                                   : cb::K0FieldWrite::Type::Float;
                  w.field = static_cast<cb::Field>(field);
                  PyObject* o = dauntless::host::k0_field_name(w);
                  if (o == nullptr) throw py::error_already_set();
                  return py::reinterpret_borrow<py::object>(o);
              },
              py::arg("field"), py::arg("watcher"),
              "The attribute a K0 write of Field `field` (or the watcher "
              "write) stores into, as the applier names it (tests).");
        m.def("combat_set_applier",
              [](py::handle ctx) {
                  PyObject* prev =
                      dauntless::host::write_applier().set_context(ctx.ptr());
                  if (prev == nullptr) throw py::error_already_set();
                  return py::reinterpret_steal<py::object>(prev);
              },
              py::arg("ctx"),
              "Install the applier context (pins, registry, walk, kinds, "
              "wake, python_setters), or None; returns the previous one "
              "(the driver restores it when its session ends).");
        m.def("combat_apply_log",
              [](py::handle writes) {
                  std::vector<dauntless::host::ApplyWrite> w;
                  if (!dauntless::host::WriteApplier::parse_log(writes.ptr(),
                                                                &w) ||
                      !dauntless::host::write_applier().apply(w, 0, w.size()))
                      throw py::error_already_set();
              },
              py::arg("writes"),
              "Apply a Python-encoded write log [(handle, field, value), "
              "...] through the C path (values as apply_writes', plus "
              "(\"slot\", index, value) and (\"watcher\", value)). "
              "Test-only entry: its encoding is the kernels' logs', not "
              "apply_writes', in two places -- a list value is always a "
              "list of int64 handles (on a PLAIN field apply_writes stores "
              "the list object itself; here a new list is built, and a "
              "non-int entry raises TypeError), and an int beyond 64 bits "
              "raises OverflowError where apply_writes stores it.");
        m.def("combat_apply_raised", [] { return k1_apply_raised(); },
              "Whether the last combat_k1_next raised applying its writes.");
        m.def("combat_apply_counts", [] {
            py::dict d;
            d["c_applied_writes"] = dauntless::host::write_applier().applied();
            return d;
        });
        m.def("combat_apply_reset_counts",
              [] { dauntless::host::write_applier().reset_counts(); });

        // ── The combat effect queue (combat_effect_queue.h) ──────────────
        // Entries come out as (kind, native, operands): a kernel's operands
        // are handles (int) and numbers (float), Python's the objects it
        // posted. engine/appc/effect_queue.py delivers them.
        {
            namespace hq = dauntless::host;
            hq::effect_queue().set_release(
                [](void* p) { Py_DECREF(static_cast<PyObject*>(p)); });
            auto kind_of = [](long k) {
                if (k < 0 || k >= static_cast<long>(hq::EffectKind::kCount))
                    throw py::value_error("combat effect: unknown kind");
                return static_cast<hq::EffectKind>(k);
            };
            m.def("combat_effect_kinds", [] {
                py::dict d;
                for (int i = 0;
                     i < static_cast<int>(hq::EffectKind::kCount); ++i)
                    d[hq::effect_kind_name(static_cast<hq::EffectKind>(i))] =
                        i;
                return d;
            });
            m.def("combat_effect_post",
                  [kind_of](long kind, py::args objs) {
                      const hq::EffectKind k = kind_of(kind);
                      if (objs.size() > hq::EffectEntry::kMaxOperands)
                          throw py::value_error(
                              "combat effect: too many operands");
                      // A damage kind's frozen layout (effect_kind_operands):
                      // its operand count.
                      if (const char* layout = hq::effect_kind_operands(k);
                          layout != nullptr &&
                          std::strlen(layout) != objs.size())
                          throw py::value_error(
                              std::string("combat effect: ") +
                              hq::effect_kind_name(k) + " takes " +
                              std::to_string(std::strlen(layout)) +
                              " operands");
                      void* ptrs[hq::EffectEntry::kMaxOperands];
                      size_t n = 0;
                      for (py::handle o : objs)
                          ptrs[n++] = Py_NewRef(o.ptr());
                      hq::effect_queue().append_objects(
                          k, std::span<void* const>(ptrs, n));
                  },
                  py::arg("kind"),
                  "Append Python's entry: `kind` and its operand objects "
                  "(the queue holds a reference to each until delivery).");
            m.def("combat_effect_post_native",
                  [kind_of](long kind, py::args ops) {
                      const hq::EffectKind k = kind_of(kind);
                      if (ops.size() > hq::EffectEntry::kMaxOperands)
                          throw py::value_error(
                              "combat effect: too many operands");
                      hq::NativeOperand v[hq::EffectEntry::kMaxOperands];
                      size_t n = 0;
                      for (py::handle o : ops) {
                          if (PyFloat_Check(o.ptr()))
                              v[n++] = o.cast<double>();
                          else if (PyLong_Check(o.ptr()))
                              v[n++] = o.cast<std::int64_t>();
                          else  // an object the entry owns (a SPAWN's)
                              v[n++] = hq::OwnedObject{Py_NewRef(o.ptr())};
                      }
                      hq::effect_queue().append_native_span(
                          k, std::span<const hq::NativeOperand>(v, n));
                  },
                  py::arg("kind"),
                  "Test entry: append a KERNEL's entry -- ints are mirror "
                  "handles (-1 None), floats numbers -- as append_native "
                  "does.");
            m.def(
                "combat_apply_hit",
                [](std::int64_t ship, py::object source, std::int64_t source_h,
                   double damage, std::array<double, 3> point,
                   py::object normal, double r_hit, bool damage_hull,
                   bool bypass_shields, py::object shield_point,
                   bool shield_point_is_point, py::object tangent,
                   py::object decal_radius, double decal_dent,
                   bool single_impact, py::object shield_radius,
                   std::int64_t hit_weapon, std::int64_t weapon_hit_type,
                   bool has_instances, std::int64_t player, bool god_mode,
                   bool double_damage, bool npc_shields_off) {
                    namespace cb = dauntless::combat;
                    cb::HitInput in;
                    in.ship = ship;
                    in.source = source_h;
                    in.damage = damage;
                    in.point = {point[0], point[1], point[2]};
                    damage_point(normal, in.has_normal, in.normal);
                    in.r_hit = r_hit;
                    in.damage_hull = damage_hull;
                    in.bypass_shields = bypass_shields;
                    damage_point(shield_point, in.has_shield_point,
                                 in.shield_point);
                    in.shield_point_is_point = shield_point_is_point;
                    damage_point(tangent, in.has_tangent, in.tangent);
                    in.has_decal_radius = !decal_radius.is_none();
                    if (in.has_decal_radius)
                        in.decal_radius = decal_radius.cast<double>();
                    in.decal_dent = decal_dent;
                    in.single_impact = single_impact;
                    in.has_shield_radius = !shield_radius.is_none();
                    if (in.has_shield_radius)
                        in.shield_radius = shield_radius.cast<double>();
                    in.hit_weapon = hit_weapon;
                    in.weapon_hit_type = weapon_hit_type;
                    in.has_instances = has_instances;
                    cb::DamageContext ctx;
                    ctx.player = player;
                    ctx.god_mode = god_mode;
                    ctx.double_damage = double_damage;
                    ctx.npc_shields_off = npc_shields_off;
                    return damage_run(
                        [&](cb::DamageOut& out) {
                            cb::apply_hit(cb::mirror(), in, ctx, out);
                        },
                        source.ptr());
                },
                "Native damage: combat._apply_hit natively (damage.h), "
                "`source` the hit's source object (its handle `source_h`, "
                "-1 None, -2 unnamed), the points as hit_present_operands "
                "spells them, the weapon type as its two codes, the cheats "
                "and the player handle. Under an applier context "
                "(combat_set_applier). False: it fell back, nothing "
                "changed -- run the Python.");
            m.def(
                "combat_set_condition",
                [](std::int64_t sub, double value, std::int64_t killer_h,
                   std::int64_t ship, py::object killer) {
                    namespace cb = dauntless::combat;
                    return damage_run(
                        [&](cb::DamageOut& out) {
                            cb::set_condition(cb::mirror(), sub, value,
                                              killer_h, ship, out);
                        },
                        killer.ptr());
                },
                "Native damage: ShipSubsystem._set_condition(value, killer, "
                "ship) natively (`ship` -1 for None). False: fell back.");
            m.def(
                "combat_damage_system",
                [](std::int64_t ship, std::int64_t sub, double amount,
                   std::int64_t killer_h, py::object killer) {
                    namespace cb = dauntless::combat;
                    return damage_run(
                        [&](cb::DamageOut& out) {
                            cb::damage_system(cb::mirror(), ship, sub, amount,
                                              killer_h, out);
                        },
                        killer.ptr());
                },
                "Native damage: DamageableObject.DamageSystem(sub, amount, "
                "killer) natively. False: fell back.");
            m.def("combat_effect_codes", [] {
                py::dict d;
                for (const hq::EffectCode& c : hq::effect_codes())
                    d[c.name] = c.value;
                return d;
            }, "The damage kinds' code operands by name "
               "(combat_effect_queue.h; effect_queue.py's constants).");
            m.def("combat_effect_operands", [] {
                py::dict d;
                for (int i = 0;
                     i < static_cast<int>(hq::EffectKind::kCount); ++i) {
                    const auto k = static_cast<hq::EffectKind>(i);
                    if (const char* layout = hq::effect_kind_operands(k))
                        d[hq::effect_kind_name(k)] = layout;
                }
                return d;
            }, "The damage kinds' frozen operand layouts by kind name "
               "(effect_kind_operands; effect_queue.OPERANDS).");
            m.def("combat_effect_post_typed",
                  [kind_of](long kind, const std::string& types,
                            py::args ops) {
                      const hq::EffectKind k = kind_of(kind);
                      if (ops.size() > hq::EffectEntry::kMaxOperands ||
                          ops.size() != types.size())
                          throw py::value_error(
                              "combat effect: operands do not fit the types");
                      std::vector<hq::NativeOperand> v;
                      v.reserve(ops.size());
                      for (size_t i = 0; i < ops.size(); ++i) {
                          py::handle o = ops[i];
                          switch (types[i]) {
                          case 'R': v.push_back(o.cast<std::int64_t>()); break;
                          case 'H':
                              if (PyLong_Check(o.ptr()))
                                  v.push_back(o.cast<std::int64_t>());
                              else
                                  v.push_back(hq::OwnedObject{
                                      Py_NewRef(o.ptr())});
                              break;
                          case 'D': v.push_back(o.cast<double>()); break;
                          case 'I':
                              v.push_back(hq::EffectInt{o.cast<std::int64_t>()});
                              break;
                          case 'B':
                              v.push_back(hq::EffectBool{o.cast<bool>()});
                              break;
                          default:
                              throw py::value_error(
                                  "combat effect: unknown operand type");
                          }
                      }
                      std::vector<hq::EffectOperand> check(v.size());
                      for (size_t i = 0; i < v.size(); ++i) {
                          if (std::holds_alternative<std::int64_t>(v[i])) {
                              check[i].handle = std::get<std::int64_t>(v[i]);
                          } else if (std::holds_alternative<double>(v[i])) {
                              check[i].type = hq::EffectOperand::Type::Number;
                          } else if (std::holds_alternative<hq::EffectInt>(v[i])) {
                              check[i].type = hq::EffectOperand::Type::Int;
                          } else if (std::holds_alternative<hq::EffectBool>(v[i])) {
                              check[i].type = hq::EffectOperand::Type::Bool;
                          } else {
                              check[i].type = hq::EffectOperand::Type::Object;
                          }
                      }
                      if (!hq::effect_operands_match(k, check)) {
                          for (const hq::NativeOperand& op : v)
                              if (const auto* h = std::get_if<hq::OwnedObject>(&op))
                                  Py_DECREF(static_cast<PyObject*>(h->object));
                          throw py::value_error(
                              "combat effect: operands do not fit the "
                              "kind's layout");
                      }
                      hq::effect_queue().append_native_span(k, v);
                  },
                  py::arg("kind"), py::arg("types"),
                  "Test entry: append a KERNEL's entry typed by `types`, one "
                  "letter per operand as effect_kind_operands spells them "
                  "(R handle, H object or -1, D double, I int, B bool).");
            m.def("combat_effect_take", [] {
                std::vector<hq::EffectEntry> taken = hq::effect_queue().take();
                // Every object reference moves into the result, even if
                // building it fails part-way (steal each exactly once).
                std::vector<py::object> owned;
                for (const hq::EffectEntry& e : taken)
                    for (int i = 0; i < e.count; ++i)
                        if (e.ops[i].type == hq::EffectOperand::Type::Object)
                            owned.push_back(py::reinterpret_steal<py::object>(
                                static_cast<PyObject*>(e.ops[i].object)));
                py::list out;
                size_t next = 0;
                for (const hq::EffectEntry& e : taken) {
                    py::tuple ops(e.count);
                    for (int i = 0; i < e.count; ++i) {
                        const hq::EffectOperand& o = e.ops[i];
                        switch (o.type) {
                        case hq::EffectOperand::Type::Handle:
                            ops[i] = py::int_(o.handle);
                            break;
                        case hq::EffectOperand::Type::Number:
                            ops[i] = py::float_(o.number);
                            break;
                        case hq::EffectOperand::Type::Object:
                            ops[i] = owned[next++];
                            break;
                        case hq::EffectOperand::Type::Int:
                            ops[i] = py::int_(o.integer);
                            break;
                        case hq::EffectOperand::Type::Bool:
                            ops[i] = py::bool_(o.boolean);
                            break;
                        }
                    }
                    out.append(py::make_tuple(static_cast<int>(e.kind),
                                              e.native, ops));
                }
                return out;
            }, "Every queued entry, in emission order, as (kind, native, "
               "operands); the queue is empty after.");
            m.def("combat_effect_rebind",
                  [](std::int64_t handle, py::handle obj) {
                      return hq::effect_queue().rebind(
                          handle, obj.ptr(), [](void* p) -> void* {
                              return Py_NewRef(static_cast<PyObject*>(p));
                          });
                  },
                  py::arg("handle"), py::arg("obj"),
                  "native_combat._drop, before it unregisters `handle`: "
                  "every pending kernel operand naming it becomes `obj` "
                  "(the queue holds a reference each), so its entries are "
                  "still delivered. Returns how many were replaced.");
            m.def("combat_effect_clear",
                  [] { hq::effect_queue().clear(); },
                  "Drop every entry (native_combat.reset).");
            m.def("combat_effect_size",
                  [] { return hq::effect_queue().size(); });
        }

        // ── The K3 torpedo kernel (k3_projectiles.h) ─────────────────────
        // One resumable session over the torpedo table and the step scan:
        // update_all's decision steps. Records (handles -1 = None, xyz a
        // 3-tuple; torp = a torpedo table handle, `_k3_row`):
        //   (DONE, writes, expired, hits)
        //     writes  [(torp, age, last_seen_xyz | None, last_tvel_xyz |
        //               None, vel_xyz | None, mount | None), ...] in
        //               `_active` order; mount = (target, (x, y, z), sub)
        //               when the kernel attributed `_mount_key` (sub -1
        //               None)
        //     expired [torp, ...]: TTL expiries, then hits (expire order)
        //     hits    [(torp, ship, hit_xyz, tier, normal_xyz | None,
        //               bubble_xyz | None, hit_is_bubble), ...]
        //   (ASK, query, *args)              -> reply combat_k3_answer
        // combat_k3_begin's ctx: combat_k2_begin's keys (a begin without
        // "iids" keeps the previous K3 session's table; "python_ships" is
        // unused) plus "n_active": len(projectiles._active) (required) and
        // "scan_serial": combat_step_serial() when the driver took its scan
        // (optional; a different serial is reason "scan").
        // It returns None with a session open, or the reason the whole step
        // is Python's (no session).
        m.def("combat_k3_kinds", [] {
            py::dict d;
            for (int i = 0; i < static_cast<int>(cb::K3Kind::kCount); ++i)
                d[cb::k3_kind_name(static_cast<cb::K3Kind>(i))] = i;
            return d;
        });
        m.def("combat_k3_begin",
              [k2_apply_ctx](double dt, const std::array<double, 2>& clocks,
                             bool use_memo, const py::dict& ctx) -> py::object {
                  if (!ctx.contains("n_active"))
                      throw py::value_error(
                          "combat K3: ctx needs \"n_active\"");
                  cb::K2Context c;
                  c.hooks = cb::installed_trace_hooks();
                  k2_apply_ctx(c, ctx);
                  std::optional<std::uint64_t> serial;
                  if (ctx.contains("scan_serial"))
                      serial = ctx["scan_serial"].cast<std::uint64_t>();
                  const auto why = cb::k3_kernel().begin(
                      dt, cb::GuideClocks{clocks[1], clocks[0]}, use_memo,
                      std::move(c), ctx["n_active"].cast<std::int64_t>(),
                      !ctx.contains("iids"), serial);
                  if (!why) return py::none();
                  return py::str(cb::k3_why_name(*why));
              },
              py::arg("dt"), py::arg("clocks"), py::arg("use_memo"),
              py::arg("ctx"),
              "Begin update_all's walk. clocks = (now, drift_now): the "
              "weapons' game time (can_detect's occlusion clock) and "
              "native_combat.now() (the nebula drift clock), as K1/K2 pass "
              "them; use_memo step_memo.active(); ctx as above. Returns None "
              "(session open) or the whole-step-to-Python reason.");
        m.def("combat_k3_next", [vec] {
            // Compute with the GIL released (THE GIL RELEASE), as
            // combat_k2_next.
            cb::K3Record r = released_compute(ComputeSite::K3, [] {
                return cb::k3_kernel().next();
            });
            const int kind = static_cast<int>(r.kind);
            auto opt = [&vec](const std::optional<cb::Vec3>& v) -> py::object {
                return v ? py::object(vec(*v)) : py::object(py::none());
            };
            if (r.kind == cb::K3Kind::ASK) {
                py::list items;
                items.append(kind);
                items.append(cb::k3_query_name(r.query));
                for (const cb::K3Arg& a : r.args) {
                    items.append(std::visit(
                        [&vec](const auto& x) -> py::object {
                            using T = std::decay_t<decltype(x)>;
                            if constexpr (std::is_same_v<T, std::monostate>)
                                return py::none();
                            else if constexpr (std::is_same_v<T, cb::Vec3>)
                                return vec(x);
                            else
                                return py::cast(x);
                        },
                        a));
                }
                return py::tuple(items);
            }
            py::list writes, expired, hits;
            for (const cb::K3TorpWrite& w : r.writes)
                writes.append(py::make_tuple(
                    w.torp, w.age, opt(w.last_seen), opt(w.last_tvel),
                    opt(w.vel),
                    w.mount ? py::object(py::make_tuple(w.mount->target,
                                                        vec(w.mount->offset),
                                                        w.mount->sub))
                            : py::object(py::none())));
            for (const std::int64_t t : r.expired) expired.append(t);
            for (const cb::K3Hit& h : r.hits)
                hits.append(py::make_tuple(
                    h.torp, h.ship, vec(h.hit.point),
                    kK2Tiers[static_cast<int>(h.hit.tier)], opt(h.hit.normal),
                    opt(h.bubble), h.hit_is_bubble));
            return py::make_tuple(kind, writes, expired, hits);
        }, "The session's next record (see combat_k3_kinds).");
        m.def("combat_k3_answer",
              [](py::object v) {
                  cb::K3Answer a;
                  switch (cb::k3_kernel().awaiting()) {
                      case cb::K3Query::frame:
                          if (v.is_none()) {
                              a.key = -1;
                          } else {
                              const auto t = v.cast<py::tuple>();
                              if (t.size() != 4)
                                  throw py::value_error(
                                      "combat K3: frame answer is "
                                      "(key, ax, ay, az) or None");
                              a.key = t[0].cast<std::int64_t>();
                              a.point = {t[1].cast<double>(),
                                         t[2].cast<double>(),
                                         t[3].cast<double>()};
                          }
                          break;
                      case cb::K3Query::steer_point:
                          a.point = v.cast<std::array<double, 3>>();
                          break;
                      case cb::K3Query::shields_block:
                          a.flag = static_cast<bool>(py::bool_(v));
                          break;
                      case cb::K3Query::bubble:
                          if (v.is_none())
                              a.none = true;
                          else
                              a.point = v.cast<std::array<double, 3>>();
                          break;
                      case cb::K3Query::resolve_hit: {
                          const auto t = v.cast<py::tuple>();
                          if (t.size() != 3)
                              throw py::value_error(
                                  "combat K3: resolve_hit answer is "
                                  "((x, y, z), normal or None, tier)");
                          a.point = t[0].cast<std::array<double, 3>>();
                          if (!t[1].is_none())
                              a.normal = t[1].cast<std::array<double, 3>>();
                          const auto tier = t[2].cast<std::string>();
                          int k = 0;
                          while (k < 4 && tier != kK2Tiers[k]) ++k;
                          if (k == 4)
                              throw py::value_error("combat K3: unknown tier " +
                                                    tier);
                          a.tier = static_cast<cb::ResolvedHit::Tier>(k);
                          break;
                      }
                      default:  // guide (None), or no ASK: answer() raises
                          break;
                  }
                  cb::k3_kernel().answer(a);
              },
              py::arg("value"),
              "ASK's reply, shaped per query (k3_projectiles.h): frame "
              "(key, ax, ay, az) or None; steer_point (x, y, z); guide None; "
              "shields_block a bool; bubble (x, y, z) or None; resolve_hit "
              "((x, y, z), normal or None, tier).");
        m.def("combat_k3_end", [] { cb::k3_kernel().end(); },
              "End the session (it must have returned DONE).");
        m.def("combat_k3_apply_hits",
              [](std::size_t start, const py::dict& pulse,
                 const std::vector<std::size_t>& python) {
                  // THE HITS (k3_projectiles.h): the last DONE's hits from
                  // `start`, applied natively until one the kernel cannot
                  // apply; each one's writes applied by the session's
                  // applier and its entries queued, in order. Returns the
                  // index of the hit handed back (len(hits) when none).
                  cb::K2PulseCtx p = k2_pulse_ctx(pulse);
                  const std::unordered_set<std::size_t> py_hits(
                      python.begin(), python.end());
                  std::vector<cb::K3Applied> out;
                  // Its compute released and timed as K3's (k3.compute).
                  const std::size_t k = released_compute(
                      ComputeSite::K3Hits, [&] {
                          return cb::k3_kernel().apply_hits(start, p, py_hits,
                                                            out);
                      });
                  auto& applier = dauntless::host::write_applier();
                  if (!out.empty() && !applier.has_context())
                      throw std::logic_error(
                          "combat K3: applying hits needs the applier "
                          "context");
                  for (const cb::K3Applied& a : out) {
                      if (!a.out.writes.empty() &&
                          !applier.apply(a.out.writes, 0, a.out.writes.size()))
                          throw py::error_already_set();
                      damage_append_held(a.out.entries, a.source);
                  }
                  return k;
              },
              py::arg("start"), py::arg("pulse"), py::arg("python"),
              "Apply the last DONE's hits from `start` (THE HITS); the index "
              "of the first one handed back, or len(hits).");
        m.def("combat_k3_abandon", [] { cb::k3_kernel().abandon(); },
              "End the session whatever its state (exception path).");
        m.def("combat_k3_open", [] { return cb::k3_kernel().open(); });
        m.def("combat_k3_counts", [] {
            const auto& c = cb::k3_kernel().counts();
            py::dict d, why, asks, guide;
            d["k3_runs"] = c.runs;
            d["k3_python_steps"] = c.python_steps;
            d["k3_records"] = c.records;
            for (size_t i = 0; i < c.why.size(); ++i)
                why[cb::k3_why_name(static_cast<cb::K3Why>(i))] = c.why[i];
            for (size_t i = 0; i < c.queries.size(); ++i)
                asks[cb::k3_query_name(static_cast<cb::K3Query>(i))] =
                    c.queries[i];
            for (const auto& [k, n] : c.guide_why) guide[py::str(k)] = n;
            // steer_point ASKs by why, every reason (zeros included).
            py::dict steer;
            for (size_t i = 0; i < c.steer_why.size(); ++i)
                steer[cb::steer_why_name(static_cast<cb::SteerWhy>(i))] =
                    c.steer_why[i];
            d["k3_python_reasons"] = why;
            d["k3_asks"] = asks;
            d["k3_guide_reasons"] = guide;
            d["k3_steer_reasons"] = steer;
            d["k3_posed_steers"] = c.posed_steers;
            d["k3_native_attributions"] = c.native_attributions;
            // THE HITS: hits applied natively, and those the kernel handed
            // back, by why (the driver adds its own).
            d["k3_native_hits"] = c.native_hits;
            py::dict hit_why;
            std::int64_t hit_python = 0;
            for (size_t i = 0; i < c.hit_why.size(); ++i) {
                hit_why[cb::k2_pulse_why_name(
                    static_cast<cb::K2PulseWhy>(i))] = c.hit_why[i];
                hit_python += c.hit_why[i];
            }
            d["k3_hit_python_reasons"] = hit_why;
            d["k3_hit_python"] = hit_python;
            return d;
        });
        m.def("combat_k3_reset_counts",
              [] { cb::k3_kernel().reset_counts(); });

        // ── The per-step scan and frame table (K3/K4, step_scan.h) ──────
        m.def("combat_step_scan",
              [](py::handle ships, long long obj_kind, int kind_shift,
                 py::handle seen, py::handle patches) {
                  PyObject* r = step_scan_ships(ships.ptr(), obj_kind,
                                                kind_shift, seen.ptr(),
                                                patches.ptr());
                  if (r == nullptr) throw py::error_already_set();
                  return py::reinterpret_steal<py::tuple>(r);
              },
              py::arg("ships"), py::arg("obj_kind"), py::arg("kind_shift"),
              py::arg("seen"), py::arg("patches"),
              "(representable, reason or None, [set handle, ...]): scan the "
              "step's ships_list into the native step state (step_scan.h).");
        m.def("combat_step_frames",
              [](const std::vector<std::tuple<std::int64_t, std::int64_t,
                                              double, double, double>>& t) {
                  auto& f = cb::step_scan().frames;
                  f.clear();
                  f.reserve(t.size());
                  for (const auto& [set, key, ax, ay, az] : t)
                      f.push_back({set, key, {ax, ay, az}});
              },
              py::arg("table"),
              "This step's frame table: [(set_handle, key_id, ax, ay, az), "
              "...], frames.frame_of(set) per set (key_id -1: None).");
        m.def("combat_step_serial", [] { return cb::step_scan().serial; },
              "The current step scan's serial (bumped by every scan and "
              "reset): K3's begin compares it with ctx[\"scan_serial\"].");
        m.def("combat_step_reset", [] { cb::step_scan().begin(); },
              "Empty the step state: nothing representable this step.");
        m.def("combat_step_dump", [] {
            const auto& s = cb::step_scan();
            py::list frames;
            for (const auto& f : s.frames)
                frames.append(py::make_tuple(f.set, f.key, f.anchor[0],
                                             f.anchor[1], f.anchor[2]));
            py::dict d;
            d["serial"] = s.serial;
            d["representable"] = s.representable;
            d["why"] = cb::scan_why_name(s.why);
            d["ships"] = s.ships;
            d["sets"] = s.sets;
            d["frames"] = frames;
            return d;
        });
        m.def("combat_k4_eligible",
              [](std::int64_t player, std::int64_t max_count, double prox_w,
                 double size_w) -> py::object {
                  auto r = [&] {
                      const ComputeSpan span(4);
                      return cb::k4_eligible(cb::mirror(), cb::step_scan(),
                                             player, max_count, prox_w,
                                             size_w);
                  }();
                  auto& c = cb::k4_counts();
                  if (!r.ok) {
                      ++c.why[static_cast<size_t>(r.why)];
                      return py::none();
                  }
                  ++c.runs;
                  PyObject* l = PyList_New(
                      static_cast<Py_ssize_t>(r.indices.size()));
                  if (l == nullptr) throw py::error_already_set();
                  for (size_t i = 0; i < r.indices.size(); ++i) {
                      PyObject* v = PyLong_FromLongLong(r.indices[i]);
                      if (v == nullptr) {
                          Py_DECREF(l);
                          throw py::error_already_set();
                      }
                      PyList_SET_ITEM(l, static_cast<Py_ssize_t>(i), v);
                  }
                  return py::reinterpret_steal<py::object>(l);
              },
              py::arg("player_handle"), py::arg("max_count"),
              py::arg("prox_w"), py::arg("size_w"),
              "select_eligible over the step scan: indices into ships_list "
              "(after the player), or None = run select_eligible in Python.");
        m.def("combat_compute_take",
              [](int kernel) {
                  if (kernel < 0 || kernel >= kComputeKernels)
                      throw py::value_error(
                          "combat_compute_take: kernel 0-5 (K0-K4, M)");
                  ComputeTimer& t =
                      compute_timers()[static_cast<size_t>(kernel)];
                  const ComputeTimer taken = t;
                  t = ComputeTimer{};
                  return py::make_tuple(static_cast<double>(taken.ns) / 1e6,
                                        taken.calls);
              },
              py::arg("kernel"),
              "(ms, calls): kernel K<kernel>'s compute-only time since the "
              "last take, and its compute calls, then zeroed (the compute "
              "timers, kernels off the lock Task 1).");
        // THE GIL PROBE (test only; see GilProbe).
        m.def("combat_gil_probe_arm",
              [](bool armed, int holds, double hold_ms, int throw_site) {
                  if (throw_site < -1 || throw_site >= kComputeSites)
                      throw py::value_error(
                          "combat_gil_probe_arm: throw_site -1 or 0-5");
                  GilProbe& p = gil_probe();
                  p.holds = holds;
                  p.hold_ns = static_cast<std::int64_t>(hold_ms * 1e6);
                  p.throw_site = throw_site;
                  p.armed.store(armed);
              },
              py::arg("armed"), py::arg("holds") = 0,
              py::arg("hold_ms") = 0.0, py::arg("throw_site") = -1,
              "Test only. Arm (or disarm) the GIL probe: count each released "
              "compute call per site (K0, K1, K2, K3 next(), K3 apply_hits) "
              "and whether the GIL was released in it; hold the next "
              "`holds` calls until another thread steps (up to hold_ms); "
              "throw from inside the next call at `throw_site`.");
        m.def("combat_gil_probe_hold",
              [](int holds, double hold_ms) {
                  GilProbe& p = gil_probe();
                  p.holds = holds;
                  p.hold_ns = static_cast<std::int64_t>(hold_ms * 1e6);
              },
              py::arg("holds"), py::arg("hold_ms"),
              "Test only. Hold the next `holds` released compute calls until "
              "another thread steps (combat_gil_probe_step), up to hold_ms.");
        m.def("combat_gil_probe_step",
              [] { gil_probe().steps.fetch_add(1); },
              "Test only. A churning thread's progress mark (it holds the "
              "GIL as it calls this).");
        m.def("combat_gil_probe_check", [] { return PyGILState_Check(); },
              "Test only. PyGILState_Check() here: 1 (a binding holds the "
              "GIL), the probe's negative control.");
        m.def("combat_gil_probe_take",
              [] {
                  GilProbe& p = gil_probe();
                  auto list = [](const auto& a) {
                      return std::vector<std::int64_t>(a.begin(), a.end());
                  };
                  py::dict d;
                  d["calls"] = list(p.calls);
                  d["released"] = list(p.released);
                  d["ran"] = list(p.ran);
                  d["during"] = list(p.during);
                  d["thrown"] = p.thrown;
                  p.calls = {};
                  p.released = {};
                  p.ran = {};
                  p.during = {};
                  p.thrown = 0;
                  return d;
              },
              "Test only. The probe's counters per site (calls, released, "
              "ran, during) and throws, then zeroed.");
        m.def("combat_k4_counts", [] {
            const auto& c = cb::k4_counts();
            py::dict why;
            for (size_t i = 0; i < c.why.size(); ++i)
                why[cb::k4_why_name(static_cast<cb::K4Why>(i))] = c.why[i];
            py::dict d;
            d["k4_runs"] = c.runs;
            d["k4_python_reasons"] = why;
            return d;
        });
        m.def("combat_k4_reset_counts",
              [] { cb::k4_counts() = cb::K4Counts{}; });
    }
}
