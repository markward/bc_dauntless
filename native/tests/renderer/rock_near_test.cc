// native/tests/renderer/rock_near_test.cc
// Rock fields (docs/superpowers/specs/2026-10-02-rock-fields-design.md):
// the near band's deterministic cells and their streaming.
#include <gtest/gtest.h>
#include <renderer/rock_near.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <set>
#include <tuple>
#include <glm/gtc/matrix_transform.hpp>
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
}

TEST(NearCells, DeterministicPerCell) {
    rockfield::NearDials d;
    const auto a = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {4, -2, 7}, d, cat());
    const auto b = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {4, -2, 7}, d, cat());
    ASSERT_EQ(a.size(), b.size());
    for (size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].pos_sys, b[i].pos_sys);
        EXPECT_EQ(a[i].radius, b[i].radius);
        EXPECT_EQ(a[i].rock, b[i].rock);
    }
}

TEST(NearCells, MeanCountMatchesDensityAtFullField) {
    rockfield::NearDials d;
    double n = 0; const int cells = 400;
    for (int i = 0; i < cells; ++i)
        n += rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small, {i, 0, 0}, d, cat()).size();
    const double expected = d.small.density * std::pow(d.small.cell_gu, 3.0);   // 8 per cell
    EXPECT_NEAR(n / cells, expected, 0.6);
}

TEST(NearCells, DensityFollowsField) {     // a 0.05 belt floor gets ~5%
    far::DiscSource belt; belt.id = 5; belt.seed = 1; belt.table = {{0.0f, 0.05f}, {1e6f, 0.05f}};
    belt.scale_height_min_gu = 1e6f;        // flat in z near the plane
    rockfield::NearDials d;
    // Pinned to the pre-2026-10-03 default (0.008 x cell_gu^3 10^3 = 8 per
    // cell at field density 1) so this expectation stays valid regardless of
    // far_dials.py's current near_small_density.
    d.small.density = 0.008f;
    double n = 0; const int cells = 2000;
    for (int i = 0; i < cells; ++i)
        n += rockfield::generate_near_cell(belt, rockfield::NearClass::Small, {i, 3, 0}, d, cat()).size();
    EXPECT_NEAR(n / cells, 0.05 * 8.0, 0.08);
}

TEST(NearCells, SizesInRangeAndRocksFromTheClassList) {
    rockfield::NearDials d;
    for (int i = 0; i < 50; ++i)
        for (const auto& r : rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, d, cat())) {
            EXPECT_GE(r.radius, d.large.r_min); EXPECT_LE(r.radius, d.large.r_max);
            EXPECT_TRUE(r.rock == 10 || r.rock == 11);
        }
}

TEST(NearCells, ExplicitRegionsAreEmpty) {   // brief: rocks inside explicit_regions are rejected
    far::DiscSource s = full_sphere();
    s.explicit_regions.push_back(glm::dvec4(0.0, 0.0, 0.0, 25.0));
    rockfield::NearDials d;
    int inside = 0, total = 0;
    for (int i = -3; i < 3; ++i)
        for (int j = -3; j < 3; ++j)
            for (int k = -3; k < 3; ++k)
                for (const auto& r : rockfield::generate_near_cell(s, rockfield::NearClass::Small, {i, j, k}, d, cat())) {
                    ++total;
                    if (glm::length(r.pos_sys) < 25.0) ++inside;
                }
    EXPECT_GT(total, 0);
    EXPECT_EQ(inside, 0);
}

TEST(NearCells, SphereCellOutsideTheRadiusIsEmpty) {
    rockfield::NearDials d;
    EXPECT_TRUE(rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Small,
                                              {2000, 0, 0}, d, cat()).empty());
}

TEST(NearStream, BoundedAndDropsCellsBehind) {
    rockfield::NearField f;
    // Pinned to the pre-far-shell large range (rock-real Part 1 streams ~2,300
    // more 50 GU large cells out to large_far_gu; NearFarLarge covers that).
    rockfield::NearDials d; d.large_far_gu = 0.0f; d.large.cell_gu = 20.0f;
    f.set_dials(d);
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const int first = f.stats().cells;
    EXPECT_GT(first, 0); EXPECT_LT(first, 1200);       // "a few hundred cells"
    f.stream(glm::dvec3(5000.0, 0.0, 0.0));            // jump far away
    EXPECT_LE(f.stats().cells, first + 10);            // old cells gone, not accumulated
    int near_origin = 0;
    f.for_each(rockfield::NearClass::Small, [&](std::uint64_t, const rockfield::NearRock& r) {
        if (glm::length(r.pos_sys) < 100.0) ++near_origin; });
    EXPECT_EQ(near_origin, 0);
}

TEST(NearStream, SameStateRegardlessOfPath) {   // returning to a place gives the same rocks
    rockfield::NearField a, b;
    for (auto* f : {&a, &b}) { f->set_catalogue(cat()); f->set_sources({full_sphere()}); }
    a.stream(glm::dvec3(0.0));
    b.stream(glm::dvec3(900.0, 0, 0)); b.stream(glm::dvec3(0.0));
    for (int i = 0; i < 10; ++i) b.stream(glm::dvec3(0.0));   // the jump shrank the far shell: regrow it
    std::set<std::uint64_t> ka, kb;
    a.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock&) { ka.insert(k); });
    b.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock&) { kb.insert(k); });
    // b may still hold margin cells; every rock in range of the origin must match
    EXPECT_FALSE(ka.empty());
    EXPECT_TRUE(std::includes(kb.begin(), kb.end(), ka.begin(), ka.end()));
}

TEST(NearStream, DialChangeClearsCells) {      // Review Focus 4
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearDials d; d.small.density *= 2.0f;
    f.set_dials(d);
    EXPECT_EQ(f.stats().cells, 0);
    f.stream(glm::dvec3(0.0));
    EXPECT_GT(f.stats().small, 0);
}

TEST(NearStream, NoSourcesNoRocks) {
    rockfield::NearField f; f.set_catalogue(cat());
    f.stream(glm::dvec3(0.0));
    EXPECT_EQ(f.stats().small + f.stats().large, 0);
}

TEST(NearStream, SourceOutOfReachMakesNoCells) {
    rockfield::NearField f; f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(50000.0, 0.0, 0.0));
    EXPECT_EQ(f.stats().cells, 0);
}

TEST(NearStream, SameSourcesKeepCellsChangedSourcesClear) {
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const int first = f.stats().cells;
    ASSERT_GT(first, 0);
    f.set_sources({full_sphere()});                    // re-pushed unchanged
    EXPECT_EQ(f.stats().cells, first);
    far::DiscSource moved = full_sphere(); moved.seed = 100;
    f.set_sources({moved});
    EXPECT_EQ(f.stats().cells, 0);
}

TEST(NearStream, NonGeneratorDialKeepsCellsAndCatalogueClears) {
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const int first = f.stats().cells;
    rockfield::NearDials d; d.fade_gu = 8.0f; d.small.max_instances = 10;
    f.set_dials(d);
    EXPECT_EQ(f.stats().cells, first);
    rockfield::NearCatalogue other; other.small_rocks = {4}; other.large_rocks = {12};
    f.set_catalogue(other);
    EXPECT_EQ(f.stats().cells, 0);
}

TEST(NearStream, StatsCountRocksPerClass) {
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    int s = 0, l = 0;
    f.for_each(rockfield::NearClass::Small, [&](std::uint64_t, const rockfield::NearRock& r) {
        ++s; EXPECT_TRUE(r.rock >= 1 && r.rock <= 3); });
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock&) { ++l; });
    EXPECT_EQ(f.stats().small, s);
    EXPECT_EQ(f.stats().large, l);
    EXPECT_GT(s, 0); EXPECT_GT(l, 0);
}

