// native/tests/renderer/rock_near_test.cc
// Rock fields (docs/superpowers/specs/2026-10-02-rock-fields-design.md):
// the near band's deterministic cells and their streaming.
#include <gtest/gtest.h>
#include <renderer/rock_near.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <set>
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
glm::mat3 linear(const minors::InstanceGpu& g) {   // rows -> glm column-major
    return glm::transpose(glm::mat3(glm::vec3(g.row0), glm::vec3(g.row1), glm::vec3(g.row2)));
}
}

TEST(NearTiers, WeightsAtTheBoundaries) {
    rockfield::NearClassDials c;  // small: 20 / 30, fade 4
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
    EXPECT_EQ(meshes, out.mesh_count);
    EXPECT_EQ(boards, out.billboard_count);
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
}

TEST(NearBuild, RenderSpaceIsSystemMinusAnchorMinusOrigin) {
    rockfield::NearField f;
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
    rockfield::NearField f; f.set_dials(d);
    f.set_catalogue(build_cat()); f.set_sources({full_sphere()});
    f.stream(glm::dvec3(0.0));
    const rockfield::NearBuildInput in = looking_along_y(170.0f);
    rockfield::NearOutput out; f.build(in, out);
    int small = 0, large = 0, small_boards = 0;
    for (const auto& b : out.meshes)
        (b.family == rockfield::kNearSmallFamily ? small : large) += static_cast<int>(b.items.size());
    for (const auto& b : out.billboards) {
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
