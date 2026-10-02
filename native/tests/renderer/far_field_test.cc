// native/tests/renderer/far_field_test.cc
// Far tier spec §2: sources and the deterministic cell generator.
#include <gtest/gtest.h>
#include <renderer/far_field.h>
#include <cmath>
#include <cstdio>
#include <algorithm>
#include <optional>
#include <string>
#include <glm/gtc/matrix_transform.hpp>
#include <unordered_map>

namespace far = renderer::far;

namespace {
// A belt like Vesuvi's band: a = 0.5 from 226k to 330k GU, 0.05 elsewhere.
far::DiscSource vesuvi_like() {
    far::DiscSource s;
    s.id = 1; s.frame = "Vesuvi"; s.seed = 7;
    s.table = {{0.0f, 0.05f}, {215000.0f, 0.05f}, {226000.0f, 0.5f},
               {330000.0f, 0.5f}, {340000.0f, 0.05f}};
    far::Population minors;
    minors.kind = 0; minors.density_at_1 = 9.67e-8f; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.rocks = {5, 6, 7}; minors.weights = {1.0f, 1.0f, 1.0f};
    far::Population majors;
    majors.kind = 1; majors.density_at_1 = 1.0f / 1.2e9f; majors.a_lo = 0.5f; majors.a_hi = 1.0f;
    majors.size = {1.0f, 5.0f, 2.5f};
    majors.rocks = {0, 1}; majors.weights = {1.0f, 1.0f};
    s.pops = {minors, majors};
    return s;
}
}  // namespace

TEST(FarField, TableInterpolatesAndFadesPastTheLastRow) {
    const auto s = vesuvi_like();
    EXPECT_FLOAT_EQ(far::table_a(s, 0.0f), 0.05f);
    EXPECT_NEAR(far::table_a(s, 278000.0f), 0.5f, 1e-6f);
    EXPECT_NEAR(far::table_a(s, 335000.0f), 0.275f, 1e-4f);
    EXPECT_NEAR(far::table_a(s, 340000.0f + 10000.0f), 0.025f, 1e-4f);  // half the fade
    EXPECT_EQ(far::table_a(s, 340000.0f + 20000.0f), 0.0f);
    EXPECT_EQ(far::table_a(s, 1.0e7f), 0.0f);
}

TEST(FarField, DensityFallsOffAboveThePlane) {
    const auto s = vesuvi_like();
    const double rho = 278000.0;
    const double H = 0.03 * rho;
    EXPECT_NEAR(far::density_a(s, {rho, 0.0, 0.0}), 0.5f, 1e-6f);
    EXPECT_NEAR(far::density_a(s, {rho, 0.0, H}), 0.5f * std::exp(-0.5f), 1e-4f);
    EXPECT_NEAR(far::density_a(s, {0.0, rho, -2.0 * H}), 0.5f * std::exp(-2.0f), 1e-4f);
}

TEST(FarField, MajorsOnlyAboveHalf) {
    const auto s = vesuvi_like();
    EXPECT_EQ(far::pop_density(s.pops[1], 0.5f), 0.0f);
    EXPECT_NEAR(far::pop_density(s.pops[1], 0.75f), 0.5f / 1.2e9f, 1e-15f);
    EXPECT_NEAR(far::pop_density(s.pops[0], 0.5f), 0.5f * 9.67e-8f, 1e-12f);
}

TEST(FarField, SizeClassesPartitionThePopulation) {
    const auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[0], g);
    ASSERT_EQ(cls.size(), 4u);
    float total = 0.0f;
    for (const auto& c : cls) total += c.share;
    EXPECT_NEAR(total, 1.0f, 1e-5f);
    EXPECT_FLOAT_EQ(cls.front().r_lo, 0.05f);
    EXPECT_FLOAT_EQ(cls.back().r_hi, 0.7f);
    // Cell = (k_ref * r_hi / p_min) / cells_per_range.
    EXPECT_NEAR(cls.back().cell_gu, 1713.0f * 0.7f / 0.25f / 4.0f, 0.5f);
}

