// native/src/renderer/include/renderer/atmosphere_math.h
#pragma once

#include <vector>

#include <glm/glm.hpp>

namespace renderer {
struct SunDescriptor;
}  // namespace renderer

// GL-free planet-atmosphere maths: a thin exponential-density shell around a
// planet, single-scattering approximation. The shader `atmosphere.frag`
// mirrors every function here line for line, so these are the numbers the
// test suite pins.
namespace renderer::planet_atmo {

inline constexpr int   kViewSamples = 8;
inline constexpr int   kSunSamples  = 6;
inline constexpr float kOpaqueTau   = 1.0e4f;   // sun ray blocked by the planet

/// A spherical planet with a concentric atmosphere shell out to r_top.
struct Shell {
    glm::vec3 center;
    float r_planet;
    float r_top;
};

/// Look/tuning knobs for one planet's atmosphere.
struct Params {
    /// Linear RGB RELATIVE per-channel Rayleigh scattering strength (not a
    /// final tint): normalised by its strongest channel (beta_rayleigh).
    glm::vec3 color;
    float thickness;
    float density;
    /// Grey Mie strength: Mie extinction = sigma * mie in every channel.
    float mie = 0.2f;
};

/// The span of `t` along a ray where it is inside the atmosphere shell (and
/// not yet past the opaque depth or the planet surface).
struct Span {
    bool hit = false;
    float t0 = 0.0f;
    float t1 = 0.0f;
};

/// Intersects [origin, origin + dir*t_max] with the atmosphere shell,
/// clipped at the planet surface (whichever the ray hits first) and at
/// t_max (the scene's opaque depth along this ray).
///
/// t_max is taken as given: the CALLER owns depth-buffer handling. The shader
/// (atmosphere.frag main) ignores a scene depth within one depth quantum of
/// the analytic planet hit (the planet's own quantised surface) and marches
/// to the planet instead; a twin comparison must hand in the march end the
/// shader would actually use.
Span air_span(const Shell& s, glm::vec3 origin, glm::vec3 dir, float t_max);

/// The shell's exponential falloff scale height: 0.25 * (r_top - r_planet).
float scale_height(const Shell& s);

/// The shell's base extinction/scattering coefficient: density / (r_top - r_planet).
/// Rayleigh per channel is sigma * beta_rayleigh(p); Mie is sigma * p.mie.
float sigma(const Shell& s, const Params& p);

/// Normalised density at a point: exp(-h/H), h = max(|p - center| - r_planet, 0).
float rho(const Shell& s, glm::vec3 p);

/// Per-channel optical depth from x toward the sun (direction sun_dir,
/// toward the light): kOpaqueTau in every channel if the planet blocks the
/// ray, else a kSunSamples midpoint quadrature of rho out to the shell exit
/// times the total extinction sigma * (beta_rayleigh + mie).
glm::vec3 sun_tau(const Shell& s, const Params& p, glm::vec3 x, glm::vec3 sun_dir);

/// p.color / max(p.color.r, g, b): the strongest channel scatters at 1.
/// An all-zero (or non-finite) colour gives zero, never NaN.
glm::vec3 beta_rayleigh(const Params& p);

/// Rayleigh phase: 3/(16*pi) * (1 + c^2).
float rayleigh_phase(float cos_theta);

/// Mie phase: Henyey-Greenstein with g = 0.76 (forward lobe).
float mie_phase(float cos_theta);

/// Single-scattering in-scattered light along a view ray: chromatic
/// Rayleigh (x rayleigh_phase) plus grey Mie (x mie_phase), both attenuated
/// by the per-channel total extinction along the view and sun paths. There
/// is no final multiply by p.color -- the colour emerges from the
/// coefficients. The caller multiplies by intensity and the sun's colour.
glm::vec3 in_scatter(const Shell& s, const Params& p, glm::vec3 origin, glm::vec3 dir,
                      float t_max, glm::vec3 sun_dir);

/// Unit direction from `center` toward the nearest sun in `suns`, or toward
/// `fallback_dir_ws` (normalised) when `suns` is empty or degenerate.
glm::vec3 sun_dir_for(glm::vec3 center, const std::vector<SunDescriptor>& suns,
                      glm::vec3 fallback_dir_ws);

}  // namespace renderer::planet_atmo