namespace {
// A dial set whose span (billboard + margin) far exceeds 16 cells, per class.
rockfield::NearDials wide_dials(float billboard_gu, float cell_gu) {
    rockfield::NearDials d;
    for (auto* c : {&d.small, &d.large}) {
        c->cell_gu = cell_gu;
        c->billboard_gu = billboard_gu;
        c->mesh_gu = billboard_gu;
        c->density = 1.0e-9f;   // generation cost is not what is measured
    }
    return d;
}
}

TEST(NearStream, CellSpanIsCappedAt33PerAxis) {   // Task 4 review: cell-count cap
    rockfield::NearField f;
    f.set_dials(wide_dials(40.0f, 1.0f));   // uncapped: ~270k cells per class
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    EXPECT_GT(f.stats().cells, 0);
    EXPECT_LE(f.stats().cells, 2 * 33 * 33 * 33);
}

TEST(NearStream, HugeRangeTinyCellsStreamsPromptly) {
    rockfield::NearField f;
    f.set_dials(wide_dials(1.0e6f, 1.0f));
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    const auto t0 = std::chrono::steady_clock::now();
    f.stream(glm::dvec3(0.0));
    f.stream(glm::dvec3(3.0, 0.0, 0.0));
    const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    EXPECT_LE(f.stats().cells, 2 * 33 * 33 * 33 + 2 * 3 * 34 * 34);   // + the kept margin slabs
    EXPECT_LT(s, 2.0);
}

TEST(FarABound, SphereIsOneWhenTheCellReachesInsideElseZero) {
    const far::DiscSource s = full_sphere();
    EXPECT_EQ(far::a_bound(s, glm::dvec3(0.0), 5.0), 1.0f);
    EXPECT_EQ(far::a_bound(s, glm::dvec3(10003.0, 0, 0), 5.0), 1.0f);
    EXPECT_EQ(far::a_bound(s, glm::dvec3(10100.0, 0, 0), 5.0), 0.0f);
}

TEST(FarABound, DiscBoundsTheTable) {
    far::DiscSource s; s.table = {{0.0f, 0.05f}, {1000.0f, 0.5f}, {2000.0f, 0.05f}};
    s.outer_fade_gu = 0.0f;
    EXPECT_GE(far::a_bound(s, glm::dvec3(1000.0, 0, 0), 50.0), 0.5f);
    EXPECT_EQ(far::a_bound(s, glm::dvec3(5000.0, 0, 0), 50.0), 0.0f);
}

// ---- Per-camera build (Task 5) -------------------------------------------
namespace {
// The catalogue with bounds and impostor view dirs: what build() needs.
rockfield::NearCatalogue build_cat() {
    rockfield::NearCatalogue k = cat();
    k.small_bound_mu = {57.0f, 57.0f, 57.0f};
    k.large_bound_mu = {57.0f, 57.0f};
    k.view_dirs_gltf = {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}};
    return k;
}
bool is_small_rock(int rock) { const auto s = cat().small_rocks; return std::find(s.begin(), s.end(), rock) != s.end(); }
rockfield::NearBuildInput looking_along_y(float fov_deg) {
    rockfield::NearBuildInput in;
    in.proj = glm::perspective(glm::radians(fov_deg), 1.0f, 0.01f, 1e5f);
    in.view = glm::lookAt(glm::vec3(0), glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
    return in;
}
glm::vec3 translation(const minors::InstanceGpu& g) { return {g.row0.w, g.row1.w, g.row2.w}; }
// The rock radius a billboard carries (far::make_impostor pads it by 1.02).
float radius_of(const far::ImpostorGpu& it) { return it.centre_half.w / 1.02f; }
glm::mat3 linear(const minors::InstanceGpu& g) {   // rows -> glm column-major
    return glm::transpose(glm::mat3(glm::vec3(g.row0), glm::vec3(g.row1), glm::vec3(g.row2)));
}
}

TEST(NearTiers, WeightsAtTheBoundaries) {
    rockfield::NearClassDials c;  // small: 20 / 30, fade 4
    // Pinned to the pre-2026-10-03 near_small_mesh_gu default (20) so the
    // literal distances below stay valid regardless of rock_near.h's
    // current default.
    c.mesh_gu = 20.0f; c.billboard_gu = 30.0f;
    auto w = [&](float d) { return rockfield::near_weights(d, c, 4.0f); };
    EXPECT_EQ(w(10).mesh, 1.0f);  EXPECT_EQ(w(10).billboard, 0.0f);
    EXPECT_NEAR(w(18).mesh + w(18).billboard, 1.0f, 1e-6f);   // inside the mesh->billboard fade
    EXPECT_GT(w(18).mesh, 0.0f); EXPECT_GT(w(18).billboard, 0.0f);
    EXPECT_EQ(w(20).mesh, 0.0f);  EXPECT_EQ(w(20).billboard, 1.0f);
    EXPECT_EQ(w(25).billboard, 1.0f);
    EXPECT_NEAR(w(28).billboard, 0.5f, 1e-5f);                // dithering in at the outer edge
    EXPECT_EQ(w(30).mesh + w(30).billboard, 0.0f);
    EXPECT_EQ(w(31).mesh + w(31).billboard, 0.0f);
}

TEST(NearBuild, OneTierPerRockOutsideFades) {
    rockfield::NearField f;
    // Pinned to the pre-2026-10-03 defaults (small mesh_gu 20, large mesh_gu
    // 50 / billboard_gu 60) so the literal 20/50/16/46/30/60 thresholds below
    // stay valid regardless of rock_near.h's current defaults.
    rockfield::NearDials d;
    d.small.mesh_gu = 20.0f; d.small.billboard_gu = 30.0f;
    d.large.mesh_gu = 50.0f; d.large.billboard_gu = 60.0f;
    d.large_far_gu = 0.0f;   // and the far shell off (NearFarLarge covers it)
    f.set_dials(d);
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const rockfield::NearBuildInput in = looking_along_y(90.0f);
    rockfield::NearOutput out;
    f.build(in, out);
    EXPECT_GT(out.mesh_count, 0);
    EXPECT_GT(out.billboard_count, 0);
    int meshes = 0, boards = 0;
    for (const auto& b : out.meshes)
        for (const auto& it : b.items) {
            ++meshes;
            const float d = glm::length(translation(it));
            const float lim = b.family == rockfield::kNearSmallFamily ? 20.0f : 50.0f;
            EXPECT_LE(d, lim + 1e-3f);
            if (d < lim - 4.0f) EXPECT_EQ(it.extra.x, 0.0f);       // solid: byte-identical path
            else EXPECT_GE(it.extra.x, 0.0f);                       // fading out: positive
        }
    for (const auto& b : out.billboards)
        for (const auto& it : b.items) {
            ++boards;
            const float d = glm::length(glm::vec3(it.centre_half));
            const float lo = is_small_rock(b.rock) ? 16.0f : 46.0f;   // mesh_gu - fade
            const float hi = is_small_rock(b.rock) ? 30.0f : 60.0f;   // billboard_gu
            EXPECT_GE(d, lo - 1e-3f);
            EXPECT_LE(d, hi + 1e-3f);
            EXPECT_LE(it.up_dither.w, 0.0f);
            if (d > lo + 4.0f + 1e-3f && d < hi - 4.0f - 1e-3f)
                EXPECT_EQ(it.up_dither.w, 0.0f);                  // weight 1: solid, exactly 0
        }
    for (const auto& b : out.billboards_fading) boards += static_cast<int>(b.items.size());
    EXPECT_EQ(meshes, out.mesh_count);
    EXPECT_EQ(boards, out.billboard_count);   // solid/dithered + translucent
}

