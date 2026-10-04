// native/src/renderer/rock_speck.cc
// Rock fields, speck band (2026-10-04). See rock_speck.h.
#include "renderer/rock_speck.h"
#include <algorithm>
#include <cmath>
#include <renderer/rock_random.h>
#include "rock_field_common.h"

namespace renderer::rockfield {
namespace {

std::uint64_t speck_cell_key(std::uint64_t source, const glm::i64vec3& ijk) {
    std::uint64_t h = detail::mix(source, 0x5bec5bec5bec5becull);
    h = detail::mix(h, static_cast<std::uint64_t>(ijk.x));
    h = detail::mix(h, static_cast<std::uint64_t>(ijk.y));
    return detail::mix(h, static_cast<std::uint64_t>(ijk.z));
}

// The cell's thinning hash: from the source's seed (not its list index), so a
// re-ordered source list keeps every cell's u.
float cell_u(std::uint64_t seed, const glm::i64vec3& ijk) {
    rockrand::Rng r{speck_cell_key(detail::mix(seed, 0x7e11ull), ijk)};
    return r.unit();
}

double box_distance(const glm::dvec3& p, const glm::dvec3& lo, double L) {
    const glm::dvec3 hi = lo + glm::dvec3(L);
    const glm::dvec3 q = glm::max(glm::max(lo - p, p - hi), glm::dvec3(0.0));
    return glm::length(q);
}

double box_far_distance(const glm::dvec3& p, const glm::dvec3& lo, double L) {
    const glm::dvec3 hi = lo + glm::dvec3(L);
    const glm::dvec3 q = glm::max(glm::abs(p - lo), glm::abs(p - hi));
    return glm::length(q);
}

}  // namespace

float speck_keep_alpha(float d, float u, const SpeckDials& s) {
    const float band = std::max(s.keep_band, 1e-3f);
    float keep = 1.0f;
    if (s.keep_d0_gu > 0.0f && d > s.keep_d0_gu) keep = std::pow(s.keep_d0_gu / d, s.keep_power);
    return std::clamp((keep * (1.0f + band) - u) / band, 0.0f, 1.0f);
}

void SpeckBand::set_dials(const SpeckDials& d) {
    dials_ = d;
    dirty_ = true;
}

void SpeckBand::set_near_dials(const NearDials& d) {
    const NearClassDials& a = near_.large;
    const NearClassDials& b = d.large;
    const bool regen = a.density != b.density || a.r_min != b.r_min || a.r_max != b.r_max ||
                       a.exponent != b.exponent || a.cell_gu != b.cell_gu;
    near_ = d;
    if (regen) { cells_.clear(); ++generation_; }
    dirty_ = true;
}

void SpeckBand::set_catalogue(const NearCatalogue& c, std::vector<glm::vec3> large_albedo) {
    cat_ = c;
    albedo_ = std::move(large_albedo);
    clear();
}

void SpeckBand::set_sources(const std::vector<far::DiscSource>& active) {
    bool same = active.size() == sources_.size();
    for (std::size_t i = 0; same && i < active.size(); ++i)
        same = active[i].seed == sources_[i].seed && active[i].centre == sources_[i].centre &&
               active[i].sphere_radius_gu == sources_[i].sphere_radius_gu &&
               active[i].noise_scale_gu == sources_[i].noise_scale_gu &&
               active[i].noise_contrast == sources_[i].noise_contrast &&
               active[i].noise_sharpness == sources_[i].noise_sharpness &&
               active[i].shape_warp == sources_[i].shape_warp &&
               active[i].shape_warp_scale_gu == sources_[i].shape_warp_scale_gu;
    sources_ = active;
    if (!same) clear();
}

SpeckBand::~SpeckBand() {
    if (job_.valid()) job_.wait();
}

void SpeckBand::clear() {
    ++generation_;                 // a rebuild in flight is discarded
    cells_.clear();
    instances_.clear();
    dirty_ = true;
    has_last_ = false;
}

bool SpeckBand::stream(const glm::dvec3& centre_sys, float dash_step_gu) {
    const double step = has_last_ ? glm::length(centre_sys - last_frame_centre_) : 0.0;
    last_frame_centre_ = centre_sys;
    has_last_ = true;
    last_generated_ = 0;
    if (dash_step_gu > 0.0f && step > dash_step_gu) {
        hidden_ = true;            // a dash: keep the stale set, draw nothing
        return false;
    }
    if (hidden_) { hidden_ = false; dirty_ = true; }
    bool changed = false;
    if (job_.valid() && job_.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
        changed = take_result();
    if (job_.valid()) return changed;    // one rebuild in flight at a time
    if (!dirty_ && glm::length(centre_sys - origin_) < dials_.restream_gu) return changed;
    Job j{dials_, near_, cat_, albedo_, sources_, centre_sys, std::move(cells_)};
    cells_.clear();
    job_generation_ = generation_;
    job_ = std::async(std::launch::async, &SpeckBand::rebuild, std::move(j));
    dirty_ = false;
    return changed;
}

bool SpeckBand::finish() {
    if (!job_.valid()) return false;
    job_.wait();
    return take_result();
}

bool SpeckBand::take_result() {
    Result r = job_.get();
    last_generated_ = r.generated;
    if (job_generation_ != generation_) { dirty_ = true; return false; }   // stale: re-run
    cells_ = std::move(r.cells);
    instances_ = std::move(r.instances);
    origin_ = r.origin;
    return true;
}

SpeckBand::Result SpeckBand::rebuild(Job job) {
    Result out;
    const glm::dvec3 c = job.centre;
    out.origin = c;
    CellMap& cells = job.cells;
    const SpeckDials& dials_ = job.dials;
    const NearDials& near_ = job.near;
    const NearCatalogue& cat_ = job.cat;
    const std::vector<glm::vec3>& albedo_ = job.albedo;
    for (auto& [k, cell] : cells) cell.live = false;
    const NearClassDials& lg = near_.large;
    const double L = lg.cell_gu;
    const double margin = std::max(0.0f, dials_.restream_gu);
    const double r_out = dials_.out_gu + margin;
    const double r_in = static_cast<double>(lg.billboard_gu) - near_.fade_gu - margin;
    if (cat_.large_rocks.empty() || !(L > 0.0) || !(dials_.out_gu > lg.billboard_gu)) return out;
    for (std::size_t si = 0; si < job.sources.size(); ++si) {
        const far::DiscSource& s = job.sources[si];
        const glm::i64vec3 lo_i(glm::floor((c - r_out) / L));
        const glm::i64vec3 hi_i(glm::floor((c + r_out) / L));
        for (std::int64_t i = lo_i.x; i <= hi_i.x; ++i)
            for (std::int64_t j = lo_i.y; j <= hi_i.y; ++j) {
                // The column's z range within r_out of c (xy box distance).
                const double dx = std::max({i * L - c.x, c.x - (i + 1) * L, 0.0});
                const double dy = std::max({j * L - c.y, c.y - (j + 1) * L, 0.0});
                const double rem = r_out * r_out - dx * dx - dy * dy;
                if (rem < 0.0) continue;
                const double hz = std::sqrt(rem);
                const std::int64_t k0 = static_cast<std::int64_t>(std::floor((c.z - hz) / L));
                const std::int64_t k1 = static_cast<std::int64_t>(std::floor((c.z + hz) / L));
                for (std::int64_t k = k0; k <= k1; ++k) {
                    const glm::i64vec3 ijk(i, j, k);
                    const glm::dvec3 lo = glm::dvec3(ijk) * L;
                    const double dmin = box_distance(c, lo, L);
                    if (dmin > r_out) continue;
                    if (box_far_distance(c, lo, L) < r_in) continue;
                    const float u = cell_u(s.seed, ijk);
                    // The nearest this cell can come before the next restream.
                    const float d_near = static_cast<float>(std::max(dmin - margin, 1.0));
                    if (speck_keep_alpha(d_near, u, dials_) <= 0.0f) continue;
                    const std::uint64_t key = speck_cell_key(si, ijk);
                    auto it = cells.find(key);
                    if (it == cells.end()) {
                        Cell cell;
                        cell.u = u;
                        for (const NearRock& r : generate_near_cell(s, NearClass::Large, ijk, near_, cat_)) {
                            const glm::vec3 alb = r.rock >= 0 && r.rock < static_cast<int>(albedo_.size())
                                ? albedo_[static_cast<std::size_t>(r.rock)] : glm::vec3(0.4f);
                            cell.rocks.push_back(RockSpeckGpu{glm::vec3(0.0f), r.radius, alb, u});
                            cell.pos_sys.push_back(r.pos_sys);
                        }
                        it = cells.emplace(key, std::move(cell)).first;
                        ++out.generated;
                    }
                    it->second.live = true;
                }
            }
    }
    for (auto it = cells.begin(); it != cells.end();) {
        if (!it->second.live) { it = cells.erase(it); continue; }
        Cell& cell = it->second;
        for (std::size_t n = 0; n < cell.rocks.size(); ++n) {
            RockSpeckGpu g = cell.rocks[n];
            g.pos = glm::vec3(cell.pos_sys[n] - c);
            out.instances.push_back(g);
        }
        ++it;
    }
    out.cells = std::move(cells);
    return out;
}

}  // namespace renderer::rockfield
