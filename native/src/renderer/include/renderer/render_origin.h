#pragma once

// World-anchored passes under the floating render origin (system-frames spec
// §5, Plan 3 Task 6).
//
// Every Space-pass position reaches the GPU in RENDER space: view coordinates
// minus the render origin, which Python moves to the camera eye every frame.
// Most passes only ever compare positions within one frame and need nothing.
// Three kinds of state do need the origin folded back in, and these helpers
// are that folding, kept pure so it is testable without GL:
//
//   * a matrix remembered from LAST frame (motion blur, the volumetric
//     nebula's temporal history) was in last frame's render space;
//   * camera TRAVEL (the dust smear, the nebula history's reset gate) --
//     the eye itself now sits at ~0 every frame;
//   * a field keyed to ABSOLUTE world position (the dust cube's toroidal
//     wrap) -- keyed to the render-space eye it would ride with the camera.

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>

namespace renderer::render_origin {

/// Last frame's proj*view re-expressed for THIS frame's render space: a
/// static point p (this frame's render space) sat at p + (origin -
/// prev_origin) last frame. Unmoved origin: `prev_vp` itself.
inline glm::mat4 rebase_prev_viewproj(const glm::mat4& prev_vp,
                                      const glm::dvec3& prev_origin,
                                      const glm::dvec3& origin) {
    const glm::dvec3 d = origin - prev_origin;
    if (d == glm::dvec3(0.0)) return prev_vp;
    return prev_vp * glm::translate(glm::mat4(1.0f), glm::vec3(d));
}

/// How far the camera moved in the world between two frames, given each
/// frame's render-space eye and render origin. Differenced in double, so a
/// large origin loses nothing.
inline glm::vec3 eye_travel(const glm::vec3& eye, const glm::vec3& prev_eye,
                            const glm::dvec3& origin,
                            const glm::dvec3& prev_origin) {
    return glm::vec3((glm::dvec3(eye) + origin) -
                     (glm::dvec3(prev_eye) + prev_origin));
}

/// The origin reduced into [0, period) per axis, in double: what a periodic
/// field keyed to render space must subtract to be keyed to the world.
inline glm::vec3 wrap_phase(const glm::dvec3& origin, double period) {
    auto m = [period](double v) {
        double r = std::fmod(v, period);
        if (r < 0.0) r += period;
        return static_cast<float>(r);
    };
    return glm::vec3(m(origin.x), m(origin.y), m(origin.z));
}

/// The uniform a shader adds to a RENDER-space position to key a noise
/// field or a phase to the WORLD point (render point + origin). Float: at
/// 450,000 GU that is ~0.03 GU, far below any noise frequency in use.
inline glm::vec3 noise_origin(const glm::dvec3& origin) {
    return glm::vec3(origin);
}

/// For a shader phase keyed to position, sin(t + dot(p, k)): the offset to
/// add so it is the WORLD point's phase, dot(origin, k) reduced into
/// [0, 2*pi) in double. Adding float(origin) to p instead would cost the
/// phase ~0.004 rad of precision at 450,000 GU.
inline float phase_offset(const glm::dvec3& origin, const glm::vec3& k) {
    constexpr double kTwoPi = 6.283185307179586;
    double r = std::fmod(glm::dot(origin, glm::dvec3(k)), kTwoPi);
    if (r < 0.0) r += kTwoPi;
    return static_cast<float>(r);
}

}  // namespace renderer::render_origin
