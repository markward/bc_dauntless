// native/tests/renderer/rock_speck_test.cc
// Rock-field speck band (2026-10-04).
#include <gtest/gtest.h>
#include <chrono>
#include <cstdio>
#include <set>
#include <tuple>
#include <renderer/rock_speck.h>
#include <renderer/rock_puffs.h>

using namespace renderer;
namespace {
far::DiscSource full_sphere() {          // density 1 everywhere within 10,000 GU, no noise
    far::DiscSource s; s.id = 3; s.seed = 99; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 10000.0f; s.sphere_edge_frac = 0.0f; s.view_space = true;
    return s;
}
rockfield::NearCatalogue cat() {
    rockfield::NearCatalogue k; k.small_rocks = {1, 2, 3}; k.large_rocks = {10, 11};
    return k;
}
void setup(rockfield::SpeckBand& b) {
    b.set_near_dials({});
    b.set_dials({});
    b.set_catalogue(cat(), {});
    b.set_sources({full_sphere()});
}
}  // namespace

TEST(SpeckBand, KeepAlphaIsOneInsideD0AndFallsBeyond) {
    rockfield::SpeckDials s;
    EXPECT_FLOAT_EQ(rockfield::speck_keep_alpha(100.0f, 0.999f, s), 1.0f);
    EXPECT_FLOAT_EQ(rockfield::speck_keep_alpha(s.keep_d0_gu, 0.999f, s), 1.0f);
    EXPECT_FLOAT_EQ(rockfield::speck_keep_alpha(3.0f * s.keep_d0_gu, 0.9f, s), 0.0f);
    EXPECT_GT(rockfield::speck_keep_alpha(3.0f * s.keep_d0_gu, 0.01f, s), 0.0f);
}

TEST(SpeckBand, SpecksInsideD0AreExactlyTheNearBandsLargeRocks) {
    rockfield::SpeckBand b;
    setup(b);
    rockfield::SpeckDials sd; sd.keep_d0_gu = 600.0f;   // a band of whole cells past the billboard edge
    b.set_dials(sd);
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    std::set<std::tuple<float, float, float, float>> got;
    for (const auto& g : b.instances()) {
        const glm::dvec3 p = glm::dvec3(g.pos) + b.origin_sys();
        got.insert({static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z), g.radius});
    }
    // Every large cell wholly in [in_gu, keep_d0_gu] of the origin: each of
    // its near rocks is a speck.
    rockfield::NearDials nd;
    const double L = nd.large.cell_gu;
    int checked = 0;
    for (int i = -12; i <= 12; ++i)
        for (int j = -12; j <= 12; ++j)
            for (int k = -12; k <= 12; ++k) {
                const glm::dvec3 lo = glm::dvec3(i, j, k) * L;
                const double dn = glm::length(glm::max(glm::max(lo, -(lo + L)), glm::dvec3(0.0)));
                const double df = glm::length(glm::max(glm::abs(lo), glm::abs(lo + L)));
                if (dn < nd.large.billboard_gu || df > sd.keep_d0_gu) continue;
                for (const auto& r : rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large,
                                                                   {i, j, k}, nd, cat())) {
                    const glm::dvec3 p = r.pos_sys;
                    EXPECT_TRUE(got.count({static_cast<float>(p.x), static_cast<float>(p.y),
                                           static_cast<float>(p.z), r.radius}))
                        << "cell " << i << "," << j << "," << k;
                    ++checked;
                }
            }
    EXPECT_GT(checked, 50);
}

