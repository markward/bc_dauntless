// native/tests/renderer/rock_mid_test.cc
// Rock fields (docs/superpowers/specs/2026-10-02-rock-fields-design.md §3):
// the mid band's nested collection tiles.
#include <gtest/gtest.h>
#include <renderer/rock_mid.h>
#include <algorithm>
#include <cmath>
#include <glm/gtc/matrix_transform.hpp>
using namespace renderer;
namespace {
far::DiscSource full_sphere(float radius = 100000.0f, std::uint32_t id = 3) {   // density 1, no noise
    far::DiscSource s; s.id = id; s.seed = 99 + id; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = radius; s.sphere_edge_frac = 0.0f; s.view_space = true;
    return s;
}
far::DiscSource flat_belt(float a) {     // a everywhere near the plane, no noise
    far::DiscSource b; b.id = 5; b.seed = 1; b.table = {{0.0f, a}, {1e6f, a}};
    b.scale_height_min_gu = 1e6f;
    return b;
}
// 16 collections per variant, atlas slots 0..47 (as Task 9's bake).
std::vector<rockfield::MidCollection> collections() {
    std::vector<rockfield::MidCollection> c;
    for (int v = 0; v < 3; ++v)
        for (int i = 0; i < 16; ++i) c.push_back({v * 16 + i, v});
    return c;
}
std::vector<glm::vec3> view_dirs() {
    return {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}};
}
rockfield::MidField field(const std::vector<far::DiscSource>& sources,
                          const rockfield::MidDials& d = {}) {
    rockfield::MidField f;
    f.set_dials(d);
    f.set_collections(collections());
    f.set_view_dirs(view_dirs());
    f.set_sources(sources);
    return f;
}
rockfield::MidBuildInput looking_along_y(float fov_deg, glm::vec3 eye = glm::vec3(0)) {
    rockfield::MidBuildInput in;
    in.proj = glm::perspective(glm::radians(fov_deg), 1.0f, 0.01f, 1e6f);
    in.view = glm::lookAt(eye, eye + glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
    return in;
}
int total(const rockfield::MidOutput& o) {
    int n = 0;
    for (const auto& b : o.sprites) n += static_cast<int>(b.items.size());
    return n;
}
}  // namespace

TEST(MidLevels, WeightsCrossfadeAndSumToOneInside) {
    rockfield::MidDials m;
    for (float d : {200.0f, 500.0f, 560.0f, 1000.0f, 2000.0f, 3000.0f, 5000.0f}) {
        const float s = rockfield::mid_level_weight(0, d, m) + rockfield::mid_level_weight(1, d, m) +
                        rockfield::mid_level_weight(2, d, m);
        EXPECT_NEAR(s, 1.0f, 1e-5f) << d;
    }
    EXPECT_EQ(rockfield::mid_level_weight(0, 79.0f, m), 0.0f);   // near band owns < 80
    EXPECT_NEAR(rockfield::mid_level_weight(0, 115.0f, m), 0.5f, 1e-5f);
    EXPECT_EQ(rockfield::mid_level_weight(2, 8000.0f, m), 0.0f); // haze owns past the hand-off
    EXPECT_NEAR(rockfield::mid_level_weight(2, 7000.0f, m), 0.5f, 1e-5f);
}

TEST(MidLevels, DitherSignFollowsTheFadeDirection) {
    rockfield::MidDials m;
    // Fading IN (lower ramp): -w.
    EXPECT_NEAR(rockfield::mid_level_dither(0, 115.0f, m), -0.5f, 1e-5f);
    EXPECT_NEAR(rockfield::mid_level_dither(1, 525.0f, m), -0.5f, 1e-5f);
    // Fading OUT (upper ramp): +(1 - w).
    EXPECT_NEAR(rockfield::mid_level_dither(0, 525.0f, m), 0.5f, 1e-5f);
    EXPECT_NEAR(rockfield::mid_level_dither(2, 7000.0f, m), 0.5f, 1e-5f);
    // Solid: exactly 0.
    EXPECT_EQ(rockfield::mid_level_dither(0, 300.0f, m), 0.0f);
    EXPECT_EQ(rockfield::mid_level_dither(1, 1000.0f, m), 0.0f);
    EXPECT_EQ(rockfield::mid_level_dither(2, 4000.0f, m), 0.0f);
    // A crossfade's two halves are complementary: the fading-in level keeps
    // the lower w_in, the fading-out one the upper w_out = 1 - w_in.
    const float in = rockfield::mid_level_dither(1, 500.0f, m);
    const float out = rockfield::mid_level_dither(0, 500.0f, m);
    EXPECT_LT(in, 0.0f); EXPECT_GT(out, 0.0f);
    EXPECT_NEAR(-in + (1.0f - out), 1.0f, 1e-5f);
}

