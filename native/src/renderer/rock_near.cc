// native/src/renderer/rock_near.cc
// Rock fields, near band: deterministic cells and streaming
// (docs/superpowers/specs/2026-10-02-rock-fields-design.md).
#include "renderer/rock_near.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <tuple>
#include <utility>
#include <glm/gtc/matrix_access.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/rock_random.h>
#include "rock_field_common.h"

namespace renderer::rockfield {
namespace {
using rockrand::Rng;

using detail::mix;
using detail::Frustum;
using glm_exact::dot3;

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
// (length(p - clamp(p, lo, lo + size)), bit for bit, as scalars: glm's
// clamp is min(max(x, lo), hi) with max = x < y ? y : x, min = y < x ? y : x.)
double aabb_distance(const glm::dvec3& p, const glm::dvec3& lo, double size) {
    auto axis = [size](double x, double l) {
        const double h = l + size;
        const double m = x < l ? l : x;
        const double q = h < m ? h : m;
        return x - q;
    };
    const double dx = axis(p.x, lo.x), dy = axis(p.y, lo.y), dz = axis(p.z, lo.z);
    return std::sqrt(glm_exact::dot3(dx, dy, dz, dx, dy, dz));
}

// False when no point within `range` of `c` can have density in `s`.
bool reaches(const far::DiscSource& s, const glm::dvec3& c, double range) {
    if (s.shape == far::DiscSource::Shape::Sphere)
        return s.sphere_radius_gu > 0.0f &&
               glm::length(c - s.centre) <= static_cast<double>(s.sphere_radius_gu) + range;
    return far::a_bound(s, c, range) > 0.0f;
}

constexpr NearClass kClasses[] = {NearClass::Small, NearClass::Large};

// The streamed ranges of one class. A class never spans more than
// kMaxCellsPerAxis cells per axis (Task 4 review): (billboard + margin) is
// shrunk to 16 cells, never the cells widened -- a huge billboard_gu over a
// tiny cell_gu would otherwise enumerate (2R/L)^3 cells in one stream().
constexpr int kMaxCellsPerAxis = 33;
struct StreamRanges { double gen, keep; };
StreamRanges stream_ranges(const NearClassDials& cd, double margin) {
    const double cap = 0.5 * (kMaxCellsPerAxis - 1) * static_cast<double>(cd.cell_gu);
    const double keep = std::min(static_cast<double>(cd.billboard_gu) + std::max(margin, 0.0), cap);
    return {std::min(static_cast<double>(cd.billboard_gu), keep), keep};
}

// Rock -> render rotation, as MinorField poses fragment meshes (the loaded
// catalogue mesh is already in BC axes; make_impostor maps to glTF itself).
// (glm::mat3(glm::rotate(glm::mat4(1), angle, axis)), bit for bit.)
glm::mat3 rotation(float angle, const glm::vec3& axis) {
    return glm_exact::rotation(angle, axis);
}

// How far the centre may move from a full stream pass's reference before
// the next full pass (NearField::stream's incremental path). Larger: fewer
// full passes, more watched cells per frame.
constexpr double kStreamWatchGu = 2.0;
// Slack for the Lipschitz bounds against double rounding in aabb_distance.
constexpr double kStreamEps = 1e-6;

float ramp_down(float d, float end, float fade) {   // 1 at end - fade, 0 at end
    if (!(fade > 0.0f)) return d < end ? 1.0f : 0.0f;
    if (d <= end - fade) return 1.0f;
    if (d >= end) return 0.0f;
    return (end - d) / fade;
}
}  // namespace

NearWeights near_weights(float d, const NearClassDials& c, float fade_gu) {
    NearWeights w;
    w.mesh = ramp_down(d, c.mesh_gu, fade_gu);
    w.billboard = std::min(1.0f - w.mesh, ramp_down(d, c.billboard_gu, fade_gu));
    return w;
}

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
    invalidate_stream_watch();   // ranges may have moved
    if (regen) clear();
}

