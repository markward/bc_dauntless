#pragma once
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace renderer {

// Mirrors of motion_blur.frag's STRENGTH and DISTANCE_GU (a test pins them to
// the shader source).
constexpr float kMotionBlurStrength = 0.7f;
constexpr float kMotionBlurDistanceGu = 100.0f;
// The pass is skipped when no probed point moves this many pixels.
constexpr float kMotionBlurSkipPx = 0.5f;

/// Largest motion-vector length, in pixels, that motion_blur.frag would
/// produce, probed at the screen centre and the four corners (same math as the
/// shader, MAX_UV cap ignored). Returns +inf on any doubt (a point behind the
/// previous camera, or a non-finite value) so the blur is never skipped then.
inline float motion_blur_max_px(const glm::mat4& inv_proj,
                                const glm::mat3& cam_rot,
                                const glm::vec3& cam_pos,
                                const glm::mat4& prev_viewproj, float shutter,
                                int fb_w, int fb_h) {
    constexpr float inf = std::numeric_limits<float>::infinity();
    static const glm::vec2 kUv[5] = {
        {0.5f, 0.5f}, {0.0f, 0.0f}, {1.0f, 0.0f}, {0.0f, 1.0f}, {1.0f, 1.0f}};
    float worst = 0.0f;
    for (const glm::vec2& uv : kUv) {
        const glm::vec2 ndc = uv * 2.0f - 1.0f;
        const glm::vec4 vr = inv_proj * glm::vec4(ndc, 1.0f, 1.0f);
        const glm::vec3 ray_view = glm::normalize(glm::vec3(vr) / vr.w);
        const glm::vec3 world =
            cam_pos + kMotionBlurDistanceGu * (cam_rot * ray_view);
        const glm::vec4 clip_prev = prev_viewproj * glm::vec4(world, 1.0f);
        if (!(clip_prev.w > 0.0f)) return inf;  // also catches NaN
        const glm::vec2 uv_prev =
            glm::vec2(clip_prev.x, clip_prev.y) / clip_prev.w * 0.5f + 0.5f;
        const glm::vec2 mv = (uv - uv_prev) * kMotionBlurStrength * shutter;
        const float px = std::hypot(mv.x * static_cast<float>(fb_w),
                                    mv.y * static_cast<float>(fb_h));
        if (!std::isfinite(px)) return inf;
        worst = std::max(worst, px);
    }
    return worst;
}

}  // namespace renderer
