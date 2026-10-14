// Running lights: blink curve + size clamp (running-lights spec §4.4).
#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "renderer/running_light_math.h"

using renderer::running_light_blink_alpha;
using renderer::running_light_world_size;

TEST(RunningLightBlink, StaticIsAlwaysOn) {
    for (float t : {0.0f, 0.3f, 1.7f, 2.9f, 100.0f})
        EXPECT_FLOAT_EQ(running_light_blink_alpha(t, 3.0f, 0.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, DegenerateTimingIsAlwaysOnNeverNaN) {
    const float cases[][2] = {{0.0f, 1.0f}, {-3.0f, 1.0f}, {3.0f, 3.0f}, {3.0f, 5.0f},
                              {std::numeric_limits<float>::quiet_NaN(), 1.0f}};
    for (const auto& c : cases) {
        const float a = running_light_blink_alpha(1.25f, c[0], c[1], 0.0f);
        EXPECT_FALSE(std::isnan(a));
        EXPECT_FLOAT_EQ(a, 1.0f);
    }
}

TEST(RunningLightBlink, OnForDurationOffForRestWithTenPercentRamps) {
    // Period 3, Duration 1: ramp up over [0, 0.1], hold to 0.9, ramp down to 1.0.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.0f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.05f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f,  3.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.95f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(1.5f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.99f, 3.0f, 1.0f, 0.0f), 0.0f);
    // Next period repeats.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(3.5f,  3.0f, 1.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, PhaseShiftsTheWindow) {
    // Phase 1.0 s: game time 2.5 reads as 3.5 -> 0.5 into the next period: on.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.5f, 3.0f, 1.0f, 1.0f), 1.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f, 3.0f, 1.0f, 1.0f), 0.0f);
}

TEST(RunningLightBlink, LargePhaseAndTimeStayInRange) {
    const float a = running_light_blink_alpha(100000.25f, 3.0f, 1.0f, 999.0f);
    EXPECT_GE(a, 0.0f);
    EXPECT_LE(a, 1.0f);
}

TEST(RunningLightSize, WorldSizeWinsUpClose) {
    // proj11 = 1/tan(30 deg) for a 60 deg vertical fov; 1080 px tall.
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, 1.0f, proj11, 1080);
    EXPECT_NEAR(d, 0.03f, 1e-6f);
}

TEST(RunningLightSize, MinPixelFloorWinsFarAway) {
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float dist = 500.0f;
    const float per_px = 2.0f * dist / (proj11 * 1080.0f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, dist, proj11, 1080);
    EXPECT_NEAR(d, 1.5f * per_px, 1e-4f);
    EXPECT_GT(d, 0.03f);
}

TEST(RunningLightSize, DegenerateViewportFallsBackToWorldSize) {
    EXPECT_NEAR(running_light_world_size(1.0f, 0.02f, 1.5f, 10.0f, 0.0f, 0), 0.02f, 1e-6f);
}

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <scenegraph/world.h>

#include "renderer/running_light_store.h"

using renderer::RunningLight;
using renderer::RunningLightDials;
using renderer::RunningLightStore;

namespace {

// T * R * S with R = 90 deg about +Z (body +X -> world +Y), uniform scale s.
glm::mat4 rl_world(const glm::vec3& t, float s) {
    glm::mat4 m = glm::translate(glm::mat4(1.0f), t);
    m = glm::rotate(m, glm::radians(90.0f), glm::vec3(0, 0, 1));
    return glm::scale(m, glm::vec3(s));
}

RunningLight static_light(glm::vec3 body, glm::vec3 rgb) {
    RunningLight l; l.body_pos = body; l.rgb = rgb;
    l.size = 1.5f; l.period = 3.0f; l.duration = 0.0f;
    return l;
}

}  // namespace

TEST(RunningLightStore, UnlistedOrAbsentLevelIsZero) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    EXPECT_FLOAT_EQ(s.level(a), 0.0f);           // no levels pushed yet
    s.set_levels({{a, 0.75f}});
    EXPECT_FLOAT_EQ(s.level(a), 0.75f);
    s.set_levels({});                            // unlisted this frame
    EXPECT_FLOAT_EQ(s.level(a), 0.0f);
}

TEST(RunningLightStore, EmptySetEraseAndClear) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    const auto b = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set(b, {static_light({1, 0, 0}, {0, 1, 0})}, 0.0f);
    EXPECT_EQ(s.size(), 2u);
    s.set(a, {}, 0.0f);
    EXPECT_EQ(s.size(), 1u);
    s.erase(b);
    EXPECT_EQ(s.size(), 0u);
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.clear();
    EXPECT_EQ(s.size(), 0u);
}

