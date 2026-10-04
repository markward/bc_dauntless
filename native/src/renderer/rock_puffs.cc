// native/src/renderer/rock_puffs.cc
// Rock fields, far look as puffs (SPIKE). See rock_puffs.h.
#include "renderer/rock_puffs.h"
#include <algorithm>
#include <renderer/rock_random.h>
#include "rock_field_common.h"

namespace renderer::rockfield {

std::vector<PuffGpu> place_puffs(const far::DiscSource& s, const PuffDials& d,
                                 std::vector<glm::dvec3>* pos_sys) {
    std::vector<PuffGpu> out;
    if (s.shape != far::DiscSource::Shape::Sphere || d.count <= 0) return out;
    const double R = s.sphere_radius_gu;
    const double Ro = far::sphere_outer_r(s);
    if (!(R > 0.0) || !(Ro > 0.0)) return out;
    const float bound = far::noise_m_bound(s);
    const glm::vec3 albedo = s.pops.empty() ? glm::vec3(0.4f) : s.pops.front().albedo;
    rockrand::Rng r{detail::mix(s.seed, 0x9077ffull)};
    const int max_tries = d.count * 60;
    for (int t = 0; t < max_tries && static_cast<int>(out.size()) < d.count; ++t) {
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
    bool same = active.size() == sources_.size();
    for (std::size_t i = 0; same && i < active.size(); ++i)
        same = active[i].seed == sources_[i].seed && active[i].centre == sources_[i].centre &&
               active[i].sphere_radius_gu == sources_[i].sphere_radius_gu &&
               active[i].noise_scale_gu == sources_[i].noise_scale_gu &&
               active[i].noise_contrast == sources_[i].noise_contrast &&
               active[i].noise_sharpness == sources_[i].noise_sharpness &&
               active[i].shape_warp == sources_[i].shape_warp &&
               active[i].shape_warp_scale_gu == sources_[i].shape_warp_scale_gu;
    if (same) return;
    sources_ = active;
    rebuild();
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
    for (const auto& s : sources_)
        if (s.shape == far::DiscSource::Shape::Sphere) { origin_ += s.centre; ++n; }
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