TEST(FarField, CellContentsAreAPureFunctionOfTheirKey) {
    const auto s = vesuvi_like();
    const far::GenParams g;
    const glm::i64vec3 ijk{1000, 3, 0};
    const auto a = far::generate_cell(s, 0, 3, ijk, g);
    // Generate other cells in between: no hidden state.
    (void)far::generate_cell(s, 0, 3, {1001, 3, 0}, g);
    (void)far::generate_cell(s, 1, 0, {5, 5, 5}, g);
    const auto b = far::generate_cell(s, 0, 3, ijk, g);
    ASSERT_EQ(a.size(), b.size());
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].pos_sys, b[i].pos_sys);
        EXPECT_EQ(a[i].radius, b[i].radius);
        EXPECT_EQ(a[i].rock, b[i].rock);
    }
}

TEST(FarField, RocksLieInTheirCellAndSizeBin) {
    const auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[0], g);
    const float L = cls[3].cell_gu;
    const glm::i64vec3 ijk{static_cast<long long>(278000.0 / L), 0, 0};
    int n = 0;
    for (int dz = -1; dz <= 0; ++dz)
        for (const auto& r : far::generate_cell(s, 0, 3, {ijk.x, ijk.y, dz}, g)) {
            ++n;
            EXPECT_GE(r.pos_sys.x, ijk.x * L); EXPECT_LT(r.pos_sys.x, (ijk.x + 1) * L);
            EXPECT_GE(r.radius, cls[3].r_lo); EXPECT_LE(r.radius, cls[3].r_hi);
            EXPECT_TRUE(r.rock == 5 || r.rock == 6 || r.rock == 7);
        }
    (void)n;
}

// Mean count over many cells matches n*V*share within 5%.
TEST(FarField, MeanCountMatchesDensity) {
    const auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[0], g);
    const int c = 0;   // smallest class: most rocks per cell
    const double L = cls[c].cell_gu;
    const long long i0 = static_cast<long long>(270000.0 / L);
    long long count = 0, cells = 0;
    for (long long i = i0; i < i0 + 40; ++i)
        for (long long j = 0; j < 40; ++j) {
            count += static_cast<long long>(far::generate_cell(s, 0, c, {i, j, 0}, g).size());
            count += static_cast<long long>(far::generate_cell(s, 0, c, {i, j, -1}, g).size());
            cells += 2;
        }
    // These cells sit within L of the plane where a ~ 0.5 (H ~ 8,300 GU >> L).
    const double expect = 0.5 * 9.67e-8 * cls[c].share * L * L * L * static_cast<double>(cells);
    EXPECT_NEAR(static_cast<double>(count), expect, 0.05 * expect + 3.0 * std::sqrt(expect));
}

TEST(FarField, DensityGradientIsHonoured) {
    // Inside the 0.5 band vs the 0.05 floor: ~10x more rocks per cell.
    const auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[0], g);
    const double L = cls[0].cell_gu;
    auto total = [&](double x) {
        long long n = 0;
        const long long i0 = static_cast<long long>(x / L);
        for (long long i = i0; i < i0 + 30; ++i)
            for (long long j = 0; j < 30; ++j)
                n += static_cast<long long>(far::generate_cell(s, 0, 0, {i, j, 0}, g).size());
        return static_cast<double>(n);
    };
    const double band = total(280000.0), floor = total(100000.0);
    EXPECT_GT(band, 6.0 * floor);
    EXPECT_LT(band, 14.0 * floor);
}

