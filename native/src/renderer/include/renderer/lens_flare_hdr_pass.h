#pragma once
#include <cstdint>
#include <memory>
namespace renderer {

class Shader;

// Image-based screen-space lens flare (John Chapman "pseudo lens flare").
// Consumes the bloom mip0 texture (blurred HDR bright buffer) and generates a
// half-resolution flare texture — ghosts + halo + chromatic dispersion — that
// ResolvePass composites additively. Occlusion is implicit: an occluded light
// is not bright in the image, so it stops flaring; no depth test needed.
class LensFlareHdrPass {
public:
    LensFlareHdrPass();
    ~LensFlareHdrPass();
    LensFlareHdrPass(const LensFlareHdrPass&) = delete;
    LensFlareHdrPass& operator=(const LensFlareHdrPass&) = delete;
    /// Generate the flare texture from bloom_mip0_tex; returns the half-res
    /// flare color texture. Rebuilds the target if fw/fh changed.
    std::uint32_t render(std::uint32_t bloom_mip0_tex, int fw, int fh);
private:
    void rebuild(int fw, int fh);
    void destroy();
    int fw_ = 0, fh_ = 0;
    std::uint32_t fbo_ = 0, tex_ = 0;   // half-res RGBA16F target
    std::uint32_t vao_ = 0, vbo_ = 0;   // fullscreen triangle
    std::unique_ptr<Shader> shader_;
};
}  // namespace renderer