void NearField::set_catalogue(NearCatalogue c) {
    cat_ = std::move(c);
    views_ = far::make_impostor_views(cat_.view_dirs_gltf);
    clear();
}

void NearField::invalidate_stream_watch() {
    gen_watch_.clear();
    drop_valid_ = false;
    drop_watch_.clear();
}

void NearField::set_sources(const std::vector<far::DiscSource>& active) {
    const bool same = active.size() == sources_.size() &&
                      std::equal(active.begin(), active.end(), sources_.begin(),
                                 [](const far::DiscSource& a, const far::DiscSource& b) {
                                     return same_generator(a, b);
                                 });
    sources_ = active;
    invalidate_stream_watch();
    if (!same) clear();
}

void NearField::stream(const glm::dvec3& c) {
    // Byte-for-byte the effect of: drop every non-pinned cell farther than
    // its class's keep range, then (sources outer, classes inner, cells in
    // (i, j, k) order) generate every missing cell within the generation
    // range. A full pass does exactly that and records which cells sit
    // within kStreamWatchGu of either threshold; while the centre stays
    // within kStreamWatchGu of that pass, only those cells (and cells
    // generated since) can change state, so only they are re-tested.
    auto keep_of = [&](NearClass cls) {
        return stream_ranges(class_dials(dials_, cls), dials_.stream_margin_gu).keep;
    };
    if (!drop_valid_ || glm::length(c - drop_ref_) > kStreamWatchGu) {
        drop_watch_.clear();
        for (auto it = cells_.begin(); it != cells_.end();) {
            const Cell& cell = it->second;
            const double keep = keep_of(cell.cls);
            const double d = cell.pinned ? 0.0 : aabb_distance(c, cell.lo, cell.size);
            if (!cell.pinned && d > keep) {
                if (cell.cls == NearClass::Large && cell.seen_step == step_count_)
                    dropped_seen_[it->first] = cell.seen_rocks;
                it = cells_.erase(it);
                continue;
            }
            if (!cell.pinned && d > keep - kStreamWatchGu - kStreamEps) drop_watch_.push_back(it->first);
            ++it;
        }
        drop_ref_ = c;
        drop_valid_ = true;
    } else {
        for (const std::uint64_t key : drop_watch_) {
            const auto it = cells_.find(key);
            if (it == cells_.end() || it->second.pinned) continue;
            const Cell& cell = it->second;
            if (aabb_distance(c, cell.lo, cell.size) > keep_of(cell.cls)) {
                if (cell.cls == NearClass::Large && cell.seen_step == step_count_)
                    dropped_seen_[it->first] = cell.seen_rocks;
                cells_.erase(it);
            }
        }
    }

    if (gen_watch_.size() != sources_.size() * 2) gen_watch_.assign(sources_.size() * 2, GenWatch{});
    auto generate = [&](const far::DiscSource& s, NearClass cls, const glm::i64vec3& ijk,
                        const glm::dvec3& lo, double L) {
        const std::uint64_t key = cell_key(s.id, cls, ijk);
        if (cells_.count(key)) return;
        Cell cell{cls, generate_near_cell(s, cls, ijk, dials_, cat_), lo, L, false, {}};
        for (const NearRock& r : cell.rocks) cell.r_max = std::max(cell.r_max, r.radius);
        if (const auto ds = dropped_seen_.find(key); ds != dropped_seen_.end()) {
            cell.seen_step = step_count_;
            cell.seen_rocks = ds->second;
        }
        cells_.emplace(key, std::move(cell));
        if (drop_valid_) drop_watch_.push_back(key);
    };
    for (std::size_t si = 0; si < sources_.size(); ++si) {
        const far::DiscSource& s = sources_[si];
        for (NearClass cls : kClasses) {
            const NearClassDials& cd = class_dials(dials_, cls);
            const double L = cd.cell_gu, R = stream_ranges(cd, dials_.stream_margin_gu).gen;
            if (!(L > 0.0) || !(R > 0.0) || !reaches(s, c, R)) continue;
            // A cell is generated when it lies in the box [floor((c - R) / L),
            // floor((c + R) / L)] AND within R of c. (The box test is not
            // redundant: a cell exactly R below c on an axis is outside it.)
            const glm::i64vec3 ga(glm::floor((c - R) / L)), gb(glm::floor((c + R) / L));
            const auto in_box = [&](const glm::i64vec3& ijk) {
                return ijk.x >= ga.x && ijk.x <= gb.x && ijk.y >= ga.y && ijk.y <= gb.y &&
                       ijk.z >= ga.z && ijk.z <= gb.z;
            };
            GenWatch& w = gen_watch_[si * 2 + static_cast<std::size_t>(cls)];
            const double moved = glm::length(c - w.c_ref);
            if (w.valid && moved <= kStreamWatchGu) {
                for (const glm::i64vec3& ijk : w.shell) {
                    if (!in_box(ijk)) continue;
                    const glm::dvec3 lo = glm::dvec3(ijk) * L;
                    if (aabb_distance(c, lo, L) > R) continue;
                    generate(s, cls, ijk, lo, L);
                }
                continue;
            }
            // Full pass over the cells within R + w (a superset of the old
            // R box, same (i, j, k) order), generating those within R. At
            // dash speed (the centre moved several watch widths since the
            // last pass) the next frame will not be inside this one's watch
            // either: skip recording the shell (w = 0 enumerates the R box).
            w.shell.clear();
            const bool record = !w.has_ref || moved <= 4.0 * kStreamWatchGu;
            const double Rw = R + (record ? kStreamWatchGu : 0.0);
            const glm::i64vec3 a(glm::floor((c - Rw) / L)), b(glm::floor((c + Rw) / L));
            for (auto i = a.x; i <= b.x; ++i)
                for (auto j = a.y; j <= b.y; ++j)
                    for (auto k = a.z; k <= b.z; ++k) {
                        const glm::i64vec3 ijk(i, j, k);
                        const glm::dvec3 lo = glm::dvec3(ijk) * L;
                        const double d = aabb_distance(c, lo, L);
                        if (record && d > R - kStreamWatchGu - kStreamEps && d <= Rw + kStreamEps)
                            w.shell.push_back(ijk);
                        if (d > R || !in_box(ijk)) continue;
                        generate(s, cls, ijk, lo, L);
                    }
            w.c_ref = c;
            w.has_ref = true;
            w.valid = record;
        }
    }
}

