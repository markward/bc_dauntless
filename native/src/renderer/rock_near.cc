// native/src/renderer/rock_near.cc
// Rock fields, near band: deterministic cells and streaming
// (docs/superpowers/specs/2026-10-02-rock-fields-design.md).
#include "renderer/rock_near.h"
#include <algorithm>
#include <cmath>
#include <utility>
#include <renderer/rock_random.h>

namespace renderer::rockfield {
namespace {
using rockrand::Rng;

// Restored from the retired far-tier belt generator (0fb9e591 far_field.cc).
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

bool in_explicit(const far::DiscSource& s, const glm::dvec3& p) {
    for (const auto& e : s.explicit_regions)
        if (glm::length(p - glm::dvec3(e)) < e.w) return true;
    return false;
}

// Uniform pick from the class list (it carries no weights).
int pick_rock(const std::vector<int>& rocks, float u) {
    return rocks[static_cast<std::size_t>(u * static_cast<float>(rocks.size())) % rocks.size()];
}

std::uint64_t mix_ijk(std::uint64_t h, NearClass cls, const glm::i64vec3& ijk) {
    h = mix(h, static_cast<std::uint64_t>(cls));
    h = mix(h, static_cast<std::uint64_t>(ijk.x));
    h = mix(h, static_cast<std::uint64_t>(ijk.y));
    return mix(h, static_cast<std::uint64_t>(ijk.z));
}

std::uint64_t cell_key(std::uint32_t source, NearClass cls, const glm::i64vec3& ijk) {
    return mix_ijk(source, cls, ijk);
}

std::uint64_t rock_key(std::uint64_t cell, std::size_t index) {
    return mix(cell, static_cast<std::uint64_t>(index) + 1u);
}

const NearClassDials& class_dials(const NearDials& d, NearClass cls) {
    return cls == NearClass::Small ? d.small : d.large;
}

// The dials generate_near_cell reads: a change invalidates every cell.
bool same_generator(const NearClassDials& a, const NearClassDials& b) {
    return a.density == b.density && a.r_min == b.r_min && a.r_max == b.r_max &&
           a.exponent == b.exponent && a.cell_gu == b.cell_gu;
}

// Every DiscSource field field_density / a_bound / the cell RNG reads.
// (Populations, haze look and frame keys do not shape the near rocks.)
bool same_generator(const far::DiscSource& a, const far::DiscSource& b) {
    return a.id == b.id && a.seed == b.seed && a.shape == b.shape && a.centre == b.centre &&
           a.sphere_radius_gu == b.sphere_radius_gu && a.sphere_edge_frac == b.sphere_edge_frac &&
           a.noise_scale_gu == b.noise_scale_gu && a.noise_contrast == b.noise_contrast &&
           a.noise_octaves == b.noise_octaves && a.normal == b.normal && a.table == b.table &&
           a.outer_fade_gu == b.outer_fade_gu && a.scale_height_frac == b.scale_height_frac &&
           a.scale_height_min_gu == b.scale_height_min_gu &&
           a.explicit_regions == b.explicit_regions;
}

// Distance from p to the AABB [lo, lo + size].
double aabb_distance(const glm::dvec3& p, const glm::dvec3& lo, double size) {
    const glm::dvec3 q = glm::clamp(p, lo, lo + glm::dvec3(size));
    return glm::length(p - q);
}

// False when no point within `range` of `c` can have density in `s`.
bool reaches(const far::DiscSource& s, const glm::dvec3& c, double range) {
    if (s.shape == far::DiscSource::Shape::Sphere)
        return s.sphere_radius_gu > 0.0f &&
               glm::length(c - s.centre) <= static_cast<double>(s.sphere_radius_gu) + range;
    return far::a_bound(s, c, range) > 0.0f;
}

constexpr NearClass kClasses[] = {NearClass::Small, NearClass::Large};
}  // namespace

std::vector<NearRock> generate_near_cell(const far::DiscSource& s, NearClass cls,
                                         const glm::i64vec3& ijk, const NearDials& d,
                                         const NearCatalogue& cat) {
    std::vector<NearRock> out;
    const NearClassDials& c = class_dials(d, cls);
    const std::vector<int>& rocks = cls == NearClass::Small ? cat.small_rocks : cat.large_rocks;
    if (rocks.empty() || !(c.cell_gu > 0.0f) || !(c.density > 0.0f)) return out;
    const double L = c.cell_gu;
    const glm::dvec3 lo = glm::dvec3(ijk) * L;
    const double n_bound = static_cast<double>(c.density) *
                           far::a_bound(s, lo + 0.5 * L, 0.5 * L) * far::noise_m_bound(s);
    if (!(n_bound > 0.0)) return out;

    Rng r{mix_ijk(s.seed, cls, ijk)};
    const int candidates = poisson(r, n_bound * L * L * L);
    for (int i = 0; i < candidates; ++i) {
        // Fixed draw order per candidate: position (3), accept, size, rock,
        // tumble axis (2), rate, phase -- drawn whether or not it is kept.
        const glm::dvec3 p = lo + glm::dvec3(r.unit(), r.unit(), r.unit()) * L;
        const float accept = r.unit();
        NearRock k;
        k.radius = rockrand::power_law(r.unit(), c.r_min, c.r_max, c.exponent);
        k.rock = pick_rock(rocks, r.unit());
        k.tumble_axis = rockrand::unit_vector(r);
        k.tumble_rate = 0.05f + 0.55f * r.unit();
        k.phase = r.unit() * 6.28318530718f;
        if (accept >= c.density * far::field_density(s, p) / n_bound) continue;
        if (in_explicit(s, p)) continue;
        k.pos_sys = p;
        out.push_back(k);
    }
    return out;
}

void NearField::set_dials(const NearDials& d) {
    const bool regen = !same_generator(d.small, dials_.small) || !same_generator(d.large, dials_.large);
    dials_ = d;
    if (regen) clear();
}

void NearField::set_catalogue(NearCatalogue c) {
    cat_ = std::move(c);
    clear();
}

void NearField::set_sources(const std::vector<far::DiscSource>& active) {
    const bool same = active.size() == sources_.size() &&
                      std::equal(active.begin(), active.end(), sources_.begin(),
                                 [](const far::DiscSource& a, const far::DiscSource& b) {
                                     return same_generator(a, b);
                                 });
    sources_ = active;
    if (!same) clear();
}

void NearField::stream(const glm::dvec3& c) {
    // Drop cells past range + margin (hysteresis: a cell re-enters at range).
    for (auto it = cells_.begin(); it != cells_.end();) {
        const double keep = class_dials(dials_, it->second.cls).billboard_gu + dials_.stream_margin_gu;
        if (aabb_distance(c, it->second.lo, it->second.size) > keep) it = cells_.erase(it);
        else ++it;
    }
    // Generate cells newly within range.
    for (const auto& s : sources_)
        for (NearClass cls : kClasses) {
            const NearClassDials& cd = class_dials(dials_, cls);
            const double L = cd.cell_gu, R = cd.billboard_gu;
            if (!(L > 0.0) || !(R > 0.0) || !reaches(s, c, R)) continue;
            const glm::i64vec3 a(glm::floor((c - R) / L)), b(glm::floor((c + R) / L));
            for (auto i = a.x; i <= b.x; ++i)
                for (auto j = a.y; j <= b.y; ++j)
                    for (auto k = a.z; k <= b.z; ++k) {
                        const glm::i64vec3 ijk(i, j, k);
                        const glm::dvec3 lo = glm::dvec3(ijk) * L;
                        if (aabb_distance(c, lo, L) > R) continue;
                        const std::uint64_t key = cell_key(s.id, cls, ijk);
                        if (cells_.count(key)) continue;
                        cells_.emplace(key, Cell{cls, generate_near_cell(s, cls, ijk, dials_, cat_), lo, L});
                    }
        }
}

void NearField::clear() {
    cells_.clear();
}

NearStats NearField::stats() const {
    NearStats st;
    st.cells = static_cast<int>(cells_.size());
    for (const auto& [key, cell] : cells_)
        (cell.cls == NearClass::Small ? st.small : st.large) += static_cast<int>(cell.rocks.size());
    return st;
}

void NearField::for_each(NearClass cls,
                         const std::function<void(std::uint64_t, const NearRock&)>& fn) const {
    for (const auto& [key, cell] : cells_) {
        if (cell.cls != cls) continue;
        for (std::size_t i = 0; i < cell.rocks.size(); ++i) fn(rock_key(key, i), cell.rocks[i]);
    }
}

}  // namespace renderer::rockfield
