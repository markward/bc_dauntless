// native/src/renderer/atmosphere_math.cc
#include "renderer/atmosphere_math.h"

#include "renderer/frame.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace renderer::planet_atmo {

namespace {
// Some toolchains only define M_PI under feature-test macros; keep our own
// so this file never depends on that (mirrors nebula_atmosphere.cc).
inline constexpr float kPi = 3.14159265358979323846f;
// Mie forward-lobe asymmetry (Earth-like haze).
inline constexpr float kMieG = 0.76f;

// Henyey-Greenstein phase kernel. Re-implemented here (rather than including
// renderer::atmosphere's nebula_atmosphere.h) because this namespace is
// deliberately separate from the nebula kit; formula matches
// nebula_atmosphere.cc:56-60.
float hg(float g, float c) {
    const float g2 = g * g;
    const float denom = std::pow(std::max(1e-6f, 1.0f + g2 - 2.0f * g * c), 1.5f);
    return (1.0f - g2) / (4.0f * kPi * denom);
}

// Ray/sphere intersection assuming a unit-length dir. Returns the near and
// far roots; `hit` is false when the discriminant is <= 0 (miss or exact
// tangent, which the shell treats as a miss so the shader can mirror it
// exactly with no epsilon tuning).
//
// Robust form: disc = r^2 - |oc - b*dir|^2 rather than b^2 - (|oc|^2 - r^2).
// At ~1e6 GU the latter subtracts two ~1e12 floats (ulp ~6e4) and moves the
// shell span by tens of GU; the perpendicular offset h stays planet-sized.
struct SphereHit {
    bool hit = false;
    float t_near = 0.0f;
    float t_far = 0.0f;
};

SphereHit intersect_sphere(glm::vec3 origin, glm::vec3 dir, glm::vec3 center, float radius) {
    const glm::vec3 oc = origin - center;
    const float b = glm::dot(oc, dir);
    const glm::vec3 h = oc - b * dir;
    const float disc = radius * radius - glm::dot(h, h);
    if (disc <= 0.0f) return {};
    const float sq = std::sqrt(disc);
    SphereHit out;
    out.hit = true;
    out.t_near = -b - sq;
    out.t_far = -b + sq;
    return out;
}
}  // namespace

Span air_span(const Shell& s, glm::vec3 origin, glm::vec3 dir, float t_max) {
    Span out;
    const SphereHit top = intersect_sphere(origin, dir, s.center, s.r_top);
    if (!top.hit) return out;

    float t0 = std::max(top.t_near, 0.0f);
    float t1 = top.t_far;

    const SphereHit planet = intersect_sphere(origin, dir, s.center, s.r_planet);
    if (planet.hit && planet.t_near > 0.0f) {
        t1 = std::min(t1, planet.t_near);
    }
    t1 = std::min(t1, t_max);

    out.hit = t1 > t0;
    out.t0 = t0;
    out.t1 = t1;
    return out;
}

float scale_height(const Shell& s) {
    return 0.25f * (s.r_top - s.r_planet);
}

float sigma(const Shell& s, const Params& p) {
    return p.density / (s.r_top - s.r_planet);
}

float rho(const Shell& s, glm::vec3 p) {
    const float h = std::max(glm::length(p - s.center) - s.r_planet, 0.0f);
    return std::exp(-h / scale_height(s));
}

glm::vec3 beta_rayleigh(const Params& p) {
    const float m = std::max(std::max(p.color.r, p.color.g), p.color.b);
    if (!(m > 0.0f)) return glm::vec3(0.0f);   // all-zero (or NaN) colour: no Rayleigh
    return p.color / m;
}

glm::vec3 sun_tau(const Shell& s, const Params& p, glm::vec3 x, glm::vec3 sun_dir) {
    const SphereHit planet = intersect_sphere(x, sun_dir, s.center, s.r_planet);
    if (planet.hit && planet.t_near > 1e-4f) return glm::vec3(kOpaqueTau);

    const SphereHit top = intersect_sphere(x, sun_dir, s.center, s.r_top);
    if (!top.hit) return glm::vec3(0.0f);

    const float len = std::max(top.t_far, 0.0f);
    const float ds = len / static_cast<float>(kSunSamples);
    float od = 0.0f;
    for (int i = 0; i < kSunSamples; ++i) {
        const float t = (static_cast<float>(i) + 0.5f) * ds;
        od += rho(s, x + sun_dir * t);
    }
    // Per-channel extinction: chromatic Rayleigh + grey Mie.
    const float sig = sigma(s, p);
    const glm::vec3 ext = sig * beta_rayleigh(p) + glm::vec3(sig * p.mie);
    return od * ds * ext;
}

float rayleigh_phase(float cos_theta) {
    return (3.0f / (16.0f * kPi)) * (1.0f + cos_theta * cos_theta);
}

float mie_phase(float cos_theta) {
    return hg(kMieG, cos_theta);
}

glm::vec3 in_scatter(const Shell& s, const Params& p, glm::vec3 origin, glm::vec3 dir,
                      float t_max, glm::vec3 sun_dir) {
    if (s.r_top <= s.r_planet) return glm::vec3(0.0f);

    const Span span = air_span(s, origin, dir, t_max);
    if (!span.hit) return glm::vec3(0.0f);

    const float sig = sigma(s, p);
    const glm::vec3 sig_r = sig * beta_rayleigh(p);   // chromatic Rayleigh
    const float sig_m = sig * p.mie;                   // grey Mie
    const glm::vec3 ext = sig_r + glm::vec3(sig_m);
    const float c = glm::dot(dir, sun_dir);
    const float ds = (span.t1 - span.t0) / static_cast<float>(kViewSamples);

    glm::vec3 tau_view(0.0f);
    glm::vec3 acc_r(0.0f);
    glm::vec3 acc_m(0.0f);
    for (int i = 0; i < kViewSamples; ++i) {
        const float t_mid = span.t0 + (static_cast<float>(i) + 0.5f) * ds;
        const glm::vec3 pt = origin + dir * t_mid;
        const float r = rho(s, pt);
        const glm::vec3 step_tau = ext * r * ds;
        const glm::vec3 tau_view_mid = tau_view + 0.5f * step_tau;
        const glm::vec3 trans = glm::exp(-(tau_view_mid + sun_tau(s, p, pt, sun_dir)));
        acc_r += r * sig_r * trans * ds;
        acc_m += r * sig_m * trans * ds;
        tau_view += step_tau;
    }

    return acc_r * rayleigh_phase(c) + acc_m * mie_phase(c);
}

glm::vec3 sun_dir_for(glm::vec3 center, const std::vector<SunDescriptor>& suns,
                      glm::vec3 fallback_dir_ws) {
    const SunDescriptor* nearest = nullptr;
    float best_d2 = std::numeric_limits<float>::infinity();
    for (const auto& sun : suns) {
        const glm::vec3 delta = sun.position - center;
        const float d2 = glm::dot(delta, delta);
        if (d2 < best_d2) {
            best_d2 = d2;
            nearest = &sun;
        }
    }

    if (nearest != nullptr) {
        const glm::vec3 delta = nearest->position - center;
        const float len = glm::length(delta);
        if (len > 1e-6f) return delta / len;
    }

    const float flen = glm::length(fallback_dir_ws);
    if (flen > 1e-6f) return fallback_dir_ws / flen;

    return glm::vec3(0.0f, 0.0f, 1.0f);
}

}  // namespace renderer::planet_atmo
