// native/src/renderer/include/renderer/lighting.h
#pragma once

#include <algorithm>
#include <cmath>

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

}  // namespace renderer
