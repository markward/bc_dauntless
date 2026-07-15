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

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <audio/python_binding.h>

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/bone_palette.h>
#include <renderer/pose_sampler.h>
#include <renderer/animation_update.h>
#include <renderer/frame.h>
#include <renderer/backdrop_pass.h>
#include <renderer/sun_pass.h>
#include <renderer/dust_pass.h>
#include <renderer/nebula_pass.h>
#include <renderer/nebula_volumetric_pass.h>
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
#include <renderer/target_reticle_pass.h>
#include <renderer/letterbox_pass.h>
#include <renderer/bridge_pass.h>
#include <renderer/viewscreen_static_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/bloom_pass.h>
#include <renderer/resolve_pass.h>
#include <renderer/ldr_target.h>
#include <renderer/smaa_pass.h>
#include <renderer/filmic_pass.h>
#include <renderer/motion_blur_pass.h>
#include <renderer/aabb.h>
#include <renderer/shadow_light.h>
#include <renderer/shadow_map_target.h>
#include <renderer/asset_path.h>
#include <renderer/ray_trace.h>
#include <renderer/glow_region.h>
#include <renderer/node_anim.h>
#include <renderer/bridge_node_anim_store.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <assets/cache.h>
#include <assets/model_compose.h>
#include <assets/texture.h>
#include <nif/file.h>
#include <nif/scene_camera.h>

