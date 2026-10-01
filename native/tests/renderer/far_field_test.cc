// native/tests/renderer/far_field_test.cc
// Far tier spec §2: sources and the deterministic cell generator.
#include <gtest/gtest.h>
#include <renderer/far_field.h>
#include <cmath>

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
