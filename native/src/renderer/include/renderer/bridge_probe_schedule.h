// native/src/renderer/include/renderer/bridge_probe_schedule.h
//
// The bridge reflection capture queue's order (spec
// 2026-10-17-bridge-reflection-layers §4.7), the base cross-fade and the
// weighted entries the shader samples (§4.2). Pure, header-only: BridgePass
// supplies which probes need a capture / are valid; this decides.
#pragma once

#include <algorithm>
#include <cmath>
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

/// The base cross-fade (spec 2026-10-17 §4.2): `w[s]` is base s's share of
/// the reflection. Each update moves the `target` base toward 1 at
/// 1 / kBridgeProbeFadeSeconds per second and the others toward 0, the
/// weights always summing to 1 -- but only once the target base is valid
/// (`base_valid(target)`); until then every weight holds, so the old base
/// keeps showing. With every weight 0 (nothing showing yet: a new bridge),
/// the first valid target snaps to 1 at once. A non-positive or non-finite
/// dt moves nothing (pause). An out-of-range target holds.
///
/// The others give up the target's rise in proportion to their weight, so
/// a retarget mid-fade (red -> green -> yellow) moves every weight by at most
/// dt / kBridgeProbeFadeSeconds per update: no pop. With one other base (the
/// settled case) that is exactly "-= dt / 0.5".
inline constexpr float kBridgeProbeFadeSeconds = 0.5f;

struct ProbeFade {
    float w[kBridgeStates] = {};

    void update(int target, float dt, const std::function<bool(int)>& base_valid) {
        if (target < 0 || target >= kBridgeStates || !base_valid(target)) return;
        float others = 0.0f;
        for (int s = 0; s < kBridgeStates; ++s)
            if (s != target) others += w[s];
        if (w[target] + others <= 0.0f) {
            w[target] = 1.0f;
            return;
        }
        if (!(dt > 0.0f) || !std::isfinite(dt)) return;
        const float rise = std::min(dt / kBridgeProbeFadeSeconds, others);
        if (rise >= others) {
            for (int s = 0; s < kBridgeStates; ++s) w[s] = s == target ? 1.0f : 0.0f;
            return;
        }
        for (int s = 0; s < kBridgeStates; ++s)
            if (s != target) w[s] -= rise * (w[s] / others);
        w[target] = 1.0f - (others - rise);
    }
};

/// One reflection sampled by the bridge shader: probe id (base s = s, layer
/// k = kBridgeStates + k) and its weight in the sum.
struct ProbeEntry {
    int   probe = -1;
    float weight = 0.0f;
};

/// Entry caps (spec §4.2): at most 3 bases (a mid-fade retarget) and 16
/// layers (2 states x the High layer cap) are sampled per fragment.
inline constexpr int kBridgeMaxProbeBaseEntries = 3;
inline constexpr int kBridgeMaxProbeLayerEntries = 16;
inline constexpr int kBridgeMaxProbeEntries =
    kBridgeMaxProbeBaseEntries + kBridgeMaxProbeLayerEntries;

/// The weighted reflections to sample: every valid base with weight > 0, then
/// every valid layer k with `layer_values[k] x base_weight[layer_states[k]]`
/// > 0 (a missing value is 0), each group in probe order. Over a cap, the
/// group keeps its largest weights (ties: the lower probe id).
inline std::vector<ProbeEntry> probe_entries(const float (&base_weight)[kBridgeStates],
                                             const std::vector<int>& layer_states,
                                             const std::vector<float>& layer_values,
                                             const std::function<bool(int)>& valid) {
    auto keep_largest = [](std::vector<ProbeEntry>& v, int cap) {
        if (static_cast<int>(v.size()) <= cap) return;
        std::stable_sort(v.begin(), v.end(), [](const ProbeEntry& a, const ProbeEntry& b) {
            return a.weight > b.weight;
        });
        v.resize(static_cast<std::size_t>(cap));
        std::sort(v.begin(), v.end(), [](const ProbeEntry& a, const ProbeEntry& b) {
            return a.probe < b.probe;
        });
    };
    std::vector<ProbeEntry> bases, layers;
    for (int s = 0; s < kBridgeStates; ++s)
        if (base_weight[s] > 0.0f && valid(s)) bases.push_back({s, base_weight[s]});
    for (std::size_t k = 0; k < layer_states.size(); ++k) {
        const int s = layer_states[k];
        if (s < 0 || s >= kBridgeStates || k >= layer_values.size()) continue;
        const float wk = layer_values[k] * base_weight[s];
        const int probe = kBridgeStates + static_cast<int>(k);
        if (wk > 0.0f && valid(probe)) layers.push_back({probe, wk});
    }
    keep_largest(bases, kBridgeMaxProbeBaseEntries);
    keep_largest(layers, kBridgeMaxProbeLayerEntries);
    bases.insert(bases.end(), layers.begin(), layers.end());
    return bases;
}

}  // namespace renderer