TEST(FarField, ExplicitRegionsAreSkipped) {
    auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[0], g);
    const double L = cls[0].cell_gu;
    const glm::i64vec3 ijk{static_cast<long long>(280000.0 / L), 0, 0};
    const glm::dvec3 c = (glm::dvec3(ijk) + 0.5) * L;
    s.explicit_regions = {glm::dvec4(c, 3.0 * L)};
    for (const auto& r : far::generate_cell(s, 0, 0, ijk, g))
        ADD_FAILURE() << "rock inside an explicit region at " << r.pos_sys.x;
}

TEST(FarField, NoMajorsInAHalfBand) {
    const auto s = vesuvi_like();
    const far::GenParams g;
    const auto cls = far::size_classes(s.pops[1], g);
    const double L = cls[0].cell_gu;
    long long n = 0;
    for (long long i = 0; i < 20; ++i)
        n += static_cast<long long>(
            far::generate_cell(s, 1, 0, {static_cast<long long>(280000.0 / L) + i, 0, 0}, g).size());
    EXPECT_EQ(n, 0);
}

// Far tier spec §1-3: FarField::build — per-camera tiers, cell cache, budget.

namespace {
far::BuildInput camera_at(glm::vec3 eye_render, glm::vec3 target, float h = 1080.0f) {
    far::BuildInput in;
    in.view = glm::lookAt(eye_render, target, glm::vec3(0, 0, 1));
    in.proj = glm::perspective(glm::radians(35.0f), 16.0f / 9.0f, 1.0f, 1.8e6f);
    in.viewport_h = h;
    return in;
}
far::FarField field_with_catalogue() {
    far::FarField f;
    std::vector<far::CatalogueRock> cat(8);
    for (auto& c : cat) c.has_impostor = true;
    cat[7].avg_albedo = glm::vec3(0.1f, 0.2f, 0.3f);
    f.set_catalogue(cat, {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {-1, 0, 0},
                          {0, 1, 0}, {0, -1, 0}, {0.6f, 0.8f, 0}, {-0.6f, -0.8f, 0}});
    return f;
}
}  // namespace

TEST(FarFieldBuild, FlaggedRockFadesThroughTheLadder) {
    far::FarField f = field_with_catalogue();
    f.set_rocks({{42, 7, 57.142857f}});
    glm::mat4 world(1.0f);
    float dist = 0.0f;
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    in.world_of = [&](std::uint64_t key, glm::mat4& w) {
        if (key != 42) return false;
        w = glm::translate(glm::mat4(1.0f), glm::vec3(0, dist, 0))
          * glm::scale(glm::mat4(1.0f), glm::vec3(0.035f));   // r = 2 GU
        return true;
    };
    far::FarOutput out;
    dist = 100.0f;  f.build(in, out);                          // p ~ 34 px: mesh
    ASSERT_EQ(out.fades.size(), 1u);
    EXPECT_EQ(out.fades[0].second, 0.0f);
    EXPECT_TRUE(out.impostors.empty());
    dist = 1000.0f; f.build(in, out);                          // p ~ 3.4 px: impostor
    EXPECT_EQ(out.fades[0].second, 1.0f);
    ASSERT_EQ(out.impostors.size(), 1u);
    EXPECT_EQ(out.impostors[0].rock, 7);
    EXPECT_NEAR(out.impostors[0].items[0].centre_half.w, 2.0f * 1.02f, 1e-3f);
    EXPECT_FLOAT_EQ(out.impostors[0].items[0].up_dither.w, -1.0f);
    dist = 5000.0f; f.build(in, out);                          // p ~ 0.69 px: speck
    EXPECT_TRUE(out.impostors.empty());
    ASSERT_EQ(out.specks.size(), 1u);
    EXPECT_EQ(out.specks[0].albedo, glm::vec3(0.1f, 0.2f, 0.3f));
    EXPECT_FLOAT_EQ(out.specks[0].alpha, 1.0f);
    dist = 20000.0f; f.build(in, out);                         // p ~ 0.17 px: gone
    EXPECT_TRUE(out.specks.empty());
    EXPECT_EQ(out.fades[0].second, 1.0f);
}

