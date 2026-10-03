// native/tests/renderer/far_field_test.cc
// Far tier spec §2: sources, haze and the per-camera build (flagged rocks).
#include <gtest/gtest.h>
#include <renderer/far_field.h>
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

TEST(FarField, MajorsOnlyAboveHalf) {
    const auto s = vesuvi_like();
    EXPECT_EQ(far::pop_density(s.pops[1], 0.5f), 0.0f);
    EXPECT_NEAR(far::pop_density(s.pops[1], 0.75f), 0.5f / 1.2e9f, 1e-15f);
    EXPECT_NEAR(far::pop_density(s.pops[0], 0.5f), 0.5f * 9.67e-8f, 1e-12f);
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
// (the near/mid bands of the rock-fields spec replace it).
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

// ---- Haze (spec §2 "Haze") -------------------------------------------------

namespace {
far::DiscSource vesuvi_minors_only() {
    auto s = vesuvi_like();
    s.pops.resize(1);   // a = 0.5 has no majors; the derivation uses minors only
    return s;
}
}  // namespace

// ---- Displayed-brightness calibration (ruling R16, 2026-10-02) -------------
//
// Over black space only the premultiplied colour shows, and the pipeline has
// no sRGB encode: resolve.frag multiplies by EXPOSURE 0.95, its shoulder is
// identity below 0.82, saturation/tint preserve the channel mean to <1%. So
// the DISPLAYED value is 0.95 * rgb * 255; we calibrate the MEAN OF THE
// CHANNELS of that to 25/255 at each reference view, with the scene's REAL
// light (the shader's term: ambient * ambient_scale + sum colour *
// lambert_sphere_phase(dot(L, -dir))) and the catalogue's real minor albedo.

namespace {
struct RealLight {
    glm::vec3 ambient;
    float ambient_scale;
    glm::vec3 dir[2], colour[2];   // toward each light
};

// far_haze.frag's light term for a view direction.
glm::vec3 light_for(const RealLight& L, const glm::vec3& view_dir) {
    glm::vec3 out = L.ambient * L.ambient_scale;
    for (int i = 0; i < 2; ++i)
        out += L.colour[i] * far::lambert_sphere_phase(glm::dot(glm::normalize(L.dir[i]), -view_dir));
    return out;
}

float displayed_255(const glm::vec3& rgb) {
    return 0.95f * (rgb.r + rgb.g + rgb.b) / 3.0f * 255.0f;
}

// The catalogue's silicate fragments (indices 5..12): density.to_native's
// albedo for every minor population, belts and tile fields alike.
const glm::vec3 kMinorAlbedo(0.439619f, 0.414532f, 0.379402f);

// ambient_scale 0.3: dauntless_filmic kFilmicAmbientScale (frame.cc), filmic
// on by default on the exterior view.
constexpr float kFilmicAmbient = 0.3f;

// Beol 4, the player at "Player Start": host_loop._aggregate_lights(Beol4
// set, Player Start) -- BC's lights with the key re-aimed from the Beol star
// by star_light.for_player. Captured 2026-10-02 from the production path.
RealLight beol4_player_start_light() {
    return {glm::vec3(0.1f), kFilmicAmbient,
            {glm::vec3(-0.293875f, -0.955838f, -0.003459f),
             glm::vec3(0.637224f, 0.172051f, 0.751228f)},
            {glm::vec3(0.435523f, 0.494378f, 0.588545f), glm::vec3(0.14f, 0.14f, 0.10f)}};
}

// Vesuvi, a player at system (278000, 0, 0) in Vesuvi6 (the region E1M2
// plays in): host_loop._aggregate_lights(Vesuvi6 set, that player). Vesuvi5's
// lights give (0.200, 0.209, 0.224) on the same view, within 1%.
RealLight vesuvi_mid_band_light() {
    return {glm::vec3(0.15f), kFilmicAmbient,
            {glm::vec3(-1.0f, 0.0f, 0.0f), glm::vec3(0.204929f, -0.064101f, 0.976676f)},
            {glm::vec3(0.393253f, 0.433587f, 0.504171f), glm::vec3(0.3f)}};
}
}  // namespace

// Spec §2 (ruling R14): with the default gain (270), looking FORWARD along the
// mid-plane of Vesuvi's band from mid-band (rho 278,000 GU) on a tangent, the
// haze alpha is 0.15 +- 0.03. The eye sees only the forward half of the band
// chord, which is why the default is 270 and not the 143 of a full chord.
// Re-derived after ruling R16 removed the pixel cut: 0.1501 -- unchanged to
// four places, because the cut only ever bit within ~5,000 GU of the eye and
// this chord is ~hundreds of thousands of GU long.
TEST(FarHaze, DefaultGainHitsTheStatedTarget) {
    EXPECT_EQ(far::FarDials{}.haze_gain, 270.0f);
    const far::DiscSource s = vesuvi_minors_only();
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 4.0f, 24, 270.0f,
                                    glm::vec3(1.0f));
    std::printf("[FarHaze] default-gain alpha = %.4f\n", h.alpha);
    EXPECT_NEAR(h.alpha, 0.15f, 0.03f);
}

