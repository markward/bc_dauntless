#include <renderer/particle_math.h>
#include <gtest/gtest.h>
#include <cmath>

using namespace renderer;

TEST(ParticleMath, CurveLerpClampsAndInterpolates) {
    float ts[3] = {0.0f, 0.5f, 1.0f};
    float vs[3] = {0.2f, 1.0f, 0.0f};
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, -1.0f), 0.2f);   // clamp low
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, 2.0f), 0.0f);    // clamp high
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, 0.25f), 0.6f);   // midpoint of [0.2,1.0]
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 0, 0.5f), 1.0f);    // no keys => 1.0
}

TEST(ParticleMath, MaxCountCeils) {
    EXPECT_EQ(particle_max_count(1.0f, 0.0f, 0.25f), 4);
    EXPECT_EQ(particle_max_count(1.0f, 0.5f, 0.5f), 3);   // (1.0+0.5)/0.5 = 3
    EXPECT_EQ(particle_max_count(1.0f, 0.0f, 0.0f), 1);   // degenerate freq
}

TEST(ParticleMath, SlotBirthAgeIsLatestBirthNotAfterNow) {
    float b = slot_birth_age(1.6f, /*i=*/0, /*n=*/4, /*f=*/0.25f);
    EXPECT_NEAR(b, 1.0f, 1e-5f);
    float b1 = slot_birth_age(1.6f, 1, 4, 0.25f);
    EXPECT_NEAR(b1, 1.25f, 1e-5f);
    EXPECT_LE(slot_birth_age(0.1f, 3, 4, 0.25f), 0.1f + 1e-5f);
}

TEST(ParticleMath, TrailTermAppearsOnlyWhenInheritBelowOne) {
    glm::vec3 emit{0, 0, 0};
    glm::vec3 dir{0, -1, 0};
    glm::vec3 vel{10, 0, 0};
    glm::vec3 p_full = particle_world_pos(emit, dir, vel, 2.0f, 1.0f, 0.5f);
    EXPECT_NEAR(p_full.x, 0.0f, 1e-5f);
    EXPECT_NEAR(p_full.y, -1.0f, 1e-5f);
    glm::vec3 p_lag = particle_world_pos(emit, dir, vel, 2.0f, 0.0f, 0.5f);
    EXPECT_NEAR(p_lag.x, -5.0f, 1e-5f);
    EXPECT_NEAR(p_lag.y, -1.0f, 1e-5f);
}

TEST(ParticleMath, ConeAndRadius) {
    const glm::vec3 axis{0.0f, -1.0f, 0.0f};
    const glm::vec2 h{0.3f, 0.7f};

    // Tight cone (0 deg) should return the axis itself.
    glm::vec3 tight = random_cone_dir(axis, 0.0f, h);
    EXPECT_NEAR(tight.x, axis.x, 1e-5f);
    EXPECT_NEAR(tight.y, axis.y, 1e-5f);
    EXPECT_NEAR(tight.z, axis.z, 1e-5f);

    // Full-sphere cone should produce a unit vector.
    glm::vec3 full = random_cone_dir(axis, 180.0f, h);
    EXPECT_NEAR(glm::length(full), 1.0f, 1e-5f);

    // A half-hemisphere cone should also produce a unit vector.
    glm::vec3 hemi = random_cone_dir(axis, 90.0f, glm::vec2{0.5f, 0.25f});
    EXPECT_NEAR(glm::length(hemi), 1.0f, 1e-5f);

    // emit_radius_offset with radius==0 must return zero.
    glm::vec3 zero_off = emit_radius_offset(0.0f, h, 42);
    EXPECT_NEAR(glm::length(zero_off), 0.0f, 1e-9f);

    // emit_radius_offset with radius==5 must stay within the sphere.
    glm::vec3 off = emit_radius_offset(5.0f, h, 42);
    EXPECT_LE(glm::length(off), 5.0f + 1e-5f);

    // Multiple salts decorrelate (lengths differ for same h).
    glm::vec3 off2 = emit_radius_offset(5.0f, h, 99);
    // They won't be identical (unless the hash happens to collide, which it won't
    // for these salts).
    EXPECT_GT(std::abs(glm::length(off) - glm::length(off2)), 1e-6f);
}

TEST(ParticleMath, DampedTravel) {
    EXPECT_FLOAT_EQ(damped_travel(2.0f, 0.0f, 0.5f), 1.0f);   // c=0 => linear v*tau
    float t1 = damped_travel(2.0f, 1.0f, 0.5f);
    float t2 = damped_travel(2.0f, 1.0f, 1.0f);
    EXPECT_LT(t1, 1.0f);            // below linear (2*0.5)
    EXPECT_GT(t2, t1);             // monotonic
    EXPECT_LT(t2, 2.0f);          // bounded by v/c = 2.0
    EXPECT_NEAR(damped_travel(2.0f, 1.0f, 100.0f), 2.0f, 1e-2f);  // asymptote v/c
}

TEST(ParticleMath, StreakQuadDegeneratesAndAligns) {
    glm::vec3 center{0, 0, 0};
    glm::vec3 axis{0, 1, 0};
    glm::vec3 cam_right{1, 0, 0};
    glm::vec3 cam_up{0, 0, 1};
    auto sq = streak_quad(center, axis, /*length=*/0.0f, /*half_width=*/0.5f, cam_right, cam_up);
    // corner 0 is (-1,-1) => center - cam_right*0.5 - cam_up*0.5 = (-0.5, 0, -0.5)
    EXPECT_NEAR(sq[0].x, -0.5f, 1e-5f);
    EXPECT_NEAR(sq[0].z, -0.5f, 1e-5f);
    auto st = streak_quad(center, axis, /*length=*/2.0f, /*half_width=*/0.1f, cam_right, cam_up);
    // long edge (corner 2 - corner 1) runs along `axis`
    glm::vec3 long_edge = st[2] - st[1];
    EXPECT_GT(std::abs(glm::dot(glm::normalize(long_edge), axis)), 0.9f);
}

// Sprite sheets are sampled through one LOD chain computed from the WHOLE
// texture, so a shrinking puff eventually lands on mips where a single cell is
// a couple of texels: neighbouring cells bleed in and the sheet averages to a
// flat wash, turning the quad into a uniform translucent square. Clamp the
// chain so a cell never falls below min_cell_texels.
TEST(ParticleMath, AtlasMaxMipLevelClampsSheetsAndLeavesPlainTexturesAlone) {
    // ExplosionA/B: 256x256 at 8x8 => 32-texel cells. Level 3 is a 4-texel
    // cell; levels 4-7 (where the whole sheet washes out) become unsamplable.
    EXPECT_EQ(atlas_max_mip_level(256, 256, 8, 8), 3);

    // Non-atlas emitters must actively RESTORE the GL default, not inherit a
    // clamp left on the texture object by an earlier atlas emitter.
    EXPECT_EQ(atlas_max_mip_level(256, 256, 1, 1), 1000);
    EXPECT_EQ(atlas_max_mip_level(256, 256, 0, 0), 1000);

    // A cell already at the floor gets level 0, never a negative level.
    EXPECT_EQ(atlas_max_mip_level(32, 32, 8, 8), 0);
    EXPECT_EQ(atlas_max_mip_level(16, 16, 8, 8), 0);

    // Non-square sheets take the smaller cell dimension: 256/8=32 vs 128/8=16.
    EXPECT_EQ(atlas_max_mip_level(256, 128, 8, 8), 2);
}
