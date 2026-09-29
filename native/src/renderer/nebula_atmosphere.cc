// native/src/renderer/nebula_atmosphere.cc
// Star-centred atmosphere maths for the system-scale nebula
// (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md).
// Pure CPU, no GL: the far-field table, the radial texels the shader reads,
// and a reference marcher the tests treat as truth.
#include "renderer/nebula_atmosphere.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace renderer::atmosphere {

namespace {
// Some toolchains only define M_PI under feature-test macros; keep our own
// so this file never depends on that.
inline constexpr float kPi = 3.14159265358979323846f;
}  // namespace

float density(const RadialProfile& p, float r) {
    if (p.r.empty()) return 0.0f;
    if (r <= p.r.front()) return p.nebula.front();
    for (size_t i = 1; i < p.r.size(); ++i) {
        if (r <= p.r[i]) {
            const float span = p.r[i] - p.r[i - 1];
            const float t = span > 0.0f ? (r - p.r[i - 1]) / span : 0.0f;
            return p.nebula[i - 1] + (p.nebula[i] - p.nebula[i - 1]) * t;
        }
    }
    return p.nebula.back();
}

float tau_star(const RadialProfile& p, float r) {
    if (r <= p.star_radius || p.k_sys <= 0.0f) return 0.0f;
    // exact trapezoid over the profile's own breakpoints
    std::vector<float> pts{p.star_radius, r};
    for (float x : p.r) if (x > p.star_radius && x < r) pts.push_back(x);
    std::sort(pts.begin(), pts.end());
    double sum = 0.0;
    for (size_t i = 1; i < pts.size(); ++i)
        sum += 0.5 * (density(p, pts[i - 1]) + density(p, pts[i])) * (pts[i] - pts[i - 1]);
    return static_cast<float>(p.k_sys * sum);
}

float hg(float g, float c) {
    const float g2 = g * g;
    const float denom = std::pow(std::max(1e-6f, 1.0f + g2 - 2.0f * g * c), 1.5f);
    return (1.0f - g2) / (4.0f * kPi * denom);
}

float radius_of_u(float u, float far_gu) { return far_gu * u * u; }
float u_of_radius(float r, float far_gu) {
    return std::sqrt(std::clamp(r / far_gu, 0.0f, 1.0f));
}

namespace {
// Distance along a ray (origin radius r0, direction cosine mu to the outward
// radial) to the sphere of radius R, the far exit (largest root), or -1.
float exit_distance(float r0, float mu, float R) {
    const float b = r0 * mu;
    const float c = r0 * r0 - R * R;
    const float disc = b * b - c;
    if (disc < 0.0f) return -1.0f;
    return -b + std::sqrt(disc);
}
// Nearest positive hit on the star sphere, or INFINITY.
float star_hit(float r0, float mu, float Rs) {
    const float b = r0 * mu;
    const float c = r0 * r0 - Rs * Rs;
    if (c <= 0.0f) return 0.0f;                 // already inside the star
    const float disc = b * b - c;
    if (disc < 0.0f) return INFINITY;
    const float t = -b - std::sqrt(disc);
    return t > 0.0f ? t : INFINITY;
}
}  // namespace

Segment reference_march(const RadialProfile& p, const LookParams& look,
                        float r0, float mu, float max_dist, int steps) {
    mu = std::clamp(mu, -1.0f, 1.0f);
    float len = std::min(max_dist, exit_distance(r0, mu, look.far_gu));
    len = std::min(len, star_hit(r0, mu, p.star_radius));
    Segment out{glm::vec3(1.0f), glm::vec3(0.0f)};
    if (!(len > 0.0f) || steps < 1) return out;
    const float dt = len / static_cast<float>(steps);
    const float sin0 = std::sqrt(std::max(0.0f, 1.0f - mu * mu));
    float transm = 1.0f;
    glm::vec3 lit(0.0f);
    for (int i = 0; i < steps; ++i) {
        const float t = (i + 0.5f) * dt;
        const float x = sin0 * t, y = r0 + mu * t;         // ray in its own plane
        const float r = std::sqrt(x * x + y * y);
        const float sigma = p.k_sys * density(p, r);
        if (sigma <= 0.0f) continue;
        // scattering angle: light travels outward (r-hat), toward the eye is -dir
        const float cos_theta = r > 1e-3f ? -(x * sin0 + y * mu) / r : 0.0f;
        const glm::vec3 light = look.scatter * hg(look.g, cos_theta) * p.star_rgb
                                * p.cloud_rgb * std::exp(-tau_star(p, r));
        const glm::vec3 emit = look.floor * p.cloud_rgb;
        const float ext = sigma * dt;
        lit += transm * (light + emit) * ext;
        transm *= std::exp(-ext);
    }
    out.transmittance = glm::vec3(transm);
    out.inscatter = lit;
    return out;
}

std::vector<glm::vec2> build_radial_texels(const RadialProfile& p, const LookParams& look) {
    std::vector<glm::vec2> out(kRadialTexels);
    for (int i = 0; i < kRadialTexels; ++i) {
        const float r = radius_of_u(static_cast<float>(i) / (kRadialTexels - 1), look.far_gu);
        out[i] = glm::vec2(density(p, r), tau_star(p, r));
    }
    return out;
}

Table build_table(const RadialProfile& p, const LookParams& look) {
    Table t;
    t.transmittance.resize(kTableR * kTableMu);
    t.inscatter.resize(kTableR * kTableMu);
    for (int j = 0; j < kTableMu; ++j) {
        const float mu = -1.0f + 2.0f * j / (kTableMu - 1);
        for (int i = 0; i < kTableR; ++i) {
            const float r = radius_of_u(static_cast<float>(i) / (kTableR - 1), look.far_gu);
            const Segment s = reference_march(p, look, r, mu, INFINITY, 512);
            t.transmittance[j * kTableR + i] = s.transmittance;
            t.inscatter[j * kTableR + i] = s.inscatter;
        }
    }
    return t;
}

std::vector<glm::vec3> tau_from_table(const Table& t) {
    std::vector<glm::vec3> out(t.transmittance.size());
    for (size_t i = 0; i < out.size(); ++i) {
        for (int c = 0; c < 3; ++c) {
            const float T = std::max(t.transmittance[i][c], std::numeric_limits<float>::min());
            out[i][c] = std::clamp(-std::log(T), 0.0f, kMaxTableTau);
        }
    }
    return out;
}

Segment compose(const Segment& n, const Segment& f) {
    return {n.transmittance * f.transmittance, n.inscatter + n.transmittance * f.inscatter};
}

Segment finite(const Segment& a, const Segment& b) {
    // b.transmittance legitimately underflows to ~1e-16 or smaller at the
    // far_gu scale of a real system profile (k_sys * far_gu is tens of
    // optical depths), so the floor here only needs to keep the division
    // finite when b.transmittance is a literal 0 -- a fixed epsilon like
    // 1e-6 is far above those real values and silently overrides the true
    // (tiny) denominator, corrupting the recovered ratio.
    const glm::vec3 denom = glm::max(b.transmittance, glm::vec3(std::numeric_limits<float>::min()));
    const glm::vec3 T = a.transmittance / denom;
    return {glm::min(T, glm::vec3(1.0f)),
            glm::max(a.inscatter - T * b.inscatter, glm::vec3(0.0f))};
}

}  // namespace renderer::atmosphere