void NearField::clear() {
    cells_.clear();
    invalidate_stream_watch();
    stepped_ = false;
    has_prev_ = false;
    dropped_seen_.clear();
    ghosts_.clear();
    large_last_.clear();
    shoves_.clear();
    large_contacts_.clear();   // a pending touch would hit a dead mission's rock
    small_contacts_.clear();
}

std::uint64_t NearField::key_of(std::uint64_t cell, const Cell& c, std::size_t i) const {
    return c.pinned ? c.keys[i] : rock_key(cell, i);
}

void NearField::debug_add_rock(NearClass cls, std::uint64_t key, const NearRock& r) {
    // Fixed keys outside the hashed space in practice; one test cell per class.
    const std::uint64_t ck = 0x7E57CE11000000ull | static_cast<std::uint64_t>(cls);
    Cell& c = cells_[ck];
    c.cls = cls;
    c.pinned = true;
    c.rocks.push_back(r);
    c.keys.push_back(key);
    c.r_max = std::max(c.r_max, r.radius);
}

NearStats NearField::stats() const {
    NearStats st;
    st.cells = static_cast<int>(cells_.size());
    st.ghosted = static_cast<int>(ghosts_.size());
    for (const auto& [key, cell] : cells_)
        (cell.cls == NearClass::Small ? st.small : st.large) += static_cast<int>(cell.rocks.size());
    return st;
}

void NearField::for_each(NearClass cls,
                         const std::function<void(std::uint64_t, const NearRock&)>& fn) const {
    for (const auto& [key, cell] : cells_) {
        if (cell.cls != cls) continue;
        for (std::size_t i = 0; i < cell.rocks.size(); ++i) fn(key_of(key, cell, i), cell.rocks[i]);
    }
}

