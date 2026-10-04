// native/src/renderer/rock_puffs.cc
// Rock fields, far look as puffs. See rock_puffs.h.
#include "renderer/rock_puffs.h"
#include <algorithm>
#include <cmath>
#include <renderer/rock_random.h>
#include "rock_field_common.h"

namespace renderer::rockfield {

namespace {

std::vector<PuffGpu> place_belt_puffs(const far::DiscSource& s, const PuffDials& d,
                                      std::vector<glm::dvec3>* pos_sys) {
    std::vector<PuffGpu> out;
    if (s.table.empty() || d.belt_count <= 0) return out;
    float a_max = 0.0f;
    for (const auto& row : s.table) a_max = std::max(a_max, row.y);
    const double R = static_cast<double>(s.table.back().x) + std::max(0.0f, s.outer_fade_gu);
    const double Z = 3.0 * far::scale_height(s, static_cast<float>(R));
    const float bound = a_max * far::noise_m_bound(s);
    if (!(R > 0.0) || !(bound > 0.0f)) return out;
    // An orthonormal basis around the belt normal.
    const glm::dvec3 n = glm::normalize(glm::dvec3(s.normal));
    const glm::dvec3 ref = std::fabs(n.z) < 0.9 ? glm::dvec3(0, 0, 1) : glm::dvec3(1, 0, 0);
    const glm::dvec3 e1 = glm::normalize(glm::cross(n, ref)), e2 = glm::cross(n, e1);
    const glm::vec3 albedo = s.pops.empty() ? glm::vec3(0.4f) : s.pops.front().albedo;
    rockrand::Rng r{detail::mix(s.seed, 0xbe17ull)};
    const int max_tries = d.belt_count * 200;
    for (int t = 0; t < max_tries && static_cast<int>(out.size()) < d.belt_count; ++t) {
        const double rho = R * std::sqrt(static_cast<double>(r.unit()));
        const double phi = 6.283185307179586 * r.unit();
        const double z = Z * (2.0 * r.unit() - 1.0);
        const float accept = r.unit();
        const float size_u = r.unit();
        const glm::dvec3 p = s.centre + e1 * (rho * std::cos(phi)) + e2 * (rho * std::sin(phi)) + n * z;
        const float w = far::field_density(s, p) / bound;
        if (!(accept < w)) continue;
        PuffGpu g;
        g.pos = glm::vec3(0.0f);
        g.radius = d.belt_size_h * far::scale_height(s, static_cast<float>(rho)) *
                   static_cast<float>(0.6 + 0.8 * size_u);
        g.albedo = albedo;
        g.weight = std::clamp(w, 0.0f, 1.0f);
        out.push_back(g);
        if (pos_sys != nullptr) pos_sys->push_back(p);
    }
    return out;
}

}  // namespace

std::vector<PuffGpu> place_puffs(const far::DiscSource& s, const PuffDials& d,
                                 std::vector<glm::dvec3>* pos_sys) {
    if (s.shape == far::DiscSource::Shape::Disc) return place_belt_puffs(s, d, pos_sys);
    std::vector<PuffGpu> out;
    if (d.count <= 0) return out;
    const double R = s.sphere_radius_gu;
    const double Ro = far::sphere_outer_r(s);
    if (!(R > 0.0) || !(Ro > 0.0)) return out;
    const float bound = far::noise_m_bound(s);
    const glm::vec3 albedo = s.pops.empty() ? glm::vec3(0.4f) : s.pops.front().albedo;
    rockrand::Rng r{detail::mix(s.seed, 0x9077ffull)};
    // The samples fill the cube of the OUTER reach, whose volume grows as
    // (Ro / R)^3 under shape warp while the field's own stays ~R^3: the try
    // budget grows with it, so a warped field still places `count` puffs.
    const double vol = std::max(1.0, (Ro / R) * (Ro / R) * (Ro / R));
    const double tries = static_cast<double>(d.count) * 60.0 * vol;
    const long long max_tries = static_cast<long long>(std::min(tries, 4.0e8));
    for (long long t = 0; t < max_tries && static_cast<int>(out.size()) < d.count; ++t) {
        const glm::dvec3 q(2.0 * r.unit() - 1.0, 2.0 * r.unit() - 1.0, 2.0 * r.unit() - 1.0);
        const float accept = r.unit();
        const float size_u = r.unit();
        if (glm::dot(q, q) > 1.0) continue;
        const glm::dvec3 p = s.centre + q * Ro;
        const float w = far::field_density(s, p) / bound;
        if (!(accept < w)) continue;
        PuffGpu g;
        g.pos = glm::vec3(0.0f);
        g.radius = static_cast<float>(d.size_frac * R * (0.6 + 0.8 * size_u));
        g.albedo = albedo;
        g.weight = std::clamp(w, 0.0f, 1.0f);
        out.push_back(g);
        if (pos_sys != nullptr) pos_sys->push_back(p);
    }
    return out;
}

void PuffField::set_dials(const PuffDials& d) {
    dials_ = d;
    rebuild();
}

void PuffField::set_sources(const std::vector<far::DiscSource>& active) {
    // far::same_density (and the source list) decide where puffs land; the
    // first population's albedo is their colour. The sources are stored
    // either way, so a later set_dials rebuild never reads a stale copy.
    bool same = detail::same_generators(active, sources_);
    for (std::size_t i = 0; same && i < active.size(); ++i) {
        const glm::vec3 a = active[i].pops.empty() ? glm::vec3(0.4f) : active[i].pops.front().albedo;
        const glm::vec3 b = sources_[i].pops.empty() ? glm::vec3(0.4f) : sources_[i].pops.front().albedo;
        same = a == b;
    }
    sources_ = active;
    if (!same) rebuild();
}

void PuffField::clear() {
    sources_.clear();
    instances_.clear();
    dirty_ = true;
}

void PuffField::rebuild() {
    instances_.clear();
    origin_ = glm::dvec3(0.0);
    int n = 0;
    for (const auto& s : sources_) { origin_ += s.centre; ++n; }
    if (n > 0) origin_ /= static_cast<double>(n);
    for (const auto& s : sources_) {
        std::vector<glm::dvec3> pos;
        auto puffs = place_puffs(s, dials_, &pos);
        for (std::size_t i = 0; i < puffs.size(); ++i) {
            puffs[i].pos = glm::vec3(pos[i] - origin_);
            instances_.push_back(puffs[i]);
        }
    }
    dirty_ = true;
}

}  // namespace renderer::rockfield
