// native/src/renderer/far_field.cc
#include "renderer/far_field.h"
#include <renderer/glm_exact.h>
#include <algorithm>
#include <cmath>
#include <glm/gtc/matrix_access.hpp>

namespace renderer::far {
namespace {
// (rho, z) of x relative to the disc.
void disc_coords(const DiscSource& s, const glm::dvec3& x, double& rho, double& z) {
    const glm::dvec3 d = x - s.centre;
    const glm::dvec3 n(s.normal);
    z = glm::dot(d, n);
    rho = glm::length(d - n * z);
}

// Frustum planes (Gribb-Hartmann), normalised: as MinorField::build_bins.
struct Frustum {
    glm::vec4 planes[6];
    explicit Frustum(const glm::mat4& vp) {
        const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                        r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
        planes[0] = r3 + r0; planes[1] = r3 - r0; planes[2] = r3 + r1;
        planes[3] = r3 - r1; planes[4] = r3 + r2; planes[5] = r3 - r2;
        for (auto& p : planes) p /= glm::length(glm::vec3(p));
    }
    // False when the sphere lies entirely outside any plane.
    bool sphere(const glm::vec3& c, float r) const {
        for (const auto& pl : planes)
            if (glm::dot(glm::vec3(pl), c) + pl.w < -r) return false;
        return true;
    }
};
}  // namespace

float table_a(const DiscSource& s, float rho) {
    const auto& t = s.table;
    if (t.empty()) return 0.0f;
    if (rho <= t.front().x) return t.front().y;
    for (std::size_t i = 1; i < t.size(); ++i)
        if (rho <= t[i].x) {
            const float span = t[i].x - t[i - 1].x;
            const float u = span > 0.0f ? (rho - t[i - 1].x) / span : 1.0f;
            return t[i - 1].y + (t[i].y - t[i - 1].y) * u;
        }
    if (!(s.outer_fade_gu > 0.0f)) return 0.0f;
    const float u = (rho - t.back().x) / s.outer_fade_gu;
    return u >= 1.0f ? 0.0f : t.back().y * (1.0f - u);
}

float scale_height(const DiscSource& s, float rho) {
    return std::max(s.scale_height_frac * rho, s.scale_height_min_gu);
}

// Sphere density (tile-field haze): 1 within R(1 - edge_frac), a linear
// ramp to 0 at R. far_haze.frag's sphere_a is the GLSL twin.
float sphere_a(const DiscSource& s, const glm::dvec3& x) {
    const double R = s.sphere_radius_gu;
    const double d = glm::length(x - s.centre);
    if (!(R > 0.0) || d >= R) return 0.0f;
    const double inner = R * (1.0 - std::clamp(static_cast<double>(s.sphere_edge_frac), 0.0, 1.0));
    if (d <= inner) return 1.0f;
    return static_cast<float>((R - d) / (R - inner));
}

float density_a(const DiscSource& s, const glm::dvec3& x) {
    if (s.shape == DiscSource::Shape::Sphere) return sphere_a(s, x);
    double rho, z;
    disc_coords(s, x, rho, z);
    const double H = scale_height(s, static_cast<float>(rho));
    return table_a(s, static_cast<float>(rho)) * static_cast<float>(std::exp(-0.5 * z * z / (H * H)));
}

float a_bound(const DiscSource& s, const glm::dvec3& c, double h) {
    const double hd = h * std::sqrt(3.0);   // the cube's bounding-sphere radius
    if (s.shape == DiscSource::Shape::Sphere) {
        const double R = s.sphere_radius_gu;
        return (R > 0.0 && glm::length(c - s.centre) - hd < R) ? 1.0f : 0.0f;
    }
    double rho, z;
    disc_coords(s, c, rho, z);
    const float lo = static_cast<float>(std::max(0.0, rho - hd));
    const float hi = static_cast<float>(rho + hd);
    float amax = std::max(table_a(s, lo), table_a(s, hi));
    for (const auto& row : s.table)
        if (row.x >= lo && row.x <= hi) amax = std::max(amax, row.y);
    const double zmin = std::max(0.0, std::fabs(z) - hd);
    const double H = scale_height(s, hi);
    return amax * static_cast<float>(std::exp(-0.5 * zmin * zmin / (H * H)));
}

float pop_density(const Population& p, float a) {
    const float span = p.a_hi - p.a_lo;
    const float w = span > 0.0f ? std::clamp((a - p.a_lo) / span, 0.0f, 1.0f) : (a > p.a_lo ? 1.0f : 0.0f);
    return p.density_at_1 * w;
}

bool haze_interval(const DiscSource& s, const glm::dvec3& origin, const glm::vec3& dir_f,
                   float t_max, float slab_sigmas, double& t0, double& t1) {
    if (s.shape == DiscSource::Shape::Sphere) {
        // Ray |d + t dir| <= R, clipped to [0, t_max]. far_haze.frag twin.
        const double R = s.sphere_radius_gu;
        if (!(R > 0.0)) return false;
        const glm::dvec3 dir(dir_f), d = origin - s.centre;
        const double qa = glm::dot(dir, dir), qb = 2.0 * glm::dot(d, dir),
                     qc = glm::dot(d, d) - R * R;
        if (qa < 1e-12) return false;
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        const double sq = std::sqrt(disc);
        t0 = std::max(0.0, (-qb - sq) / (2.0 * qa));
        t1 = std::min(static_cast<double>(t_max), (-qb + sq) / (2.0 * qa));
        return t1 > t0;
    }
    if (s.table.empty()) return false;
    const double R = static_cast<double>(s.table.back().x) + std::max(0.0f, s.outer_fade_gu);
    const double Z = static_cast<double>(slab_sigmas) * scale_height(s, static_cast<float>(R));
    const glm::dvec3 n(s.normal), dir(dir_f), d = origin - s.centre;
    t0 = 0.0;
    t1 = t_max;
    // Slab |z0 + t dz| <= Z.
    const double z0 = glm::dot(d, n), dz = glm::dot(dir, n);
    if (std::fabs(dz) < 1e-12) {
        if (std::fabs(z0) > Z) return false;
    } else {
        const double a = (-Z - z0) / dz, b = (Z - z0) / dz;
        t0 = std::max(t0, std::min(a, b));
        t1 = std::min(t1, std::max(a, b));
    }
    // Cylinder |p + t v| <= R in the disc plane.
    const glm::dvec3 p = d - n * z0, v = dir - n * dz;
    const double qa = glm::dot(v, v), qb = 2.0 * glm::dot(p, v), qc = glm::dot(p, p) - R * R;
    if (qa < 1e-12) {
        if (qc > 0.0) return false;
    } else {
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        const double sq = std::sqrt(disc);
        t0 = std::max(t0, (-qb - sq) / (2.0 * qa));
        t1 = std::min(t1, (-qb + sq) / (2.0 * qa));
    }
    return t1 > t0;
}

HazeSample haze_column(const DiscSource& s, const glm::dvec3& origin, const glm::vec3& dir,
                       float t_max, float slab_sigmas, int steps, float gain,
                       const glm::vec3& light, float start_gu, float ramp_gu) {
    HazeSample out;
    double t0 = 0.0, t1 = 0.0;
    steps = haze_steps_for(s, steps);
    if (steps < 1 || !haze_interval(s, origin, dir, t_max, slab_sigmas, t0, t1)) return out;
    // The start clip (rock-fields Task 12 fix round 1): nothing before the
    // start counts, so an interval ending there is empty and the march begins
    // at it -- the whole step budget lands inside the haze. far_haze.frag's
    // twin. start 0 is a no-op (t0 >= 0), keeping the unramped column exact.
    if (ramp_gu > 0.0f ? t1 <= start_gu : t1 < start_gu) return out;
    t0 = std::max(t0, static_cast<double>(start_gu));
    const double dt = (t1 - t0) / steps;
    float T = 1.0f;
    for (int i = 0; i < steps; ++i) {
        const double t = t0 + (i + 0.5) * dt;
        const glm::dvec3 x = origin + glm::dvec3(dir) * t;
        const float a = density_a(s, x);
        // No pixel cut (ruling R16): the WHOLE population cross-section, so
        // the haze does not depend on k (resolution / fov). far_haze.frag twin.
        float sum = 0.0f;
        glm::vec3 sum_albedo(0.0f);
        for (const Population& P : s.pops) {
            const float ns = pop_density(P, a) * mean_cross_section(P.size);
            sum += ns;
            sum_albedo += ns * P.albedo;
        }
        if (!(sum > 0.0f)) continue;
        // Tile-field noise scales the rock density, not `a` (pop_density
        // would clamp a * m at a_hi and lose the bright half). m == 1 (an
        // exact multiply) when the noise is off.
        const float m = haze_noise_m(s, x);
        // The start ramp multiplies LAST: with start 0 / ramp 0 it is an exact
        // * 1, so the unramped column is reproduced bit for bit.
        const float dtau = gain * s.gain_scale * sum * m * static_cast<float>(dt) *
                           haze_start_weight(static_cast<float>(t), start_gu, ramp_gu);
        const float ext = std::exp(-dtau);
        // brightness scales the colour only; T (alpha) is untouched.
        out.rgb += T * (1.0f - ext) * (sum_albedo / sum) * light * s.brightness;
        T *= ext;
    }
    out.alpha = 1.0f - T;
    return out;
}

float haze_start_weight(float t, float start_gu, float ramp_gu) {
    if (!(ramp_gu > 0.0f)) return t >= start_gu ? 1.0f : 0.0f;
    const float u = std::clamp((t - start_gu) / ramp_gu, 0.0f, 1.0f);
    return u * u * (3.0f - 2.0f * u);
}

// ---- Haze noise (every source). far_haze.frag's haze_hash / value_noise /
// fbm / noise_m are the GLSL twins: keep identical (integer hash, 24-bit
// lattice value, smoothstep fade, the same lerp order, octave seeds and the
// 8-octave cap). FarPassGLTest.NoisySphereHazeShaderMatchesTheCpuReference
// pins them together.
namespace {
constexpr int kMaxNoiseOctaves = 8;      // far_haze.frag's fbm loop bound
constexpr int kMaxHazeSteps = 64;        // far_haze.frag's march loop bound

// `hs` is the PRE-HASHED seed (haze_hash(seed)), hashed once per octave by
// the caller rather than in each of the 8 lattice calls per noise sample.
float lattice(std::int32_t x, std::int32_t y, std::int32_t z, std::uint32_t hs) {
    const std::uint32_t h =
        haze_hash(static_cast<std::uint32_t>(x) ^
                  haze_hash(static_cast<std::uint32_t>(y) ^
                            haze_hash(static_cast<std::uint32_t>(z) ^ hs)));
    return static_cast<float>(h >> 8) / 16777215.0f;
}
float lerp(float a, float b, float t) { return a + (b - a) * t; }
}  // namespace

std::uint32_t haze_hash(std::uint32_t v) {
    const std::uint32_t state = v * 747796405u + 2891336453u;
    const std::uint32_t word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float haze_value_noise(const glm::vec3& p, std::uint32_t seed) {
    return haze_value_noise_h(p, haze_hash(seed));
}

float haze_value_noise_h(const glm::vec3& p, std::uint32_t seed) {
    const glm::vec3 fl = glm::floor(p);
    const glm::vec3 f = p - fl;
    const glm::vec3 u = f * f * (3.0f - 2.0f * f);
    const auto x = static_cast<std::int32_t>(fl.x), y = static_cast<std::int32_t>(fl.y),
               z = static_cast<std::int32_t>(fl.z);
    const float x00 = lerp(lattice(x, y, z, seed), lattice(x + 1, y, z, seed), u.x);
    const float x10 = lerp(lattice(x, y + 1, z, seed), lattice(x + 1, y + 1, z, seed), u.x);
    const float x01 = lerp(lattice(x, y, z + 1, seed), lattice(x + 1, y, z + 1, seed), u.x);
    const float x11 = lerp(lattice(x, y + 1, z + 1, seed), lattice(x + 1, y + 1, z + 1, seed), u.x);
    return lerp(lerp(x00, x10, u.y), lerp(x01, x11, u.y), u.z);
}

float haze_fbm(const glm::vec3& p, int octaves, std::uint32_t seed) {
    const int n = std::min(octaves, kMaxNoiseOctaves);
    if (n <= 0) return 0.5f;
    float sum = 0.0f, norm = 0.0f, amp = 1.0f;
    glm::vec3 q = p;
    for (int o = 0; o < n; ++o) {
        const std::uint32_t hs = haze_hash(seed + static_cast<std::uint32_t>(o) * 0x9E3779B9u);
        sum += amp * haze_value_noise_h(q, hs);
        norm += amp;
        amp *= 0.5f;
        q *= 2.0f;
    }
    return sum / norm;
}

float haze_noise_m(const DiscSource& s, const glm::dvec3& x) {
    if (!(s.noise_scale_gu > 0.0f) || s.noise_contrast == 0.0f || s.noise_octaves <= 0)
        return 1.0f;
    const float contrast = std::clamp(s.noise_contrast, 0.0f, 1.0f);
    const glm::vec3 local = glm::vec3(x - s.centre) / s.noise_scale_gu;
    const float fbm = haze_fbm(local, s.noise_octaves, s.seed);
    return std::max(0.0f, 1.0f + contrast * (2.0f * fbm - 1.0f));
}

float field_density(const DiscSource& s, const glm::dvec3& x) {
    return density_a(s, x) * haze_noise_m(s, x);
}

float noise_m_bound(const DiscSource& s) {
    if (!(s.noise_scale_gu > 0.0f) || s.noise_contrast == 0.0f || s.noise_octaves <= 0)
        return 1.0f;
    return 1.0f + std::clamp(s.noise_contrast, 0.0f, 1.0f);
}

int haze_steps_for(const DiscSource& s, int global_steps) {
    return s.steps > 0 ? std::clamp(s.steps, 1, kMaxHazeSteps) : global_steps;
}

ViewBasis make_view_basis(const glm::vec3& dir) {
    // Copy of native/src/rockgen/src/impostor.cc:make_basis — the bake's rule.
    const glm::vec3 up_ref = (std::abs(dir.y) > 0.99f) ? glm::vec3(1.0f, 0.0f, 0.0f)
                                                        : glm::vec3(0.0f, 1.0f, 0.0f);
    const glm::vec3 forward = -dir;   // the direction the bake camera looks
    const glm::vec3 right = glm::normalize(glm::cross(up_ref, forward));
    const glm::vec3 up = glm::cross(forward, right);
    return {dir, right, up};
}

glm::mat3 gltf_to_bc() {
    return glm::mat3(glm::vec3(-1, 0, 0), glm::vec3(0, 0, 1), glm::vec3(0, 1, 0));
}

ImpostorGpu make_impostor(const std::vector<glm::vec3>& view_dirs_gltf, const glm::vec3& eye,
                          const glm::vec3& c, const glm::mat3& R, float r, float dither) {
    const glm::mat3 M = gltf_to_bc();   // its own inverse: BC -> glTF here
    const glm::vec3 to_eye = glm::transpose(R) * (eye - c);
    const float len = glm::length(to_eye);
    const glm::vec3 e_g = M * (len > 0.0f ? to_eye / len : glm::vec3(0, 0, 1));
    std::size_t best = 0;
    float best_dot = -2.0f;
    for (std::size_t i = 0; i < view_dirs_gltf.size(); ++i) {
        const float d = glm::dot(view_dirs_gltf[i], e_g);
        if (d > best_dot) { best_dot = d; best = i; }
    }
    const ViewBasis b = make_view_basis(view_dirs_gltf[best]);
    const glm::vec3 right_w = R * (M * b.right), up_w = R * (M * b.up);
    return ImpostorGpu{glm::vec4(c, r * 1.02f), glm::vec4(right_w, static_cast<float>(best)),
                       glm::vec4(up_w, dither)};
}

int impostor_grid_for(std::size_t view_count) {
    if (view_count < 4) return 0;
    const int g = static_cast<int>(std::lround(std::sqrt(static_cast<double>(view_count))));
    return static_cast<std::size_t>(g) * static_cast<std::size_t>(g) == view_count ? g : 0;
}

namespace {
float sgn_nz(float v) { return v >= 0.0f ? 1.0f : -1.0f; }   // sign, +1 at 0
}  // namespace

glm::vec2 oct_encode(const glm::vec3& d) {
    const float l1 = std::abs(d.x) + std::abs(d.y) + std::abs(d.z);
    const glm::vec3 p = l1 > 0.0f ? d / l1 : glm::vec3(0, 1, 0);
    if (p.y >= 0.0f) return glm::vec2(p.x, p.z);
    return glm::vec2((1.0f - std::abs(p.z)) * sgn_nz(p.x), (1.0f - std::abs(p.x)) * sgn_nz(p.z));
}

glm::vec3 oct_decode(const glm::vec2& f) {
    // Copied in native/src/rockgen/src/impostor.cc and the impostor shader.
    glm::vec3 n(f.x, 1.0f - std::abs(f.x) - std::abs(f.y), f.y);
    if (n.y < 0.0f) {
        const float x = (1.0f - std::abs(f.y)) * sgn_nz(f.x);
        const float z = (1.0f - std::abs(f.x)) * sgn_nz(f.y);
        n.x = x;
        n.z = z;
    }
    n = glm::normalize(n);
    return n + glm::vec3(0.0f);   // -0 -> +0: mirror twins stay bit-identical
}

glm::vec3 oct_view_dir(int view, int grid) {
    // (2i - (grid-1)) / (grid-1): exactly -1 and 1 at the ends and exactly
    // antisymmetric, so mirror twins decode from exactly negated points.
    const int i = view % grid, j = view / grid;
    const float span = static_cast<float>(grid - 1);
    return oct_decode(glm::vec2(static_cast<float>(2 * i - (grid - 1)) / span,
                                static_cast<float>(2 * j - (grid - 1)) / span));
}

std::vector<glm::vec3> oct_view_dirs(int grid) {
    std::vector<glm::vec3> v;
    if (grid < 2) return v;
    v.reserve(static_cast<std::size_t>(grid * grid));
    for (int k = 0; k < grid * grid; ++k) v.push_back(oct_view_dir(k, grid));
    return v;
}

ViewBlend view_blend(const glm::vec3& eye_dir_gltf, int grid) {
    ViewBlend b;
    if (grid < 2) return b;
    const glm::vec2 f = oct_encode(eye_dir_gltf);
    const float span = static_cast<float>(grid - 1);
    const float gx = std::clamp((f.x * 0.5f + 0.5f) * span, 0.0f, span);
    const float gy = std::clamp((f.y * 0.5f + 0.5f) * span, 0.0f, span);
    const int i0 = std::min(static_cast<int>(gx), grid - 2);
    const int j0 = std::min(static_cast<int>(gy), grid - 2);
    const float fx = gx - static_cast<float>(i0), fy = gy - static_cast<float>(j0);
    auto idx = [grid](int i, int j) { return j * grid + i; };
    if (fx + fy <= 1.0f) {   // lower-left triangle of the cell
        b.view[0] = idx(i0, j0);         b.w[0] = 1.0f - fx - fy;
        b.view[1] = idx(i0 + 1, j0);     b.w[1] = fx;
        b.view[2] = idx(i0, j0 + 1);     b.w[2] = fy;
    } else {                 // upper-right
        b.view[0] = idx(i0 + 1, j0 + 1); b.w[0] = fx + fy - 1.0f;
        b.view[1] = idx(i0, j0 + 1);     b.w[1] = 1.0f - fx;
        b.view[2] = idx(i0 + 1, j0);     b.w[2] = 1.0f - fy;
    }
    // Rounding residue (an encoded baked direction lands a few ulps off its
    // grid point) is dropped, so a baked direction is exactly one view. The
    // step this adds is below 1e-5 of a weight -- invisible in 8 bits.
    float kept = 0.0f;
    for (float& w : b.w) { if (w < 1e-5f) w = 0.0f; kept += w; }
    for (float& w : b.w) w /= kept;   // kept >= 1 - 2e-5: one weight is >= 1/3
    // The heaviest view first (FarPass may skip near-zero tails).
    for (int a = 0; a < 2; ++a)
        for (int c = a + 1; c < 3; ++c)
            if (b.w[c] > b.w[a]) { std::swap(b.w[a], b.w[c]); std::swap(b.view[a], b.view[c]); }
    return b;
}

float impostor_fade_alpha(float dither) {
    if (dither < 0.0f) return -dither;          // fading in: keeps the lower |d|
    if (dither > 0.0f) return 1.0f - dither;    // fading out: keeps the upper 1 - d
    return 1.0f;                                // solid
}

ImpostorViews make_impostor_views(const std::vector<glm::vec3>& view_dirs_gltf) {
    const glm::mat3 M = gltf_to_bc();
    ImpostorViews v;
    v.dirs = view_dirs_gltf;
    for (const glm::vec3& d : view_dirs_gltf) {
        const ViewBasis b = make_view_basis(d);
        v.right_bc.push_back(M * b.right);
        v.up_bc.push_back(M * b.up);
    }
    return v;
}

ImpostorGpu make_impostor(const ImpostorViews& views, const glm::vec3& eye, const glm::vec3& c,
                          const glm::mat3& R, float r, float dither) {
    // make_impostor above, step for step (renderer/glm_exact.h replicas).
    using glm_exact::dot3;
    const glm::mat3 M = gltf_to_bc();
    const glm::vec3 w(eye.x - c.x, eye.y - c.y, eye.z - c.z);
    const glm::vec3 to_eye = glm_exact::mul_transposed(R, w);
    const float len = std::sqrt(dot3(to_eye.x, to_eye.y, to_eye.z, to_eye.x, to_eye.y, to_eye.z));
    const glm::vec3 u = len > 0.0f ? glm::vec3(to_eye.x / len, to_eye.y / len, to_eye.z / len)
                                   : glm::vec3(0, 0, 1);
    const glm::vec3 e_g = glm_exact::mul(M, u);
    std::size_t best = 0;
    float best_dot = -2.0f;
    for (std::size_t i = 0; i < views.dirs.size(); ++i) {
        const glm::vec3& vd = views.dirs[i];
        const float d = dot3(vd.x, vd.y, vd.z, e_g.x, e_g.y, e_g.z);
        if (d > best_dot) { best_dot = d; best = i; }
    }
    const glm::vec3 right_w = glm_exact::mul(R, views.right_bc[best]);
    const glm::vec3 up_w = glm_exact::mul(R, views.up_bc[best]);
    return ImpostorGpu{glm::vec4(c, r * 1.02f), glm::vec4(right_w, static_cast<float>(best)),
                       glm::vec4(up_w, dither)};
}

void FarField::set_dials(const FarDials& d) { dials_ = d; }

void FarField::set_catalogue(std::vector<CatalogueRock> cat, std::vector<glm::vec3> view_dirs_gltf) {
    catalogue_ = std::move(cat);
    view_dirs_ = std::move(view_dirs_gltf);
}

void FarField::set_sources(std::vector<DiscSource> s) {
    sources_ = std::move(s);
    refresh_active();
}

void FarField::set_rocks(std::vector<FlaggedRock> r) { rocks_ = std::move(r); }

void FarField::set_frame(std::optional<std::string> system, const glm::dvec3& anchor_sys) {
    frame_ = std::move(system);
    anchor_ = anchor_sys;
    refresh_active();
}

void FarField::clear() {
    sources_.clear();
    active_.clear();
    rocks_.clear();
    frame_.reset();
    anchor_ = glm::dvec3(0.0);
}

void FarField::refresh_active() {
    active_.clear();
    for (const auto& s : sources_) {
        if (s.view_space) {
            // View space -> system: + anchor (0 for an unmapped set).
            active_.push_back(s);
            active_.back().centre = s.centre + anchor_;
        } else if (frame_ && s.frame == *frame_) {
            active_.push_back(s);
        }
    }
}

void FarField::drop_impostor(int index) {
    if (index >= 0 && static_cast<std::size_t>(index) < catalogue_.size())
        catalogue_[static_cast<std::size_t>(index)].has_impostor = false;
}

void FarField::build(const BuildInput& in, FarOutput& out) {
    out.impostors.clear();
    out.specks.clear();
    out.fades.clear();

    const float k = pixels_per_gu(in.proj, in.viewport_h);
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const TierDials& td = dials_.tiers;

    std::vector<std::vector<ImpostorGpu>> bins(catalogue_.size());
    auto albedo_of = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size()
                   ? catalogue_[static_cast<std::size_t>(index)].avg_albedo
                   : glm::vec3(0.4f);
    };
    auto has_impostor = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size() &&
               catalogue_[static_cast<std::size_t>(index)].has_impostor;
    };
    // Step 3: the baked view nearest the eye in the rock's own frame.
    auto emit_impostor = [&](int index, const glm::vec3& c, const glm::mat3& R, float r, float w) {
        if (!has_impostor(index) || view_dirs_.empty()) return;
        bins[static_cast<std::size_t>(index)].push_back(make_impostor(view_dirs_, eye, c, R, r, -w));
    };