TEST(MidTiles, DeterministicAndDensityDriven) {
    rockfield::MidDials d; d.max_sprites = 1000000;   // the cap must not shape the ratio
    const auto in = looking_along_y(120.0f);

    rockfield::MidOutput full_a, full_b, belt;
    const auto full = field({full_sphere()}, d);
    full.build(in, full_a);
    full.build(in, full_b);
    field({flat_belt(0.05f)}, d).build(in, belt);

    ASSERT_GT(full_a.count, 200);
    EXPECT_EQ(full_a.count, total(full_a));
    const double ratio = static_cast<double>(belt.count) / full_a.count;
    EXPECT_NEAR(ratio, 0.05, 0.03) << belt.count << " / " << full_a.count;

    ASSERT_EQ(full_a.sprites.size(), full_b.sprites.size());
    for (std::size_t i = 0; i < full_a.sprites.size(); ++i) {
        EXPECT_EQ(full_a.sprites[i].rock, full_b.sprites[i].rock);
        ASSERT_EQ(full_a.sprites[i].items.size(), full_b.sprites[i].items.size());
        for (std::size_t j = 0; j < full_a.sprites[i].items.size(); ++j) {
            const auto& x = full_a.sprites[i].items[j];
            const auto& y = full_b.sprites[i].items[j];
            EXPECT_EQ(x.centre_half, y.centre_half);
            EXPECT_EQ(x.right_view, y.right_view);
            EXPECT_EQ(x.up_dither, y.up_dither);
        }
    }
    // Full density => every sprite is a dense (variant 2) collection, slots 32..47.
    for (const auto& b : full_a.sprites) {
        EXPECT_GE(b.rock, 32); EXPECT_LE(b.rock, 47);
    }
    // A sparse belt => sparse collections only, slots 0..15.
    for (const auto& b : belt.sprites) {
        EXPECT_GE(b.rock, 0); EXPECT_LE(b.rock, 15);
    }
}

TEST(MidTiles, OverlappingSourcesDoNotDoublePlace) {
    // Tile hashes ignore the source: two full spheres place exactly the
    // sprites one does (density clamps to 1).
    rockfield::MidDials d; d.max_sprites = 1000000;
    const auto in = looking_along_y(90.0f);
    rockfield::MidOutput one, two;
    field({full_sphere()}, d).build(in, one);
    field({full_sphere(100000.0f, 3), full_sphere(100000.0f, 8)}, d).build(in, two);
    ASSERT_GT(one.count, 0);
    EXPECT_EQ(one.count, two.count);
    ASSERT_EQ(one.sprites.size(), two.sprites.size());
    for (std::size_t i = 0; i < one.sprites.size(); ++i)
        ASSERT_EQ(one.sprites[i].items.size(), two.sprites[i].items.size());
}

TEST(MidTiles, VoidsShowNothing) {
    const auto in = looking_along_y(90.0f);
    rockfield::MidOutput out;
    out.count = 99;
    field({}).build(in, out);
    EXPECT_EQ(out.count, 0);
    EXPECT_TRUE(out.sprites.empty());

    // A source whose density is zero everywhere in range: nothing either.
    rockfield::MidOutput empty_belt;
    field({flat_belt(0.0f)}).build(in, empty_belt);
    EXPECT_EQ(empty_belt.count, 0);
    EXPECT_TRUE(empty_belt.sprites.empty());
}

TEST(MidTiles, NoViewDirsEmitsNothing) {
    rockfield::MidField f;
    f.set_collections(collections());
    f.set_sources({full_sphere()});
    rockfield::MidOutput out;
    f.build(looking_along_y(90.0f), out);
    EXPECT_EQ(out.count, 0);
    EXPECT_TRUE(out.sprites.empty());
}

