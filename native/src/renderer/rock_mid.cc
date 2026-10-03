// native/src/renderer/rock_mid.cc
// Rock fields, mid band: nested collection tiles
// (docs/superpowers/specs/2026-10-02-rock-fields-design.md §3).
#include "renderer/rock_mid.h"
#include <algorithm>
#include <cmath>
#include <map>
#include <tuple>
#include <utility>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/rock_random.h>
#include "rock_field_common.h"

namespace renderer::rockfield {
namespace {
using detail::Frustum;
using glm_exact::dot3;
using detail::mix;

// Source-independent salts: overlapping sources share every tile's hashes,
// so they never place a tile's sprite twice (their densities sum instead).
constexpr std::uint64_t kTileSalt = 0x6D69645F74696C65ull;   // "mid_tile"
constexpr std::uint64_t kAxisSalt = 0x6D69645F61786973ull;   // "mid_axis"

// A level never spans more than this many tiles per axis: a tile dial pushed
// far below its level's range shrinks the range, never the tiles (as
// NearField's kMaxCellsPerAxis). The defaults need ~10.
constexpr int kMaxTilesPerAxis = 33;

// MidField's tile-selection cache bound (blocks of 64 tiles, ~4 KB each).
constexpr std::size_t kMaxCachedBlocks = 1024;

std::int64_t floor_div(std::int64_t a, std::int64_t b) {   // b > 0
    return a >= 0 ? a / b : -((-a + b - 1) / b);
}

// 0 at a, 1 at b, linear between; b <= a is a hard step at b.
float ramp(float a, float b, float d) {
    if (!(b > a)) return d >= b ? 1.0f : 0.0f;
    return std::clamp((d - a) / (b - a), 0.0f, 1.0f);
}

// A level's two ramps: weight = ramp(lo) * (1 - ramp(up)).
struct LevelRamps { float lo_a, lo_b, up_a, up_b; };
LevelRamps level_ramps(int lvl, const MidDials& m) {
    const float f = m.xfade_frac;
    switch (lvl) {
    case 0: return {m.in_lo_gu, m.in_hi_gu, m.l0_out_gu * (1.0f - f), m.l0_out_gu};
    case 1: return {m.l0_out_gu * (1.0f - f), m.l0_out_gu, m.l1_out_gu * (1.0f - f), m.l1_out_gu};
    default: return {m.l1_out_gu * (1.0f - f), m.l1_out_gu, m.handoff_gu - m.handoff_band_gu,
                     m.handoff_gu};
    }
}

float level_tile(int lvl, const MidDials& m) {
    return lvl == 0 ? m.l0_tile_gu : (lvl == 1 ? m.l1_tile_gu : m.l2_tile_gu);
}

struct Cand {
    float dist;          // sprite centre to eye
    int atlas;
    glm::vec3 c;         // render space, jittered
    glm::mat3 R;
    float half, dither;
    float band;          // fading (dither != 0): the far end of its ramp; 0 when solid
};
}  // namespace

float mid_level_weight(int lvl, float d, const MidDials& m) {
    if (lvl < 0 || lvl > 2) return 0.0f;
    const LevelRamps r = level_ramps(lvl, m);
    return ramp(r.lo_a, r.lo_b, d) * (1.0f - ramp(r.up_a, r.up_b, d));
}

float mid_level_dither(int lvl, float d, const MidDials& m) {
    if (lvl < 0 || lvl > 2) return 0.0f;
    const LevelRamps r = level_ramps(lvl, m);
    const float lo = ramp(r.lo_a, r.lo_b, d), up = ramp(r.up_a, r.up_b, d);
    const float w = lo * (1.0f - up);
    if (!(w > 0.0f)) return 0.0f;
    if (lo < 1.0f) return -w;           // fading in
    if (up > 0.0f) return 1.0f - w;     // fading out
    return 0.0f;                        // solid
}

void MidField::set_dials(const MidDials& d) { dials_ = d; tile_cache_.clear(); }
void MidField::set_collections(std::vector<MidCollection> c) {
    collections_ = std::move(c);
    tile_cache_.clear();
}
void MidField::set_view_dirs(std::vector<glm::vec3> v) {
    view_dirs_ = std::move(v);
    views_ = far::make_impostor_views(view_dirs_);
}
void MidField::set_sources(const std::vector<far::DiscSource>& active) {
    // The host re-pushes the same sources every frame (far_set_frame): keep
    // the cache unless a field the selection reads changed.
    if (!detail::same_generators(active, sources_)) tile_cache_.clear();
    sources_ = active;
}

std::size_t MidField::TileKeyHash::operator()(const TileKey& t) const {
    std::uint64_t h = static_cast<std::uint64_t>(t.lvl) * 0x9E3779B97F4A7C15ull;
    h ^= static_cast<std::uint64_t>(t.i) * 0xC2B2AE3D27D4EB4Full;
    h = (h << 31) | (h >> 33);
    h ^= static_cast<std::uint64_t>(t.j) * 0x165667B19E3779F9ull;
    h = (h << 29) | (h >> 35);
    h ^= static_cast<std::uint64_t>(t.k) * 0x27D4EB2F165667C5ull;
    return static_cast<std::size_t>(h ^ (h >> 32));
}

void MidField::build(const MidBuildInput& in, MidOutput& out) const {
    out.sprites.clear();
    out.sprites_fading.clear();
    out.count = out.fading = out.tiles = 0;
    if (views_.grid < 2 || sources_.empty() || collections_.empty() || dials_.max_sprites <= 0)
        return;

    const MidDials& m = dials_;
    std::vector<int> by_variant[3];
    for (const MidCollection& c : collections_)
        if (c.variant >= 0 && c.variant <= 2) by_variant[c.variant].push_back(c.atlas_index);

    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const glm::dvec3 to_render = in.anchor_sys + in.render_origin;   // render = sys - to_render
    const glm::dvec3 eye_sys = glm::dvec3(eye) + to_render;
    const float sprite_scale = std::max(m.sprite_scale, 0.0f);

    std::vector<Cand> cands;
    // One tile's selection -- presence, collection, jitter, size, spin --
    // keyed by the tile alone. `pos_sys` is the point the tile stands for
    // (its centre, or a snapped tile's source centre); the sprite is
    // jittered by up to +-jitter_gu per axis (0.25 T; a snap's 0.25 R) and
    // its diameter is diameter_gu * scale * (0.8 + 0.4 u) (T; a snap's 2R).
    const auto select = [&](int lvl, const glm::i64vec3& ijk, const glm::dvec3& pos_sys,
                            double jitter_gu, double diameter_gu) {
        TileSel sel;
        std::uint64_t h = mix(kTileSalt, static_cast<std::uint64_t>(lvl));
        h = mix(h, static_cast<std::uint64_t>(ijk.x));
        h = mix(h, static_cast<std::uint64_t>(ijk.y));
        h = mix(h, static_cast<std::uint64_t>(ijk.z));
        rockrand::Rng rng{h};
        const float u0 = rng.unit(), u1 = rng.unit(), u2 = rng.unit(),
                    u3 = rng.unit(), u4 = rng.unit(), u5 = rng.unit();
        sel.jitter = (glm::vec3(u2, u3, u4) - 0.5f) * static_cast<float>(2.0 * jitter_gu);

        double dens = 0.0;
        for (const auto& s : sources_) dens += far::field_density(s, pos_sys);
        dens = std::min(dens, 1.0);
        const float df = static_cast<float>(dens) * m.fill;
        const float chance = std::clamp(df, 0.0f, 1.0f);
        if (!(u0 < chance)) return sel;

        const int variant = df < 1.0f / 3.0f ? 0 : (df < 2.0f / 3.0f ? 1 : 2);
        const std::vector<int>& pool = by_variant[variant];
        if (pool.empty()) return sel;
        const float pick = u1 * static_cast<float>(pool.size());
        const std::size_t idx = std::min(pool.size() - 1, static_cast<std::size_t>(pick));
        // The pick's remainder: a second uniform from u1 for the size.
        const float u1b = std::clamp(pick - static_cast<float>(idx), 0.0f, 1.0f);

        rockrand::Rng axis_rng{h ^ kAxisSalt};
        const glm::vec3 axis = rockrand::unit_vector(axis_rng);
        sel.present = true;
        sel.atlas = pool[idx];
        sel.R = glm::mat3(glm::rotate(glm::mat4(1.0f), u5 * 6.28318530718f, axis));
        sel.half = 0.5f * static_cast<float>(diameter_gu) * sprite_scale * (0.8f + 0.4f * u1b);
        return sel;
    };
    // The near-band guard, the level weight and the dither are decided at
    // the DRAWN sprite's distance, so no sprite ever sits inside in_lo_gu.
    // The caller has already frustum-culled the tile point c0.
    // `r` is the level's ramps: the weight and dither are mid_level_weight /
    // mid_level_dither's, computed once here from the same two ramps.
    const auto emit = [&](const LevelRamps& r, const TileSel& sel, const glm::vec3& c0) {
        const glm::vec3 c = c0 + sel.jitter;
        const float d = glm::length(c - eye);
        if (d < m.in_lo_gu) return;   // the near band's (no double drawing)
        const float lo = ramp(r.lo_a, r.lo_b, d), up = ramp(r.up_a, r.up_b, d);
        const float w = lo * (1.0f - up);
        if (!(w > 0.0f)) return;
        ++out.tiles;
        if (!sel.present) return;
        // Fading (dither != 0, drawn translucent): `band` is the far end of
        // the ramp it is on -- its lower ramp fading in, its upper fading out.
        float dither = 0.0f, band = 0.0f;
        if (lo < 1.0f) { dither = -w; band = r.lo_b; }
        else if (up > 0.0f) { dither = 1.0f - w; band = r.up_b; }
        cands.push_back({d, sel.atlas, c, sel.R, sel.half, dither, band});
    };

    for (int lvl = 0; lvl < 3; ++lvl) {
        const double T = level_tile(lvl, m);
        if (!(T > 0.0) || !std::isfinite(T)) continue;
        const LevelRamps r = level_ramps(lvl, m);
        // Cheap reject on the tile point: the jitter moves the sprite at
        // most |jitter| = jitter_gu * sqrt(3) from it.
        const float lo_min = std::max(r.lo_a, m.in_lo_gu);
        const auto too_near_or_far = [&](double d_tile, double reach_j) {
            return d_tile + reach_j < lo_min || d_tile - reach_j > r.up_b;
        };

        // Cluster snap (rock-fields Task 14 ruling): a SPHERE source smaller
        // than this level's tile (2R < T) would slip between tile centres, so
        // the tile holding its centre stands for it instead -- presence and
        // variant from the density at the source centre, the sprite at the
        // source centre (+-0.25 R jitter) sized from R. It REPLACES that
        // tile's centre-density sprite. First source in order wins a tile.
        std::map<std::tuple<std::int64_t, std::int64_t, std::int64_t>, std::size_t> snaps;
        for (std::size_t si = 0; si < sources_.size(); ++si) {
            const far::DiscSource& s = sources_[si];
            if (s.shape != far::DiscSource::Shape::Sphere) continue;
            const double R = s.sphere_radius_gu;
            if (!(R > 0.0) || !(2.0 * R < T)) continue;
            const glm::dvec3 t = glm::floor(s.centre / T);
            snaps.emplace(std::make_tuple(static_cast<std::int64_t>(t.x),
                                          static_cast<std::int64_t>(t.y),
                                          static_cast<std::int64_t>(t.z)), si);
        }
        for (const auto& [key, si] : snaps) {   // few: never cached
            const far::DiscSource& s = sources_[si];
            const double R = s.sphere_radius_gu;
            const glm::i64vec3 ijk(std::get<0>(key), std::get<1>(key), std::get<2>(key));
            const float r_cull = static_cast<float>(0.25 * R * std::sqrt(3.0) + 1.2 * R * sprite_scale * 1.02);
            if (too_near_or_far(glm::length(s.centre - eye_sys), (0.25 * R) * std::sqrt(3.0))) continue;
            const glm::vec3 c0(s.centre - to_render);
            if (!frustum.sphere(c0, r_cull)) continue;
            emit(r, select(lvl, ijk, s.centre, 0.25 * R, 2.0 * R), c0);
        }

        // weight > 0 only for sprite distances in (lo_a, up_b); a sprite
        // lies within 0.25 T * sqrt(3) of its tile centre.
        double reach = std::min(static_cast<double>(r.up_b) + 0.25 * T * std::sqrt(3.0),
                                0.5 * (kMaxTilesPerAxis - 1) * T);
        if (!(reach > 0.0)) continue;
        const glm::dvec3 lo_f = glm::floor((eye_sys - reach) / T);
        const glm::dvec3 hi_f = glm::floor((eye_sys + reach) / T);
        const glm::i64vec3 lo(lo_f), hi(hi_f);
        // Cull radius: tile-centre jitter (<= 0.25 T per axis) plus the
        // largest sprite half-size (make_impostor pads by 1.02).
        const float r_cull = static_cast<float>(0.25 * T * std::sqrt(3.0) + 0.6 * T * sprite_scale * 1.02);
        const double reach_j = (0.25 * T) * std::sqrt(3.0);

        // Blocks of kBlock^3 tiles (aligned in tile index space) are rejected
        // whole when every tile point in them fails the distance reject or
        // lies outside one frustum plane by more than r_cull (tile points lie
        // within the block's bounding sphere; slack covers float rounding).
        // A surviving block runs the per-tile tests unchanged. Candidates are
        // emitted block by block, not in global (i, j, k) order -- the sort
        // below orders them by (distance, atlas, position), which no two
        // sprites share.
        constexpr std::int64_t K = kBlock;
        const double ex = eye_sys.x, ey = eye_sys.y, ez = eye_sys.z;
        const double rx = to_render.x, ry = to_render.y, rz = to_render.z;
        for (std::int64_t bi = floor_div(lo.x, K); bi <= floor_div(hi.x, K); ++bi)
            for (std::int64_t bj = floor_div(lo.y, K); bj <= floor_div(hi.y, K); ++bj)
                for (std::int64_t bk = floor_div(lo.z, K); bk <= floor_div(hi.z, K); ++bk) {
                    const glm::i64vec3 b0(std::max(bi * K, lo.x), std::max(bj * K, lo.y),
                                          std::max(bk * K, lo.z));
                    const glm::i64vec3 b1(std::min(bi * K + K - 1, hi.x), std::min(bj * K + K - 1, hi.y),
                                          std::min(bk * K + K - 1, hi.z));
                    const glm::dvec3 pmin = (glm::dvec3(b0) + 0.5) * T, pmax = (glm::dvec3(b1) + 0.5) * T;
                    const glm::dvec3 bc = 0.5 * (pmin + pmax);
                    const double brad = 0.5 * glm::length(pmax - pmin);
                    const double dc = glm::length(bc - eye_sys);
                    constexpr double kEps = 1e-3;
                    if (dc + brad + reach_j < static_cast<double>(lo_min) - kEps) continue;
                    if (dc - brad - reach_j > static_cast<double>(r.up_b) + kEps) continue;
                    const glm::vec3 bc0(bc - to_render);
                    const float fslack = 1.0f + 1e-5f * glm::length(bc0);
                    if (!frustum.sphere(bc0, static_cast<float>(brad) + r_cull + fslack)) continue;

                    BlockSel* block = nullptr;
                    for (std::int64_t i = b0.x; i <= b1.x; ++i)
                        for (std::int64_t j = b0.y; j <= b1.y; ++j)
                            for (std::int64_t k = b0.z; k <= b1.z; ++k) {
                                // (dvec3(i, j, k) + 0.5) * T, length(centre - eye) and
                                // vec3(centre - to_render), as scalars: bit-identical.
                                const double cx = (static_cast<double>(i) + 0.5) * T;
                                const double cy = (static_cast<double>(j) + 0.5) * T;
                                const double cz = (static_cast<double>(k) + 0.5) * T;
                                const double d_tile = std::sqrt(dot3(cx - ex, cy - ey, cz - ez,
                                                                     cx - ex, cy - ey, cz - ez));
                                if (too_near_or_far(d_tile, reach_j)) continue;
                                const glm::vec3 c0(static_cast<float>(cx - rx), static_cast<float>(cy - ry),
                                                   static_cast<float>(cz - rz));
                                if (!frustum.sphere(c0, r_cull)) continue;
                                if (!snaps.empty() && snaps.count(std::make_tuple(i, j, k))) continue;
                                if (block == nullptr) {
                                    const TileKey bkey{lvl, bi, bj, bk};
                                    auto it = tile_cache_.find(bkey);
                                    if (it == tile_cache_.end()) {
                                        if (tile_cache_.size() >= kMaxCachedBlocks) {
                                            tile_cache_.clear();
                                            ++cache_stats_.evictions;
                                        }
                                        it = tile_cache_.emplace(bkey, BlockSel{}).first;
                                    }
                                    block = &it->second;
                                }
                                const int local = static_cast<int>(((i - bi * K) * K + (j - bj * K)) * K + (k - bk * K));
                                TileSel& sel = block->tiles[static_cast<std::size_t>(local)];
                                if (!(block->done >> local & 1u)) {
                                    sel = select(lvl, {i, j, k}, glm::dvec3(cx, cy, cz), 0.25 * T, T);
                                    ++cache_stats_.fills;
                                    block->done |= std::uint64_t{1} << local;
                                }
                                emit(r, sel, c0);
                            }
                }
    }

    // Nearest first so the cap drops the far end; ties by atlas slot and
    // position keep the order independent of enumeration order.
    std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
        if (a.dist != b.dist) return a.dist < b.dist;
        if (a.atlas != b.atlas) return a.atlas < b.atlas;
        return std::tie(a.c.x, a.c.y, a.c.z) < std::tie(b.c.x, b.c.y, b.c.z);
    });
    if (cands.size() > static_cast<std::size_t>(m.max_sprites))
        cands.resize(static_cast<std::size_t>(m.max_sprites));

    std::map<int, std::vector<far::ImpostorGpu>> bins;   // solid, by atlas
    for (const Cand& cn : cands)
        if (cn.dither == 0.0f)
            bins[cn.atlas].push_back(far::make_impostor(views_, eye, cn.c, cn.R, cn.half, cn.dither));
    for (auto& [atlas, items] : bins) {
        out.count += static_cast<int>(items.size());
        out.sprites.push_back(far::ImpostorBin{atlas, std::move(items)});
    }
    // Translucent (rock fade), blended back to front: walk the candidates
    // farthest first; each run of one fade band becomes that band's bins in
    // atlas order, each bin's items farthest first. The bands are disjoint
    // distance ranges with the default dials, so this is (band farthest
    // first, atlas); dials that overlap two bands only split a band into
    // more, still far-to-near, runs.
    std::map<int, std::vector<far::ImpostorGpu>> run;
    float run_band = -1.0f;
    const auto flush = [&] {
        for (auto& [atlas, items] : run) {
            out.count += static_cast<int>(items.size());
            out.fading += static_cast<int>(items.size());
            out.sprites_fading.push_back(far::ImpostorBin{atlas, std::move(items)});
        }
        run.clear();
    };
    for (std::size_t i = cands.size(); i-- > 0;) {
        const Cand& cn = cands[i];
        if (cn.dither == 0.0f) continue;
        if (cn.band != run_band) { flush(); run_band = cn.band; }
        run[cn.atlas].push_back(far::make_impostor(views_, eye, cn.c, cn.R, cn.half, cn.dither));
    }
    flush();
}

}  // namespace renderer::rockfield