// Rock fade (2026-10-03): only the close mesh <-> billboard hand-off keeps
// the screen door. A billboard fading in from nothing at billboard_gu goes
// to billboards_fading, translucent with alpha = its weight (the dither
// coverage, far::impostor_fade_alpha); weight 1 stays solid (dither 0) in
// billboards. Fading bins draw far to near: the class whose band is farther
// first, each bin's items farthest first.
TEST(NearBuild, OuterFadeBillboardsAreTranslucent) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearOutput out;
    f.build(looking_along_y(90.0f), out);
    const auto& dl = f.dials();
    const rockfield::NearBuildInput in90 = looking_along_y(90.0f);
    const float kpx = far::pixels_per_gu(in90.proj, in90.viewport_h);
    // Each class's rule: the large class has the far shell (rock-real Part 1).
    auto weights = [&](int rock, const far::ImpostorGpu& it) {
        const float d = glm::length(glm::vec3(it.centre_half));
        return is_small_rock(rock) ? rockfield::near_weights(d, dl.small, dl.fade_gu)
                                   : rockfield::near_large_weights(d, radius_of(it) * kpx / d, dl);
    };
    auto outer = [&](int rock) { return is_small_rock(rock) ? dl.small.billboard_gu : dl.large_far_gu; };
    auto outer_fade = [&](int rock) { return is_small_rock(rock) ? dl.fade_gu : dl.large_far_fade_gu; };
    int solid = 0, handoff = 0, fading = 0;
    for (const auto& b : out.billboards)
        for (const auto& it : b.items) {
            const auto& cd = is_small_rock(b.rock) ? dl.small : dl.large;
            const float d = glm::length(glm::vec3(it.centre_half));
            const auto w = weights(b.rock, it);
            if (it.up_dither.w == 0.0f) { ++solid; EXPECT_EQ(w.billboard, 1.0f) << d; continue; }
            ++handoff;   // dithered: only while the mesh still draws
            EXPECT_GT(w.mesh, 0.0f) << d;
            EXPECT_LT(d, cd.mesh_gu + 1e-3f);
        }
    float prev_band = 1e30f;
    for (const auto& b : out.billboards_fading) {
        ASSERT_FALSE(b.items.empty());
        EXPECT_LE(outer(b.rock), prev_band) << "the farther band's bins draw first";
        prev_band = outer(b.rock);
        float prev_d = 1e30f;
        for (const auto& it : b.items) {
            ++fading;
            const float d = glm::length(glm::vec3(it.centre_half));
            const auto w = weights(b.rock, it);
            EXPECT_EQ(w.mesh, 0.0f) << d;
            // Fading in from the outer edge, or (large) up from the pixel floor.
            const bool ramping_px = !is_small_rock(b.rock) &&
                radius_of(it) * kpx / d < dl.large_min_px + rockfield::kNearPixelFadeBand;
            if (!ramping_px) EXPECT_GE(d, outer(b.rock) - outer_fade(b.rock) - 1e-3f);
            EXPECT_LT(it.up_dither.w, 0.0f);
            EXPECT_NEAR(far::impostor_fade_alpha(it.up_dither.w), w.billboard, 1e-5f) << d;
            EXPECT_LE(d, prev_d + 1e-4f) << "far to near within a bin";
            prev_d = d;
        }
    }
    EXPECT_GT(solid, 0);
    EXPECT_GT(handoff, 0);
    EXPECT_GT(fading, 0);
    EXPECT_EQ(fading, out.billboard_fading_count);
    EXPECT_EQ(solid + handoff + fading, out.billboard_count);
}

TEST(NearBuild, MeshItemCarriesFullScaleAndLodRule) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearBuildInput in = looking_along_y(90.0f);
    in.lod0_pixel_radius = 24.0f;
    rockfield::NearOutput out;
    f.build(in, out);
    const float k = far::pixels_per_gu(in.proj, in.viewport_h);
    int lod0 = 0, lod1 = 0;
    for (const auto& b : out.meshes) {
        const auto& rocks = b.family == rockfield::kNearSmallFamily ? cat().small_rocks : cat().large_rocks;
        ASSERT_GE(b.slot, 0); ASSERT_LT(b.slot, static_cast<int>(rocks.size()));
        const auto& cd = b.family == rockfield::kNearSmallFamily ? f.dials().small : f.dials().large;
        for (const auto& it : b.items) {
            const float s = glm::length(linear(it)[0]);
            const float r = s * 57.0f;                          // radius = s * bound_mu
            EXPECT_GE(r, cd.r_min - 1e-4f); EXPECT_LE(r, cd.r_max + 1e-4f);
            const float d = glm::length(translation(it));
            EXPECT_EQ(b.lod, r * k / d >= in.lod0_pixel_radius ? 0 : 1);
            (b.lod == 0 ? lod0 : lod1)++;
        }
    }
    EXPECT_GT(lod0 + lod1, 0);
}

TEST(NearBuild, MeshAndBillboardOfOneRockAgree) {   // same R for both tiers
    rockfield::NearField f;
    const auto k = build_cat();
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearBuildInput in = looking_along_y(90.0f);
    in.game_time = 12.5;
    rockfield::NearOutput out;
    f.build(in, out);
    int pairs = 0;
    for (const auto& mb : out.meshes)
        for (const auto& m : mb.items) {
            if (!(m.extra.x > 0.0f)) continue;                   // only rocks in the fade band
            for (const auto& bb : out.billboards)
                for (const auto& b : bb.items) {
                    if (glm::length(glm::vec3(b.centre_half) - translation(m)) > 1e-5f) continue;
                    const glm::mat3 L = linear(m);
                    const float s = glm::length(L[0]);
                    const float r = s * 57.0f;
                    const auto want = far::make_impostor(k.view_dirs_gltf, glm::vec3(0), translation(m),
                                                         L / s, r, b.up_dither.w);
                    EXPECT_NEAR(glm::length(glm::vec3(want.right_view) - glm::vec3(b.right_view)), 0.0f, 1e-4f);
                    EXPECT_NEAR(glm::length(glm::vec3(want.up_dither) - glm::vec3(b.up_dither)), 0.0f, 1e-4f);
                    EXPECT_EQ(want.right_view.w, b.right_view.w);
                    EXPECT_NEAR(want.centre_half.w, b.centre_half.w, 1e-5f);
                    EXPECT_NEAR(m.extra.x + b.up_dither.w, 0.0f, 1e-5f);   // (1 - w_mesh) == w_billboard
                    ++pairs;
                }
        }
    EXPECT_GT(pairs, 0);
}

TEST(NearBuild, NoViewDirsNoBillboards) {
    rockfield::NearField f;
    rockfield::NearCatalogue k = build_cat(); k.view_dirs_gltf.clear();
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearOutput out;
    f.build(looking_along_y(90.0f), out);
    EXPECT_GT(out.mesh_count, 0);
    EXPECT_EQ(out.billboard_count, 0);
    EXPECT_TRUE(out.billboards.empty());
    EXPECT_TRUE(out.billboards_fading.empty());
}

TEST(NearBuild, RenderSpaceIsSystemMinusAnchorMinusOrigin) {
    rockfield::NearField f;
    // Pinned to the pre-2026-10-03 large.mesh_gu default (50) so the <= 50
    // GU bound below stays valid regardless of rock_near.h's current default.
    rockfield::NearDials d; d.large.mesh_gu = 50.0f;
    f.set_dials(d);
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(300.0, 0.0, 0.0));            // rocks streamed around system x = 300
    rockfield::NearBuildInput in = looking_along_y(90.0f);
    in.anchor_sys = glm::dvec3(200.0, 0.0, 0.0);
    in.render_origin = glm::dvec3(100.0, 0.0, 0.0);   // eye at render 0 == system 300
    rockfield::NearOutput out;
    f.build(in, out);
    EXPECT_GT(out.mesh_count, 0);
    for (const auto& b : out.meshes)
        for (const auto& it : b.items) EXPECT_LE(glm::length(translation(it)), 50.0f + 1e-3f);
}