TEST(MidTiles, NothingInsideTheNearBand) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    const float allowance = 0.25f * d.l0_tile_gu * std::sqrt(3.0f);
    // Eyes on and off tile corners, plus a render-origin / anchor shift.
    for (const glm::vec3 eye : {glm::vec3(0), glm::vec3(37, -12, 81), glm::vec3(75, 75, 75)}) {
        auto in = looking_along_y(170.0f, eye);
        in.render_origin = {10.0, 20.0, -30.0};
        in.anchor_sys = {-5.0, 40.0, 2.0};
        rockfield::MidOutput out;
        field({full_sphere()}, d).build(in, out);
        ASSERT_GT(out.count, 0);
        for (const auto& b : out.sprites)
            for (const auto& g : b.items)
                EXPECT_GE(glm::length(glm::vec3(g.centre_half) - eye), d.in_lo_gu - allowance);
    }
    // A near band wider than a tile: tiles whose centres lie in [~65, 200)
    // exist and must not emit (a jittered sprite sits within the allowance
    // of its tile centre, so any such sprite would land inside the bound).
    rockfield::MidDials big = d;
    big.in_lo_gu = 200.0f; big.in_hi_gu = 300.0f;
    auto in = looking_along_y(170.0f);
    rockfield::MidOutput out;
    field({full_sphere()}, big).build(in, out);
    const float big_allowance = 0.25f * big.l0_tile_gu * std::sqrt(3.0f);
    for (const auto& b : out.sprites)
        for (const auto& g : b.items)
            EXPECT_GE(glm::length(glm::vec3(g.centre_half)), big.in_lo_gu - big_allowance);
}

TEST(MidTiles, SpritesSizedFromTheirTile) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    rockfield::MidOutput out;
    field({full_sphere()}, d).build(looking_along_y(90.0f), out);
    ASSERT_GT(out.count, 0);
    // half = 0.5 * tile * scale * (0.8 + 0.4u), make_impostor pads by 1.02.
    const float lo = 0.5f * d.l0_tile_gu * 0.8f * 1.02f - 1e-3f;
    const float hi = 0.5f * d.l2_tile_gu * 1.2f * 1.02f + 1e-3f;
    for (const auto& b : out.sprites)
        for (const auto& g : b.items) {
            EXPECT_GE(g.centre_half.w, lo);
            EXPECT_LE(g.centre_half.w, hi);
            EXPECT_GE(g.up_dither.w, -1.0f); EXPECT_LE(g.up_dither.w, 1.0f);
        }
}

TEST(MidTiles, CapKeepsTheNearest) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    const auto in = looking_along_y(90.0f);
    rockfield::MidOutput all;
    field({full_sphere()}, d).build(in, all);
    ASSERT_GT(all.count, 100);
    std::vector<float> dists;
    for (const auto& b : all.sprites)
        for (const auto& g : b.items) dists.push_back(glm::length(glm::vec3(g.centre_half)));
    std::sort(dists.begin(), dists.end());

    d.max_sprites = 50;
    rockfield::MidOutput capped;
    field({full_sphere()}, d).build(in, capped);
    EXPECT_EQ(capped.count, 50);
    for (const auto& b : capped.sprites)
        for (const auto& g : b.items)
            EXPECT_LE(glm::length(glm::vec3(g.centre_half)), dists[49] + 1e-3f);
}

TEST(MidTiles, TelephotoCapHolds) {   // Review Focus 5
    rockfield::MidDials m; m.max_sprites = 300;
    // vast full-density sphere (radius 1e6), 1 degree fov looking along +Y.
    rockfield::MidOutput out;
    field({full_sphere(1e6f)}, m).build(looking_along_y(1.0f), out);
    EXPECT_LE(out.count, 300);
    EXPECT_GT(out.count, 0);
    EXPECT_LT(out.tiles, 200000);

    // Tiny tiles (a dial pushed down hard) stay bounded too.
    m.l0_tile_gu = 1.0f; m.l1_tile_gu = 1.0f; m.l2_tile_gu = 1.0f;
    rockfield::MidOutput tiny;
    field({full_sphere(1e6f)}, m).build(looking_along_y(1.0f), tiny);
    EXPECT_LE(tiny.count, 300);
    EXPECT_LT(tiny.tiles, 200000);
}
