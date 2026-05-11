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

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/frame.h>
#include <renderer/backdrop_pass.h>
#include <renderer/sun_pass.h>
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
std::vector<renderer::Backdrop> g_backdrops;
std::unique_ptr<renderer::BackdropPass> g_backdrop_pass;
std::vector<renderer::SunDescriptor> g_suns;
std::unique_ptr<renderer::SunPass> g_sun_pass;

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
std::unique_ptr<renderer::Pipeline> g_pipeline;
// FrameSubmitter is a unique_ptr (not a static instance) so its destructor —
// which calls glDeleteTextures on the white-fallback texture — runs from
// shutdown() while the GL context is still alive, not from process-exit
// static destruction order which would run after the Window is gone.
std::unique_ptr<renderer::FrameSubmitter> g_submitter;

scenegraph::ModelHandle load_model_impl(const std::string& nif_path,
                                        const std::string& texture_search_path) {
    if (!g_window) {
        throw std::runtime_error("load_model: init must be called first (asset upload needs a GL context)");
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
    if (!g_cache) g_cache = std::make_unique<assets::AssetCache>();
    auto handle = g_cache->load(nif_path, texture_search_path);
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
    g_backdrops.clear();
    g_backdrop_pass = std::make_unique<renderer::BackdropPass>();
    g_suns.clear();
    g_sun_pass = std::make_unique<renderer::SunPass>();

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
    g_window.reset();
    g_prev_key_state.clear();
    // Mirror init()'s lighting reset for symmetry and defense-in-depth:
    // any future code path that reads g_lighting between shutdown() and a
    // subsequent init() will see the documented default, not stale state
    // from the previous session.
    g_lighting = renderer::Lighting{};
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
    g_submitter->submit_opaque(g_world, g_camera, *g_pipeline, lookup, g_lighting);

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
    keys.attr("KEY_F8")    = GLFW_KEY_F8;

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

    m.def("panel_root", [](int panel_id) -> int {
        if (!g_ui_system) return 0;
        auto* p = g_ui_system->get_panel(panel_id);
        return p ? p->root_element_id() : 0;
    });

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
}