// Belt brightness (engine/rocks/far_dials.py "haze_brightness"; FarDials has
// no copy -- it rides per source). Vesuvi mid-band (rho 278,000 GU, z 0)
// looking tangentially along the plane, Vesuvi's real light: at the belt gain
// alpha is 0.15 and its colour at brightness 1 shows as 3.12/255;
// 25 / 3.12 = 8.01 => 8.0.
constexpr float kHazeBrightness = 8.0f;
TEST(FarHaze, DefaultBeltBrightnessShowsTwentyFiveOverBlack) {
    far::DiscSource s = vesuvi_like();   // the real Vesuvi table's asteroids column
    for (auto& P : s.pops) P.albedo = kMinorAlbedo;
    s.brightness = kHazeBrightness;
    const glm::vec3 dir(0.0f, 1.0f, 0.0f);
    const glm::vec3 L = light_for(vesuvi_mid_band_light(), dir);
    std::printf("[FarHaze] Vesuvi mid-band light (%.4f %.4f %.4f)\n", L.r, L.g, L.b);
    EXPECT_NEAR(L.r, 0.198654f, 1e-4f);   // the production value (see the fixture)
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, dir, 1.0e6f, 4.0f, 24,
                                    far::FarDials{}.haze_gain, L);
    std::printf("[FarHaze] belt displayed %.2f/255 (alpha %.4f)\n", displayed_255(h.rgb),
                h.alpha);
    EXPECT_NEAR(displayed_255(h.rgb), 25.0f, 1.0f);
}

TEST(FarHaze, NoSourceNoHaze) {
    far::DiscSource s = vesuvi_minors_only();
    s.table.clear();
    const auto h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                    1.0e6f, 4.0f, 24, 143.0f,
                                    glm::vec3(1.0f));
    EXPECT_EQ(h.alpha, 0.0f);
    EXPECT_EQ(h.rgb, glm::vec3(0.0f));
}

TEST(FarHaze, StopsAtSceneDepth) {
    const far::DiscSource s = vesuvi_minors_only();
    const auto far_h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                        1.0e6f, 4.0f, 24, 143.0f,
                                        glm::vec3(1.0f));
    const auto near_h = far::haze_column(s, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f},
                                         1000.0f, 4.0f, 24, 143.0f,
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
                                    1.0e6f, 4.0f, 24, 143.0f, light);
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
                                    1.0e6f, 4.0f, 24, 143.0f,
                                    glm::vec3(1.0f));
    EXPECT_EQ(h.alpha, 0.0f);
}

