#pragma once
#include <pybind11/pybind11.h>

namespace open_stbc::audio {
// Attach the `audio` submodule onto the parent _open_stbc_host module.
void register_python_bindings(pybind11::module_& parent);

// Test/host accessor — the singleton AudioSystem after init().
class AudioSystem;
AudioSystem* system();
}  // namespace open_stbc::audio
