// native/src/renderer/include/renderer/glow_region.h
#pragma once

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// A fore/aft capsule fitted to one glow region (capsule or sphere), in
/// body/model units. `axis` is unit-length; `aft <= 0 <= fore` are signed
/// projections along `axis` relative to `center`. `dim_target`/`disable_time`
/// are live render state, not produced by the fit (default to "full glow,
/// never disabled").
struct GlowRegion {
    glm::vec3 center{0.0f};
    glm::vec3 axis{0.0f, 1.0f, 0.0f};
    float     radius = 0.0f;       // lateral capture radius (model units)
    float     aft    = 0.0f;       // min projection (<= 0)
    float     fore   = 0.0f;       // max projection (>= 0)
    float     dim_target   = 1.0f; // 1 = full glow, ~0.08 = disabled
    float     disable_time = -1.0f; // game-time secs of last disable edge; <0 = never
    bool      active = false;
};

/// Widen factor applied to the hardpoint radius to gather candidate vertices
/// and bound the axial fit (spec §Approach.1).
inline constexpr float kGlowCapsuleRadiusWiden = 1.25f;
/// Lateral radius of the RENDERED capsule, as a fraction of the widened
/// gameplay radius. The hardpoint radius is the damage sphere — wide enough to
/// reach across the spine into the secondary hull — so the visible capsule uses
/// a nacelle-scale fraction of it: wide enough to cover the nacelle's glow band,
/// short of the hull. Tuned by eye on real hulls.
inline constexpr float kGlowCapsuleRenderRadiusFrac = 0.3f;
/// Fallback half-length as a multiple of the (widened) radius when the
/// lateral capture is degenerate (spec §Approach.1 fallback).
inline constexpr float kGlowCapsuleFallbackHalfLenFactor = 2.5f;
/// Minimum captured vertices for the mesh fit to be trusted; below this we
/// use the formula fallback.
inline constexpr int kGlowCapsuleMinCaptured = 8;
/// Lateral radius (as a fraction of the widened radius) used to select which
/// captured vertices define the fore/aft extent. The hardpoint radius is the
/// gameplay damage sphere — several times wider than the nacelle's visual
/// cross-section — so a tube that wide reaches sideways into the saucer/hull
/// and the axial fit stretches across the whole ship. Fitting against only the
/// vertices that hug the nacelle axis (this tight fraction) drops the
/// laterally-offset saucer, which in turn opens the axial gap that the gap-stop
/// below trims. The full (wide) radius is still used for the RENDERED capsule
/// so the shader covers the nacelle's glow width. Tuned by eye on real hulls.
inline constexpr float kGlowCapsuleFitRadiusFrac = 0.2f;
/// Axial gap (as a fraction of the widened radius) that ends the contiguous
/// vertex run when fitting aft/fore. After tight-radius selection the nacelle
/// and the saucer form separate axial clusters; growth from the hardpoint stops
/// at the first axial gap wider than kGlowCapsuleGapFrac * widened_radius,
/// keeping only the nacelle's local run. Tuned large enough not to split a
/// dense nacelle, small enough to separate it from the saucer cluster.
inline constexpr float kGlowCapsuleGapFrac = 0.85f;

/// Fit a nacelle capsule. Walks the model's retained CPU vertices into body
/// space (same node-transform composition as compute_model_aabb), keeps those
/// within `radius * kGlowCapsuleRadiusWiden` laterally of the `axis` line through
/// `center`, and sets aft/fore to the min/max axial projection of the kept
/// vertices. Falls back to +/- kGlowCapsuleFallbackHalfLenFactor * widened radius
/// when fewer than kGlowCapsuleMinCaptured vertices are captured (or the model has
/// no CPU data). `axis` is assumed unit-length (model +Y by default).
GlowRegion compute_capsule_region(const assets::Model& model,
                                  const glm::vec3& center,
                                  const glm::vec3& axis,
                                  float radius);

/// Build a sphere glow region: the capsule test degenerates to a sphere when
/// axis == (0,0,0) and aft == fore == 0 (then the axial bound 0<=0<=0 always
/// holds and the lateral test becomes dot(d,d) > radius^2). No vertex fit and
/// no widen — impulse/sensor glow is a compact spot, not a long tube. center /
/// radius are in body/model units.
GlowRegion add_sphere_region(const glm::vec3& center, float radius);

}  // namespace renderer
