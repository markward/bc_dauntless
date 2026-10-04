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
    EXPECT_LT(b.instances().size(), 160000u);   // keep_d0 420 (behind the 405 GU billboards)
    EXPECT_LT(b.last_stream_cells_generated(), first_cells / 4);
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