TEST(FarFieldBuild, ImpostorViewFacesTheEye) {
    far::FarField f = field_with_catalogue();
    f.set_rocks({{1, 0, 57.142857f}});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    in.world_of = [](std::uint64_t, glm::mat4& w) {
        w = glm::translate(glm::mat4(1.0f), glm::vec3(0, 800, 0))
          * glm::scale(glm::mat4(1.0f), glm::vec3(0.035f));
        return true;
    };
    far::FarOutput out;
    f.build(in, out);
    ASSERT_EQ(out.impostors.size(), 1u);
    const auto& g = out.impostors[0].items[0];
    // The baked view direction (cross(up, right)) must point back at the eye.
    const glm::vec3 view_dir = glm::cross(glm::vec3(g.up_dither), glm::vec3(g.right_view));
    EXPECT_GT(glm::dot(glm::normalize(view_dir), glm::vec3(0, -1, 0)), 0.99f);
}

TEST(FarFieldBuild, ViewBasisMatchesTheBakeRule) {
    const auto b = far::make_view_basis(glm::normalize(glm::vec3(0.3f, 0.2f, 0.9f)));
    EXPECT_NEAR(glm::dot(b.right, b.up), 0.0f, 1e-6f);
    EXPECT_NEAR(glm::dot(glm::cross(b.up, b.right), b.dir), 1.0f, 1e-5f);
    const auto p = far::make_view_basis(glm::vec3(0, 1, 0));   // pole: up_ref = +X
    EXPECT_NEAR(glm::length(p.right), 1.0f, 1e-6f);
}

TEST(FarFieldBuild, GltfToBcIsAProperInvolution) {
    const glm::mat3 M = far::gltf_to_bc();
    EXPECT_NEAR(glm::determinant(M), 1.0f, 1e-6f);
    EXPECT_EQ(M * M, glm::mat3(1.0f));
    EXPECT_EQ(M * glm::vec3(1, 2, 3), glm::vec3(-1, 3, 2));
}

TEST(FarFieldBuild, OnlyTheViewedFrameSourcesGenerate) {
    far::FarField f = field_with_catalogue();
    auto s = vesuvi_like();
    f.set_sources({s});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    far::FarOutput out;
    f.set_frame(std::string("Beol"), {280000.0, 0.0, 0.0});
    f.build(in, out);
    EXPECT_EQ(out.generated, 0);
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    f.build(in, out);
    EXPECT_GT(out.generated, 0);
    EXPECT_FALSE(out.specks.empty());
    f.set_frame(std::nullopt, {0.0, 0.0, 0.0});
    f.build(in, out);
    EXPECT_EQ(out.generated, 0);
}

TEST(FarFieldBuild, BudgetTakesTheNearestCellsFirst) {
    // The whole in-view Vesuvi-like enumeration holds only ~220 rocks, so the
    // budget must sit well below that to bind (200 barely did: the walk reached
    // the same farthest speck either way).
    constexpr int kBudget = 50;
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarDials d;
    d.max_far_rocks = kBudget;
    f.set_dials(d);
    far::FarOutput out;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    EXPECT_GE(out.generated, kBudget);
    EXPECT_LT(out.generated, kBudget + 400);   // stops within one cell's worth
    float maxd = 0.0f;
    for (const auto& sp : out.specks) maxd = std::max(maxd, glm::length(sp.pos));
    d.max_far_rocks = 60000;
    f.set_dials(d);
    far::FarOutput full;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), full);
    ASSERT_GT(full.generated, 2 * kBudget);    // the budget really binds
    EXPECT_LT(out.cells, full.cells);
    float maxfull = 0.0f;
    for (const auto& sp : full.specks) maxfull = std::max(maxfull, glm::length(sp.pos));
    EXPECT_LT(maxd, maxfull);
}

TEST(FarFieldBuild, CameraOutsideTheSlabEnumeratesNothing) {
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 200000.0});   // far above the plane
    far::FarOutput out;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    EXPECT_EQ(out.cells, 0);
}

