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
    // Pinned to the pre-2026-10-03 20 GU large cells.
    rockfield::NearDials d; d.large.cell_gu = 20.0f;
    d.small.billboard_gu = 30.0f; d.large.billboard_gu = 90.0f;   // pinned: pre-2026-10-04 ranges
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
    for (int i = 0; i < 20; ++i) b.stream(glm::dvec3(0.0));   // the jump collapsed the billboards: regrow them
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
    k.view_dirs_gltf = renderer::far::oct_view_dirs(8);
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
    EXPECT_EQ(w(19.99f).mesh, 1.0f); EXPECT_EQ(w(19.99f).billboard, 0.0f);   // a hard swap
    EXPECT_EQ(w(20).mesh, 0.0f);  EXPECT_EQ(w(20).billboard, 1.0f);
    EXPECT_EQ(w(25).billboard, 1.0f);
    EXPECT_NEAR(w(28).billboard, 0.5f, 1e-5f);                // fading in at the outer edge
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
            EXPECT_LT(d, lim + 1e-3f);
            EXPECT_EQ(it.extra.x, 0.0f);                            // never dithered
        }
    for (const auto* list : {&out.billboards, &out.billboards_fading})
        for (const auto& b : *list)
            for (const auto& it : b.items) {
                ++boards;
                const float d = glm::length(glm::vec3(it.centre_half));
                const float lo = is_small_rock(b.rock) ? 20.0f : 50.0f;   // mesh_gu: the hard swap
                const float hi = is_small_rock(b.rock) ? 30.0f : 60.0f;   // billboard_gu
                EXPECT_GE(d, lo - 1e-3f);
                EXPECT_LE(d, hi + 1e-3f);
                if (list == &out.billboards) EXPECT_EQ(it.axis_y_dither.w, 0.0f);   // solid
                else EXPECT_LT(it.axis_y_dither.w, 0.0f);                          // translucent
            }
    EXPECT_EQ(meshes, out.mesh_count);
    EXPECT_EQ(boards, out.billboard_count);   // solid + translucent
}

