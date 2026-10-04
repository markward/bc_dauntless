// native/src/renderer/rock_near.cc
// Rock fields, near band: deterministic cells and streaming
// (docs/superpowers/specs/2026-10-02-rock-fields-design.md).
#include "renderer/rock_near.h"
#include <algorithm>
#include <cmath>
#include <cstring>
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

using detail::same_generator;
using detail::same_generators;

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

// The far shell (rock-real Part 1): the large class streams and draws on to
// large_far_gu only when that lies beyond its billboard_gu.
bool far_shell_on(const NearDials& d) { return d.large_far_gu > d.large.billboard_gu; }

// A class's outer draw distance, which is also its streamed radius.
float reach_gu(const NearDials& d, NearClass cls) {
    if (cls == NearClass::Large && far_shell_on(d)) return d.large_far_gu;
    return class_dials(d, cls).billboard_gu;
}

// 0 at or below floor_px, 1 at floor_px + kNearPixelFadeBand and above.
float pixel_ramp(float px, float floor_px) {
    if (!(px > floor_px)) return 0.0f;
    const float t = (px - floor_px) / kNearPixelFadeBand;
    return t < 1.0f ? t : 1.0f;
}

// The whole far shell's edge: large_far_gu, but never past the large
// class's 33-cells-per-axis cap (see stream_ranges).
float full_shell_far(const NearDials& d);

// The streamed ranges of one class. A class never spans more than
// kMaxCellsPerAxis cells per axis (Task 4 review): (billboard + margin) is
// shrunk to 16 cells, never the cells widened -- a huge billboard_gu over a
// tiny cell_gu would otherwise enumerate (2R/L)^3 cells in one stream().
constexpr int kMaxCellsPerAxis = 33;
// (NearField::stream's full pass walks the box of R + watch_gu(L) <= R + L / 2
// (or 2 GU) to record its watch shell -- up to 35 cells per axis -- but
// generates only within R, so the 33-per-axis generation cap holds.)
struct StreamRanges { double gen, keep; };
float full_shell_far(const NearDials& d) {
    const double cap = 0.5 * (kMaxCellsPerAxis - 1) * static_cast<double>(d.large.cell_gu);
    return static_cast<float>(std::min(static_cast<double>(d.large_far_gu), cap));
}

StreamRanges stream_ranges(const NearDials& d, NearClass cls) {
    const NearClassDials& cd = class_dials(d, cls);
    const double reach = reach_gu(d, cls);
    const double cap = 0.5 * (kMaxCellsPerAxis - 1) * static_cast<double>(cd.cell_gu);
    const double keep = std::min(reach + std::max(static_cast<double>(d.stream_margin_gu), 0.0), cap);
    return {std::min(reach, keep), keep};
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
// The watch width of a class with cell edge L: half a cell, 2 to 8 GU (the
// path-length heaps make a frame's work independent of it; a wider watch
// means rarer full passes, each walking a slightly larger box).
double watch_gu(double L) { return std::clamp(0.5 * L, 2.0, 8.0); }
// A full pass records its watch shell only when the centre moved at most
// this far since the last one (at dash speed the next frame is outside it).
constexpr double kStreamRecordMaxMoveGu = 8.0;
// Slack for the Lipschitz bounds against double rounding in aabb_distance.
constexpr double kStreamEps = 1e-6;
// NearField::stream's path-length heaps: the slack a due is popped early by
// (rounding of the summed travel), and the travel after which the watch
// starts afresh (bounding that rounding).
constexpr double kStreamPathSlackGu = 0.01;
constexpr double kStreamPathRebaseGu = 1.0e5;

// Cells per block edge (NearField::Block): ~40 GU small blocks, ~100 GU large.
constexpr std::int64_t block_cells(NearClass cls) { return cls == NearClass::Small ? 4 : 2; }

std::int64_t floor_div(std::int64_t a, std::int64_t b) {
    const std::int64_t q = a / b;
    return (a % b != 0 && a < 0) ? q - 1 : q;
}

std::uint64_t block_key(NearClass cls, const glm::i64vec3& ijk) {
    const std::int64_t K = block_cells(cls);
    return mix_ijk(0x0B10C0u, cls, glm::i64vec3(floor_div(ijk.x, K), floor_div(ijk.y, K), floor_div(ijk.z, K)));
}

// std::sort(v, less) for a `less` ordering by the float member d first (d >=
// 0 and never NaN, so its bit patterns order as the values): an LSD radix
// sort on d's bits, then each run of equal d sorted by `less` itself. The
// same order (up to wholly equivalent items), far cheaper in a Debug build.
template <class T, class Less>
void sort_by_distance(std::vector<T>& v, Less less) {
    const std::size_t n = v.size();
    if (n < 64) { std::sort(v.begin(), v.end(), less); return; }
    std::vector<std::uint64_t> a(n), b(n);
    for (std::size_t i = 0; i < n; ++i) {
        std::uint32_t bits;
        std::memcpy(&bits, &v[i].d, sizeof bits);
        a[i] = (static_cast<std::uint64_t>(bits) << 32) | static_cast<std::uint64_t>(i);
    }
    std::uint64_t* src = a.data();
    std::uint64_t* dst = b.data();
    for (int shift = 32; shift < 64; shift += 8) {
        std::size_t count[257] = {};
        for (std::size_t i = 0; i < n; ++i) ++count[((src[i] >> shift) & 0xFFu) + 1];
        for (int k = 0; k < 256; ++k) count[k + 1] += count[k];
        for (std::size_t i = 0; i < n; ++i) dst[count[(src[i] >> shift) & 0xFFu]++] = src[i];
        std::swap(src, dst);
    }
    std::vector<T> out(n);
    T* o = out.data();
    const T* in = v.data();
    for (std::size_t i = 0; i < n; ++i) o[i] = in[src[i] & 0xFFFFFFFFu];
    for (std::size_t i = 0; i < n;) {
        std::size_t j = i + 1;
        while (j < n && (src[j] >> 32) == (src[i] >> 32)) ++j;
        if (j - i > 1) std::sort(out.begin() + static_cast<std::ptrdiff_t>(i), out.begin() + static_cast<std::ptrdiff_t>(j), less);
        i = j;
    }
    v.swap(out);
}

float ramp_down(float d, float end, float fade) {   // 1 at end - fade, 0 at end
    if (!(fade > 0.0f)) return d < end ? 1.0f : 0.0f;
    if (d <= end - fade) return 1.0f;
    if (d >= end) return 0.0f;
    return (end - d) / fade;
}
}  // namespace