#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/matrix_inverse.hpp>
#include <array>
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
// Forward-declared here (before the anonymous namespace) so render_space()
// inside the anonymous namespace can read the always-on hull-breach gate.
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
namespace dauntless_warp_vfx {
    bool enabled(); void set_enabled(bool);   // defined in frame.cc
    float streak_intensity(); float flash_intensity();
    glm::vec3 travel_dir();
    void set_streak(float); void set_flash(float); void set_travel(glm::vec3);
}
namespace dauntless_volumetric_nebulae {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
namespace dauntless_nebula_lightning {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}

namespace {

std::unique_ptr<renderer::Window> g_window;
scenegraph::World g_world;
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
std::unique_ptr<renderer::SunPass> g_sun_pass;
std::unique_ptr<renderer::DustPass> g_dust_pass;
std::vector<renderer::NebulaVolume> g_nebulae;
std::vector<renderer::NebulaWakePoint> g_nebula_wake;   // world pos, faded strength, pod size
std::unique_ptr<renderer::NebulaPass> g_nebula_pass;
std::unique_ptr<renderer::NebulaVolumetricPass> g_nebula_volumetric_pass;
std::vector<renderer::GodrayFlash> g_nebula_godrays;
std::unique_ptr<renderer::NebulaGodrayPass> g_nebula_godray_pass;
std::unique_ptr<renderer::ShieldPass> g_shield_pass;
std::vector<renderer::LensFlareDescriptor> g_lens_flares;
std::unique_ptr<renderer::LensFlarePass>   g_lens_flare_pass;
std::vector<renderer::TorpedoDescriptor>   g_torpedoes;
std::unique_ptr<renderer::TorpedoPass>     g_torpedo_pass;
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
std::vector<renderer::SubsystemPin>          g_subsystem_pins;
std::unique_ptr<renderer::SubsystemPinPass>  g_subsystem_pin_pass;
// Developer debug overlay (Ship Property Viewer "Glow Regions" toggle):
// world-space wireframe cylinders set each frame from Python. Empty list →
// zero GL work; only rendered in viewer_mode.
std::vector<renderer::DebugCylinder>         g_debug_cylinders;
std::unique_ptr<renderer::DebugVolumePass>   g_debug_volume_pass;
renderer::TargetReticle                      g_target_reticle;
std::unique_ptr<renderer::TargetReticlePass> g_target_reticle_pass;
// "Hologram-only" frame mode: when on (set by the Ship Property Viewer while
// open), frame() clears to g_hologram_bg and skips both the space scene and the
// bridge pass, drawing only the hologram + subsystem pins.
bool      g_hologram_only_mode = false;
glm::vec3 g_hologram_bg{0.0f, 0.0f, 0.0f};
std::unique_ptr<renderer::BridgePass>      g_bridge_pass;
std::unique_ptr<renderer::HdrTarget>       g_hdr_target;
std::unique_ptr<renderer::HdrTarget>       g_viewscreen_hdr;
std::unique_ptr<renderer::BloomPass>       g_bloom_pass;
std::unique_ptr<renderer::LensFlareHdrPass> g_lens_flare_hdr_pass;  // image-based screen-space flare
std::unique_ptr<renderer::ResolvePass>     g_resolve_pass;
std::unique_ptr<renderer::LdrTarget>       g_ldr_target;
std::unique_ptr<renderer::LdrTarget>       g_ldr_target2;   // SMAA→filmic intermediate
std::unique_ptr<renderer::FilmicPass>      g_filmic_pass;
std::unique_ptr<renderer::SmaaPass>        g_smaa_pass;
std::unique_ptr<renderer::MotionBlurPass>  g_motion_blur_pass;
glm::mat4 g_prev_viewproj = glm::mat4(1.0f);   // previous exterior frame proj*view
bool      g_have_prev_viewproj = false;         // false until first exterior frame
// Sun shadow map: depth-only caster FBO rendered once per frame from the sun's
// POV (see frame()), shared by the main view and the viewscreen RTT. Owned here
// so its GL handles are released in shutdown() while the context is current.
std::unique_ptr<renderer::ShadowMapTarget> g_shadow_target;
bool g_smaa_enabled = true;   // post-process SMAA 1x; default on. Set by smaa_set_enabled.
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

scenegraph::ModelHandle load_model_impl(
    const std::string& nif_path,
    const py::object& texture_search_path,
    const py::object& texture_replacements) {
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

    // Dedupe by (nif_path, replacements): callers that load the same NIF +
    // registry for multiple ships get the same handle and the underlying
    // assets::AssetCache::load isn't even called a second time. Distinct
    // registries on the same NIF correctly produce distinct handles.
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
        g_cache = std::make_unique<assets::AssetCache>(std::move(cfg));
    }
    auto handle = g_cache->load(nif_path, search_paths, replacements);
    LoadedModel lm;
    lm.nif_path         = std::move(canonical);
    lm.handle           = std::move(handle);
    lm.replacements_key = std::move(rep_key);
    g_loaded_models.push_back(std::move(lm));
    return static_cast<scenegraph::ModelHandle>(g_loaded_models.size());
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
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_ambient_scale = 1.0f;
    g_bridge_pass_enabled = false;
    g_backdrops.clear();
    g_sky_dirty = true;
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_suns.clear();
    g_dust_planets.clear();
    g_sun_pass = std::make_unique<renderer::SunPass>();
    g_dust_pass = std::make_unique<renderer::DustPass>();
    g_nebula_pass = std::make_unique<renderer::NebulaPass>();
    g_nebula_volumetric_pass = std::make_unique<renderer::NebulaVolumetricPass>();
    g_nebula_godray_pass = std::make_unique<renderer::NebulaGodrayPass>();
    g_nebula_godrays.clear();
    g_nebulae.clear();
    g_nebula_wake.clear();
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
    // The breach pass lazily loads its own animated interior texture
    // (game/data/Damage1..4.tga) on first draw — no host wiring needed.
    g_subsystem_pin_pass  = std::make_unique<renderer::SubsystemPinPass>();
    g_debug_volume_pass   = std::make_unique<renderer::DebugVolumePass>();
    g_target_reticle_pass = std::make_unique<renderer::TargetReticlePass>();
    g_bridge_pass         = std::make_unique<renderer::BridgePass>();
    g_viewscreen_static_pass = std::make_unique<renderer::ViewscreenStaticPass>();
    g_hdr_target      = std::make_unique<renderer::HdrTarget>();
    g_viewscreen_hdr  = std::make_unique<renderer::HdrTarget>();
    g_bloom_pass   = std::make_unique<renderer::BloomPass>();
    g_lens_flare_hdr_pass = std::make_unique<renderer::LensFlareHdrPass>();
    g_resolve_pass = std::make_unique<renderer::ResolvePass>();
    g_ldr_target   = std::make_unique<renderer::LdrTarget>();
    g_ldr_target2  = std::make_unique<renderer::LdrTarget>();
    g_filmic_pass  = std::make_unique<renderer::FilmicPass>();
    g_smaa_pass    = std::make_unique<renderer::SmaaPass>();
    g_motion_blur_pass = std::make_unique<renderer::MotionBlurPass>();
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
    g_loaded_models.clear();
    // Handle-recycling hazard: see the matching call in init(). Pure CPU
    // state (no GL), safe regardless of context currency.
    renderer::reset_model_radius_cache();
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_backdrops.clear();
    g_sky_dirty = true;
    g_backdrop_pass.reset();  // releases sphere + texture caches while the
                              // GL context is still alive.
    g_suns.clear();
    g_dust_planets.clear();
    g_sun_pass.reset();
    g_dust_pass.reset();
    g_nebula_pass.reset();
    g_nebula_volumetric_pass.reset();
    g_nebula_godray_pass.reset();
    g_nebula_godrays.clear();
    g_nebulae.clear();
    g_nebula_wake.clear();
    g_shield_pass.reset();
    g_lens_flares.clear();
    g_lens_flare_pass.reset();
    g_torpedoes.clear();
    g_torpedo_pass.reset();
    g_shockwaves.clear();
    g_shockwave_pass.reset();
    g_hit_vfx.clear();
    g_hit_vfx_pass.reset();
    g_hull_discharges.clear();
    g_hull_discharge_pass.reset();
    g_nebula_wake_pass.reset();
    g_particle_emitters.clear();
    g_particle_pass.reset();
    g_phaser_beams.clear();
    g_tractor_beams.clear();
    g_spv_overlay_beams.clear();
    g_phaser_pass.reset();
    g_subsystem_pins.clear();
    g_hologram_ship = renderer::HologramShip{};
    g_hologram_only_mode = false;
    g_hologram_pass.reset();
    g_cloak_ships.clear();
    g_cloak_pass.reset();
    g_breach_pass.reset();   // releases the sphere mesh + fill textures while the GL context lives
    g_carve_cache.reset();   // releases the carved-fill 3D textures (GL alive)
    g_subsystem_pin_pass.reset();
    g_debug_cylinders.clear();
    g_debug_volume_pass.reset();
    g_target_reticle = renderer::TargetReticle{};
    g_target_reticle_pass.reset();
    g_bridge_pass.reset();
    g_viewscreen_static_pass.reset();
    g_bloom_pass.reset();
    g_lens_flare_hdr_pass.reset();
    g_motion_blur_pass.reset();
    g_have_prev_viewproj = false;
    g_smaa_pass.reset();
    g_filmic_pass.reset();
    g_ldr_target2.reset();
    g_ldr_target.reset();
    g_resolve_pass.reset();
    g_hdr_target.reset();
    g_viewscreen_hdr.reset();
    g_shadow_target.reset();
    g_window.reset();
    g_prev_key_state.clear();
    g_prev_mouse_state.clear();
    // Mirror init()'s lighting reset for symmetry and defense-in-depth:
    // any future code path that reads g_lighting between shutdown() and a
    // subsequent init() will see the documented default, not stale state
    // from the previous session.
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_ambient_scale = 1.0f;
    g_bridge_pass_enabled = false;
    g_viewscreen_enabled = false;
    // g_covered (native/src/renderer/letterbox_pass.cc) is a TU-static, not
    // owned by this file, but it is re-established from Python state every
    // frame by _pump_letterbox before r.frame() runs (see the comment on
    // g_covered itself) -- zero it defensively anyway for symmetry with the
    // other flag resets above, in case a future caller ever reads
    // renderer::letterbox::covered() between shutdown() and the next init().
    renderer::letterbox::set_covered(0.0f);
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

void frame() {
    if (!g_window || !g_pipeline || !g_submitter) {
        throw std::runtime_error("_dauntless_host: frame called before init");
    }
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

    g_world.propagate();
    // SP2: rebuild each animated instance's bone palette for this frame BEFORE
    // anything consumes it (the space skinned draw and the bridge pass). Shares
    // the `now` wall clock with draw_model / flip controllers.
    renderer::update_animations(g_world, lookup, now);
    update_bridge_node_anims(now);

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
            g_backdrop_pass->bake(g_backdrops, *g_pipeline,
                                  static_cast<float>(now));
            g_sky_dirty = false;
        }
        sky_use_cubemap = g_backdrop_pass->has_cubemap();  // false if alloc failed
    }
    // Renders the space scene from `cam` into `target` (bound by the caller),
    // whose color/depth textures and viewport dims (vw, vh) drive the
    // framebuffer-coupled passes (volumetric nebula, godrays, lens flares).
    // The viewscreen RTT now renders every pass the main view does — dust
    // (camera-anchored smear, keyed off for_viewscreen so the cockpit isn't
    // smeared except during warp streaking), nebulae, godrays, lens flares,
    // hull discharges, shockwaves, particles, and cloak refraction — so the
    // bridge viewscreen matches the exterior view.
    auto render_space = [&](const scenegraph::Camera& cam, bool for_viewscreen,
                            renderer::HdrTarget& target, int vw, int vh) {
        if (sky_use_cubemap)
            g_backdrop_pass->render_cubemap(cam, *g_pipeline);
        else
            g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                                    dauntless_procedural_sky::enabled(),
                                    static_cast<float>(now));
        g_sun_pass->render(g_suns, cam, *g_pipeline, now);
        // Filmic ambient dim: -20% when the toggle is on, 1.0 when off. The
        // viewscreen now matches the exterior view (no separate dim rule).
        const float ambient_scale = dauntless_filmic::ambient_scale();
        g_submitter->submit_opaque_in_pass(
            g_world, cam, *g_pipeline, lookup, g_lighting,
            scenegraph::Pass::Space, g_decal_game_time, g_carve_cache.get(),
            ambient_scale);
        // Breach scoop pass: for each active carve sphere, draws the front-
        // face-culled sphere inner wall masked by the original hull fill
        // (triplanar Damage.tga). Runs right after the opaque hull
        // (depth-test/write on) so the scoop shows only through clip holes.
        // Gated on dauntless_hull_damage::enabled() inside the pass (no-op when off).
        if (g_breach_pass && g_carve_cache)
            g_breach_pass->render(g_world, cam, *g_pipeline, lookup,
                                  *g_carve_cache, g_decal_game_time);
        if (g_shield_pass) g_shield_pass->submit(g_world, cam, *g_pipeline, now, lookup);
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
        if (g_dust_pass && (!for_viewscreen || warp_streaking))
            g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets,
                                dauntless_warp_vfx::streak_intensity(),
                                dauntless_warp_vfx::travel_dir());
        if (!g_nebulae.empty()) {
            if (dauntless_volumetric_nebulae::enabled() && g_nebula_volumetric_pass) {
                // VOLUMETRIC (Modern VFX): raymarch the fbm field, blended
                // into the HDR target, occluded by the scene depth texture.
                const glm::mat4 inv_vp =
                    glm::inverse(cam.proj_matrix() * cam.view_matrix());
                g_nebula_volumetric_pass->render(
                    cam, *g_pipeline, g_nebulae, g_lighting,
                    target.color_texture(), target.depth_texture(),
                    inv_vp, cam.eye, static_cast<float>(now));
            } else if (g_nebula_pass) {
                g_nebula_pass->render(cam, *g_pipeline, g_nebulae);  // V1 faithful
            }
            // Decoupled additive wake trail (Plan B #1) — drawn over the cloud
            // so the soft-glow billboards add on top of the nebula density.
            if (dauntless_volumetric_nebulae::enabled() && g_nebula_wake_pass
                    && !g_nebula_wake.empty())
                g_nebula_wake_pass->render(cam, *g_pipeline, g_nebula_wake,
                                           static_cast<float>(now));
        }
        if (dauntless_nebula_lightning::enabled()
                && g_nebula_godray_pass && !g_nebula_godrays.empty())
            g_nebula_godray_pass->render(cam, *g_pipeline, g_nebula_godrays,
                                         target.color_texture());
        if (g_lens_flare_pass)
            g_lens_flare_pass->render(g_lens_flares, cam, *g_pipeline, vw, vh, now);
        if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    cam, *g_pipeline);
        if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, cam, *g_pipeline);
        if (g_phaser_pass)  g_phaser_pass ->render(g_tractor_beams, cam, *g_pipeline);
        if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, cam, *g_pipeline);
        if (dauntless_nebula_lightning::enabled()
                && g_hull_discharge_pass && !g_hull_discharges.empty())
            g_hull_discharge_pass->render(cam, *g_pipeline, g_hull_discharges);
        if (g_shockwave_pass)
            g_shockwave_pass->render(cam, g_shockwaves, *g_pipeline);
        // Venting jets: build per-frame descriptors from active breach events
        // and append to a combined emitter list for the particle pass.
        // Never mutate g_particle_emitters in place (Python-owned).
        if (g_particle_pass) {
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
                            inst.breach_events, inst.id, g_decal_game_time);
                        all_emitters.insert(all_emitters.end(),
                                            vent.begin(), vent.end());
                        auto debris = renderer::build_debris_descriptors(
                            inst.breach_events, inst.id, g_decal_game_time);
                        all_emitters.insert(all_emitters.end(),
                                            debris.begin(), debris.end());
                    });
            }
            g_particle_pass->render(all_emitters, g_world, cam, *g_pipeline);
        }
        // Cloak refraction: bend + chromatically disperse the scene behind each
        // cloaking hull. Runs last (the target holds the fully lit scene and is
        // still bound). Now shared by both the main view and the viewscreen RTT.
        if (g_cloak_pass && !g_cloak_ships.empty())
            g_cloak_pass->render(g_cloak_ships, g_world, cam, *g_pipeline, lookup,
                                 static_cast<float>(now), g_lighting, ambient_scale);
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
        g_viewscreen_hdr->resize(kViewscreenRttW, kViewscreenRttH);
        g_viewscreen_hdr->bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
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
            render_space(scam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        kViewscreenRttW, kViewscreenRttH);
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            render_space(vcam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                        kViewscreenRttW, kViewscreenRttH);
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
        g_bridge_pass->set_viewscreen_texture(0);   // off -> step-5b blank panel
    }

    // ── Main HDR target ────────────────────────────────────────────────────
    g_hdr_target->resize(fw, fh);
    g_hdr_target->bind();   // sets viewport to fw x fh
    if (viewer_mode) {
        glClearColor(g_hologram_bg.r, g_hologram_bg.g, g_hologram_bg.b, 1.0f);
    } else {
        glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    }
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    // Space scene goes to the main view only outside bridge view (in bridge
    // view it went to the RTT above, or nowhere when the screen is off — the
    // bridge pass fills the screen either way). This also retires the old
    // "wasted space render in bridge mode".
    if (!viewer_mode && !bridge_active) {
        render_space(g_camera, /*for_viewscreen=*/false, *g_hdr_target, fw, fh);
    }

    if (g_hologram_pass && g_hologram_ship.active)
        g_hologram_pass->render(g_hologram_ship, g_world, g_camera, *g_pipeline, lookup);
    if (viewer_mode && g_phaser_pass && !g_spv_overlay_beams.empty())
        g_phaser_pass->render(g_spv_overlay_beams, g_camera, *g_pipeline,
                              /*depth_test=*/false);
    if (viewer_mode && g_debug_volume_pass && !g_debug_cylinders.empty())
        g_debug_volume_pass->render(g_debug_cylinders, g_camera);
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
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
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

    // Compute bloom from the HDR target while the HDR FBO is still in use.
    // bloom_tex is set to the HDR color texture as a harmless dummy when HDR is
    // off — the resolve's OFF branch never samples u_bloom.
    std::uint32_t bloom_tex = g_hdr_target->color_texture();
    if (dauntless_hdr::enabled()) {
        bloom_tex = g_bloom_pass->render(g_hdr_target->color_texture(), fw, fh);
    }

    // Resolve the HDR target, then run any active optional LDR post passes
    // (SMAA -> motion blur -> filmic) as a 2-target ping-pong, the last writing
    // the backbuffer. With none active, resolve writes straight to the
    // backbuffer (unchanged, zero-added-cost path). CEF composite + swap run
    // after this so the overlay composites on top of the resolved 3D scene.
    const bool aa_on    = g_smaa_enabled;
    const bool exterior = !viewer_mode && !bridge_active;
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
    std::uint32_t lens_flare_tex = g_hdr_target->color_texture();  // dummy when off
    float lens_flare_strength = 0.0f;
    if (dauntless_hdr::enabled() && dauntless_hdr_lens_flare::enabled()
            && exterior && g_lens_flare_hdr_pass) {
        lens_flare_tex = g_lens_flare_hdr_pass->render(bloom_tex, fw, fh);
        lens_flare_strength = 0.15f;   // additive flare intensity (locked in)
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
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex, lens_flare_tex);

    if (any_post) {
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
            const glm::mat4 prev     = g_prev_viewproj;
            passes.emplace_back([inv_proj, cam_rot, cam_pos, prev, fw, fh]
                                (std::uint32_t s, std::uint32_t d) {
                g_motion_blur_pass->draw(s, d, fw, fh, inv_proj, cam_rot,
                                         cam_pos, prev);
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
    if (!viewer_mode) renderer::letterbox::draw(fw, fh);

    // Cache this exterior frame's view-projection for next frame's motion blur.
    // Non-exterior frames invalidate it so re-entering the exterior view skips
    // one frame of blur instead of smearing across the transition.
    if (exterior) {
        g_prev_viewproj = g_camera.proj_matrix() * g_camera.view_matrix();
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
    g_window->poll_events();

#ifdef DAUNTLESS_ENABLE_CEF
    // Pump CEF's message loop (may deliver OnPaint synchronously into
    // g_client), then composite the latest bitmap over the 3D scene with
    // premultiplied-alpha blend. Runs AFTER poll_events to avoid stealing
    // keyboard events from GLFW (see comment above poll_events).
    dauntless::ui_cef::pump();
    dauntless::ui_cef::composite();
#endif

    g_window->swap_buffers();
}

}  // namespace

// Toggle for the opaque-pass specular term.
// Defined in frame.cc (librenderer), forward-declared here so
// host_bindings can expose it to Python without a circular dependency.
namespace dauntless_specular {
    void set_enabled(bool v);  // defined in frame.cc
}
// Toggle for the opaque-pass Fresnel rim term. Defined in frame.cc.
namespace dauntless_rim {
    void set_enabled(bool v);  // defined in frame.cc
}
// dauntless_shadows is forward-declared earlier (before frame()).
// Toggle for the opaque-pass persistent damage decals. Defined in frame.cc.
namespace dauntless_decals {
    void set_enabled(bool v);  // defined in frame.cc
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
    m.def("should_close", &should_close);
    m.def("frame", &frame);
    m.def("load_model", &load_model_impl,
          py::arg("nif_path"), py::arg("texture_search_path"),
          py::arg("texture_replacements") = py::none());
    m.def("parse_set_camera", &parse_set_camera_impl,
          "Extract the embedded camera (frustum + world transform) from a set "
          "NIF, or None. Parse-only; no GL context required.");

    py::class_<scenegraph::InstanceId>(m, "InstanceId")
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
              }
          },
          py::arg("id"));
    m.def("set_world_transform",
          [](scenegraph::InstanceId id, const std::vector<float>& m) {
              if (m.size() != 16) {
                  throw std::runtime_error("set_world_transform: need 16 floats");
              }
              glm::mat4 mat;
              // Row-major from Python; glm is column-major. Transpose on input.
              for (int r = 0; r < 4; ++r)
                  for (int c = 0; c < 4; ++c)
                      mat[c][r] = m[r * 4 + c];
              g_world.set_world_transform(id, mat);
          },
          py::arg("id"), py::arg("mat4"));
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
    m.def("set_instance_animation",
          [](scenegraph::InstanceId id, int clip_index, bool loop,
             bool sample_at_start) {
              auto* in = g_world.get(id);
              if (!in) return;
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = loop;
              st.sample_at_start = sample_at_start;
              // Same wall clock frame() threads into update_animations /
              // draw_model / flip controllers, so animation t=0 lines up with
              // the per-frame sample. (frame() reads glfwGetTime() into `now`.)
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("sample_at_start") = false,
          "SP2: play model.animations[clip_index] on this instance. loop=false "
          "(default) plays once and holds the last frame; the renderer rebuilds "
          "the bone palette each frame until it settles.");
    m.def("set_instance_rest_pose",
          [](scenegraph::InstanceId id, int clip_index, bool at_start) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.sample_at_start = at_start;
              st.sample_at_end = !at_start;
              st.start_wall_time = glfwGetTime();
              g_world.set_rest_pose(id, st);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("at_start") = false,
          "Freeze an officer at the static placement pose: at_start=true holds "
          "the clip's first frame (move-from-station clips), false holds the "
          "last frame (stand/seated clips). No play-through.");
    m.def("restore_rest_pose",
          [](scenegraph::InstanceId id) { g_world.restore_rest_pose(id); },
          py::arg("iid"),
          "Snap the instance back to its stored rest pose (AT_DEFAULT).");
    m.def("play_instance_idle",
          [](scenegraph::InstanceId id, int clip_index) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = true;
              st.layer_over_rest = true;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Loop a layered idle (e.g. breathing) over the instance's rest pose: "
          "the idle clip drives the body, the placement supplies the root + any "
          "bones the idle doesn't track. Loops until a gesture or restore "
          "replaces it.");
    m.def("play_instance_gesture",
          [](scenegraph::InstanceId id, int clip_index) {
              // BC-faithful dead-clip gate: stbc.exe binds clip channels to
              // nodes by exact strcmp and silently idles unmatched nodes, so
              // a clip driving ZERO bones of this skeleton shows nothing in
              // BC (e.g. the "Kiska …"-rigged Console_Look_*.NIF gestures on
              // the "Bip01 …" officer rigs). Setting it as the animation here
              // would instead freeze the officer at the layered base pose for
              // the clip's duration — so leave the current idle running.
              scenegraph::Instance* in = g_world.get(id);
              if (in) {
                  const assets::Model* m = resolve_model(in->model_handle);
                  if (m && clip_index >= 0 &&
                      clip_index < static_cast<int>(m->animations.size()) &&
                      !renderer::clip_drives_skeleton(
                          m->animations[clip_index], m->skeleton))
                      return;
              }
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.layer_over_rest = true;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a transient gesture/reaction clip LAYERED over the instance's "
          "rest pose: gesture-tracked bones override, the root and untracked "
          "bones stay at the placement pose. Plays once and holds the last "
          "frame until restore_rest_pose. A clip that drives none of this "
          "skeleton's bones is a visual no-op (BC's exact-strcmp channel "
          "binding silently idles unmatched nodes).");
    m.def("play_instance_walk",
          [](scenegraph::InstanceId id, int clip_index) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.layer_over_rest = false;   // FULL clip: root translation applied
              st.sample_at_start = false;
              st.sample_at_end = false;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a full clip with ROOT MOTION applied (non-layered): the clip's "
          "baked Bip01 root translation moves the character across the set (e.g. "
          "a turbolift walk-on). Plays once and settles at the last frame.");
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
              std::vector<float> out(16);              // ROW-MAJOR for Python
              for (int r = 0; r < 4; ++r)
                  for (int c = 0; c < 4; ++c) out[r * 4 + c] = w[c][r];
              return py::cast(out);
          },
          py::arg("iid"), py::arg("node_name"), py::arg("animated") = true,
          "Return the named node's world transform as 16 floats (row-major), "
          "or None if the instance/node is absent. animated=True applies the "
          "current node overrides; False composes the static locals (rest).");

    m.def("instance_surface_points",
          [](scenegraph::InstanceId id) -> py::object {
              auto* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* mdl = resolve_model(in->model_handle);
              if (!mdl) return py::none();
              std::vector<std::tuple<float, float, float>> out;
              out.reserve(mdl->surface_points.size());
              for (const glm::vec3& p : mdl->surface_points) {
                  glm::vec4 w = in->world * glm::vec4(p, 1.0f);  // model -> world
                  out.emplace_back(w.x, w.y, w.z);
              }
              return py::cast(out);
          },
          py::arg("iid"),
          "World-space sample of the instance model's hull surface points "
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
                                            py::none());
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

              glm::mat4 world(1.0f);
              world[3][0] = pos.x;
              world[3][1] = pos.y;
              world[3][2] = pos.z;
              g_world.set_world_transform(id, world);
              g_world.set_pass(id, bridge ? scenegraph::Pass::Bridge
                                          : scenegraph::Pass::Space);
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
                  g_lens_flares.push_back(std::move(f));
              }
          },
          py::arg("flares"),
          "Set the active lens-flare list, applied each frame().");

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
              return py::make_tuple(c.x, c.y, c.z, radius);
          },
          py::arg("instance_id"),
          "Return (cx, cy, cz, radius) world-space bounding sphere of the "
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
              return py::make_tuple(c.x, c.y, c.z);
          },
          py::arg("instance_id"),
          "Return (cx, cy, cz) world-space centre of a posed character's HEAD "
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

    m.def("specular_set_enabled",
          [](bool enabled) { dauntless_specular::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass specular term. Default: on.");
    m.def("rim_set_enabled",
          [](bool enabled) { dauntless_rim::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass Fresnel rim term. Default: on.");
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
    m.def("warp_flythrough_set_enabled",
          [](bool enabled) { dauntless_warp_vfx::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the procedural warp flythrough VFX (Modern VFX). Default: on.");
    m.def("warp_flythrough_enabled",
          []() { return dauntless_warp_vfx::enabled(); },
          "Read the Warp Flythrough toggle (Modern VFX). Default: on.");
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
    m.def("hdr_set_enabled",
          [](bool e) { dauntless_hdr::set_enabled(e); },
          py::arg("enabled"),
          "Toggle the HDR resolve (tonemap+bloom+grade). Default: on.");
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
    m.def("decals_set_enabled",
          [](bool enabled) { dauntless_decals::set_enabled(enabled); },
          py::arg("enabled"),
          "Enable/disable persistent hull damage decals (default on).");
    m.def("smaa_set_enabled",
          [](bool enabled) { g_smaa_enabled = enabled; },
          py::arg("enabled"),
          "Enable/disable the post-process SMAA 1x pass (default on).");

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
             float intensity) {
              if (!g_shield_pass) return;
              const glm::vec3 p(std::get<0>(point),
                                 std::get<1>(point),
                                 std::get<2>(point));
              const glm::vec4 c(std::get<0>(rgba),
                                 std::get<1>(rgba),
                                 std::get<2>(rgba),
                                 std::get<3>(rgba));
              g_shield_pass->shield_hit(id, p, c, intensity, glfwGetTime());
          },
          py::arg("instance_id"), py::arg("point"),
          py::arg("rgba") = std::make_tuple(0.0f, 0.0f, 0.0f, 0.0f),
          py::arg("intensity") = 1.0f,
          "Push a shield-hit flash for the given ship at a world-space point. "
          "rgba=(0,0,0,0) substitutes the ship's default ShieldGlowColor.");

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

              auto hit = renderer::ray_trace_instance(
                  *model, inst->world, o, d, max_dist);
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
          "Ray-cast a world-space ray against an instance's loaded mesh. "
          "origin and direction are in world coordinates; direction is "
          "auto-normalised. Returns ((point), (normal), t) on hit or None "
          "on miss. t is world-space distance from origin.");

    m.def("damage_decal_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float radius, float intensity,
             std::uint32_t weapon_class, float time) {
              if (weapon_class > 1u) return;  // unknown weapon class — drop silently
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              const glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              // Convert radius game-units -> NIF/model units here (the same
              // space as pb), so the ring's merge test and the shader both work
              // in model units. s = |world's X column| = the uniform NIF->world
              // scale baked into inst->world.
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float radius_model = (s > 0.0f) ? radius / s : radius;
              inst->decals.add(pb, nb, radius_model, intensity,
                               static_cast<scenegraph::WeaponClass>(weapon_class),
                               time);
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("radius"), py::arg("intensity"),
          py::arg("weapon_class"), py::arg("time"),
          "Record an object-space damage decal on a ship instance. World-space "
          "point/normal are transformed into the ship body frame. weapon_class: "
          "0=HeatGlow (phaser), 1=Scorch (torpedo/disruptor).");

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
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              // Transform the world-space surface normal to body frame.
              // world_dir_to_body strips translation and scale; result is
              // a unit body-frame outward normal. Fall back to the radial
              // direction from origin if the transformed result is degenerate.
              glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              if (glm::length(nb) < 1e-4f) {
                  nb = (glm::length(pb) > 1e-4f)
                       ? glm::normalize(pb)
                       : glm::vec3(0.f, 0.f, 1.f);
              }
              // s = |world's X column| = the uniform NIF->world scale baked into
              // inst->world (same derivation as damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              const float influ_model = influ_radius * inv_s;
              const float floor_model = floor_radius * inv_s;

              // Accumulate strength; derive the visible radius from the grown
              // total (BC's additive metaball field) but never shrink, and never
              // below the caller's floor (authored / core-breach carves want a
              // guaranteed size; combat hits pass floor 0 and stay invisible
              // until the accumulated strength crosses the iso).
              scenegraph::HullCarve& c =
                  inst->carve.add(pb, influ_model, strength, nb);
              const float prev_radius = c.radius;
              // Strength -> an ABSOLUTE carve radius (GU): a weapon carves the
              // same hole whatever it hits, so no scaling by hull size.
              // radius_modifier is BC's per-ship DamageRadMod (default 1.0; only
              // big fixed structures set it bigger).
              const float vis_gu =
                  scenegraph::hull_carve_strength_to_radius_gu(c.strength)
                  * radius_modifier;
              const float vis_model = vis_gu * inv_s;
              c.radius = std::max(c.radius, std::max(floor_model, vis_model));

              // Breach event (transient VFX: debris, venting, rim) only when the
              // carve newly appears or visibly grows — sub-iso accumulation is
              // silent, so phaser dribble doesn't spray debris before it breaches.
              if (c.radius > prev_radius + 1e-4f && c.radius > 0.0f) {
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
                  inst->breach_events.push(pb, c.radius, nb,
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
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              const glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              return py::make_tuple(
                  py::make_tuple(pb.x, pb.y, pb.z),
                  py::make_tuple(nb.x, nb.y, nb.z));
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          "Convert a world-space hit point + normal into the ship instance's "
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
    keys.attr("KEY_F7")    = GLFW_KEY_F7;
    keys.attr("KEY_F8")    = GLFW_KEY_F8;
    keys.attr("KEY_F9")    = GLFW_KEY_F9;
    keys.attr("KEY_F10")   = GLFW_KEY_F10;
    keys.attr("KEY_F12")          = GLFW_KEY_F12;
    keys.attr("KEY_LEFT_BRACKET")  = GLFW_KEY_LEFT_BRACKET;
    keys.attr("KEY_RIGHT_BRACKET") = GLFW_KEY_RIGHT_BRACKET;
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
}