void NearField::build(const NearBuildInput& in, NearOutput& out) const {
    out.meshes.clear();
    out.billboards.clear();
    out.mesh_count = out.billboard_count = 0;

    const float k = far::pixels_per_gu(in.proj, in.viewport_h);
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const glm::dvec3 to_render = in.anchor_sys + in.render_origin;
    const float t = static_cast<float>(in.game_time);

    std::map<std::tuple<int, int, int>, std::vector<minors::InstanceGpu>> mesh_bins;
    std::map<int, std::vector<far::ImpostorGpu>> board_bins;

    // Cells holding a shoved (small) rock: their rocks may sit off the cell,
    // so they skip the cell broad phase and look up their shoves.
    std::vector<std::uint64_t> shoved_cells;
    shoved_cells.reserve(shoves_.size());
    for (const auto& [key, sh] : shoves_) { (void)key; shoved_cells.push_back(sh.cell); }
    std::sort(shoved_cells.begin(), shoved_cells.end());
    const float eye_len = glm::length(eye);

    struct Cand { float d; glm::vec3 c; NearWeights w; const NearRock* rock; float spin; };
    for (NearClass cls : kClasses) {
        const NearClassDials& cd = class_dials(dials_, cls);
        const bool small = cls == NearClass::Small;
        const std::vector<int>& rocks = small ? cat_.small_rocks : cat_.large_rocks;
        const std::vector<float>& bounds = small ? cat_.small_bound_mu : cat_.large_bound_mu;
        const int family = small ? kNearSmallFamily : kNearLargeFamily;
        // Neither tier draws at camera distance >= max(mesh_gu, billboard_gu).
        const float d_max = std::max(cd.mesh_gu, cd.billboard_gu);

        std::vector<Cand> cands;
        for (const auto& [key, cell] : cells_) {
            if (cell.cls != cls || cell.rocks.empty()) continue;
            const bool shoved = small && !shoved_cells.empty() &&
                                std::binary_search(shoved_cells.begin(), shoved_cells.end(), key);
            if (!cell.pinned && !shoved) {
                // Cell broad phase: every rock centre lies within the cell's
                // half-diagonal of its centre, so a cell wholly beyond d_max
                // or wholly outside a frustum plane (by its largest rock's
                // radius) holds no rock the per-rock tests below would keep.
                const double h = 0.5 * cell.size;
                const glm::vec3 cc(static_cast<float>(cell.lo.x + h - to_render.x),
                                   static_cast<float>(cell.lo.y + h - to_render.y),
                                   static_cast<float>(cell.lo.z + h - to_render.z));
                const float half_diag = static_cast<float>(0.8660254037844386 * cell.size);
                const float dx = cc.x - eye.x, dy = cc.y - eye.y, dz = cc.z - eye.z;
                const float slack = 0.01f + 1e-5f * (std::fabs(cc.x) + std::fabs(cc.y) +
                                                     std::fabs(cc.z) + eye_len);
                if (std::sqrt(dot3(dx, dy, dz, dx, dy, dz)) - half_diag - slack >= d_max) continue;
                if (!frustum.sphere(cc, half_diag + cell.r_max + slack)) continue;
            }
            for (std::size_t i = 0; i < cell.rocks.size(); ++i) {
                const NearRock& r = cell.rocks[i];
                // vec3(pos_sys - to_render) and length(c - eye), as scalars.
                glm::vec3 c(static_cast<float>(r.pos_sys.x - to_render.x),
                            static_cast<float>(r.pos_sys.y - to_render.y),
                            static_cast<float>(r.pos_sys.z - to_render.z));
                float spin = 0.0f;
                if (shoved)
                    if (auto sh = shoves_.find(key_of(key, cell, i)); sh != shoves_.end()) {
                        c += sh->second.s.offset;
                        spin = sh->second.s.spin;
                    }
                const float ex = c.x - eye.x, ey = c.y - eye.y, ez = c.z - eye.z;
                const float d = std::sqrt(dot3(ex, ey, ez, ex, ey, ez));
                const NearWeights w = near_weights(d, cd, dials_.fade_gu);
                if (!(w.mesh > 0.0f) && !(w.billboard > 0.0f)) continue;
                if (!frustum.sphere(c, r.radius)) continue;
                cands.push_back({d, c, w, &r, spin});
            }
        }
        // Nearest first so the cap drops the far end; ties by catalogue index
        // and position keep the order independent of the cell map's order.
        std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
            if (a.d != b.d) return a.d < b.d;
            if (a.rock->rock != b.rock->rock) return a.rock->rock < b.rock->rock;
            return std::tie(a.c.x, a.c.y, a.c.z) < std::tie(b.c.x, b.c.y, b.c.z);
        });

        int emitted = 0;
        for (const Cand& cn : cands) {
            if (emitted >= cd.max_instances) break;
            const NearRock& r = *cn.rock;
            const glm::mat3 R = rotation(r.phase + r.tumble_rate * t + cn.spin, r.tumble_axis);
            if (cn.w.mesh > 0.0f) {
                const auto it = std::find(rocks.begin(), rocks.end(), r.rock);
                const std::size_t slot = static_cast<std::size_t>(it - rocks.begin());
                if (it != rocks.end() && slot < bounds.size() && bounds[slot] > 0.0f) {
                    const glm::mat3 rs = R * (r.radius / bounds[slot]);
                    minors::InstanceGpu g;   // rows of [R*s | t]; glm is column-major: rs[col][row]
                    g.row0 = {rs[0][0], rs[1][0], rs[2][0], cn.c.x};
                    g.row1 = {rs[0][1], rs[1][1], rs[2][1], cn.c.y};
                    g.row2 = {rs[0][2], rs[1][2], rs[2][2], cn.c.z};
                    g.extra.x = cn.w.mesh < 1.0f ? 1.0f - cn.w.mesh : 0.0f;
                    const int lod = r.radius * k / std::max(cn.d, 1e-3f) >= in.lod0_pixel_radius ? 0 : 1;
                    mesh_bins[{family, static_cast<int>(slot), lod}].push_back(g);
                    ++emitted;
                }
            }
            if (cn.w.billboard > 0.0f && !cat_.view_dirs_gltf.empty() && emitted < cd.max_instances) {
                const float dither = cn.w.billboard < 1.0f ? -cn.w.billboard : 0.0f;
                board_bins[r.rock].push_back(
                    far::make_impostor(views_, eye, cn.c, R, r.radius, dither));
                ++emitted;
            }
        }
    }

    for (auto& [key, items] : mesh_bins) {
        minors::Bin b;
        std::tie(b.family, b.slot, b.lod) = key;
        out.mesh_count += static_cast<int>(items.size());
        b.items = std::move(items);
        out.meshes.push_back(std::move(b));
    }
    for (auto& [rock, items] : board_bins) {
        out.billboard_count += static_cast<int>(items.size());
        out.billboards.push_back(far::ImpostorBin{rock, std::move(items)});
    }
}