TEST(SpeckBand, FullDensityCountIsBoundedAndRestreamIsIncremental) {
    rockfield::SpeckBand b;
    setup(b);
    const auto t0 = std::chrono::steady_clock::now();
    b.stream(glm::dvec3(0.0), 0.0f);
    const auto ts = std::chrono::steady_clock::now();
    ASSERT_TRUE(b.finish());
    const auto t1 = std::chrono::steady_clock::now();
    const int first_cells = b.last_stream_cells_generated();
    EXPECT_FALSE(b.stream(glm::dvec3(10.0, 0.0, 0.0), 0.0f));   // under restream_gu
    EXPECT_FALSE(b.finish());                                    // nothing launched
    const auto t1b = std::chrono::steady_clock::now();
    b.stream(glm::dvec3(60.0, 0.0, 0.0), 0.0f);
    const auto t1c = std::chrono::steady_clock::now();
    ASSERT_TRUE(b.finish());
    const auto t2 = std::chrono::steady_clock::now();
    const double ms0 = std::chrono::duration<double, std::milli>(t1 - t0).count();
    const double ms1 = std::chrono::duration<double, std::milli>(t2 - t1b).count();
    const double launch0 = std::chrono::duration<double, std::milli>(ts - t0).count();
    const double launch1 = std::chrono::duration<double, std::milli>(t1c - t1b).count();
    std::printf("[speck band] main-thread cost of stream(): %.2f ms first, %.2f ms restream\n",
                launch0, launch1);
    std::printf("[speck band] full density: %zu specks, %d cells; first stream %.1f ms "
                "(%d cells generated), 60 GU restream %.1f ms (%d generated)\n",
                b.instances().size(), b.cells(), ms0, first_cells, ms1,
                b.last_stream_cells_generated());
    // keep_d0 420 (behind the 405 GU billboards). The margin is 2 x
    // restream_gu at rest (review I4: it must cover the trigger overshoot and
    // the worker's latency), not restream_gu: ~235k here, was ~160k at 50 GU.
    EXPECT_LT(b.instances().size(), 250000u);
    EXPECT_LT(b.last_stream_cells_generated(), first_cells / 2);
}

TEST(SpeckBand, DashHidesAndSlowShowsAgain) {
    rockfield::SpeckBand b;
    setup(b);
    b.stream(glm::dvec3(0.0), 25.0f);
    b.finish();
    EXPECT_FALSE(b.stream(glm::dvec3(500.0, 0.0, 0.0), 25.0f));
    EXPECT_TRUE(b.hidden());
    b.stream(glm::dvec3(505.0, 0.0, 0.0), 25.0f);
    EXPECT_FALSE(b.hidden());
    EXPECT_TRUE(b.finish());
}

TEST(Puffs, BeltPuffsFollowTheBeltDensity) {
    far::DiscSource belt; belt.id = 5; belt.seed = 7;
    belt.table = {{0.0f, 0.0f}, {9000.0f, 0.0f}, {10000.0f, 1.0f}, {11000.0f, 0.0f}};
    belt.outer_fade_gu = 0.0f;
    rockfield::PuffDials d; d.belt_count = 300;
    std::vector<glm::dvec3> pos;
    const auto p = rockfield::place_puffs(belt, d, &pos);
    ASSERT_EQ(p.size(), 300u);
    for (std::size_t i = 0; i < p.size(); ++i) {
        const double rho = glm::length(glm::dvec2(pos[i]));
        EXPECT_GT(rho, 9000.0); EXPECT_LT(rho, 11000.0);
        EXPECT_GT(p[i].radius, 0.0f);
    }
    std::vector<glm::dvec3> pos2;
    const auto q = rockfield::place_puffs(belt, d, &pos2);
    EXPECT_EQ(pos, pos2);   // deterministic
}

TEST(Puffs, TileFieldPuffsStayInsideTheField) {
    far::DiscSource s = full_sphere(); s.sphere_radius_gu = 1000.0f;
    rockfield::PuffDials d;
    std::vector<glm::dvec3> pos;
    const auto p = rockfield::place_puffs(s, d, &pos);
    ASSERT_EQ(p.size(), static_cast<std::size_t>(d.count));
    for (const auto& x : pos) EXPECT_LE(glm::length(x - s.centre), 1000.0 + 1e-6);
}