TEST(NearBuild, BuildIsConstAcrossCameras) {   // Review Focus 3
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const auto before = f.stats();
    rockfield::NearBuildInput far_cam;
    far_cam.proj = glm::perspective(glm::radians(10.0f), 1.0f, 0.01f, 1e6f);
    far_cam.view = glm::lookAt(glm::vec3(5000, 0, 0), glm::vec3(5000, 1, 0), glm::vec3(0, 0, 1));
    rockfield::NearOutput out;
    out.mesh_count = 7;                                 // stale output is reset
    const rockfield::NearField& cf = f;
    cf.build(far_cam, out);
    EXPECT_EQ(out.mesh_count + out.billboard_count, 0);    // nothing streamed out there
    EXPECT_TRUE(out.meshes.empty());
    EXPECT_EQ(f.stats().cells, before.cells);
    EXPECT_EQ(f.stats().small, before.small);
}

TEST(NearBuild, InstanceCapHolds) {             // Review Focus 5
    rockfield::NearDials d; d.small.max_instances = 50;
    // Pinned to the pre-2026-10-03 small mesh_gu/billboard_gu defaults (20/30)
    // so "~270 small rocks within 20 GU" below stays valid regardless of
    // rock_near.h's current near_small_mesh_gu.
    d.small.mesh_gu = 20.0f; d.small.billboard_gu = 30.0f;
    rockfield::NearField f; f.set_dials(d);
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const rockfield::NearBuildInput in = looking_along_y(170.0f);
    rockfield::NearOutput out; f.build(in, out);
    int small = 0, large = 0, small_boards = 0;
    for (const auto& b : out.meshes)
        (b.family == rockfield::kNearSmallFamily ? small : large) += static_cast<int>(b.items.size());
    for (const auto* list : {&out.billboards, &out.billboards_fading})
        for (const auto& b : *list) {
            const int n = static_cast<int>(b.items.size());
            if (is_small_rock(b.rock)) { small += n; small_boards += n; } else large += n;
        }
    EXPECT_EQ(small, 50);                       // the cap binds, meshes + billboards together
    EXPECT_GT(large, 0);                        // the other class is untouched
    // Nearest first: ~270 small rocks lie within 20 GU in view, so 50 kept
    // must all be near meshes -- no small billboard (>= 16 GU) survives.
    EXPECT_EQ(small_boards, 0);
}

// ---- Contacts (Task 6) ----------------------------------------------------
namespace {
constexpr double kTick = 1.0 / 60.0;
minors::PlayerBox unit_box_at(const glm::vec3& p) {   // half extents 1 GU, render space
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    pb.world = glm::translate(glm::mat4(1.0f), p);
    return pb;
}
rockfield::NearRock rock_at(const glm::dvec3& p, float radius, int rock = 10) {
    rockfield::NearRock r; r.pos_sys = p; r.radius = radius; r.rock = rock;
    return r;
}
// Pose the player at render `p` and step at game time `t`.
void step_at(rockfield::NearField& f, rockfield::NearStepInput& in, const glm::vec3& p, double t) {
    in.player = unit_box_at(p);
    in.game_time = t;
    f.step(in);
}
}

TEST(NearContact, SweptHitAtDashSpeed) {
    rockfield::NearField f;
    rockfield::NearRock r; r.pos_sys = {0, 500, 0}; r.radius = 2.0f;
    f.debug_add_rock(rockfield::NearClass::Large, 42, r);
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    rockfield::NearStepInput in; in.player = pb;
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 0, 0));
    in.game_time = 1.0; f.step(in);
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 1000, 0));   // 1,000 GU in one step
    in.game_time = 1.0 + 1.0 / 60.0; f.step(in);
    const auto c = f.drain_large_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(c[0].rock_radius, 2.0f, 1e-6f);
    EXPECT_NEAR(c[0].rel_speed, 60000.0f, 10.0f);
    // The rock centre lies on the sweep: the closest point is the centre
    // itself, so the normal falls back to the reverse of the sweep.
    EXPECT_NEAR(glm::length(c[0].normal - glm::vec3(0, -1, 0)), 0.0f, 1e-4f);
    EXPECT_NEAR(glm::length(c[0].rock_centre_view - glm::dvec3(0, 500, 0)), 0.0, 1e-9);
    EXPECT_EQ(c[0].pen, 0.0f);                       // 500 GU clear at the current pose
    EXPECT_TRUE(f.drain_large_contacts().empty());   // drained
}

TEST(NearContact, ReportsViewSpacePointNormalAndPen) {
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 5, rock_at({150, 3, 0}, 2.0f));   // view (100,3,0), render (0,3,0)
    rockfield::NearStepInput in;
    in.anchor_sys = {50, 0, 0};
    in.render_origin = {100, 0, 0};
    step_at(f, in, {0, -10, 0}, 1.0);
    step_at(f, in, {0, 1.5f, 0}, 1.0 + kTick);   // top face at y = 2.5: 0.5 GU from the centre
    const auto c = f.drain_large_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(glm::length(c[0].point_view - glm::dvec3(100, 2.5, 0)), 0.0, 1e-4);
    EXPECT_NEAR(glm::length(c[0].rock_centre_view - glm::dvec3(100, 3, 0)), 0.0, 1e-9);
    EXPECT_NEAR(glm::length(c[0].normal - glm::vec3(0, -1, 0)), 0.0f, 1e-4f);   // rock -> ship
    EXPECT_NEAR(c[0].pen, 1.5f, 1e-4f);                                         // 2 - 0.5
    EXPECT_NEAR(c[0].rel_speed, 11.5f * 60.0f, 0.1f);
}

TEST(NearContact, APenetratingTouchReportsEveryStepInsideTheCooldown) {   // final review 2
    // The ship keeps pushing into the rock: every step it still penetrates
    // at the current pose (pen > 0) reports, cooldown or not -- Python's
    // receding gate (v_rel >= 0) is the debounce, as collisions._respond_pair.
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 9, rock_at({0, 0, 0}, 2.0f));
    rockfield::NearStepInput in;
    step_at(f, in, {0, -10, 0}, 1.0);                 // clear: face 9 GU from the centre
    int step = 0;
    for (float y : {-2.5f, -2.4f, -2.3f, -2.3f}) {    // face 1.5 .. 1.3 GU away: pen > 0
        step_at(f, in, {0, y, 0}, 1.0 + (++step) * kTick);
        const auto c = f.drain_large_contacts();
        ASSERT_EQ(c.size(), 1u) << "y " << y;
        EXPECT_GT(c[0].pen, 0.0f);
    }
}

TEST(NearContact, CooldownSuppressesRepeatsOnceClear) {
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 9, rock_at({0, 0, 0}, 2.0f));
    rockfield::NearStepInput in;
    step_at(f, in, {0, -10, 0}, 1.0);
    step_at(f, in, {0, -2.5f, 0}, 1.1);               // touch, pen 0.5
    EXPECT_EQ(f.drain_large_contacts().size(), 1u);
    // Backing off: the sweep starts touching but ends clear (pen 0), 0.1 s on.
    step_at(f, in, {0, -10, 0}, 1.2);
    EXPECT_TRUE(f.drain_large_contacts().empty());
    // A dash straight through, ending clear on the far side, still inside
    // the cooldown: suppressed.
    step_at(f, in, {0, 10, 0}, 1.3);
    EXPECT_TRUE(f.drain_large_contacts().empty());
    // The same dash back 0.6 s after the last report: reported, pen 0.
    step_at(f, in, {0, -10, 0}, 1.7);
    const auto c = f.drain_large_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_EQ(c[0].pen, 0.0f);
}