NearWeights near_weights(float d, const NearClassDials& c, float fade_gu) {
    return near_weights(d, c, fade_gu, fade_gu);
}

NearWeights near_weights(float d, const NearClassDials& c, float fade_gu, float handoff_fade_gu) {
    NearWeights w;
    w.mesh = ramp_down(d, c.mesh_gu, handoff_fade_gu);
    w.billboard = std::min(1.0f - w.mesh, ramp_down(d, c.billboard_gu, fade_gu));
    return w;
}

NearWeights near_large_weights(float d, float px, const NearDials& dials) {
    const NearClassDials& c = dials.large;
    if (!far_shell_on(dials)) return near_weights(d, c, dials.fade_gu, dials.handoff_fade_gu);
    NearWeights w;
    w.mesh = ramp_down(d, c.mesh_gu, dials.handoff_fade_gu);
    w.billboard = std::min(1.0f - w.mesh, ramp_down(d, dials.large_far_gu, dials.large_far_fade_gu));
    // The pixel floor blends in over [mesh_gu, mesh_gu + fade_gu]: 1 at the
    // mesh edge (the hand-off is untouched), the floor ramp beyond.
    const float fade = dials.fade_gu;
    const float t = fade > 0.0f ? std::clamp((d - c.mesh_gu) / fade, 0.0f, 1.0f) : (d > c.mesh_gu ? 1.0f : 0.0f);
    w.billboard *= 1.0f - t * (1.0f - pixel_ramp(px, dials.large_min_px));
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
    // A whole shell follows a live dial; a shrunk/regrowing one keeps regrowing.
    if (shell_far_ >= 0.0f && shell_far_ >= full_shell_far(dials_)) shell_far_ = full_shell_far(d);
    dials_ = d;
    update_effective();
    invalidate_stream_watch();   // ranges may have moved
    if (regen) clear();
}

void NearField::set_catalogue(NearCatalogue c) {
    cat_ = std::move(c);
    views_ = far::make_impostor_views(cat_.view_dirs_gltf);
    clear();
}

void NearField::update_effective() {
    eff_ = dials_;
    if (!far_shell_on(dials_)) return;
    const float full = full_shell_far(dials_);
    const float f = shell_far_ < 0.0f ? full : std::min(shell_far_, full);
    eff_.large_far_gu = f;
    eff_.large_far_fade_gu = std::min(dials_.large_far_fade_gu, std::max(0.0f, f - dials_.large.billboard_gu));
}

float NearField::large_reach_gu() const { return reach_gu(eff_, NearClass::Large); }

void NearField::invalidate_stream_watch() {
    gen_watch_.clear();
    drop_valid_ = false;
    drop_heap_.clear();
    path_s_ = 0.0;   // every due keyed by it is gone
}

void NearField::set_sources(const std::vector<far::DiscSource>& active) {
    // The host re-pushes the same sources every frame (far_set_frame): only
    // a real change drops the cells and the incremental-stream state.
    const bool same = same_generators(active, sources_);
    sources_ = active;
    if (!same) clear();   // clear() also invalidates the stream watch
}