void NearField::step(const NearStepInput& in) {
    const double t = in.game_time;
    // dt <= 0 is a paused frame (or the first): no touches, no integration.
    const double dt = stepped_ ? t - last_time_ : 0.0;
    last_time_ = t;
    stepped_ = true;
    const minors::Dials& md = in.minor_dials;
    const glm::dvec3 to_render = in.anchor_sys + in.render_origin;
    // The seen clock: a large cell the previous step saw has seen_step == prev.
    const std::uint64_t prev = step_count_;
    const std::uint64_t now = ++step_count_;
    dropped_seen_.clear();
    const auto streamed = [&](std::uint64_t cell) { return cells_.count(cell) != 0; };

    // 1. Shoves: forget rocks that left the stream, integrate the rest.
    if (!shoves_.empty()) {
        for (auto it = shoves_.begin(); it != shoves_.end();)
            it = streamed(it->second.cell) ? std::next(it) : shoves_.erase(it);
        if (dt > 0.0)
            for (auto& [key, sh] : shoves_) { (void)key; minors::advance_shove(sh.s, static_cast<float>(dt), md); }
    }
    // Large rocks no longer streamed: their cooldowns and ghosts are dropped.
    for (auto it = large_last_.begin(); it != large_last_.end();)
        it = streamed(it->second.cell) ? std::next(it) : large_last_.erase(it);
    for (auto it = ghosts_.begin(); it != ghosts_.end();)
        it = streamed(it->second) ? std::next(it) : ghosts_.erase(it);

    if (!in.player) {                    // no contacts; the next posed step starts afresh
        has_prev_ = false;
        for (auto& [ckey, cell] : cells_) {
            (void)ckey;
            if (cell.cls != NearClass::Large) continue;
            cell.seen_step = now;
            cell.seen_rocks = cell.rocks.size();
        }
        return;
    }

    // 2. The sweep, render space. The previous centre is kept in SYSTEM space
    // (where the rocks are fixed), so a moved origin or anchor is not travel.
    const minors::PlayerBox& box = *in.player;
    const glm::vec3 c = glm::vec3(box.world * glm::vec4(box.center_mu, 1.0f));
    const bool had_prev = has_prev_;
    const glm::vec3 prev_render = glm::vec3(prev_center_sys_ - to_render);
    has_prev_ = true;
    prev_center_sys_ = glm::dvec3(c) + to_render;

    glm::vec3 seg0 = c, v_player{0.0f};
    if (had_prev && dt > 0.0 && glm::length(c - prev_render) <= md.teleport_gu) {
        seg0 = prev_render;
        v_player = (c - prev_render) / static_cast<float>(dt);
    }                                    // else teleport / no pose: current pose only
    const float rel_speed = glm::length(v_player);
    const glm::vec3 seg = c - seg0;
    const float seg_len2 = glm::dot(seg, seg);
    auto dist_to_segment = [&](const glm::vec3& p) {
        const float u = seg_len2 > 0.0f
            ? std::clamp(glm::dot(p - seg0, seg) / seg_len2, 0.0f, 1.0f) : 0.0f;
        return glm::length(p - (seg0 + seg * u));
    };
    // Cell broad phase: every rock centre p of a cell lies within the cell's
    // half-diagonal of its centre, and dist_to_segment is 1-Lipschitz, so a
    // cell whose centre is farther than half-diagonal + reach (+ float slack)
    // from the sweep holds no rock the per-rock cull would keep.
    // (Scalar code: a conservative bound needs no bit-exactness, only speed
    // in this Debug build.)
    const float seg_scale = std::fabs(c.x) + std::fabs(c.y) + std::fabs(c.z) +
                            std::fabs(seg0.x) + std::fabs(seg0.y) + std::fabs(seg0.z);
    auto cell_lower_bound = [&](const Cell& cell) {
        const double h = 0.5 * cell.size;
        const float px = static_cast<float>(cell.lo.x + h - to_render.x);
        const float py = static_cast<float>(cell.lo.y + h - to_render.y);
        const float pz = static_cast<float>(cell.lo.z + h - to_render.z);
        const float wx = px - seg0.x, wy = py - seg0.y, wz = pz - seg0.z;
        float u = 0.0f;
        if (seg_len2 > 0.0f)
            u = std::clamp((wx * seg.x + wy * seg.y + wz * seg.z) / seg_len2, 0.0f, 1.0f);
        const float qx = wx - seg.x * u, qy = wy - seg.y * u, qz = wz - seg.z * u;
        const float half_diag = static_cast<float>(0.8660254037844386 * cell.size);
        const float slack = 0.01f + 1e-5f * (std::fabs(px) + std::fabs(py) + std::fabs(pz) + seg_scale);
        return std::sqrt(qx * qx + qy * qy + qz * qz) - half_diag - slack;
    };
    // 3. Large rocks: solid, fixed, player only; the box inflated to the
    // shield bubble while shields are up.
    const float inflate = in.shield_inflate > 0.0f ? in.shield_inflate : 1.0f;
    const minors::SweepBox lb = minors::sweep_box_of(box, 0.0f, inflate);
    const float margin = dials_.collide_margin_gu;
    auto gap_now = [&](const glm::vec3& p) {   // rock centre to the shape at the current pose
        return glm::length(p - minors::closest_on_box(lb, c, p));
    };
    int reported = 0;
    for (auto& [ckey, cell] : cells_) {
        if (cell.cls != NearClass::Large) continue;
        // A rock is fresh unless the previous posed step saw it.
        const bool cell_seen = had_prev && cell.seen_step == prev;
        const std::size_t seen_rocks = cell.seen_rocks;
        cell.seen_step = now;
        cell.seen_rocks = cell.rocks.size();
        if (cell.rocks.empty()) continue;
        if (!cell.pinned && cell_lower_bound(cell) > lb.bound + cell.r_max + margin) {
            // No rock here overlaps or is swept: only a ghost is released.
            if (!ghosts_.empty())
                for (std::size_t i = 0; i < cell.rocks.size(); ++i) ghosts_.erase(key_of(ckey, cell, i));
            continue;
        }
        for (std::size_t i = 0; i < cell.rocks.size(); ++i) {
            const std::uint64_t key = key_of(ckey, cell, i);
            const NearRock& r = cell.rocks[i];
            const glm::vec3 p(r.pos_sys - to_render);
            const float reach = r.radius + margin;

            // Ghosting: met overlapping on arrival (stream-in or first posed
            // step) => no touches until a step finds the box clear; the step
            // that releases it reports nothing (the sweep starts inside).
            const bool fresh = !cell_seen || i >= seen_rocks;
            const bool ghost = !ghosts_.empty() && ghosts_.count(key) > 0;
            if (fresh || ghost) {
                const bool overlap = glm::length(p - c) <= lb.bound + reach && gap_now(p) <= reach;
                if (overlap) { ghosts_.emplace(key, ckey); continue; }
                if (ghost) { ghosts_.erase(key); continue; }
            }
            if (!(dt > 0.0) || reported >= md.max_shoves_per_frame) continue;
            if (dist_to_segment(p) > lb.bound + reach) continue;

            float s = 1.0f;
            if (minors::sweep_min_distance(lb, seg0, seg, p, s) > reach) continue;
            // Still penetrating at the current pose: report every step, so the
            // ship cannot press into the rock unanswered -- Python's receding
            // gate (v_rel >= 0) is the debounce, as collisions._respond_pair.
            // The cooldown only silences repeats once the ship is clear.
            const float pen = std::max(0.0f, r.radius - gap_now(p));
            if (auto it = large_last_.find(key);
                !(pen > 0.0f) && it != large_last_.end() &&
                t - it->second.t < dials_.collide_cooldown_s)
                continue;
            large_last_[key] = Touch{t, ckey};

            const glm::vec3 q = minors::closest_on_box(lb, seg0 + seg * s, p);
            glm::vec3 nrm = q - p;               // rock -> ship
            if (glm::length(nrm) > 1e-6f) nrm = glm::normalize(nrm);
            else if (seg_len2 > 1e-12f) nrm = -glm::normalize(seg);
            else if (glm::length(c - p) > 1e-6f) nrm = glm::normalize(c - p);
            else nrm = glm::vec3(0.0f, 0.0f, 1.0f);
            NearContact nc;
            nc.point_view = glm::dvec3(q) + in.render_origin;
            nc.normal = nrm;
            nc.rock_centre_view = glm::dvec3(p) + in.render_origin;
            nc.rock_radius = r.radius;
            nc.rel_speed = rel_speed;
            nc.pen = pen;
            nc.key = key;
            large_contacts_.push_back(nc);
            ++reported;
        }
    }

    // 4. Small rocks: the minors' harmless shove (MinorField::step_contact),
    // against the bare hull box -- shields widen only the large contacts.
    if (!(dt > 0.0)) return;
    const minors::SweepBox sb = minors::sweep_box_of(box, md.contact_margin_gu, 1.0f);
    // A shoved rock sits up to |offset| off its cell: widen that cell's
    // broad phase by its largest offset (decided before any rock of the cell
    // moves this step; a rock's offset only changes while its cell is processed).
    std::vector<std::pair<std::uint64_t, float>> shove_reach;
    shove_reach.reserve(shoves_.size());
    for (const auto& [key, sh] : shoves_) { (void)key; shove_reach.emplace_back(sh.cell, glm::length(sh.s.offset)); }
    std::sort(shove_reach.begin(), shove_reach.end());
    auto cell_shove_reach = [&](std::uint64_t ckey) {
        float m = 0.0f;
        auto it = std::lower_bound(shove_reach.begin(), shove_reach.end(),
                                   std::make_pair(ckey, -1.0f));
        for (; it != shove_reach.end() && it->first == ckey; ++it) {
            // A non-finite offset (a degenerate shove) passes the per-rock
            // cull (NaN compares false): never skip its cell.
            if (!std::isfinite(it->second)) return std::numeric_limits<float>::infinity();
            m = std::max(m, it->second);
        }
        return m;
    };
    int touches = 0;
    for (const auto& [ckey, cell] : cells_) {
        if (cell.cls != NearClass::Small) continue;
        if (touches >= md.max_shoves_per_frame) break;
        if (cell.rocks.empty()) continue;
        if (!cell.pinned &&
            cell_lower_bound(cell) - (shove_reach.empty() ? 0.0f : cell_shove_reach(ckey)) >
                cell.r_max + sb.bound)
            continue;
        for (std::size_t i = 0; i < cell.rocks.size(); ++i) {
            if (touches >= md.max_shoves_per_frame) break;
            const std::uint64_t key = key_of(ckey, cell, i);
            const float radius = cell.rocks[i].radius;
            glm::vec3 p(cell.rocks[i].pos_sys - to_render);
            if (!shoves_.empty())
                if (auto sh = shoves_.find(key); sh != shoves_.end()) p += sh->second.s.offset;
            if (dist_to_segment(p) > radius + sb.bound) continue;

            float s = 1.0f;
            minors::sweep_min_distance(sb, seg0, seg, p, s);
            const glm::vec3 ck = seg0 + seg * s;
            const glm::vec3 d = p - ck;
            // Inside is decided in box-local coordinates (float round-trip).
            float dl[3];
            bool inside = true;
            for (int ax = 0; ax < 3; ++ax) {
                dl[ax] = glm::dot(d, sb.axes[ax]);
                inside = inside && std::fabs(dl[ax]) <= sb.half[ax];
            }
            glm::vec3 nrm, q, push;
            if (inside) {
                // Exit through the face of least penetration, ending one radius out.
                int k = 0;
                for (int ax = 1; ax < 3; ++ax)
                    if (sb.half[ax] - std::fabs(dl[ax]) < sb.half[k] - std::fabs(dl[k])) k = ax;
                const float depth = sb.half[k] - std::fabs(dl[k]);
                nrm = sb.axes[k] * (dl[k] >= 0.0f ? 1.0f : -1.0f);
                q = p + nrm * depth;
                push = nrm * (depth + radius);
            } else {
                q = minors::closest_on_box(sb, ck, p);
                const float gap = glm::length(p - q);
                if (gap > radius) continue;
                nrm = (p - q) / gap;
                push = nrm * (radius - gap);
            }
            Shove& st = shoves_[key];
            st.cell = ckey;
            minors::ShoveState& sh = st.s;
            sh.offset += push;                   // sit on the surface
            const bool report = t - sh.last_contact >= md.contact_cooldown_s;
            minors::apply_shove(sh, nrm, glm::dot(v_player, nrm), t, md);
            if (report) small_contacts_.push_back({glm::dvec3(q) + in.render_origin, radius, rel_speed});
            ++touches;
        }
    }
}

}  // namespace renderer::rockfield