TEST(NearContact, CarriesTheRockKeyAndRearmClearsItsCooldown) {   // Task 8 fix 1
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 9, rock_at({0, 0, 0}, 2.0f));
    rockfield::NearStepInput in;
    step_at(f, in, {0, -10, 0}, 1.0);
    step_at(f, in, {0, -2.5f, 0}, 1.1);               // touch
    const auto c = f.drain_large_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_EQ(c[0].key, 9u);
    // Python rejected it for geometry (a shield-bubble miss): re-arm, and
    // the next touching step reports again inside collide_cooldown_s.
    f.rearm(c[0].key);
    step_at(f, in, {0, -2.5f, 0}, 1.1 + kTick);
    EXPECT_EQ(f.drain_large_contacts().size(), 1u);
    f.rearm(12345);                                   // an unknown key is a no-op
    step_at(f, in, {0, -10, 0}, 1.1 + 2 * kTick);     // backs off clear: no rearm of 9, cooled down
    EXPECT_TRUE(f.drain_large_contacts().empty());
}

TEST(NearContact, OverlapOnStreamInIsGhosted) {          // Review Focus 2
    rockfield::NearField f;
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    rockfield::NearStepInput in; in.player = pb; in.game_time = 1.0;
    rockfield::NearRock r; r.pos_sys = {0, 0.5, 0}; r.radius = 2.0f;   // inside the ship
    f.debug_add_rock(rockfield::NearClass::Large, 7, r);
    f.step(in);
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_EQ(f.stats().ghosted, 1);
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, -20, 0)); in.game_time = 2.0; f.step(in);  // separate
    EXPECT_EQ(f.stats().ghosted, 0);
    in.player->world = glm::mat4(1); in.game_time = 3.0; f.step(in);   // come back: now it hits
    EXPECT_EQ(f.drain_large_contacts().size(), 1u);
}

TEST(NearContact, StreamInWithAPreviousPoseIsGhostedToo) {   // Review Focus 2
    rockfield::NearField f;
    rockfield::NearStepInput in;
    step_at(f, in, {0, 0, 0}, 1.0);                                   // pose known, no rocks
    f.debug_add_rock(rockfield::NearClass::Large, 8, rock_at({0, 0.5, 0}, 2.0f));
    step_at(f, in, {0, 0, 0}, 1.0 + kTick);                           // the rock streams in overlapping
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_EQ(f.stats().ghosted, 1);
    step_at(f, in, {0, 0.1f, 0}, 1.0 + 2 * kTick);                    // still overlapping: still ghosted
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_EQ(f.stats().ghosted, 1);
}

TEST(NearContact, ShieldInflateTouchesEarlier) {
    // Rock radius 1, centre 2.5 GU from a unit-half box's centre: the face
    // gap is 1.5 (> 1) uninflated, 2.5 - sqrt(3) = 0.77 (<= 1) inflated.
    auto touches = [](float inflate) {
        rockfield::NearField f;
        f.debug_add_rock(rockfield::NearClass::Large, 3, rock_at({0, 2.5, 0}, 1.0f));
        rockfield::NearStepInput in;
        in.shield_inflate = inflate;
        step_at(f, in, {0, -20, 0}, 1.0);
        step_at(f, in, {0, 0, 0}, 1.0 + kTick);
        return f.drain_large_contacts().size();
    };
    EXPECT_EQ(touches(0.0f), 0u);
    EXPECT_EQ(touches(std::sqrt(3.0f)), 1u);
}

TEST(NearContact, NoPlayerNoContactsAndSweepResets) {
    // A rock sits on the old -> new segment. With the middle step posed the
    // sweep hits it (control); with the middle step unposed nothing does.
    auto run = [](bool pose_middle) {
        rockfield::NearField f;
        f.debug_add_rock(rockfield::NearClass::Large, 4, rock_at({0, 50, 0}, 2.0f));
        rockfield::NearStepInput in;
        step_at(f, in, {0, 0, 0}, 1.0);
        if (pose_middle) {
            step_at(f, in, {0, 0, 0}, 1.1);
        } else {
            in.player.reset();
            in.game_time = 1.1;
            f.step(in);
            EXPECT_TRUE(f.drain_large_contacts().empty());
        }
        step_at(f, in, {0, 100, 0}, 1.2);
        return f.drain_large_contacts().size();
    };
    EXPECT_EQ(run(true), 1u);
    EXPECT_EQ(run(false), 0u);
}

TEST(NearContact, ResetPlayerForgetsThePose) {
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 4, rock_at({0, 50, 0}, 2.0f));
    rockfield::NearStepInput in;
    step_at(f, in, {0, 0, 0}, 1.0);
    f.reset_player();
    step_at(f, in, {0, 100, 0}, 1.1);
    EXPECT_TRUE(f.drain_large_contacts().empty());
}

TEST(NearContact, TeleportGuardSweepsTheCurrentPoseOnly) {
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 4, rock_at({0, 500, 0}, 2.0f));
    rockfield::NearStepInput in;
    in.minor_dials.teleport_gu = 900.0f;
    step_at(f, in, {0, 0, 0}, 1.0);
    step_at(f, in, {0, 1000, 0}, 1.0 + kTick);   // 1,000 GU > teleport_gu
    EXPECT_TRUE(f.drain_large_contacts().empty());
}

TEST(NearContact, ContactsCappedPerClassPerStep) {
    rockfield::NearField f;
    for (int i = 0; i < 3; ++i)
        f.debug_add_rock(rockfield::NearClass::Large, 100 + i, rock_at({0, 100.0 + 100.0 * i, 0}, 2.0f));
    rockfield::NearStepInput in;
    in.minor_dials.max_shoves_per_frame = 2;
    step_at(f, in, {0, 0, 0}, 1.0);
    step_at(f, in, {0, 1000, 0}, 1.0 + kTick);
    EXPECT_EQ(f.drain_large_contacts().size(), 2u);
}

TEST(NearContact, SmallRocksShoveAndReportMinorContacts) {
    rockfield::NearField f;
    f.set_catalogue(build_cat());                                   // clears: add the rock after
    f.debug_add_rock(rockfield::NearClass::Small, 11, rock_at({0, 50, 0}, 0.2f, /*rock=*/1));
    rockfield::NearStepInput in;
    step_at(f, in, {0, 0, 0}, 1.0);
    step_at(f, in, {0, 100, 0}, 1.0 + kTick);
    const auto c = f.drain_small_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(c[0].radius, 0.2f, 1e-6f);
    EXPECT_NEAR(c[0].rel_speed, 6000.0f, 1.0f);
    EXPECT_TRUE(f.drain_large_contacts().empty());                  // small rocks never hit

    rockfield::NearBuildInput b;
    b.proj = glm::perspective(glm::radians(90.0f), 1.0f, 0.01f, 1e5f);
    b.view = glm::lookAt(glm::vec3(0, 45, 0), glm::vec3(0, 50, 0), glm::vec3(0, 0, 1));
    rockfield::NearOutput out;
    f.build(b, out);
    ASSERT_EQ(out.mesh_count, 1);
    const glm::vec3 drawn = translation(out.meshes[0].items[0]);
    EXPECT_GT(glm::length(drawn - glm::vec3(0, 50, 0)), 0.2f);     // pushed off the ship's path
}

