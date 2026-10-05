// native/src/renderer/rock_speck.cc
// Rock fields, speck band (2026-10-04). See rock_speck.h.
#include "renderer/rock_speck.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdexcept>
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

float speck_keep_d0(const SpeckDials& s, float edge_gu, float fade_gu) {
    return std::max(s.keep_d0_gu, edge_gu + std::max(fade_gu, 0.0f));
}

float speck_cell_u(std::uint32_t seed, const glm::i64vec3& ijk) { return cell_u(seed, ijk); }

glm::vec4 speck_shape_seed(const glm::dvec3& p) {
    std::uint64_t bx, by, bz;
    std::memcpy(&bx, &p.x, sizeof bx);
    std::memcpy(&by, &p.y, sizeof by);
    std::memcpy(&bz, &p.z, sizeof bz);
    rockrand::Rng r{detail::mix(detail::mix(detail::mix(0x5eed5bec0ull, bx), by), bz)};
    constexpr float kTau = 6.2831853f;
    const float a = r.unit(), b = r.unit(), c = r.unit(), w = r.unit();
    return glm::vec4(a * kTau, b * kTau, c * kTau, w);
}

namespace {
// The margin a rebuild at the stream centre covers: how far the camera can
// be from the drawn set's origin before the NEXT set swaps in. A restream
// launches once the centre is restream_gu (+ up to one frame's step) from
// the drawn origin and lands J frames later (J: the last job's measured
// latency, in stream() calls); if J frames of travel already exceed
// restream_gu it launches the moment the previous one lands. So the drawn
// set's lag is at most max(restream + step, J step) + J step <= restream +
// step + 2 J step. Floored at 2 x restream_gu (slack for a job slower than
// the last), capped at max(4 x restream_gu, 200 GU) (the cell count grows
// with it; past the cap a far-too-slow worker shows as gaps, not a stall).
double rebuild_margin_gu(float restream_gu, double step, int job_frames) {
    const double base = std::max(0.0f, restream_gu);
    const double lag = base + step + 2.0 * static_cast<double>(std::max(job_frames, 1)) * step;
    return std::min(std::max(2.0 * base, lag), std::max(4.0 * base, 200.0));
}

// The belts' vertical reach in scale heights: exp(-0.5 x 8^2) ~ 1e-14.
constexpr double kBeltReachH = 8.0;

// False when no point within `range` of `c` can have density in `s`:
// a sphere within far::sphere_outer_r (its warped lobes), a belt within its
// cylinder (radial: the table and outer fade; vertical: kBeltReachH scale
// heights).
bool source_reaches(const far::DiscSource& s, const glm::dvec3& c, double range) {
    if (s.shape == far::DiscSource::Shape::Sphere)
        return s.sphere_radius_gu > 0.0f && glm::length(c - s.centre) <= far::sphere_outer_r(s) + range;
    if (s.table.empty()) return false;
    const glm::dvec3 n = glm::normalize(glm::dvec3(s.normal));
    const glm::dvec3 d = c - s.centre;
    const double z = glm::dot(d, n);
    const double rho = glm::length(d - n * z);
    const double R = static_cast<double>(s.table.back().x) + std::max(0.0f, s.outer_fade_gu);
    if (rho - range > R) return false;
    const double H = far::scale_height(s, static_cast<float>(std::min(rho + range, R)));
    if (std::fabs(z) - range > kBeltReachH * H) return false;
    return far::a_bound(s, c, range) > 0.0f;
}
}  // namespace

double SpeckBand::next_margin_gu() const {
    return rebuild_margin_gu(dials_.restream_gu, std::max(step_peak_, last_step_), last_job_frames_);
}

void SpeckBand::set_dials(const SpeckDials& d) {
    dials_ = d;
    dirty_ = true;
}

void SpeckBand::set_near_dials(const NearDials& d) {
    const NearClassDials& a = near_.large;
    const NearClassDials& b = d.large;
    const bool regen = a.density != b.density || a.r_min != b.r_min || a.r_max != b.r_max ||
                       a.exponent != b.exponent || a.cell_gu != b.cell_gu ||
                       near_.large_ramp_lo != d.large_ramp_lo || near_.large_ramp_hi != d.large_ramp_hi;
    near_ = d;
    if (regen) { cells_.clear(); invalidate(); }
    dirty_ = true;
}

