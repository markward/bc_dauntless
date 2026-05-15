// native/src/host/host_bindings.cc
//
// pybind11 module exposing the renderer host API to Python. Built as both:
//   1. A standalone Python extension module (_open_stbc_host.so) for pytest.
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
#include <renderer/bridge_pass.h>
#include <renderer/aabb.h>
#include <ui/UiSystem.h>
#include <ui/PanelDocument.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <assets/cache.h>

#include <cstdlib>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace py = pybind11;

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
std::unique_ptr<renderer::BridgePass>      g_bridge_pass;
double g_prev_frame_time_seconds = 0.0;

// Bridge pass state. Camera is set from Python via set_bridge_camera each
// tick when bridge mode is active. The pass renders after the dust pass and
// before the UI overlay; see frame().
scenegraph::Camera g_bridge_camera;
bool g_bridge_pass_enabled = false;

struct LoadedModel {
    std::filesystem::path nif_path;
    assets::ModelHandle handle;
};

std::unique_ptr<assets::AssetCache> g_cache;
std::vector<LoadedModel> g_loaded_models;  // index = our public ModelHandle - 1

std::unique_ptr<ui::UiSystem> g_ui_system;
ui::HudState                  g_hud_state;

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

void init(int width, int height, const std::string& title,
          const std::string& ui_assets_root = "") {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
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
    g_backdrops.clear();
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_suns.clear();
    g_sun_pass = std::make_unique<renderer::SunPass>();
    g_dust_pass = std::make_unique<renderer::DustPass>();
    g_shield_pass = std::make_unique<renderer::ShieldPass>();
    g_lens_flare_pass = std::make_unique<renderer::LensFlarePass>();
    g_torpedo_pass = std::make_unique<renderer::TorpedoPass>();
    g_hit_vfx_pass = std::make_unique<renderer::HitVfxPass>();
    g_phaser_pass  = std::make_unique<renderer::PhaserPass>();
    g_bridge_pass  = std::make_unique<renderer::BridgePass>();
    g_prev_frame_time_seconds = glfwGetTime();

    if (!ui_assets_root.empty()) {
        g_ui_system = std::make_unique<ui::UiSystem>(
            g_window->native_handle(),
            std::filesystem::path(ui_assets_root));
    }
}

void shutdown() {
    // UI system must be destroyed before g_window — RmlUi shutdown calls into
    // the GL render interface, which needs a valid GL context.
    g_ui_system.reset();
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
    g_bridge_pass.reset();
    g_window.reset();
    g_prev_key_state.clear();
    g_prev_mouse_state.clear();
    // Mirror init()'s lighting reset for symmetry and defense-in-depth:
    // any future code path that reads g_lighting between shutdown() and a
    // subsequent init() will see the documented default, not stale state
    // from the previous session.
    g_lighting = renderer::Lighting{};
    g_bridge_lighting = renderer::Lighting{};
    g_hud_state = ui::HudState{};
}

bool should_close() {
    return !g_window || g_window->should_close();
}

void frame() {
    if (!g_window || !g_pipeline || !g_submitter) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);
    glViewport(0, 0, fw, fh);
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        if (h == 0 || h > g_loaded_models.size()) return nullptr;
        return g_loaded_models[h - 1].handle.get();
    };

    g_world.propagate();
    g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);
    g_sun_pass->render(g_suns, g_camera, *g_pipeline);
    g_submitter->submit_opaque_in_pass(
        g_world, g_camera, *g_pipeline, lookup, g_lighting,
        scenegraph::Pass::Space);

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;

    // Shield pass: additive flash on top of opaque ships. Runs before dust
    // so dust specks appear in front of fading shields (both are additive
    // blends, so order is mostly cosmetic, but dust drawn last keeps it
    // visually on top of any lingering shield fade).
    if (g_shield_pass) g_shield_pass->submit(g_world, g_camera, *g_pipeline,
                                              now, lookup);

    if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline);

    if (g_lens_flare_pass) {
        g_lens_flare_pass->render(g_lens_flares, g_camera, *g_pipeline,
                                  fw, fh, now);
    }

    if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    g_camera, *g_pipeline);
    if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, g_camera, *g_pipeline);
    if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx,      g_camera, *g_pipeline);

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

    if (g_ui_system) {
        g_ui_system->update_hud(g_hud_state);
        g_ui_system->render(fw, fh);
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
    g_window->poll_events();
    g_window->swap_buffers();
}

}  // namespace