// Rock fade (2026-10-03): a billboard at full weight is solid (dither 0) in
// billboards; one fading in from nothing -- at billboard_gu, or up from its
// class's pixel floor -- goes to billboards_fading, translucent with alpha =
// its weight (far::impostor_fade_alpha). Fading bins draw far to near: the
// class whose band is farther first, each bin's items farthest first.
TEST(NearBuild, OuterFadeBillboardsAreTranslucent) {
    rockfield::NearField f;
    { rockfield::NearDials pd; pd.small_min_px = 0.0f; pd.large_min_px = 1.5f; f.set_dials(pd); }   // pinned: no small floor, a large one
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearOutput out;
    f.build(looking_along_y(90.0f), out);
    const auto& dl = f.dials();
    const rockfield::NearBuildInput in90 = looking_along_y(90.0f);
    const float kpx = far::pixels_per_gu(in90.proj, in90.viewport_h);
    auto cls = [&](int rock) -> const rockfield::NearClassDials& {
        return is_small_rock(rock) ? dl.small : dl.large;
    };
    auto floor_px = [&](int rock) { return is_small_rock(rock) ? dl.small_min_px : dl.large_min_px; };
    auto weights = [&](int rock, const far::ImpostorGpu& it) {
        const float d = glm::length(glm::vec3(it.centre_half));
        return rockfield::near_weights(d, radius_of(it) * kpx / d, cls(rock), dl.fade_gu, floor_px(rock));
    };
    int solid = 0, fading = 0;
    for (const auto& b : out.billboards)
        for (const auto& it : b.items) {
            const float d = glm::length(glm::vec3(it.centre_half));
            ++solid;
            EXPECT_EQ(it.axis_y_dither.w, 0.0f) << d;
            EXPECT_EQ(weights(b.rock, it).billboard, 1.0f) << d;
            EXPECT_GE(d, cls(b.rock).mesh_gu - 1e-3f) << "the swap is hard";
        }
    float prev_band = 1e30f;
    for (const auto& b : out.billboards_fading) {
        ASSERT_FALSE(b.items.empty());
        const float band = cls(b.rock).billboard_gu;
        EXPECT_LE(band, prev_band) << "the farther band's bins draw first";
        prev_band = band;
        float prev_d = 1e30f;
        for (const auto& it : b.items) {
            ++fading;
            const float d = glm::length(glm::vec3(it.centre_half));
            const auto w = weights(b.rock, it);
            EXPECT_EQ(w.mesh, 0.0f) << d;
            // Fading in from the outer edge, or up from the pixel floor.
            const bool ramping_px = radius_of(it) * kpx / d < floor_px(b.rock) + rockfield::kNearPixelFadeBand;
            if (!ramping_px) EXPECT_GE(d, band - dl.fade_gu - 1e-3f);
            EXPECT_LT(it.axis_y_dither.w, 0.0f);
            EXPECT_NEAR(far::impostor_fade_alpha(it.axis_y_dither.w), w.billboard, 1e-5f) << d;
            EXPECT_LE(d, prev_d + 1e-4f) << "far to near within a bin";
            prev_d = d;
        }
    }
    EXPECT_GT(solid, 0);
    EXPECT_GT(fading, 0);
    EXPECT_EQ(fading, out.billboard_fading_count);
    EXPECT_EQ(solid + fading, out.billboard_count);
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

// The hard swap draws one tier per rock, so pull the mesh range in (a
// non-generator dial: the same rocks) and compare each rock's mesh with its
// billboard at the same game time: the same rotation for both tiers.
TEST(NearBuild, MeshAndBillboardOfOneRockAgree) {   // same R for both tiers
    rockfield::NearField f;
    const auto k = build_cat();
    f.set_catalogue(k); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    rockfield::NearBuildInput in = looking_along_y(90.0f);
    in.game_time = 12.5;
    rockfield::NearOutput meshes, boards;
    f.build(in, meshes);
    rockfield::NearDials pulled = f.dials();
    pulled.small.mesh_gu = 2.0f; pulled.large.mesh_gu = 2.0f;
    f.set_dials(pulled);
    f.build(in, boards);
    int pairs = 0;
    for (const auto& mb : meshes.meshes)
        for (const auto& m : mb.items) {
            if (glm::length(translation(m)) < 3.0f) continue;   // still a mesh after the pull
            for (const auto* list : {&boards.billboards, &boards.billboards_fading})
                for (const auto& bb : *list)
                    for (const auto& b : bb.items) {
                        if (glm::length(glm::vec3(b.centre_half) - translation(m)) > 1e-5f) continue;
                        const glm::mat3 L = linear(m);
                        const float s = glm::length(L[0]);
                        const float r = s * 57.0f;
                        const auto want = far::make_impostor(k.view_dirs_gltf, glm::vec3(0), translation(m),
                                                             L / s, r, b.axis_y_dither.w);
                        EXPECT_NEAR(glm::length(glm::vec3(want.axis_x_grid) - glm::vec3(b.axis_x_grid)), 0.0f, 1e-4f);
                        EXPECT_NEAR(glm::length(glm::vec3(want.axis_y_dither) - glm::vec3(b.axis_y_dither)), 0.0f, 1e-4f);
                        EXPECT_EQ(want.axis_x_grid.w, b.axis_x_grid.w);
                        EXPECT_NEAR(want.centre_half.w, b.centre_half.w, 1e-5f);
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

// ---- Large billboards and the pixel floors (rock-real Part 1, 2026-10-03) ---
// Every big-asteroid silhouette is a real rock: the large class's billboards
// reach far (405 GU), and a billboard whose on-screen radius falls below its
// class's pixel floor fades out instead of drawing. The step's contacts only
// ever look at cells near the player.
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
            if (same(glm::vec3(it.centre_half))) (it.axis_y_dither.w == 0.0f ? s.solid : s.dithered)++;
    for (const auto& b : out.billboards_fading)
        for (const auto& it : b.items)
            if (same(glm::vec3(it.centre_half))) { ++s.fading; s.alpha = far::impostor_fade_alpha(it.axis_y_dither.w); }
    return s;
}
}

TEST(NearLarge, DefaultsAreTheBrief) {
    const rockfield::NearDials d;
    EXPECT_EQ(d.large_min_px, 0.0f);   // off: the speck hand-off has no floor (review I1)
    EXPECT_EQ(d.small_min_px, 2.5f);
    EXPECT_EQ(d.large.cell_gu, 50.0f);   // 400 GU of 20 GU cells would hit the 33-per-axis cap
    EXPECT_EQ(d.large.billboard_gu, 405.0f);   // 3x, then +50% (Mark, live 2026-10-04)
    EXPECT_EQ(d.large.mesh_gu, 60.0f);
}

TEST(NearLarge, PixelFloorWeights) {
    rockfield::NearClassDials c;   // mesh 60, billboard 400, fade 40 (pinned: the literals below)
    c.mesh_gu = 60.0f; c.billboard_gu = 400.0f;
    auto w = [&](float dist, float px = 100.0f) { return rockfield::near_weights(dist, px, c, 40.0f, 1.5f); };
    EXPECT_EQ(w(30).mesh, 1.0f);   EXPECT_EQ(w(30).billboard, 0.0f);
    EXPECT_EQ(w(250).billboard, 1.0f);  EXPECT_EQ(w(250).mesh, 0.0f);
    EXPECT_NEAR(w(380).billboard, 0.5f, 1e-5f);                 // fading out over the last 40 GU
    EXPECT_EQ(w(400).billboard, 0.0f);
    // The pixel floor: nothing below 1.5 px, a 1 px ramp in, 1 above.
    EXPECT_EQ(w(250, 1.4f).billboard, 0.0f);
    EXPECT_EQ(w(250, 1.5f).billboard, 0.0f);
    EXPECT_NEAR(w(250, 2.0f).billboard, 0.5f, 1e-5f);
    EXPECT_EQ(w(250, 2.5f).billboard, 1.0f);
    EXPECT_NEAR(w(380, 2.0f).billboard, 0.25f, 1e-5f);          // both fades multiply
    // A floor of 0 is off: exactly the plain rule.
    for (float dist : {10.0f, 58.0f, 75.0f, 200.0f, 390.0f})
        for (float px : {0.5f, 100.0f}) {
            const auto a = rockfield::near_weights(dist, px, c, 40.0f, 0.0f);
            const auto b = rockfield::near_weights(dist, c, 40.0f);
            EXPECT_EQ(a.mesh, b.mesh) << dist;
            EXPECT_EQ(a.billboard, b.billboard) << dist;
        }
}

TEST(NearLarge, AFarBillboardApproachedIsTheRockThatBecomesAMesh) {
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
    ASSERT_GT(f.dials().large.billboard_gu - f.dials().fade_gu, 200.0f);
    const glm::dvec3 dir = glm::normalize(pos);
    // Stand-off distances from the rock: far billboard, near billboard, mesh.
    const struct { double d; int meshes, solid, fading; } stages[] = {
        {185.0, 0, 1, 0}, {130.0, 0, 1, 0}, {75.0, 0, 1, 0}, {30.0, 1, 0, 0}};
    glm::dvec3 cur(0.0);   // fly in, 5 GU per stream (below the dash collapse step)
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

TEST(NearLarge, OneRepresentationPerRockPerCamera) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    for (const auto& in : {camera(glm::vec3(0), glm::vec3(0, 1, 0)),
                           camera(glm::vec3(0), glm::vec3(1, 0.2f, -0.1f), 200.0f)}) {
        rockfield::NearOutput out;
        f.build(in, out);
        int drawn = 0;
        f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock& r) {
            const Seen s = seen_at(out, glm::vec3(r.pos_sys));
            const int n = s.meshes + s.solid + s.dithered + s.fading;
            if (n == 0) return;
            ++drawn;
            EXPECT_EQ(n, 1);   // the hard swap: never both tiers
            EXPECT_EQ(s.dithered, 0);
        });
        EXPECT_GT(drawn, 100);
    }
}

