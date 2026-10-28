#pragma once

#include <assets/texture.h>

#include <cstdint>
#include <span>
#include <vector>

namespace lottie {

struct PanelTick {
    std::int64_t tick;  // monotonic, counts across loops
    float frame;        // Lottie frame to render, in [0, total_frames - 1]
};

/// Playback is capped at 30 Hz. Pure in `t`: equal times give equal results,
/// so a paused clock never re-renders.
PanelTick panel_tick(double t, double start, float total_frames, float fps);

struct PanelSize { std::uint32_t w, h; };

/// Fit the canvas aspect into `longest_edge` on its long side.
PanelSize panel_size(float canvas_w, float canvas_h, std::uint32_t longest_edge);

/// Lottie (premultiplied RGBA8, w*h) over the still scaled to w*h. The still's
/// RGB is used as-is: BC alpha is a test mask, not coverage.
std::vector<std::uint8_t> composite_panel(const assets::Image& still,
                                          std::span<const std::uint8_t> lottie_premul_rgba,
                                          std::uint32_t w, std::uint32_t h);

}  // namespace lottie