TEST(FarMathCrossSection, BelowPlusAboveIsTheMean) {
    // For one size population: cross_section_below(r_cut) + the cross-section
    // of r >= r_cut == mean_cross_section, at the r_cut the per-rock cull
    // uses at distance d. (The haze itself no longer cuts -- ruling R16 -- but
    // the closed form is still far_math's.) The share above is integrated
    // numerically, independent of the closed form, for q = 2.5 and the
    // q == 1 / q == 3 log branches.
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

// ---- Tile-field haze: Sphere sources (added 2026-10-02) --------------------

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

TEST(FarHazeSphere, DensityIsOneInsideAndRampsToZeroAtTheRadius) {
    const far::DiscSource s = beol4_tile_field();
    const glm::dvec3 c = s.centre, x(1.0, 0.0, 0.0);
    EXPECT_EQ(far::density_a(s, c), 1.0f);
    EXPECT_EQ(far::density_a(s, c + 799.0 * x), 1.0f);
    EXPECT_NEAR(far::density_a(s, c + 900.0 * x), 0.5f, 1e-5f);
    EXPECT_EQ(far::density_a(s, c + 1000.0 * x), 0.0f);
    EXPECT_EQ(far::density_a(s, c + 1500.0 * x), 0.0f);
}

TEST(FarHazeSphere, IntervalIsTheChordClippedToTheRay) {
    far::DiscSource s = beol4_tile_field();
    s.centre = {0.0, 0.0, 0.0};
    double t0 = 0, t1 = 0;
    ASSERT_TRUE(far::haze_interval(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, t0, t1));
    EXPECT_NEAR(t0, 1000.0, 1e-6);
    EXPECT_NEAR(t1, 3000.0, 1e-6);
    // From inside: starts at the eye.
    ASSERT_TRUE(far::haze_interval(s, {0.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, t0, t1));
    EXPECT_EQ(t0, 0.0);
    EXPECT_NEAR(t1, 1000.0, 1e-6);
    // Depth stop.
    ASSERT_TRUE(far::haze_interval(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1500.0f, 4.0f, t0, t1));
    EXPECT_NEAR(t1, 1500.0, 1e-6);
    // Missing it, and pointing away from it.
    EXPECT_FALSE(far::haze_interval(s, {-2000.0, 1001.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, t0, t1));
    EXPECT_FALSE(far::haze_interval(s, {-2000.0, 0.0, 0.0}, {-1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, t0, t1));
}

TEST(FarHazeSphere, ColumnIsZeroOutsideThickestThroughTheCentreAndStopsAtDepth) {
    far::DiscSource s = beol4_tile_field();
    s.centre = {0.0, 0.0, 0.0};
    const glm::vec3 L(1.0f);
    auto col = [&](glm::dvec3 o, float t_max) {
        return far::haze_column(s, o, {1.0f, 0.0f, 0.0f}, t_max, 4.0f, 24,
                                1.0e5f, L);
    };
    const auto centre = col({-2000.0, 0.0, 0.0}, 1.0e6f);
    const auto graze = col({-2000.0, 900.0, 0.0}, 1.0e6f);
    const auto miss = col({-2000.0, 1001.0, 0.0}, 1.0e6f);
    const auto stopped = col({-2000.0, 0.0, 0.0}, 1050.0f);
    EXPECT_GT(centre.alpha, 0.0f);
    EXPECT_GT(graze.alpha, 0.0f);
    EXPECT_GT(centre.alpha, 2.0f * graze.alpha);
    EXPECT_EQ(miss.alpha, 0.0f);
    EXPECT_EQ(miss.rgb, glm::vec3(0.0f));
    EXPECT_LT(stopped.alpha, 0.1f * centre.alpha);
}

TEST(FarHazeSphere, GainScaleMultipliesTheGain) {
    far::DiscSource s = beol4_tile_field();
    s.centre = {0.0, 0.0, 0.0};
    const auto a = far::haze_column(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, 24, 2.0e5f, glm::vec3(1.0f));
    s.gain_scale = 2.0f;
    const auto b = far::haze_column(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, 24, 1.0e5f, glm::vec3(1.0f));
    EXPECT_NEAR(a.alpha, b.alpha, 1e-6f);
    EXPECT_GT(b.alpha, 0.0f);
}

// Haze brightness (2026-10-02, ruling R16): `brightness` scales the colour a
// source accumulates and nothing else -- alpha (the transmittance) is the
// same at any brightness.
TEST(FarHazeSphere, BrightnessScalesColourNotAlpha) {
    far::DiscSource s = beol4_tile_field();
    s.centre = {0.0, 0.0, 0.0};
    const glm::vec3 L(0.3f, 0.2f, 0.1f);
    const auto a = far::haze_column(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, 24, 2.0e4f, L);
    s.brightness = 7.5f;
    const auto b = far::haze_column(s, {-2000.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, 24, 2.0e4f, L);
    ASSERT_GT(a.alpha, 0.01f);
    EXPECT_EQ(b.alpha, a.alpha);
    for (int c = 0; c < 3; ++c) EXPECT_NEAR(b.rgb[c], 7.5f * a.rgb[c], 1e-6f);
}

// No pixel cut (ruling R16): the haze integrates the WHOLE population
// cross-section at every distance, so it does not depend on the camera's k
// (resolution, fov). Through the centre of a sphere with no edge ramp, n is
// constant over the 2R chord, so tau = gain * n * mean_cross_section * 2R
// exactly (the midpoint rule is exact for a constant).
TEST(FarHazeSphere, HazeIsTheWholeCrossSectionAtAnyDistance) {
    far::DiscSource s = beol4_tile_field();
    s.centre = {0.0, 0.0, 0.0};
    s.sphere_edge_frac = 0.0f;
    const float gain = 2.0e4f;
    const double tau = static_cast<double>(gain) * s.pops[0].density_at_1 *
                       far::mean_cross_section(s.pops[0].size) * 2000.0;
    const auto h = far::haze_column(s, {-1001.0, 0.0, 0.0}, {1.0f, 0.0f, 0.0f}, 1.0e6f, 4.0f, 24, gain, glm::vec3(1.0f));
    EXPECT_NEAR(h.alpha, 1.0 - std::exp(-tau), 1e-4 * (1.0 - std::exp(-tau)));
}

TEST(FarFieldBuild, ANonProceduralSourceStillHazes) {
    far::FarField f = field_with_catalogue();
    auto s = vesuvi_like();
    s.procedural = false;
    f.set_sources({s});
    f.set_frame(std::string("Vesuvi"), {280000.0, 0.0, 0.0});
    far::FarOutput out;
    f.build(camera_at({0, 0, 0}, {0, 1, 0}), out);
    EXPECT_TRUE(out.specks.empty());
    EXPECT_TRUE(out.impostors.empty());
    EXPECT_EQ(f.active_sources().size(), 1u);   // still hazes
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

// Tile-field haze gains.
// kTileHazeGain is the DEFAULT (engine/rocks/far_dials.py "tile_haze_gain";
// keep the two equal -- tests/unit/test_far_dials.py pins the Python side):
// Mark's live choice 2026-10-03 ("this works well"), 131,700 = 9.3x the
// derivation below, so the Player Start column reaches alpha ~0.78.
// kTileHazeCalibrationGain is the DERIVED gain the brightness calibration
// was made at (re-derived 2026-10-02 after ruling R16 removed the pixel cut):
// from Beol 4 "Player Start" (-593.717346, 840.869934, -269.268738) looking
// at the tile field's centre, 24 steps, Beol 4's numbers (beol4_tile_field).
// alpha is 1 - exp(-gain * tau_1) exactly (T telescopes), so gain =
// -ln(0.85) / tau_1 for the target alpha 0.15. Measured tau_1 = 1.1497e-5 =>
// gain 14,136, rounded to 14,140. (With the old r_cut at k = 1713 it was
// 26,860; with no cut the haze no longer depends on k at all.)
constexpr float kTileHazeCalibrationGain = 14140.0f;
constexpr float kTileHazeGain = 131700.0f;
TEST(FarHazeSphere, TileGainsHitTheirStatedTargets) {
    const far::DiscSource s = beol4_tile_field();
    const glm::dvec3 eye(-593.717346, 840.869934, -269.268738);
    const glm::vec3 dir = glm::vec3(glm::normalize(s.centre - eye));
    // Measured at gain 1e4 (alpha ~0.1): at gain 1 alpha ~1e-5 is too
    // close to float epsilon for 1 - T to carry tau_1 accurately.
    const auto probe = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f,
                                        glm::vec3(1.0f));
    const double tau1 = -std::log(1.0 - static_cast<double>(probe.alpha)) / 1.0e4;
    std::printf("[FarHazeSphere] tau at gain 1 = %.6e; gain for 0.15 = %.2f\n", tau1,
                -std::log(0.85) / tau1);
    const auto c = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, kTileHazeCalibrationGain,
                                    glm::vec3(1.0f));
    std::printf("[FarHazeSphere] tile alpha at gain %.1f = %.4f\n", kTileHazeCalibrationGain,
                c.alpha);
    EXPECT_NEAR(c.alpha, 0.15f, 0.03f);
    const auto h = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, kTileHazeGain,
                                    glm::vec3(1.0f));
    std::printf("[FarHazeSphere] tile alpha at gain %.1f = %.4f\n", kTileHazeGain, h.alpha);
    EXPECT_NEAR(h.alpha, 0.78f, 0.03f);
}


// Tile-field brightness (engine/rocks/far_dials.py "tile_haze_brightness").
// At the calibration gain the reference view's alpha is 0.15 and its colour at
// brightness 1 shows as 2.75/255; 25 / 2.75 = 9.09 => 9.1.
constexpr float kTileHazeBrightness = 9.1f;
TEST(FarHazeSphere, DefaultTileBrightnessShowsTwentyFiveOverBlack) {
    far::DiscSource s = beol4_tile_field();
    s.pops[0].albedo = kMinorAlbedo;
    s.brightness = kTileHazeBrightness;
    const glm::dvec3 eye(-593.717346, 840.869934, -269.268738);
    const glm::vec3 dir = glm::vec3(glm::normalize(s.centre - eye));
    const glm::vec3 L = light_for(beol4_player_start_light(), dir);
    std::printf("[FarHazeSphere] Beol 4 light (%.4f %.4f %.4f)\n", L.r, L.g, L.b);
    EXPECT_NEAR(L.r, 0.163660f, 1e-4f);   // the production value (see the fixture)
    const auto h = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, kTileHazeCalibrationGain, L);
    std::printf("[FarHazeSphere] tile displayed %.2f/255 (alpha %.4f)\n", displayed_255(h.rgb),
                h.alpha);
    EXPECT_NEAR(displayed_255(h.rgb), 25.0f, 1.0f);
}

// ---- Tile-field haze noise (2026-10-02) ------------------------------------
// A tile field's sphere haze is modulated by 3D value-noise fbm FIXED to the
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

TEST(FarHazeNoise, FbmIsDeterministicSeededAndInZeroOne) {
    int differs = 0;
    for (int i = 0; i < 200; ++i) {
        const glm::vec3 p(0.37f * i - 11.0f, 1.13f * i + 0.5f, -0.71f * i + 3.0f);
        const float a = far::haze_fbm(p, 3, 7u);
        EXPECT_EQ(a, far::haze_fbm(p, 3, 7u));
        EXPECT_GE(a, 0.0f);
        EXPECT_LE(a, 1.0f);
        if (std::fabs(a - far::haze_fbm(p, 3, 8u)) > 0.05f) ++differs;
    }
    EXPECT_GT(differs, 100);
}

TEST(FarHazeNoise, ValueNoiseHitsTheLatticeValuesAndIsContinuous) {
    // At an integer point the trilinear blend is the corner's hashed value.
    const float v = far::haze_value_noise(glm::vec3(3.0f, -2.0f, 5.0f), 11u);
    EXPECT_NEAR(far::haze_value_noise(glm::vec3(3.0f + 1e-4f, -2.0f, 5.0f), 11u), v, 1e-3f);
    EXPECT_NEAR(far::haze_value_noise(glm::vec3(3.0f - 1e-4f, -2.0f, 5.0f), 11u), v, 1e-3f);
}

TEST(FarHazeNoise, MeanModulationIsOne) {
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
        const double m = far::haze_noise_m(s, p);
        sum += m; lo = std::min(lo, m); hi = std::max(hi, m);
    }
    std::printf("[FarHazeNoise] mean m over %d points = %.4f (min %.3f max %.3f)\n", n,
                sum / n, lo, hi);
    EXPECT_NEAR(sum / n, 1.0, 0.05);
    EXPECT_LT(lo, 0.7);   // it IS clumpy
    EXPECT_GT(hi, 1.3);
}

TEST(FarHazeNoise, PatternIsFixedToTheField) {
    far::DiscSource s = noisy_tile_field();
    const glm::dvec3 off(123.0, -45.0, 300.0);
    const float m0 = far::haze_noise_m(s, s.centre + off);
    s.centre += glm::dvec3(5000.0, 0.0, -700.0);
    EXPECT_EQ(far::haze_noise_m(s, s.centre + off), m0);
}

TEST(FarHazeNoise, OffMeansOne) {
    far::DiscSource s = noisy_tile_field();
    s.noise_contrast = 0.0f;
    EXPECT_EQ(far::haze_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
    s = noisy_tile_field(); s.noise_scale_gu = 0.0f;
    EXPECT_EQ(far::haze_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
    s = noisy_tile_field(); s.noise_octaves = 0;
    EXPECT_EQ(far::haze_noise_m(s, s.centre + glm::dvec3(10.0)), 1.0f);
}

TEST(FarHazeNoise, ContrastZeroColumnIsByteIdenticalToNoNoise) {
    const far::DiscSource plain = beol4_tile_field();
    far::DiscSource zero = noisy_tile_field();
    zero.noise_contrast = 0.0f;
    const glm::dvec3 eye(-593.717346, 840.869934, -269.268738);
    const glm::vec3 dir = glm::vec3(glm::normalize(plain.centre - eye));
    const auto a = far::haze_column(plain, eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f, glm::vec3(0.3f));
    const auto b = far::haze_column(zero, eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f, glm::vec3(0.3f));
    EXPECT_EQ(a.alpha, b.alpha);
    EXPECT_EQ(a.rgb, b.rgb);
    // And with noise on, the column changes.
    const auto c = far::haze_column(noisy_tile_field(), eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f,
                                    glm::vec3(0.3f));
    EXPECT_NE(a.alpha, c.alpha);
}

// Rock-fields R1 (2026-10-02): belts carry the noise too (they used to
// ignore the keys).
TEST(FarHazeNoise, BeltColumnCarriesTheNoiseKeys) {
    const far::DiscSource plain = vesuvi_like();
    far::DiscSource noisy = vesuvi_like();
    noisy.noise_scale_gu = 4000.0f; noisy.noise_contrast = 0.8f; noisy.noise_octaves = 3;
    const auto a = far::haze_column(plain, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f}, 1.0e6f, 4.0f, 24, 270.0f, glm::vec3(0.3f));
    const auto b = far::haze_column(noisy, {278000.0, 0.0, 0.0}, {0.0f, 1.0f, 0.0f}, 1.0e6f, 4.0f, 24, 270.0f, glm::vec3(0.3f));
    EXPECT_NE(a.alpha, b.alpha);
}

TEST(FarHazeNoise, PerSourceStepsOverrideTheGlobalAndClampTo64) {
    far::DiscSource s = noisy_tile_field();
    const glm::dvec3 eye(-593.717346, 840.869934, -269.268738);
    const glm::vec3 dir = glm::vec3(glm::normalize(s.centre - eye));
    const auto g48 = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 48, 1.0e4f, glm::vec3(1.0f));
    const auto g64 = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 64, 1.0e4f, glm::vec3(1.0f));
    s.steps = 48;
    const auto o48 = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f, glm::vec3(1.0f));
    EXPECT_EQ(o48.alpha, g48.alpha);
    s.steps = 500;
    const auto o500 = far::haze_column(s, eye, dir, 1.0e6f, 4.0f, 24, 1.0e4f, glm::vec3(1.0f));
    EXPECT_EQ(o500.alpha, g64.alpha);
    EXPECT_EQ(far::haze_steps_for(s, 24), 64);
    s.steps = 0;
    EXPECT_EQ(far::haze_steps_for(s, 24), 24);
}

