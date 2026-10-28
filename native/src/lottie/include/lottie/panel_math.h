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

/// The same, into `out` (w*h*4 bytes, every byte written), so a caller's
/// default-initialised array is never zeroed first.
void composite_panel_into(const assets::Image& still,
                          std::span<const std::uint8_t> lottie_premul_rgba,
                          std::uint32_t w, std::uint32_t h, std::span<std::uint8_t> out);

/// The still bilinear-scaled to w*h as straight RGBA8 (transparent black when
/// the still is empty): the panel worker caches this once per (panel, size).
std::vector<std::uint8_t> scale_still_rgba(const assets::Image& still,
                                           std::uint32_t w, std::uint32_t h);

/// Lottie over a scale_still_rgba result, every byte of `out` written; the
/// three spans are the same size. composite_panel_into is scale_still_rgba
/// then this, so a cached still gives the same bytes. The panel worker's
/// form: it writes into a default-initialised array, so a large buffer is
/// never zeroed first nor destroyed element by element (a Debug
/// std::vector<uint8_t> of 2 MB took ~5 ms to destroy).
void over_into(std::span<const std::uint8_t> still_rgba,
               std::span<const std::uint8_t> lottie_premul_rgba, std::span<std::uint8_t> out);

}  // namespace lottie
