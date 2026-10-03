// native/tests/renderer/rock_mid_test.cc
// Rock fields (docs/superpowers/specs/2026-10-02-rock-fields-design.md §3):
// the mid band's nested collection tiles.
#include <gtest/gtest.h>
#include <utility>
#include <renderer/rock_mid.h>
#include "rock_fade_merge.h"
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
    return far::oct_view_dirs(8);
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
// The build's solid + translucent sprites as the one list it emitted before
// the rock-fade split (rock_fade_merge.h), ordered as the build ordered them
// from `in`'s eye.
std::vector<far::ImpostorBin> merged(const rockfield::MidOutput& o,
                                     const rockfield::MidBuildInput& in = {}) {
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    return rock_fade_merge::merge(o.sprites, o.sprites_fading,
                                  [eye](const glm::vec3& c) { return glm::length(c - eye); });
}
int total(const rockfield::MidOutput& o) {
    int n = 0;
    for (const auto& b : merged(o)) n += static_cast<int>(b.items.size());
    return n;
}
}  // namespace

TEST(MidLevels, WeightsCrossfadeAndSumToOneInside) {
    rockfield::MidDials m;
    // Pinned to the pre-2026-10-03 defaults (in_lo_gu 80, in_hi_gu 150, so
    // their midpoint is 115) so the literals below stay valid regardless of
    // rock_mid.h's current defaults.
    m.in_lo_gu = 80.0f; m.in_hi_gu = 150.0f;
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
    // Pinned to the pre-2026-10-03 defaults (in_lo_gu 80, in_hi_gu 150) so
    // the literal distances below stay valid regardless of rock_mid.h's
    // current defaults.
    m.in_lo_gu = 80.0f; m.in_hi_gu = 150.0f;
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
    ASSERT_EQ(full_a.sprites_fading.size(), full_b.sprites_fading.size());
    const auto ma = merged(full_a), mb = merged(full_b);
    ASSERT_EQ(ma.size(), mb.size());
    for (std::size_t i = 0; i < ma.size(); ++i) {
        EXPECT_EQ(ma[i].rock, mb[i].rock);
        ASSERT_EQ(ma[i].items.size(), mb[i].items.size());
        for (std::size_t j = 0; j < ma[i].items.size(); ++j) {
            const auto& x = ma[i].items[j];
            const auto& y = mb[i].items[j];
            EXPECT_EQ(x.centre_half, y.centre_half);
            EXPECT_EQ(x.axis_x_grid, y.axis_x_grid);
            EXPECT_EQ(x.axis_y_dither, y.axis_y_dither);
        }
    }
    // Full density => every sprite is a dense (variant 2) collection, slots 32..47.
    for (const auto& b : merged(full_a)) {
        EXPECT_GE(b.rock, 32); EXPECT_LE(b.rock, 47);
    }
    // A sparse belt => sparse collections only, slots 0..15.
    for (const auto& b : merged(belt)) {
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
    const auto m1 = merged(one), m2 = merged(two);
    ASSERT_EQ(m1.size(), m2.size());
    for (std::size_t i = 0; i < m1.size(); ++i)
        ASSERT_EQ(m1[i].items.size(), m2[i].items.size());
}

TEST(MidTiles, VoidsShowNothing) {
    const auto in = looking_along_y(90.0f);
    rockfield::MidOutput out;
    out.count = 99;
    field({}).build(in, out);
    EXPECT_EQ(out.count, 0);
    EXPECT_TRUE(merged(out).empty());

    // A source whose density is zero everywhere in range: nothing either.
    rockfield::MidOutput empty_belt;
    field({flat_belt(0.0f)}).build(in, empty_belt);
    EXPECT_EQ(empty_belt.count, 0);
    EXPECT_TRUE(merged(empty_belt).empty());
}

TEST(MidTiles, NoViewDirsEmitsNothing) {
    rockfield::MidField f;
    f.set_collections(collections());
    f.set_sources({full_sphere()});
    rockfield::MidOutput out;
    f.build(looking_along_y(90.0f), out);
    EXPECT_EQ(out.count, 0);
    EXPECT_TRUE(merged(out).empty());
}

TEST(MidTiles, NothingInsideTheNearBand) {   // final review 3: gated on the SPRITE
    rockfield::MidDials d; d.max_sprites = 1000000;
    // Eyes on and off tile corners, plus a render-origin / anchor shift.
    for (const glm::vec3 eye : {glm::vec3(0), glm::vec3(37, -12, 81), glm::vec3(75, 75, 75)}) {
        auto in = looking_along_y(170.0f, eye);
        in.render_origin = {10.0, 20.0, -30.0};
        in.anchor_sys = {-5.0, 40.0, 2.0};
        rockfield::MidOutput out;
        field({full_sphere()}, d).build(in, out);
        ASSERT_GT(out.count, 0);
        for (const auto& b : merged(out))
            for (const auto& g : b.items)
                EXPECT_GE(glm::length(glm::vec3(g.centre_half) - eye), d.in_lo_gu);
    }
    // A near band wider than a tile: no sprite inside it either.
    rockfield::MidDials big = d;
    big.in_lo_gu = 200.0f; big.in_hi_gu = 300.0f;
    auto in = looking_along_y(170.0f);
    rockfield::MidOutput out;
    field({full_sphere()}, big).build(in, out);
    ASSERT_GT(out.count, 0);
    for (const auto& b : merged(out))
        for (const auto& g : b.items)
            EXPECT_GE(glm::length(glm::vec3(g.centre_half)), big.in_lo_gu);
}

TEST(MidTiles, WeightAndDitherFollowTheJitteredSprite) {   // final review 3
    // Every emitted sprite's dither is its level's at |sprite - eye|; the
    // level is found from the sprite's own tile size (0.5 T * 0.8..1.2 * 1.02).
    rockfield::MidDials d; d.max_sprites = 1000000;
    rockfield::MidOutput out;
    field({full_sphere()}, d).build(looking_along_y(120.0f), out);
    ASSERT_GT(out.count, 0);
    int checked = 0;
    for (const auto& b : merged(out))
        for (const auto& g : b.items) {
            const float dist = glm::length(glm::vec3(g.centre_half));
            const float half = g.centre_half.w / 1.02f;
            int lvl = -1;
            for (int l = 0; l < 3; ++l) {
                const float T = l == 0 ? d.l0_tile_gu : (l == 1 ? d.l1_tile_gu : d.l2_tile_gu);
                if (half >= 0.4f * T - 1e-2f && half <= 0.6f * T + 1e-2f) lvl = l;
            }
            ASSERT_GE(lvl, 0);
            EXPECT_GT(rockfield::mid_level_weight(lvl, dist, d), 0.0f) << dist;
            EXPECT_NEAR(g.axis_y_dither.w, rockfield::mid_level_dither(lvl, dist, d), 1e-3f) << dist;
            ++checked;
        }
    EXPECT_GT(checked, 100);
}

TEST(MidTiles, SpritesSizedFromTheirTile) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    rockfield::MidOutput out;
    field({full_sphere()}, d).build(looking_along_y(90.0f), out);
    ASSERT_GT(out.count, 0);
    // half = 0.5 * tile * scale * (0.8 + 0.4u), make_impostor pads by 1.02.
    const float lo = 0.5f * d.l0_tile_gu * 0.8f * 1.02f - 1e-3f;
    const float hi = 0.5f * d.l2_tile_gu * 1.2f * 1.02f + 1e-3f;
    for (const auto& b : merged(out))
        for (const auto& g : b.items) {
            EXPECT_GE(g.centre_half.w, lo);
            EXPECT_LE(g.centre_half.w, hi);
            EXPECT_GE(g.axis_y_dither.w, -1.0f); EXPECT_LE(g.axis_y_dither.w, 1.0f);
        }
}

