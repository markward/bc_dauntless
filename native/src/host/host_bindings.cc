// native/src/host/host_bindings.cc
//
// pybind11 module exposing the renderer host API to Python. Built as both:
//   1. A standalone Python extension module (_dauntless_host.so) for pytest.
//   2. Statically linked into open_stbc (registered via
//      PyImport_AppendInittab before Py_InitializeEx).
//
// Phase B: real window owned by the bindings; init/shutdown control its
// lifetime, frame() polls + swaps. No draws yet — Phase D adds the opaque
// pass.

#include "host_bindings.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <audio/python_binding.h>

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/frame.h>
#include <renderer/backdrop_pass.h>
#include <renderer/sun_pass.h>
#include <renderer/dust_pass.h>
#include <renderer/shield_pass.h>
#include <renderer/lens_flare_pass.h>
#include <renderer/torpedo_pass.h>
#include <renderer/hit_vfx_pass.h>
#include <renderer/phaser_pass.h>
#include <renderer/hologram_pass.h>
#include <renderer/subsystem_pin_pass.h>
#include <renderer/bridge_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/bloom_pass.h>
#include <renderer/resolve_pass.h>
#include <renderer/ldr_target.h>
#include <renderer/fxaa_pass.h>
#include <renderer/aabb.h>
#include <renderer/ray_trace.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <assets/cache.h>
#include "developer_mode.h"

#ifdef DAUNTLESS_ENABLE_CEF
#include "ui_cef/cef_lifecycle.h"
#endif

#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace py = pybind11;

