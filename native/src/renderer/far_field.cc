// native/src/renderer/far_field.cc
#include "renderer/far_field.h"
#include <algorithm>
#include <cmath>
#include <renderer/rock_random.h>

namespace renderer::far {
namespace {
using rockrand::Rng;

std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
    Rng r{h ^ (v + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2))};
    return r.next();
}

// Knuth for small lambda; rounded normal approximation above 30.
int poisson(Rng& r, double lambda) {
    if (!(lambda > 0.0)) return 0;
    if (lambda > 30.0) {
        const double u1 = std::max(1e-12, static_cast<double>(r.unit()));
        const double u2 = r.unit();
        const double z = std::sqrt(-2.0 * std::log(u1)) * std::cos(6.283185307179586 * u2);
        return std::max(0, static_cast<int>(std::lround(lambda + z * std::sqrt(lambda))));
    }
    const double L = std::exp(-lambda);
    int k = 0; double p = 1.0;
    do { ++k; p *= r.unit(); } while (p > L);
    return k - 1;
}

// (rho, z) of x relative to the disc.
void disc_coords(const DiscSource& s, const glm::dvec3& x, double& rho, double& z) {
    const glm::dvec3 d = x - s.centre;
    const glm::dvec3 n(s.normal);
    z = glm::dot(d, n);
    rho = glm::length(d - n * z);
}

// The largest `a` anywhere in the axis-aligned cube (centre c, half h).
float a_bound(const DiscSource& s, const glm::dvec3& c, double h) {
    double rho, z;
    disc_coords(s, c, rho, z);
    const double hd = h * std::sqrt(3.0);
    const float lo = static_cast<float>(std::max(0.0, rho - hd));
    const float hi = static_cast<float>(rho + hd);
    float amax = std::max(table_a(s, lo), table_a(s, hi));
    for (const auto& row : s.table)
        if (row.x >= lo && row.x <= hi) amax = std::max(amax, row.y);
    const double zmin = std::max(0.0, std::fabs(z) - hd);
    const double H = scale_height(s, hi);
    return amax * static_cast<float>(std::exp(-0.5 * zmin * zmin / (H * H)));
}

bool in_explicit(const DiscSource& s, const glm::dvec3& p) {
    for (const auto& e : s.explicit_regions)
        if (glm::length(p - glm::dvec3(e)) < e.w) return true;
    return false;
}

int pick_rock(const Population& p, float u) {
    if (p.rocks.empty()) return 0;
    float total = 0.0f;
    for (float w : p.weights) total += w;
    if (!(total > 0.0f)) return p.rocks[static_cast<std::size_t>(u * p.rocks.size()) % p.rocks.size()];
    float acc = 0.0f;
    for (std::size_t i = 0; i < p.rocks.size(); ++i) {
        acc += (i < p.weights.size() ? p.weights[i] : 0.0f) / total;
        if (u < acc) return p.rocks[i];
    }
    return p.rocks.back();
}
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

float density_a(const DiscSource& s, const glm::dvec3& x) {
    double rho, z;
    disc_coords(s, x, rho, z);
    const double H = scale_height(s, static_cast<float>(rho));
    return table_a(s, static_cast<float>(rho)) * static_cast<float>(std::exp(-0.5 * z * z / (H * H)));
}

float pop_density(const Population& p, float a) {
    const float span = p.a_hi - p.a_lo;
    const float w = span > 0.0f ? std::clamp((a - p.a_lo) / span, 0.0f, 1.0f) : (a > p.a_lo ? 1.0f : 0.0f);
    return p.density_at_1 * w;
}

std::vector<ClassBin> size_classes(const Population& p, const GenParams& g) {
    const int n = std::max(1, g.size_classes);
    std::vector<ClassBin> out(static_cast<std::size_t>(n));
    const float ratio = p.size.r_max / p.size.r_min;
    for (int i = 0; i < n; ++i) {
        ClassBin& c = out[static_cast<std::size_t>(i)];
        c.r_lo = i == 0 ? p.size.r_min : p.size.r_min * std::pow(ratio, static_cast<float>(i) / n);
        c.r_hi = i == n - 1 ? p.size.r_max : p.size.r_min * std::pow(ratio, static_cast<float>(i + 1) / n);
        c.share = power_law_cdf(p.size, c.r_hi) - power_law_cdf(p.size, c.r_lo);
        c.cell_gu = (g.k_ref * c.r_hi / g.p_min) / static_cast<float>(std::max(1, g.cells_per_range));
    }
    return out;
}

std::vector<FarRock> generate_cell(const DiscSource& s, int pop, int cls,
                                   const glm::i64vec3& ijk, const GenParams& g) {
    std::vector<FarRock> out;
    if (pop < 0 || static_cast<std::size_t>(pop) >= s.pops.size()) return out;
    const Population& P = s.pops[static_cast<std::size_t>(pop)];
    const auto bins = size_classes(P, g);
    if (cls < 0 || static_cast<std::size_t>(cls) >= bins.size()) return out;
    const ClassBin& B = bins[static_cast<std::size_t>(cls)];
    const double L = B.cell_gu;
    const glm::dvec3 lo = glm::dvec3(ijk) * L;
    const float ab = a_bound(s, lo + 0.5 * L, 0.5 * L);
    const double n_bound = pop_density(P, ab);
    if (!(n_bound > 0.0)) return out;

    std::uint64_t h = mix(s.seed, static_cast<std::uint64_t>(pop));
    h = mix(h, static_cast<std::uint64_t>(cls));
    h = mix(h, static_cast<std::uint64_t>(ijk.x));
    h = mix(h, static_cast<std::uint64_t>(ijk.y));
    h = mix(h, static_cast<std::uint64_t>(ijk.z));
    Rng r{h};
    const int candidates = poisson(r, n_bound * B.share * L * L * L);
    for (int i = 0; i < candidates; ++i) {
        // Fixed draw order per candidate: position, accept, size, rock, look.
        const glm::dvec3 p = lo + glm::dvec3(r.unit(), r.unit(), r.unit()) * L;
        const float accept = r.unit();
        FarRock k;
        k.radius = rockrand::power_law(r.unit(), B.r_lo, B.r_hi, P.size.q);
        k.rock = pick_rock(P, r.unit());
        k.tumble_axis = rockrand::unit_vector(r);
        k.tumble_rate = 0.05f + 0.55f * r.unit();
        k.phase = r.unit() * 6.28318530718f;
        if (accept >= pop_density(P, density_a(s, p)) / n_bound) continue;
        if (in_explicit(s, p)) continue;
        k.pos_sys = p;
        out.push_back(k);
    }
    return out;
}

}  // namespace renderer::far
