#pragma once
#include <cstdint>
#include <memory>
#include <vector>
#include <renderer/shader.h>

namespace renderer {

/// Developer diagnostic: detects NaN / Inf texels in a floating-point render
/// target and reports roughly where on screen they were.
///
/// Why this exists
/// ---------------
/// A single non-finite texel in the HDR target used to paint a hard-edged black
/// rectangle tens of pixels across, for one frame, at an unpredictable position.
/// The amplifier was the bloom chain (see bloom_prefilter.frag's comment); that
/// is now fixed, which means the SOURCE of the non-finite value is invisible
/// again. This probe keeps it visible.
///
/// Point it at the HDR target, NOT at the bloom output. After the prefilter fix
/// the two signals should move in OPPOSITE directions: the probe keeps firing
/// (whatever emits the non-finite value is still emitting it) while the black
/// rectangles stop. If both go quiet at once, something other than the intended
/// change moved and the result should not be trusted.
///
/// Cost
/// ----
/// Every source texel is inspected -- sampling would defeat the purpose, since
/// the seed can be a single pixel. Two reduction passes (source -> 1/8 -> grid)
/// keep occupancy reasonable, then a small synchronous readback. Perhaps a
/// millisecond or two at 1080p plus a pipeline stall for the readback, so this
/// is opt-in and off by default even under --developer.
class NonfiniteProbe {
public:
    /// Coarse readback grid. 32x18 keeps the readback at 576 bytes while still
    /// localising a hit to ~60x60 screen pixels at 1080p -- enough to say which
    /// object or effect it landed on.
    static constexpr int kGridW = 32;
    static constexpr int kGridH = 18;

    struct Result {
        bool any = false;             ///< any non-finite texel this frame
        int  flagged_cells = 0;       ///< how many grid cells tripped
        /// Largest cause code seen (opaque.frag's u_nan_debug encoding, 1..17).
        /// 1 means "flagged but no cause recorded" -- either the shader-side
        /// debug was off, or the writer was a pass that does not emit codes.
        /// With several distinct causes in one frame, the highest wins.
        int  max_code = 0;
        /// kGridW*kGridH row-major cells, origin BOTTOM-LEFT (GL convention).
        /// Non-zero = that cell contained at least one non-finite texel, and the
        /// value IS the cause code for that cell.
        std::vector<std::uint8_t> grid;
    };

    NonfiniteProbe();
    ~NonfiniteProbe();
    NonfiniteProbe(const NonfiniteProbe&) = delete;
    NonfiniteProbe& operator=(const NonfiniteProbe&) = delete;

    /// Reduce `src_tex` (`fw` x `fh`) and read back the flag grid. Saves and
    /// restores cull/depth/blend and leaves FBO 0 bound, like the other
    /// fullscreen passes. The returned reference is valid until the next run().
    const Result& run(std::uint32_t src_tex, int fw, int fh);

    /// Last result without re-running.
    const Result& last() const { return result_; }

private:
    struct Target {
        std::uint32_t tex = 0, fbo = 0;
        int w = 0, h = 0;
    };
    void rebuild(int fw, int fh);
    void destroy();
    void reduce(std::uint32_t src_tex, const Target& dst, int block_x,
                int block_y, bool detect);
    void draw_quad();

    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
    Target coarse_;              ///< 1/8-res intermediate
    Target grid_;                ///< kGridW x kGridH readback target
    int    fw_ = 0, fh_ = 0;     ///< source size the targets were built for
    Result result_;
};

}  // namespace renderer