// Toggle for the HDR resolve pass. Defined in frame.cc (librenderer).
// Forward-declared here (before the anonymous namespace) so frame() inside
// the anonymous namespace can call dauntless_hdr::enabled().
namespace dauntless_hdr {
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
std::vector<renderer::Backdrop> g_backdrops;
std::unique_ptr<renderer::BackdropPass> g_backdrop_pass;
std::vector<renderer::SunDescriptor> g_suns;
std::vector<glm::vec4> g_dust_planets;   // xyz = world pos, w = radius
std::unique_ptr<renderer::SunPass> g_sun_pass;
std::unique_ptr<renderer::DustPass> g_dust_pass;
std::unique_ptr<renderer::ShieldPass> g_shield_pass;
std::vector<renderer::LensFlareDescriptor> g_lens_flares;
std::unique_ptr<renderer::LensFlarePass>   g_lens_flare_pass;
std::vector<renderer::TorpedoDescriptor>   g_torpedoes;
std::unique_ptr<renderer::TorpedoPass>     g_torpedo_pass;
std::vector<renderer::HitVfxDescriptor>    g_hit_vfx;
std::unique_ptr<renderer::HitVfxPass>      g_hit_vfx_pass;
std::vector<renderer::PhaserBeamDescriptor> g_phaser_beams;
std::unique_ptr<renderer::PhaserPass>      g_phaser_pass;
renderer::HologramShip                       g_hologram_ship;
std::unique_ptr<renderer::HologramPass>      g_hologram_pass;
std::vector<renderer::SubsystemPin>          g_subsystem_pins;
std::unique_ptr<renderer::SubsystemPinPass>  g_subsystem_pin_pass;
std::unique_ptr<renderer::BridgePass>      g_bridge_pass;
std::unique_ptr<renderer::HdrTarget>       g_hdr_target;
std::unique_ptr<renderer::BloomPass>       g_bloom_pass;
std::unique_ptr<renderer::ResolvePass>     g_resolve_pass;
std::unique_ptr<renderer::LdrTarget>       g_ldr_target;
std::unique_ptr<renderer::FxaaPass>        g_fxaa_pass;
bool g_fxaa_enabled = true;   // post-process FXAA; default on. Set by fxaa_set_enabled.
double g_prev_frame_time_seconds = 0.0;
float g_decal_game_time = 0.0f;  // game-time secs for decal ember; set by damage_decals_tick

// Bridge pass state. Camera is set from Python via set_bridge_camera each
// tick when bridge mode is active. The pass renders after the dust pass;
// see frame().
scenegraph::Camera g_bridge_camera;
bool g_bridge_pass_enabled = false;

struct LoadedModel {
    std::filesystem::path nif_path;
    assets::ModelHandle handle;
};

std::unique_ptr<assets::AssetCache> g_cache;
std::vector<LoadedModel> g_loaded_models;  // index = our public ModelHandle - 1

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

scenegraph::ModelHandle load_model_impl(const std::string& nif_path,
                                        const py::object& texture_search_path) {
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

    // Dedupe by nif_path: callers that load the same NIF for multiple ships
    // get the same handle and the underlying assets::AssetCache::load isn't
    // even called a second time.
    std::filesystem::path canonical = nif_path;
    for (std::size_t i = 0; i < g_loaded_models.size(); ++i) {
        if (g_loaded_models[i].nif_path == canonical) {
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
    auto handle = g_cache->load(nif_path, search_paths);
    g_loaded_models.push_back({std::move(canonical), std::move(handle)});
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
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_pass_enabled = false;
    g_backdrops.clear();
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_suns.clear();
    g_dust_planets.clear();
    g_sun_pass = std::make_unique<renderer::SunPass>();
    g_dust_pass = std::make_unique<renderer::DustPass>();
    g_shield_pass = std::make_unique<renderer::ShieldPass>();
    g_lens_flare_pass = std::make_unique<renderer::LensFlarePass>();
    g_torpedo_pass = std::make_unique<renderer::TorpedoPass>();
    g_hit_vfx_pass = std::make_unique<renderer::HitVfxPass>();
    g_phaser_pass        = std::make_unique<renderer::PhaserPass>();
    g_hologram_pass      = std::make_unique<renderer::HologramPass>();
    g_subsystem_pin_pass = std::make_unique<renderer::SubsystemPinPass>();
    g_bridge_pass        = std::make_unique<renderer::BridgePass>();
    g_hdr_target   = std::make_unique<renderer::HdrTarget>();
    g_bloom_pass   = std::make_unique<renderer::BloomPass>();
    g_resolve_pass = std::make_unique<renderer::ResolvePass>();
    g_ldr_target   = std::make_unique<renderer::LdrTarget>();
    g_fxaa_pass    = std::make_unique<renderer::FxaaPass>();
    g_prev_frame_time_seconds = glfwGetTime();
}

void shutdown() {
    // Destroy GL-handle owners BEFORE the GL context (g_window) goes away.
    // Order matters: pipeline shaders and the submitter's white-fallback
    // texture are GL objects that must be released while the context is
    // still current.
    g_submitter.reset();
    g_pipeline.reset();
    g_loaded_models.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_backdrops.clear();
    g_backdrop_pass.reset();  // releases sphere + texture caches while the
                              // GL context is still alive.
    g_suns.clear();
    g_dust_planets.clear();
    g_sun_pass.reset();
    g_dust_pass.reset();
    g_shield_pass.reset();
    g_lens_flares.clear();
    g_lens_flare_pass.reset();
    g_torpedoes.clear();
    g_torpedo_pass.reset();
    g_hit_vfx.clear();
    g_hit_vfx_pass.reset();
    g_phaser_beams.clear();
    g_phaser_pass.reset();
    g_subsystem_pins.clear();
    g_hologram_ship = renderer::HologramShip{};
    g_hologram_pass.reset();
    g_subsystem_pin_pass.reset();
    g_bridge_pass.reset();
    g_bloom_pass.reset();
    g_fxaa_pass.reset();
    g_ldr_target.reset();
    g_resolve_pass.reset();
    g_hdr_target.reset();
    g_window.reset();
    g_prev_key_state.clear();
    g_prev_mouse_state.clear();
    // Mirror init()'s lighting reset for symmetry and defense-in-depth:
    // any future code path that reads g_lighting between shutdown() and a
    // subsequent init() will see the documented default, not stale state
    // from the previous session.
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_bridge_pass_enabled = false;
}

bool should_close() {
    return !g_window || g_window->should_close();
}

void frame() {
    if (!g_window || !g_pipeline || !g_submitter) {
        throw std::runtime_error("_dauntless_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);

    // Route 3D scene into the HDR target. resize() is a no-op when unchanged.
    g_hdr_target->resize(fw, fh);
    g_hdr_target->bind();   // sets viewport to fw x fh
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        if (h == 0 || h > g_loaded_models.size()) return nullptr;
        return g_loaded_models[h - 1].handle.get();
    };

    g_world.propagate();
    g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;

    g_sun_pass->render(g_suns, g_camera, *g_pipeline, now);
    g_submitter->submit_opaque_in_pass(
        g_world, g_camera, *g_pipeline, lookup, g_lighting,
        scenegraph::Pass::Space, g_decal_game_time);

    // Shield pass: additive flash on top of opaque ships. Runs before dust
    // so dust specks appear in front of fading shields (both are additive
    // blends, so order is mostly cosmetic, but dust drawn last keeps it
    // visually on top of any lingering shield fade).
    if (g_shield_pass) g_shield_pass->submit(g_world, g_camera, *g_pipeline,
                                              now, lookup);

    if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline,
                                         g_suns, g_dust_planets);

    if (g_lens_flare_pass) {
        g_lens_flare_pass->render(g_lens_flares, g_camera, *g_pipeline,
                                  fw, fh, now);
    }

    if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    g_camera, *g_pipeline);
    if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, g_camera, *g_pipeline);
    if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx,      g_camera, *g_pipeline);
    if (g_hologram_pass && g_hologram_ship.active)
        g_hologram_pass->render(g_hologram_ship, g_world, g_camera, *g_pipeline, lookup);
    if (g_subsystem_pin_pass && !g_subsystem_pins.empty())
        g_subsystem_pin_pass->render(g_subsystem_pins, g_camera, *g_pipeline);