TEST(NearLarge, PixelFloorSkipsAndFadesTinyFarBillboards) {
    rockfield::NearField f;
    { rockfield::NearDials pd; pd.large_min_px = 1.5f; f.set_dials(pd); }   // pinned: a non-zero floor
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    // 120 lines at 60 degrees: k ~= 104 px/GU-at-1-GU, so a 1 GU rock is
    // 1.5 px at ~70 GU and most far billboards are under the floor.
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

TEST(NearLarge, TheStepOnlyTestsLargeCellsNearThePlayer) {
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

// ---- Dash collapse (Mark, 2026-10-04) --------------------------------------
// A stream whose centre moved more than dash_collapse_step_gu since the last
// one collapses both classes' billboard reach to the mesh range; slower
// streams regrow it.
TEST(NearLarge, DashCollapsesBillboardsToTheMeshRangeAndRegrows) {
    rockfield::NearField f;
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    const rockfield::NearDials d = f.dials();
    ASSERT_GT(d.dash_collapse_step_gu, 0.0f);
    f.stream(glm::dvec3(0.0));
    EXPECT_EQ(f.large_reach_gu(), d.large.billboard_gu);   // a first stream: the full reach
    glm::dvec3 c(0.0);
    for (int i = 0; i < 3; ++i) { c.y += 2.0 * d.dash_collapse_step_gu; f.stream(c); }
    EXPECT_EQ(f.large_reach_gu(), d.large.mesh_gu);
    EXPECT_EQ(f.effective_dials().small.billboard_gu, d.small.mesh_gu);
    double farthest = 0.0;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t, const rockfield::NearRock& r) {
        farthest = std::max(farthest, glm::length(r.pos_sys - c)); });
    EXPECT_LT(farthest, d.large.mesh_gu + d.stream_margin_gu + 1.7321 * d.large.cell_gu + 1.0);
    // Slow again: back to the full reach, never past it.
    float prev = f.large_reach_gu();
    int streams = 0;
    while (f.large_reach_gu() < d.large.billboard_gu && streams < 100) {
        c.y += 0.1; f.stream(c); ++streams;
        EXPECT_GE(f.large_reach_gu(), prev);
        prev = f.large_reach_gu();
    }
    EXPECT_EQ(f.large_reach_gu(), d.large.billboard_gu);
    EXPECT_GT(streams, 1);   // regrown over several streams, not in one hitch
}

TEST(NearLarge, ThePixelFloorDoesNotPopWhereTheMeshEnds) {
    rockfield::NearDials d;   // mesh 60, fade 4
    d.large_min_px = 1.5f;    // pinned: a non-zero floor
    auto w = [&](float dist) {
        return rockfield::near_weights(dist, 0.5f, d.large, d.fade_gu, d.large_min_px);
    };
    // A rock under the floor: the swap is untouched, and the billboard then
    // blends down to 0 over [mesh_gu, mesh_gu + fade_gu] -- continuous.
    EXPECT_EQ(w(59.999f).mesh, 1.0f);
    EXPECT_EQ(w(60.0f).billboard, 1.0f);
    EXPECT_NEAR(w(62.0f).billboard, 0.5f, 1e-5f);
    EXPECT_EQ(w(64.0f).billboard, 0.0f);
    for (float x = 55.0f; x < 66.0f; x += 0.01f)
        EXPECT_LT(std::fabs(w(x + 0.01f).mesh + w(x + 0.01f).billboard - w(x).mesh - w(x).billboard),
                  0.01f) << x;
}

