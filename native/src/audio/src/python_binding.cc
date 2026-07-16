#include <audio/python_binding.h>
#include <audio/audio_system.h>
#include <audio/null_backend.h>
#include <audio/openal_backend.h>
#include <memory>

namespace py = pybind11;

namespace dauntless::audio {

static std::unique_ptr<AudioSystem> g_system;

AudioSystem* system() { return g_system.get(); }

static Category parse_category(const std::string& s) {
    if (s == "Voice") return Category::Voice;
    if (s == "Interface") return Category::Interface;
    return Category::SFX;
}

static bool init_impl(const std::string& backend_kind) {
    if (g_system) { g_system->shutdown(); g_system.reset(); }
    std::unique_ptr<IAudioBackend> b;
    if (backend_kind == "null") {
        b = std::make_unique<NullBackend>();
    } else {
        b = make_openal_backend();
        if (!b) b = std::make_unique<NullBackend>();
    }
    g_system = std::make_unique<AudioSystem>(std::move(b));
    return g_system->init();
}

static void shutdown_impl() {
    if (g_system) { g_system->shutdown(); g_system.reset(); }
}

static bool load_sound_impl(const std::string& path, const std::string& name,
                            py::bytes wav, bool positional) {
    if (!g_system) return false;
    std::string s = wav;
    return g_system->load_sound(path, name,
                                reinterpret_cast<const uint8_t*>(s.data()),
                                s.size(), positional);
}

static uint32_t get_sound_impl(const std::string& name) {
    return g_system ? g_system->get_sound(name) : 0;
}

static double get_duration_impl(const std::string& name) {
    return g_system ? g_system->get_duration(name) : 0.0;
}

static uint32_t play_impl(const std::string& name, bool looping, float gain,
                          const std::string& category,
                          py::object position, bool force_non_positional) {
    if (!g_system) return 0;
    float x=0,y=0,z=0; bool provided=false;
    if (!position.is_none()) {
        auto t = position.cast<std::tuple<float,float,float>>();
        x = std::get<0>(t); y = std::get<1>(t); z = std::get<2>(t);
        provided = true;
    }
    return g_system->play_sound(name, looping, gain, parse_category(category),
                                provided, x, y, z,
                                force_non_positional);
}

static void stop_impl(uint32_t pid) { if (g_system) g_system->stop(pid); }

static void set_position_impl(uint32_t pid, float x, float y, float z) {
    if (g_system) g_system->set_position(pid, x, y, z);
}

static void set_velocity_impl(uint32_t pid, float x, float y, float z) {
    if (g_system) g_system->set_velocity(pid, x, y, z);
}

static void set_gain_impl(uint32_t pid, float g) {
    if (g_system) g_system->set_gain(pid, g);
}

static void set_looping_impl(uint32_t pid, bool l) {
    if (g_system) g_system->set_looping(pid, l);
}

static void set_min_max_distance_impl(uint32_t pid, float mn, float mx) {
    if (g_system) g_system->set_min_max_distance(pid, mn, mx);
}

static void set_category_gain_impl(const std::string& cat, float g) {
    if (g_system) g_system->set_category_gain(parse_category(cat), g);
}

static void update_impl(float lx, float ly, float lz,
                        float fx, float fy, float fz,
                        float ux, float uy, float uz, float dt) {
    if (g_system) g_system->update(lx,ly,lz, fx,fy,fz, ux,uy,uz, dt);
}

static py::list debug_command_log_impl() {
    py::list out;
    if (!g_system) return out;
    auto* nb = dynamic_cast<NullBackend*>(g_system->backend());
    if (!nb) return out;
    for (const auto& c : nb->command_log()) {
        py::dict d;
        d["op"] = c.op;
        d["u"] = py::make_tuple(c.u[0], c.u[1], c.u[2], c.u[3]);
        d["f"] = py::make_tuple(c.f[0], c.f[1], c.f[2], c.f[3],
                                 c.f[4], c.f[5], c.f[6], c.f[7], c.f[8],
                                 c.f[9], c.f[10], c.f[11]);
        d["b"] = py::make_tuple(c.b[0], c.b[1]);
        out.append(d);
    }
    return out;
}

static void clear_command_log_impl() {
    if (!g_system) return;
    if (auto* nb = dynamic_cast<NullBackend*>(g_system->backend()))
        nb->clear_command_log();
}

static bool is_finished_impl(uint32_t pid) {
    // No system at all means nothing is playing -> treat as finished so a
    // Python pump loop can't spin forever on a dead reference.
    return !g_system || g_system->is_finished(pid);
}

// Test-only hook: force `pid`'s underlying NullBackend source to report
// finished, so Python tests can simulate a one-shot completing naturally
// without waiting on real playback duration.
static void debug_mark_finished_impl(uint32_t pid) {
    if (!g_system) return;
    if (auto* nb = dynamic_cast<NullBackend*>(g_system->backend()))
        nb->mark_finished(g_system->debug_backend_handle(pid));
}

void register_python_bindings(py::module_& parent) {
    auto m = parent.def_submodule("audio", "OpenAL audio subsystem.");
    m.def("init", &init_impl, py::arg("backend") = "openal");
    m.def("shutdown", &shutdown_impl);
    m.def("load_sound", &load_sound_impl,
          py::arg("path"), py::arg("name"), py::arg("wav"),
          py::arg("positional") = false);
    m.def("get_sound", &get_sound_impl);
    m.def("get_duration", &get_duration_impl);
    m.def("play", &play_impl,
          py::arg("name"), py::arg("looping") = false,
          py::arg("gain") = 1.0f, py::arg("category") = "SFX",
          py::arg("position") = py::none(),
          py::arg("force_non_positional") = false);
    m.def("stop", &stop_impl);
    m.def("set_position", &set_position_impl);
    m.def("set_velocity", &set_velocity_impl);
    m.def("set_gain", &set_gain_impl);
    m.def("set_looping", &set_looping_impl);
    m.def("set_min_max_distance", &set_min_max_distance_impl);
    m.def("set_category_gain", &set_category_gain_impl);
    m.def("update", &update_impl);
    m.def("is_finished", &is_finished_impl);
    m.def("debug_mark_finished", &debug_mark_finished_impl);
    m.def("debug_command_log", &debug_command_log_impl);
    m.def("clear_command_log", &clear_command_log_impl);
}

}  // namespace dauntless::audio
