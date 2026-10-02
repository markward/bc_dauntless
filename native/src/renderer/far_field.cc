// native/src/renderer/far_field.cc
#include "renderer/far_field.h"
#include <algorithm>
#include <cmath>
#include <tuple>
#include <glm/gtc/matrix_access.hpp>
#include <glm/gtc/matrix_transform.hpp>
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
glm::mat3 rotation(float angle, const glm::vec3& axis) {
    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, axis));
}

// Frustum planes (Gribb-Hartmann), normalised: as MinorField::build_bins.
struct Frustum {
    glm::vec4 planes[6];
    explicit Frustum(const glm::mat4& vp) {
        const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                        r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
        planes[0] = r3 + r0; planes[1] = r3 - r0; planes[2] = r3 + r1;
        planes[3] = r3 - r1; planes[4] = r3 + r2; planes[5] = r3 - r2;
        for (auto& p : planes) p /= glm::length(glm::vec3(p));
    }
    // False when the sphere lies entirely outside any plane.
    bool sphere(const glm::vec3& c, float r) const {
        for (const auto& pl : planes)
            if (glm::dot(glm::vec3(pl), c) + pl.w < -r) return false;
        return true;
    }
};

std::uint64_t cell_key(std::uint32_t source, int pop, int cls, const glm::i64vec3& ijk) {
    std::uint64_t h = mix(source, static_cast<std::uint64_t>(pop));
    h = mix(h, static_cast<std::uint64_t>(cls));
    h = mix(h, static_cast<std::uint64_t>(ijk.x));
    h = mix(h, static_cast<std::uint64_t>(ijk.y));
    return mix(h, static_cast<std::uint64_t>(ijk.z));
}

// Only a procedural DISC with a table generates rocks: a sphere (tile field)
// has real minors, and the cell filters below are disc-shaped.
bool generates(const DiscSource& s) {
    return s.procedural && s.shape == DiscSource::Shape::Disc && !s.table.empty();
}

bool same_pop(const Population& a, const Population& b) {
    return a.kind == b.kind && a.density_at_1 == b.density_at_1 && a.a_lo == b.a_lo &&
           a.a_hi == b.a_hi && a.size.r_min == b.size.r_min && a.size.r_max == b.size.r_max &&
           a.size.q == b.size.q && a.rocks == b.rocks && a.weights == b.weights;
}

// Every input generate_cell / the cell walk reads.
bool same_generator(const DiscSource& a, const DiscSource& b) {
    if (!(a.id == b.id && a.frame == b.frame && a.centre == b.centre && a.normal == b.normal &&
          a.table == b.table && a.outer_fade_gu == b.outer_fade_gu &&
          a.scale_height_frac == b.scale_height_frac &&
          a.scale_height_min_gu == b.scale_height_min_gu && a.seed == b.seed &&
          a.explicit_regions == b.explicit_regions && a.pops.size() == b.pops.size()))
        return false;
    for (std::size_t i = 0; i < a.pops.size(); ++i)
        if (!same_pop(a.pops[i], b.pops[i])) return false;
    return true;
}

bool same_generators(const std::vector<DiscSource>& a, const std::vector<DiscSource>& b) {
    std::vector<const DiscSource*> ga, gb;
    for (const auto& s : a) if (generates(s)) ga.push_back(&s);
    for (const auto& s : b) if (generates(s)) gb.push_back(&s);
    if (ga.size() != gb.size()) return false;
    for (std::size_t i = 0; i < ga.size(); ++i)
        if (!same_generator(*ga[i], *gb[i])) return false;
    return true;
}