TEST(MidTiles, CapKeepsTheNearest) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    const auto in = looking_along_y(90.0f);
    rockfield::MidOutput all;
    field({full_sphere()}, d).build(in, all);
    ASSERT_GT(all.count, 100);
    std::vector<float> dists;
    for (const auto& b : merged(all))
        for (const auto& g : b.items) dists.push_back(glm::length(glm::vec3(g.centre_half)));
    std::sort(dists.begin(), dists.end());

    d.max_sprites = 50;
    rockfield::MidOutput capped;
    field({full_sphere()}, d).build(in, capped);
    EXPECT_EQ(capped.count, 50);
    for (const auto& b : merged(capped))
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

    // Small tiles (a dial pushed down hard) stay bounded by the per-axis
    // cap: 10 GU tiles span at most 33 per axis, so every level reaches at
    // most 160 GU per axis -- tiles beyond in_lo (80) exist and emit, but
    // none of L0's 600, L1's 2,400 or L2's 8,000 GU reach survives.
    m.l0_tile_gu = 10.0f; m.l1_tile_gu = 10.0f; m.l2_tile_gu = 10.0f;
    rockfield::MidOutput tiny;
    field({full_sphere(1e6f)}, m).build(looking_along_y(1.0f), tiny);
    EXPECT_GT(tiny.tiles, 0);
    EXPECT_GT(tiny.count, 0);
    EXPECT_LE(tiny.count, 300);
    EXPECT_LE(tiny.tiles, 3 * 33 * 33 * 33);
    const float capped = 0.5f * 32.0f * 10.0f * std::sqrt(3.0f) + 0.25f * 10.0f * std::sqrt(3.0f);
    for (const auto& b : merged(tiny))
        for (const auto& g : b.items) EXPECT_LE(glm::length(glm::vec3(g.centre_half)), capped);
}