void SpeckBand::set_catalogue(const NearCatalogue& c, std::vector<glm::vec3> large_albedo) {
    cat_ = c;
    albedo_ = std::move(large_albedo);
    clear();
}

void SpeckBand::set_sources(const std::vector<far::DiscSource>& active) {
    const bool same = detail::same_generators(active, sources_);
    sources_ = active;
    if (!same) clear();
}

void SpeckBand::set_excluded(std::unordered_set<std::uint64_t> keys) {
    // Python re-pushes the list every acting tick (4 Hz): only a real change
    // re-streams. Cells stay cached -- the exclusion is applied when the
    // instances are assembled -- and a rebuild in flight is left to land
    // (the next stream re-runs it with the new set).
    if (keys == excluded_) return;
    excluded_ = std::move(keys);
    dirty_ = true;
}

SpeckBand::~SpeckBand() {
    cancel_.store(true);
    if (job_.valid()) job_.wait();
}

void SpeckBand::invalidate() {
    ++generation_;                 // a rebuild in flight is discarded ...
    cancel_.store(true);           // ... and stops early
}

void SpeckBand::clear() {
    invalidate();
    cells_.clear();
    excluded_.clear();             // as NearField::clear: keys die with the sources
    instances_.clear();
    ++version_;                    // the host uploads the empty set
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
    last_step_ = step;
    step_peak_ = std::max(step_peak_, step);
    if (hidden_) { hidden_ = false; dirty_ = true; }
    bool changed = false;
    if (job_.valid()) {
        ++job_frames_;
        if (job_frames_ >= debug_min_job_frames_ &&
            job_.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
            changed = take_result();
    }
    if (job_.valid()) return changed;    // one rebuild in flight at a time
    if (!dirty_ && glm::length(centre_sys - origin_) < dials_.restream_gu) return changed;
    Job j{dials_, near_, cat_, albedo_, sources_, excluded_, centre_sys, std::move(cells_), next_margin_gu(),
          debug_fail_jobs_};
    cells_.clear();
    job_generation_ = generation_;
    job_frames_ = 0;
    step_peak_ = 0.0;
    cancel_.store(false);
    job_ = std::async(std::launch::async, &SpeckBand::run_job, std::move(j), &cancel_);
    dirty_ = false;
    return changed;
}

bool SpeckBand::finish() {
    if (!job_.valid()) return false;
    job_.wait();
    return take_result();
}

bool SpeckBand::take_result() {
    Result r = job_.get();   // never throws: run_job catches
    last_generated_ = r.generated;
    last_cancelled_ = r.cancelled;
    last_job_frames_ = std::max(job_frames_, 1);
    if (job_generation_ != generation_ || r.cancelled) { dirty_ = true; return false; }   // stale: re-run
    cells_ = std::move(r.cells);
    instances_ = std::move(r.instances);
    origin_ = r.origin;
    ++version_;
    return true;
}

SpeckBand::Result SpeckBand::run_job(Job job, const std::atomic<bool>* cancel) {
    const glm::dvec3 c = job.centre;
    try {
        return rebuild(std::move(job), *cancel);
    } catch (const std::exception& e) {
        static std::atomic<bool> logged{false};
        if (!logged.exchange(true))
            std::fprintf(stderr, "[rock specks] rebuild failed (%s); the band draws nothing until the next restream\n",
                         e.what());
    } catch (...) {
        static std::atomic<bool> logged{false};
        if (!logged.exchange(true))
            std::fprintf(stderr, "[rock specks] rebuild failed; the band draws nothing until the next restream\n");
    }
    Result out;
    out.origin = c;
    return out;
}

SpeckBand::Result SpeckBand::rebuild(Job job, const std::atomic<bool>& cancel) {
    Result out;
    const glm::dvec3 c = job.centre;
    out.origin = c;
    if (job.fail) throw std::runtime_error("debug_fail_jobs");
    CellMap& cells = job.cells;
    const NearDials& near_ = job.near;
    const NearCatalogue& cat_ = job.cat;
    const std::vector<glm::vec3>& albedo_ = job.albedo;
    for (auto& [k, cell] : cells) cell.live = false;
    const NearClassDials& lg = near_.large;
    const double L = lg.cell_gu;
    if (cat_.large_rocks.empty() || !(L > 0.0) || !(job.dials.out_gu > lg.billboard_gu)) return out;
    // Thinning starts no nearer than the billboards' outer edge + fade.
    SpeckDials dials_ = job.dials;
    dials_.keep_d0_gu = speck_keep_d0(job.dials, lg.billboard_gu, near_.fade_gu);
    const double margin = job.margin;
    const double cap = 0.5 * (kSpeckMaxCellsPerAxis - 1) * L;
    const double r_out = std::min(static_cast<double>(dials_.out_gu) + margin, cap);
    // From the MESH range, not the billboard edge: after a dash the billboards
    // regrow from mesh_gu out to billboard_gu over ~17 frames and the shader
    // fades specks in at that regrowing edge (u_in_gu = the effective edge),
    // so those rocks must already be here. Inside the edge they cost only a
    // vertex each -- rock_speck.vert drops them at alpha 0.
    const double r_in = static_cast<double>(lg.mesh_gu) - near_.fade_gu - margin;
    // Checked per column: clear(), a source / generator change and the
    // destructor stop a rebuild in flight within one column's work.
    auto stopped = [&c]() { Result r; r.origin = c; r.cancelled = true; return r; };
    for (std::size_t si = 0; si < job.sources.size(); ++si) {
        const far::DiscSource& s = job.sources[si];
        if (!source_reaches(s, c, r_out)) continue;
        const glm::i64vec3 lo_i(glm::floor((c - r_out) / L));
        const glm::i64vec3 hi_i(glm::floor((c + r_out) / L));
        for (std::int64_t i = lo_i.x; i <= hi_i.x; ++i) {
            for (std::int64_t j = lo_i.y; j <= hi_i.y; ++j) {
                if (cancel.load(std::memory_order_relaxed)) return stopped();
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
                    // The nearest this cell can come before the next set swaps in.
                    const float d_near = static_cast<float>(std::max(dmin - margin, 1.0));
                    if (speck_keep_alpha(d_near, u, dials_) <= 0.0f) continue;
                    // A cell with no density holds no rocks: never cached.
                    if (!(far::a_bound(s, lo + 0.5 * L, 0.5 * L) > 0.0f)) continue;
                    const std::uint64_t key = speck_cell_key(si, ijk);
                    auto it = cells.find(key);
                    if (it == cells.end()) {
                        Cell cell;
                        cell.u = u;
                        const auto rocks = generate_near_cell(s, NearClass::Large, ijk, near_, cat_);
                        for (std::size_t n = 0; n < rocks.size(); ++n) {
                            const NearRock& r = rocks[n];
                            const glm::vec3 alb = r.rock >= 0 && r.rock < static_cast<int>(albedo_.size())
                                ? albedo_[static_cast<std::size_t>(r.rock)] : glm::vec3(0.4f);
                            cell.rocks.push_back(RockSpeckGpu{glm::vec3(0.0f), r.radius, alb, u,
                                                              speck_shape_seed(r.pos_sys)});
                            cell.pos_sys.push_back(r.pos_sys);
                            cell.keys.push_back(near_rock_key(s.id, NearClass::Large, ijk, n));
                        }
                        it = cells.emplace(key, std::move(cell)).first;
                        ++out.generated;
                    }
                    it->second.live = true;
                }
            }
        }
    }
    for (auto it = cells.begin(); it != cells.end();) {
        if (!it->second.live) { it = cells.erase(it); continue; }
        Cell& cell = it->second;
        for (std::size_t n = 0; n < cell.rocks.size(); ++n) {
            if (!job.excluded.empty() && job.excluded.count(cell.keys[n])) continue;
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
