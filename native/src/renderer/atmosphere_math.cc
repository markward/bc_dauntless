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
struct SphereHit {
    bool hit = false;
    float t_near = 0.0f;
    float t_far = 0.0f;
};

SphereHit intersect_sphere(glm::vec3 origin, glm::vec3 dir, glm::vec3 center, float radius) {
    const glm::vec3 oc = origin - center;
    const float b = glm::dot(oc, dir);
    const float c = glm::dot(oc, oc) - radius * radius;
    const float disc = b * b - c;
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

float sun_tau(const Shell& s, const Params& p, glm::vec3 x, glm::vec3 sun_dir) {
    const SphereHit planet = intersect_sphere(x, sun_dir, s.center, s.r_planet);
    if (planet.hit && planet.t_near > 1e-4f) return kOpaqueTau;

    const SphereHit top = intersect_sphere(x, sun_dir, s.center, s.r_top);
    if (!top.hit) return 0.0f;

    const float len = std::max(top.t_far, 0.0f);
    const float ds = len / static_cast<float>(kSunSamples);
    double tau = 0.0;
    for (int i = 0; i < kSunSamples; ++i) {
        const float t = (static_cast<float>(i) + 0.5f) * ds;
        tau += rho(s, x + sun_dir * t);
    }
    tau *= static_cast<double>(ds) * static_cast<double>(sigma(s, p));
    return static_cast<float>(tau);
}

float phase(float cos_theta) {
    const float c2 = cos_theta * cos_theta;
    return (3.0f / (16.0f * kPi)) * (1.0f + c2) + 0.25f * hg(0.6f, cos_theta);
}

glm::vec3 in_scatter(const Shell& s, const Params& p, glm::vec3 origin, glm::vec3 dir,
                      float t_max, glm::vec3 sun_dir) {
    if (s.r_top <= s.r_planet) return glm::vec3(0.0f);

    const Span span = air_span(s, origin, dir, t_max);
    if (!span.hit) return glm::vec3(0.0f);

    const float sig = sigma(s, p);
    const float ph = phase(glm::dot(dir, sun_dir));
    const float ds = (span.t1 - span.t0) / static_cast<float>(kViewSamples);

    float tau_view = 0.0f;
    float accum = 0.0f;
    for (int i = 0; i < kViewSamples; ++i) {
        const float t_mid = span.t0 + (static_cast<float>(i) + 0.5f) * ds;
        const glm::vec3 pt = origin + dir * t_mid;
        const float r = rho(s, pt);
        const float step_tau = sig * r * ds;
        const float tau_view_mid = tau_view + 0.5f * step_tau;
        const float stau = sun_tau(s, p, pt, sun_dir);
        accum += r * std::exp(-(tau_view_mid + stau)) * sig * ds;
        tau_view += step_tau;
    }

    return accum * ph * p.color;
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
