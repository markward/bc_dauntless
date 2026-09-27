#pragma once
#include <algorithm>

namespace renderer {

/// Motion-blur shutter scale (the `u_shutter` uniform).
///
/// Shutter-angle normalisation: the motion vector is a per-FRAME displacement,
/// so a dipped framerate moves the camera further and smears harder -- blur
/// measuring frames instead of time. Scaling by ref_dt/dt restores a fixed
/// exposure duration. Clamped to 1.0 deliberately: above the reference rate
/// the physically consistent scale would be > 1 and the blur would GROW
/// relative to how it was tuned. This only ever reduces.
///
/// The result is then faded by (1 - dash_intensity), clamped to [0,1]. The
/// blur places every pixel at a fixed distance and includes camera
/// translation, so at in-system-dash speed (~167+ GU/frame) the motion vector
/// saturates across nearly the whole screen and smears the sun into a blob
/// (live finding 2026-09-27). The dash's own dust streaks carry the sense of
/// speed instead.
inline float motion_blur_shutter(double dt, double ref_dt,
                                 float dash_intensity) {
    const float frame_scale =
        (dt > 1e-6) ? static_cast<float>(std::min(ref_dt / dt, 1.0)) : 1.0f;
    const float dash = std::clamp(dash_intensity, 0.0f, 1.0f);
    return frame_scale * (1.0f - dash);
}

}  // namespace renderer
