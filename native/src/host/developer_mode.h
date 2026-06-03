// native/src/host/developer_mode.h
//
// Process-global developer-mode flag. Parsed once from argv in host_main.cc;
// read by C++ callers (renderer overlays) directly, and exposed to Python via
// the _dauntless_host module's `developer_mode` attribute (see host_bindings.cc).
#pragma once

namespace dauntless {

// Returns true if the binary was launched with --developer.
bool is_developer_mode();

// Set by host_main.cc after parsing argv. Tests should not call this directly;
// they monkey-patch _dauntless_host.developer_mode in Python instead.
void set_developer_mode(bool enabled);

}  // namespace dauntless
