#pragma once
#include <cstdint>
#include <memory>
#include <glm/glm.hpp>
#include <renderer/shader.h>
namespace renderer {

/// Camera motion blur via depthless fixed-distance reprojection: each pixel's
/// view ray is placed at a fixed distance and reprojected through the previous
/// frame's view-projection to derive a screen-space motion vector, then color
/// is averaged along it. Reuses the fullscreen-triangle vertex shader
/// (resolve.vert). Runs after SMAA and before filmic, exterior view only.
class MotionBlurPass {
public:
    MotionBlurPass();
    ~MotionBlurPass();
    MotionBlurPass(const MotionBlurPass&) = delete;
    MotionBlurPass& operator=(const MotionBlurPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` into `dst_fbo`
    /// (0 = backbuffer), viewport `fw`x`fh`. `inv_proj` = inverse(proj),
    /// `cam_rot` = camera view->world rotation, `cam_pos` = camera world pos,
    /// `prev_viewproj` = previous frame proj*view. Disables cull/depth/blend
    /// and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t dst_fbo, int fw, int fh,
              const glm::mat4& inv_proj, const glm::mat3& cam_rot,
              const glm::vec3& cam_pos, const glm::mat4& prev_viewproj);
private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};
}  // namespace renderer