// ---- Review fixes (2026-10-04 kept-code review, I2-I6, M1-M4, M6) -----------
// Every dial these tests depend on is spelled out (never a default).
#include <algorithm>
#include <map>
#include <unordered_map>
namespace {
rockfield::NearDials pinned_near() {
    rockfield::NearDials d;
    d.small = {0.010f, 0.05f, 0.5f, 2.5f, 10.0f, 15.0f, 90.0f, 4000};
    d.large = {1.0f / 16000.0f, 1.0f, 5.0f, 2.5f, 50.0f, 60.0f, 405.0f, 4000};
    d.fade_gu = 4.0f; d.tumble_scale = 0.05f; d.dash_collapse_step_gu = 25.0f;
    d.large_min_px = 0.0f; d.small_min_px = 2.5f; d.stream_margin_gu = 10.0f;
    return d;
}
rockfield::SpeckDials pinned_speck() {
    rockfield::SpeckDials s;
    s.out_gu = 1500.0f; s.out_fade_gu = 400.0f; s.keep_d0_gu = 420.0f; s.keep_power = 3.0f;
    s.keep_band = 0.25f; s.restream_gu = 50.0f; s.gain = 0.25f;
    return s;
}
far::DiscSource field(float R) {          // full density within R of the origin, no noise
    far::DiscSource s = full_sphere(); s.sphere_radius_gu = R; return s;
}
void setup_pinned(rockfield::SpeckBand& b, const std::vector<far::DiscSource>& src,
                  const rockfield::SpeckDials& sd = pinned_speck()) {
    b.set_near_dials(pinned_near());
    b.set_dials(sd);
    b.set_catalogue(cat(), {});
    b.set_sources(src);
}
using SeedKey = std::tuple<float, float, float, float, float>;
SeedKey seed_key(const glm::vec4& s, float r) { return {s.x, s.y, s.z, s.w, r}; }

// The shader's alpha (rock_speck.vert) for a rock at distance d with cell hash u.
float shader_alpha(float d, float u, const rockfield::SpeckDials& sd, const rockfield::NearDials& nd) {
    const float in = nd.large.billboard_gu, fade = nd.fade_gu;
    const float a_in = std::clamp((d - (in - fade)) / fade, 0.0f, 1.0f);
    const float a_out = std::clamp((sd.out_gu - d) / sd.out_fade_gu, 0.0f, 1.0f);
    rockfield::SpeckDials k = sd;
    k.keep_d0_gu = rockfield::speck_keep_d0(sd, in, fade);
    return a_in * a_out * rockfield::speck_keep_alpha(d, u, k);
}
}  // namespace

// I2: every field the density reads invalidates the speck band, the near
// band and the puffs.
TEST(ReviewFixes, EveryDensityFieldInvalidatesAllThreeBands) {
    using Mut = void (*)(far::DiscSource&);
    const std::vector<std::pair<const char*, Mut>> muts = {
        {"shape_warp", [](far::DiscSource& s) { s.shape_warp = 0.3f; s.shape_warp_scale_gu = 900.0f; }},
        {"noise_sharpness", [](far::DiscSource& s) { s.noise_sharpness = 2.0f; }},
        {"sphere_edge_frac", [](far::DiscSource& s) { s.sphere_edge_frac = 0.4f; }},
        {"noise_octaves", [](far::DiscSource& s) { s.noise_octaves = 5; }},
        {"outer_fade_gu", [](far::DiscSource& s) { s.outer_fade_gu = 10.0f; }},
        {"scale_height_frac", [](far::DiscSource& s) { s.scale_height_frac = 0.05f; }},
        {"explicit_regions", [](far::DiscSource& s) { s.explicit_regions.push_back({0, 0, 0, 5}); }},
        {"shape", [](far::DiscSource& s) { s.shape = far::DiscSource::Shape::Disc; }},
    };
    far::DiscSource base = field(3000.0f);
    base.noise_scale_gu = 600.0f; base.noise_contrast = 0.6f; base.noise_octaves = 3;
    for (const auto& [name, mut] : muts) {
        far::DiscSource changed = base;
        mut(changed);
        EXPECT_FALSE(far::same_density(base, changed)) << name;
        rockfield::SpeckBand b;
        setup_pinned(b, {base});
        b.stream(glm::dvec3(0.0), 0.0f);
        ASSERT_TRUE(b.finish());
        ASSERT_GT(b.cells(), 0);
        const auto v = b.version();
        b.set_sources({base});   // the same: kept
        EXPECT_GT(b.cells(), 0) << name;
        b.set_sources({changed});
        EXPECT_EQ(b.cells(), 0) << name;
        EXPECT_TRUE(b.instances().empty()) << name;
        EXPECT_GT(b.version(), v) << name;

        rockfield::NearField nf;
        nf.set_dials(pinned_near());
        nf.set_catalogue(cat());
        nf.set_sources({base});
        nf.stream(glm::dvec3(0.0));
        ASSERT_GT(nf.stats().cells, 0);
        nf.set_sources({base});
        EXPECT_GT(nf.stats().cells, 0) << name;
        nf.set_sources({changed});
        EXPECT_EQ(nf.stats().cells, 0) << name;
    }
    // Puffs: a change moves them; the colour (first population) recolours.
    rockfield::PuffField pf;
    rockfield::PuffDials pd; pd.count = 60;
    pf.set_dials(pd);
    far::DiscSource s = field(3000.0f);
    s.pops.push_back({}); s.pops.back().albedo = glm::vec3(0.3f);
    pf.set_sources({s});
    (void)pf.take_dirty();
    const auto before = pf.instances();
    pf.set_sources({s});
    EXPECT_FALSE(pf.take_dirty());   // the same sources: no rebuild
    far::DiscSource w = s; w.shape_warp = 0.3f; w.shape_warp_scale_gu = 900.0f;
    pf.set_sources({w});
    EXPECT_TRUE(pf.take_dirty());
    far::DiscSource sh = s; sh.noise_scale_gu = 600.0f; sh.noise_contrast = 0.8f; sh.noise_octaves = 3;
    pf.set_sources({sh});
    EXPECT_TRUE(pf.take_dirty());
    sh.noise_sharpness = 3.0f;
    pf.set_sources({sh});
    EXPECT_TRUE(pf.take_dirty());
    far::DiscSource col = sh; col.pops.back().albedo = glm::vec3(0.7f);
    pf.set_sources({col});
    ASSERT_TRUE(pf.take_dirty());
    ASSERT_FALSE(pf.instances().empty());
    EXPECT_EQ(pf.instances().front().albedo, glm::vec3(0.7f));
    // A dial rebuild reads the sources last set, not a stale copy.
    pd.count = 61;
    pf.set_dials(pd);
    EXPECT_EQ(pf.instances().front().albedo, glm::vec3(0.7f));
    (void)before;
}

