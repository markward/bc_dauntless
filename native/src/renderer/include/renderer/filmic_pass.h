#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

/// Filmic post-process: film grain + vignette + chromatic aberration over a
/// final-display-space LDR color texture. Reuses the fullscreen-triangle vertex
/// shader (resolve.vert). Runs last in the post chain (after tonemap + SMAA),
/// applied only to the exterior space view.
class FilmicPass {
public:
    FilmicPass();
    ~FilmicPass();
    FilmicPass(const FilmicPass&) = delete;
    FilmicPass& operator=(const FilmicPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` into `dest_fbo`
    /// (0 = backbuffer), setting the viewport to `fw`x`fh`. `time_seconds`
    /// animates the grain. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t dest_fbo,
              int fw, int fh, float time_seconds);
private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};
}  // namespace renderer