// ---- Near band CPU at the 3x ranges (rock-perf2, 2026-10-04) ----------------
// What build/stream/step produce is pinned by RockPerfEquivalence; these pin
// that the work stays local.
#include "rock_scenario.h"
namespace {
struct Beol4Frame {
    rockfield::NearField f;
    rockfield::NearBuildInput bin;
    rockfield::NearOutput out;
    Beol4Frame() {
        f.set_catalogue(rock_scenario::near_catalogue());
        f.set_sources({rock_scenario::beol4_field()});
        bin.viewport_h = 1080.0f;
        const auto pose = rock_scenario::player_pose(30, 6.0);
        f.stream(pose.pos);
        rock_scenario::chase_camera(pose, bin.view, bin.proj);
        f.build(bin, out);
    }
};
}  // namespace

TEST(NearPerf, BuildVisitsOnlyTheCellsOfBlocksInView) {
    Beol4Frame fr;
    const int cells = fr.f.stats().cells;
    ASSERT_GT(cells, 3000);
    ASSERT_GT(fr.out.billboard_count, 100);
    // Every streamed cell was tested before the blocks (4,851 of 4,868 here);
    // the blocks of a chase camera's 60 x 92 degree view hold under half.
    EXPECT_LT(fr.out.cells_tested, cells / 2) << "of " << cells;
}

TEST(NearPerf, BuildStopsAtTheFirstRockUnderThePixelFloor) {
    Beol4Frame fr;
    const auto st = fr.f.stats();
    // Most small rocks at 30-90 GU are under the 2.5 px floor: within a cell
    // they are visited largest first and the rest skipped at the first one
    // under it (6,823 rocks were tested here before; ~2,900 after).
    EXPECT_LT(fr.out.rocks_tested, (st.small + st.large) / 10)
        << "small=" << st.small << " large=" << st.large;
}

TEST(NearPerf, SlowFlightStreamTestsOnlyCellsNearTheThresholds) {
    // At 6 GU/s a frame moves 0.1 GU: only cells within ~0.1 GU of a
    // generate or keep threshold can change state, a few dozen of the
    // ~5,000 streamed. (A full pass -- a dial change, a jump -- tests more.)
    rockfield::NearField f;
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    f.stream(rock_scenario::player_pose(0, 6.0).pos);
    long tested = 0;
    int frames = 0, worst = 0;
    for (int i = 1; i <= 240; ++i) {
        const std::uint64_t full = f.full_stream_passes();
        f.stream(rock_scenario::player_pose(i, 6.0).pos);
        if (f.full_stream_passes() != full) continue;
        tested += f.last_stream_cells_tested();
        worst = std::max(worst, f.last_stream_cells_tested());
        ++frames;
    }
    ASSERT_GT(frames, 100);
    EXPECT_LT(tested / frames, 150) << "worst " << worst;
}

TEST(NearPerf, NoMarginZigzagStreamsExactlyTheCellsInRange) {
    // stream_margin_gu 0: keep == the generation range, so a zigzag inside
    // one watch window drops cells and must generate them again -- the
    // incremental stream's narrowest case. Every frame's set must equal a
    // fresh field's at the same centre.
    rockfield::NearDials d;
    d.stream_margin_gu = 0.0f;
    d.small.billboard_gu = 40.0f;
    d.large.billboard_gu = 120.0f;
    auto keys = [](const rockfield::NearField& f) {
        std::set<std::uint64_t> k;
        for (auto cls : {rockfield::NearClass::Small, rockfield::NearClass::Large})
            f.for_each(cls, [&](std::uint64_t key, const rockfield::NearRock&) { k.insert(key); });
        return k;
    };
    rockfield::NearField f;
    f.set_dials(d);
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    const glm::dvec3 base(3.0, -640.0, 2.0);
    for (int i = 0; i < 120; ++i) {
        const double t = i * 0.37;
        const glm::dvec3 c = base + glm::dvec3(3.0 * std::sin(t), 0.02 * i + 2.5 * std::cos(1.3 * t),
                                               1.5 * std::sin(2.1 * t));
        f.stream(c);
        rockfield::NearField fresh;
        fresh.set_dials(d);
        fresh.set_catalogue(rock_scenario::near_catalogue());
        fresh.set_sources({rock_scenario::beol4_field()});
        fresh.stream(c);
        ASSERT_EQ(keys(f), keys(fresh)) << "frame " << i;
    }
    EXPECT_LT(f.full_stream_passes(), 40u);   // the zigzag stayed incremental
}

