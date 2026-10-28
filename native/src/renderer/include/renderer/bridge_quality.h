// native/src/renderer/include/renderer/bridge_quality.h
#pragma once

#include <renderer/bridge_ao_pass.h>

#include <cstdint>

namespace renderer {

/// Bridge rendering quality presets, driving the bridge AO's sample count and
/// target resolution scale. Int-backed so it round-trips cleanly through the
/// Python binding (`set_bridge_quality` / `bridge_quality`).
enum class BridgeQuality : int { Low = 0, Medium = 1, High = 2 };

inline constexpr BridgeQuality kDefaultBridgeQuality = BridgeQuality::Medium;

/// AO settings for each preset:
///   Low    { 24, 0.5 }
///   Medium { 32, 0.5 }
///   High   { 64, 1.0 }
inline BridgeAoSettings ao_settings_for(BridgeQuality q) {
    switch (q) {
        case BridgeQuality::Low:    return BridgeAoSettings{24, 0.5f};
        case BridgeQuality::Medium: return BridgeAoSettings{32, 0.5f};
        case BridgeQuality::High:   return BridgeAoSettings{64, 1.0f};
    }
    return BridgeAoSettings{32, 0.5f};
}

/// Longest edge, in texels, of a bridge Lottie panel's texture per preset.
inline std::uint32_t panel_edge_for(BridgeQuality q) {
    switch (q) {
        case BridgeQuality::Low:    return 512;
        case BridgeQuality::Medium: return 1024;
        case BridgeQuality::High:   return 2048;
    }
    return 1024;
}

/// Clamp an arbitrary int (e.g. from Python) into a valid preset: below Low
/// clamps to Low, above High clamps to High.
inline BridgeQuality clamp_bridge_quality(int v) {
    if (v < static_cast<int>(BridgeQuality::Low)) return BridgeQuality::Low;
    if (v > static_cast<int>(BridgeQuality::High)) return BridgeQuality::High;
    return static_cast<BridgeQuality>(v);
}

}  // namespace renderer