TEST(FarFieldBuild, ViewscreenHeightShrinksTheRange) {
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarOutput a, b;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}, 1080.0f), a);
    f.build(camera_at({0, 0, 0}, {0, 1, 0}, 360.0f), b);
    EXPECT_LT(b.cells, a.cells);
}

TEST(FarFieldBuild, ClearKeepsTheCatalogue) {
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_rocks({{1, 0, 57.0f}});
    f.clear();
    EXPECT_EQ(f.source_count(), 0u);
    EXPECT_EQ(f.rock_count(), 0u);
    EXPECT_EQ(f.cached_cells(), 0u);
    f.set_rocks({{1, 0, 57.142857f}});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    in.world_of = [](std::uint64_t, glm::mat4& w) {
        w = glm::translate(glm::mat4(1.0f), glm::vec3(0, 800, 0))
          * glm::scale(glm::mat4(1.0f), glm::vec3(0.035f));
        return true;
    };
    far::FarOutput out;
    f.build(in, out);
    EXPECT_EQ(out.impostors.size(), 1u);   // catalogue survived: impostor still available
}

TEST(FarFieldBuild, CellCacheIsCappedAndForgetsOnGeneratorChange) {
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarDials d;
    d.cell_cache_max = 40;
    f.set_dials(d);
    far::FarOutput out;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    ASSERT_GT(out.cells, 40);                    // this frame walked past the cap
    EXPECT_LE(f.cached_cells(), 40u);
    d.cell_cache_max = 32768;
    f.set_dials(d);                              // gen unchanged: cache kept
    EXPECT_GT(f.cached_cells(), 0u);
    d.gen.cells_per_range = 8;
    f.set_dials(d);                              // gen changed: cache emptied
    EXPECT_EQ(f.cached_cells(), 0u);
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    EXPECT_GT(f.cached_cells(), 0u);
    f.set_sources({vesuvi_like()});
    EXPECT_EQ(f.cached_cells(), 0u);
}

TEST(FarFieldBuild, FailedLookupGivesAFadeOfZero) {
    far::FarField f = field_with_catalogue();
    f.set_rocks({{42, 7, 57.142857f}, {43, 7, 57.142857f}});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    far::FarOutput out;
    f.build(in, out);                            // no lookup at all
    ASSERT_EQ(out.fades.size(), 2u);
    EXPECT_EQ(out.fades[0], std::make_pair(std::uint64_t{42}, 0.0f));
    EXPECT_EQ(out.fades[1], std::make_pair(std::uint64_t{43}, 0.0f));
    in.world_of = [](std::uint64_t key, glm::mat4& w) {
        if (key == 42) return false;             // lookup fails
        w = glm::scale(glm::translate(glm::mat4(1.0f), glm::vec3(0, 1000, 0)),
                       glm::vec3(0.0f));        // degenerate scale
        return true;
    };
    f.build(in, out);
    ASSERT_EQ(out.fades.size(), 2u);
    EXPECT_EQ(out.fades[0], std::make_pair(std::uint64_t{42}, 0.0f));
    EXPECT_EQ(out.fades[1], std::make_pair(std::uint64_t{43}, 0.0f));
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_TRUE(out.specks.empty());
}

