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

#include <renderer/window.h>

#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string>

namespace py = pybind11;

namespace {

std::unique_ptr<renderer::Window> g_window;

void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    // Visible by default. Tests that need offscreen can set OPEN_STBC_HOST_HEADLESS=1.
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
}

void shutdown() {
    g_window.reset();
}

bool should_close() {
    return !g_window || g_window->should_close();
}

void frame() {
    if (!g_window) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
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
}
