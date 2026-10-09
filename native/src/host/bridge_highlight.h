// native/src/host/bridge_highlight.h
//
// The body of the developer-only set_bridge_highlight binding (spec
// 2026-10-08-bridge-emitters §4), as a free function so it is unit-tested in
// C++ (native/tests/host) -- where the developer gate can be set without any
// Python-reachable setter.
#pragma once

namespace renderer { class BridgePass; }

namespace dauntless {

/// The bridge editor's selection tint request. model 0 = none.
struct BridgeHighlight {
    unsigned long long model = 0;
    int selected = -1;
    int hover = -1;
};

/// Apply a set_bridge_highlight request. `model_handle` is the instance's
/// model handle, or 0 when the binding got None or a stale id (which clears).
/// No-op returning false without --developer. Otherwise updates `state` and,
/// when `pass` is non-null, pushes it to the pass; returns true.
bool apply_bridge_highlight(BridgeHighlight& state, renderer::BridgePass* pass,
                            unsigned long long model_handle, int selected,
                            int hover);

}  // namespace dauntless