// A rock whose impostor atlas failed to load is told so (drop_impostor): it
// becomes ExplicitNoImpostor, keeping its whole mesh (fade 0) in the impostor
// band down to speck_hi, with no impostor bin, rather than vanishing.
TEST(FarFieldBuild, DroppedImpostorKeepsTheMeshToSpeckHi) {
    far::FarField f = field_with_catalogue();
    f.set_rocks({{42, 7, 57.142857f}});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    in.world_of = [](std::uint64_t, glm::mat4& w) {
        w = glm::translate(glm::mat4(1.0f), glm::vec3(0, 1000, 0))
          * glm::scale(glm::mat4(1.0f), glm::vec3(0.035f));   // p ~ 3.4 px: impostor band
        return true;
    };
    far::FarOutput out;
    f.build(in, out);
    ASSERT_EQ(out.fades[0].second, 1.0f) << "precondition: an impostor-tier rock";
    ASSERT_EQ(out.impostors.size(), 1u);
    f.drop_impostor(7);
    f.drop_impostor(99);                                      // out of range: ignored
    f.build(in, out);
    ASSERT_EQ(out.fades.size(), 1u);
    EXPECT_EQ(out.fades[0].second, 0.0f);
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_TRUE(out.specks.empty());
}

TEST(FarFieldBuild, FrustumCulledFlaggedRockKeepsItsFade) {
    far::FarField f = field_with_catalogue();
    f.set_rocks({{42, 7, 57.142857f}});
    auto in = camera_at({0, 0, 0}, {0, 1, 0});
    in.world_of = [](std::uint64_t, glm::mat4& w) {
        w = glm::translate(glm::mat4(1.0f), glm::vec3(0, -1000, 0))   // behind the eye
          * glm::scale(glm::mat4(1.0f), glm::vec3(0.035f));            // p ~ 3.4 px: impostor
        return true;
    };
    far::FarOutput out;
    f.build(in, out);
    ASSERT_EQ(out.fades.size(), 1u);
    EXPECT_EQ(out.fades[0].first, 42u);
    EXPECT_EQ(out.fades[0].second, 1.0f);
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_TRUE(out.specks.empty());
}

TEST(FarFieldBuild, TelephotoEnumerationIsBoundedPerAxis) {
    // k = 10 x k_ref two ways. The narrow FOV is the viewscreen zoom; its
    // frustum already rejects most cells, so `cells` alone cannot see the
    // enumeration. The tall target has the same k with a wide frustum, so
    // without the per-axis clamp its walk passes the bound.
    far::FarField f = field_with_catalogue();
    const auto s = vesuvi_like();
    f.set_sources({s});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarDials d;
    EXPECT_EQ(d.max_cells_per_axis, 17);
    const int bound = d.gen.size_classes * static_cast<int>(s.pops.size()) * 17 * 17 * 17;
    auto narrow = camera_at({0, 0, 0}, {0, 1, 0});
    narrow.proj = glm::perspective(glm::radians(3.5f), 16.0f / 9.0f, 1.0f, 1.8e6f);
    auto tall = camera_at({0, 0, 0}, {0, 1, 0}, 10820.0f);
    for (const auto* in : {&narrow, &tall}) {
        ASSERT_GE(far::pixels_per_gu(in->proj, in->viewport_h), 10.0f * d.gen.k_ref);
        far::FarOutput out;
        f.build(*in, out);
        EXPECT_LE(out.cells, bound);
        EXPECT_FALSE(out.specks.empty());
    }
}

// ---- Haze (spec §2 "Haze") -------------------------------------------------

namespace {
far::DiscSource vesuvi_minors_only() {
    auto s = vesuvi_like();
    s.pops.resize(1);   // a = 0.5 has no majors; the derivation uses minors only
    return s;
}
}  // namespace

// Spec §2 (ruling R14): with the default gain (270), looking FORWARD along the
// mid-plane of Vesuvi's band from mid-band (rho 278,000 GU) on a tangent, the
// haze alpha is 0.15 +- 0.03. The eye sees only the forward half of the band
// chord, which is why the default is 270 and not the 143 of a full chord.
TEST(FarHaze, DefaultGainHitsTheStatedTarget) {
    EXPECT_EQ(far::FarDials{}.haze_gain, 270.0f);
    const far::DiscSource s = vesuvi_minors_only();
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 1713.0f, 0.25f, 4.0f, 24, 270.0f,
                                    glm::vec3(1.0f));
    std::printf("[FarHaze] default-gain alpha = %.4f\n", h.alpha);
    EXPECT_NEAR(h.alpha, 0.15f, 0.03f);
}

