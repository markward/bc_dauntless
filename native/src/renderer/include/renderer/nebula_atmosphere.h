// native/src/renderer/include/renderer/nebula_atmosphere.h
#pragma once

#include <cmath>
#include <vector>

#include <glm/glm.hpp>

namespace renderer::atmosphere {

/// A star-centred radial profile: distance-from-star rows of nebula density
/// (0-1, linear between rows, last row persists outward), plus the derived
/// scattering coefficient and the two colours the marcher composites.
struct RadialProfile {
    std::vector<float> r;
    std::vector<float> nebula;
    float k_sys = 0.0f;
    float star_radius = 0.0f;
    glm::vec3 cloud_rgb{1.0f};
    glm::vec3 star_rgb{1.0f};
};

/// Look/tuning knobs shared by the reference marcher and the shader that
/// samples its table.
struct LookParams {
    float g = 0.6f;
    float floor = 0.03f;
    float scatter = 1.0f;
    float far_gu = 1800000.0f;
};

/// Result of marching one ray segment: the light that survives from the far
/// end of the segment (transmittance) and the light gathered along the way
/// (inscatter), both per-channel.
struct Segment {
    glm::vec3 transmittance{1.0f};
    glm::vec3 inscatter{0.0f};
};

/// Row-major far-field table: cell `[mu_index * kTableR + r_index]`.
struct Table {
    std::vector<glm::vec3> transmittance;
    std::vector<glm::vec3> inscatter;
};

inline constexpr int kRadialTexels = 4096;
inline constexpr int kTableR = 256;
inline constexpr int kTableMu = 128;

/// `nebula(r)`: linear between rows, clamped to the first row below it and
/// persisting the last row outward.
float density(const RadialProfile& p, float r);

/// `k_sys · ∫_{star_radius}^{r} nebula` — 0 for r ≤ star_radius.
float tau_star(const RadialProfile& p, float r);

/// Henyey-Greenstein phase function, normalised over the sphere.
float hg(float g, float cos_theta);

/// CPU truth: march from a point at radius r0, direction with cosine mu to
/// the outward radial, for max_dist or until the ray leaves the far sphere
/// or hits the star.
Segment reference_march(const RadialProfile& p, const LookParams& look,
                         float r0, float mu, float max_dist, int steps);

/// u -> r and r -> u for the far-field table's non-linear radius axis: more
/// texels near the star, where density and curvature change fastest.
float radius_of_u(float u, float far_gu);
float u_of_radius(float r, float far_gu);

/// kRadialTexels samples of (density, tau_star) at radius_of_u(i/(N-1)) —
/// the per-system texture the shader reads directly.
std::vector<glm::vec2> build_radial_texels(const RadialProfile& p, const LookParams& look);

/// Builds the kTableR x kTableMu far-field table: each cell is
/// reference_march from radius_of_u(i/(R-1)) toward mu_j = -1 + 2j/(Mu-1),
/// out to infinity.
Table build_table(const RadialProfile& p, const LookParams& look);

/// Composes two adjoining segments (near then far) into the segment for the
/// whole ray.
Segment compose(const Segment& near, const Segment& far);

/// Recovers the finite segment between two points on the same ray from two
/// to-infinity segments cast from each point (from_a is nearer the eye).
Segment finite(const Segment& from_a, const Segment& from_b);

}  // namespace renderer::atmosphere