    // Step 2: flagged (explicit) rocks.
    // Every flagged rock gets a fade entry; one we cannot place is mesh-only
    // (0), so the host never keeps a stale fade that hides the mesh.
    for (const auto& fr : rocks_) {
        glm::mat4 W(1.0f);
        const bool placed = in.world_of && in.world_of(fr.key, W);
        const float s = placed ? glm::length(glm::vec3(W[0])) : 0.0f;
        if (!(s > 0.0f)) { out.fades.emplace_back(fr.key, 0.0f); continue; }
        const glm::vec3 c(W[3]);
        const glm::mat3 R = glm::mat3(W) / s;
        const float r = fr.radius_mu * s;
        const float d = glm::length(c - eye);
        const float p = r * k / std::max(d, 1e-3f);
        const Kind kind = has_impostor(fr.index) ? Kind::Explicit : Kind::ExplicitNoImpostor;
        const TierWeights w = tier_weights(p, kind, td);
        out.fades.emplace_back(fr.key, 1.0f - w.mesh);   // culled ones too: fade stays current
        if (!frustum.sphere(c, r)) continue;
        if (w.impostor > 0.0f) emit_impostor(fr.index, c, R, r, w.impostor);
        if (w.speck > 0.0f) out.specks.push_back(SpeckGpu{c, p, albedo_of(fr.index), w.speck});
    }

    for (std::size_t i = 0; i < bins.size(); ++i)
        if (!bins[i].empty())
            out.impostors.push_back(ImpostorBin{static_cast<int>(i), std::move(bins[i])});
}

}  // namespace renderer::far
