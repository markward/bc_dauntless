// native/tests/renderer/far_field_test.cc
// Far tier spec §2: sources, field density and the per-camera build (flagged rocks).
#include <gtest/gtest.h>
#include <renderer/far_field.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <algorithm>
#include <optional>
#include <array>
#include <map>
#include <set>
#include <cstdint>
#include <string>
#include <glm/gtc/matrix_transform.hpp>

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

// Far tier spec §1-3: FarField::build — per-camera tiers for flagged rocks.

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
    f.set_catalogue(cat, far::oct_view_dirs(8));
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
    EXPECT_FLOAT_EQ(out.impostors[0].items[0].axis_y_dither.w, -1.0f);
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
    // The blended views surround the eye's direction in the rock's frame:
    // their weighted direction points back at the eye.
    const glm::vec3 ax(g.axis_x_grid), ay(g.axis_y_dither);
    const glm::mat3 Q(ax, ay, glm::cross(ax, ay));   // rock glTF -> render
    EXPECT_EQ(g.axis_x_grid.w, 8.0f);
    glm::vec3 dir(0.0f);
    for (int k = 0; k < 3; ++k) dir += g.weights[k] * (Q * far::oct_view_dir(static_cast<int>(g.views[k]), 8));
    EXPECT_GT(glm::dot(glm::normalize(dir), glm::vec3(0, -1, 0)), 0.97f);
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