// ── Cluster snap (rock-fields Task 14 ruling) ─────────────────────────────────
// A SPHERE source with 2R < a level's tile is smaller than one tile: point
// sampling at tile centres would miss it (Beol 4's r 1,000 field in 2,400 GU
// L2 tiles), so the tile containing its centre "snaps" to it.
namespace {
far::DiscSource sphere_at(glm::dvec3 c, float r, std::uint32_t id = 21) {
    far::DiscSource s = full_sphere(r, id);
    s.centre = c;
    return s;
}
rockfield::MidBuildInput looking_at(glm::vec3 eye, glm::vec3 target, float fov_deg = 30.0f) {
    rockfield::MidBuildInput in;
    in.proj = glm::perspective(glm::radians(fov_deg), 1.0f, 0.01f, 1e7f);
    in.view = glm::lookAt(eye, target, glm::vec3(0, 0, 1));
    return in;
}
std::vector<far::ImpostorGpu> items_of(const rockfield::MidOutput& o) {
    std::vector<far::ImpostorGpu> v;
    for (const auto& b : merged(o)) v.insert(v.end(), b.items.begin(), b.items.end());
    return v;
}
// The pre-blend (before rock-blend, 2026-10-03) instance's view vec4s for
// `g`: the baked view nearest the eye among the six axis directions these
// digests were recorded with, its basis posed by the rock's rotation R --
// recovered from the new instance's rock axes (R = Q * gltf_to_bc(), Q's
// third column their cross product). So the digest below still pins
// everything the pre-blend build emitted: same sprites, places, sizes,
// rotations, dithers and order.
std::pair<glm::vec4, glm::vec4> legacy_view(const far::ImpostorGpu& g, const glm::vec3& eye) {
    const std::vector<glm::vec3> dirs = {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}};
    const glm::vec3 q0(g.axis_x_grid), q1(g.axis_y_dither);
    const glm::mat3 M = far::gltf_to_bc();
    const glm::mat3 R = glm::mat3(q0, q1, glm::cross(q0, q1)) * M;
    const glm::vec3 c(g.centre_half);
    const glm::vec3 to_eye = glm::transpose(R) * (eye - c);
    const float len = glm::length(to_eye);
    const glm::vec3 e_g = M * (len > 0.0f ? to_eye / len : glm::vec3(0, 0, 1));
    std::size_t best = 0;
    float best_dot = -2.0f;
    for (std::size_t i = 0; i < dirs.size(); ++i)
        if (glm::dot(dirs[i], e_g) > best_dot) { best_dot = glm::dot(dirs[i], e_g); best = i; }
    const far::ViewBasis b = far::make_view_basis(dirs[best]);
    return {glm::vec4(R * (M * b.right), static_cast<float>(best)), glm::vec4(R * (M * b.up), g.axis_y_dither.w)};
}

// Order-sensitive digest of a build (solid + translucent, merged in the
// build's order from `in`'s eye): atlas slots and every float of the
// pre-blend instance (legacy_view), rounded.
double digest(const rockfield::MidOutput& o, const rockfield::MidBuildInput& in) {
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    double h = 0.0, k = 1.0;
    for (const auto& b : merged(o, in)) {
        h += k * b.rock; k += 0.37;
        for (const auto& g : b.items) {
            const auto [right_view, up_dither] = legacy_view(g, eye);
            for (const glm::vec4* v : {&g.centre_half, &right_view, &up_dither})
                for (int i = 0; i < 4; ++i) { h += k * std::round((*v)[i] * 100.0) / 100.0; k += 0.013; }
        }
    }
    return h;
}
}  // namespace

