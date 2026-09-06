// native/src/renderer/include/renderer/lighting.h
#pragma once

#include <algorithm>
#include <cmath>
#include <glm/glm.hpp>

namespace renderer {

/// Map BC's normalized glossiness [0,1] to a Blinn-Phong exponent.
///
/// BC NIFs author NiMaterialProperty.glossiness in a normalized [0,1]
/// range (corpus values: 0.000, 0.120, 0.250, 0.300, with a single 4.0
/// outlier — not Phong exponents). This function remaps to a usable
/// exponent. The chosen mapping is linear into [48, 1536]:
///
///   gloss=0.12 -> 226.56   gloss=0.25 -> 420.0
///   gloss=0.30 -> 494.4    gloss=1.00 -> 1536.0
///
/// The range was tuned interactively against the Galaxy and Keldon
/// spec maps. Lower exponents produced visibly soft, almost-diffuse
/// shoulders; the chosen curve gives the tight panel highlights that
/// read as "specular" on Cardassian and Federation hulls.
///
/// To A/B-compare alternate curves, swap the body and re-run the build.
/// The pinned values in lighting_test.cc must be updated in the same
/// commit so the test documents the deliberate change.
///
/// Alternates considered:
///   gentle [4, 128]:         4.0f + 124.0f * g
///   D3D-fixed-function era:  2.0f + 254.0f * g   (range [2, 256])
///   exp2 mapping:            std::pow(2.0f, g * 10.0f) (range [1, 1024])
inline float glossiness_to_specular_power(float g) {
    g = std::clamp(g, 0.0f, 1.0f);
    return 48.0f + 1488.0f * g;
}

// Fresnel rim strength is a per-instance value (Instance::rim_strength),
// authored by the hardpoint stats' 'SpecularCoef' key with a fixed default —
// it is no longer derived from material specular/glossiness (the old
// rim_strength_from_material lived here).

/// One directional-ambient gradient: an axis and how strongly to apply it.
/// strength == 0 means "no gradient" and dir_ws is then meaningless.
struct AmbientGradient {
    glm::vec3 dir_ws{0.0f, 1.0f, 0.0f};
    float     strength = 0.0f;
};

/// Derive the ambient gradient axis from every directional light in the set.
///
/// Deliberately NOT "the direction of light 0": sets can author up to
/// MAX_DIRECTIONALS (4) lights, so keying off one would be wrong in any
/// multi-star system. The luminance-weighted vector sum
///
///     D = sum( normalize(dirs[i]) * luminance(colors[i]) )
///
/// handles every arrangement without a special case. Coherence
/// |D| / sum(luminance) is 1 when the lights agree and 0 when they cancel,
/// so two opposed equal stars produce a flat ambient BY CONSTRUCTION -- which
/// is correct, not a fallback: with light from both sides there is no shadow
/// side to fill.
///
/// `dirs_to_light` point TOWARD the light, matching Lighting::directional_dir_ws.
/// Zero-length directions are skipped (normalize() on one yields NaN, which
/// would poison every fragment).
inline AmbientGradient ambient_gradient_from_lights(
        const glm::vec3* dirs_to_light, const glm::vec3* colors,
        int count, float max_strength) {
    AmbientGradient out;
    out.strength = 0.0f;
    const float budget = std::clamp(max_strength, 0.0f, 1.0f);
    if (dirs_to_light == nullptr || colors == nullptr || count <= 0 ||
        budget <= 0.0f) {
        return out;
    }

    glm::vec3 sum(0.0f);
    float total_lum = 0.0f;
    for (int i = 0; i < count; ++i) {
        const float len2 = glm::dot(dirs_to_light[i], dirs_to_light[i]);
        if (len2 < 1e-12f) continue;            // zero-vector guard
        const float lum = 0.2126f * colors[i].r
                        + 0.7152f * colors[i].g
                        + 0.0722f * colors[i].b;
        if (lum <= 0.0f) continue;
        sum += (dirs_to_light[i] / std::sqrt(len2)) * lum;
        total_lum += lum;
    }
    if (total_lum <= 0.0f) return out;          // all black: no divide by zero

    const float mag = std::sqrt(glm::dot(sum, sum));
    if (mag < 1e-6f) return out;                // perfectly opposed: flat
    out.dir_ws  = sum / mag;
    // The clamp is NOT dead code, even though the triangle inequality says
    // |sum| <= total_lum in exact arithmetic (each term has magnitude ==
    // its luminance, since dirs_to_light[i]/sqrt(len2) is meant to be unit
    // length). In float it is only APPROXIMATELY unit length -- sqrt(len2)
    // is itself rounded -- so mag/total_lum can land at 1 + 1ulp, pushing
    // out.strength marginally ABOVE the caller's requested budget. (An
    // earlier version of this comment said "negative", which is wrong:
    // budget, mag and total_lum are all non-negative, so no path here
    // produces a negative product.) Leave the clamp; a prior review called
    // it dead by the exact-arithmetic argument, and that argument does not
    // hold in float.
    out.strength = budget * std::clamp(mag / total_lum, 0.0f, 1.0f);
    return out;
}

}  // namespace renderer
