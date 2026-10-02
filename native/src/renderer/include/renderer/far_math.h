// native/src/renderer/include/renderer/far_math.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md) pure math.
#pragma once
#include <cstdint>
#include <glm/glm.hpp>

namespace renderer::far {

// Spec §1 thresholds, in framebuffer pixels of on-screen radius.
struct TierDials { float imp_hi = 16.0f, imp_lo = 12.0f, speck_hi = 2.0f,
                   speck_lo = 1.5f, p_min = 0.25f; };

enum class Kind : std::uint8_t {
    Explicit,            // a flagged mission/breakup rock with an impostor atlas
    ExplicitNoImpostor,  // a flagged rock without one (stock BC mesh)
};

// How much of each representation draws. Above p_min the three sum to 1.
struct TierWeights { float mesh = 0.0f, impostor = 0.0f, speck = 0.0f; };

TierWeights tier_weights(float p, Kind k, const TierDials& d);

// k of the spec: on-screen radius (px) = r * k / distance. Same formula as
// MinorField::build_bins' px_per_gu.
inline float pixels_per_gu(const glm::mat4& proj, float viewport_h) {
    return proj[1][1] * 0.5f * viewport_h;
}

// Disk-mean of max(N.L, 0) over a Lambert sphere's visible disk, for the
// phase angle alpha (sun-rock-eye), given cos(alpha).
float lambert_sphere_phase(float cos_alpha);

// pdf ∝ r^-q on [r_min, r_max].
struct PowerLaw { float r_min = 0.05f, r_max = 0.7f, q = 2.5f; };
float power_law_cdf(const PowerLaw& pl, float r);
// ∫ π r² f(r) dr over [r_min, min(r_cut, r_max)], f the normalised pdf.
float cross_section_below(const PowerLaw& pl, float r_cut);
inline float mean_cross_section(const PowerLaw& pl) { return cross_section_below(pl, pl.r_max); }

}  // namespace renderer::far
