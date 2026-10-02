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
using detail::mix;

// Source-independent salts: overlapping sources share every tile's hashes,
// so they never place a tile's sprite twice (their densities sum instead).
constexpr std::uint64_t kTileSalt = 0x6D69645F74696C65ull;   // "mid_tile"
constexpr std::uint64_t kAxisSalt = 0x6D69645F61786973ull;   // "mid_axis"

// A level never spans more than this many tiles per axis: a tile dial pushed
// far below its level's range shrinks the range, never the tiles (as
// NearField's kMaxCellsPerAxis). The defaults need ~10.
constexpr int kMaxTilesPerAxis = 33;

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

void MidField::set_dials(const MidDials& d) { dials_ = d; }
void MidField::set_collections(std::vector<MidCollection> c) { collections_ = std::move(c); }
void MidField::set_view_dirs(std::vector<glm::vec3> v) { view_dirs_ = std::move(v); }
void MidField::set_sources(const std::vector<far::DiscSource>& active) { sources_ = active; }

void MidField::build(const MidBuildInput& in, MidOutput& out) const {
    out.sprites.clear();
    out.count = out.tiles = 0;
    if (view_dirs_.empty() || sources_.empty() || collections_.empty() || dials_.max_sprites <= 0)
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
    // One tile's sprite. `pos_sys` is the point the tile stands for (its
    // centre, or a snapped tile's source centre); the sprite is jittered by
    // up to +-jitter_gu per axis (0.25 T; a snap's 0.25 R) and its diameter
    // is diameter_gu * scale * (0.8 + 0.4 u) (T; a snap's 2R).
    const auto emit = [&](int lvl, const glm::i64vec3& ijk, const glm::dvec3& pos_sys,
                          double jitter_gu, double diameter_gu, float r_cull) {
        const float d = static_cast<float>(glm::length(pos_sys - eye_sys));
        if (d < m.in_lo_gu) return;   // the near band's (no double drawing)
        const float w = mid_level_weight(lvl, d, m);
        if (!(w > 0.0f)) return;
        const glm::vec3 c0(pos_sys - to_render);
        if (!frustum.sphere(c0, r_cull)) return;
        ++out.tiles;

        double dens = 0.0;
        for (const auto& s : sources_) dens += far::field_density(s, pos_sys);
        dens = std::min(dens, 1.0);
        const float df = static_cast<float>(dens) * m.fill;
        const float chance = std::clamp(df, 0.0f, 1.0f);

        std::uint64_t h = mix(kTileSalt, static_cast<std::uint64_t>(lvl));
        h = mix(h, static_cast<std::uint64_t>(ijk.x));
        h = mix(h, static_cast<std::uint64_t>(ijk.y));
        h = mix(h, static_cast<std::uint64_t>(ijk.z));
        rockrand::Rng rng{h};
        const float u0 = rng.unit(), u1 = rng.unit(), u2 = rng.unit(),
                    u3 = rng.unit(), u4 = rng.unit(), u5 = rng.unit();
        if (!(u0 < chance)) return;

        const int variant = df < 1.0f / 3.0f ? 0 : (df < 2.0f / 3.0f ? 1 : 2);
        const std::vector<int>& pool = by_variant[variant];
        if (pool.empty()) return;
        const float pick = u1 * static_cast<float>(pool.size());
        const std::size_t idx = std::min(pool.size() - 1, static_cast<std::size_t>(pick));
        // The pick's remainder: a second uniform from u1 for the size.
        const float u1b = std::clamp(pick - static_cast<float>(idx), 0.0f, 1.0f);

        const glm::vec3 c = c0 + (glm::vec3(u2, u3, u4) - 0.5f) * static_cast<float>(2.0 * jitter_gu);
        rockrand::Rng axis_rng{h ^ kAxisSalt};
        const glm::vec3 axis = rockrand::unit_vector(axis_rng);
        const glm::mat3 R(glm::rotate(glm::mat4(1.0f), u5 * 6.28318530718f, axis));
        const float half = 0.5f * static_cast<float>(diameter_gu) * sprite_scale * (0.8f + 0.4f * u1b);
        // Weight and dither from the tile point's distance (as the gate above).
        cands.push_back({glm::length(c - eye), pool[idx], c, R, half,
                         mid_level_dither(lvl, d, m)});
    };

    for (int lvl = 0; lvl < 3; ++lvl) {
        const double T = level_tile(lvl, m);
        if (!(T > 0.0) || !std::isfinite(T)) continue;
        const LevelRamps r = level_ramps(lvl, m);

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
        for (const auto& [key, si] : snaps) {
            const far::DiscSource& s = sources_[si];
            const double R = s.sphere_radius_gu;
            const glm::i64vec3 ijk(std::get<0>(key), std::get<1>(key), std::get<2>(key));
            const float r_cull = static_cast<float>(0.25 * R * std::sqrt(3.0) + 1.2 * R * sprite_scale * 1.02);
            emit(lvl, ijk, s.centre, 0.25 * R, 2.0 * R, r_cull);
        }

        // weight > 0 only for tile-centre distances in (lo_a, up_b).
        double reach = std::min(static_cast<double>(r.up_b), 0.5 * (kMaxTilesPerAxis - 1) * T);
        if (!(reach > 0.0)) continue;
        const glm::dvec3 lo_f = glm::floor((eye_sys - reach) / T);
        const glm::dvec3 hi_f = glm::floor((eye_sys + reach) / T);
        const glm::i64vec3 lo(lo_f), hi(hi_f);
        // Cull radius: tile-centre jitter (<= 0.25 T per axis) plus the
        // largest sprite half-size (make_impostor pads by 1.02).
        const float r_cull = static_cast<float>(0.25 * T * std::sqrt(3.0) + 0.6 * T * sprite_scale * 1.02);

        for (std::int64_t i = lo.x; i <= hi.x; ++i)
            for (std::int64_t j = lo.y; j <= hi.y; ++j)
                for (std::int64_t k = lo.z; k <= hi.z; ++k) {
                    if (!snaps.empty() && snaps.count(std::make_tuple(i, j, k))) continue;
                    const glm::dvec3 centre_sys = (glm::dvec3(i, j, k) + 0.5) * T;
                    emit(lvl, {i, j, k}, centre_sys, 0.25 * T, T, r_cull);
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

    std::map<int, std::vector<far::ImpostorGpu>> bins;
    for (const Cand& cn : cands)
        bins[cn.atlas].push_back(far::make_impostor(view_dirs_, eye, cn.c, cn.R, cn.half, cn.dither));
    for (auto& [atlas, items] : bins) {
        out.count += static_cast<int>(items.size());
        out.sprites.push_back(far::ImpostorBin{atlas, std::move(items)});
    }
}

}  // namespace renderer::rockfield