    // ── Bridge pass ──────────────────────────────────────────────────────
    // Renders bridge-tagged instances with the bridge camera, after a
    // color + depth clear so the bridge geometry overlays the space
    // scene cleanly (without the space pass's color leaking through any
    // gaps in the bridge interior). The space pass + special passes
    // above are wasted GPU work in bridge mode today, but are kept so
    // the future viewscreen RTT can swap the space pass's target from
    // "main framebuffer" to "viewscreen texture" without adding a
    // "render space here" path that didn't exist before.
    if (g_bridge_pass_enabled && g_bridge_pass) {
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        if (fh > 0) g_bridge_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);
        g_bridge_pass->render(g_world, g_bridge_camera, *g_pipeline,
                              lookup, g_bridge_lighting);
    }

    // Compute bloom from the HDR target while the HDR FBO is still in use.
    // bloom_tex is set to the HDR color texture as a harmless dummy when HDR is
    // off — the resolve's OFF branch never samples u_bloom.
    std::uint32_t bloom_tex = g_hdr_target->color_texture();
    if (dauntless_hdr::enabled()) {
        bloom_tex = g_bloom_pass->render(g_hdr_target->color_texture(), fw, fh);
    }

    // Resolve the HDR target. When FXAA is on, resolve into an LDR intermediate
    // target and then run FXAA into the backbuffer; when off, resolve straight
    // to the backbuffer (unchanged, zero-added-cost path). CEF composite + swap
    // run after this so the overlay composites on top of the resolved 3D scene.
    const bool fxaa_on = g_fxaa_enabled;
    if (fxaa_on) {
        g_ldr_target->resize(fw, fh);
        g_ldr_target->bind();
    } else {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);
    if (fxaa_on) {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
        g_fxaa_pass->draw(g_ldr_target->color_texture(), fw, fh);
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
// Toggle for the opaque-pass persistent damage decals. Defined in frame.cc.
namespace dauntless_decals {
    void set_enabled(bool v);  // defined in frame.cc
}

PYBIND11_MODULE(_dauntless_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase B: window + frame stub)";

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
          py::arg("nif_path"), py::arg("texture_search_path"));

    py::class_<scenegraph::InstanceId>(m, "InstanceId")
        .def_readonly("index", &scenegraph::InstanceId::index)
        .def_readonly("generation", &scenegraph::InstanceId::generation);

    m.def("create_instance",
          [](scenegraph::ModelHandle h) { return g_world.create_instance(h); },
          py::arg("model"));
    m.def("destroy_instance",
          [](scenegraph::InstanceId id) { g_world.destroy_instance(id); },
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

    m.def("create_bridge_instance",
          [](scenegraph::ModelHandle h) {
              auto id = g_world.create_instance(h);
              g_world.set_pass(id, scenegraph::Pass::Bridge);
              return id;
          },
          py::arg("model"),
          "Like create_instance but tags the new instance for the bridge pass.");

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

    m.def("set_bridge_wall_time",
          [](double t) { if (g_bridge_pass) g_bridge_pass->set_wall_time(t); },
          py::arg("t"),
          "Wall-clock seconds used to advance NiFlipController-driven "
          "texture animations on bridge materials (e.g. EBridge's LCARS "
          "Schematic Right panel). Host loop pushes time.monotonic() each "
          "tick.");

    m.def("set_backdrops",
          [](const std::vector<py::dict>& descriptors) {
              g_backdrops.clear();
              g_backdrops.reserve(descriptors.size());
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
                  auto m9 = d["world_rotation"].cast<std::vector<float>>();
                  if (m9.size() == 9) {
                      b.world_rotation = glm::mat3(
                          m9[0], m9[1], m9[2],
                          m9[3], m9[4], m9[5],
                          m9[6], m9[7], m9[8]);
                  }
                  g_backdrops.push_back(std::move(b));
              }
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
                  g_torpedoes.push_back(std::move(t));
              }
          },
          py::arg("torpedoes"),
          "Set the active torpedo list, applied each frame().");

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
                  g_hit_vfx.push_back(std::move(v));
              }
          },
          py::arg("vfx"),
          "Set the active hit-VFX list (position + normal + severity + age), "
          "applied each frame().");

    m.def("set_phaser_beams",
          [](const std::vector<py::dict>& descs) {
              g_phaser_beams.clear();
              g_phaser_beams.reserve(descs.size());
              for (const auto& d : descs) {
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
                  g_phaser_beams.push_back(std::move(b));
              }
          },
          py::arg("beams"),
          "Set the active phaser-beam list, applied each frame().");

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

    m.def("dust_set_enabled",
          [](bool enabled) {
              if (g_dust_pass) g_dust_pass->set_enabled(enabled);
          },
          py::arg("enabled"),
          "Toggle the space-dust pass at runtime. Default: on.");

    m.def("specular_set_enabled",
          [](bool enabled) { dauntless_specular::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass specular term. Default: on.");
    m.def("rim_set_enabled",
          [](bool enabled) { dauntless_rim::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass Fresnel rim term. Default: on.");
    m.def("hdr_set_enabled",
          [](bool e) { dauntless_hdr::set_enabled(e); },
          py::arg("enabled"),
          "Toggle the HDR resolve (tonemap+bloom+grade). Default: on.");
    m.def("decals_set_enabled",
          [](bool enabled) { dauntless_decals::set_enabled(enabled); },
          py::arg("enabled"),
          "Enable/disable persistent hull damage decals (default on).");
    m.def("fxaa_set_enabled",
          [](bool enabled) { g_fxaa_enabled = enabled; },
          py::arg("enabled"),
          "Enable/disable the post-process FXAA pass (default on).");

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

    m.def("damage_decals_tick",
          [](float time) {
              g_decal_game_time = time;
              g_world.for_each_alive([&](scenegraph::Instance& inst) {
                  inst.decals.tick(time);
              });
          },
          py::arg("time"),
          "Age every instance's decal ring; reclaim cold heat-glow decals.");

    auto keys = m.def_submodule("keys", "GLFW key-code constants for input bindings.");
    keys.attr("KEY_W") = GLFW_KEY_W;
    keys.attr("KEY_S") = GLFW_KEY_S;
    keys.attr("KEY_A") = GLFW_KEY_A;
    keys.attr("KEY_D") = GLFW_KEY_D;
    keys.attr("KEY_Q") = GLFW_KEY_Q;
    keys.attr("KEY_E") = GLFW_KEY_E;
    keys.attr("KEY_R") = GLFW_KEY_R;
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
    m.def("cef_pump",            []() {});
    m.def("cef_composite",       []() {});
    m.def("cef_shutdown",        []() {});
    m.def("cef_toggle_devtools", []() {});
    m.def("cef_reload",          []() {});
    m.def("cef_execute_javascript", [](const std::string&) {});
    m.def("cef_send_mouse_move",  [](int, int) {});
    m.def("cef_send_mouse_click", [](int, int, int, bool) {});
    m.def("cef_set_event_handler",[](py::function) {});
    m.def("cef_set_load_end_handler", [](py::function) {});
#endif

    dauntless::audio::register_python_bindings(m);
}