// I3: a warped tile field's lobes beyond sphere_radius_gu + reach stream
// near rocks (and the speck band specks).
TEST(ReviewFixes, AWarpedLobeStreamsNearRocks) {
    far::DiscSource s = field(3000.0f);
    s.shape_warp = 0.35f; s.shape_warp_scale_gu = 1800.0f;
    // Find a point well past R + the large reach with real density.
    glm::dvec3 lobe(0.0);
    bool found = false;
    for (int k = 0; k < 4000 && !found; ++k) {
        const double th = 0.7 * k, ph = 0.31 * k;
        const glm::dvec3 dir(std::cos(th) * std::sin(ph), std::sin(th) * std::sin(ph), std::cos(ph));
        for (double r = 3500.0; r < 4200.0 && !found; r += 50.0)
            if (far::field_density(s, dir * r) > 0.5f) { lobe = dir * r; found = true; }
    }
    ASSERT_TRUE(found) << "no lobe past R + 500 for this seed";
    ASSERT_GT(glm::length(lobe), 3000.0 + 405.0 + 10.0);
    rockfield::NearField nf;
    nf.set_dials(pinned_near());
    nf.set_catalogue(cat());
    nf.set_sources({s});
    nf.stream(lobe);
    EXPECT_GT(nf.stats().large, 0) << "an empty lobe: no near rocks, no collisions";
}

// I5: a source whose reach misses the stream sphere is skipped whole.
TEST(ReviewFixes, ASourceOutOfReachAddsNoCells) {
    rockfield::SpeckBand a, b;
    setup_pinned(a, {field(3000.0f)});
    std::vector<far::DiscSource> many = {field(3000.0f)};
    for (int i = 0; i < 4; ++i) {
        far::DiscSource f = field(3000.0f);
        f.id = 10 + i; f.seed = 1000 + i; f.centre = glm::dvec3(1.0e6 * (i + 1), 0.0, 0.0);
        many.push_back(f);
    }
    setup_pinned(b, many);
    a.stream(glm::dvec3(0.0), 0.0f);
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(a.finish());
    ASSERT_TRUE(b.finish());
    EXPECT_GT(a.cells(), 0);
    EXPECT_EQ(a.cells(), b.cells());
    EXPECT_EQ(a.instances().size(), b.instances().size());
}

