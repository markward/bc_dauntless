#pragma once

#include <assets/texture.h>

#include <cstdint>
#include <optional>
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

/// The long edge to draw a panel at: the quality's edge, but no more than
/// kPanelCanvasScale x the authored canvas's long edge (rounded up) and, below
/// that, no less than kPanelMinEdge. Mark authors at the texture's resolution
/// (a 512x512 trace of a 512x512 glow map), so High's 2048 for such a panel
/// costs 4x the raster and upload of 1024 for detail nobody sees (spec §7).
inline constexpr float kPanelCanvasScale = 2.f;
inline constexpr std::uint32_t kPanelMinEdge = 512;
std::uint32_t panel_edge_cap(std::uint32_t quality_edge, float canvas_w, float canvas_h);

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

/// A rectangle of a panel image, in pixels from its top-left.
struct PanelRect { std::uint32_t x, y, w, h; };

/// The smallest rectangle holding every pixel that differs between two w*h
/// RGBA8 images (same size spans); nullopt when they are identical. The panel
/// worker uploads only this, so an unchanged frame costs no upload at all and
/// one button moving costs that button.
std::optional<PanelRect> changed_rect(std::span<const std::uint8_t> before,
                                      std::span<const std::uint8_t> after,
                                      std::uint32_t w, std::uint32_t h);

/// The smallest rect holding both; an empty one (w or h 0) adds nothing.
PanelRect union_rect(PanelRect a, PanelRect b);

/// `r` out of a `w`-wide RGBA8 image into `out` (r.w*r.h*4 bytes), tightly
/// packed row by row, as glTexSubImage2D reads it.
void copy_rect(std::span<const std::uint8_t> image, std::uint32_t w, PanelRect r,
               std::span<std::uint8_t> out);

/// GL's size for mip `level` of a w x h image: each side halved per level
/// (floored), never below 1.
PanelSize mip_size(std::uint32_t w, std::uint32_t h, int level);
/// Levels in a full chain down to 1x1, level 0 included.
int mip_levels(std::uint32_t w, std::uint32_t h);

/// `dst_rect` of the next level (mip_size(sw, sh, 1)) from `src` (sw x sh
/// RGBA8, straight, like glGenerateMipmap filters it): each pixel the rounded
/// mean of its 2x2 block, the block clamped at a 1-pixel edge. `dst` is the
/// whole next level; nothing outside `dst_rect` is written. The panel worker
/// builds mips with this so the render thread never calls glGenerateMipmap,
/// which measured 5-10 ms a call in a live window (2026-10-30, perf P-14).
void downsample_rect(std::span<const std::uint8_t> src, std::uint32_t sw, std::uint32_t sh,
                     std::span<std::uint8_t> dst, PanelRect dst_rect);

/// The pixels of the next level whose 2x2 block reads any of `r` (a rect of
/// a sw x sh level); nullopt when none does (an odd edge GL never reads).
std::optional<PanelRect> mip_rect(PanelRect r, std::uint32_t sw, std::uint32_t sh);

}  // namespace lottie
