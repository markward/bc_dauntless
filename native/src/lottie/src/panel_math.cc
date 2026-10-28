#include <lottie/panel_math.h>

#include <algorithm>
#include <cmath>

namespace lottie {

PanelTick panel_tick(double t, double start, float total_frames, float fps) {
    const double rate = std::min<double>(fps, 30.0);
    const double duration = static_cast<double>(total_frames) / fps;
    // Bias so a time exactly on a tick boundary counts as the later tick.
    const double elapsed = (t - start) + 1e-9;
    const double loops = std::floor(elapsed / duration);
    const double local = elapsed - loops * duration;
    const double per_loop = std::ceil(duration * rate - 1e-9);
    const double in_loop = std::floor(local * rate);
    PanelTick out;
    out.tick = static_cast<std::int64_t>(loops * per_loop + in_loop);
    out.frame = static_cast<float>(
        std::min(in_loop * fps / rate, static_cast<double>(total_frames) - 1.0));
    return out;
}

PanelSize panel_size(float canvas_w, float canvas_h, std::uint32_t longest_edge) {
    const float lo = std::min(canvas_w, canvas_h);
    const float hi = std::max(canvas_w, canvas_h);
    const auto shortest = static_cast<std::uint32_t>(std::max<long>(
        1, std::lround(static_cast<double>(longest_edge) * lo / hi)));
    return canvas_w >= canvas_h ? PanelSize{longest_edge, shortest}
                                : PanelSize{shortest, longest_edge};
}

namespace {

struct Rgba { float r, g, b, a; };

Rgba still_texel(const assets::Image& im, std::uint32_t x, std::uint32_t y) {
    using F = assets::Image::Format;
    const std::size_t n = im.format == F::RGBA8 ? 4 : im.format == F::RGB8 ? 3 : 1;
    const std::uint8_t* p = &im.pixels[(static_cast<std::size_t>(y) * im.width + x) * n];
    if (n == 4) return {p[0] / 255.f, p[1] / 255.f, p[2] / 255.f, p[3] / 255.f};
    if (n == 3) return {p[0] / 255.f, p[1] / 255.f, p[2] / 255.f, 1.f};
    return {p[0] / 255.f, p[0] / 255.f, p[0] / 255.f, 1.f};
}

}  // namespace

std::vector<std::uint8_t> composite_panel(const assets::Image& still,
                                          std::span<const std::uint8_t> lottie,
                                          std::uint32_t w, std::uint32_t h) {
    std::vector<std::uint8_t> out(static_cast<std::size_t>(w) * h * 4);
    composite_panel_into(still, lottie, w, h, out);
    return out;
}

void composite_panel_into(const assets::Image& still, std::span<const std::uint8_t> lottie,
                          std::uint32_t w, std::uint32_t h, std::span<std::uint8_t> out) {
    const bool have_still = still.width > 0 && still.height > 0;
    for (std::uint32_t y = 0; y < h; ++y) {
        for (std::uint32_t x = 0; x < w; ++x) {
            Rgba s{0, 0, 0, 0};
            if (have_still) {
                // Texel-centre bilinear.
                const float fx = std::clamp((x + 0.5f) * still.width / w - 0.5f,
                                            0.f, static_cast<float>(still.width - 1));
                const float fy = std::clamp((y + 0.5f) * still.height / h - 0.5f,
                                            0.f, static_cast<float>(still.height - 1));
                const std::uint32_t x0 = static_cast<std::uint32_t>(fx);
                const std::uint32_t y0 = static_cast<std::uint32_t>(fy);
                const std::uint32_t x1 = std::min(x0 + 1, still.width - 1);
                const std::uint32_t y1 = std::min(y0 + 1, still.height - 1);
                const float tx = fx - x0, ty = fy - y0;
                const Rgba a = still_texel(still, x0, y0), b = still_texel(still, x1, y0);
                const Rgba c = still_texel(still, x0, y1), d = still_texel(still, x1, y1);
                auto mix = [&](float Rgba::* m) {
                    const float top = a.*m + (b.*m - a.*m) * tx;
                    const float bot = c.*m + (d.*m - c.*m) * tx;
                    return top + (bot - top) * ty;
                };
                s = {mix(&Rgba::r), mix(&Rgba::g), mix(&Rgba::b), mix(&Rgba::a)};
            }
            const std::size_t i = (static_cast<std::size_t>(y) * w + x) * 4;
            const float la = lottie[i + 3] / 255.f;
            const float inv = 1.f - la;
            const float o[4] = {lottie[i] / 255.f + s.r * inv, lottie[i + 1] / 255.f + s.g * inv,
                                lottie[i + 2] / 255.f + s.b * inv, la + s.a * inv};
            for (int k = 0; k < 4; ++k)
                out[i + k] = static_cast<std::uint8_t>(
                    std::lround(std::clamp(o[k], 0.f, 1.f) * 255.f));
        }
    }
}

}  // namespace lottie