TEST(FarHaze, NoSourceNoHaze) {
    far::DiscSource s = vesuvi_minors_only();
    s.table.clear();
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 1713.0f, 0.25f, 4.0f, 24, 143.0f,
                                    glm::vec3(1.0f));
    EXPECT_EQ(h.alpha, 0.0f);
    EXPECT_EQ(h.rgb, glm::vec3(0.0f));
}

TEST(FarHaze, StopsAtSceneDepth) {
    const far::DiscSource s = vesuvi_minors_only();
    const auto far_h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                        1.0e6f, 1713.0f, 0.25f, 4.0f, 24, 143.0f,
                                        glm::vec3(1.0f));
    const auto near_h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                         1000.0f, 1713.0f, 0.25f, 4.0f, 24, 143.0f,
                                         glm::vec3(1.0f));
    EXPECT_GT(far_h.alpha, 0.0f);
    EXPECT_GT(near_h.alpha, 0.0f);
    EXPECT_LT(near_h.alpha, 0.01f * far_h.alpha);
}

TEST(FarHaze, ColourIsPremultipliedAlbedoTimesLight) {
    // One population: rgb == alpha * albedo * light exactly (T telescopes).
    const far::DiscSource s = vesuvi_minors_only();
    const glm::vec3 light(2.0f, 1.0f, 0.5f);
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 1713.0f, 0.25f, 4.0f, 24, 143.0f, light);
    const glm::vec3 want = h.alpha * s.pops[0].albedo * light;
    EXPECT_NEAR(h.rgb.r, want.r, 1e-5f);
    EXPECT_NEAR(h.rgb.g, want.g, 1e-5f);
    EXPECT_NEAR(h.rgb.b, want.b, 1e-5f);
}

TEST(FarHaze, OutsideTheSlabSeesNothing) {
    // A ray parallel to the plane, 10 scale heights above it.
    const far::DiscSource s = vesuvi_minors_only();
    const double H = far::scale_height(s, 360000.0f);
    const auto h = far::haze_column(s, {278000.0, 0.0, 10.0 * H}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 1713.0f, 0.25f, 4.0f, 24, 143.0f,
                                    glm::vec3(1.0f));
    EXPECT_EQ(h.alpha, 0.0f);
}

TEST(FarHaze, SpecksAndHazeConserveCrossSection) {
    // For one size population at distance d: cross_section_below(r_cut(d)) +
    // the specks' share (cross-section of r >= r_cut) == mean_cross_section.
    // The specks' share is integrated numerically here, independent of the
    // closed form, for q = 2.5 and the q == 1 / q == 3 log branches.
    for (float q : {1.0f, 2.5f, 3.0f}) {
        const far::PowerLaw pl{0.05f, 0.7f, q};
        double norm = 0.0;
        const int N = 200000;
        const double w = (pl.r_max - pl.r_min) / N;
        for (int i = 0; i < N; ++i) norm += std::pow(pl.r_min + (i + 0.5) * w, -q) * w;
        for (float d : {500.0f, 1000.0f, 2000.0f, 4000.0f, 8000.0f}) {
            const float r_cut = 0.25f * d / 1713.0f;
            double above = 0.0;
            const double lo = std::max<double>(r_cut, pl.r_min);
            if (lo < pl.r_max) {
                const double wa = (pl.r_max - lo) / N;
                for (int i = 0; i < N; ++i) {
                    const double r = lo + (i + 0.5) * wa;
                    above += 3.14159265358979 * r * r * std::pow(r, -q) / norm * wa;
                }
            }
            const float below = far::cross_section_below(pl, r_cut);
            EXPECT_NEAR(below + above, far::mean_cross_section(pl),
                        1e-4 * far::mean_cross_section(pl)) << "q=" << q << " d=" << d;
        }
    }
}
