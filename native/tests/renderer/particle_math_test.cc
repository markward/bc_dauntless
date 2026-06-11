#include <renderer/particle_math.h>
#include <gtest/gtest.h>

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
