#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

class FxaaPass {
public:
    FxaaPass();
    ~FxaaPass();
    FxaaPass(const FxaaPass&) = delete;
    FxaaPass& operator=(const FxaaPass&) = delete;

    /// Draw a fullscreen triangle running FXAA over `ldr_color_tex` into the
    /// currently-bound framebuffer. Caller binds the target FBO + viewport
    /// first. `fw`,`fh` are the framebuffer pixel dims (for u_inv_resolution).
    /// Disables cull/depth/blend and restores them (mirrors ResolvePass).
    void draw(std::uint32_t ldr_color_tex, int fw, int fh);

private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};

}  // namespace renderer
