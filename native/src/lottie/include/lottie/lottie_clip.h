// native/src/lottie/include/lottie/lottie_clip.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace lottie {

/// Initialises ThorVG once (0 worker threads). Idempotent and thread-safe.
void ensure_thorvg_initialised();

/// One loaded Lottie animation, rasterised on the CPU by ThorVG.
class LottieClip {
public:
    ~LottieClip();
    LottieClip(const LottieClip&) = delete;
    LottieClip& operator=(const LottieClip&) = delete;

    /// Null on failure, with *error (when non-null) set to exactly one of
    /// "not a Lottie animation", "zero canvas size", "no frames",
    /// "unreadable file".
    static std::unique_ptr<LottieClip> load(const std::filesystem::path& file,
                                            std::string* error);

    float canvas_width() const;
    float canvas_height() const;
    float total_frames() const;
    float duration_s() const;
    float fps() const;

    /// Renders `frame` (0-based from the in-point) at w x h into
    /// `out_premul_rgba` (w*h*4 bytes, premultiplied R,G,B,A), cleared to
    /// transparent first. Not thread-safe per clip.
    bool render(float frame, std::uint32_t w, std::uint32_t h,
                std::vector<std::uint8_t>& out_premul_rgba);

private:
    LottieClip();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace lottie