// The tile calibration with the production noise on (250 GU, contrast 0.8,
// 3 octaves, 48 steps). A single ray is no longer 25 +- 1: through the
// centre from Beol 4's Player Start it reads 24.2-26.1/255 across seeds (3:
// 26.14). So, per the brief, the MEAN is pinned instead: over the 81 view
// rays of a 21x21 grid inside the inner half of the field's disc, the noisy
// mean is within 1/255 of the noise-off mean (22.87/255; noisy 22.2-23.7 over
// the four seeds below). Brightness is NOT retuned for the noise --
// DefaultTileBrightnessShowsTwentyFiveOverBlack (noise off) still defines it.
TEST(FarHazeNoise, TileNoiseKeepsTheMeanDisplayedHaze) {
    for (std::uint32_t seed : {3u, 7u, 1234567u, 0xdeadbeefu}) {
        far::DiscSource s = noisy_tile_field();
        s.seed = seed; s.steps = 48;
        s.pops[0].albedo = kMinorAlbedo;
        s.brightness = kTileHazeBrightness;
        far::DiscSource plain = s;
        plain.noise_contrast = 0.0f;
        const glm::dvec3 eye(-593.717346, 840.869934, -269.268738);
        const glm::vec3 fwd = glm::vec3(glm::normalize(s.centre - eye));
        const far::ViewBasis b = far::make_view_basis(fwd);
        const float ang = static_cast<float>(
            std::asin(s.sphere_radius_gu / glm::length(s.centre - eye)));
        double sum_noisy = 0.0, sum_plain = 0.0;
        int n = 0;
        for (int i = -10; i <= 10; ++i)
            for (int j = -10; j <= 10; ++j) {
                const float ax = ang * i / 10.0f, ay = ang * j / 10.0f;
                if (ax * ax + ay * ay > 0.25f * ang * ang) continue;
                const glm::vec3 d =
                    glm::normalize(fwd + std::tan(ax) * b.right + std::tan(ay) * b.up);
                const glm::vec3 L = light_for(beol4_player_start_light(), d);
                sum_noisy += displayed_255(
                    far::haze_column(s, eye, d, 1.0e6f, 4.0f, 24, kTileHazeCalibrationGain, L).rgb);
                sum_plain += displayed_255(
                    far::haze_column(plain, eye, d, 1.0e6f, 4.0f, 24, kTileHazeCalibrationGain, L).rgb);
                ++n;
            }
        std::printf("[FarHazeNoise] seed %u: mean over %d rays noisy %.2f plain %.2f /255\n",
                    seed, n, sum_noisy / n, sum_plain / n);
        EXPECT_EQ(n, 81);
        EXPECT_NEAR(sum_noisy / n, sum_plain / n, 1.0);
    }
}