void NearField::stream(const glm::dvec3& c) {
    // The far shell at dash speed (NearDials::far_shell_max_step_gu): shrink
    // to the pre-shell reach, regrow in bounded steps once slow again.
    if (far_shell_on(dials_)) {
        const float full = full_shell_far(dials_);
        float next;
        if (has_last_centre_ && glm::length(c - last_centre_) > dials_.far_shell_max_step_gu)
            next = std::min(full, dials_.large.billboard_gu);
        else if (shell_far_ < 0.0f)
            next = full;
        else
            next = std::min(full, shell_far_ + std::max(dials_.far_shell_regrow_gu, 0.0f));
        if (next != shell_far_) {
            shell_far_ = next;
            update_effective();
            invalidate_stream_watch();   // the large ranges moved
        }
    }
    if (has_last_centre_) path_s_ += glm::length(c - last_centre_);
    has_last_centre_ = true;
    last_centre_ = c;
    last_stream_cells_tested_ = 0;
    // Bound the path length (its rounding) by starting the watch afresh.
    if (path_s_ > kStreamPathRebaseGu) invalidate_stream_watch();
    const auto tested_distance = [this](const glm::dvec3& p, const glm::dvec3& lo, double size) {
        ++last_stream_cells_tested_;
        return aabb_distance(p, lo, size);
    };
    // A heap entry is due once path_s_ reaches it, with slack for rounding:
    // re-testing early is harmless, late never happens.
    const double now_s = path_s_ + kStreamPathSlackGu;
    const auto heap_push = [](std::vector<Due>& h, const Due& e) {
        h.push_back(e);
        std::push_heap(h.begin(), h.end(), std::greater<Due>());
    };
    const auto heap_pop = [](std::vector<Due>& h) {
        std::pop_heap(h.begin(), h.end(), std::greater<Due>());
        const Due e = h.back();
        h.pop_back();
        return e;
    };

    // Byte-for-byte the effect of: drop every non-pinned cell farther than
    // its class's keep range, then (sources outer, classes inner, cells in
    // (i, j, k) order) generate every missing cell within the generation
    // range. Drop: every streamed cell waits until the centre's travel could
    // have carried it past keep (keep - d), then is re-tested.
    auto keep_of = [&](NearClass cls) {
        return stream_ranges(eff_, cls).keep;
    };
    const auto drop = [&](std::unordered_map<std::uint64_t, Cell>::iterator it) {
        const Cell& cell = it->second;
        if (cell.cls == NearClass::Large && cell.seen_step == step_count_)
            dropped_seen_[it->first] = cell.seen_rocks;
        block_remove(it->first, cell);
        return cells_.erase(it);
    };
    if (!drop_valid_) {
        drop_heap_.clear();
        for (auto it = cells_.begin(); it != cells_.end();) {
            const Cell& cell = it->second;
            if (cell.pinned) { ++it; continue; }
            const double keep = keep_of(cell.cls);
            const double d = tested_distance(c, cell.lo, cell.size);
            if (d > keep) { it = drop(it); continue; }
            drop_heap_.push_back({path_s_ + (keep - d), it->first});
            ++it;
        }
        std::make_heap(drop_heap_.begin(), drop_heap_.end(), std::greater<Due>());
        drop_valid_ = true;
    } else {
        std::vector<Due> again;
        while (!drop_heap_.empty() && drop_heap_.front().due <= now_s) {
            const Due e = heap_pop(drop_heap_);
            const auto it = cells_.find(e.id);
            if (it == cells_.end() || it->second.pinned) continue;
            const double keep = keep_of(it->second.cls);
            const double d = tested_distance(c, it->second.lo, it->second.size);
            if (d > keep) drop(it);
            else again.push_back({path_s_ + (keep - d), e.id});
        }
        for (const Due& e : again) heap_push(drop_heap_, e);
    }

    if (gen_watch_.size() != sources_.size() * 2) gen_watch_.assign(sources_.size() * 2, GenWatch{});
    // d: the cell's distance from c (it is within the generation range).
    auto generate = [&](const far::DiscSource& s, NearClass cls, const glm::i64vec3& ijk,
                        const glm::dvec3& lo, double L, double d) {
        const std::uint64_t key = cell_key(s.id, cls, ijk);
        if (cells_.count(key)) return;
        Cell cell{cls, generate_near_cell(s, cls, ijk, dials_, cat_), lo, L, false, {}};
        for (const NearRock& r : cell.rocks) cell.r_max = std::max(cell.r_max, r.radius);
        cell.ijk = ijk;
        cell.by_radius.resize(cell.rocks.size());
        for (std::size_t i = 0; i < cell.rocks.size(); ++i) cell.by_radius[i] = static_cast<std::uint32_t>(i);
        std::stable_sort(cell.by_radius.begin(), cell.by_radius.end(), [&](std::uint32_t a, std::uint32_t b) {
            return cell.rocks[a].radius > cell.rocks[b].radius;
        });
        if (const auto ds = dropped_seen_.find(key); ds != dropped_seen_.end()) {
            cell.seen_step = step_count_;
            cell.seen_rocks = ds->second;
        }
        block_add(key, cells_.emplace(key, std::move(cell)).first->second);
        heap_push(drop_heap_, {path_s_ + std::max(0.0, keep_of(cls) - d), key});
    };
    for (std::size_t si = 0; si < sources_.size(); ++si) {
        const far::DiscSource& s = sources_[si];
        for (NearClass cls : kClasses) {
            const NearClassDials& cd = class_dials(eff_, cls);
            const StreamRanges ranges = stream_ranges(eff_, cls);
            const double L = cd.cell_gu, R = ranges.gen, keep = ranges.keep;
            GenWatch& w = gen_watch_[si * 2 + static_cast<std::size_t>(cls)];
            if (!(L > 0.0) || !(R > 0.0) || !reaches(s, c, R)) {
                // Not tested this frame, so the watch cannot vouch for the
                // cells the drop pass removes meanwhile (out of reach and
                // back): the next reaching frame starts with a full pass.
                w.valid = false;
                w.has_ref = false;
                w.prev_complete = false;
                continue;
            }
            // A cell is generated when it lies in the box [floor((c - R) / L),
            // floor((c + R) / L)] AND within R of c. (The box test is not
            // redundant: a cell exactly R below c on an axis is outside it.)
            const glm::i64vec3 ga(glm::floor((c - R) / L)), gb(glm::floor((c + R) / L));
            const auto in_box = [&](const glm::i64vec3& ijk) {
                return ijk.x >= ga.x && ijk.x <= gb.x && ijk.y >= ga.y && ijk.y <= gb.y &&
                       ijk.z >= ga.z && ijk.z <= gb.z;
            };
            // When a watched cell must next be re-tested: once the travel could
            // bring it within R (outside now), at once while it is within R
            // but outside the box, else once it could have passed keep (and
            // been dropped, to be generated again).
            const auto due_of = [&](double d, bool box) {
                if (d > R) return path_s_ + (d - R);
                if (!box) return path_s_;
                return path_s_ + std::max(0.0, keep - d);
            };
            const double moved = glm::length(c - w.c_ref);
            const double ww = watch_gu(L);
            if (w.valid && moved <= ww) {
                std::vector<std::uint64_t> due;
                while (!w.heap.empty() && w.heap.front().due <= now_s) due.push_back(heap_pop(w.heap).id);
                std::sort(due.begin(), due.end());   // shell order is (i, j, k) order
                for (const std::uint64_t idx : due) {
                    const glm::i64vec3& ijk = w.shell[idx];
                    const glm::dvec3 lo = glm::dvec3(ijk) * L;
                    const double d = tested_distance(c, lo, L);
                    const bool box = in_box(ijk);
                    if (d <= R && box) generate(s, cls, ijk, lo, L, d);
                    w.heap.push_back({due_of(d, box), idx});
                    std::push_heap(w.heap.begin(), w.heap.end(), std::greater<Due>());
                }
                w.c_prev = c;
                w.prev_complete = true;
                continue;
            }
            // Full pass over the cells within R + w (a superset of the old
            // R box, same (i, j, k) order), generating those within R. At
            // dash speed (the centre moved several watch widths since the
            // last pass) the next frame will not be inside this one's watch
            // either: skip recording the shell (w = 0 enumerates the R box).
            // A cell within R of c_prev (and in its box) exists already when
            // the last stream left this watch complete: no lookup.
            ++full_stream_passes_;
            w.shell.clear();
            w.heap.clear();
            const bool record = !w.has_ref || moved <= kStreamRecordMaxMoveGu;
            const double Rw = R + (record ? ww : 0.0);
            const bool known_prev = w.prev_complete;
            const glm::i64vec3 pa(glm::floor((w.c_prev - R) / L)), pb(glm::floor((w.c_prev + R) / L));
            const glm::i64vec3 a(glm::floor((c - Rw) / L)), b(glm::floor((c + Rw) / L));
            for (auto i = a.x; i <= b.x; ++i)
                for (auto j = a.y; j <= b.y; ++j)
                    for (auto k = a.z; k <= b.z; ++k) {
                        const glm::i64vec3 ijk(i, j, k);
                        const glm::dvec3 lo = glm::dvec3(ijk) * L;
                        const double d = tested_distance(c, lo, L);
                        const bool box = in_box(ijk);
                        if (record && d > R - ww - kStreamEps && d <= Rw + kStreamEps) {
                            w.heap.push_back({due_of(d, box), w.shell.size()});
                            w.shell.push_back(ijk);
                        }
                        if (d > R || !box) continue;
                        if (known_prev && i >= pa.x && i <= pb.x && j >= pa.y && j <= pb.y && k >= pa.z &&
                            k <= pb.z && tested_distance(w.c_prev, lo, L) <= R)
                            continue;
                        generate(s, cls, ijk, lo, L, d);
                    }
            std::make_heap(w.heap.begin(), w.heap.end(), std::greater<Due>());
            w.c_ref = c;
            w.has_ref = true;
            w.valid = record;
            w.c_prev = c;
            w.prev_complete = true;
        }
    }
}