TEST(FarFieldBuild, ClearKeepsTheCatalogue) {
    far::FarField f = field_with_catalogue();
    f.set_sources({vesuvi_like()});
    f.set_rocks({{1, 0, 57.0f}});
    f.clear();
    EXPECT_EQ(f.source_count(), 0u);
    EXPECT_EQ(f.rock_count(), 0u);
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

// Rock-fields (2026-10-02): the belt generator is gone. A procedural belt is
// a density source only -- the far tier emits no rocks of its own for it
// (the rock-fields near band, specks and puffs replace it).
TEST(FarField, NoProceduralRocksFromABelt) {
    far::FarField f;
    far::DiscSource belt; belt.id = 1; belt.frame = "Vesuvi";
    belt.table = {{0.0f, 1.0f}, {50000.0f, 1.0f}};
    far::Population p; p.density_at_1 = 1e-3f; p.rocks = {0}; p.weights = {1.0f};
    belt.pops = {p};
    f.set_catalogue({far::CatalogueRock{glm::vec3(0.4f), true}}, {glm::vec3(0, 0, 1)});
    f.set_sources({belt});
    f.set_frame(std::string("Vesuvi"), glm::dvec3(0.0));
    far::BuildInput in;
    in.proj = glm::perspective(glm::radians(30.0f), 1.0f, 0.1f, 1e6f);
    far::FarOutput out;
    f.build(in, out);
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_TRUE(out.specks.empty());
}

// ---- Tile fields: Sphere sources (added 2026-10-02) ------------------------

namespace {
// Beol 4's tile field: 3^3 tiles x 15 asteroids in a 1,000 GU sphere, size
// factor 7 (r_max 0.7), r_min 0.05, exponent 2.5; minors only, a == 1 inside.
far::DiscSource beol4_tile_field() {
    far::DiscSource s;
    s.id = 99; s.frame = ""; s.seed = 3;
    s.shape = far::DiscSource::Shape::Sphere;
    s.procedural = false;
    s.view_space = true;
    s.centre = {797.714355, 977.248474, 1268.854858};
    s.sphere_radius_gu = 1000.0f;
    s.sphere_edge_frac = 0.2f;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = static_cast<float>(27.0 * 15.0 / (4.0 / 3.0 * 3.14159265358979 * 1.0e9));
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.rocks = {5}; minors.weights = {1.0f};
    s.pops = {minors};
    return s;
}
}  // namespace

TEST(FarFieldSphere, DensityIsOneInsideAndRampsToZeroAtTheRadius) {
    const far::DiscSource s = beol4_tile_field();
    const glm::dvec3 c = s.centre, x(1.0, 0.0, 0.0);
    EXPECT_EQ(far::density_a(s, c), 1.0f);
    EXPECT_EQ(far::density_a(s, c + 799.0 * x), 1.0f);
    EXPECT_NEAR(far::density_a(s, c + 900.0 * x), 0.5f, 1e-5f);
    EXPECT_EQ(far::density_a(s, c + 1000.0 * x), 0.0f);
    EXPECT_EQ(far::density_a(s, c + 1500.0 * x), 0.0f);
}

TEST(FarFieldBuild, ANonProceduralSourceStaysActive) {
    far::FarField f = field_with_catalogue();
    auto s = vesuvi_like();
    s.procedural = false;
    f.set_sources({s});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarOutput out;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    EXPECT_TRUE(out.specks.empty());
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_EQ(f.active_sources().size(), 1u);   // still a density source
}

TEST(FarFieldBuild, AViewSpaceSourceIgnoresTheFrameKeyAndRidesTheAnchor) {
    far::FarField f = field_with_catalogue();
    auto tile = beol4_tile_field();
    tile.frame = "Nowhere";
    auto belt = vesuvi_like();   // frame "Vesuvi": still keyed
    f.set_sources({tile, belt});
    f.set_frame(std::nullopt, {0.0, 0.0, 0.0});   // an unmapped set (Multi7)
    ASSERT_EQ(f.active_sources().size(), 1u);
    EXPECT_EQ(f.active_sources()[0].centre, tile.centre);
    f.set_frame(std::string("Beol"), {5000.0, -3000.0, 7.0});
    ASSERT_EQ(f.active_sources().size(), 1u);
    EXPECT_EQ(f.active_sources()[0].id, tile.id);
    EXPECT_EQ(f.active_sources()[0].centre, tile.centre + glm::dvec3(5000.0, -3000.0, 7.0));
    f.set_frame(std::string("Vesuvi"), {1.0, 2.0, 3.0});
    EXPECT_EQ(f.active_sources().size(), 2u);
}

// ---- Field noise (2026-10-02) ---------------------------------------------
// A tile field's density is modulated by 3D value-noise fbm FIXED to the
// field (x relative to the centre), so it reads as a clumpy rock field, not a
// smooth grey ball. m(x) = max(0, 1 + contrast * (2 fbm - 1)); belts never.

namespace {
far::DiscSource noisy_tile_field() {
    far::DiscSource s = beol4_tile_field();
    s.noise_scale_gu = 250.0f;
    s.noise_contrast = 0.8f;
    s.noise_octaves = 3;
    return s;
}
}  // namespace

TEST(FarFieldNoise, FbmIsDeterministicSeededAndInZeroOne) {
    int differs = 0;
    for (int i = 0; i < 200; ++i) {
        const glm::vec3 p(0.37f * i - 11.0f, 1.13f * i + 0.5f, -0.71f * i + 3.0f);
        const float a = far::field_fbm(p, 3, 7u);
        EXPECT_EQ(a, far::field_fbm(p, 3, 7u));
        EXPECT_GE(a, 0.0f);
        EXPECT_LE(a, 1.0f);
        if (std::fabs(a - far::field_fbm(p, 3, 8u)) > 0.05f) ++differs;
    }
    EXPECT_GT(differs, 100);
}

TEST(FarFieldNoise, ValueNoiseHitsTheLatticeValuesAndIsContinuous) {
    // At an integer point the trilinear blend is the corner's hashed value.
    const float v = far::field_value_noise(glm::vec3(3.0f, -2.0f, 5.0f), 11u);
    EXPECT_NEAR(far::field_value_noise(glm::vec3(3.0f + 1e-4f, -2.0f, 5.0f), 11u), v, 1e-3f);
    EXPECT_NEAR(far::field_value_noise(glm::vec3(3.0f - 1e-4f, -2.0f, 5.0f), 11u), v, 1e-3f);
}

TEST(FarFieldNoise, MeanModulationIsOne) {
    const far::DiscSource s = noisy_tile_field();
    std::uint64_t st = 12345;
    auto u01 = [&]() {
        st = st * 6364136223846793005ull + 1442695040888963407ull;
        return static_cast<double>(st >> 11) / 9007199254740992.0;
    };
    double sum = 0.0, lo = 1e9, hi = -1e9;
    const int n = 20000;
    for (int i = 0; i < n; ++i) {
        const glm::dvec3 p = s.centre + glm::dvec3(u01() - 0.5, u01() - 0.5, u01() - 0.5) * 2000.0;
        const double m = far::field_noise_m(s, p);
        sum += m; lo = std::min(lo, m); hi = std::max(hi, m);
    }
    std::printf("[FarFieldNoise] mean m over %d points = %.4f (min %.3f max %.3f)\n", n,
                sum / n, lo, hi);
    EXPECT_NEAR(sum / n, 1.0, 0.05);
    EXPECT_LT(lo, 0.7);   // it IS clumpy
    EXPECT_GT(hi, 1.3);
}

TEST(FarFieldNoise, PatternIsFixedToTheField) {
    far::DiscSource s = noisy_tile_field();
    const glm::dvec3 off(123.0, -45.0, 300.0);
    const float m0 = far::field_noise_m(s, s.centre + off);
    s.centre += glm::dvec3(5000.0, 0.0, -700.0);
    EXPECT_EQ(far::field_noise_m(s, s.centre + off), m0);
}

TEST(FarFieldNoise, OffMeansOne) {
    far::DiscSource s = noisy_tile_field();
    s.noise_contrast = 0.0f;
    EXPECT_EQ(far::field_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
    s = noisy_tile_field(); s.noise_scale_gu = 0.0f;
    EXPECT_EQ(far::field_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
    s = noisy_tile_field(); s.noise_octaves = 0;
    EXPECT_EQ(far::field_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
}

TEST(FarNoise, DiscSourcesNowCarryNoise) {
    far::DiscSource s;                       // a disc
    s.table = {{0.0f, 1.0f}, {50000.0f, 1.0f}};
    s.noise_scale_gu = 1000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3; s.seed = 7;
    bool varied = false;
    for (int i = 0; i < 64; ++i) {
        const float m = far::field_noise_m(s, glm::dvec3(i * 517.0, 300.0, 0.0));
        EXPECT_GE(m, 0.0f);
        EXPECT_LE(m, far::noise_m_bound(s));
        if (std::fabs(m - 1.0f) > 0.05f) varied = true;
    }
    EXPECT_TRUE(varied);
}

TEST(FarNoise, OffIsExactlyOneForBothShapes) {
    far::DiscSource d; d.noise_scale_gu = 0.0f; d.noise_contrast = 0.8f; d.noise_octaves = 3;
    far::DiscSource sph = d; sph.shape = far::DiscSource::Shape::Sphere;
    EXPECT_EQ(far::field_noise_m(d, glm::dvec3(1, 2, 3)), 1.0f);
    EXPECT_EQ(far::field_noise_m(sph, glm::dvec3(1, 2, 3)), 1.0f);
}

TEST(FarNoise, FieldDensityIsAtimesM) {
    far::DiscSource s; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 1000.0f; s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f;
    s.noise_octaves = 3; s.seed = 11;
    const glm::dvec3 x(120.0, -40.0, 33.0);
    EXPECT_FLOAT_EQ(far::field_density(s, x), far::density_a(s, x) * far::field_noise_m(s, x));
}

TEST(FarNoise, ContrastAboveOneIsClampedInTheBound) {
    far::DiscSource s; s.noise_scale_gu = 10.0f; s.noise_contrast = 3.0f; s.noise_octaves = 2;
    EXPECT_FLOAT_EQ(far::noise_m_bound(s), 2.0f);
}

// Golden values recorded 2026-10-02 from the code BEFORE the per-octave seed
// hash refactor (field_hash(seed) inside every lattice() call): the refactor
// must be value-identical.
TEST(FarNoise, OncePerOctaveSeedHashKeepsValues) {
    const float a = far::field_fbm(glm::vec3(0.3f, 1.7f, -2.2f), 3, 12345u);
    const float b = far::field_fbm(glm::vec3(10.1f, -4.0f, 0.5f), 5, 99u);
    const float c = far::field_value_noise(glm::vec3(-7.5f, 3.25f, 8.0f), 4242u);
    EXPECT_EQ(a, 0x1.51d48ap-1f);   // 0.659824669
    EXPECT_EQ(b, 0x1.65a954p-1f);   // 0.698557496
    EXPECT_EQ(c, 0x1.15239ep-1f);   // 0.541287363
}

TEST(FarNoise, ContrastAboveOneIsClampedInM) {
    far::DiscSource s; s.shape = far::DiscSource::Shape::Sphere;
    s.noise_scale_gu = 10.0f; s.noise_contrast = 3.0f; s.noise_octaves = 2; s.seed = 5;
    far::DiscSource one = s; one.noise_contrast = 1.0f;
    for (int i = 0; i < 64; ++i) {
        const glm::dvec3 x(i * 3.7, -i * 1.3, i * 0.9);
        EXPECT_EQ(far::field_noise_m(s, x), far::field_noise_m(one, x));
    }
}

// rock-fields Task 3: the impostor emit, shared with the near band.
TEST(FarImpostor, MakeImpostorDitherAndSize) {
    const auto g = far::make_impostor(far::oct_view_dirs(8), glm::vec3(0, 0, 10), glm::vec3(0),
                                      glm::mat3(1.0f), 2.0f, -0.25f);
    EXPECT_FLOAT_EQ(g.centre_half.w, 2.0f * 1.02f);
    EXPECT_FLOAT_EQ(g.axis_y_dither.w, -0.25f);
}

// rock-blend: the instance carries the rock's glTF axes in render space
// (gltf_to_bc maps (x,y,z) -> (-x,z,y), then R), the grid, and the
// view_blend of the eye's direction in the rock's glTF frame.
TEST(FarImpostor, MakeImpostorCarriesTheRockAxesAndTheBlend) {
    const glm::mat3 R(glm::rotate(glm::mat4(1.0f), 0.7f, glm::normalize(glm::vec3(0.2f, -0.5f, 0.8f))));
    const glm::vec3 c(3.0f, -2.0f, 1.0f), eye(-40.0f, 25.0f, 9.0f);
    const auto g = far::make_impostor(far::oct_view_dirs(8), eye, c, R, 1.5f, 0.0f);
    const glm::mat3 Q = R * far::gltf_to_bc();
    EXPECT_NEAR(glm::length(glm::vec3(g.axis_x_grid) - Q[0]), 0.0f, 1e-6f);
    EXPECT_NEAR(glm::length(glm::vec3(g.axis_y_dither) - Q[1]), 0.0f, 1e-6f);
    EXPECT_EQ(g.axis_x_grid.w, 8.0f);
    EXPECT_EQ(glm::vec3(g.centre_half), c);
    const far::ViewBlend want = far::view_blend(glm::normalize(glm::transpose(Q) * (eye - c)), 8);
    for (int k = 0; k < 3; ++k) {
        EXPECT_EQ(g.views[k], static_cast<float>(want.view[k])) << k;
        EXPECT_NEAR(g.weights[k], want.w[k], 1e-5f) << k;
    }
    EXPECT_EQ(g.views.w, 0.0f);
    EXPECT_EQ(g.weights.w, 0.0f);
}

TEST(FarImpostor, AnEyeOnABakedViewIsThatViewAlone) {
    // Eye on BC +Y == glTF +Z (gltf_to_bc maps (x,y,z) -> (-x,z,y)): oct
    // (0, 0) after the y < 0 fold is not a grid point for an even grid, so
    // use the -y pole (glTF -Y == BC -Z), every grid corner.
    const auto g = far::make_impostor(far::oct_view_dirs(8), glm::vec3(0, 0, -50), glm::vec3(0),
                                      glm::mat3(1.0f), 1.0f, 0.0f);
    EXPECT_EQ(far::oct_view_dir(static_cast<int>(g.views.x), 8), glm::vec3(0, -1, 0));
    EXPECT_FLOAT_EQ(g.weights.x, 1.0f);
    EXPECT_EQ(g.weights.y, 0.0f);
    EXPECT_EQ(g.weights.z, 0.0f);
}

// ---- Octahedral view blend (rock-blend, 2026-10-03) -------------------------

namespace {
// A ViewBlend as weight per DISTINCT direction: the oct layout's mirrored
// border views share a direction (and so a picture), so the blend at a fold
// may name either twin. Keyed by the direction's bits.
using DirWeights = std::map<std::array<float, 3>, float>;
DirWeights by_direction(const far::ViewBlend& b, int grid) {
    DirWeights m;
    for (int k = 0; k < 3; ++k) {
        if (b.w[k] == 0.0f) continue;
        const glm::vec3 d = far::oct_view_dir(b.view[k], grid);
        m[{d.x, d.y, d.z}] += b.w[k];
    }
    return m;
}
float l1(const DirWeights& a, const DirWeights& b) {
    float s = 0.0f;
    for (const auto& [k, v] : a) { auto it = b.find(k); s += std::abs(v - (it == b.end() ? 0.0f : it->second)); }
    for (const auto& [k, v] : b) if (!a.count(k)) s += std::abs(v);
    return s;
}
glm::vec3 rot(const glm::vec3& axis, float angle, const glm::vec3& v) {
    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, axis)) * v;
}
}  // namespace

TEST(FarImpostorBlend, GridIsTheSquareRootOfTheViewCount) {
    EXPECT_EQ(far::impostor_grid_for(64), 8);
    EXPECT_EQ(far::impostor_grid_for(16), 4);
    EXPECT_EQ(far::impostor_grid_for(6), 0);
    EXPECT_EQ(far::impostor_grid_for(1), 0);
    EXPECT_EQ(far::impostor_grid_for(0), 0);
}

// The atlas is read as an N x N octahedral layout, so a view set that is a
// square COUNT but not that layout (an older bake, a reordered or hand-made
// list) would sample the wrong views: it is unusable (grid 0, no impostors),
// exactly as a non-square count is. (2026-10-04 review, deferred minor.)
TEST(FarImpostorBlend, ViewsMustBeTheOctahedralLayoutNotJustASquareCount) {
    EXPECT_EQ(far::make_impostor_views(far::oct_view_dirs(8)).grid, 8);
    EXPECT_EQ(far::make_impostor_views(far::oct_view_dirs(4)).grid, 4);
    // The catalogue's dirs come through JSON as rounded floats: still the layout.
    std::vector<glm::vec3> rounded = far::oct_view_dirs(8);
    for (auto& d : rounded) d = glm::round(d * 1.0e5f) / 1.0e5f;
    EXPECT_EQ(far::make_impostor_views(rounded).grid, 8);
    std::vector<glm::vec3> swapped = far::oct_view_dirs(8);
    std::swap(swapped[9], swapped[10]);                 // two interior views out of order
    EXPECT_EQ(far::make_impostor_views(swapped).grid, 0);
    std::vector<glm::vec3> fib;                         // 16 spread directions, not an oct grid
    for (int k = 0; k < 16; ++k) {
        const float y = 1.0f - (k + 0.5f) / 8.0f, r = std::sqrt(std::max(0.0f, 1.0f - y * y));
        const float a = 2.399963f * static_cast<float>(k);
        fib.emplace_back(r * std::cos(a), y, r * std::sin(a));
    }
    EXPECT_EQ(far::make_impostor_views(fib).grid, 0);
    EXPECT_EQ(far::make_impostor_views(std::vector<glm::vec3>(6, glm::vec3(0, 1, 0))).grid, 0);
    EXPECT_EQ(far::make_impostor_views({}).grid, 0);
}

TEST(FarImpostorBlend, OctViewsAreUnitAndMirrorTwinsAreBitIdentical) {
    const int N = 8;
    const auto dirs = far::oct_view_dirs(N);
    ASSERT_EQ(dirs.size(), 64u);
    for (const auto& d : dirs) EXPECT_NEAR(glm::length(d), 1.0f, 1e-6f);
    auto at = [&](int i, int j) { return dirs[static_cast<std::size_t>(j * N + i)]; };
    for (int k = 0; k < N; ++k) {   // each border edge folds onto itself, mirrored
        EXPECT_EQ(at(k, 0), at(N - 1 - k, 0)) << k;
        EXPECT_EQ(at(k, N - 1), at(N - 1 - k, N - 1)) << k;
        EXPECT_EQ(at(0, k), at(0, N - 1 - k)) << k;
        EXPECT_EQ(at(N - 1, k), at(N - 1, N - 1 - k)) << k;
    }
    EXPECT_EQ(at(0, 0), glm::vec3(0.0f, -1.0f, 0.0f));   // every corner is the -y pole
    EXPECT_EQ(at(N - 1, N - 1), at(0, 0));
    // 36 interior + 4 edges x 3 + 1 pole distinct directions.
    std::set<std::array<float, 3>> distinct;
    for (const auto& d : dirs) distinct.insert({d.x, d.y, d.z});
    EXPECT_EQ(distinct.size(), 49u);
    for (std::size_t v = 0; v < dirs.size(); ++v)
        EXPECT_NEAR(glm::length(far::oct_decode(far::oct_encode(dirs[v])) - dirs[v]), 0.0f, 1e-6f) << v;
}

TEST(FarImpostorBlend, ABakedDirectionIsExactlyThatView) {
    for (int N : {4, 8}) {
        const auto dirs = far::oct_view_dirs(N);
        ASSERT_EQ(dirs.size(), static_cast<std::size_t>(N * N));
        for (std::size_t v = 0; v < dirs.size(); ++v) {
            const auto m = by_direction(far::view_blend(dirs[v], N), N);
            ASSERT_EQ(m.size(), 1u) << "N " << N << " view " << v;
            EXPECT_EQ(m.begin()->first, (std::array<float, 3>{dirs[v].x, dirs[v].y, dirs[v].z}));
            EXPECT_NEAR(m.begin()->second, 1.0f, 1e-5f) << v;
        }
    }
}

TEST(FarImpostorBlend, WeightsAreNonNegativeAndSumToOne) {
    std::uint32_t s = 12345u;
    auto u = [&]() { s = s * 1664525u + 1013904223u; return (s >> 8) / 16777216.0f * 2.0f - 1.0f; };
    for (int n = 0; n < 20000; ++n) {
        glm::vec3 d(u(), u(), u());
        if (glm::length(d) < 1e-3f) continue;
        d = glm::normalize(d);
        const far::ViewBlend b = far::view_blend(d, 8);
        float sum = 0.0f;
        for (int k = 0; k < 3; ++k) {
            EXPECT_GE(b.w[k], 0.0f);
            EXPECT_GE(b.view[k], 0); EXPECT_LT(b.view[k], 64);
            sum += b.w[k];
        }
        EXPECT_NEAR(sum, 1.0f, 1e-5f);
    }
}

// A small rotation of the eye changes the weights a little -- everywhere,
// including across the oct map's folds and through both poles. A snap to
// another view would change them by up to 2 in one step.
TEST(FarImpostorBlend, WeightsAreContinuousInTheEyeDirection) {
    const float step = 1e-3f;
    const glm::vec3 axes[] = {{0, 0, 1}, {1, 0, 0}, {0, 1, 0}, glm::normalize(glm::vec3(1, 1, 0)),
                              glm::normalize(glm::vec3(0.3f, -0.8f, 0.5f)), glm::normalize(glm::vec3(-1, 0.2f, 1))};
    float worst = 0.0f;
    for (const glm::vec3& axis : axes) {
        // A start perpendicular to the axis: a great circle through the folds.
        glm::vec3 start = glm::cross(axis, glm::vec3(0.31f, 0.52f, 0.79f));
        start = glm::normalize(start);
        DirWeights prev = by_direction(far::view_blend(start, 8), 8);
        for (int i = 1; i <= static_cast<int>(6.2832f / step); ++i) {
            const DirWeights cur = by_direction(far::view_blend(rot(axis, step * i, start), 8), 8);
            const float d = l1(prev, cur);
            worst = std::max(worst, d);
            ASSERT_LT(d, 50.0f * step) << "axis (" << axis.x << " " << axis.y << " " << axis.z << ") step " << i;
            prev = cur;
        }
    }
    std::printf("[view_blend] worst L1 weight change per 1e-3 rad: %.5f\n", worst);
}

// A full turn about any axis returns the same weights: the loop closes.
TEST(FarImpostorBlend, AFullRevolutionReturnsTheSameWeights) {
    const glm::vec3 axis = glm::normalize(glm::vec3(0.2f, 0.9f, -0.4f));
    const glm::vec3 eye = glm::normalize(glm::vec3(0.7f, -0.1f, 0.4f));
    const int steps = 240;
    for (int i = 0; i <= steps; ++i) {
        const float a = 6.2831853f * static_cast<float>(i) / steps;
        const auto w0 = by_direction(far::view_blend(rot(axis, a, eye), 8), 8);
        const auto w1 = by_direction(far::view_blend(rot(axis, a + 6.2831853f, eye), 8), 8);
        EXPECT_LT(l1(w0, w1), 1e-4f) << i;
    }
}

// Report only: the CPU cost of one billboard instance (view_blend + the
// rock axes), the per-sprite work of the near / mid / far builds.
TEST(FarImpostorBlend, MakeImpostorCostReport) {
    const far::ImpostorViews views = far::make_impostor_views(far::oct_view_dirs(8));
    std::vector<glm::mat3> Rs;
    for (int i = 0; i < 256; ++i)
        Rs.emplace_back(glm::rotate(glm::mat4(1.0f), 0.37f * i, glm::normalize(glm::vec3(0.3f, std::sin(i * 1.0f), 0.8f))));
    constexpr int kCalls = 200000;
    float sink = 0.0f;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < kCalls; ++i) {
        const auto g = far::make_impostor(views, glm::vec3(10.0f, -40.0f, 3.0f), glm::vec3(0.01f * i, 0, 0),
                                          Rs[static_cast<std::size_t>(i) & 255u], 1.0f, 0.0f);
        sink += g.weights.x;
    }
    const double ns = std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now() - t0).count() / kCalls;
    std::printf("[impostor blend] make_impostor: %.1f ns per billboard (checksum %.1f)\n", ns, sink);
    EXPECT_GT(sink, 0.0f);
}

// Rock fade (2026-10-03): a translucent impostor's alpha is the coverage its
// signed dither would have kept -- |d| fading in (d < 0), 1 - d fading out
// (d > 0), 1 when solid. impostor.vert/opaque.frag compute the same.
TEST(FarImpostor, FadeAlphaIsTheDitherCoverage) {
    EXPECT_EQ(far::impostor_fade_alpha(0.0f), 1.0f);
    EXPECT_FLOAT_EQ(far::impostor_fade_alpha(-0.3f), 0.3f);
    EXPECT_FLOAT_EQ(far::impostor_fade_alpha(0.3f), 0.7f);
    EXPECT_EQ(far::impostor_fade_alpha(-1.0f), 1.0f);
    EXPECT_EQ(far::impostor_fade_alpha(1.0f), 0.0f);
}