TEST(FarNoise, DiscSourcesNowCarryNoise) {
    far::DiscSource s;                       // a disc
    s.table = {{0.0f, 1.0f}, {50000.0f, 1.0f}};
    s.noise_scale_gu = 1000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3; s.seed = 7;
    bool varied = false;
    for (int i = 0; i < 64; ++i) {
        const float m = far::haze_noise_m(s, glm::dvec3(i * 517.0, 300.0, 0.0));
        EXPECT_GE(m, 0.0f);
        EXPECT_LE(m, far::noise_m_bound(s));
        if (std::fabs(m - 1.0f) > 0.05f) varied = true;
    }
    EXPECT_TRUE(varied);
}

TEST(FarNoise, OffIsExactlyOneForBothShapes) {
    far::DiscSource d; d.noise_scale_gu = 0.0f; d.noise_contrast = 0.8f; d.noise_octaves = 3;
    far::DiscSource sph = d; sph.shape = far::DiscSource::Shape::Sphere;
    EXPECT_EQ(far::haze_noise_m(d, glm::dvec3(1, 2, 3)), 1.0f);
    EXPECT_EQ(far::haze_noise_m(sph, glm::dvec3(1, 2, 3)), 1.0f);
}

TEST(FarNoise, FieldDensityIsAtimesM) {
    far::DiscSource s; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 1000.0f; s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f;
    s.noise_octaves = 3; s.seed = 11;
    const glm::dvec3 x(120.0, -40.0, 33.0);
    EXPECT_FLOAT_EQ(far::field_density(s, x), far::density_a(s, x) * far::haze_noise_m(s, x));
}

