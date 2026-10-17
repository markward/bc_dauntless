// native/src/renderer/include/renderer/bridge_probe_schedule.h
//
// The bridge reflection capture queue's order (spec
// 2026-10-17-bridge-reflection-layers §4.7). Pure, header-only: BridgePass
// supplies which probes need a capture; this decides which one goes next.
#pragma once

#include <cstddef>
#include <functional>
#include <vector>

namespace renderer {

/// Bridge states (spec 2026-10-17-bridge-reflection-layers §4): 0 green,
/// 1 yellow, 2 red, 3 offline, 4 special. Probe ids: base of state s = s,
/// animation layer k = kBridgeStates + k.
inline constexpr int kBridgeStates = 5;

/// The next probe to capture, one at a time: the base of `shown_state`; then
/// the layers of `shown_state` (index order); then the other bases (index
/// order); then the other layers (index order). `layer_states[k]` is layer
/// k's state (probe kBridgeStates + k); `needs(probe)` says whether a probe
/// needs a capture. -1 when nothing does. An out-of-range `shown_state` has
/// no base or layers of its own: everything comes from the "other" groups.
inline int next_probe(int shown_state, const std::vector<int>& layer_states,
                      const std::function<bool(int)>& needs) {
    const bool shown_ok = shown_state >= 0 && shown_state < kBridgeStates;
    const int layers = static_cast<int>(layer_states.size());
    auto layer_state = [&](int k) { return layer_states[static_cast<std::size_t>(k)]; };
    if (shown_ok && needs(shown_state)) return shown_state;
    for (int k = 0; k < layers; ++k)
        if (layer_state(k) == shown_state && needs(kBridgeStates + k)) return kBridgeStates + k;
    for (int s = 0; s < kBridgeStates; ++s)
        if (s != shown_state && needs(s)) return s;
    for (int k = 0; k < layers; ++k)
        if (layer_state(k) != shown_state && needs(kBridgeStates + k)) return kBridgeStates + k;
    return -1;
}

}  // namespace renderer
