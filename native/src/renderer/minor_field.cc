// native/src/renderer/minor_field.cc
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md).
#include "renderer/minor_field.h"

#include <algorithm>
#include <cmath>

namespace renderer::minors {
namespace {

// splitmix64: deterministic, platform-independent (std::*_distribution is not).
struct Rng {
    std::uint64_t s;
    std::uint64_t next() {
        std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    float unit() { return static_cast<float>(next() >> 40) / 16777216.0f; }  // [0,1)
};

glm::vec3 unit_vector(Rng& r) {
    const float z = r.unit() * 2.0f - 1.0f;
    const float t = r.unit() * 6.28318530718f;
    const float s = std::sqrt(std::max(0.0f, 1.0f - z * z));
    return {s * std::cos(t), s * std::sin(t), z};
}

// Inverse CDF of pdf ∝ r^-a on [lo, hi].
float power_law(float u, float lo, float hi, float a) {
    if (hi <= lo) return lo;
    if (std::fabs(a - 1.0f) < 1e-4f)
        return lo * std::pow(hi / lo, u);
    const float e = 1.0f - a;
    const float l = std::pow(lo, e), h = std::pow(hi, e);
    return std::pow(l + u * (h - l), 1.0f / e);
}

}  // namespace

std::vector<Minor> generate(const CloudDesc& d) {
    std::vector<Minor> out;
    const int n = std::max(0, d.count);
    out.reserve(static_cast<std::size_t>(n) + d.debris.size());
    Rng rng{(static_cast<std::uint64_t>(d.seed) << 1) ^ 0xA57E401DULL};
    const float i3 = d.shell_inner * d.shell_inner * d.shell_inner;
    const float o3 = d.shell_outer * d.shell_outer * d.shell_outer;
    for (int i = 0; i < n; ++i) {
        Minor m;
        // Volume-uniform in the shell when falloff == 0; u^(1+falloff)
        // biases toward the inner surface.
        const float u = std::pow(rng.unit(), 1.0f + std::max(0.0f, d.falloff));
        const float dist = std::cbrt(i3 + (o3 - i3) * u);
        m.offset = unit_vector(rng) * dist;
        m.radius = power_law(rng.unit(), d.r_min, d.r_max, d.size_exponent);
        m.tumble_axis = unit_vector(rng);
        m.tumble_u = rng.unit();
        m.phase = rng.unit() * 6.28318530718f;
        m.orbit_u = 0.5f + 0.5f * rng.unit();
        m.mesh_u = static_cast<std::uint32_t>(rng.next() >> 32);
        out.push_back(m);
    }
    for (const auto& s : d.debris) {
        Rng dr{(static_cast<std::uint64_t>(s.seed) << 1) ^ 0xDEB815ULL};
        Minor m;
        m.offset = s.offset;
        m.v0 = s.v0;
        m.radius = s.radius;
        m.tumble_axis = unit_vector(dr);
        m.tumble_u = dr.unit();
        m.phase = dr.unit() * 6.28318530718f;
        m.orbit_u = 0.0f;                    // debris does not orbit
        m.mesh_u = static_cast<std::uint32_t>(dr.next() >> 32);
        m.debris = true;
        out.push_back(m);
    }
    return out;
}

}  // namespace renderer::minors