void NearField::clear() {
    cells_.clear();
    for (auto& b : blocks_) b.clear();
    pinned_.clear();
    invalidate_stream_watch();
    // A fresh start, as a new field: the next stream gets the whole far shell
    // (a source change mid-dash costs that one frame, then shrinks again).
    shell_far_ = -1.0f;
    has_last_centre_ = false;
    update_effective();
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

void NearField::block_add(std::uint64_t key, Cell& c) {
    Block& b = blocks_[static_cast<int>(c.cls)][block_key(c.cls, c.ijk)];
    const glm::dvec3 hi = c.lo + glm::dvec3(c.size);
    if (b.cells.empty()) { b.lo = c.lo; b.hi = hi; b.r_max = c.r_max; }
    else { b.lo = glm::min(b.lo, c.lo); b.hi = glm::max(b.hi, hi); b.r_max = std::max(b.r_max, c.r_max); }
    b.cells.emplace_back(key, &c);
}

void NearField::block_remove(std::uint64_t key, const Cell& c) {
    auto& blocks = blocks_[static_cast<int>(c.cls)];
    const auto it = blocks.find(block_key(c.cls, c.ijk));
    if (it == blocks.end()) return;
    auto& v = it->second.cells;
    for (std::size_t i = 0; i < v.size(); ++i)
        if (v[i].first == key) { v[i] = v.back(); v.pop_back(); break; }
    if (v.empty()) blocks.erase(it);
}

void NearField::debug_add_rock(NearClass cls, std::uint64_t key, const NearRock& r) {
    // Fixed keys outside the hashed space in practice; one test cell per class.
    const std::uint64_t ck = 0x7E57CE11000000ull | static_cast<std::uint64_t>(cls);
    if (!cells_.count(ck)) pinned_.push_back(ck);
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
    out.billboards_fading.clear();
    out.mesh_count = out.billboard_count = out.billboard_fading_count = 0;
    out.cells_tested = out.rocks_tested = 0;

    const float k = far::pixels_per_gu(in.proj, in.viewport_h);
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const glm::dvec3 to_render = in.anchor_sys + in.render_origin;
    const float t = static_cast<float>(in.game_time);

    std::map<std::tuple<int, int, int>, std::vector<minors::InstanceGpu>> mesh_bins;
    std::map<int, std::vector<far::ImpostorGpu>> board_bins;
    // Translucent billboards (rock fade), by class draw rank then rock: rank
    // 0 is the class with the larger billboard_gu (the farther band).
    std::map<int, std::vector<far::ImpostorGpu>> fade_bins[2];
    // The map entry per rock, looked up once per build (a handful of rocks).
    struct BinCache {
        std::map<int, std::vector<far::ImpostorGpu>>* bins;
        std::vector<std::pair<int, std::vector<far::ImpostorGpu>*>> hit;
        std::vector<far::ImpostorGpu>& get(int rock) {
            const auto* h = hit.data();
            for (std::size_t i = 0, n = hit.size(); i < n; ++i)
                if (h[i].first == rock) return *h[i].second;
            hit.emplace_back(rock, &(*bins)[rock]);
            return *hit.back().second;
        }
    };
    BinCache board_cache{&board_bins, {}}, fade_cache[2] = {{&fade_bins[0], {}}, {&fade_bins[1], {}}};
    const bool large_first = reach_gu(eff_, NearClass::Large) >= reach_gu(eff_, NearClass::Small);
    const bool far_shell = far_shell_on(eff_);

    // Cells holding a shoved (small) rock: their rocks may sit off the cell,
    // so they skip the cell broad phase and look up their shoves.
    std::vector<std::uint64_t> shoved_cells;
    shoved_cells.reserve(shoves_.size());
    for (const auto& [key, sh] : shoves_) { (void)key; shoved_cells.push_back(sh.cell); }
    std::sort(shoved_cells.begin(), shoved_cells.end());
    const float eye_len = glm::length(eye);

    struct Cand { float d; glm::vec3 c; NearWeights w; const NearRock* rock; float spin; };
    for (NearClass cls : kClasses) {
        const NearClassDials& cd = class_dials(eff_, cls);
        const bool small = cls == NearClass::Small;
        const std::vector<int>& rocks = small ? cat_.small_rocks : cat_.large_rocks;
        const std::vector<float>& bounds = small ? cat_.small_bound_mu : cat_.large_bound_mu;
        const int family = small ? kNearSmallFamily : kNearLargeFamily;
        // Neither tier draws at camera distance >= max(mesh_gu, reach).
        const float d_max = std::max(cd.mesh_gu, reach_gu(eff_, cls));
        const bool shell = !small && far_shell;   // the large class's far-shell rule

        std::vector<Cand> cands;
        std::size_t n_cands = 0;   // cands[0, n_cands) (grown by hand: a Debug-build hot path)
        const float floor_px = small ? eff_.small_min_px : eff_.large_min_px;
        const bool pixel_floor = shell || (small && eff_.small_min_px > 0.0f);
        const float floor_from = cd.mesh_gu + std::max(eff_.fade_gu, 0.0f);   // the floor applies whole past here
        const float fade_gu = eff_.fade_gu, handoff = eff_.handoff_fade_gu;
        const float mesh_in = cd.mesh_gu - handoff, board_in = cd.billboard_gu - fade_gu;   // ramp_down's end - fade
        // One cell: the broad phase, then the per-rock tests (pinned and
        // shoved cells skip the broad phase: a shoved rock may sit off its cell).
        // `of`: the frustum planes the cell's block straddles (the cell lies
        // inside the others with room to spare).
        const auto visit = [&](std::uint64_t key, const Cell& cell, bool shoved, unsigned of) {
            ++out.cells_tested;
            // Past floor_from, a cell's rocks visited largest first stop at the
            // first under the pixel floor: every later one is as small or
            // smaller and at least as far (>= d_lo), so has a zero weight.
            float cut_d_lo = 0.0f;
            unsigned planes = 0x3Fu;   // the frustum planes each rock is tested on
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
                const float d_lo = std::sqrt(dot3(dx, dy, dz, dx, dy, dz)) - half_diag - slack;
                if (d_lo >= d_max) return;
                if (!frustum.sphere_on(cc, half_diag + cell.r_max + slack, of)) return;
                // Only the planes the cell straddles can reject one of its rocks.
                planes = frustum.straddled(cc, half_diag + slack, of);
                // The pixel floor, whole cell: beyond the mesh range every
                // rock's on-screen radius is at most r_max * k / d_lo.
                if (pixel_floor && d_lo > floor_from) {
                    if (!(cell.r_max * k / d_lo > floor_px)) return;
                    cut_d_lo = d_lo;
                }
            }
            const std::size_t n = cell.rocks.size();
            const NearRock* rock_p = cell.rocks.data();
            const bool ordered = cut_d_lo > 0.0f && cell.by_radius.size() == n;
            for (std::size_t j = 0; j < n; ++j) {
                const std::size_t i = ordered ? cell.by_radius[j] : j;
                const NearRock& r = rock_p[i];
                if (ordered && !(r.radius * k / cut_d_lo > floor_px)) break;
                ++out.rocks_tested;
                // vec3(pos_sys - to_render) and length(c - eye), as scalars
                // (hand-inlined throughout: this loop is the build's hot path
                // in the Debug build, where every helper is a call).
                float cx = static_cast<float>(r.pos_sys.x - to_render.x);
                float cy = static_cast<float>(r.pos_sys.y - to_render.y);
                float cz = static_cast<float>(r.pos_sys.z - to_render.z);
                float spin = 0.0f;
                if (shoved)
                    if (auto sh = shoves_.find(key_of(key, cell, i)); sh != shoves_.end()) {
                        cx += sh->second.s.offset.x;
                        cy += sh->second.s.offset.y;
                        cz += sh->second.s.offset.z;
                        spin = sh->second.s.spin;
                    }
                const float ex = cx - eye.x, ey = cy - eye.y, ez = cz - eye.z;
                const float exx = ex * ex;   // glm_exact::dot3
                const float eyy = ey * ey;
                const float ezz = ez * ez;
                const float d = std::sqrt(exx + eyy + ezz);
                // Neither tier draws at d >= d_max (the weights below are 0 there).
                if (!(d < d_max)) continue;
                NearWeights w;
                if (shell) {
                    w = near_large_weights(d, r.radius * k / std::max(d, 1e-3f), eff_);
                } else {
                    // near_weights(d, cd, fade_gu, handoff_fade_gu), op for op.
                    w.mesh = !(handoff > 0.0f) ? (d < cd.mesh_gu ? 1.0f : 0.0f)
                           : d <= mesh_in ? 1.0f : d >= cd.mesh_gu ? 0.0f : (cd.mesh_gu - d) / handoff;
                    const float bb = !(fade_gu > 0.0f) ? (d < cd.billboard_gu ? 1.0f : 0.0f)
                                   : d <= board_in ? 1.0f : d >= cd.billboard_gu ? 0.0f
                                   : (cd.billboard_gu - d) / fade_gu;
                    const float rest = 1.0f - w.mesh;
                    w.billboard = bb < rest ? bb : rest;   // std::min(rest, bb)
                }
                if (small && eff_.small_min_px > 0.0f) {   // the small pixel floor (0 = off), blended in past the mesh edge
                    float tt;
                    if (fade_gu > 0.0f) {   // std::clamp((d - mesh_gu) / fade, 0, 1)
                        const float v = (d - cd.mesh_gu) / fade_gu;
                        tt = v < 0.0f ? 0.0f : (1.0f < v ? 1.0f : v);
                    } else {
                        tt = d > cd.mesh_gu ? 1.0f : 0.0f;
                    }
                    const float px = r.radius * k / (d < 1e-3f ? 1e-3f : d);   // std::max(d, 1e-3f)
                    float ramp = 0.0f;                                          // pixel_ramp(px, floor)
                    if (px > eff_.small_min_px) {
                        const float u = (px - eff_.small_min_px) / kNearPixelFadeBand;
                        ramp = u < 1.0f ? u : 1.0f;
                    }
                    w.billboard *= 1.0f - tt * (1.0f - ramp);
                }
                if (!(w.mesh > 0.0f) && !(w.billboard > 0.0f)) continue;
                if (planes != 0) {   // frustum.sphere_on(c, radius, planes)
                    bool out_of_view = false;
                    for (unsigned pi = 0, m = planes; m != 0; ++pi, m >>= 1) {
                        if (!(m & 1u)) continue;
                        const glm::vec4& pl = frustum.planes[pi];
                        const float px_ = pl.x * cx;
                        const float py_ = pl.y * cy;
                        const float pz_ = pl.z * cz;
                        if (px_ + py_ + pz_ + pl.w < -r.radius) { out_of_view = true; break; }
                    }
                    if (out_of_view) continue;
                }
                if (n_cands == cands.size()) cands.resize(2 * n_cands + 256);
                Cand& cn = cands.data()[n_cands++];
                cn.d = d;
                cn.c.x = cx; cn.c.y = cy; cn.c.z = cz;
                cn.w = w;
                cn.rock = &r;
                cn.spin = spin;
            }
        };
        const auto is_shoved = [&](std::uint64_t key) {
            return small && !shoved_cells.empty() &&
                   std::binary_search(shoved_cells.begin(), shoved_cells.end(), key);
        };
        // The blocks holding a shoved cell: only their cells need the lookup.
        std::vector<std::uint64_t> shoved_blocks;
        if (small)
            for (const std::uint64_t key : shoved_cells)
                if (const auto it = cells_.find(key); it != cells_.end() && !it->second.pinned)
                    shoved_blocks.push_back(block_key(it->second.cls, it->second.ijk));
        std::sort(shoved_blocks.begin(), shoved_blocks.end());
        // The test cells and shoved cells, each once, outside the blocks.
        // (The candidates are sorted below, so the visiting order is not output.)
        for (const std::uint64_t key : pinned_) {
            const auto it = cells_.find(key);
            if (it != cells_.end() && it->second.cls == cls && !it->second.rocks.empty())
                visit(key, it->second, is_shoved(key), 0x3Fu);
        }
        if (small)
            for (std::size_t si = 0; si < shoved_cells.size(); ++si) {
                const std::uint64_t key = shoved_cells[si];
                if (si > 0 && shoved_cells[si - 1] == key) continue;
                const auto it = cells_.find(key);
                if (it == cells_.end() || it->second.pinned || it->second.cls != cls || it->second.rocks.empty())
                    continue;
                visit(key, it->second, true, 0x3Fu);
            }
        // Block broad phase: as the cell one, over the block's bounding
        // sphere (its box's half-diagonal) widened by its largest rock and a
        // float slack that grows with the block -- conservative, so a block
        // is rejected only when every cell in it would be.
        for (const auto& [bkey, b] : blocks_[static_cast<int>(cls)]) {
            const glm::dvec3 bc = 0.5 * (b.lo + b.hi);
            const glm::vec3 cc(static_cast<float>(bc.x - to_render.x), static_cast<float>(bc.y - to_render.y),
                               static_cast<float>(bc.z - to_render.z));
            const glm::dvec3 ext = b.hi - b.lo;
            const float rad = static_cast<float>(0.5 * std::sqrt(ext.x * ext.x + ext.y * ext.y + ext.z * ext.z));
            const float dx = cc.x - eye.x, dy = cc.y - eye.y, dz = cc.z - eye.z;
            const float slack = 0.05f + 1e-5f * (std::fabs(cc.x) + std::fabs(cc.y) + std::fabs(cc.z) +
                                                 eye_len + rad);
            const float d_lo = std::sqrt(dx * dx + dy * dy + dz * dz) - rad - slack;
            if (d_lo >= d_max) continue;
            if (!frustum.sphere(cc, rad + b.r_max + slack)) continue;
            const unsigned of = frustum.straddled(cc, rad + slack);
            if (pixel_floor && d_lo > floor_from && !(b.r_max * k / d_lo > floor_px)) continue;
            const bool any_shoved = !shoved_blocks.empty() &&
                                    std::binary_search(shoved_blocks.begin(), shoved_blocks.end(), bkey);
            for (const auto& [key, cp] : b.cells) {
                if (cp->rocks.empty() || (any_shoved && is_shoved(key))) continue;
                visit(key, *cp, false, of);
            }
        }
        // Nearest first so the cap drops the far end; ties by catalogue index
        // and position keep the order independent of the cell map's order.
        cands.resize(n_cands);
        sort_by_distance(cands, [](const Cand& a, const Cand& b) {
            if (a.d != b.d) return a.d < b.d;
            if (a.rock->rock != b.rock->rock) return a.rock->rock < b.rock->rock;
            return std::tie(a.c.x, a.c.y, a.c.z) < std::tie(b.c.x, b.c.y, b.c.z);
        });

        int emitted = 0;
        for (const Cand& cn : cands) {
            if (emitted >= cd.max_instances) break;
            const NearRock& r = *cn.rock;
            const glm::mat3 R = rotation(r.phase + r.tumble_rate * eff_.tumble_scale * t + cn.spin, r.tumble_axis);
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
            if (cn.w.billboard > 0.0f && views_.grid >= 2 && emitted < cd.max_instances) {
                const float dither = cn.w.billboard < 1.0f ? -cn.w.billboard : 0.0f;
                // Only the hand-off against this rock's own mesh keeps the
                // screen door (the two must complement exactly); fading in
                // from nothing at billboard_gu is translucent.
                const bool translucent = dither != 0.0f && !(cn.w.mesh > 0.0f);
                auto& bin = translucent ? fade_cache[small == large_first ? 1 : 0].get(r.rock)
                                        : board_cache.get(r.rock);
                bin.push_back(far::make_impostor(views_, eye, cn.c, R, r.radius, dither));
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
    for (auto& rank : fade_bins)
        for (auto& [rock, items] : rank) {
            // Emitted nearest first: blended back to front, farthest first.
            std::reverse(items.begin(), items.end());
            out.billboard_count += static_cast<int>(items.size());
            out.billboard_fading_count += static_cast<int>(items.size());
            out.billboards_fading.push_back(far::ImpostorBin{rock, std::move(items)});
        }
}

void NearField::step(const NearStepInput& in) {
    const double t = in.game_time;
    // dt <= 0 is a paused frame (or the first): no touches, no integration.
    const double dt = stepped_ ? t - last_time_ : 0.0;
    last_time_ = t;
    stepped_ = true;
    last_step_large_cells_tested_ = 0;
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
    // A cheaper first cut (the far shell streams thousands of large cells):
    // the sweep's SYSTEM-space AABB widened by everything a rock of the cell
    // could reach, plus a generous float slack. A cell box that misses it
    // holds no rock within reach of any point of the sweep, which is exactly
    // what cell_lower_bound rejects -- conservative, so nothing changes.
    const glm::dvec3 sw0 = glm::dvec3(seg0) + to_render, sw1 = glm::dvec3(c) + to_render;
    const glm::dvec3 sw_lo = glm::min(sw0, sw1), sw_hi = glm::max(sw0, sw1);
    auto sweep_box_meets = [&](const Cell& cell) {
        const double e = static_cast<double>(lb.bound + cell.r_max + margin) + 0.05 + 1e-4 * seg_scale;
        return !(cell.lo.x > sw_hi.x + e || cell.lo.x + cell.size < sw_lo.x - e ||
                 cell.lo.y > sw_hi.y + e || cell.lo.y + cell.size < sw_lo.y - e ||
                 cell.lo.z > sw_hi.z + e || cell.lo.z + cell.size < sw_lo.z - e);
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
        if (!cell.pinned && (!sweep_box_meets(cell) || cell_lower_bound(cell) > lb.bound + cell.r_max + margin)) {
            // No rock here overlaps or is swept: only a ghost is released.
            if (!ghosts_.empty())
                for (std::size_t i = 0; i < cell.rocks.size(); ++i) ghosts_.erase(key_of(ckey, cell, i));
            continue;
        }
        ++last_step_large_cells_tested_;
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
        if (!cell.pinned) {
            // Cheap first cut (Mark, 2026-10-04: thousands of small cells at
            // the 45 GU range): the sweep's system-space AABB widened by the
            // cell's reach and its largest shove, as the large loop's
            // sweep_box_meets. Conservative, so the order and every contact
            // are unchanged.
            const float shove = shove_reach.empty() ? 0.0f : cell_shove_reach(ckey);
            const double e = static_cast<double>(sb.bound + cell.r_max) + shove + 0.05 + 1e-4 * seg_scale;
            if (!(e < std::numeric_limits<double>::infinity()) ? false :
                (cell.lo.x > sw_hi.x + e || cell.lo.x + cell.size < sw_lo.x - e ||
                 cell.lo.y > sw_hi.y + e || cell.lo.y + cell.size < sw_lo.y - e ||
                 cell.lo.z > sw_hi.z + e || cell.lo.z + cell.size < sw_lo.z - e))
                continue;
            if (cell_lower_bound(cell) - shove > cell.r_max + sb.bound) continue;
        }
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
