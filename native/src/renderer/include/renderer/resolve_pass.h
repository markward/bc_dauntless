#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

class ResolvePass {
public:
    ResolvePass();
    ~ResolvePass();
    ResolvePass(const ResolvePass&) = delete;
    ResolvePass& operator=(const ResolvePass&) = delete;
    void set_hdr_enabled(bool e) { hdr_enabled_ = e; }
    void set_bloom_strength(float s) { bloom_strength_ = s; }
    void set_warp_flash(float v) { warp_flash_ = v; }

    /// Draw a fullscreen triangle sampling `hdr_color_tex` (+ `bloom_tex` when
    /// HDR is on) into the currently-bound framebuffer. Disables depth-test +
    /// blend and restores them. Caller binds the target framebuffer + viewport
    /// first. `bloom_tex` is bound to unit 1 but only sampled on the HDR-on
    /// branch; pass any valid texture handle when HDR is off (it is ignored).
    void draw(std::uint32_t hdr_color_tex, std::uint32_t bloom_tex);
private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
    bool hdr_enabled_ = true;
    float bloom_strength_ = 1.45f;  // additive bloom intensity, tuned by eye on the Galaxy scene
    float warp_flash_ = 0.0f;       // 0 = no flash (identity); set per-frame during warp
};
}  // namespace renderer