TEST(FarNoise, ContrastAboveOneIsClampedInTheBound) {
    far::DiscSource s; s.noise_scale_gu = 10.0f; s.noise_contrast = 3.0f; s.noise_octaves = 2;
    EXPECT_FLOAT_EQ(far::noise_m_bound(s), 2.0f);
}

// Golden values recorded 2026-10-02 from the code BEFORE the per-octave seed
// hash refactor (haze_hash(seed) inside every lattice() call): the refactor
// must be value-identical.
TEST(FarNoise, OncePerOctaveSeedHashKeepsValues) {
    const float a = far::haze_fbm(glm::vec3(0.3f, 1.7f, -2.2f), 3, 12345u);
    const float b = far::haze_fbm(glm::vec3(10.1f, -4.0f, 0.5f), 5, 99u);
    const float c = far::haze_value_noise(glm::vec3(-7.5f, 3.25f, 8.0f), 4242u);
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
        EXPECT_EQ(far::haze_noise_m(s, x), far::haze_noise_m(one, x));
    }
}

// rock-fields Task 3: the impostor emit, shared with the near band.
TEST(FarImpostor, MakeImpostorDitherAndSize) {
    const std::vector<glm::vec3> dirs = {glm::vec3(0, 0, 1), glm::vec3(0, 0, -1)};
    const auto g = far::make_impostor(dirs, glm::vec3(0, 0, 10), glm::vec3(0), glm::mat3(1.0f),
                                      2.0f, -0.25f);
    EXPECT_FLOAT_EQ(g.centre_half.w, 2.0f * 1.02f);
    EXPECT_FLOAT_EQ(g.up_dither.w, -0.25f);
}

