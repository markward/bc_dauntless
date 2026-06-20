#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

/// SMAA 1x post-process anti-aliasing: three fullscreen passes
/// (edge detection -> blend-weight calc -> neighborhood blend) over a
/// tonemapped LDR color texture. Owns two intermediate render targets
/// (edges RG8, weights RGBA8) and two lookup textures (AreaTex, SearchTex).
/// Sits in the post chain as the final anti-aliasing stage.
class SmaaPass {
public:
    SmaaPass();
    ~SmaaPass();
    SmaaPass(const SmaaPass&) = delete;
    SmaaPass& operator=(const SmaaPass&) = delete;

    /// Run SMAA over `ldr_color_tex` and write the result into `dest_fbo`
    /// (0 = backbuffer). `fw`,`fh` are the framebuffer pixel dims. Resizes
    /// internal targets as needed. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t ldr_color_tex, std::uint32_t dest_fbo, int fw, int fh);

private:
    void resize(int w, int h);   // (re)alloc edges + weights targets
    void destroy_targets();

    std::unique_ptr<renderer::Shader> edge_;
    std::unique_ptr<renderer::Shader> weight_;
    std::unique_ptr<renderer::Shader> blend_;

    std::uint32_t vao_ = 0, vbo_ = 0;
    std::uint32_t area_tex_ = 0, search_tex_ = 0;
    std::uint32_t edges_fbo_ = 0,   edges_tex_ = 0;
    std::uint32_t weights_fbo_ = 0, weights_tex_ = 0;
    int width_ = 0, height_ = 0;
};

}  // namespace renderer