TEST(NearPerf, SlowFlightRecordsTheWatchOnEveryFullPass) {
    // A large class with 50 GU cells has an 8 GU watch width. Flying at
    // 1 GU per stream, the centre leaves the watch after ~8 streams: that
    // full pass must record the next watch (this frame's travel is slow),
    // so the flight costs one full pass per ~9 streams. Deciding "dash
    // speed" from the travel since the LAST FULL PASS (always > 8 GU when a
    // watch of width 8 expires) skipped recording, so every expiry cost a
    // second full pass the next frame.
    rockfield::NearDials d;
    d.small.billboard_gu = 0.0f;   // the large class alone streams
    d.large.cell_gu = 50.0f;
    d.large.billboard_gu = 200.0f;
    d.stream_margin_gu = 10.0f;
    d.dash_collapse_step_gu = 0.0f;
    rockfield::NearField f;
    f.set_dials(d);
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    const glm::dvec3 base(3.0, -640.0, 2.0);
    constexpr int kStreams = 180;
    for (int i = 0; i < kStreams; ++i) f.stream(base + glm::dvec3(0.0, 1.0 * i, 0.0));
    ASSERT_GT(f.stats().large, 0) << "precondition: the flight is inside the field";
    EXPECT_LE(f.full_stream_passes(), static_cast<std::uint64_t>(kStreams / 8 + 2));
    rockfield::NearField fresh;
    fresh.set_dials(d);
    fresh.set_catalogue(rock_scenario::near_catalogue());
    fresh.set_sources({rock_scenario::beol4_field()});
    fresh.stream(base + glm::dvec3(0.0, 1.0 * (kStreams - 1), 0.0));
    // (The flown field also keeps cells within the stream margin behind.)
    std::set<std::uint64_t> flown;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock&) { flown.insert(k); });
    int missing = 0;
    fresh.for_each(rockfield::NearClass::Large,
                   [&](std::uint64_t k, const rockfield::NearRock&) { missing += flown.count(k) ? 0 : 1; });
    EXPECT_EQ(missing, 0);
}

TEST(NearPerf, StepExaminesOnlyCellsNearTheSweep) {
    rockfield::NearField f;
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    rockfield::NearStepInput in;
    for (int i = 0; i < 3; ++i) {
        const auto pose = rock_scenario::player_pose(i, 6.0);
        f.stream(pose.pos);
        in.game_time = 10.0 + i / 60.0;
        in.player = rock_scenario::galaxy_box(glm::vec3(pose.pos), pose.fwd);
        f.step(in);
    }
    ASSERT_GT(f.stats().cells, 3000);
    // The blocks around a 0.1 GU sweep: a few hundred cells at most, not every streamed one.
    EXPECT_LT(f.last_step_cells_examined(), 600) << "of " << f.stats().cells;
}

// Streamed (not pinned) large cells are "seen" lazily (Cell::born): pin both
// halves of the old per-step stamp on real streamed rocks.
namespace {
struct StreamedRock { std::uint64_t key; glm::vec3 pos; float radius; };
StreamedRock large_rock_near_origin(const rockfield::NearDials& d) {
    rockfield::NearField g;
    g.set_dials(d); g.set_catalogue(cat()); g.set_sources({full_sphere()});
    g.stream(glm::dvec3(0.0));
    StreamedRock best{0, glm::vec3(1e9f), 0.0f};
    g.for_each(rockfield::NearClass::Large, [&](std::uint64_t key, const rockfield::NearRock& r) {
        if (glm::length(glm::vec3(r.pos_sys)) < glm::length(best.pos)) best = {key, glm::vec3(r.pos_sys), r.radius};
    });
    return best;
}
rockfield::NearDials dense_large() {
    rockfield::NearDials d;
    d.large.density = 2.0e-3f;
    return d;
}
}  // namespace

TEST(NearPerf, AStreamedLargeRockArrivingOverlappingIsGhosted) {
    const rockfield::NearDials d = dense_large();
    const StreamedRock rock = large_rock_near_origin(d);
    ASSERT_GT(rock.radius, 0.0f);
    rockfield::NearField f;
    f.set_dials(d); f.set_catalogue(cat()); f.set_sources({full_sphere()});
    rockfield::NearStepInput in;
    f.stream(glm::dvec3(0.0, 5000.0, 0.0));          // the rock's cell is not streamed
    step_at(f, in, rock.pos, 1.0);                    // pose known, no rock there yet
    f.stream(glm::dvec3(0.0));                        // it streams in, overlapping the box
    step_at(f, in, rock.pos, 1.0 + kTick);
    EXPECT_TRUE(f.drain_large_contacts().empty());
    EXPECT_GE(f.stats().ghosted, 1);
}

TEST(NearPerf, ALargeCellDroppedAndRestreamedBetweenStepsStaysSeen) {
    const rockfield::NearDials d = dense_large();
    const StreamedRock rock = large_rock_near_origin(d);
    ASSERT_GT(rock.radius, 0.0f);
    rockfield::NearField f;
    f.set_dials(d); f.set_catalogue(cat()); f.set_sources({full_sphere()});
    rockfield::NearStepInput in;
    const glm::vec3 away = rock.pos + glm::vec3(rock.radius + 3.0f, 0.0f, 0.0f);
    f.stream(glm::dvec3(0.0));
    step_at(f, in, away, 1.0);                        // the step sees the rock, clear of it
    step_at(f, in, away, 1.0 + kTick);
    f.stream(glm::dvec3(0.0, 5000.0, 0.0));          // dropped ...
    f.stream(glm::dvec3(0.0));                        // ... and back before the next step
    step_at(f, in, rock.pos, 1.0 + 2 * kTick);        // the ship flies into it: a touch, not a ghost
    EXPECT_FALSE(f.drain_large_contacts().empty());
    EXPECT_EQ(f.stats().ghosted, 0);
}

