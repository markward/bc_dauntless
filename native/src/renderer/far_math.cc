#include "renderer/far_math.h"
#include <algorithm>
#include <cmath>

namespace renderer::far {
namespace {
float sat(float x) { return std::clamp(x, 0.0f, 1.0f); }
// Linear ramp from lo (0) to hi (1), clamped. A zero-width band (hi == lo,
// reachable live by stepping the dev dials) would otherwise divide by zero
// and NaN would sail straight through std::clamp; fall back to a hard step
// (p >= hi => 1, else 0) instead.
float band(float p, float lo, float hi) {
    if (hi == lo) return p >= hi ? 1.0f : 0.0f;
    return sat((p - lo) / (hi - lo));
}
// ∫ r^e dr from a to b (e may be -1).
double int_pow(double a, double b, double e) {
    if (std::fabs(e + 1.0) < 1e-6) return std::log(b / a);
    return (std::pow(b, e + 1.0) - std::pow(a, e + 1.0)) / (e + 1.0);
}
}  // namespace

TierWeights tier_weights(float p, Kind k, const TierDials& d) {
    TierWeights w;
    if (!(p >= d.p_min)) return w;                         // haze / culled (NaN-safe)
    const float f = band(p, d.imp_lo, d.imp_hi);     // 1 = mesh
    const float g = band(p, d.speck_lo, d.speck_hi); // 1 = not speck
    switch (k) {
    case Kind::Explicit:
        w.mesh = f; w.impostor = (1.0f - f) * g; w.speck = 1.0f - g; break;
    case Kind::ExplicitNoImpostor:
        w.mesh = g; w.speck = 1.0f - g; break;
    case Kind::ProceduralMajor:
        w.impostor = (1.0f - f) * g; w.speck = 1.0f - g; break;
    case Kind::ProceduralMinor:
        w.speck = 1.0f - g; break;
    }
    return w;
}

float lambert_sphere_phase(float cos_alpha) {
    const float c = std::clamp(cos_alpha, -1.0f, 1.0f);
    const float a = std::acos(c);
    return (2.0f / (3.0f * 3.14159265f)) * (std::sin(a) + (3.14159265f - a) * c);
}

float power_law_cdf(const PowerLaw& pl, float r) {
    if (r <= pl.r_min) return 0.0f;
    if (r >= pl.r_max) return 1.0f;
    const double e = -static_cast<double>(pl.q);
    return static_cast<float>(int_pow(pl.r_min, r, e) / int_pow(pl.r_min, pl.r_max, e));
}

float cross_section_below(const PowerLaw& pl, float r_cut) {
    const double hi = std::min(r_cut, pl.r_max);
    if (hi <= pl.r_min) return 0.0f;
    const double e = -static_cast<double>(pl.q);
    const double norm = int_pow(pl.r_min, pl.r_max, e);
    return static_cast<float>(3.14159265358979 * int_pow(pl.r_min, hi, e + 2.0) / norm);
}

}  // namespace renderer::far