TEST(RunningLightStore, ResetLightsReplaceNotAppend) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0}), static_light({2, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set(a, {static_light({3, 0, 0}, {0, 0, 1})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    world.set_world_transform(a, glm::mat4(1.0f));
    const auto sprites = s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, -10}, 0.0f, 0);
    ASSERT_EQ(sprites.size(), 1u);
}

TEST(RunningLightStore, SpritesFollowTheHullTransformWithScaleDividedOut) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, rl_world({10, 20, 30}, 2.5f));
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0.5f, 0})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    RunningLightDials dials;  // intensity 4
    const auto sprites = s.build_sprites(world, 0.0f, dials, {0, 0, 0}, 0.0f, 0);
    ASSERT_EQ(sprites.size(), 1u);
    EXPECT_NEAR(sprites[0].world_pos.x, 10.0f, 1e-4f);
    EXPECT_NEAR(sprites[0].world_pos.y, 21.0f, 1e-4f);   // body +X -> world +Y, unscaled
    EXPECT_NEAR(sprites[0].world_pos.z, 30.0f, 1e-4f);
    EXPECT_NEAR(sprites[0].color.r, 4.0f, 1e-5f);
    EXPECT_NEAR(sprites[0].color.g, 2.0f, 1e-5f);
    EXPECT_NEAR(sprites[0].half_size, 0.5f * 1.5f * 0.02f, 1e-6f);
}

TEST(RunningLightStore, LevelAndBlinkScaleColourAndDarkLightsAreDropped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, glm::mat4(1.0f));
    RunningLight blinker = static_light({0, 0, 0}, {1, 1, 1});
    blinker.duration = 1.0f;   // on 0.1..0.9 of each 3 s period
    RunningLightStore s;
    s.set(a, {blinker}, 0.0f);
    s.set_levels({{a, 0.5f}});
    auto on = s.build_sprites(world, 0.5f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0);
    ASSERT_EQ(on.size(), 1u);
    EXPECT_NEAR(on[0].color.r, 4.0f * 0.5f, 1e-5f);
    EXPECT_TRUE(s.build_sprites(world, 2.0f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).empty());
    s.set_levels({{a, 0.0f}});
    EXPECT_TRUE(s.build_sprites(world, 0.5f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).empty());
}

TEST(RunningLightStore, DestroyedInstanceIsSkipped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    world.destroy_instance(a);
    EXPECT_TRUE(s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, 0}, 0.0f, 0).empty());
}

TEST(RunningLightStore, SpriteCountIsCapped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, glm::mat4(1.0f));
    std::vector<RunningLight> many(renderer::kMaxRunningLightSprites + 50,
                                   static_light({0, 0, 0}, {1, 1, 1}));
    RunningLightStore s;
    s.set(a, many, 0.0f);
    s.set_levels({{a, 1.0f}});
    EXPECT_EQ(s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).size(),
              renderer::kMaxRunningLightSprites);
}

TEST(RunningLightStore, NonFiniteOrNegativeLevelDrawsNothing) {
    // std::clamp passes NaN straight through, and NaN <= 0 is false, so a NaN
    // level used to survive build_sprites' "level <= 0" skip.
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, glm::mat4(1.0f));
    RunningLightStore s;
    s.set(a, {static_light({0, 0, 0}, {1, 1, 1})}, 0.0f);
    for (float bad : {std::numeric_limits<float>::quiet_NaN(), -0.5f}) {
        s.set_levels({{a, bad}});
        EXPECT_FLOAT_EQ(s.level(a), 0.0f);
        EXPECT_TRUE(s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0)
                        .empty());
    }
    s.set_levels({{a, 7.0f}});
    EXPECT_FLOAT_EQ(s.level(a), 1.0f);
}

TEST(RunningLightDials, DefaultsMatchTheSpec) {
    // Spec §4.5 start values; min_px 2.5 so a floored sprite centred on a pixel
    // corner still lights its neighbours (final review I2).
    const RunningLightDials d;
    EXPECT_FLOAT_EQ(d.size_gu_per_radius, 0.02f);
    EXPECT_FLOAT_EQ(d.min_px, 2.5f);
    EXPECT_FLOAT_EQ(d.intensity, 4.0f);
}