TEST(NearPerf, RandomFlightStreamsEveryCellInRangeAndNoneBeyondKeep) {
    // The incremental stream against fresh fields, frame by frame, over a
    // flight mixing slow drift, medium steps, dash jumps (the collapse on),
    // out-of-reach hops and non-generator dial changes: every cell within the
    // EFFECTIVE generation range exists, and none beyond its keep range.
    rockfield::NearDials d;
    d.small.billboard_gu = 30.0f; d.small.mesh_gu = 12.0f;
    d.large.billboard_gu = 120.0f; d.large.mesh_gu = 50.0f;
    d.stream_margin_gu = 5.0f;
    d.dash_collapse_step_gu = 25.0f;
    auto keys = [](const rockfield::NearField& f) {
        std::set<std::uint64_t> k;
        for (auto cls : {rockfield::NearClass::Small, rockfield::NearClass::Large})
            f.for_each(cls, [&](std::uint64_t key, const rockfield::NearRock&) { k.insert(key); });
        return k;
    };
    auto fresh_keys = [&](const rockfield::NearDials& fd, const glm::dvec3& c) {
        rockfield::NearField g;
        g.set_dials(fd);
        g.set_catalogue(rock_scenario::near_catalogue());
        g.set_sources({rock_scenario::beol4_field()});
        g.stream(c);
        return keys(g);
    };
    rockfield::NearField f;
    f.set_dials(d);
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    std::uint64_t h = 0x9E3779B97F4A7C15ull;
    auto unit = [&h]() {
        h ^= h << 13; h ^= h >> 7; h ^= h << 17;
        return static_cast<double>(h >> 11) * (1.0 / 9007199254740992.0);
    };
    glm::dvec3 c(5.0, -620.0, 3.0);
    int dashes = 0, slow = 0;
    for (int i = 0; i < 400; ++i) {
        const double u = unit();
        double step = u < 0.75 ? 0.05 + 1.5 * unit() : u < 0.9 ? 4.0 + 10.0 * unit() : 30.0 + 150.0 * unit();
        dashes += step > 25.0 ? 1 : 0;
        slow += step < 2.0 ? 1 : 0;
        glm::dvec3 dir(unit() - 0.5, unit() - 0.5, 0.3 * (unit() - 0.5));
        dir = glm::normalize(dir);
        if (glm::length(c + dir * step) > 700.0) dir = -dir;   // stay inside the field
        c += dir * step;
        if (i == 150) c += glm::dvec3(0.0, 0.0, 5000.0);       // out of every source's reach
        if (i == 151) c -= glm::dvec3(0.0, 0.0, 5000.0);       // ... and back
        if (i == 220) {
            rockfield::NearDials d2 = f.dials();
            d2.large.billboard_gu = 140.0f; d2.stream_margin_gu = 8.0f;
            f.set_dials(d2);
        }
        f.stream(c);
        const std::set<std::uint64_t> have = keys(f);
        rockfield::NearDials need = f.effective_dials();
        need.dash_collapse_step_gu = 0.0f;
        for (const std::uint64_t k : fresh_keys(need, c))
            ASSERT_TRUE(have.count(k)) << "frame " << i << ": a cell in range was not streamed";
        rockfield::NearDials keep = need;   // generate out to the keep range
        for (auto* cd : {&keep.small, &keep.large}) cd->billboard_gu += keep.stream_margin_gu;
        keep.stream_margin_gu = 0.0f;
        const std::set<std::uint64_t> allowed = fresh_keys(keep, c);
        for (const std::uint64_t k : have)
            ASSERT_TRUE(allowed.count(k)) << "frame " << i << ": a cell beyond keep was kept";
    }
    EXPECT_GT(dashes, 10);
    EXPECT_GT(slow, 100);
}

TEST(NearRamp, LargeRampRule) {
    using rockfield::large_ramp;
    EXPECT_EQ(large_ramp(0.0f, 0.5f, 1.0f), 0.0f);
    EXPECT_EQ(large_ramp(0.5f, 0.5f, 1.0f), 0.0f);
    EXPECT_NEAR(large_ramp(0.75f, 0.5f, 1.0f), 0.5f, 1e-6f);
    EXPECT_EQ(large_ramp(1.0f, 0.5f, 1.0f), 1.0f);
    EXPECT_EQ(large_ramp(2.0f, 0.5f, 1.0f), 1.0f);
    EXPECT_EQ(large_ramp(0.5f, 0.5f, 0.5f), 0.0f);   // hi <= lo: a step at lo
    EXPECT_EQ(large_ramp(0.51f, 0.5f, 0.5f), 1.0f);
}

