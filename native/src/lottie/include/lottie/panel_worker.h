#pragma once

#include <assets/panel_files.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <vector>

namespace lottie {

/// What a panel's load found. The canvas is the default file's.
struct PanelInfo {
    std::array<bool, assets::kPanelVariants> valid{};
    std::array<float, assets::kPanelVariants> total_frames{}, fps{};
    float canvas_w = 0, canvas_h = 0;
    std::uint64_t generation = 0;
};

struct PanelJob {
    std::uint64_t key;
    int variant;
    float frame;
    std::uint32_t w, h;
    std::uint64_t generation;
};

struct PanelResult {
    std::uint64_t key;
    std::uint64_t generation;
    std::uint32_t w, h;
    /// Straight RGBA from composite_panel_into, `bytes` = w*h*4. A plain
    /// array, not a vector: freeing it is one delete[] wherever it dies (the
    /// render thread, or take_results under the worker mutex), never a
    /// per-element destroy loop.
    std::unique_ptr<std::uint8_t[]> rgba;
    std::size_t bytes = 0;
    double raster_ms;
};

/// Bridge Lottie panels (spec 2026-10-28-bridge-lottie-panels-design.md §6):
/// the one thread that loads, rasterises and composites panels. Every
/// LottieClip / ThorVG object lives and dies on it, so the render thread only
/// queues work and collects finished buffers; nothing here blocks on a raster.
class PanelWorker {
public:
    PanelWorker();
    /// Drops queued work and joins (an in-flight raster finishes first).
    ~PanelWorker();
    PanelWorker(const PanelWorker&) = delete;
    PanelWorker& operator=(const PanelWorker&) = delete;

    /// Always (re)loads from disk on the worker and bumps the key's
    /// generation; results for older generations are dropped.
    void set_panel(std::uint64_t key, assets::PanelFiles files,
                   std::filesystem::path albedo);
    void remove_panel(std::uint64_t key);
    /// nullopt until that key's first load finishes.
    std::optional<PanelInfo> info(std::uint64_t key) const;
    /// False when a job for the key is already queued or running.
    bool submit(const PanelJob& job);
    /// Non-blocking.
    std::vector<PanelResult> take_results();
    /// Lets every warning print once more (dev reload).
    void clear_warnings();
    /// Tests only: sleep this long before each raster.
    void set_test_raster_delay(std::chrono::milliseconds d);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace lottie