TEST(FarImpostor, MakeImpostorPicksTheViewNearestTheEye) {
    // Eye on BC +Y == glTF +Z (gltf_to_bc maps (x,y,z) -> (-x,z,y)).
    const std::vector<glm::vec3> dirs = {glm::vec3(0, 0, -1), glm::vec3(1, 0, 0),
                                         glm::vec3(0, 0, 1)};
    const auto g = far::make_impostor(dirs, glm::vec3(0, 50, 0), glm::vec3(0), glm::mat3(1.0f),
                                      1.0f, 0.0f);
    EXPECT_EQ(g.right_view.w, 2.0f);
    EXPECT_EQ(glm::vec3(g.centre_half), glm::vec3(0));
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

// ---- Haze start ramp (rock-fields Task 12) ---------------------------------

namespace {
// A full-density sphere of radius 20,000 GU around the origin, one population.
far::DiscSource full_sphere_20k() {
    far::DiscSource s;
    s.id = 12; s.shape = far::DiscSource::Shape::Sphere; s.procedural = false;
    s.sphere_radius_gu = 20000.0f;
    s.sphere_edge_frac = 0.0f;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = 1.0e-7f;
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    return s;
}
}  // namespace

// The haze ramps in over [start, start + ramp] (the mid band's L2 fade-out):
// a column that stops before the start accumulates nothing; one reaching past
// it does.
TEST(FarHazeStart, NothingBeforeTheStart) {
    const far::DiscSource s = full_sphere_20k();
    const auto near = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 5000.0f, 4.0f, 48,
                                       1000.0f, glm::vec3(1), 6000.0f, 2000.0f);
    EXPECT_EQ(near.alpha, 0.0f);
    EXPECT_EQ(near.rgb, glm::vec3(0.0f));
    const auto far_ = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 19000.0f, 4.0f, 48,
                                       1000.0f, glm::vec3(1), 6000.0f, 2000.0f);
    EXPECT_GT(far_.alpha, 0.0f);
    // And less than the unramped column over the same interval.
    const auto whole = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 19000.0f, 4.0f, 48,
                                        1000.0f, glm::vec3(1));
    EXPECT_LT(far_.alpha, whole.alpha);
}