PYBIND11_MODULE(_open_stbc_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase B: window + frame stub)";
    m.def("init", &init,
          py::arg("width"), py::arg("height"), py::arg("title"),
          py::arg("ui_assets_root") = "",
          "Open a window and initialise the renderer. ui_assets_root points to "
          "native/assets/ui/; leave empty to skip UI initialisation.");
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
                  s.position          = {std::get<0>(pos),
                                         std::get<1>(pos),
                                         std::get<2>(pos)};
                  s.radius            = d["radius"].cast<float>();
                  s.base_texture_path = d["base_texture_path"].cast<std::string>();
                  s.corona_radius     = d["corona_radius"].cast<float>();
                  g_suns.push_back(std::move(s));
              }
          },
          py::arg("suns"),
          "Set the active sun list, applied each frame().");

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
                  v.age = d["age"].cast<float>();
                  g_hit_vfx.push_back(std::move(v));
              }
          },
          py::arg("vfx"),
          "Set the active hit-VFX list (position + age), applied each frame().");

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
                  g_phaser_beams.push_back(std::move(b));
              }
          },
          py::arg("beams"),
          "Set the active phaser-beam list, applied each frame().");

    m.def("dust_set_enabled",
          [](bool enabled) {
              if (g_dust_pass) g_dust_pass->set_enabled(enabled);
          },
          py::arg("enabled"),
          "Toggle the space-dust pass at runtime. Default: on.");

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

    m.def("set_hud_state",
          [](const py::dict& d) {
              if (!g_ui_system) return;
              auto pos = d["pos"].cast<std::tuple<float,float,float>>();
              g_hud_state.pos_x       = std::get<0>(pos);
              g_hud_state.pos_y       = std::get<1>(pos);
              g_hud_state.pos_z       = std::get<2>(pos);
              g_hud_state.yaw_deg     = d["yaw"].cast<float>();
              g_hud_state.pitch_deg   = d["pitch"].cast<float>();
              g_hud_state.roll_deg    = d["roll"].cast<float>();
              g_hud_state.system_name = d["system"].cast<std::string>();
              g_hud_state.ship_name   = d["ship"].cast<std::string>();
          },
          py::arg("state"),
          "Update HUD overlay state. No-op when UI is not initialized.");

    auto keys = m.def_submodule("keys", "GLFW key-code constants for input bindings.");
    keys.attr("KEY_W") = GLFW_KEY_W;
    keys.attr("KEY_S") = GLFW_KEY_S;
    keys.attr("KEY_A") = GLFW_KEY_A;
    keys.attr("KEY_D") = GLFW_KEY_D;
    keys.attr("KEY_Q") = GLFW_KEY_Q;
    keys.attr("KEY_E") = GLFW_KEY_E;
    keys.attr("KEY_R") = GLFW_KEY_R;
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
    keys.attr("KEY_UP")    = GLFW_KEY_UP;
    keys.attr("KEY_DOWN")  = GLFW_KEY_DOWN;
    keys.attr("KEY_LEFT")  = GLFW_KEY_LEFT;
    keys.attr("KEY_RIGHT") = GLFW_KEY_RIGHT;
    keys.attr("KEY_F7")    = GLFW_KEY_F7;
    keys.attr("KEY_F8")    = GLFW_KEY_F8;
    keys.attr("KEY_F9")    = GLFW_KEY_F9;
    keys.attr("KEY_F10")   = GLFW_KEY_F10;
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

    // ── UI scale ─────────────────────────────────────────────────────────
    m.def("set_ui_scale",
          [](float scale) {
              if (!g_ui_system) return;
              g_ui_system->set_ui_scale(scale);
          });

    m.def("toggle_ui_debugger",
          []() {
              if (!g_ui_system) return;
              g_ui_system->toggle_debugger();
          });

    m.def("toggle_ui_visibility",
          []() {
              if (!g_ui_system) return;
              g_ui_system->toggle_visibility();
          });

    // ── UI panel + element primitives ───────────────────────────────────
    //
    // Panel ids are unique across the UiSystem. Element ids are unique
    // within a panel and the binding layer resolves which panel owns a
    // given element id by linear scan — fine for our small number of
    // panels (typically 1-4).
    m.def("create_panel",
          [](const std::string& /*name*/, const std::string& anchor,
             float width_vw, float height_vh) -> int {
              if (!g_ui_system) {
                  throw std::runtime_error("create_panel: ui system not initialized");
              }
              return g_ui_system->create_panel(anchor, width_vw, height_vh);
          });

    m.def("destroy_panel", [](int panel_id) {
        if (!g_ui_system) return;
        g_ui_system->destroy_panel(panel_id);
    });

    m.def("clear_panel", [](int panel_id) {
        if (!g_ui_system) return;
        if (auto* p = g_ui_system->get_panel(panel_id)) p->clear();
    });

    m.def("set_panel_visible", [](int panel_id, bool visible) {
        if (!g_ui_system) return;
        if (auto* p = g_ui_system->get_panel(panel_id)) p->set_visible(visible);
    });

    m.def("panel_root", [](int panel_id) -> int {
        if (!g_ui_system) return 0;
        auto* p = g_ui_system->get_panel(panel_id);
        return p ? p->root_element_id() : 0;
    });

    m.def("panel_bounds", [](int panel_id) -> py::tuple {
        if (!g_ui_system) return py::make_tuple(0.0f, 0.0f, 0.0f, 0.0f);
        auto* p = g_ui_system->get_panel(panel_id);
        if (!p) return py::make_tuple(0.0f, 0.0f, 0.0f, 0.0f);
        float x = 0.0f, y = 0.0f, w = 0.0f, h = 0.0f;
        p->bounds(&x, &y, &w, &h);
        return py::make_tuple(x, y, w, h);
    },
    "Return (x, y, w, h) screen-pixel rect of the panel.  (x, y) is "
    "top-left, (w, h) is outer size.  Returns (0,0,0,0) if the panel "
    "doesn't exist or hasn't been laid out yet.");

    m.def("set_panel_css_var",
          [](int panel_id, const std::string& name, const std::string& value) {
              if (!g_ui_system) return;
              if (auto* p = g_ui_system->get_panel(panel_id))
                  p->set_css_var(name, value);
          });

    m.def("append_div",
          [](int parent_id, const std::string& class_names) -> int {
              if (!g_ui_system) return 0;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(parent_id)) {
                      return kv.second->append_div(parent_id, class_names);
                  }
              }
              throw std::runtime_error("append_div: parent_id not found in any panel");
          });

    m.def("remove_element", [](int element_id) {
        if (!g_ui_system) return;
        for (auto& kv : g_ui_system->panels_for_bindings()) {
            if (kv.second->has_element(element_id)) {
                kv.second->remove_element(element_id); return;
            }
        }
    });

    m.def("set_class",
          [](int element_id, const std::string& class_names) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->set_class(element_id, class_names); return;
                  }
              }
          });

    m.def("set_text",
          [](int element_id, const std::string& text) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->set_text(element_id, text); return;
                  }
              }
          });

    m.def("set_visible",
          [](int element_id, bool visible) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->set_visible(element_id, visible); return;
                  }
              }
          });

    m.def("set_element_property",
          [](int element_id, const std::string& name, const std::string& value) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->set_property(element_id, name, value); return;
                  }
              }
          },
          "Set an arbitrary RCSS property on a UI element (e.g. "
          "set_element_property(body_id, 'margin-top', '-30dp')).");

    m.def("on_click",
          [](int element_id, py::object callback) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      if (callback.is_none()) {
                          kv.second->on_click(element_id, nullptr);
                      } else {
                          kv.second->on_click(element_id, [callback]() {
                              py::gil_scoped_acquire gil;
                              callback();
                          });
                      }
                      return;
                  }
              }
          });

    m.def("on_dblclick",
          [](int element_id, py::object callback) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      if (callback.is_none()) {
                          kv.second->on_dblclick(element_id, nullptr);
                      } else {
                          kv.second->on_dblclick(element_id, [callback]() {
                              py::gil_scoped_acquire gil;
                              callback();
                          });
                      }
                      return;
                  }
              }
          });

    open_stbc::audio::register_python_bindings(m);
}
