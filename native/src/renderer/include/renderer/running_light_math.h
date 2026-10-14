// native/src/renderer/include/renderer/running_light_math.h
#pragma once

namespace renderer {

/// Blink alpha in [0,1] for a ship running light at game time `t` (seconds).
/// duration <= 0, period <= 0, non-finite inputs, or duration >= period => 1
/// (always on). Otherwise the light is on for `duration` seconds out of every
/// `period`, with linear ramps of 0.1*duration at each end (BC's alpha-key
/// spacing, on the mod authors' timescale -- spec §3 explains why BC's own
/// D/P^2 loop is not reproduced).
float running_light_blink_alpha(float t, float period, float duration, float phase);

/// Sprite DIAMETER in GU: max(size * size_gu_per_radius, min_px pixels at
/// `distance`). proj11 = proj[1][1] (1 / tan(fov_y/2)). A degenerate viewport
/// or projection returns the world size alone.
float running_light_world_size(float size, float size_gu_per_radius, float min_px,
                               float distance, float proj11, int viewport_h);

}  // namespace renderer