// ramp == 0 is a hard step at start: the weight is 0 below it and 1 from
// it on, and a column ending short of the start is empty while one reaching
// just past it is not.
TEST(FarHazeStart, ZeroRampIsAHardStep) {
    EXPECT_EQ(far::haze_start_weight(4759.9f, 4760.0f, 0.0f), 0.0f);
    EXPECT_EQ(far::haze_start_weight(4760.0f, 4760.0f, 0.0f), 1.0f);
    EXPECT_EQ(far::haze_start_weight(4000.0f, 4000.0f, 1000.0f), 0.0f);
    EXPECT_EQ(far::haze_start_weight(4500.0f, 4000.0f, 1000.0f), 0.5f);
    EXPECT_EQ(far::haze_start_weight(5000.0f, 4000.0f, 1000.0f), 1.0f);
    const far::DiscSource s = full_sphere_20k();
    const auto before = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 4800.0f, 4.0f, 48,
                                         1000.0f, glm::vec3(1), 4801.0f, 0.0f);
    EXPECT_EQ(before.alpha, 0.0f);
    const auto after = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 4800.0f, 4.0f, 48,
                                        1000.0f, glm::vec3(1), 4799.0f, 0.0f);
    EXPECT_GT(after.alpha, 0.0f);
}

// start 0, ramp 0 is today's column, bit for bit.
TEST(FarHazeStart, ZeroStartIsTodaysColumn) {
    for (const far::DiscSource& s : {full_sphere_20k(), vesuvi_like()}) {
        const glm::dvec3 eye = s.shape == far::DiscSource::Shape::Sphere
                                   ? glm::dvec3(0.0) : glm::dvec3(278000.0, 0.0, 0.0);
        const auto a = far::haze_column(s, eye, glm::vec3(0, 1, 0), 1.0e6f, 4.0f, 24, 270.0f,
                                        glm::vec3(0.7f));
        const auto b = far::haze_column(s, eye, glm::vec3(0, 1, 0), 1.0e6f, 4.0f, 24, 270.0f,
                                        glm::vec3(0.7f), 0.0f, 0.0f);
        EXPECT_GT(a.alpha, 0.0f);
        EXPECT_EQ(a.alpha, b.alpha);
        EXPECT_EQ(a.rgb, b.rgb);
    }
}

// The FarDials defaults put the ramp exactly over the mid band's L2 fade-out
// (haze_handoff_gu - haze_handoff_band_gu .. haze_handoff_gu = 6,000 .. 8,000).
TEST(FarHazeStart, DialDefaults) {
    const far::FarDials d;
    EXPECT_EQ(d.haze_start_gu, 6000.0f);
    EXPECT_EQ(d.haze_start_ramp_gu, 2000.0f);
    EXPECT_EQ(d.haze_res_divisor, 4);
}

// Fix round 1 (controller ruling): the march interval is clipped to start at
// the haze start, so the whole step budget lands inside the haze. With a hard
// step, a noisy column from the eye equals the column marched from the start
// point itself (same points, same steps) -- the noise is fixed to the field,
// so an unclipped march (a third of its steps wasted before the start)
// samples different points and differs.
TEST(FarHazeStart, TheStepBudgetLandsInsideTheHaze) {
    far::DiscSource s = full_sphere_20k();
    s.seed = 77; s.noise_scale_gu = 800.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    const glm::vec3 dir(0, 1, 0);
    const auto clipped = far::haze_column(s, glm::dvec3(0), dir, 19000.0f, 4.0f, 48,
                                          1000.0f, glm::vec3(1), 6000.0f, 0.0f);
    const auto from_start = far::haze_column(s, glm::dvec3(0.0, 6000.0, 0.0), dir, 13000.0f,
                                             4.0f, 48, 1000.0f, glm::vec3(1));
    std::printf("[FarHazeStart] clipped %.6f from-start %.6f\n", clipped.alpha, from_start.alpha);
    EXPECT_GT(clipped.alpha, 0.0f);
    EXPECT_NEAR(clipped.alpha, from_start.alpha, 1e-5f);
    for (int c = 0; c < 3; ++c) EXPECT_NEAR(clipped.rgb[c], from_start.rgb[c], 1e-5f);
}

// An interval that ends at the start (ramp > 0) holds no haze: empty sample.
TEST(FarHazeStart, AnIntervalEndingAtTheStartIsEmpty) {
    const far::DiscSource s = full_sphere_20k();
    const auto h = far::haze_column(s, glm::dvec3(0), glm::vec3(0, 1, 0), 6000.0f, 4.0f, 48,
                                    1000.0f, glm::vec3(1), 6000.0f, 2000.0f);
    EXPECT_EQ(h.alpha, 0.0f);
    EXPECT_EQ(h.rgb, glm::vec3(0.0f));
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
