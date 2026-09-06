// native/src/renderer/include/renderer/dof_pass.h
#pragma once
#include <cstdint>
#include <memory>
#include <renderer/dof.h>
#include <renderer/shader.h>

namespace renderer {

/// Depth of field over an HDR scene colour + depth pair.
///
/// Runs BEFORE bloom and the tonemap, unlike every other post pass here: a
/// defocused highlight has to still be bright when it spreads, or it reads as
/// a grey smudge instead of bokeh. Reuses the fullscreen-triangle vertex
/// shader (resolve.vert), as FilmicPass does.
///
/// Exterior space view only. The caller is expected to skip the pass entirely
/// when no subject is focused, which keeps the default deep-focus frame
/// byte-identical to the pre-DOF renderer.
class DofPass {
public:
    DofPass();
    ~DofPass();
    DofPass(const DofPass&) = delete;
    DofPass& operator=(const DofPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` (HDR colour) and
    /// `depth_tex` (the same target's depth) into `dest_fbo`, viewport
    /// `fw`x`fh`. `near_gu`/`far_gu` are the camera planes, needed to
    /// linearize depth. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t depth_tex,
              std::uint32_t dest_fbo, int fw, int fh,
              float near_gu, float far_gu, const DofParams& p);

private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};

}  // namespace renderer