TEST(MidSnap, SmallSphereInsideOneL2TileGetsOneSpriteAtItsCentre) {
    // r 600 (2R = 1,200 < 2,400): the L2 tile [0, 2400)^3 holds it, and its
    // tile centre (1200, 1200, 1200) lies 1,212 GU away -- outside the sphere.
    const glm::dvec3 c(500.0, 500.0, 500.0);
    const float r = 600.0f;
    const glm::vec3 eye = glm::vec3(c) + glm::vec3(0.0f, -6000.0f, 0.0f);
    rockfield::MidDials d;
    rockfield::MidOutput out;
    field({sphere_at(c, r)}, d).build(looking_at(eye, glm::vec3(c)), out);
    const auto items = items_of(out);
    ASSERT_EQ(items.size(), 1u) << "tiles " << out.tiles;
    const glm::vec3 p(items[0].centre_half);
    EXPECT_LE(glm::length(p - glm::vec3(c)), 0.25f * r * std::sqrt(3.0f) + 1e-2f);
    // half = R * scale * (0.8 + 0.4u), padded 1.02 by make_impostor.
    EXPECT_GE(items[0].centre_half.w, 0.8f * r * 1.02f - 1e-2f);
    EXPECT_LE(items[0].centre_half.w, 1.2f * r * 1.02f + 1e-2f);
    // Full density at the centre => a dense collection.
    const auto bins = merged(out);
    ASSERT_EQ(bins.size(), 1u);
    EXPECT_GE(bins[0].rock, 32);
    EXPECT_LE(bins[0].rock, 47);
}

TEST(MidSnap, ASnappedTileNeverPlacesTwo) {
    // The tile centre (1200, 1200, 1200) lies INSIDE this r 1,000 sphere, so
    // the centre-density path would place a sprite there too: the snap
    // replaces it.
    const glm::dvec3 c(1100.0, 1100.0, 1100.0);
    const float r = 1000.0f;
    const glm::vec3 eye = glm::vec3(c) + glm::vec3(0.0f, -6000.0f, 0.0f);
    rockfield::MidOutput out;
    field({sphere_at(c, r)}).build(looking_at(eye, glm::vec3(c)), out);
    const auto items = items_of(out);
    ASSERT_EQ(items.size(), 1u);
    EXPECT_LE(glm::length(glm::vec3(items[0].centre_half) - glm::vec3(c)),
              0.25f * r * std::sqrt(3.0f) + 1e-2f);
}

TEST(MidSnap, LevelWeightAndDitherFollowTheSpriteDistance) {
    const glm::dvec3 c(500.0, 500.0, 500.0);
    const float r = 600.0f;
    rockfield::MidDials d;
    // Past the hand-off: no level weight at the sprite => nothing.
    {
        const glm::vec3 eye = glm::vec3(c) + glm::vec3(0.0f, -9000.0f, 0.0f);
        rockfield::MidOutput out;
        field({sphere_at(c, r)}, d).build(looking_at(eye, glm::vec3(c)), out);
        EXPECT_EQ(out.count, 0);
    }
    // In L2's fade-out (7,000 GU): dithered fading out, +(1 - w).
    {
        const glm::vec3 eye = glm::vec3(c) + glm::vec3(0.0f, -7000.0f, 0.0f);
        rockfield::MidOutput out;
        field({sphere_at(c, r)}, d).build(looking_at(eye, glm::vec3(c)), out);
        const auto items = items_of(out);
        ASSERT_EQ(items.size(), 1u);
        // The snapped sprite's own drawn point (after the jitter), not the
        // tile's centre nor the source centre.
        const float dist = glm::length(glm::vec3(items[0].centre_half) - eye);
        EXPECT_NEAR(items[0].axis_y_dither.w, rockfield::mid_level_dither(2, dist, d), 1e-4f);
        EXPECT_GT(items[0].axis_y_dither.w, 0.0f);
    }
}

TEST(MidSnap, TheNearBandGuardStillApplies) {
    // r 50 (2R = 100 < 150): snaps at L0. With the eye 40 GU from the centre
    // (< in_lo 80) the near band owns it: no mid sprite.
    const glm::dvec3 c(1000.0, 1000.0, 1000.0);
    const glm::vec3 eye = glm::vec3(c) + glm::vec3(0.0f, -40.0f, 0.0f);
    rockfield::MidOutput out;
    field({sphere_at(c, 50.0f)}).build(looking_at(eye, glm::vec3(c), 90.0f), out);
    EXPECT_EQ(out.count, 0);
    // From 120 GU (in L0's range) it shows, once.
    const glm::vec3 eye2 = glm::vec3(c) + glm::vec3(0.0f, -300.0f, 0.0f);
    rockfield::MidOutput out2;
    field({sphere_at(c, 50.0f)}).build(looking_at(eye2, glm::vec3(c), 90.0f), out2);
    EXPECT_EQ(out2.count, 1);
}