// I5: small cells are capped per axis (the walk is bounded), so a rebuild
// at 20 GU cells reaches at most (kSpeckMaxCellsPerAxis - 1) / 2 cells out.
TEST(ReviewFixes, SmallCellsAreCappedPerAxis) {
    rockfield::SpeckBand b;
    b.set_dials(pinned_speck());
    rockfield::NearDials nd = pinned_near();
    nd.large.cell_gu = 20.0f;
    b.set_near_dials(nd);
    b.set_catalogue(cat(), {});
    b.set_sources({field(3000.0f)});
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    const double cap = 0.5 * (rockfield::kSpeckMaxCellsPerAxis - 1) * 20.0;
    ASSERT_FALSE(b.instances().empty());
    for (const auto& g : b.instances())
        EXPECT_LE(glm::length(glm::dvec3(g.pos)), cap + 20.0 * 1.7321 + 1e-3);
}

// I5: clear() cancels a rebuild in flight (it stops early and is discarded).
TEST(ReviewFixes, ClearCancelsARebuildInFlight) {
    rockfield::SpeckBand b;
    setup_pinned(b, {full_sphere()});
    b.stream(glm::dvec3(0.0), 0.0f);
    b.clear();
    EXPECT_FALSE(b.finish());
    EXPECT_TRUE(b.debug_last_job_cancelled());
    EXPECT_EQ(b.cells(), 0);
    EXPECT_TRUE(b.instances().empty());
    // ... and the next stream rebuilds in full.
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    EXPECT_FALSE(b.debug_last_job_cancelled());
    EXPECT_GT(b.cells(), 0);
    // A band destroyed mid-rebuild does not wait the rebuild out.
    { rockfield::SpeckBand c; setup_pinned(c, {full_sphere()}); c.stream(glm::dvec3(0.0), 0.0f); }
}