TEST(NearContact, SmallRockShoveUsesTheBareHullBox) {   // final review 4
    // Rock radius 0.2 beside the sweep, 1.5 GU off its axis: the bare box
    // (half 1 + contact margin 0.1) misses it by 0.2, the shield-inflated
    // box (half sqrt(3)) would swallow it. Shields only widen LARGE contacts.
    auto touches = [](float inflate) {
        rockfield::NearField f;
        f.set_catalogue(build_cat());
        f.debug_add_rock(rockfield::NearClass::Small, 11, rock_at({1.5, 50, 0}, 0.2f, /*rock=*/1));
        rockfield::NearStepInput in;
        in.shield_inflate = inflate;
        step_at(f, in, {0, 0, 0}, 1.0);
        step_at(f, in, {0, 100, 0}, 1.0 + kTick);
        return f.drain_small_contacts().size();
    };
    EXPECT_EQ(touches(0.0f), 0u);
    EXPECT_EQ(touches(std::sqrt(3.0f)), 0u);
}

TEST(NearContact, ClearDropsContactsCooldownsGhosts) {   // Review Focus 1
    rockfield::NearField f;
    f.debug_add_rock(rockfield::NearClass::Large, 9, rock_at({0, 0, 0}, 2.0f));
    f.debug_add_rock(rockfield::NearClass::Large, 10, rock_at({0, -9.5, 0}, 2.0f));   // overlaps the first pose
    f.debug_add_rock(rockfield::NearClass::Small, 11, rock_at({0, -5, 0}, 0.2f, 1));
    rockfield::NearStepInput in;
    step_at(f, in, {0, -10, 0}, 1.0);
    EXPECT_EQ(f.stats().ghosted, 1);
    step_at(f, in, {0, -2.5f, 0}, 1.0 + kTick);     // touches rock 9, shoves rock 11
    // (do not drain)
    f.clear();
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_TRUE(f.drain_small_contacts().empty());
    const auto st = f.stats();
    EXPECT_EQ(st.cells, 0); EXPECT_EQ(st.small, 0); EXPECT_EQ(st.large, 0); EXPECT_EQ(st.ghosted, 0);
    int n = 0;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock&) { ++n; });
    EXPECT_EQ(n, 0);
    // Cooldowns went too: the same rock, touched again at once, reports.
    f.debug_add_rock(rockfield::NearClass::Large, 9, rock_at({0, 0, 0}, 2.0f));
    step_at(f, in, {0, -10, 0}, 1.0 + 2 * kTick);  // the pose went with clear(): re-learn it
    step_at(f, in, {0, -2.5f, 0}, 1.0 + 3 * kTick);
    EXPECT_EQ(f.drain_large_contacts().size(), 1u);
}

// ---- Far large billboards (rock-real Part 1, 2026-10-03) -------------------
// Every big-asteroid silhouette is a real rock: the large class's SAME rocks
// stream on past near_large_billboard_gu as billboards out to large_far_gu,
// fading out (translucent) over the last large_far_fade_gu, and a billboard
// whose on-screen radius falls below large_min_px fades out instead of
// drawing. The step's contacts only ever look at cells near the player.
namespace {
// A camera at `eye` looking at `at`, 60 degree vertical FOV, 1080 lines.
rockfield::NearBuildInput camera(const glm::vec3& eye, const glm::vec3& at, float viewport_h = 1080.0f) {
    rockfield::NearBuildInput in;
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1e6f);
    in.view = glm::lookAt(eye, at, glm::vec3(0, 0, 1));
    in.viewport_h = viewport_h;
    return in;
}
// How one rock (render centre `c`) is drawn in `out`.
struct Seen { int meshes = 0, solid = 0, dithered = 0, fading = 0; float alpha = 0.0f; };
Seen seen_at(const rockfield::NearOutput& out, const glm::vec3& c) {
    Seen s;
    auto same = [&](const glm::vec3& p) { return glm::length(p - c) < 1e-3f; };
    for (const auto& b : out.meshes)
        for (const auto& it : b.items)
            if (b.family == rockfield::kNearLargeFamily && same(translation(it))) ++s.meshes;
    for (const auto& b : out.billboards)
        for (const auto& it : b.items)
            if (same(glm::vec3(it.centre_half))) (it.up_dither.w == 0.0f ? s.solid : s.dithered)++;
    for (const auto& b : out.billboards_fading)
        for (const auto& it : b.items)
            if (same(glm::vec3(it.centre_half))) { ++s.fading; s.alpha = far::impostor_fade_alpha(it.up_dither.w); }
    return s;
}
}

TEST(NearFarLarge, DefaultsAreTheBrief) {
    const rockfield::NearDials d;
    // 250, not the brief's 400 target: 400 cost +1.5 ms per frame in the
    // Beol 4 inside bench (NearBench.InsideBeol4, Debug), 250 ~ +0.4.
    EXPECT_EQ(d.large_far_gu, 250.0f);
    EXPECT_EQ(d.large_far_fade_gu, 40.0f);
    EXPECT_EQ(d.large_min_px, 1.5f);
    EXPECT_EQ(d.large.cell_gu, 50.0f);   // 400 GU of 20 GU cells would hit the 33-per-axis cap
    EXPECT_EQ(d.large.billboard_gu, 90.0f);
    EXPECT_EQ(d.large.mesh_gu, 60.0f);
}

TEST(NearFarLarge, WeightsBeyondTheBillboardRange) {
    rockfield::NearDials d;   // mesh 60, billboard 90, far 400 (fade 40), floor 1.5 px
    d.large_far_gu = 400.0f;  // pinned: the literal distances below
    auto w = [&](float dist, float px = 100.0f) { return rockfield::near_large_weights(dist, px, d); };
    EXPECT_EQ(w(30).mesh, 1.0f);   EXPECT_EQ(w(30).billboard, 0.0f);
    EXPECT_NEAR(w(58).mesh + w(58).billboard, 1.0f, 1e-6f);    // the hand-off is unchanged
    EXPECT_EQ(w(75).billboard, 1.0f);
    EXPECT_EQ(w(88).billboard, 1.0f);   // no fade at billboard_gu any more: the far shell continues
    EXPECT_EQ(w(90).billboard, 1.0f);
    EXPECT_EQ(w(250).billboard, 1.0f);  EXPECT_EQ(w(250).mesh, 0.0f);
    EXPECT_EQ(w(360).billboard, 1.0f);
    EXPECT_NEAR(w(380).billboard, 0.5f, 1e-5f);                 // fading out over the last 40 GU
    EXPECT_EQ(w(400).billboard, 0.0f);
    EXPECT_EQ(w(450).billboard, 0.0f);
    // The pixel floor: nothing below 1.5 px, a 1 px ramp in, 1 above.
    EXPECT_EQ(w(250, 1.4f).billboard, 0.0f);
    EXPECT_EQ(w(250, 1.5f).billboard, 0.0f);
    EXPECT_NEAR(w(250, 2.0f).billboard, 0.5f, 1e-5f);
    EXPECT_EQ(w(250, 2.5f).billboard, 1.0f);
    EXPECT_NEAR(w(380, 2.0f).billboard, 0.25f, 1e-5f);          // both fades multiply
    // Far shell off (large_far_gu <= billboard_gu): exactly the old rule.
    rockfield::NearDials off = d; off.large_far_gu = 0.0f;
    for (float dist : {10.0f, 58.0f, 75.0f, 88.0f, 90.0f, 200.0f})
        for (float px : {0.5f, 100.0f}) {
            const auto a = rockfield::near_large_weights(dist, px, off);
            const auto b = rockfield::near_weights(dist, off.large, off.fade_gu);
            EXPECT_EQ(a.mesh, b.mesh) << dist;
            EXPECT_EQ(a.billboard, b.billboard) << dist;
        }
}

