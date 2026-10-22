// native/src/renderer/include/renderer/warp_in_flash_shape.h
#pragma once

#include <glm/glm.hpp>

namespace renderer {

// Warp-in flash look (warp-in spec 6.3). Procedural, no textures. These
// functions are the CPU twin of shaders/warp_in_flash.frag: the constants and
// the shape terms MUST match the shader, which mirrors each constant by name
// (warp_in_flash_shape_test pins the text). Distances are in units of the
// flash radius; t = age / lifetime. Every term is 0 for t >= 1.

/// Core flare rise time (fraction of life) — the core peaks here.
inline constexpr float kCoreRise = 0.08f;
/// Core gaussian falloff: exp(-kCoreFalloff * (r / w)^2).
inline constexpr float kCoreFalloff = 3.0f;
/// Default ring fade-in time (fraction of life): WarpInFlashParams::ring_rise.
inline constexpr float kRingRise = 0.05f;
/// Ring band half-width, as a fraction of ring_radii.
inline constexpr float kRingBand = 0.12f;
/// Default fraction of life by which the streak has fully retracted:
/// WarpInFlashParams::streak_end.
inline constexpr float kStreakEnd = 0.9f;
/// Streak thickness, as a fraction of core_radii.
inline constexpr float kStreakThickness = 0.08f;

/// Live-tunable look (the "warp in" dial group, engine/appc/warp_in_dials.py).
/// Sizes are multiples of the flash radius.
struct WarpInFlashParams {
    float core_radii = 1.5f;
    float streak_radii = 8.0f;
    float ring_radii = 3.0f;
    float intensity = 4.0f;
    glm::vec3 tint{0.75f, 0.85f, 1.0f};
    /// Timing, fractions of the life (spec 6.3 "streak and ring timing").
    float streak_end = kStreakEnd;
    float ring_rise = kRingRise;
};

/// Hot point at the exit point: flares fast (peak at kCoreRise), fades over
/// the life. `r` = distance from the core. MUST match shaders/warp_in_flash.frag.
float warp_in_core(float r, float t, const WarpInFlashParams& p);

/// Brief ring expanding to ring_radii, fading as it grows; fades in over
/// p.ring_rise. Drawn in the plane perpendicular to the forward axis; `r` =
/// distance from the core in that plane. MUST match shaders/warp_in_flash.frag.
float warp_in_ring(float r, float t, const WarpInFlashParams& p);

/// Thin line along the flash's forward axis, one-sided (forward of the core):
/// stretches out early, retracts by p.streak_end. `along` = distance forward of
/// the core, `across` = distance off the axis. MUST match
/// shaders/warp_in_flash.frag.
float warp_in_streak(float along, float across, float t, const WarpInFlashParams& p);

}  // namespace renderer