// I6: a rock's shape seed is a function of the rock, not of the band origin.
TEST(ReviewFixes, ShapeSeedsAreStableAcrossARestream) {
    rockfield::SpeckBand b;
    setup_pinned(b, {full_sphere()});
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    std::map<std::tuple<float, float, float>, glm::vec4> first;
    std::set<std::tuple<float, float, float, float>> distinct;
    for (const auto& g : b.instances()) {
        first[{g.pos.x, g.pos.y, g.pos.z}] = g.seed;
        distinct.insert({g.seed.x, g.seed.y, g.seed.z, g.seed.w});
    }
    EXPECT_GT(distinct.size(), b.instances().size() * 9 / 10);   // per rock, not one shared seed
    const glm::dvec3 o1 = b.origin_sys();
    b.stream(glm::dvec3(60.0, 0.0, 0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    const glm::dvec3 o2 = b.origin_sys();
    ASSERT_NE(o1, o2);
    // Match each rock by its seed: every surviving rock keeps its seed, and
    // the seed is speck_shape_seed of its system position.
    std::map<std::tuple<float, float, float, float>, int> by_seed;
    for (const auto& [p, s] : first) by_seed[{s.x, s.y, s.z, s.w}]++;
    int kept = 0;
    for (const auto& g : b.instances()) {
        if (by_seed.count({g.seed.x, g.seed.y, g.seed.z, g.seed.w})) ++kept;
    }
    EXPECT_GT(kept, static_cast<int>(b.instances().size()) / 2);
    // Recompute from a generated rock: identical.
    const auto rocks = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {9, 0, 0},
                                                     pinned_near(), cat());
    ASSERT_FALSE(rocks.empty());
    bool hit = false;
    for (const auto& g : b.instances())
        if (g.seed == rockfield::speck_shape_seed(rocks.front().pos_sys)) hit = true;
    EXPECT_TRUE(hit);
}

// M1: clear() empties the drawn set and moves the version (the host uploads).
TEST(ReviewFixes, ClearMovesTheVersionAndEmptiesTheDrawnSet) {
    rockfield::SpeckBand b;
    setup_pinned(b, {full_sphere()});
    const auto v0 = b.version();
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    const auto v1 = b.version();
    EXPECT_GT(v1, v0);
    ASSERT_FALSE(b.instances().empty());
    b.clear();
    EXPECT_GT(b.version(), v1);
    EXPECT_TRUE(b.instances().empty());
}

// M6: a rebuild that throws is caught in the worker: an empty set, no rethrow.
TEST(ReviewFixes, AThrowingRebuildIsCaughtInTheWorker) {
    rockfield::SpeckBand b;
    setup_pinned(b, {full_sphere()});
    b.debug_fail_jobs(true);
    b.stream(glm::dvec3(0.0), 0.0f);
    bool swapped = false;
    EXPECT_NO_THROW(swapped = b.finish());
    EXPECT_TRUE(swapped);
    EXPECT_TRUE(b.instances().empty());
    b.debug_fail_jobs(false);
    EXPECT_NO_THROW(b.stream(glm::dvec3(100.0, 0.0, 0.0), 0.0f));
    ASSERT_TRUE(b.finish());
    EXPECT_FALSE(b.instances().empty());
}

// M4: thinning never starts inside the billboards' edge + fade, whatever
// keep_d0_gu says: every rock the billboards hand over is a speck.
TEST(ReviewFixes, ThinningNeverStartsInsideTheBillboardEdge) {
    rockfield::SpeckDials sd = pinned_speck();
    sd.keep_d0_gu = 50.0f;   // far inside the 405 GU edge
    const rockfield::NearDials nd = pinned_near();
    EXPECT_EQ(rockfield::speck_keep_d0(sd, 405.0f, 4.0f), 409.0f);
    EXPECT_EQ(rockfield::speck_keep_d0(pinned_speck(), 405.0f, 4.0f), 420.0f);
    rockfield::SpeckBand b;
    setup_pinned(b, {full_sphere()}, sd);
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    std::set<SeedKey> got;
    for (const auto& g : b.instances()) got.insert(seed_key(g.seed, g.radius));
    int checked = 0;
    for (int i = -9; i <= 9; ++i)
        for (int j = -9; j <= 9; ++j)
            for (int k = -9; k <= 9; ++k)
                for (const auto& r : rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large,
                                                                   {i, j, k}, nd, cat())) {
                    const double d = glm::length(r.pos_sys);
                    if (d <= nd.large.billboard_gu - nd.fade_gu || d > nd.large.billboard_gu + nd.fade_gu) continue;
                    EXPECT_TRUE(got.count(seed_key(rockfield::speck_shape_seed(r.pos_sys), r.radius)))
                        << "a handed-over rock at " << d << " GU is no speck";
                    ++checked;
                }
    EXPECT_GT(checked, 20);
}