namespace {
far::DiscSource flat_belt(float a) {   // a constant `a` across a huge flat disc, no noise
    far::DiscSource s; s.id = 7; s.seed = 5; s.table = {{0.0f, a}, {1e7f, a}};
    s.scale_height_min_gu = 1e7f;
    return s;
}
double mean_count(const far::DiscSource& s, rockfield::NearClass cls, const rockfield::NearDials& d, int cells) {
    double n = 0;
    for (int i = 0; i < cells; ++i) n += rockfield::generate_near_cell(s, cls, {i, 2, 0}, d, cat()).size();
    return n / cells;
}
}

TEST(NearRamp, NoLargeRocksAtHalfDensity) {     // Vesuvi's 0.5 band: small rocks only
    rockfield::NearDials d;
    EXPECT_EQ(mean_count(flat_belt(0.5f), rockfield::NearClass::Large, d, 400), 0.0);
    EXPECT_GT(mean_count(flat_belt(0.5f), rockfield::NearClass::Small, d, 400), 0.0);
}

TEST(NearRamp, LargeDensityFollowsTheRamp) {
    rockfield::NearDials d;
    d.large.density = 1.0f / 2000.0f;   // ~62 candidates per 50 GU cell: a stable mean
    const double full = mean_count(flat_belt(1.0f), rockfield::NearClass::Large, d, 300);
    const double three_q = mean_count(flat_belt(0.75f), rockfield::NearClass::Large, d, 300);
    ASSERT_GT(full, 20.0);
    // density x a x ramp(a): 0.75 x 0.5 = 0.375 of full
    EXPECT_NEAR(three_q / full, 0.375, 0.05);
}

TEST(NearRamp, FullDensityUnchanged) {          // tile-field interiors (a = 1) keep every rock
    rockfield::NearDials on, off;
    off.large_ramp_lo = -1.0f; off.large_ramp_hi = 0.0f;   // ramp == 1 for every a >= 0
    for (int i = 0; i < 50; ++i) {
        const auto a = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, on, cat());
        const auto b = rockfield::generate_near_cell(full_sphere(), rockfield::NearClass::Large, {i, 1, 1}, off, cat());
        ASSERT_EQ(a.size(), b.size());
        for (size_t k = 0; k < a.size(); ++k) EXPECT_EQ(a[k].pos_sys, b[k].pos_sys);
    }
}

TEST(NearRamp, RampDialChangeClearsCells) {
    rockfield::NearField f;
    f.set_catalogue(cat());
    f.set_sources({full_sphere()});
    f.stream({0, 0, 0});
    ASSERT_GT(f.stats().cells, 0);
    rockfield::NearDials d = f.dials();
    d.large_ramp_lo = 0.25f;
    f.set_dials(d);
    EXPECT_EQ(f.stats().cells, 0);
}

namespace {
rockfield::NearField streamed_field() {
    rockfield::NearField f;
    // build_cat() (bound_mu + view_dirs_gltf): ExcludedKeyIsNotDrawnButNeighboursAre
    // needs build() to actually emit meshes/billboards, not just generate rocks.
    f.set_catalogue(build_cat());
    f.set_sources({full_sphere()});
    f.stream({0, 0, 0});
    return f;
}
std::map<std::uint64_t, rockfield::NearRock> streamed_large(const rockfield::NearField& f) {
    std::map<std::uint64_t, rockfield::NearRock> m;
    f.for_each(rockfield::NearClass::Large, [&](std::uint64_t k, const rockfield::NearRock& r) { m[k] = r; });
    return m;
}
}

TEST(NearQuery, MatchesTheStreamedRocksInRange) {
    auto f = streamed_field();
    const auto streamed = streamed_large(f);
    const glm::dvec3 c{12.0, -30.0, 7.0};
    const auto hits = f.query_large(c, 200.0, 0.0f);
    ASSERT_FALSE(hits.empty());
    std::size_t in_range = 0;
    for (const auto& [k, r] : streamed) if (glm::length(r.pos_sys - c) <= 200.0) ++in_range;
    EXPECT_EQ(hits.size(), in_range);
    for (const auto& h : hits) {
        const auto it = streamed.find(h.key);
        ASSERT_NE(it, streamed.end());
        EXPECT_EQ(it->second.pos_sys, h.rock.pos_sys);
        EXPECT_EQ(it->second.radius, h.rock.radius);
        EXPECT_EQ(it->second.rock, h.rock.rock);
        EXPECT_EQ(it->second.phase, h.rock.phase);
    }
    for (std::size_t i = 1; i < hits.size(); ++i)
        EXPECT_LE(glm::length(hits[i - 1].rock.pos_sys - c), glm::length(hits[i].rock.pos_sys - c));
}

