// native/src/host/host_bindings.cc
//
// pybind11 module exposing the renderer host API to Python. Built as both:
//   1. A standalone Python extension module (_open_stbc_host.so) for pytest.
//   2. Statically linked into open_stbc_host (registered via
//      PyImport_AppendInittab before Py_InitializeEx).
//
// Phase B: real window owned by the bindings; init/shutdown control its
// lifetime, frame() polls + swaps. No draws yet — Phase D adds the opaque
// pass.

#include "host_bindings.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <glad/glad.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/frame.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <assets/cache.h>

#include <cstdlib>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace py = pybind11;

namespace {

std::unique_ptr<renderer::Window> g_window;
scenegraph::World g_world;
scenegraph::Camera g_camera;

struct LoadedModel {
    std::filesystem::path nif_path;
    assets::ModelHandle handle;
};

std::unique_ptr<assets::AssetCache> g_cache;
std::vector<LoadedModel> g_loaded_models;  // index = our public ModelHandle - 1
std::unique_ptr<renderer::Pipeline> g_pipeline;
renderer::FrameSubmitter g_submitter;

scenegraph::ModelHandle load_model_impl(const std::string& nif_path,
                                        const std::string& texture_search_path) {
    if (!g_window) {
        throw std::runtime_error("load_model: init must be called first (asset upload needs a GL context)");
    }
    if (!g_cache) g_cache = std::make_unique<assets::AssetCache>();
    auto handle = g_cache->load(nif_path, texture_search_path);
    g_loaded_models.push_back({nif_path, std::move(handle)});
    return static_cast<scenegraph::ModelHandle>(g_loaded_models.size());
}

void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    // Visible by default. Tests that need offscreen can set OPEN_STBC_HOST_HEADLESS=1.
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
    g_pipeline = std::make_unique<renderer::Pipeline>();
    g_world = scenegraph::World{};
    g_loaded_models.clear();
}

void shutdown() {
    g_pipeline.reset();
    g_loaded_models.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_window.reset();
}

bool should_close() {
    return !g_window || g_window->should_close();
}

void frame() {
    if (!g_window || !g_pipeline) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);
    glViewport(0, 0, fw, fh);
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    g_world.propagate();
    g_submitter.submit_opaque(g_world, g_camera, *g_pipeline,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            if (h == 0 || h > g_loaded_models.size()) return nullptr;
            return g_loaded_models[h - 1].handle.get();
        });

    g_window->poll_events();
    g_window->swap_buffers();
}

}  // namespace

PYBIND11_MODULE(_open_stbc_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase B: window + frame stub)";
    m.def("init", &init, py::arg("width"), py::arg("height"), py::arg("title"));
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
    m.def("set_skybox",
          [](scenegraph::ModelHandle h) { g_world.set_skybox(h); },
          py::arg("model"));
}