TEST(NearFarLarge, StreamsTheSameLargeRocksOutToTheFarRange) {
    rockfield::NearField on, off;
    rockfield::NearDials d_off; d_off.large_far_gu = 0.0f;   // same generator, far shell off
    off.set_dials(d_off);
    for (auto* f : {&on, &off}) { f->set_catalogue(cat()); f->set_sources({full_sphere()}); f->stream(glm::dvec3(0.0)); }
    std::map<std::uint64_t, glm::dvec3> near_on, near_off;
    double farthest = 0.0;
    on.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) {
        const double dist = glm::length(r.pos_sys);
        farthest = std::max(farthest, dist);
        if (dist < 85.0) near_on[k] = r.pos_sys;
    });
    off.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) {
        if (glm::length(r.pos_sys) < 85.0) near_off[k] = r.pos_sys;
    });
    EXPECT_FALSE(near_on.empty());
    EXPECT_EQ(near_on, near_off) << "the far shell must not change which rocks are near";
    // The 33-cells-per-axis cap does not bind: rocks stream all the way out.
    EXPECT_GT(farthest, on.dials().large_far_gu - 5.0);
    EXPECT_GT(on.stats().large, 10 * off.stats().large);
}

TEST(NearFarLarge, FarBillboardsFillTheShellAndFadeOutTranslucent) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const auto in = camera(glm::vec3(0), glm::vec3(0, 1, 0));
    rockfield::NearOutput out;
    f.build(in, out);
    const auto& dl = f.dials();
    const float k = far::pixels_per_gu(in.proj, in.viewport_h);
    int solid_far = 0, fading_far = 0;
    for (const auto& b : out.billboards)
        for (const auto& it : b.items) {
            if (is_small_rock(b.rock)) continue;
            const float d = glm::length(glm::vec3(it.centre_half));
            EXPECT_LT(d, dl.large_far_gu - dl.large_far_fade_gu + 1e-3f);
            if (d > dl.large.billboard_gu + 1.0f) { ++solid_far; EXPECT_EQ(it.up_dither.w, 0.0f) << d; }
        }
    for (const auto& b : out.billboards_fading)
        for (const auto& it : b.items) {
            if (is_small_rock(b.rock)) continue;
            const float d = glm::length(glm::vec3(it.centre_half));
            EXPECT_GE(d, dl.large_far_gu - dl.large_far_fade_gu - 1e-3f) << "only the outer fade is translucent";
            EXPECT_LE(d, dl.large_far_gu + 1e-3f);
            const auto w = rockfield::near_large_weights(d, radius_of(it) * k / d, dl);
            EXPECT_NEAR(far::impostor_fade_alpha(it.up_dither.w), w.billboard, 1e-5f) << d;
            ++fading_far;
        }
    EXPECT_GT(solid_far, 50);
    EXPECT_GT(fading_far, 10);
    for (const auto& b : out.meshes)
        for (const auto& it : b.items) EXPECT_LE(glm::length(translation(it)), dl.large.mesh_gu + 1e-3f);
}

// Fly at a rock first seen as a far billboard: the SAME rock (by key and
// position) becomes a near billboard, then a mesh.
TEST(NearFarLarge, AFarBillboardApproachedIsTheRockThatBecomesAMesh) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    std::uint64_t key = 0; glm::dvec3 pos(0.0); double best = 1e9;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) {
        const double dist = glm::length(r.pos_sys);
        const double off_axis = glm::length(glm::dvec2(r.pos_sys.x, r.pos_sys.z));
        if (dist > 170.0 && dist < 200.0 && r.pos_sys.y > 0.0 && off_axis < best) { best = off_axis; key = k; pos = r.pos_sys; }
    });
    ASSERT_NE(key, 0u);
    ASSERT_GT(f.dials().large_far_gu - f.dials().large_far_fade_gu, 200.0f);
    const glm::dvec3 dir = glm::normalize(pos);
    // Stand-off distances from the rock: far billboard, near billboard, mesh.
    const struct { double d; int meshes, solid, fading; } stages[] = {
        {185.0, 0, 1, 0}, {130.0, 0, 1, 0}, {75.0, 0, 1, 0}, {30.0, 1, 0, 0}};
    glm::dvec3 cur(0.0);   // fly in, 5 GU per stream (flight speed keeps the far shell)
    for (const auto& st : stages) {
        const glm::dvec3 eye = pos - dir * st.d;
        while (glm::length(eye - cur) > 5.0) { cur += glm::normalize(eye - cur) * 5.0; f.stream(cur); }
        cur = eye;
        f.stream(eye);
        int found = 0;
        f.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) {
            if (k == key) { ++found; EXPECT_EQ(r.pos_sys, pos); }
        });
        ASSERT_EQ(found, 1) << "the rock streamed out at " << st.d;
        // Render space == system space here (anchor 0, origin 0).
        const auto in = camera(glm::vec3(eye), glm::vec3(pos));
        rockfield::NearOutput out;
        f.build(in, out);
        const Seen s = seen_at(out, glm::vec3(pos));
        EXPECT_EQ(s.meshes, st.meshes) << st.d;
        EXPECT_EQ(s.solid, st.solid) << st.d;
        EXPECT_EQ(s.fading, st.fading) << st.d;
        EXPECT_EQ(s.dithered, 0) << st.d;
    }
}

TEST(NearFarLarge, OneRepresentationPerRockPerCamera) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    for (const auto& in : {camera(glm::vec3(0), glm::vec3(0, 1, 0)),
                           camera(glm::vec3(0), glm::vec3(1, 0.2f, -0.1f), 200.0f)}) {
        rockfield::NearOutput out;
        f.build(in, out);
        int drawn = 0, handoffs = 0;
        f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock& r) {
            const Seen s = seen_at(out, glm::vec3(r.pos_sys));
            const int n = s.meshes + s.solid + s.dithered + s.fading;
            if (n == 0) return;
            ++drawn;
            if (n == 2) {   // only the mesh <-> billboard hand-off draws twice
                ++handoffs;
                EXPECT_EQ(s.meshes, 1); EXPECT_EQ(s.dithered, 1);
                return;
            }
            EXPECT_EQ(n, 1);
        });
        EXPECT_GT(drawn, 100);
    }
}

TEST(NearFarLarge, PixelFloorSkipsAndFadesTinyFarBillboards) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    // 120 lines at 60 degrees: k ~= 104 px/GU-at-1-GU, so a 1 GU rock is
    // 1.5 px at ~70 GU and most of the far shell is under the floor.
    const auto in = camera(glm::vec3(0), glm::vec3(0, 1, 0), 120.0f);
    const float k = far::pixels_per_gu(in.proj, in.viewport_h);
    const auto& dl = f.dials();
    rockfield::NearOutput out;
    f.build(in, out);
    int ramping = 0;
    auto check = [&](const std::vector<far::ImpostorBin>& bins, bool fading) {
        for (const auto& b : bins)
            for (const auto& it : b.items) {
                if (is_small_rock(b.rock)) continue;
                const float d = glm::length(glm::vec3(it.centre_half));
                const float px = radius_of(it) * k / d;
                // (Over [mesh_gu, mesh_gu + fade_gu] the floor blends in from 1:
                // no pop where the mesh ends.)
                if (!(d > dl.large.mesh_gu + dl.fade_gu)) continue;
                EXPECT_GT(px, dl.large_min_px) << "a billboard below the pixel floor drew, d " << d;
                if (px < dl.large_min_px + 1.0f) {
                    EXPECT_TRUE(fading) << "a ramping billboard must be translucent";
                    ++ramping;
                }
            }
    };
    check(out.billboards, false);
    check(out.billboards_fading, true);
    EXPECT_GT(ramping, 0);
    // The floor bound: in-view rocks beyond 90 GU exist that drew nothing.
    int skipped = 0;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock& r) {
        const glm::vec3 c(r.pos_sys);
        const float d = glm::length(c);
        if (d < 100.0f || d > 200.0f || c.y < 0.9f * d) return;   // well inside the view
        const Seen s = seen_at(out, c);
        if (s.meshes + s.solid + s.dithered + s.fading == 0) ++skipped;
    });
    EXPECT_GT(skipped, 0);
}

