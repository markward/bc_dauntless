// native/src/renderer/include/renderer/nacelle_region.h
#pragma once

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// A fore/aft capsule fitted to one warp nacelle, in body/model units.
/// `axis` is unit-length; `aft <= 0 <= fore` are signed projections along
/// `axis` relative to `center`. `dim_target`/`disable_time` are live render
/// state, not produced by the fit (default to "full glow, never disabled").
struct NacelleRegion {
    glm::vec3 center{0.0f};
    glm::vec3 axis{0.0f, 1.0f, 0.0f};
    float     radius = 0.0f;       // lateral capture radius (model units)
    float     aft    = 0.0f;       // min projection (<= 0)
    float     fore   = 0.0f;       // max projection (>= 0)
    float     dim_target   = 1.0f; // 1 = full glow, ~0.08 = disabled
    float     disable_time = -1.0f; // game-time secs of last disable edge; <0 = never
    bool      active = false;
};

/// Widen factor applied to the hardpoint radius to catch the full nacelle
/// cross-section (spec §Approach.1).
inline constexpr float kNacelleRadiusWiden = 1.25f;
/// Fallback half-length as a multiple of the (widened) radius when the
/// lateral capture is degenerate (spec §Approach.1 fallback).
inline constexpr float kNacelleFallbackHalfLenFactor = 2.5f;
/// Minimum captured vertices for the mesh fit to be trusted; below this we
/// use the formula fallback.
inline constexpr int kNacelleMinCaptured = 8;

/// Fit a nacelle capsule. Walks the model's retained CPU vertices into body
/// space (same node-transform composition as compute_model_aabb), keeps those
/// within `radius * kNacelleRadiusWiden` laterally of the `axis` line through
/// `center`, and sets aft/fore to the min/max axial projection of the kept
/// vertices. Falls back to +/- kNacelleFallbackHalfLenFactor * widened radius
/// when fewer than kNacelleMinCaptured vertices are captured (or the model has
/// no CPU data). `axis` is assumed unit-length (model +Y by default).
NacelleRegion compute_nacelle_region(const assets::Model& model,
                                     const glm::vec3& center,
                                     const glm::vec3& axis,
                                     float radius);

}  // namespace renderer
