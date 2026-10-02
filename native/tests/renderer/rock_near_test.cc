// native/tests/renderer/rock_near_test.cc
// Rock fields (docs/superpowers/specs/2026-10-02-rock-fields-design.md):
// the near band's deterministic cells and their streaming.
#include <gtest/gtest.h>
#include <renderer/rock_near.h>
#include <algorithm>
#include <cmath>
#include <set>
using namespace renderer;
namespace {
far::DiscSource full_sphere() {          // density 1 everywhere within 10,000 GU, no noise
    far::DiscSource s; s.id = 3; s.seed = 99; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 10000.0f; s.sphere_edge_frac = 0.0f; s.view_space = true;
    return s;
}
rockfield::NearCatalogue cat() { return {{1, 2, 3}, {10, 11}}; }
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
    f.set_catalogue({{4}, {12}});
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