TEST(NearFarLarge, TheStepOnlyTestsLargeCellsNearThePlayer) {
    rockfield::NearField f;
    f.set_catalogue(cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    ASSERT_GT(f.stats().cells, 500);
    rockfield::NearStepInput in;
    step_at(f, in, {0, 0, 0}, 1.0);
    step_at(f, in, {0, 1, 0}, 1.0 + kTick);
    EXPECT_GT(f.last_step_large_cells_tested(), 0);
    EXPECT_LE(f.last_step_large_cells_tested(), 8);   // the 50 GU cells around a 1 GU sweep
}

TEST(NearFarLarge, CollisionsNearThePlayerAreUnchanged) {
    // A short flight through dense large rocks, the same 50 GU cells with the
    // far shell on and off: every step drains the same large contacts.
    // (Per step, sorted by key: the cell map's order differs between fields.)
    auto flight = [](float far_gu) {
        rockfield::NearDials d; d.large_far_gu = far_gu; d.large.density = 2.0e-3f;
        rockfield::NearField f; f.set_dials(d);
        f.set_catalogue(cat()); f.set_sources({full_sphere()});
        std::vector<std::vector<std::tuple<std::uint64_t, float, float, float, float>>> steps;
        rockfield::NearStepInput in;
        for (int i = 0; i < 240; ++i) {
            const glm::vec3 p(-120.0f + 1.0f * i, 0.3f * i, 0.0f);
            f.stream(glm::dvec3(p));
            in.player = unit_box_at(p);
            in.player->half_mu = glm::vec3(3.0f);
            in.game_time = 1.0 + i * kTick;
            f.step(in);
            std::vector<std::tuple<std::uint64_t, float, float, float, float>> c;
            for (const auto& x : f.drain_large_contacts())
                c.emplace_back(x.key, x.pen, x.rel_speed, x.normal.x + x.normal.y + x.normal.z,
                               static_cast<float>(x.point_view.x + x.point_view.y + x.point_view.z));
            std::sort(c.begin(), c.end());
            steps.push_back(std::move(c));
        }
        return steps;
    };
    const auto on = flight(rockfield::NearDials{}.large_far_gu), off = flight(0.0f);
    std::size_t n = 0;
    for (const auto& s : on) n += s.size();
    EXPECT_GT(n, 3u) << "the flight must touch rocks";
    EXPECT_EQ(on, off);
}

// ---- Far shell at dash speed (rock-real review, 2026-10-03) ---------------
// The far shell is visual only and flashes past at dash speed: a stream that
// moved more than far_shell_max_step_gu since the last one shrinks the large
// class back to its pre-shell reach (billboard_gu); slower streams regrow it
// by at most far_shell_regrow_gu each, so it never comes back in one hitch.
TEST(NearFarLarge, DashShrinksTheShellAndItRegrowsInBoundedSteps) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    const auto& d = f.dials();
    EXPECT_EQ(d.far_shell_max_step_gu, 25.0f);
    EXPECT_EQ(d.far_shell_regrow_gu, 20.0f);
    f.stream(glm::dvec3(0.0));
    EXPECT_EQ(f.large_reach_gu(), d.large_far_gu);                // a first stream: the whole shell
    // In-system warp, 400 GU/s at 60 Hz: the shell stays.
    for (int i = 1; i <= 30; ++i) f.stream(glm::dvec3(0.0, i * 400.0 / 60.0, 0.0));
    EXPECT_EQ(f.large_reach_gu(), d.large_far_gu);
    // A dash, 100,000 GU/s at 60 Hz: the pre-shell reach, drawn by the old rule.
    glm::dvec3 c(0.0, 200.0, 0.0);
    for (int i = 0; i < 3; ++i) { c.y += 1666.7; f.stream(c); }
    EXPECT_EQ(f.large_reach_gu(), d.large.billboard_gu);
    double farthest = 0.0;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock& r) {
        farthest = std::max(farthest, glm::length(r.pos_sys - c)); });
    EXPECT_LT(farthest, d.large.billboard_gu + d.stream_margin_gu + 1.7321 * d.large.cell_gu + 1.0);
    rockfield::NearOutput out;
    f.build(camera(glm::vec3(c), glm::vec3(c) + glm::vec3(0, 1, 0)), out);
    for (const auto* list : {&out.billboards, &out.billboards_fading})
        for (const auto& b : *list)
            for (const auto& it : b.items)
                EXPECT_LE(glm::length(glm::vec3(it.centre_half) - glm::vec3(c)), d.large.billboard_gu + 1e-2f);
    // Slow again: regrows in steps of at most 20 GU, back to the whole shell.
    float prev = f.large_reach_gu();
    int streams = 0;
    while (f.large_reach_gu() < d.large_far_gu && streams < 100) {
        c.y += 0.1; f.stream(c); ++streams;
        EXPECT_LE(f.large_reach_gu() - prev, d.far_shell_regrow_gu + 1e-3f);
        EXPECT_GE(f.large_reach_gu(), prev);
        prev = f.large_reach_gu();
    }
    EXPECT_EQ(f.large_reach_gu(), d.large_far_gu);
    EXPECT_GE(streams, 7);   // (250 - 90) / 20 = 8 regrow steps
}

TEST(NearFarLarge, TheDrawnShellNeverPassesTheStreamedReach) {
    // A live dial past the 33-cells-per-axis cap: 2,000 GU of 20 GU cells
    // streams only 320 GU; the drawn shell ends (faded) there too.
    rockfield::NearDials d; d.large_far_gu = 2000.0f; d.large.cell_gu = 20.0f;
    rockfield::NearField f; f.set_dials(d);
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    EXPECT_EQ(f.large_reach_gu(), 320.0f);
    rockfield::NearOutput out;
    f.build(camera(glm::vec3(0), glm::vec3(0, 1, 0)), out);
    int fading = 0;
    for (const auto* list : {&out.billboards, &out.billboards_fading})
        for (const auto& b : *list)
            for (const auto& it : b.items) {
                if (is_small_rock(b.rock)) continue;
                const float dist = glm::length(glm::vec3(it.centre_half));
                EXPECT_LE(dist, 320.0f + 1e-3f);
                if (list == &out.billboards) EXPECT_LT(dist, 320.0f - d.large_far_fade_gu + 1e-3f);
                else if (dist > 290.0f) ++fading;
            }
    EXPECT_GT(fading, 0) << "the clamped edge must fade, not cut";
}

TEST(NearFarLarge, ThePixelFloorDoesNotPopWhereTheMeshEnds) {
    const rockfield::NearDials d;   // mesh 60, fade 4, floor 1.5
    auto w = [&](float dist) { return rockfield::near_large_weights(dist, 0.5f, d); };
    // A rock under the floor: the hand-off is untouched, and the billboard
    // then blends down to 0 over [mesh_gu, mesh_gu + fade_gu] -- continuous.
    EXPECT_NEAR(w(59.999f).mesh + w(59.999f).billboard, 1.0f, 1e-3f);
    EXPECT_EQ(w(60.0f).billboard, 1.0f);
    EXPECT_NEAR(w(62.0f).billboard, 0.5f, 1e-5f);
    EXPECT_EQ(w(64.0f).billboard, 0.0f);
    for (float x = 55.0f; x < 66.0f; x += 0.01f)
        EXPECT_LT(std::fabs(w(x + 0.01f).billboard - w(x).billboard), 0.01f) << x;
}