bool same_gen(const GenParams& a, const GenParams& b) {
    return a.k_ref == b.k_ref && a.p_min == b.p_min && a.size_classes == b.size_classes &&
           a.cells_per_range == b.cells_per_range;
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

// Sphere density (tile-field haze): 1 within R(1 - edge_frac), a linear
// ramp to 0 at R. far_haze.frag's sphere_a is the GLSL twin.
float sphere_a(const DiscSource& s, const glm::dvec3& x) {
    const double R = s.sphere_radius_gu;
    const double d = glm::length(x - s.centre);
    if (!(R > 0.0) || d >= R) return 0.0f;
    const double inner = R * (1.0 - std::clamp(static_cast<double>(s.sphere_edge_frac), 0.0, 1.0));
    if (d <= inner) return 1.0f;
    return static_cast<float>((R - d) / (R - inner));
}

float density_a(const DiscSource& s, const glm::dvec3& x) {
    if (s.shape == DiscSource::Shape::Sphere) return sphere_a(s, x);
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

bool haze_interval(const DiscSource& s, const glm::dvec3& origin, const glm::vec3& dir_f,
                   float t_max, float slab_sigmas, double& t0, double& t1) {
    if (s.shape == DiscSource::Shape::Sphere) {
        // Ray |d + t dir| <= R, clipped to [0, t_max]. far_haze.frag twin.
        const double R = s.sphere_radius_gu;
        if (!(R > 0.0)) return false;
        const glm::dvec3 dir(dir_f), d = origin - s.centre;
        const double qa = glm::dot(dir, dir), qb = 2.0 * glm::dot(d, dir),
                     qc = glm::dot(d, d) - R * R;
        if (qa < 1e-12) return false;
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        const double sq = std::sqrt(disc);
        t0 = std::max(0.0, (-qb - sq) / (2.0 * qa));
        t1 = std::min(static_cast<double>(t_max), (-qb + sq) / (2.0 * qa));
        return t1 > t0;
    }
    if (s.table.empty()) return false;
    const double R = static_cast<double>(s.table.back().x) + std::max(0.0f, s.outer_fade_gu);
    const double Z = static_cast<double>(slab_sigmas) * scale_height(s, static_cast<float>(R));
    const glm::dvec3 n(s.normal), dir(dir_f), d = origin - s.centre;
    t0 = 0.0;
    t1 = t_max;
    // Slab |z0 + t dz| <= Z.
    const double z0 = glm::dot(d, n), dz = glm::dot(dir, n);
    if (std::fabs(dz) < 1e-12) {
        if (std::fabs(z0) > Z) return false;
    } else {
        const double a = (-Z - z0) / dz, b = (Z - z0) / dz;
        t0 = std::max(t0, std::min(a, b));
        t1 = std::min(t1, std::max(a, b));
    }
    // Cylinder |p + t v| <= R in the disc plane.
    const glm::dvec3 p = d - n * z0, v = dir - n * dz;
    const double qa = glm::dot(v, v), qb = 2.0 * glm::dot(p, v), qc = glm::dot(p, p) - R * R;
    if (qa < 1e-12) {
        if (qc > 0.0) return false;
    } else {
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) return false;
        const double sq = std::sqrt(disc);
        t0 = std::max(t0, (-qb - sq) / (2.0 * qa));
        t1 = std::min(t1, (-qb + sq) / (2.0 * qa));
    }
    return t1 > t0;
}

HazeSample haze_column(const DiscSource& s, const glm::dvec3& origin, const glm::vec3& dir,
                       float t_max, float k, float p_min, float slab_sigmas, int steps,
                       float gain, const glm::vec3& light) {
    HazeSample out;
    double t0 = 0.0, t1 = 0.0;
    if (steps < 1 || !haze_interval(s, origin, dir, t_max, slab_sigmas, t0, t1)) return out;
    const double dt = (t1 - t0) / steps;
    float T = 1.0f;
    for (int i = 0; i < steps; ++i) {
        const double t = t0 + (i + 0.5) * dt;
        const float a = density_a(s, origin + glm::dvec3(dir) * t);
        const float r_cut = p_min * static_cast<float>(t) / k;
        float sum = 0.0f;
        glm::vec3 sum_albedo(0.0f);
        for (const Population& P : s.pops) {
            const float ns = pop_density(P, a) * cross_section_below(P.size, r_cut);
            sum += ns;
            sum_albedo += ns * P.albedo;
        }
        if (!(sum > 0.0f)) continue;
        const float dtau = gain * s.gain_scale * sum * static_cast<float>(dt);
        const float ext = std::exp(-dtau);
        out.rgb += T * (1.0f - ext) * (sum_albedo / sum) * light;
        T *= ext;
    }
    out.alpha = 1.0f - T;
    return out;
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

ViewBasis make_view_basis(const glm::vec3& dir) {
    // Copy of native/src/rockgen/src/impostor.cc:make_basis — the bake's rule.
    const glm::vec3 up_ref = (std::abs(dir.y) > 0.99f) ? glm::vec3(1.0f, 0.0f, 0.0f)
                                                        : glm::vec3(0.0f, 1.0f, 0.0f);
    const glm::vec3 forward = -dir;   // the direction the bake camera looks
    const glm::vec3 right = glm::normalize(glm::cross(up_ref, forward));
    const glm::vec3 up = glm::cross(forward, right);
    return {dir, right, up};
}

glm::mat3 gltf_to_bc() {
    return glm::mat3(glm::vec3(-1, 0, 0), glm::vec3(0, 0, 1), glm::vec3(0, 1, 0));
}

void FarField::set_dials(const FarDials& d) {
    if (!same_gen(d.gen, dials_.gen)) cache_.clear();
    dials_ = d;
}

void FarField::set_catalogue(std::vector<CatalogueRock> cat, std::vector<glm::vec3> view_dirs_gltf) {
    catalogue_ = std::move(cat);
    view_dirs_ = std::move(view_dirs_gltf);
}

void FarField::set_sources(std::vector<DiscSource> s) {
    // A tile (non-generating) source change keeps the belt cells.
    if (!same_generators(sources_, s)) cache_.clear();
    sources_ = std::move(s);
    refresh_active();
}

void FarField::set_rocks(std::vector<FlaggedRock> r) { rocks_ = std::move(r); }

void FarField::set_frame(std::optional<std::string> system, const glm::dvec3& anchor_sys) {
    frame_ = std::move(system);
    anchor_ = anchor_sys;
    refresh_active();
}

void FarField::clear() {
    sources_.clear();
    active_.clear();
    rocks_.clear();
    frame_.reset();
    anchor_ = glm::dvec3(0.0);
    cache_.clear();
}

void FarField::refresh_active() {
    active_.clear();
    for (const auto& s : sources_) {
        if (s.view_space) {
            // View space -> system: + anchor (0 for an unmapped set).
            active_.push_back(s);
            active_.back().centre = s.centre + anchor_;
        } else if (frame_ && s.frame == *frame_) {
            active_.push_back(s);
        }
    }
}

const std::vector<FarRock>& FarField::fetch(const DiscSource& s, int pop, int cls,
                                            const glm::i64vec3& ijk) {
    const std::uint64_t key = cell_key(s.id, pop, cls, ijk);
    auto it = cache_.find(key);
    if (it == cache_.end())
        it = cache_.emplace(key, CachedCell{generate_cell(s, pop, cls, ijk, dials_.gen), 0}).first;
    it->second.last_used = frame_counter_;
    return it->second.rocks;
}

void FarField::evict() {
    const std::size_t cap = static_cast<std::size_t>(std::max(0, dials_.cell_cache_max));
    if (cache_.size() <= cap) return;
    const std::size_t keep = cap * 9 / 10;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> age;   // (last_used, key)
    age.reserve(cache_.size());
    for (const auto& [k, c] : cache_) age.emplace_back(c.last_used, k);
    const std::size_t drop = cache_.size() - keep;
    std::nth_element(age.begin(), age.begin() + static_cast<std::ptrdiff_t>(drop), age.end());
    for (std::size_t i = 0; i < drop; ++i) cache_.erase(age[i].second);
}

void FarField::drop_impostor(int index) {
    if (index >= 0 && static_cast<std::size_t>(index) < catalogue_.size())
        catalogue_[static_cast<std::size_t>(index)].has_impostor = false;
}

void FarField::build(const BuildInput& in, FarOutput& out) {
    out.impostors.clear();
    out.specks.clear();
    out.fades.clear();
    out.generated = 0;
    out.cells = 0;
    ++frame_counter_;

    const float k = pixels_per_gu(in.proj, in.viewport_h);
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const glm::mat3 M = gltf_to_bc();
    const TierDials& td = dials_.tiers;

    std::vector<std::vector<ImpostorGpu>> bins(catalogue_.size());
    auto albedo_of = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size()
                   ? catalogue_[static_cast<std::size_t>(index)].avg_albedo
                   : glm::vec3(0.4f);
    };
    auto has_impostor = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size() &&
               catalogue_[static_cast<std::size_t>(index)].has_impostor;
    };
    // Step 3: the baked view nearest the eye in the rock's own frame.
    auto emit_impostor = [&](int index, const glm::vec3& c, const glm::mat3& R, float r, float w) {
        if (!has_impostor(index) || view_dirs_.empty()) return;
        const glm::vec3 to_eye = glm::transpose(R) * (eye - c);
        const float len = glm::length(to_eye);
        const glm::vec3 e_g = M * (len > 0.0f ? to_eye / len : glm::vec3(0, 0, 1));
        std::size_t best = 0;
        float best_dot = -2.0f;
        for (std::size_t i = 0; i < view_dirs_.size(); ++i) {
            const float d = glm::dot(view_dirs_[i], e_g);
            if (d > best_dot) { best_dot = d; best = i; }
        }
        const ViewBasis b = make_view_basis(view_dirs_[best]);
        const glm::vec3 right_w = R * (M * b.right), up_w = R * (M * b.up);
        bins[static_cast<std::size_t>(index)].push_back(
            ImpostorGpu{glm::vec4(c, r * 1.02f), glm::vec4(right_w, static_cast<float>(best)),
                        glm::vec4(up_w, -w)});
    };

    // Step 2: flagged (explicit) rocks.
    // Every flagged rock gets a fade entry; one we cannot place is mesh-only
    // (0), so the host never keeps a stale fade that hides the mesh.
    for (const auto& fr : rocks_) {
        glm::mat4 W(1.0f);
        const bool placed = in.world_of && in.world_of(fr.key, W);
        const float s = placed ? glm::length(glm::vec3(W[0])) : 0.0f;
        if (!(s > 0.0f)) { out.fades.emplace_back(fr.key, 0.0f); continue; }
        const glm::vec3 c(W[3]);
        const glm::mat3 R = glm::mat3(W) / s;
        const float r = fr.radius_mu * s;
        const float d = glm::length(c - eye);
        const float p = r * k / std::max(d, 1e-3f);
        const Kind kind = has_impostor(fr.index) ? Kind::Explicit : Kind::ExplicitNoImpostor;
        const TierWeights w = tier_weights(p, kind, td);
        out.fades.emplace_back(fr.key, 1.0f - w.mesh);   // culled ones too: fade stays current
        if (!frustum.sphere(c, r)) continue;
        if (w.impostor > 0.0f) emit_impostor(fr.index, c, R, r, w.impostor);
        if (w.speck > 0.0f) out.specks.push_back(SpeckGpu{c, p, albedo_of(fr.index), w.speck});
    }

    // Step 4: enumerate the active sources' cells, nearest first.
    if (frame_ && !active_.empty()) {
        const glm::dvec3 eye_sys = in.render_origin + glm::dvec3(eye) + anchor_;
        const glm::dvec3 to_render = anchor_ + in.render_origin;
        struct Cand { double dist; std::uint32_t src; int pop, cls; glm::i64vec3 ijk; };
        std::vector<Cand> cands;
        const double half_diag_unit = std::sqrt(3.0) * 0.5;
        for (std::uint32_t si = 0; si < active_.size(); ++si) {
            const DiscSource& s = active_[si];
            if (!generates(s)) continue;
            const double rho_max = static_cast<double>(s.table.back().x) + s.outer_fade_gu;
            for (int pi = 0; pi < static_cast<int>(s.pops.size()); ++pi) {
                const auto classes = size_classes(s.pops[static_cast<std::size_t>(pi)], dials_.gen);
                for (int ci = 0; ci < static_cast<int>(classes.size()); ++ci) {
                    const ClassBin& B = classes[static_cast<std::size_t>(ci)];
                    const double L = B.cell_gu;
                    // Telephoto guard: D grows with k, so cap the span at
                    // max_cells_per_axis cells per axis.
                    const double D = std::min(static_cast<double>(k) * B.r_hi / td.p_min,
                                              0.5 * dials_.max_cells_per_axis * L);
                    if (!(D > 0.0) || !(L > 0.0)) continue;
                    const double hd = L * half_diag_unit;
                    const glm::i64vec3 lo(glm::floor((eye_sys - D) / L));
                    const glm::i64vec3 hi(glm::floor((eye_sys + D) / L));
                    for (auto i = lo.x; i <= hi.x; ++i)
                        for (auto j = lo.y; j <= hi.y; ++j)
                            for (auto kk = lo.z; kk <= hi.z; ++kk) {
                                const glm::dvec3 bmin = glm::dvec3(i, j, kk) * L;
                                const glm::dvec3 q = glm::clamp(eye_sys, bmin, bmin + L);
                                const double dist = glm::length(q - eye_sys);
                                if (dist > D) continue;                         // (a)
                                const glm::dvec3 centre = bmin + 0.5 * L;
                                if (!frustum.sphere(glm::vec3(centre - to_render),
                                                    static_cast<float>(hd)))
                                    continue;                                   // (b)
                                double rho, z;
                                disc_coords(s, centre, rho, z);
                                if (std::fabs(z) - hd > dials_.slab_sigmas *
                                        scale_height(s, static_cast<float>(rho + L)))
                                    continue;                                   // (c) slab
                                if (rho - hd > rho_max) continue;               // (c) outer
                                cands.push_back({dist, si, pi, ci, {i, j, kk}});
                            }
                }
            }
        }
        std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
            if (a.dist != b.dist) return a.dist < b.dist;
            return std::tie(a.src, a.pop, a.cls, a.ijk.x, a.ijk.y, a.ijk.z) <
                   std::tie(b.src, b.pop, b.cls, b.ijk.x, b.ijk.y, b.ijk.z);
        });

        // Step 5: each walked cell's rocks through the ladder.
        for (const Cand& cd : cands) {
            if (out.generated >= dials_.max_far_rocks) break;
            const DiscSource& s = active_[cd.src];
            const Kind kind = s.pops[static_cast<std::size_t>(cd.pop)].kind == 1
                                  ? Kind::ProceduralMajor : Kind::ProceduralMinor;
            const auto& rocks = fetch(s, cd.pop, cd.cls, cd.ijk);
            ++out.cells;
            out.generated += static_cast<int>(rocks.size());
            for (const FarRock& fr : rocks) {
                const glm::vec3 c(fr.pos_sys - to_render);
                const float d = glm::length(c - eye);
                const float p = fr.radius * k / std::max(d, 1e-3f);
                const TierWeights w = tier_weights(p, kind, td);
                if (!(w.impostor > 0.0f) && !(w.speck > 0.0f)) continue;
                if (!frustum.sphere(c, fr.radius)) continue;
                if (w.impostor > 0.0f) {
                    const float angle = fr.phase + fr.tumble_rate * static_cast<float>(in.game_time);
                    emit_impostor(fr.rock, c, rotation(angle, fr.tumble_axis), fr.radius, w.impostor);
                }
                if (w.speck > 0.0f) out.specks.push_back(SpeckGpu{c, p, albedo_of(fr.rock), w.speck});
            }
        }
    }

    for (std::size_t i = 0; i < bins.size(); ++i)
        if (!bins[i].empty())
            out.impostors.push_back(ImpostorBin{static_cast<int>(i), std::move(bins[i])});
    evict();
}

}  // namespace renderer::far
