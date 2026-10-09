// native/src/renderer/include/renderer/planet_detail_noise.h
#pragma once

#include <cstdint>

#include <glm/glm.hpp>

// GL-free procedural detail noise for the planet surface-detail clipmap: a
// deterministic hash, analytic-derivative gradient noise, per-surface-type
// height fields built from it, a per-type tunable parameter table, and the
// gnomonic plane anchor the baker projects through. The bake shader (Task 6)
// mirrors every function here line for line, so these are the numbers the
// test suite pins.
namespace renderer::planet_detail {

enum class SurfaceType : int { None = 0, Rocky = 1, Desert = 2, Ice = 3, Gas = 4, Ocean = 5 };

/// Per-type look/tuning knobs. All fields except the eight listed in
/// `shape_hash`'s doc comment are display-only (never baked).
struct TypeParams {
    float base_wavelength_gu;  // octave-0 wavelength before Surface::scale
    int   max_octaves;
    float gain;                // amplitude ratio per octave
    float ridged;              // 1 = ridged multifractal, 0 = fBm
    float amplitude;           // height amplitude
    float bump;                // shading-normal tilt per unit gradient
    float albedo;              // log-luminance variation per unit height
    float roughness;           // water/sheen GGX roughness
    float roughness_var;       // A-channel modulation of roughness
    float crack_width;         // ice only: crack line half-width in noise units
    float stretch;             // gas only: latitude-frequency multiplier (bands)
    float warp;                // gas only: domain-warp strength
    float gas_rate_gups;       // gas only: peak eastward flow, GU/s
    float gas_period_s;        // gas only: two-phase period
    float coast_k;             // coast smoothstep half-width
    float coast_a;             // coast height perturbation
};

/// Factory defaults for one surface type (the calibration starting point).
TypeParams default_params(SurfaceType t);

/// Runtime-tunable copy (dev dials); starts at the defaults and persists
/// across calls until `reset_live_params`.
TypeParams& live_params(SurfaceType t);
void reset_live_params();

/// A hash of every field that changes the BAKED field (base_wavelength_gu,
/// max_octaves, gain, ridged, amplitude, crack_width, stretch, warp): the
/// pass resets the clipmap when it changes.
std::uint32_t shape_hash(const TypeParams& p);

/// Jarzynski & Olano 2020 integer hash: deterministic, mixes all three lanes.
glm::uvec3 pcg3d(glm::uvec3 v);

/// Quintic-interpolated gradient noise with analytic derivative.
/// Returns {value, d/dx, d/dy, d/dz}.
glm::vec4 noised(const glm::vec3& x, std::uint32_t seed);

/// One sampled height field: h (amplitude-scaled), its gradient d h / d q
/// with q = p_local_gu / (base_wavelength_gu * scale) — no further scale
/// factor is applied — and `a` an auxiliary [0,1] mask/variation channel
/// whose meaning is per-type (wind roughness, crack mask, cloud-phase mix, ...).
struct FieldSample { float h; glm::vec3 grad; float a; };

/// p_local_gu: planet-local position (body frame, centre removed, scaled to
/// GU). `scale` multiplies the base wavelength (Surface::scale); `octaves`
/// is the already-decided octave count for this call (see
/// `octaves_for_texel`).
FieldSample field(SurfaceType t, const TypeParams& p, const glm::vec3& p_local_gu,
                   std::uint32_t seed, float scale, int octaves);

/// Octaves whose wavelength >= 2 texels at this texel size, clamped
/// [1, max(max_octaves, 1)].
int octaves_for_texel(const TypeParams& p, float scale, float texel_gu);

/// A local tangent-plane frame anchored at `dir_local` on a sphere of
/// radius R: A is the outward normal, E/N span the tangent plane.
struct Anchor { glm::vec3 A, E, N; float R; };

/// E = normalize(cross(Z, A)); falls back to normalize(cross(A, (0,1,0)))
/// when that is near-degenerate (dir_local close to a pole). A zero-length
/// dir_local gives A = (0,0,1).
Anchor make_anchor(const glm::vec3& dir_local, float R);

/// Gnomonic (gnomonic/perspective) projection of a point near the anchor
/// onto its tangent plane. The denominator dot(p, A) is floored at 1e-6*R so
/// a point on or past the horizon stays finite (and meaningless).
glm::vec2 to_plane(const Anchor& a, const glm::vec3& p_local);

/// Inverse of `to_plane`: a point ON the sphere (|p| == a.R).
glm::vec3 from_plane(const Anchor& a, const glm::vec2& xy);

}  // namespace renderer::planet_detail
