// native/src/lottie/src/lottie_clip.cc
#include "lottie/lottie_clip.h"

#include <thorvg.h>

#include <algorithm>
#include <cstring>
#include <mutex>

#include "assets/file_bytes.h"

namespace lottie {

void ensure_thorvg_initialised() {
    static std::once_flag once;
    std::call_once(once, [] { tvg::Initializer::init(0); });
}

struct LottieClip::Impl {
    std::unique_ptr<tvg::Animation> animation;
    std::unique_ptr<tvg::SwCanvas> canvas;  // owns the pushed picture's slot
    std::vector<std::uint32_t> pixels;      // canvas target
    std::uint32_t target_w = 0;
    std::uint32_t target_h = 0;
    float canvas_w = 0.f;
    float canvas_h = 0.f;
    float total = 0.f;
    float duration = 0.f;

    ~Impl() {
        // Canvas first: it references the picture the animation owns.
        canvas.reset();
        animation.reset();
    }
};

LottieClip::LottieClip() : impl_(std::make_unique<Impl>()) {}
LottieClip::~LottieClip() = default;

namespace {
void set_error(std::string* error, const char* msg) {
    if (error) *error = msg;
}
}  // namespace

std::unique_ptr<LottieClip> LottieClip::load(const std::filesystem::path& file,
                                             std::string* error) {
    ensure_thorvg_initialised();

    auto bytes = assets::read_binary_file(file);
    if (!bytes) {
        set_error(error, "unreadable file");
        return nullptr;
    }

    std::unique_ptr<LottieClip> clip(new LottieClip());
    Impl& m = *clip->impl_;
    m.animation.reset(tvg::Animation::gen());
    tvg::Picture* pic = m.animation->picture();
    if (!pic || pic->load(reinterpret_cast<const char*>(bytes->data()),
                          static_cast<std::uint32_t>(bytes->size()), "lottie+json",
                          nullptr, true) != tvg::Result::Success) {
        set_error(error, "not a Lottie animation");
        return nullptr;
    }
    pic->size(&m.canvas_w, &m.canvas_h);
    if (!(m.canvas_w > 0.f) || !(m.canvas_h > 0.f)) {
        set_error(error, "zero canvas size");
        return nullptr;
    }
    m.total = m.animation->totalFrame();
    m.duration = m.animation->duration();
    if (!(m.total > 0.f) || !(m.duration > 0.f)) {
        set_error(error, "no frames");
        return nullptr;
    }
    return clip;
}

float LottieClip::canvas_width() const { return impl_->canvas_w; }
float LottieClip::canvas_height() const { return impl_->canvas_h; }
float LottieClip::total_frames() const { return impl_->total; }
float LottieClip::duration_s() const { return impl_->duration; }
float LottieClip::fps() const { return impl_->total / impl_->duration; }

bool LottieClip::render(float frame, std::uint32_t w, std::uint32_t h,
                        std::vector<std::uint8_t>& out_premul_rgba) {
    Impl& m = *impl_;
    if (w == 0 || h == 0) return false;

    tvg::Picture* pic = m.animation->picture();
    if (!m.canvas) {
        m.canvas.reset(tvg::SwCanvas::gen());
        if (!m.canvas || m.canvas->add(pic) != tvg::Result::Success) {
            m.canvas.reset();
            return false;
        }
    }
    if (w != m.target_w || h != m.target_h) {
        m.pixels.assign(static_cast<size_t>(w) * h, 0u);
        if (m.canvas->target(m.pixels.data(), w, w, h,
                             tvg::ColorSpace::ABGR8888) != tvg::Result::Success)
            return false;
        m.target_w = w;
        m.target_h = h;
        pic->size(static_cast<float>(w), static_cast<float>(h));
    }
    // Same-frame requests report InsufficientCondition; the picture is still valid.
    m.animation->frame(std::clamp(frame, 0.f, m.total - 1.f));

    if (m.canvas->update() != tvg::Result::Success) return false;
    // draw(true) clears the whole target first (SwRenderer::clear).
    if (m.canvas->draw(true) != tvg::Result::Success) return false;
    if (m.canvas->sync() != tvg::Result::Success) return false;

    out_premul_rgba.resize(m.pixels.size() * 4);
    std::memcpy(out_premul_rgba.data(), m.pixels.data(), out_premul_rgba.size());
    return true;
}

}  // namespace lottie