// I4: at in-system warp speed (400 GU/s = 6.67 GU per 60 Hz frame) with a
// worst-case worker latency, no speck the shader would draw is missing from
// the drawn set on ANY frame.
TEST(ReviewFixes, NoVisibleSpeckIsMissingAt400GuPerSecond) {
    const rockfield::NearDials nd = pinned_near();
    rockfield::SpeckDials sd = pinned_speck();
    sd.out_gu = 700.0f; sd.out_fade_gu = 150.0f;   // a smaller band: the reference set per frame stays cheap
    const far::DiscSource src = field(2500.0f);
    rockfield::SpeckBand b;
    setup_pinned(b, {src}, sd);
    b.debug_set_min_job_frames(6);                 // ~100 ms at 60 Hz: twice the measured Debug restream
    const double step = 400.0 / 60.0;
    glm::dvec3 cam(-500.0, 0.0, 0.0);
    b.stream(cam, 25.0f);
    ASSERT_TRUE(b.finish());
    const double L = nd.large.cell_gu;
    std::unordered_map<std::uint64_t, std::vector<rockfield::NearRock>> gen;   // memo per cell
    std::set<SeedKey> drawn;
    std::uint64_t drawn_version = 0;
    int swaps = 0, checked = 0, missing = 0;
    for (int f = 0; f < 150; ++f) {
        cam.x += step;
        b.stream(cam, 25.0f);
        if (b.version() != drawn_version) {
            drawn.clear();
            for (const auto& g : b.instances()) drawn.insert(seed_key(g.seed, g.radius));
            drawn_version = b.version();
            ++swaps;
        }
        if (f % 2 == 1) continue;   // every other frame (cost); the worst lag is every frame before a swap
        // The reference: every rock with shader alpha > 0 from `cam`.
        const glm::i64vec3 lo_i(glm::floor((cam - double(sd.out_gu)) / L));
        const glm::i64vec3 hi_i(glm::floor((cam + double(sd.out_gu)) / L));
        for (std::int64_t i = lo_i.x; i <= hi_i.x; ++i)
            for (std::int64_t j = lo_i.y; j <= hi_i.y; ++j)
                for (std::int64_t k = lo_i.z; k <= hi_i.z; ++k) {
                    const glm::i64vec3 ijk(i, j, k);
                    const glm::dvec3 lo = glm::dvec3(ijk) * L;
                    const glm::dvec3 q = glm::max(glm::max(lo - cam, cam - (lo + L)), glm::dvec3(0.0));
                    const float dmin = static_cast<float>(glm::length(q));
                    if (dmin > sd.out_gu) continue;
                    const float u = rockfield::speck_cell_u(src.seed, ijk);
                    // Past the edge the alpha only falls with distance: the
                    // cell's nearest point bounds it.
                    if (dmin >= nd.large.billboard_gu && !(shader_alpha(dmin, u, sd, nd) > 0.0f)) continue;
                    const std::uint64_t key = (static_cast<std::uint64_t>(i & 0x1FFFFF) << 42) |
                                              (static_cast<std::uint64_t>(j & 0x1FFFFF) << 21) |
                                              static_cast<std::uint64_t>(k & 0x1FFFFF);
                    auto it = gen.find(key);
                    if (it == gen.end())
                        it = gen.emplace(key, rockfield::generate_near_cell(src, rockfield::NearClass::Large,
                                                                            ijk, nd, cat())).first;
                    for (const auto& r : it->second) {
                        const float d = static_cast<float>(glm::length(r.pos_sys - cam));
                        if (!(shader_alpha(d, u, sd, nd) > 0.0f)) continue;
                        ++checked;
                        if (!drawn.count(seed_key(rockfield::speck_shape_seed(r.pos_sys), r.radius))) ++missing;
                    }
                }
    }
    std::printf("[speck band] 400 GU/s: %d swaps, %d visible specks checked, %d missing, margin %.1f GU\n",
                swaps, checked, missing, b.next_margin_gu());
    EXPECT_GE(swaps, 10);
    EXPECT_GT(checked, 10000);
    EXPECT_EQ(missing, 0);
}

// M3: a strongly warped tile field still places every puff it asks for.
TEST(ReviewFixes, PuffsPlaceTheirCountAtHighWarp) {
    far::DiscSource s = field(1000.0f);
    s.shape_warp = 0.9f; s.shape_warp_scale_gu = 600.0f;
    rockfield::PuffDials d; d.count = 60;
    std::vector<glm::dvec3> pos;
    const auto p = rockfield::place_puffs(s, d, &pos);
    EXPECT_EQ(p.size(), 60u);
    for (const auto& x : pos) EXPECT_GT(far::field_density(s, x), 0.0f);
}

// After a dash the near billboards regrow from the mesh range back out to
// billboard_gu over ~17 frames, and the shader fades specks in at that
// REGROWING edge. The band must already hold those rocks: every rock of a
// cell wholly between the mesh range and the full billboard edge is a speck.
TEST(SpeckBand, HoldsTheRocksInsideTheBillboardEdgeForTheDashRegrow) {
    rockfield::SpeckBand b;
    setup(b);
    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    std::set<std::tuple<float, float, float, float>> got;
    for (const auto& g : b.instances()) {
        const glm::dvec3 p = glm::dvec3(g.pos) + b.origin_sys();
        got.insert({static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z), g.radius});
    }
    rockfield::NearDials nd;
    const double L = nd.large.cell_gu;
    int checked = 0;
    for (int i = -9; i <= 9; ++i)
        for (int j = -9; j <= 9; ++j)
            for (int k = -9; k <= 9; ++k) {
                const glm::dvec3 lo = glm::dvec3(i, j, k) * L;
                const double dn = glm::length(glm::max(glm::max(lo, -(lo + L)), glm::dvec3(0.0)));
                const double df = glm::length(glm::max(glm::abs(lo), glm::abs(lo + L)));
                if (dn < nd.large.mesh_gu + nd.fade_gu || df > nd.large.billboard_gu - nd.fade_gu) continue;
                for (const auto& r : rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large,
                                                                   {i, j, k}, nd, cat())) {
                    EXPECT_TRUE(got.count({static_cast<float>(r.pos_sys.x), static_cast<float>(r.pos_sys.y),
                                           static_cast<float>(r.pos_sys.z), r.radius}))
                        << "cell " << i << "," << j << "," << k;
                    ++checked;
                }
            }
    EXPECT_GT(checked, 500);
}