TEST(NearQuery, IndependentOfStreaming) {   // works far from anything streamed (NPCs)
    rockfield::NearField a = streamed_field();
    // Same catalogue as streamed_field(): only the streaming differs.
    rockfield::NearField b; b.set_catalogue(build_cat()); b.set_sources({full_sphere()});   // never streamed
    const glm::dvec3 c{3000.0, 0.0, 0.0};
    const auto ha = a.query_large(c, 150.0, 0.0f), hb = b.query_large(c, 150.0, 0.0f);
    ASSERT_FALSE(ha.empty());
    ASSERT_EQ(ha.size(), hb.size());
    for (std::size_t i = 0; i < ha.size(); ++i) {
        EXPECT_EQ(ha[i].key, hb[i].key);
        EXPECT_EQ(ha[i].rock.pos_sys, hb[i].rock.pos_sys);
        EXPECT_EQ(ha[i].rock.radius, hb[i].rock.radius);
    }
}

TEST(NearQuery, MinRadiusFilters) {
    auto f = streamed_field();
    const auto all = f.query_large({0, 0, 0}, 300.0, 0.0f);
    const auto big = f.query_large({0, 0, 0}, 300.0, 4.0f);
    ASSERT_FALSE(big.empty());
    ASSERT_LT(big.size(), all.size());                  // the filter dropped something
    std::set<std::uint64_t> kept;
    for (const auto& h : big) { EXPECT_GE(h.rock.radius, 4.0f); kept.insert(h.key); }
    std::size_t dropped = 0;
    for (const auto& h : all) {
        if (kept.count(h.key)) continue;
        ++dropped;
        EXPECT_LT(h.rock.radius, 4.0f);                 // only small rocks were dropped
    }
    EXPECT_EQ(dropped + big.size(), all.size());        // a subset: nothing new appeared
}

TEST(NearExclude, ExcludedKeyIsNotDrawnButNeighboursAre) {
    auto f = streamed_field();
    const auto hits = f.query_large({0, 0, 0}, 50.0, 0.0f);   // inside mesh range
    ASSERT_FALSE(hits.empty());
    // Aim the camera straight at the chosen hit so it is guaranteed inside
    // the frustum, with a NARROW fov: the large class's full billboard reach
    // (405 GU, a full-density field) generates far more candidates than its
    // max_instances cap, so a wide fov would let a farther rock backfill the
    // excluded one's slot and the totals would not move -- a correct no-op
    // masquerading as a bug. A narrow cone keeps this cell's few neighbours
    // the whole candidate set.
    const glm::vec3 dir = glm::normalize(glm::vec3(hits[0].rock.pos_sys));
    const glm::vec3 up = std::fabs(dir.z) < 0.9f ? glm::vec3(0, 0, 1) : glm::vec3(1, 0, 0);
    rockfield::NearBuildInput in;
    in.view = glm::lookAt(glm::vec3(0, 0, 0), dir, up);
    in.proj = glm::perspective(glm::radians(5.0f), 1.0f, 0.1f, 5000.0f);
    rockfield::NearOutput before; f.build(in, before);
    ASSERT_GT(before.mesh_count + before.billboard_count, 0);
    f.set_excluded({hits[0].key});
    rockfield::NearOutput after; f.build(in, after);
    EXPECT_EQ(after.mesh_count + after.billboard_count, before.mesh_count + before.billboard_count - 1);
    f.stream({1.0, 0.0, 0.0});                                // survives a stream
    rockfield::NearOutput again; f.build(in, again);
    EXPECT_EQ(again.mesh_count + again.billboard_count, after.mesh_count + after.billboard_count);
}

TEST(NearExclude, ExcludedKeyMakesNoContact) {
    // Control: the same explicit rock + sweep, WITHOUT exclusion, reports a
    // contact (copied from NearContact.SweptHitAtDashSpeed's setup/sweep).
    {
        rockfield::NearField f;
        rockfield::NearRock r; r.pos_sys = {0, 500, 0}; r.radius = 2.0f;
        f.debug_add_rock(rockfield::NearClass::Large, 42, r);
        minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
        rockfield::NearStepInput in; in.player = pb;
        in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 0, 0));
        in.game_time = 1.0; f.step(in);
        in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 1000, 0));   // 1,000 GU in one step
        in.game_time = 1.0 + 1.0 / 60.0; f.step(in);
        ASSERT_FALSE(f.drain_large_contacts().empty());
    }
    // Same setup, excluded: no contact.
    rockfield::NearField f;
    rockfield::NearRock r; r.pos_sys = {0, 500, 0}; r.radius = 2.0f;
    f.debug_add_rock(rockfield::NearClass::Large, 42, r);
    f.set_excluded({42});
    minors::PlayerBox pb; pb.half_mu = glm::vec3(1.0f);
    rockfield::NearStepInput in; in.player = pb;
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 0, 0));
    in.game_time = 1.0; f.step(in);
    in.player->world = glm::translate(glm::mat4(1), glm::vec3(0, 1000, 0));
    in.game_time = 1.0 + 1.0 / 60.0; f.step(in);
    EXPECT_TRUE(f.drain_large_contacts().empty());
}

TEST(NearExclude, ClearDropsTheExclusion) {
    auto f = streamed_field();
    f.set_excluded({1, 2, 3});
    f.clear();
    EXPECT_TRUE(f.excluded().empty());
}