TEST(MidSnap, LargeSpheresAndBeltsAreUnchanged) {
    // 2R >= every tile, and belts, never snap. The snap digest (s) was
    // recorded BEFORE the snap existed; a and b were re-recorded when the
    // guard, weight and dither moved from the tile-centre distance to the
    // jittered sprite's (final review 3) -- same tiles, same selection.
    // Pinned to the pre-2026-10-03 in_lo_gu/in_hi_gu defaults (80/150) so the
    // recorded digests below stay valid regardless of rock_mid.h's current
    // defaults.
    rockfield::MidDials d; d.max_sprites = 1000000;
    d.in_lo_gu = 80.0f; d.in_hi_gu = 150.0f;
    rockfield::MidOutput a, b, s;
    const auto in_a = looking_along_y(90.0f);
    const auto in_b = looking_along_y(90.0f, glm::vec3(5000, 0, 0));
    const glm::dvec3 c(1100.0, 1100.0, 1100.0);   // r 1,300: 2R = 2,600 > 2,400
    const auto in_s = looking_at(glm::vec3(c) + glm::vec3(0, -4000, 0), glm::vec3(c), 60.0f);
    field({full_sphere()}, d).build(in_a, a);
    field({flat_belt(0.3f)}, d).build(in_b, b);
    field({sphere_at(c, 1300.0f)}, d).build(in_s, s);
    std::printf("[mid snap digests] %.6f %.6f %.6f (counts %d %d %d)\n", digest(a, in_a),
                digest(b, in_b), digest(s, in_s), a.count, b.count, s.count);
    EXPECT_EQ(a.count, 254);
    EXPECT_EQ(b.count, 77);
    EXPECT_EQ(s.count, 1);
    EXPECT_NEAR(digest(a, in_a), 11570214.548270, 1e-3);
    EXPECT_NEAR(digest(b, in_b), 5412515.457730, 1e-3);
    EXPECT_NEAR(digest(s, in_s), 5293.574110, 1e-3);
}

// Rock fade (2026-10-03): EVERY mid fade -- L0 fading in, the level
// crossfades, L2 fading out -- is translucent (sprites_fading, alpha = the
// level weight, the dither coverage far::impostor_fade_alpha); only weight-1
// sprites stay in sprites, solid (dither exactly 0). Fading bins draw far to
// near: a fade band's bins before a nearer band's, each bin farthest first.
TEST(MidFade, EveryFadeIsTranslucentAndDrawsFarToNear) {
    rockfield::MidDials d; d.max_sprites = 1000000;
    rockfield::MidOutput out;
    field({full_sphere()}, d).build(looking_along_y(120.0f), out);
    int solid = 0, fading = 0;
    for (const auto& b : out.sprites)
        for (const auto& g : b.items) { ++solid; EXPECT_EQ(g.axis_y_dither.w, 0.0f); }
    // The far end of the fade band holding distance `dist`.
    const auto band_of = [&](float dist) {
        for (float e : {d.in_hi_gu, d.l0_out_gu, d.l1_out_gu, d.handoff_gu})
            if (dist <= e + 1e-2f) return e;
        return 1e30f;
    };
    float prev_band = 1e30f;
    for (const auto& b : out.sprites_fading) {
        ASSERT_FALSE(b.items.empty());
        const float band = band_of(glm::length(glm::vec3(b.items.front().centre_half)));
        EXPECT_LE(band, prev_band) << "a farther band's bins draw first";
        prev_band = band;
        float prev_d = 1e30f;
        for (const auto& g : b.items) {
            ++fading;
            const float dist = glm::length(glm::vec3(g.centre_half));
            EXPECT_EQ(band_of(dist), band) << "one band per bin";
            EXPECT_LE(dist, prev_d + 1e-3f) << "far to near within a bin";
            prev_d = dist;
            ASSERT_NE(g.axis_y_dither.w, 0.0f);
            const float half = g.centre_half.w / 1.02f;
            int lvl = -1;
            for (int l = 0; l < 3; ++l) {
                const float T = l == 0 ? d.l0_tile_gu : (l == 1 ? d.l1_tile_gu : d.l2_tile_gu);
                if (half >= 0.4f * T - 1e-2f && half <= 0.6f * T + 1e-2f) lvl = l;
            }
            ASSERT_GE(lvl, 0);
            const float w = rockfield::mid_level_weight(lvl, dist, d);
            EXPECT_GT(w, 0.0f); EXPECT_LT(w, 1.0f);
            EXPECT_NEAR(far::impostor_fade_alpha(g.axis_y_dither.w), w, 1e-3f) << dist;
        }
    }
    EXPECT_GT(solid, 0);
    EXPECT_GT(fading, 0);
    EXPECT_EQ(fading, out.fading);
    EXPECT_EQ(solid + fading, out.count);
}