// Rock promotion, final review M1: a promoted or destroyed key (the list
// rockfield_set_promoted pushes) must not come back as a speck past the
// billboard edge. The speck band keys each rock exactly as the near band
// does (near_rock_key == NearField::query_large's key); an excluded key
// draws no speck while its cell neighbours still do, across a restream.
namespace {
std::set<std::tuple<float, float, float, float>> speck_set(const rockfield::SpeckBand& b) {
    std::set<std::tuple<float, float, float, float>> got;
    for (const auto& g : b.instances()) {
        const glm::dvec3 p = glm::dvec3(g.pos) + b.origin_sys();
        got.insert({static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z), g.radius});
    }
    return got;
}
std::tuple<float, float, float, float> speck_of(const rockfield::NearRock& r) {
    return {static_cast<float>(r.pos_sys.x), static_cast<float>(r.pos_sys.y),
            static_cast<float>(r.pos_sys.z), r.radius};
}
}  // namespace

TEST(SpeckBand, AnExcludedKeyDrawsNoSpeckButItsNeighboursDo) {
    rockfield::SpeckBand b;
    setup(b);
    rockfield::SpeckDials sd; sd.keep_d0_gu = 600.0f;   // no thinning out to 600 GU
    b.set_dials(sd);
    rockfield::NearDials nd;
    // A cell wholly past the 405 GU billboard edge, inside 600, with >= 2 rocks.
    glm::i64vec3 ijk{9, 0, 0};
    std::vector<rockfield::NearRock> rocks;
    for (std::int64_t j = 0; j < 8 && rocks.size() < 2; ++j) {
        ijk = {9, j, 0};
        rocks = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, ijk, nd, cat());
    }
    ASSERT_GE(rocks.size(), 2u);
    const std::uint64_t key = rockfield::near_rock_key(full_sphere().id, rockfield::NearClass::Large, ijk, 0);
    // The same key the near band's query (and so promotion) assigns that rock.
    rockfield::NearField nf;
    nf.set_catalogue(cat());
    nf.set_sources({full_sphere()});
    bool matched = false;
    for (const auto& h : nf.query_large(rocks[0].pos_sys, 0.001, 0.0f))
        if (h.rock.pos_sys == rocks[0].pos_sys) { EXPECT_EQ(h.key, key); matched = true; }
    ASSERT_TRUE(matched);

    b.stream(glm::dvec3(0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    const auto before = speck_set(b);
    ASSERT_TRUE(before.count(speck_of(rocks[0])));
    ASSERT_TRUE(before.count(speck_of(rocks[1])));
    const std::size_t n_before = b.instances().size();

    b.set_excluded({key});
    b.stream(glm::dvec3(0.0), 0.0f);                    // an exclusion change re-streams in place
    ASSERT_TRUE(b.finish());
    const auto after = speck_set(b);
    EXPECT_FALSE(after.count(speck_of(rocks[0])));
    EXPECT_TRUE(after.count(speck_of(rocks[1])));
    EXPECT_EQ(b.instances().size(), n_before - 1);

    b.stream(glm::dvec3(60.0, 0.0, 0.0), 0.0f);        // a restream keeps it out
    ASSERT_TRUE(b.finish());
    const auto moved = speck_set(b);
    EXPECT_FALSE(moved.count(speck_of(rocks[0])));
    EXPECT_TRUE(moved.count(speck_of(rocks[1])));

    b.set_excluded({});                                 // released: back as a speck
    b.stream(glm::dvec3(60.0, 0.0, 0.0), 0.0f);
    ASSERT_TRUE(b.finish());
    EXPECT_TRUE(speck_set(b).count(speck_of(rocks[0])));
}
