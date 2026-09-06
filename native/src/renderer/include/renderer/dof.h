// native/src/renderer/include/renderer/dof.h
#pragma once

#include <algorithm>

namespace renderer {

/// Depth-of-field parameters, pushed whole from Python each frame.
///
/// EVERY field here is authored in engine/cameras/dof.py and arrives as a
/// uniform. There is deliberately no C++ default that means anything: the
/// values below exist only so a default-constructed DofParams is inert.
/// Adding a "tuned default" here would create a second home for a number that
/// must have exactly one -- see the spec's Tuning ergonomics section.
struct DofParams {
    float focus_gu        = 0.0f; ///< distance to the focus subject, GU
    float blend           = 0.0f; ///< 0..1 engage ramp; 0 == pass is skipped
    float near_strength   = 0.0f; ///< foreground defocus gain
    float far_strength    = 0.0f; ///< background defocus gain, pre-ceiling
    float far_ceiling     = 0.0f; ///< hard cap on far-field CoC
    float max_radius_frac = 0.0f; ///< max blur radius / screen height
};

/// Convert a [0,1] depth-buffer value to a view distance in game units.
///
/// Standard OpenGL perspective with glDepthRange left at its default. The
/// result is always in [near_gu, far_gu] for a well-formed projection.
inline float linear_depth_gu(float d, float near_gu, float far_gu) {
    const float ndc = 2.0f * d - 1.0f;
    return (2.0f * near_gu * far_gu)
         / (far_gu + near_gu - ndc * (far_gu - near_gu));
}

/// Signed circle of confusion, in [-1, far_ceiling].
///
/// Negative is the near field (between the camera and the subject), positive
/// the far field. The sign exists only so the two sides can be tuned
/// separately; the blur radius uses the magnitude.
///
/// This is a real thin lens: `1 - focus/z` is zero at the focus distance,
/// grows without bound toward the camera, and saturates at 1 as z goes to
/// infinity. That single form is why the design carries no near/far RANGE
/// constants -- focus on a 4 GU torpedo is shallow and focus on a ship 200 GU
/// out is deep, both falling out of the same expression.
///
/// MIRRORED IN shaders/dof.frag -- the two must agree. dof_pass_test.cc pins
/// the starfield threshold against this implementation; if you change the
/// curve here, change it there in the same commit.
inline float coc_from_depth(float d, float near_gu, float far_gu,
                            const DofParams& p) {
    // No subject: the thin-lens term would degenerate to 1.0 and blur the
    // whole frame at the ceiling. The host also skips the pass when blend is
    // 0, but this keeps the function itself total.
    if (p.focus_gu <= 0.0f) return 0.0f;

    const float z = linear_depth_gu(d, near_gu, far_gu);
    if (z <= 0.0f) return 0.0f;              // guard against invalid caller args

    // The backdrop pass draws the sky with glDepthMask(GL_FALSE), so sky
    // pixels never write depth and hold the clear value. Testing the
    // LINEARIZED distance rather than d >= 0.999999 keeps this correct even
    // if someone later calls glClearDepth with something other than 1.0.
    // At far=5000 the threshold is 4900 GU (857 km) -- no scene geometry is
    // ever that distant.
    if (z >= far_gu * 0.98f) return 0.0f;

    const float dd = 1.0f - p.focus_gu / z;
    return (dd < 0.0f) ? std::max(dd * p.near_strength, -1.0f)
                       : std::min(dd * p.far_strength,   p.far_ceiling);
}

}  // namespace renderer
